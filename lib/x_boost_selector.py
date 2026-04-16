#!/usr/bin/env python3
"""x_boost_selector.py — GSC impr高 & CTR低の既存記事からX投稿ブースト対象を20件選定。

ルール:
  - impressions >= 50
  - ctr < 5%  (低すぎずブースト効果見込める範囲)
  - position <= 20 (発見はされているがクリックされていない)
  - 各記事のHOOK強化版tweetを生成（数字+固有名詞+感情語必須）
  - hook_score 60 以上のみキューへ (80は厳しすぎるため 60 に緩和)

出力: logs/x_revival_queue.jsonl に上書き + logs/x_backfill_runner.sh 更新

使い方:
  python3 lib/x_boost_selector.py [--limit 20]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
METRICS = LOGS / "gsc_metrics_latest.json"
OUT_QUEUE = LOGS / "x_revival_queue.jsonl"
OUT_RUNNER = LOGS / "x_backfill_runner.sh"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

MIN_IMPR = 50
MAX_CTR = 0.05
MAX_POS = 20
MIN_HOOK_SCORE = 60


def curl_get(path: str):
    cmd = ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH]
    return json.loads(subprocess.check_output(cmd, timeout=30).decode())


def load_gsc():
    if not METRICS.exists():
        return []
    d = json.loads(METRICS.read_text())
    return d.get("pages", [])


def fetch_post_by_slug(slug: str):
    try:
        res = curl_get(f"/wp-json/wp/v2/posts?slug={slug}&_fields=id,title,link,categories")
        if isinstance(res, list) and res:
            return res[0]
    except Exception:
        pass
    return None


def extract_slug(url: str) -> str:
    m = re.match(r"^https://www\.kpopjournal\.tokyo/([^/?#]+)/?$", url)
    return m.group(1) if m else ""


ARTISTS = [
    "BTS", "BLACKPINK", "BIGBANG", "aespa", "BABYMONSTER", "ILLIT", "IVE",
    "SEVENTEEN", "TWICE", "Stray Kids", "NewJeans", "LE SSERAFIM", "NCT",
    "RIIZE", "TXT", "ENHYPEN", "ITZY", "NMIXX", "EXO", "SHINee", "TAEMIN",
    "G-DRAGON", "T.O.P", "KATSEYE", "MAMAMOO", "JIMIN",
]
EMOTIONS = ["衝撃", "電撃", "判明", "ついに", "まさか", "速報", "記録", "驚愕",
            "神", "解禁", "完全", "必見", "復帰", "制覇", "初", "歴史", "快挙",
            "1位", "首位", "伝説", "奇跡", "爆発", "炎上", "暴露", "異常", "全貌"]


def hook_score(text: str) -> int:
    score = 0
    if re.search(r"[0-9]", text):
        score += 25
    if any(a.lower() in text.lower() for a in ARTISTS):
        score += 25
    if any(e in text for e in EMOTIONS):
        score += 20
    if re.search(r"→|vs|VS|から|でも|なのに|なぜ|なのか|空白|一転|激変|崩壊|[0-9]+年ぶり", text):
        score += 20
    total = len(text.strip())
    if 120 <= total <= 150:
        score += 10
    return min(score, 100)


def build_strong_hook(title: str, ctr_pct: float, impr: int, pos: float) -> tuple[str, int]:
    """数字+固有名詞+感情語を必ず含むhook生成。複数パターンから最高scoreを選ぶ。"""
    # アーティスト抽出
    artist = ""
    for a in ARTISTS:
        if a.lower() in title.lower():
            artist = a
            break
    if not artist:
        # タイトルから固有名詞候補を抽出 (K-POP/韓国関連で頻出)
        m = re.search(r"[A-Za-z\-]+\d+|[A-Za-z]{3,}", title)
        artist = m.group(0) if m else "K-POP"

    title_short = re.sub(r"[【】「」『』]", "", title).strip()[:80]
    # 数字が既にタイトルに含まれていればそれを拾う、なければimpr数を活用
    has_num = bool(re.search(r"[0-9０-９]", title))
    num_hint = "" if has_num else f"見た{impr:,}人が気になった"

    # 感情語を先頭に必ず入れる
    patterns = [
        f"【衝撃】{title_short}",
        f"【必見】{title_short}",
        f"ついに判明：{title_short}",
        f"まさかの展開｜{title_short}",
        f"【暴露】{title_short}",
        f"{num_hint}。{title_short}" if num_hint else f"【完全解説】{title_short}",
    ]

    best = ("", 0)
    hashtags = "\n#KPOP #K_POP #KPOPJournal"
    for p in patterns:
        text = p + hashtags
        if len(text) > 250:
            # 長すぎは削る
            text = p[:180] + hashtags
        # 3要件必須チェック
        has_number = bool(re.search(r"[0-9]", text))
        has_artist = any(a.lower() in text.lower() for a in ARTISTS) or (artist and artist.lower() in text.lower())
        has_emotion = any(e in text for e in EMOTIONS)
        if not (has_number and has_artist and has_emotion):
            # 要件不足 → 強制付与
            if not has_number:
                text = f"{impr:,}imprなのにCTR{ctr_pct:.1f}% | " + text
            if not has_emotion:
                text = "【衝撃】" + text
        sc = hook_score(text)
        if sc > best[1]:
            best = (text, sc)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    pages = load_gsc()
    print(f"[x_boost_selector] GSC全体 {len(pages)} ページ")

    # Filter
    cand = []
    HOME = "https://www.kpopjournal.tokyo/"
    for p in pages:
        url = p["url"]
        if "#" in url or "?" in url or url == HOME:
            continue
        slug = extract_slug(url)
        if not slug:
            continue
        if p["impressions"] < MIN_IMPR:
            continue
        if p["ctr"] >= MAX_CTR:
            continue
        if p.get("position", 999) > MAX_POS:
            continue
        cand.append(p)

    print(f"[x_boost_selector] 条件通過 {len(cand)} 件 (impr>={MIN_IMPR}, ctr<{MAX_CTR*100}%, pos<={MAX_POS})")

    ts = datetime.now(tz=JST).isoformat()
    queued = 0
    skipped_low_hook = 0

    with OUT_QUEUE.open("w") as fp:
        for p in cand:
            if queued >= args.limit:
                break
            slug = extract_slug(p["url"])
            post = fetch_post_by_slug(slug)
            if not post:
                continue
            title = post["title"]["rendered"] if isinstance(post["title"], dict) else post["title"]
            ctr_pct = p["ctr"] * 100
            text, sc = build_strong_hook(title, ctr_pct, p["impressions"], p["position"])
            if sc < MIN_HOOK_SCORE:
                skipped_low_hook += 1
                continue
            rec = {
                "queued_at": ts, "post_id": post["id"], "slug": slug,
                "title": title, "url": p["url"], "reply_url": p["url"],
                "tweet_text": text, "hook_score": sc,
                "gsc": {"impressions": p["impressions"], "clicks": p["clicks"],
                        "ctr_pct": round(ctr_pct, 2), "position": round(p["position"], 1)},
                "rule": "number+artist+emotion required",
            }
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            queued += 1

    # Regenerate runner
    runner = f"""#!/bin/bash
# x_backfill_runner.sh - regenerated by x_boost_selector.py
# 実行: ENABLE_X_POST=1 bash {OUT_RUNNER}
set -e
QUEUE="{OUT_QUEUE}"
LOG="{BASE}/logs/x_backfill_run.log"
POSTER="{BASE}/google_metrics/post_to_x.sh"

if [ "${{ENABLE_X_POST:-0}}" != "1" ]; then
  echo "[x_backfill_runner] ENABLE_X_POST=1 が設定されていないため投稿しません (dry-run)"
  echo "[x_backfill_runner] キュー件数: $(wc -l < \"$QUEUE\")"
  exit 0
fi

echo "=== x_backfill_runner start $(date -Iseconds) ===" | tee -a "$LOG"
COUNT=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  post_id=$(echo "$line" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('post_id',''))")
  text=$(echo "$line" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('tweet_text',''))")
  url=$(echo "$line" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('reply_url',''))")
  COUNT=$((COUNT+1))
  echo "[backfill $COUNT] posting post_id=$post_id ..." | tee -a "$LOG"
  TWEET_TEXT="$text" POST_URL="$url" BACKFILL_MODE=1 bash "$POSTER" 2>&1 | tee -a "$LOG" | tail -3 || true
  # Rate limiting: 90s between posts
  sleep 90
done < "$QUEUE"
echo "=== x_backfill_runner done $(date -Iseconds) (posted=$COUNT) ===" | tee -a "$LOG"
"""
    OUT_RUNNER.write_text(runner)
    OUT_RUNNER.chmod(0o755)

    print(f"[x_boost_selector] キュー {queued} 件 / hook<{MIN_HOOK_SCORE} スキップ {skipped_low_hook}")
    print(f"  queue:  {OUT_QUEUE}")
    print(f"  runner: {OUT_RUNNER}")


if __name__ == "__main__":
    main()
