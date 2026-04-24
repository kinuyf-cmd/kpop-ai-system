#!/usr/bin/env python3
"""
品質ダブルチェックシステム — 投稿済み記事の品質監査

直近48時間の全記事をWP APIから取得し、10項目の品質チェックを実施。
問題のある記事はDiscord通知・JSONL記録・リライトキュー追加を行う。

スコア基準:
  S (90+)  最高品質 — そのまま公開
  A (75-89) 良質 — 公開OK
  B (60-74) 要改善 — リライトキューに追加
  C (<60)   問題あり — Discord即時アラート

Usage:
  python3 lib/quality_double_check.py           # 直近48時間を監査
  python3 lib/quality_double_check.py --now     # 同上（明示的に即時実行）
  python3 lib/quality_double_check.py --hours 24  # 直近24時間
  python3 lib/quality_double_check.py --dry-run # 通知せずレポートのみ
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

LOGS = BASE / "logs"
ISSUES_LOG = LOGS / "quality_issues.jsonl"
REWRITE_QUEUE = LOGS / "rewrite_queue.jsonl"
QUALITY_LOG = LOGS / "quality_check.log"

JST = timezone(timedelta(hours=9))

# ── 環境変数ロード ──
def _load_env():
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)

_load_env()

SITE_URL = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")


# ── WP API ──
def fetch_recent_posts(hours: int = 48, per_page: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    url = (
        f"{SITE_URL}/wp-json/wp/v2/posts"
        f"?per_page={per_page}"
        f"&after={since_str}"
        f"&_fields=id,title,date,content,excerpt,categories,featured_media"
        f"&orderby=date&order=desc"
    )
    req = urllib.request.Request(url)
    if WP_USER and WP_PASS:
        import base64
        cred = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"❌ WP API取得失敗: {e}", file=sys.stderr)
        return []


# ── テンプレートフィラー検出パターン ──
FILLER_PATTERNS = [
    r"ここに.*を入力",
    r"テンプレート",
    r"\[要.*\]",
    r"TODO",
    r"FIXME",
    r"xxx+",
    r"〇〇〇",
    r"●●●",
]

# ── Claude JSONリーク検出 ──
JSON_LEAK_PATTERNS = [
    r'"type"\s*:\s*"(text|tool_use|tool_result)"',
    r'"role"\s*:\s*"(assistant|user|system)"',
    r'"content"\s*:\s*\[\s*\{',
    r'"model"\s*:\s*"claude',
    r'"stop_reason"',
    r'"usage"\s*:\s*\{',
    r'"input_tokens"',
]

# ── フック語（CTR向上）──
HOOK_WORDS = [
    "完全", "徹底", "最新", "保存版", "まとめ", "ガイド",
    "なぜ", "理由", "真相", "衝撃", "異常", "前人未踏",
    "速報", "緊急", "2026", "ランキング", "TOP", "比較",
    "初心者", "入門", "解説", "予測", "先読み", "全貌",
]


def strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", text)
    return text.strip()


def audit_post(post: dict) -> dict:
    """1記事の品質監査。スコアと問題リストを返す。"""
    post_id = post["id"]
    title_raw = post.get("title", {}).get("rendered", "")
    title = strip_html(title_raw)
    content_html = post.get("content", {}).get("rendered", "")
    text = strip_html(content_html)
    char_count = len(text)
    date = post.get("date", "")
    featured_media = post.get("featured_media", 0)
    excerpt_html = post.get("excerpt", {}).get("rendered", "")
    excerpt = strip_html(excerpt_html)
    categories = post.get("categories", [])

    score = 100
    problems = []
    details = {}

    # 1. 文字数チェック
    details["chars"] = char_count
    if char_count < 1500:
        score -= 30
        problems.append(f"文字数不足({char_count}字 < 1500字)")
    elif char_count < 2500:
        score -= 10
        problems.append(f"文字数やや少ない({char_count}字)")

    # 2. h2/h3構造
    h2_count = len(re.findall(r"<h2", content_html, re.I))
    h3_count = len(re.findall(r"<h3", content_html, re.I))
    details["h2"] = h2_count
    details["h3"] = h3_count
    if h2_count < 4:
        score -= 15
        problems.append(f"h2不足({h2_count}本 < 4本)")

    # 3. 内部リンク
    internal_links = len(re.findall(
        r'href=["\']https?://(?:www\.)?kpopjournal\.tokyo', content_html, re.I
    ))
    details["internal_links"] = internal_links
    if internal_links < 3:
        score -= 10
        problems.append(f"内部リンク不足({internal_links}本 < 3本)")

    # 4. アイキャッチ画像
    details["featured_media"] = featured_media
    if not featured_media:
        score -= 10
        problems.append("アイキャッチ画像なし")

    # 5. メタディスクリプション（excerpt で代替チェック）
    details["excerpt_len"] = len(excerpt)
    if len(excerpt) < 30:
        score -= 5
        problems.append("メタディスクリプション短い/なし")

    # 6. テンプレートフィラー
    filler_hits = []
    for pat in FILLER_PATTERNS:
        matches = re.findall(pat, text, re.I)
        if matches:
            filler_hits.extend(matches[:2])
    if filler_hits:
        score -= 20
        problems.append(f"テンプレートフィラー検出: {', '.join(filler_hits[:3])}")

    # 7. Claude JSONリーク
    json_leaks = []
    for pat in JSON_LEAK_PATTERNS:
        if re.search(pat, content_html):
            json_leaks.append(pat[:30])
    if json_leaks:
        score -= 25
        problems.append(f"Claude APIメタデータ混入({len(json_leaks)}箇所)")

    # 8. 事実誤認の基本チェック（未来日付を過去形で記述等）
    # 年号が現在と大幅にずれている場合
    year_mentions = re.findall(r"20(\d{2})年", text)
    bad_years = [y for y in year_mentions if abs(int(y) - 26) > 3]
    if bad_years:
        score -= 5
        problems.append(f"年号確認推奨(20{',20'.join(bad_years[:3])}年)")

    # 9. タイトルのフック語
    hook_count = sum(1 for w in HOOK_WORDS if w in title)
    details["hook_words"] = hook_count
    if hook_count == 0:
        score -= 5
        problems.append("タイトルにフック語なし")

    # 10. 20文字以上の同一テキスト繰り返し
    repeat_matches = re.findall(r"(.{20,}?)\1", text)
    if repeat_matches:
        score -= 15
        problems.append(f"テキスト繰り返し検出({len(repeat_matches)}箇所)")

    score = max(0, score)
    grade = "S" if score >= 90 else "A" if score >= 75 else "B" if score >= 60 else "C"

    return {
        "post_id": post_id,
        "title": title,
        "date": date,
        "score": score,
        "grade": grade,
        "problems": problems,
        "details": details,
        "categories": categories,
    }


def check_duplicates(results: list[dict]) -> list[dict]:
    """48時間以内に同一テーマの重複がないかチェック"""
    for i, r in enumerate(results):
        for j, other in enumerate(results):
            if i >= j:
                continue
            # タイトルの共通トークン比率で判定
            t1 = set(re.findall(r"[\w]+", r["title"]))
            t2 = set(re.findall(r"[\w]+", other["title"]))
            if not t1 or not t2:
                continue
            overlap = len(t1 & t2) / min(len(t1), len(t2))
            if overlap > 0.6:
                r.setdefault("problems", []).append(
                    f"重複疑い: ID:{other['post_id']} と{overlap:.0%}類似"
                )
                if r["score"] >= 60:
                    r["score"] -= 10
                    r["grade"] = (
                        "S" if r["score"] >= 90 else
                        "A" if r["score"] >= 75 else
                        "B" if r["score"] >= 60 else "C"
                    )
    return results


# ── Discord通知 ──
def notify_discord(results: list[dict], dry_run: bool = False):
    """C/Bスコアの記事をDiscord通知"""
    critical = [r for r in results if r["grade"] == "C"]
    warnings = [r for r in results if r["grade"] == "B"]

    if not critical and not warnings:
        return

    try:
        from lib.discord_notifier import send_discord, CHANNEL_CRITICAL, CHANNEL_WARNING
        from lib.discord_notifier import COLOR_CRITICAL, COLOR_WARNING
    except ImportError:
        print("  ⚠️ discord_notifier import失敗 → Discord通知スキップ", file=sys.stderr)
        return

    if critical:
        body_lines = []
        for r in critical:
            probs = " / ".join(r["problems"][:3])
            body_lines.append(f"**[C]{r['score']}点** ID:{r['post_id']} {r['title'][:35]}\n  {probs}")
        body = "\n".join(body_lines[:5])
        send_discord(
            channel=CHANNEL_CRITICAL,
            title=f"🚨 品質C判定 {len(critical)}件",
            body=body[:1800],
            color=COLOR_CRITICAL,
            event_key=f"quality_C__{datetime.now(JST).strftime('%Y%m%d_%H')}",
            severity="CRITICAL",
            dry_run=dry_run,
        )

    if warnings:
        body_lines = []
        for r in warnings:
            probs = " / ".join(r["problems"][:3])
            body_lines.append(f"**[B]{r['score']}点** ID:{r['post_id']} {r['title'][:35]}\n  {probs}")
        body = "\n".join(body_lines[:5])
        send_discord(
            channel=CHANNEL_WARNING,
            title=f"⚠️ 品質B判定 {len(warnings)}件 — リライト推奨",
            body=body[:1800],
            color=COLOR_WARNING,
            event_key=f"quality_B__{datetime.now(JST).strftime('%Y%m%d_%H')}",
            severity="WARNING",
            dry_run=dry_run,
        )


# ── ログ記録 ──
def log_issues(results: list[dict]):
    """問題のある記事をJSONLに記録"""
    issues = [r for r in results if r["grade"] in ("B", "C")]
    if not issues:
        return
    LOGS.mkdir(exist_ok=True)
    now = datetime.now(JST).isoformat()
    with ISSUES_LOG.open("a", encoding="utf-8") as f:
        for r in issues:
            record = {
                "ts": now,
                "post_id": r["post_id"],
                "title": r["title"],
                "score": r["score"],
                "grade": r["grade"],
                "problems": r["problems"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def add_to_rewrite_queue(results: list[dict]):
    """B/C判定の記事をリライトキューに追加"""
    targets = [r for r in results if r["grade"] in ("B", "C")]
    if not targets:
        return
    # 既存キューのpost_idを読み込んで重複排除
    existing_ids = set()
    if REWRITE_QUEUE.exists():
        for line in REWRITE_QUEUE.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                existing_ids.add(rec.get("post_id"))
            except json.JSONDecodeError:
                pass

    now = datetime.now(JST).isoformat()
    added = 0
    with REWRITE_QUEUE.open("a", encoding="utf-8") as f:
        for r in targets:
            if r["post_id"] in existing_ids:
                continue
            record = {
                "ts": now,
                "post_id": r["post_id"],
                "title": r["title"],
                "score": r["score"],
                "grade": r["grade"],
                "problems": r["problems"],
                "status": "pending",
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            added += 1
    if added:
        print(f"  📝 リライトキューに{added}件追加")


# ── メイン ──
def main():
    parser = argparse.ArgumentParser(description="品質ダブルチェックシステム")
    parser.add_argument("--now", action="store_true", help="即時実行")
    parser.add_argument("--hours", type=int, default=48, help="対象期間（時間）")
    parser.add_argument("--dry-run", action="store_true", help="通知せずレポートのみ")
    args = parser.parse_args()

    now = datetime.now(JST)
    print(f"\n{'='*60}")
    print(f"品質ダブルチェック開始: {now.strftime('%Y-%m-%d %H:%M JST')}")
    print(f"対象期間: 直近{args.hours}時間")
    print(f"{'='*60}\n")

    posts = fetch_recent_posts(hours=args.hours)
    if not posts:
        print("対象記事なし")
        return

    print(f"対象記事: {len(posts)}件\n")

    # 全記事を監査
    results = []
    for post in posts:
        result = audit_post(post)
        results.append(result)

    # 重複チェック
    results = check_duplicates(results)

    # 結果表示
    grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for r in results:
        grade_counts[r["grade"]] += 1
        icon = {"S": "🏆", "A": "✅", "B": "⚠️", "C": "🚨"}.get(r["grade"], "?")
        print(f"  {icon} [{r['grade']}]{r['score']:3d}点 ID:{r['post_id']} {r['title'][:45]}")
        d = r["details"]
        print(f"     {d['chars']}字 h2={d['h2']} links={d['internal_links']} hook={d['hook_words']} img={'✓' if d['featured_media'] else '✗'}")
        if r["problems"]:
            for p in r["problems"]:
                print(f"     → {p}")
        print()

    # サマリー
    print(f"{'='*60}")
    print(f"サマリー: S={grade_counts['S']} A={grade_counts['A']} B={grade_counts['B']} C={grade_counts['C']}")
    avg = sum(r["score"] for r in results) / len(results) if results else 0
    print(f"平均スコア: {avg:.1f}点")
    print(f"{'='*60}\n")

    # ログ記録
    log_issues(results)

    # リライトキュー追加
    add_to_rewrite_queue(results)

    # Discord通知
    notify_discord(results, dry_run=args.dry_run)

    # 終了メッセージ
    if grade_counts["C"] > 0:
        print(f"🚨 C判定{grade_counts['C']}件 — Discord通知{'予定' if args.dry_run else '済み'}")
    if grade_counts["B"] > 0:
        print(f"⚠️  B判定{grade_counts['B']}件 — リライトキュー追加済み")
    if grade_counts["C"] == 0 and grade_counts["B"] == 0:
        print("✅ 全記事が品質基準を満たしています")


if __name__ == "__main__":
    main()
