#!/usr/bin/env python3
"""自律コンテンツパイプライン(2026-11-13 owner依頼。同日「承認は不要、サブエージェントが承認すれば公開」)。

段:
  monitor   公式情報源を WebSearch で確認(claude -p)→ 新しい項目を content/queue.tsv に追加
  process   NEW の項目ごとに
              執筆(claude -p, writer)→ WP 下書き作成 → ファクトチェック(claude -p, 別文脈)
              → publish-validate → 承認(claude -p, 別文脈)→ 公開 → 本番ページを再検査
              → GSC 再インデックス申請 + IndexNow → X 投稿(URL 位置は A/B の勝者、未決なら A/B 割当)
  xretry    上限・間隔で見送った X 投稿を再試行
  run       monitor → process → xretry(cron はこれを2時間ごとに呼ぶ)

人の承認は挟まない代わりに、機械の歯止めを置く:
  - content/STOP があれば何もしない
  - 公開は1日 CONTENT_PIPELINE_DAILY_PUBLISH 本まで(既定4)、claude -p の費用は1日 $CONTENT_PIPELINE_DAILY_USD まで(既定10)
  - ファクトチェックは日付/時刻/名前/プラットフォームの全主張に一次情報2つ以上を要求し、
    本文中の日付・時刻トークンが検証済み主張に含まれているかをコードでも照合する
  - 公開後に本番HTMLで publish-validate --live を走らせ、落ちたら即下書きへ戻す
  - 既存ハブと同じ検索意図の項目は新記事にせず HUB_UPDATE として通知だけする(カニバリ防止)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.content_pipeline import common as C  # noqa: E402
from tools.content_pipeline.publish_validate import validate  # noqa: E402
from tools.content_pipeline.watchlist import build as build_watchlist, recent_titles  # noqa: E402

PROMPTS = Path(__file__).resolve().parent / "prompts"
MAX_ITEMS_PER_RUN = 2
X_MIN_GAP_MIN = 30          # パイプライン発の X 投稿は直前の投稿から30分以上空ける(連投=シャドウバン主因)
FC_TYPES = ("date", "time", "name", "platform")
DRY = False   # --dry: 承認判定まで行い、公開・X はしない(試運転用)


def _prompt(name: str, **kw) -> str:
    t = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in kw.items():
        t = t.replace("{" + k + "}", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1))
    return t


def _style() -> str:
    return (PROMPTS / "style.md").read_text(encoding="utf-8")


def _plain(html_text: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    t = re.sub(r"</(p|h2|h3|li|tr)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", html.unescape(t)).strip()


# ================================================================ monitor
def monitor() -> int:
    if C.stopped():
        return 0
    w = build_watchlist()
    with C.queue_lock():
        rows = C.read_queue()
    known = sorted({r["note"].split("key=", 1)[1].split(" ")[0] for r in rows if "key=" in r["note"]})
    titles = recent_titles()
    watch = {"artists": w["artists"],
             "events": [e for e in w["events"] if not e.get("handled_elsewhere")],
             "dramas": w["dramas"]}
    prompt = _prompt("monitor", TODAY=date.today().isoformat(), NOW=datetime.now().strftime("%H:%M"),
                     WATCHLIST=watch, KNOWN_KEYS="\n".join(known) or "(なし)",
                     RECENT_TITLES="\n".join(titles))
    out = C.run_claude("monitor", prompt, allowed_tools=["WebSearch", "WebFetch"], budget_usd=1.5,
                       timeout=1500)
    items = C.extract_json(out).get("items", [])
    added = 0
    handled = list(w["handled_elsewhere"])
    with C.queue_lock():
        rows = C.read_queue()
        have = {r["note"].split("key=", 1)[1].split(" ")[0] for r in rows if "key=" in r["note"]}
        next_id = max([int(r["id"]) for r in rows] + [0]) + 1
        for it in items:
            key = re.sub(r"\s+", "", str(it.get("key", "")))
            urls = [u for u in it.get("source_urls", []) if str(u).startswith("http")]
            if not key or key in have or not urls or it.get("kind") not in (
                    "lineup", "award_result", "streaming_date"):
                continue
            if any(h in (it.get("subject", "") + it.get("claim", "")) for h in handled):
                continue
            status = "HUB_UPDATE" if (it.get("hub_post_id") and it.get("same_intent_as_hub")) else "NEW"
            rows.append({"id": str(next_id), "detected_at": C.now(), "kind": it["kind"],
                         "subject": it.get("subject", ""), "claim": it.get("claim", ""),
                         "event_date": it.get("event_date", ""), "source_urls": " ".join(urls),
                         "hub_post_id": str(it.get("hub_post_id") or ""), "status": status,
                         "post_id": "", "updated_at": C.now(), "note": f"key={key}"})
            have.add(key)
            if status == "HUB_UPDATE":
                C.notify("[content] 既存ハブへの追記候補",
                         f"#{next_id} post {it['hub_post_id']} ← {it.get('claim', '')[:120]} ({urls[0]})",
                         key=f"hub_{next_id}")
            next_id += 1
            added += 1
        C.write_queue(rows)
    C.log_event("monitor", found=len(items), added=added)
    print(f"[monitor] 発見 {len(items)} / 追加 {added}")
    return added


# ================================================================ draft
def _hub_links() -> str:
    try:
        d = json.loads((C.BASE / "config" / "artist_hub_links.json").read_text(encoding="utf-8"))
        today = date.today().isoformat()
        return "\n".join(f"- {l['title']} {l['url']}" for l in d["links"]
                         if not l.get("until") or l["until"] >= today)
    except (OSError, ValueError, KeyError):
        return ""


def render_faq(faq: list[dict]) -> str:
    """可視 FAQ と FAQPage JSON-LD を同じデータから組む(食い違いを構造的に起こさない)。"""
    faq = [f for f in faq if str(f.get("q", "")).strip() and str(f.get("a", "")).strip()]
    if not faq:
        raise ValueError("faq が空")
    vis = ['<h2>よくある質問</h2>', '<div class="kpj-faq">']
    for f in faq:
        vis.append(f"<h3>{html.escape(f['q'].strip())}</h3>\n<p>{html.escape(f['a'].strip())}</p>")
    vis.append("</div>")
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": f["q"].strip(),
                          "acceptedAnswer": {"@type": "Answer", "text": f["a"].strip()}} for f in faq]}
    # JSON 内の "</" は script を閉じてしまうのでエスケープ
    js = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return "\n".join(vis) + f'\n<script type="application/ld+json">{js}</script>'


def _category_ids(cat: str) -> list[int]:
    if cat == "kdrama":
        return [19]
    try:
        from lib.unified_publisher import _fetch_category_id
        cid = _fetch_category_id("event" if cat == "event" else "news")
        return [cid] if cid else []
    except Exception:  # noqa: BLE001
        return []


def _thumbnail(art: dict, source_urls: list[str]) -> int | None:
    """公式情報源の og:image → アーティスト写真。DALL-E は使わない(誤画像より無画像)。"""
    import tempfile
    from lib.unified_publisher import _upload_media
    with tempfile.TemporaryDirectory(prefix="kpj_cp_") as td:
        out = str(Path(td) / "og.jpg")
        for u in source_urls[:3]:
            try:
                from lib.thumbnail_resolver import fetch_source_image
                if fetch_source_image(u, out):
                    mid = _upload_media(out, alt_text=f"{art['title']}のサムネイル画像",
                                        expected_artist=art.get("artist", ""), article_title=art["title"])
                    if mid:
                        return mid
            except Exception:  # noqa: BLE001
                continue
        if art.get("artist"):
            try:
                from lib.image_utils import aspect_preserve_resize
                from lib.thumbnail_source_resolver import resolve
                r = resolve(artist_name=art["artist"], article_type="concrete", article_title=art["title"])
                if r and r.get("image_path") and Path(r["image_path"]).exists():
                    p = str(Path(td) / "artist.jpg")
                    aspect_preserve_resize(r["image_path"], p)
                    return _upload_media(p, alt_text=f"{art['title']}のサムネイル画像",
                                         expected_artist=art["artist"], article_title=art["title"])
            except Exception:  # noqa: BLE001
                pass
    return None


def draft(item: dict) -> dict:
    prompt = _prompt("writer", TODAY=date.today().isoformat(), STYLE=_style(), LINKS=_hub_links(),
                     ITEM={k: item[k] for k in ("kind", "subject", "claim", "event_date", "source_urls",
                                                 "hub_post_id")})
    out = C.run_claude("writer", prompt, allowed_tools=["WebSearch", "WebFetch"], budget_usd=1.5)
    art = C.extract_json(out)
    for k in ("title", "description", "body_html", "faq"):
        if not art.get(k):
            raise ValueError(f"writer の出力に {k} が無い")
    # タイトル/description はタグを含めない(素のテキストとして扱う)
    art["title"] = re.sub(r"<[^>]*>", "", html.unescape(art["title"])).strip()
    art["description"] = re.sub(r"<[^>]*>", "", html.unescape(art["description"])).strip()
    # 本文は許可リストで組み直す(外部ページ経由のインジェクションで script 等が混ざっても通さない)
    from tools.content_pipeline.sanitize import sanitize
    body, removed = sanitize(art["body_html"].strip())
    if removed:
        C.log_event("sanitized", id=item["id"], removed=removed[:30])
    if any(r.startswith(("<script", "<iframe", "<object", "<embed", "<form", "href=")) or "[on" in r
           for r in removed):
        # 危険な要素が出てきた時点で、出力全体を信用しない(素直な執筆なら出ない)
        raise ValueError(f"writer の本文に危険な要素: {removed[:5]}")
    # 出典段落の直前に FAQ を置く(無ければ末尾)
    faq_html = render_faq(art["faq"])
    i = body.rfind('<p class="kpj-sources"')
    body = (body[:i] + faq_html + "\n" + body[i:]) if i >= 0 else (body + "\n" + faq_html)
    art["content"] = body
    (C.DRAFTS / f"{item['id']}.json").write_text(json.dumps(art, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")

    data = {"title": art["title"], "content": body, "status": "draft", "excerpt": art["description"],
            "categories": _category_ids(art.get("category", "news"))}
    if re.fullmatch(r"[a-z0-9\-]{3,80}", art.get("slug", "")):
        data["slug"] = art["slug"]
    p = C.wp("POST", "/posts", data)
    pid = int(p["id"])
    # description は wp_aioseo_posts に書いて DB 実値で検証([[aioseo-desc-write-traps]])
    from tools.backfill_aioseo_description import set_description_for_post
    set_description_for_post(pid, art["description"])
    mid = _thumbnail(art, item["source_urls"].split())
    if mid:
        C.wp("POST", f"/posts/{pid}", {"featured_media": mid})
    art["post_id"], art["featured_media"] = pid, mid
    return art


# ================================================================ factcheck
DATE_TOKEN = re.compile(r"\d{1,2}月\d{1,2}日|(?<![0-9A-Za-z])\d{1,2}:\d{2}(?!\d)|\d{4}年"
                        r"|(?<![0-9A-Za-z/])\d{1,2}/\d{1,2}(?![0-9/])")
_SLD = {"co", "ne", "or", "go", "ac", "ed", "lg", "com", "net", "org", "gov", "edu"}


def _publisher(src: dict) -> str:
    """一次情報の発信元。publisher 名があればそれ(同じ組織の別ページは1つと数える)、無ければ登録ドメイン。"""
    pub = re.sub(r"[\s　・.()（）]|公式|株式会社|official", "", str(src.get("publisher", "")).lower())
    if pub:
        return pub
    host = urlparse(str(src.get("url", ""))).netloc.lower().split(":")[0]
    parts = host.split(".")
    n = 3 if len(parts) >= 3 and parts[-2] in _SLD else 2
    return ".".join(parts[-n:])


def judge_factcheck(fc: dict, body_text: str) -> list[str]:
    """ファクトチェック結果を機械で判定する。問題の一覧(空なら合格)。"""
    probs = []
    claims = fc.get("claims") or []
    if not claims:
        return ["ファクトチェックの claims が空"]
    for d in fc.get("discrepancies") or []:
        probs.append(f"食い違い: {d}")
    confirmed_text = ""
    for c in claims:
        st, typ = c.get("status"), c.get("type")
        srcs = c.get("primary_sources") or []
        domains = {_publisher(s) for s in srcs if str(s.get("url", "")).startswith("http")}
        if st != "confirmed":
            probs.append(f"[{typ}] {st}: {c.get('text', '')[:60]} {c.get('note', '')[:80]}")
        elif typ in FC_TYPES and len(domains) < 2:
            probs.append(f"[{typ}] 一次情報の発信元が {len(domains)} つのみ(別々の2つ以上が必要): {c.get('text', '')[:60]}")
        else:
            confirmed_text += " " + str(c.get("text", ""))
    # 検証漏れ: 本文の日付・時刻トークンは、検証済みの主張のどれかに含まれていなければならない
    norm = re.sub(r"\s+", "", confirmed_text)
    for tok in sorted(set(DATE_TOKEN.findall(body_text))):
        if tok not in norm:
            probs.append(f"検証漏れ: 本文の「{tok}」を含む主張が検証済みに無い")
    return probs


def factcheck(item: dict, art: dict) -> tuple[dict, list[str]]:
    body = _plain(art["content"])
    prompt = _prompt("factcheck", TODAY=date.today().isoformat(), TITLE=art["title"],
                     DESCRIPTION=art["description"], BODY=body)
    out = C.run_claude("factcheck", prompt, allowed_tools=["WebSearch", "WebFetch"], budget_usd=2.5,
                       timeout=1800)
    fc = C.extract_json(out)
    probs = judge_factcheck(fc, body + " " + art["title"] + " " + art["description"])
    fc["_problems"] = probs
    (C.FACTCHECK / f"{item['id']}.json").write_text(json.dumps(fc, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
    return fc, probs


# ================================================================ approve
def approve(item: dict, art: dict, fc: dict, val: dict) -> dict:
    prompt = _prompt("approver", TODAY=date.today().isoformat(), STYLE=_style(),
                     ITEM={k: item[k] for k in ("kind", "subject", "claim", "event_date", "source_urls",
                                                 "hub_post_id")},
                     TITLE=art["title"], DESCRIPTION=art["description"], BODY=_plain(art["content"]),
                     FACTCHECK=fc, VALIDATE=val, RECENT_TITLES="\n".join(recent_titles()))
    out = C.run_claude("approver", prompt, allowed_tools=["WebSearch"], budget_usd=1.0)
    d = C.extract_json(out)
    (C.APPROVALS / f"{item['id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
    return d


# ================================================================ publish
def published_today() -> int:
    today = date.today().isoformat()
    n = 0
    if C.PIPELINE_LOG.exists():
        for line in C.PIPELINE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("stage") == "published" and e.get("ts", "").startswith(today):
                n += 1
    return n


def publish(item: dict, pid: int) -> bool:
    p = C.wp("POST", f"/posts/{pid}", {"status": "publish"})
    url = p["link"]
    time.sleep(8)
    live = validate(pid, live=True)
    if not live["ok"]:
        C.wp("POST", f"/posts/{pid}", {"status": "draft"})
        C.update_item(item["id"], status="LIVE_FAIL", note=item["note"] + " live:" + "; ".join(live["errors"])[:300])
        C.notify("[content] 公開後の検査で落ちたので下書きに戻しました",
                 f"#{item['id']} post {pid}: {'; '.join(live['errors'])[:300]}", 0xE74C3C, key=f"livefail_{pid}")
        C.log_event("live_fail", id=item["id"], post_id=pid, errors=live["errors"])
        return False
    C.log_event("published", id=item["id"], post_id=pid, url=url)
    # 再インデックス: Google(Indexing API)と Bing ほか(IndexNow)。流入の主力は Bing。
    try:
        from lib.gsc_indexing import notify_url_updated
        g = notify_url_updated(url)
    except Exception as e:  # noqa: BLE001
        g = {"error": str(e)}
    try:
        from lib.indexnow import submit
        inow = submit([url])
    except Exception as e:  # noqa: BLE001
        inow = (0, str(e))
    C.log_event("reindex", id=item["id"], url=url, gsc=str(g)[:200], indexnow=str(inow)[:200])
    C.update_item(item["id"], status="PUBLISHED", post_id=str(pid))
    return True


# ================================================================ X
URL_POS_STATE = C.BASE / "data" / "x_url_pos_state.json"


def placement() -> tuple[str, str]:
    """(配置, 理由)。A/B の勝者が state に記録されていればそれ、未決なら既存の A/B 割当に従う。

    11/6 開始の URL 位置 A/B は各腕15本で判定する約束(memory x-url-position-ab-20261106)。
    11/13 時点 reply 5 / body 4 で未決のため、勝者が書かれるまでは A/B を進める側に回す
    (ここで片方に寄せると A/B 自体が壊れる)。
    """
    try:
        st = json.loads(URL_POS_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if st.get("winner") in ("reply", "body"):
        return st["winner"], f"A/B勝者({st.get('decided_at', '')})"
    from pipeline.x_scheduled_poster import _next_url_pos
    return _next_url_pos(), "A/B未決のため割当(少ない側)"


def _x_cron_active() -> bool:
    """x_auto_repause_guard は悪化時に X の cron 行をコメントアウトして止める。止まっていれば投稿しない。"""
    import subprocess
    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    return any("pipeline.x_scheduled_poster" in l and not l.lstrip().startswith("#")
               for l in cron.splitlines())


def post_x(item: dict) -> str:
    """戻り値: X_DONE / X_DEFERRED / X_SKIPPED

    既存の X 運用ルールにそのまま従う: URL 付き投稿は Phase3 以上かつ記事帯(8/12/15時)だけ・
    1日の総投稿上限・直前投稿から30分空ける・repause ガードが止めていれば出さない。
    条件が合わなければ見送り(X_DEFERRED)、次の回で再試行。36時間を過ぎたら諦める。
    """
    from lib.x_phase import get_phase
    from pipeline.x_scheduled_poster import (ARTICLE_HOURS, DAILY_POST_CAP, _last_post_time,
                                             _posts_today)
    pid = int(item["post_id"])
    try:
        age_h = (datetime.now() - datetime.fromisoformat(item["updated_at"])).total_seconds() / 3600
    except ValueError:
        age_h = 0
    if item["status"] == "X_DEFERRED" and age_h > 36:
        return "X_SKIPPED"
    if not _x_cron_active() or get_phase() < 3:
        return "X_DEFERRED"
    if datetime.now().hour not in ARTICLE_HOURS:
        return "X_DEFERRED"
    if _posts_today() >= DAILY_POST_CAP:
        return "X_DEFERRED"
    if (datetime.now() - _last_post_time()).total_seconds() < X_MIN_GAP_MIN * 60:
        return "X_DEFERRED"
    p = C.wp("GET", f"/posts/{pid}?_fields=link,title,status")
    if p["status"] != "publish":
        return "X_SKIPPED"
    pos, why = placement()
    from lib.x_phase import with_utm
    from lib.x_poster import post_hook_and_reply
    title = html.unescape(p["title"]["rendered"])
    r = post_hook_and_reply(title, with_utm(p["link"], "x_pipeline", pos), post_id=pid,
                            genre="pipeline", artist="", require_concrete=True, url_position=pos)
    if r.get("queued"):
        return "X_DEFERRED"
    if not r.get("success"):
        C.log_event("x_fail", id=item["id"], post_id=pid, error=str(r.get("error"))[:200])
        C.update_item(item["id"], note=item["note"] + f" x_err={str(r.get('error'))[:80]}")
        return "X_SKIPPED"
    used = r.get("url_pos", pos)
    rec = {"ts": datetime.now().isoformat(), "tweet_id": r.get("tweet_id"), "reply_id": r.get("reply_id"),
           "variant": r.get("variant"), "post_id": pid, "title": title[:120], "genre": "pipeline",
           "mode": r.get("mode", "hook_reply"), "url_pos": used}
    # 既存 A/B の集計(x_auto_repause_guard / _next_url_pos)に数えるため同じログへも書く
    with open(C.BASE / "logs" / "x_ab_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    new = not C.PLACEMENT_LOG.exists()
    with C.PLACEMENT_LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("ts\tqueue_id\tpost_id\turl_pos\treason\ttweet_id\treply_id\turl\n")
        f.write(f"{rec['ts']}\t{item['id']}\t{pid}\t{used}\t{why}\t{rec['tweet_id']}\t"
                f"{rec['reply_id'] or ''}\t{p['link']}\n")
    C.log_event("x_posted", id=item["id"], post_id=pid, url_pos=used, reason=why)
    return "X_DONE"


# ================================================================ process
def process_one(item: dict) -> str:
    iid = item["id"]
    C.update_item(iid, status="DRAFTING")
    art = draft(item)
    pid = art["post_id"]
    C.update_item(iid, status="DRAFTED", post_id=str(pid))
    item = C.get_item(iid)

    fc, probs = factcheck(item, art)
    if probs:
        C.update_item(iid, status="FACTCHECK_FAIL", note=item["note"] + " fc:" + "; ".join(probs)[:400])
        C.log_event("factcheck_fail", id=iid, post_id=pid, problems=probs)
        return "FACTCHECK_FAIL"

    val = validate(pid)
    if not val["ok"]:
        C.update_item(iid, status="VALIDATE_FAIL", note=item["note"] + " val:" + "; ".join(val["errors"])[:400])
        C.log_event("validate_fail", id=iid, post_id=pid, errors=val["errors"])
        return "VALIDATE_FAIL"

    C.update_item(iid, status="READY")
    ap = approve(item, art, fc, val)
    if ap.get("decision") != "APPROVE":
        C.update_item(iid, status="REJECTED", note=item["note"] + " ap:" + "; ".join(ap.get("reasons", []))[:400])
        C.log_event("rejected", id=iid, post_id=pid, reasons=ap.get("reasons"))
        return "REJECTED"
    C.log_event("approved", id=iid, post_id=pid, reasons=ap.get("reasons"))
    if DRY:
        C.update_item(iid, status="DRY_APPROVED")
        return "DRY_APPROVED(公開せず)"

    if published_today() >= C.DAILY_PUBLISH_CAP:
        C.update_item(iid, note=item["note"] + " 日次公開上限で翌回へ")
        return "READY"
    if not publish(C.get_item(iid), pid):
        return "LIVE_FAIL"
    xs = post_x(C.get_item(iid))
    C.update_item(iid, status=xs if xs != "X_DONE" else "PUBLISHED_X")
    link = C.wp("GET", f"/posts/{pid}?_fields=link")["link"]
    C.notify("[content] 自動公開", f"#{iid} {art['title']} {link} / X={xs} / {ap.get('one_line', '')[:120]}",
             0x2ECC71, key=f"pub_{pid}")
    return "PUBLISHED"


def process(only: str | None = None) -> None:
    if C.stopped():
        return
    with C.queue_lock():
        rows = C.read_queue()
    # 承認済みだが上限で止めていたもの(READY かつ approvals あり)を先に公開
    for r in [r for r in rows if r["status"] == "READY" and r["post_id"] and not DRY
              and (C.APPROVALS / f"{r['id']}.json").exists()]:
        if published_today() >= C.DAILY_PUBLISH_CAP:
            break
        try:
            ap = json.loads((C.APPROVALS / f"{r['id']}.json").read_text(encoding="utf-8"))
            if ap.get("decision") == "APPROVE" and validate(int(r["post_id"]))["ok"] \
                    and publish(r, int(r["post_id"])):
                xs = post_x(C.get_item(r["id"]))
                C.update_item(r["id"], status=xs if xs != "X_DONE" else "PUBLISHED_X")
        except Exception as e:  # noqa: BLE001
            C.update_item(r["id"], status="ERROR", note=r["note"] + f" err={str(e)[:200]}")
    todo = [r for r in rows if r["status"] == "NEW" and (not only or r["id"] == only)][:MAX_ITEMS_PER_RUN]
    for r in todo:
        try:
            res = process_one(r)
            print(f"[process] #{r['id']} {r['subject']} → {res}")
        except Exception as e:  # noqa: BLE001
            C.update_item(r["id"], status="ERROR", note=r["note"] + f" err={str(e)[:200]}")
            C.log_event("error", id=r["id"], error=str(e)[:500])
            print(f"[process] #{r['id']} ERROR {e}")
            if "日次費用上限" in str(e):
                C.update_item(r["id"], status="NEW")  # 費用で止めたものは翌日に回す
                break


def xretry() -> None:
    if C.stopped():
        return
    for r in [r for r in C.read_queue() if r["status"] == "X_DEFERRED"]:
        xs = post_x(r)
        if xs == "X_DEFERRED":
            break  # 状態を書き換えない(updated_at を見送り開始時刻のまま残し、36時間で打ち切る)
        C.update_item(r["id"], status=xs if xs != "X_DONE" else "PUBLISHED_X")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["run", "monitor", "process", "xretry", "status", "add"])
    ap.add_argument("--dry", action="store_true", help="公開・X 投稿をしない(承認判定まで)")
    ap.add_argument("--item", help="add 用 JSON: {kind,subject,claim,event_date,source_urls:[...],hub_post_id}")
    ap.add_argument("--only", help="process で処理する queue id")
    a = ap.parse_args()
    global DRY
    DRY = a.dry
    if a.stage == "add":
        it = json.loads(a.item)
        with C.queue_lock():
            rows = C.read_queue()
            nid = str(max([int(r["id"]) for r in rows] + [0]) + 1)
            rows.append({"id": nid, "detected_at": C.now(), "kind": it["kind"], "subject": it["subject"],
                         "claim": it["claim"], "event_date": it.get("event_date", ""),
                         "source_urls": " ".join(it["source_urls"]), "hub_post_id": it.get("hub_post_id", ""),
                         "status": "NEW", "post_id": "", "updated_at": C.now(),
                         "note": f"key=manual:{nid} 手動追加"})
            C.write_queue(rows)
        print(f"added #{nid}")
        return 0
    if C.stopped() and a.stage != "status":
        print(f"[pipeline] {C.STOP_FILE} があるため停止中")
        return 0
    if a.stage == "status":
        for r in C.read_queue():
            print(f"#{r['id']:>3} {r['status']:<15} {r['kind']:<14} {r['subject'][:20]:<20} "
                  f"post={r['post_id'] or '-':<6} {r['claim'][:50]}")
        print(f"本日: 公開 {published_today()}/{C.DAILY_PUBLISH_CAP} 本・費用 ${C.spent_today():.2f}/${C.DAILY_USD_CAP}")
        return 0
    if a.stage in ("run", "xretry"):
        xretry()  # 記事帯(8/12時台)の回の冒頭で見送り分を出す(後段は長いので帯を外れる)
    if a.stage in ("run", "monitor"):
        try:
            monitor()
        except Exception as e:  # noqa: BLE001
            C.log_event("monitor_error", error=str(e)[:500])
            print(f"[monitor] ERROR {e}")
            # claude のログイン切れ等で全段が止まるので、1日1回は人に知らせる
            C.notify("[content] 監視が失敗しています", f"{str(e)[:300]}(ログイン切れなら `claude setup-token`)",
                     0xE74C3C, key=f"monitor_err_{date.today()}")
    if a.stage in ("run", "process"):
        process(a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
