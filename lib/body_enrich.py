#!/usr/bin/env python3
"""body_enrich.py — Lane C 既存記事の本文を「網羅性拡充」で1ページ目へ押し上げる。

data/enrich_queue.json(seo_lane_c_bridge が pos6-12 の記事を積む)を処理し、
不足している高CTR型の H2(キャスト一覧/相関図/楽曲一覧/読み方 等)を生成して
**既存本文に追記**する。SWF3/デーモンハンターズで実証済みの勝ちパターン。

完全自動だが、本日のイベント誤情報事故と同型のリスクがあるため安全装置を必須化:
  - 既存本文は削除・改変しない(新規 H2 の追記のみ。破壊的変更禁止)
  - 追記後の記事を factcheck_v2 に通し、critical があれば WP 更新せずスキップ
  - 曖昧アーティスト名の誤マッチ防止ガードを適用
  - auto_rewriter の安全制御を踏襲(記事あたり最大2回 / 24h連続禁止 / WIN除外 / slug不変)
  - 1回の実行は少数(--limit 既定3本/週)に絞る
  - 同一slugでWP更新(GSC資産継承)→ 公開後 gsc_indexing で URL_UPDATED

使い方:
  python3 lib/body_enrich.py --dry-run            # 生成+factcheckのみ、WP更新なし
  python3 lib/body_enrich.py --limit 3            # 上位3本を実拡充
依存: anthropic(本文生成/factcheck)、auto_rewriter(wp_request/安全制御)、
      internal_links、gsc_indexing。
"""
import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ANTHROPIC_API_KEY 等は .env から読む(factcheck_v2 等と同じ作法)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    pass

ENRICH_QUEUE = os.path.join(BASE_DIR, "data", "enrich_queue.json")
ENRICH_LOG = os.path.join(BASE_DIR, "logs", "body_enrich.jsonl")
BACKUP_DIR = os.path.join(BASE_DIR, "backups", "body_enrich")

# 追記後の文字数が追記前よりこの倍率を超えて増える、または追記前を下回る場合は
# 本文消失/異常膨張の兆候とみなし WP 更新をブロックする(wp post update stdin
# 破壊事故の再発防止)。
MAX_GROWTH_RATIO = 1.5


def _backup_content(slug, pid, content):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{slug}_{_now().replace(':', '')}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _size_sane(before_len, after_len):
    if after_len < before_len:
        return False, "shrunk"
    if before_len > 0 and after_len > before_len * MAX_GROWTH_RATIO:
        return False, f"growth_over_{MAX_GROWTH_RATIO}x"
    return True, "ok"


def _notify_discord(message):
    try:
        from lib.resolve_discord_webhook import resolve
        import urllib.request
        url = resolve("seo_insights")
        if not url:
            return
        body = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (compatible; KpopJournalBot/1.0)"},
            method="POST")
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  [enrich] discord通知失敗(続行): {e}", file=sys.stderr)


def _verify_live_render(url, expected_h2_texts):
    """公開後、実際に curl で本文を取得し追記した H2 が反映されているか確認する
    (wp-ro db query/post get 出力汚染の教訓=書込み結果は必ず実レンダで確認)。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; KpopJournalBot/1.0)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        missing = [h for h in expected_h2_texts if h not in html]
        return len(missing) == 0, missing
    except Exception as e:
        return False, [f"fetch_error:{e}"]

# 追記する高CTR型セクションの候補(テーマ別の「不足しがちなH2」)
ENRICH_SECTION_HINTS = {
    "movie_anime": ["登場キャラクター一覧", "声優・キャスト", "挿入歌・楽曲一覧", "あらすじ"],
    "dance_show": ["出演メンバー一覧", "クルー・チーム紹介", "ミッション・楽曲"],
    "kdrama": ["登場人物・相関図", "キャスト一覧", "あらすじ", "配信・視聴方法"],
    "artist": ["メンバープロフィール", "代表曲・ディスコグラフィ", "経歴"],
    "trend_goods": ["特徴・種類", "入手方法・販売店", "価格"],
    "beauty": ["使い方・手順", "成分・効果", "口コミ・評判"],
    "travel": ["アクセス・行き方", "周辺スポット", "営業時間・料金"],
}
DEFAULT_HINTS = ["詳細・基本情報", "よくある質問"]

# 完全自動 enrich を行わないテーマ(オーナー判断 2026-05-26)。
# ダンス番組/個人プロフィール記事は既に網羅的なうえ、追記しようとすると
# メンバー個々の出身国・生年・チーム名由来など「検証困難な固有情報」に
# 踏み込みやすく捏造リスクが高い。作品系(movie_anime/kdrama=声優・楽曲・
# あらすじが公式確認できる)に絞る。これらは drop=queue除外。
ENRICH_BLOCKED_THEMES = {"dance_show", "artist"}

MAX_ENRICH_PER_POST = 2     # auto_rewriter と同じく記事あたり上限


def _now():
    return datetime.now(timezone.utc).isoformat()


def _log(entry):
    entry["ts"] = _now()
    os.makedirs(os.path.dirname(ENRICH_LOG), exist_ok=True)
    with open(ENRICH_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_queue():
    if not os.path.exists(ENRICH_QUEUE):
        return []
    try:
        return json.load(open(ENRICH_QUEUE, encoding="utf-8"))
    except Exception:
        return []


def _save_queue(items):
    json.dump(items, open(ENRICH_QUEUE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def _enrich_count(slug):
    """この slug を過去に何回 enrich したか(24h連続防止 + 上限判定用)。"""
    n, last_ts = 0, None
    if not os.path.exists(ENRICH_LOG):
        return 0, None
    for line in open(ENRICH_LOG, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("slug") == slug and r.get("result") == "updated":
            n += 1
            last_ts = r.get("ts")
    return n, last_ts


def _within_24h(ts_iso):
    if not ts_iso:
        return False
    try:
        t = datetime.fromisoformat(ts_iso)
        return (datetime.now(timezone.utc) - t).total_seconds() < 86400
    except Exception:
        return False


def _existing_h2_set(html):
    return set(re.findall(r"<h2[^>]*>(.*?)</h2>", html or "", re.S | re.I))


def _ambiguous_artist_ok(title, body):
    """曖昧アーティスト名の誤マッチ防止(イベント誤情報事故と同型リスクの予防)。
    enrich 対象は既に公開済みの記事なので、ここでは「誤マッチ語が記事の主題で、
    かつ K-POP 文脈語が一切無い」ケースだけを弾く(保守的)。判定不能なら通す。
    本来の捏造防止は generate_enrich_sections のプロンプト制約 + factcheck ゲート。"""
    sample = (title + " " + re.sub(r"<[^>]+>", " ", body or "")[:600]).lower()
    # 一般語同綴のグループ名(treasure/ive/ace)が主題っぽいのに文脈語が皆無なら弾く
    ambiguous = ("treasure", "ive", "ace")
    context = ("k-pop", "kpop", "韓国", "korea", "ソウル", "アイドル",
               "カムバック", "コンサート", "ファンミ", "アルバム",
               "트레저", "아이브", "デビュー", "メンバー")
    if any(a in sample for a in ambiguous) and not any(c in sample for c in context):
        return False
    return True


def generate_enrich_sections(title, theme, existing_h2, plain_body):
    """不足している高CTR型 H2 を Claude で生成して HTML 断片を返す。
    事実は本文/web から裏取りし、ソースに無い固有情報は断定しない。"""
    import anthropic
    hints = ENRICH_SECTION_HINTS.get(theme, DEFAULT_HINTS)
    # 既に存在する H2 と「概念が重複」しないものだけ依頼。
    # 単なる先頭一致では「メンバー7人一覧」と「出演メンバー一覧」を別物と誤判定し
    # 薄い重複コンテンツを生む(SWF3プロフィール記事で実害)。各 hint を概念
    # トークンに分解し、既存 H2 群のどれかと意味的に重なれば除外する。
    CONCEPT_TOKENS = {
        "出演メンバー一覧": ["メンバー", "出演", "ロスター", "一覧"],
        "クルー・チーム紹介": ["クルー", "チーム", "グループ紹介"],
        "ミッション・楽曲": ["ミッション", "楽曲", "曲", "パフォーマンス"],
        "登場キャラクター一覧": ["キャラクター", "登場人物", "キャラ一覧"],
        "声優・キャスト": ["声優", "キャスト", "ボイス", "歌唱担当"],
        "挿入歌・楽曲一覧": ["挿入歌", "楽曲", "サウンドトラック", "OST"],
        "あらすじ": ["あらすじ", "ストーリー", "物語"],
        "メンバープロフィール": ["メンバー", "プロフィール"],
        "代表曲・ディスコグラフィ": ["代表曲", "ディスコグラフィ", "楽曲"],
        "経歴": ["経歴", "来歴", "歴史"],
        "登場人物・相関図": ["登場人物", "相関図", "キャラクター"],
        "キャスト一覧": ["キャスト", "出演者", "俳優"],
        "配信・視聴方法": ["配信", "視聴", "見る方法", "どこで"],
    }
    ex_text = " ".join(existing_h2)

    def _overlaps(hint):
        tokens = CONCEPT_TOKENS.get(hint, [hint[:3]])
        # 既存H2に概念トークンが2語以上、または主要1語が含まれれば重複とみなす
        hits = sum(1 for t in tokens if t in ex_text)
        return hits >= 1

    wanted = [h for h in hints if not _overlaps(h)]
    if not wanted:
        print(f"  [enrich] 追記候補すべて既存と重複(網羅済み記事)。スキップ。", file=sys.stderr)
        return "", []
    client = anthropic.Anthropic()
    prompt = (
        f"あなたはK-POPメディアの編集者です。以下の既存記事に対し、検索ユーザーが"
        f"求めるが不足している網羅セクションを HTML で追記します。\n\n"
        f"【記事タイトル】{title}\n"
        f"【既存本文(抜粋)】\n{plain_body[:1800]}\n\n"
        f"【追記したいセクション(不足分)】{', '.join(wanted)}\n\n"
        f"要件:\n"
        f"- 各セクションは <h2>見出し</h2> + <p>本文</p> 形式。h3 補助可。\n"
        f"- **既存本文に書かれている事実と矛盾させない。確認できない固有名詞・人名・"
        f"日付・数値は創作しない**(分からなければそのセクションは出力しない)。\n"
        f"- **特に『チーム名/グループ名の由来・語源・意味』『デビューの裏話』など"
        f"出典で裏取りできない逸話は書かない**(もっともらしく創作する典型的な"
        f"ハルシネーション源。既存本文に明記が無い限り触れない)。\n"
        f"- 事実が不確かな箇所は断定せず、一般論・観戦ガイド等の検証不要な切り口に留める。\n"
        f"- 3ペルソナ(初心者/コアファン/検索流入)に有用な内容。\n"
        f"- 出力は追記する HTML 断片のみ。前置き・コードフェンス不要。"
    )
    try:
        msg = client.messages.create(
            # 2026-07-15: Sonnet 5 移行。本文拡充はHTML断片生成タスクで、
            # thinking を明示 disabled (adaptive ON だと max_tokens を圧迫)。
            model="claude-sonnet-5",
            max_tokens=2500,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        html = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as e:
        print(f"  [enrich] 生成失敗: {e}", file=sys.stderr)
        return "", []
    # コードフェンス除去
    html = re.sub(r"^```[a-z]*\n?|\n?```$", "", html).strip()
    if "<h2" not in html:
        return "", []
    return html, wanted


def factcheck_passes(post_id, title, full_html):
    """追記後の全文を factcheck_v2 に通し critical 0 なら合格。"""
    try:
        from lib.factcheck_v2 import proofread_post_v2
    except Exception as e:
        print(f"  [enrich] factcheck import 失敗、安全側でスキップ: {e}", file=sys.stderr)
        return False, {"error": "factcheck_unavailable"}
    post = {"id": post_id, "title": title, "content": full_html}
    try:
        res = proofread_post_v2(post, use_web_search=True)
    except Exception as e:
        print(f"  [enrich] factcheck 実行失敗、安全側でスキップ: {e}", file=sys.stderr)
        return False, {"error": str(e)}
    critical = res.get("critical", [])
    return (len(critical) == 0), res


def process_one(item, dry_run=False):
    from lib.auto_rewriter import wp_request
    slug = item.get("slug", "")
    url = item.get("url", "")

    # 安全制御: 上限 / 24h連続
    n, last_ts = _enrich_count(slug)
    if n >= MAX_ENRICH_PER_POST:
        _log({"slug": slug, "result": "skip", "reason": f"max_enrich({n})"})
        return "skip"
    if _within_24h(last_ts):
        _log({"slug": slug, "result": "skip", "reason": "within_24h"})
        return "skip"

    # 記事取得(URL→slug 経由で WP REST 検索)
    posts, err = wp_request("GET", f"/posts?slug={slug}&_fields=id,title,content,link,status")
    if err or not posts:
        # 記事が存在しない(GSC に残るが本番404=消失記事)。enrich 対象外なので
        # queue から恒久除外する(再生成は別フローの仕事)。
        _log({"slug": slug, "result": "drop", "reason": f"not_found_404:{err}"})
        return "drop"
    post = posts[0]
    pid = post["id"]
    title = post["title"]["rendered"] if isinstance(post.get("title"), dict) else post.get("title", "")
    content = post["content"]["rendered"] if isinstance(post.get("content"), dict) else post.get("content", "")
    if post.get("status") != "publish":
        _log({"slug": slug, "result": "skip", "reason": "not_publish"})
        return "skip"

    # テーマガード: ダンス番組/個人プロフィール系は自動enrich対象外(捏造リスク)
    if item.get("theme") in ENRICH_BLOCKED_THEMES:
        _log({"slug": slug, "result": "drop", "reason": f"blocked_theme:{item.get('theme')}"})
        return "drop"

    # 曖昧名ガード
    if not _ambiguous_artist_ok(title, content):
        _log({"slug": slug, "result": "skip", "reason": "ambiguous_artist_guard"})
        return "skip"

    existing_h2 = _existing_h2_set(content)
    plain = re.sub(r"<[^>]+>", " ", content)
    plain = re.sub(r"\s+", " ", plain).strip()

    sections_html, wanted = generate_enrich_sections(
        title, item.get("theme", ""), existing_h2, plain)
    if not sections_html:
        _log({"slug": slug, "result": "skip", "reason": "no_new_sections"})
        return "skip"

    # 内部リンク集約(追記分にインラインリンクのみ。末尾「関連記事」セクションは
    # 既存記事側に既にあるため付けない=重複防止。insert_internal_links は末尾
    # セクションを必ず足す仕様なので、内部の _insert_inline_links を直接使う)。
    try:
        from lib.internal_links import (
            _find_related_articles, _insert_inline_links, get_article_index)
        idx = get_article_index()
        related = _find_related_articles(sections_html, title, idx, current_url=url)
        sections_html = _insert_inline_links(sections_html, related)
    except Exception as e:
        print(f"  [enrich] internal_links 失敗(続行): {e}", file=sys.stderr)

    # 追記のみ(既存本文は不変)
    new_full = content.rstrip() + "\n\n" + sections_html

    # factcheck ゲート(追記後の全文)
    ok, fc = factcheck_passes(pid, title, new_full)
    if not ok:
        _log({"slug": slug, "post_id": pid, "result": "factcheck_block",
              "wanted": wanted, "critical": fc.get("critical", fc)})
        return "factcheck_block"

    if dry_run:
        _log({"slug": slug, "post_id": pid, "result": "dry_run_ok",
              "wanted": wanted, "added_chars": len(sections_html)})
        print(f"  [enrich] DRY-OK {slug}: +{len(sections_html)}字 sections={wanted}")
        return "dry_run_ok"

    # サイズ整合性チェック(本文消失/異常膨張の兆候を検知)
    sane, size_reason = _size_sane(len(content), len(new_full))
    if not sane:
        _log({"slug": slug, "post_id": pid, "result": "size_block", "reason": size_reason,
              "before_len": len(content), "after_len": len(new_full)})
        _notify_discord(f"⚠️ body_enrich 異常検知: {slug} ({size_reason}) "
                         f"本文更新をブロックしました。")
        return "size_block"

    # 更新前の本文をバックアップ(wp post update stdin破壊事故の再発防止)
    backup_path = _backup_content(slug, pid, content)

    # WP 更新(content。slug 不変=GSC資産継承)
    resp, err = wp_request("POST", f"/posts/{pid}", {"content": new_full})
    if err or not (resp and resp.get("id")):
        _log({"slug": slug, "post_id": pid, "result": "wp_update_fail", "error": err,
              "backup": backup_path})
        _notify_discord(f"⚠️ body_enrich WP更新失敗: {slug} ({err})")
        return "wp_update_fail"

    # 公開後、実レンダで追記H2が反映されているか確認(汚染/消失の検知)
    new_h2 = re.findall(r"<h2[^>]*>(.*?)</h2>", sections_html, re.S | re.I)
    verified, missing = _verify_live_render(url, new_h2)
    if not verified:
        _log({"slug": slug, "post_id": pid, "result": "verify_fail",
              "missing": missing, "backup": backup_path})
        _notify_discord(f"⚠️ body_enrich 公開後検証失敗: {slug} missing={missing} "
                         f"backup={backup_path}")
        return "verify_fail"

    # Indexing 送信
    try:
        from lib.gsc_indexing import notify_url_updated  # 関数名は実在に合わせる
        notify_url_updated(url)
    except Exception:
        # gsc_indexing の公開関数名が異なる場合は CLI 経由でも可。失敗は致命でない。
        pass

    _log({"slug": slug, "post_id": pid, "result": "updated",
          "wanted": wanted, "added_chars": len(sections_html), "potential": item.get("potential", 0),
          "backup": backup_path})
    print(f"  [enrich] UPDATED {slug}: +{len(sections_html)}字 sections={wanted}")
    return "updated"


def run(limit=3, dry_run=False):
    queue = _load_queue()
    if not queue:
        print("[enrich] enrich_queue が空。bridge を先に実行してください。")
        return 0
    processed, done, dropped = 0, [], []
    for item in queue:
        if processed >= limit:
            break
        slug = item.get("slug", "?")
        print(f"[enrich] processing {slug} (pos{item.get('position')} pot+{item.get('potential')})")
        result = process_one(item, dry_run=dry_run)
        processed += 1
        if result in ("updated", "dry_run_ok"):
            done.append(item.get("url"))
        elif result == "drop":
            dropped.append(item.get("url"))  # 404等=恒久除外
    # 成功 URL と 404 URL を queue から除去(dry-run では除去しない)
    if not dry_run and (done or dropped):
        remove = set(done) | set(dropped)
        remaining = [i for i in queue if i.get("url") not in remove]
        _save_queue(remaining)
        if dropped:
            print(f"[enrich] queueから除外(404等): {len(dropped)}件")
    print(f"[enrich] 完了: {processed}件処理")
    if not dry_run and processed:
        _notify_discord(f"📝 body_enrich 完了: {processed}件処理 / 成功{len(done)}件 / "
                         f"除外{len(dropped)}件")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(run(limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
