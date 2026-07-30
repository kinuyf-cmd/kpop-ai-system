#!/usr/bin/env python3
"""seo_lane_c_bridge.py — SEO opportunity queue を「実行キュー」に配線する。

seo_opportunity_scanner.py は data/seo_opportunity_queue.json に Lane C/B 候補を
query 単位で出すが、それを消費する経路が無かった(最大の欠落配線)。本スクリプトが:

  1. queue の lane_C_rewrite / lane_B_new の各 query を GSC の query×page 次元で
     突合し、その query を主に拾っている自サイト URL(=post)を特定する。
  2. position でルート分岐:
       pos 4.0-6.0  → logs/regeneration_queue.jsonl(auto_rewriter が CTR 改善)
       pos 6.1-12.0 → data/enrich_queue.json(body_enrich が本文拡充)
  3. 突合できない query はログに残す(新規記事候補=Lane B の本来の姿)。

使い方:
  venv_kpi/bin/python3 lib/seo_lane_c_bridge.py --dry-run   # 振り分けを表示のみ
  venv_kpi/bin/python3 lib/seo_lane_c_bridge.py             # 実キュー書き込み
依存: google-api-python-client / service_account.json(venv_kpi に存在)
"""
import os
import sys
import json
import argparse
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SA_FILE = os.path.join(BASE_DIR, "google_metrics", "service_account.json")
SITE = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")

QUEUE_IN = os.path.join(BASE_DIR, "data", "seo_opportunity_queue.json")
REGEN_QUEUE = os.path.join(BASE_DIR, "logs", "regeneration_queue.jsonl")
ENRICH_QUEUE = os.path.join(BASE_DIR, "data", "enrich_queue.json")
UNMATCHED_LOG = os.path.join(BASE_DIR, "logs", "lane_c_bridge_unmatched.jsonl")

# position 分岐の境界(plan で確定)
POS_REWRITE = (4.0, 6.0)      # CTR 改善で 1ページ目内上位化(auto_rewriter)
POS_ENRICH = (6.01, 20.0)     # 本文拡充が必要(body_enrich)。12→20拡張で2ページ目上位の常緑案件も対象化

# 1回の bridge 実行で扱う上位件数(暴走防止)
MAX_PER_LANE = 40

# ゴシップ/私的事実の slug は enrich/rewrite 対象から除外(E-E-A-T・規約リスク。
# scanner のクエリ除外をすり抜けて突合 page がゴシップ記事になるケースの最終防御)。
GOSSIP_SLUG_TERMS = [
    "dating", "scandal", "relationship", "controversy", "rumor",
    "divorce", "marriage", "enlist", "military-service",
    "removed", "leave", "leaving", "withdrawal", "disband",
]


def _is_gossip_slug(slug):
    sl = (slug or "").lower()
    return any(g in sl for g in GOSSIP_SLUG_TERMS)


# body_enrich が捏造リスクで処理を拒否するテーマ(プロフ系)。bridge 側でも
# 落としておき enrich_queue を実際に処理可能な候補だけにする(配線の自浄)。
# 根拠: 完全自動 enrich が安全に効くのは作品系(movie_anime/kdrama)の公式情報のみ。
# dance_show/artist はメンバー出身国・生年・チーム名由来など検証困難な固有情報で
# factcheck をすり抜ける捏造を生む(seo-lane-c-pipeline-page-one の教訓)。
ENRICH_BLOCKED_THEMES = {"dance_show", "artist"}

# theme が scanner で "other" 等に誤ラベルされても、slug 形状でプロフ系を捕捉する保険。
# 例: ダンスクルー系プロフ(swf3-*/supa3-*/*-profile)は出身国・生年・チーム名由来など
# 検証困難な固有情報の宝庫で enrich の捏造リスクが高い。
import re as _re
PROFILE_SLUG_RE = _re.compile(r"(^|[-_])(swf\d|supa\d)([-_]|$)|(-profile)([-_]|$)", _re.I)


def _is_profile_slug(slug):
    return bool(PROFILE_SLUG_RE.search(slug or ""))


# 既に enrich 済みの slug は queue に入れ直さない(自浄)。判定は body_enrich の
# 履歴ログ(result="updated")を流用。consumer の上限(2)より保守的に「1回でも
# 拡充済みなら除外」=未着手記事に機会を回す。
ENRICH_LOG = os.path.join(BASE_DIR, "logs", "body_enrich.jsonl")


def _enriched_slugs():
    """body_enrich 履歴(result="updated")から拡充済み slug 集合を1回読みで構築。
    呼ばれる度の全行再走査(O(候補数×ログ行数))を避けるため lru_cache で1回に固定。"""
    slugs = set()
    if not os.path.exists(ENRICH_LOG):
        return slugs
    for line in open(ENRICH_LOG, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("result") == "updated" and r.get("slug"):
            slugs.add(r["slug"])
    return slugs


def _already_enriched(slug, _cache={}):
    if "set" not in _cache:
        _cache["set"] = _enriched_slugs()
    return slug in _cache["set"]


def _url_is_live(url, timeout=8, _cache={}):
    """突合 URL が本番で 200 か。404(GSC に残るが本番消失)は enrich でなく
    再生成案件なので enrich_queue から除外する。判定不能(例外)は live 扱いで残す。
    同一 bridge 実行内の重複 URL は結果をメモ化(同期HEADの再発行を防ぐ)。"""
    if url in _cache:
        return _cache[url]
    import urllib.request
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "KpopJournalBot/1.0 lane-c-bridge"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            live = (r.status == 200)
    except urllib.error.HTTPError as e:
        live = (e.code != 404)
    except Exception:
        live = True  # ネットワーク等の一時失敗で取りこぼさない
    _cache[url] = live
    return live


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds)


def fetch_page_for_query(svc, query, days=90):
    """指定 query を最も多く拾っている自サイト page(URL)と指標を返す。
    query×page 次元で引き、impression 最大の page を採用。無ければ None。"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": ["page"],
        "dimensionFilterGroups": [{
            "filters": [{
                "dimension": "query",
                "operator": "equals",
                "expression": query,
            }]
        }],
        "rowLimit": 5,
    }
    try:
        res = svc.searchanalytics().query(siteUrl=SITE, body=body).execute()
    except Exception as e:
        print(f"  GSC error for query={query!r}: {e}", file=sys.stderr)
        return None
    rows = res.get("rows", [])
    if not rows:
        return None
    # GSC は目次アンカー(#kpop-h-N)を別行で返す。本体行と imp/pos が同値のため
    # そのまま max を取るとアンカー URL を掴み、後段の WP 更新先が壊れる。
    # クリックが載るのは本体行だけなので、フラグメントは落として集約する。
    merged = {}
    for r in rows:
        page = r["keys"][0].split("#", 1)[0]
        m = merged.get(page)
        if m is None:
            merged[page] = dict(r, keys=[page])
            continue
        m["clicks"] = m.get("clicks", 0) + r.get("clicks", 0)
        m["impressions"] = max(m.get("impressions", 0), r.get("impressions", 0))
        m["position"] = min(m.get("position", 999), r.get("position", 999))
        m["ctr"] = (m["clicks"] / m["impressions"]) if m["impressions"] else 0.0

    # impression 最大の page
    top = max(merged.values(), key=lambda r: r.get("impressions", 0))
    return {
        "url": top["keys"][0],
        "clicks": int(top.get("clicks", 0)),
        "impressions": int(top.get("impressions", 0)),
        "ctr": float(top.get("ctr", 0.0)),
        "position": float(top.get("position", 0.0)),
    }


def _slug_from_url(url):
    return url.rstrip("/").rsplit("/", 1)[-1] if url else ""


def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_enrich_queue():
    if os.path.exists(ENRICH_QUEUE):
        try:
            return json.load(open(ENRICH_QUEUE, encoding="utf-8"))
        except Exception:
            return []
    return []


def run(dry_run=False, days=90):
    if not os.path.exists(QUEUE_IN):
        print(f"[bridge] queue 無し: {QUEUE_IN}", file=sys.stderr)
        return 1
    q = json.load(open(QUEUE_IN, encoding="utf-8"))
    svc = _service()

    candidates = (q.get("lane_C_rewrite", [])[:MAX_PER_LANE]
                  + q.get("lane_B_new", [])[:MAX_PER_LANE])

    routed_rewrite, routed_enrich, unmatched = [], [], []
    seen_urls = set()  # 同一 URL の二重投入を防ぐ

    for cand in candidates:
        query = cand.get("query", "")
        if not query:
            continue
        page = fetch_page_for_query(svc, query, days=days)
        if not page or not page["url"]:
            unmatched.append({"query": query, "reason": "no_page_for_query",
                              "potential": cand.get("potential", 0)})
            continue
        url = page["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # ゴシップ/私的事実 slug は除外(最終防御)
        if _is_gossip_slug(_slug_from_url(url)):
            unmatched.append({"query": query, "url": url, "reason": "gossip_slug_excluded"})
            continue
        # 捏造リスクの高いプロフ系は enrich/rewrite 対象から除外(theme + slug 形状の二重)
        theme = cand.get("theme", "")
        if theme in ENRICH_BLOCKED_THEMES:
            unmatched.append({"query": query, "url": url,
                              "reason": f"blocked_theme:{theme}"})
            continue
        if _is_profile_slug(_slug_from_url(url)):
            unmatched.append({"query": query, "url": url,
                              "reason": "profile_slug_excluded"})
            continue
        if _already_enriched(_slug_from_url(url)):
            unmatched.append({"query": query, "url": url,
                              "reason": "already_enriched"})
            continue
        pos = page["position"]
        rec = {
            "query": query,
            "url": url,
            "slug": _slug_from_url(url),
            "position": round(pos, 2),
            "impressions": page["impressions"],
            "clicks": page["clicks"],
            "potential": cand.get("potential", 0),
            "theme": cand.get("theme", ""),
            "source": "seo_lane_c_bridge",
        }
        if POS_REWRITE[0] <= pos <= POS_REWRITE[1]:
            rec["route"] = "rewrite"
            routed_rewrite.append(rec)
        elif POS_ENRICH[0] <= pos <= POS_ENRICH[1]:
            # 本番 404(GSC に残るが消失)は本文拡充でなく再生成案件 → enrich から除外
            if not _url_is_live(url):
                unmatched.append({"query": query, "url": url, "position": round(pos, 2),
                                  "reason": "url_404_regen_candidate"})
                continue
            rec["route"] = "enrich"
            routed_enrich.append(rec)
        else:
            unmatched.append({"query": query, "url": url, "position": round(pos, 2),
                              "reason": "pos_out_of_range"})

    # potential 降順
    routed_rewrite.sort(key=lambda r: -r["potential"])
    routed_enrich.sort(key=lambda r: -r["potential"])

    print(f"[bridge] rewrite={len(routed_rewrite)} enrich={len(routed_enrich)} "
          f"unmatched={len(unmatched)} (dry_run={dry_run})")
    for r in routed_rewrite[:5]:
        print(f"  REWRITE pos{r['position']:>5} pot+{r['potential']:>5} {r['slug']}")
    for r in routed_enrich[:5]:
        print(f"  ENRICH  pos{r['position']:>5} pot+{r['potential']:>5} {r['slug']}")

    if dry_run:
        return 0

    # rewrite → auto_rewriter が読む regeneration_queue.jsonl(追記式)
    for r in routed_rewrite:
        _append_jsonl(REGEN_QUEUE, {
            "post_id": None,            # auto_rewriter は url/slug でも解決可。未解決は side で対応
            "url": r["url"], "slug": r["slug"],
            "reason": "lane_c_bridge_rewrite", "priority": "P1",
            "potential": r["potential"], "query": r["query"], "position": r["position"],
        })

    # enrich → body_enrich が読む enrich_queue.json(マージ・URL重複排除)
    existing = _load_enrich_queue()
    by_url = {e.get("url"): e for e in existing if isinstance(e, dict)}
    for r in routed_enrich:
        by_url[r["url"]] = r  # 最新の指標で上書き
    # 既存エントリも全除外フィルタで掃除(過去版・フィルタ追加前に入った滞留を自浄):
    # ゴシップ slug / プロフ slug / ブロックテーマ / enrich済み / 本番404 を落とす。
    def _keep(r):
        slug = r.get("slug", "")
        if _is_gossip_slug(slug) or _is_profile_slug(slug):
            return False
        if r.get("theme", "") in ENRICH_BLOCKED_THEMES:
            return False
        if _already_enriched(slug):
            return False
        if r.get("url") and not _url_is_live(r["url"]):
            return False
        return True
    merged = sorted((r for r in by_url.values() if _keep(r)),
                    key=lambda r: -r.get("potential", 0))
    os.makedirs(os.path.dirname(ENRICH_QUEUE), exist_ok=True)
    json.dump(merged, open(ENRICH_QUEUE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    for u in unmatched:
        _append_jsonl(UNMATCHED_LOG, u)

    print(f"[bridge] 書き込み完了: regen+{len(routed_rewrite)} "
          f"enrich_queue={len(merged)}件 unmatched_log+{len(unmatched)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    sys.exit(run(dry_run=args.dry_run, days=args.days))


if __name__ == "__main__":
    main()
