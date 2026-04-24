#!/usr/bin/env python3
"""ctr_title_rewriter.py — GSC低CTR記事のタイトルを claude CLI で書き換え、
score_title_ctr.py で二段階判定、tier>=provisional ならWP更新。

既存 update_low_ctr_titles.sh の Python 版。bash のset -e問題を回避し確実に20件処理する。

使い方:
  python3 lib/ctr_title_rewriter.py --top 20
  python3 lib/ctr_title_rewriter.py --top 5 --dry-run
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
METRICS = LOGS / "gsc_metrics_latest.json"
SCORE_SH = BASE / "google_metrics" / "score_title_ctr.py"
HISTORY = LOGS / "ctr_title_rewrite.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

IMPR_THRESHOLD = 50
CTR_THRESHOLD = 0.03

CLAUDE_PROMPT = """あなたはK-POPメディアのCTR改善担当です。既存タイトルを CTR が上がる形に書き換えよ。

【4つの必須要素 — すべて1つのタイトルに含めよ】
① 数字（例: 3週連続 / 641,000 / 2026 / 15形態 / 500万人）
② 固有名詞（BTS / BLACKPINK / aespa / 番組名 / イベント名 — 元タイトルから継承OK）
③ 感情語・強ワード（衝撃 / 異常 / ついに / まさか / 完全 / 暴露 / 制覇 / 快挙 / 神 / 解禁 / 首位 から1つ）
④ 対比構造（→ / vs / から / なのに / 空白 / 復帰 / 崩壊 / 逆転 / 週連続 / 年ぶり / 一転 / 塗替 から1つ）

【プロセス】
1. 内部で3案考える
2. 4要素すべてを含む案のうち、最もクリックされやすい1案を選ぶ
3. 4要素揃う案がない場合でも、最低3要素は含めよ

【制約】
- 26〜40文字（長すぎない、短すぎない）
- 誇張や釣り表現（爆速！絶対！神回確定！など）は禁止
- 記号の乱用禁止（「！！」「？？」禁止）
- 説明文・前置き・案番号一切出力禁止
- 出力は新タイトル本体1行のみ

既存タイトル:
{OLD_TITLE}"""


def curl_get(path: str):
    out = subprocess.check_output(["curl", "-s", f"{WP}{path}", "-K", WP_AUTH], timeout=30).decode()
    return json.loads(out)


def curl_post(path: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def slug_from_url(url: str) -> str:
    m = re.match(r"https://www\.kpopjournal\.tokyo/([^/?#]+)/?$", url)
    return m.group(1) if m else ""


def load_top_candidates(top: int) -> list[dict]:
    if not METRICS.exists():
        return []
    d = json.loads(METRICS.read_text())
    pages = d.get("pages", [])
    from growth_exclude import is_excluded
    cand = []
    for p in pages:
        u = p["url"]
        if is_excluded(u)[0]:
            continue
        if p["impressions"] < IMPR_THRESHOLD or p["ctr"] >= CTR_THRESHOLD:
            continue
        cand.append(p)
    cand.sort(key=lambda x: -x["impressions"])
    return cand[:top]


def already_retried_today(url: str) -> bool:
    if not HISTORY.exists():
        return False
    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    for line in HISTORY.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("url") == url and d.get("ts", "")[:10] == today:
                return True
        except Exception:
            continue
    return False


def gen_new_title(old_title: str) -> str:
    prompt = CLAUDE_PROMPT.replace("{OLD_TITLE}", old_title)
    try:
        r = subprocess.run(["claude", "-p", prompt],
                           capture_output=True, text=True, timeout=120)
        out = r.stdout.strip()
        # tail -n 1 相当
        lines = [l for l in out.splitlines() if l.strip()]
        return lines[-1].strip() if lines else ""
    except Exception as e:
        print(f"  [claude error] {e}", file=sys.stderr)
        return ""


def score_title(title: str) -> dict:
    try:
        r = subprocess.run(["python3", str(SCORE_SH), title],
                           capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout)
    except Exception:
        return {"score": 0, "tier": "reject"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="score>=8 (full tier) のみ採用。provisional は除外")
    ap.add_argument("--daily-log", type=str, default="",
                    help="追加書き込み先 (例: logs/ctr_rewrite_daily.jsonl)")
    args = ap.parse_args()

    cand = load_top_candidates(args.top)
    print(f"[ctr_title_rewriter] 対象 {len(cand)} 件 (impr>{IMPR_THRESHOLD} & ctr<{CTR_THRESHOLD*100}%)")
    if not cand:
        return

    ts = datetime.now(tz=JST).isoformat()
    stats = {"full": 0, "provisional": 0, "reject": 0, "same": 0, "retry_block": 0, "error": 0}
    MAX_REGEN = 3

    for i, p in enumerate(cand, 1):
        url = p["url"]
        slug = slug_from_url(url)
        if not slug:
            print(f"  [{i:2d}] ⏭ slug extract fail: {url}")
            stats["error"] += 1
            continue
        if already_retried_today(url):
            print(f"  [{i:2d}] ⏭ 本日すでにリトライ済: {slug}")
            stats["retry_block"] += 1
            continue
        # post lookup
        try:
            r = curl_get(f"/wp-json/wp/v2/posts?slug={slug}&_fields=id,title")
            if not isinstance(r, list) or not r:
                print(f"  [{i:2d}] ❌ 投稿なし: {slug}")
                stats["error"] += 1
                continue
            pid = r[0]["id"]
            old_title = r[0]["title"]["rendered"]
        except Exception as e:
            print(f"  [{i:2d}] ❌ post lookup fail: {e}")
            stats["error"] += 1
            continue

        # 生成改善ループ: 最大MAX_REGEN回まで再生成して条件満たす案を採る
        # required_tier: strict時は full のみ、そうでなければ provisional 以上で可
        best = None
        attempt_log = []
        for attempt in range(1, MAX_REGEN + 1):
            new_title = gen_new_title(old_title)
            if not new_title:
                attempt_log.append(f"try{attempt}=empty")
                continue
            if new_title == old_title:
                attempt_log.append(f"try{attempt}=same")
                continue
            scored = score_title(new_title)
            tier = scored.get("tier", "reject")
            score = scored.get("score", 0)
            attempt_log.append(f"try{attempt}={tier}(s={score})")
            passed = (tier == "full") or (tier == "provisional" and not args.strict)
            if passed:
                best = {"new_title": new_title, "tier": tier, "score": score}
                break

        if not best:
            # NG×MAX_REGEN → skip（書き換えない）
            print(f"  [{i:2d}] ⏭ NG×{MAX_REGEN} skip [{' '.join(attempt_log)}]: {old_title[:40]}")
            stats["reject"] += 1
            fail_record = {
                "ts": ts, "url": url, "post_id": pid,
                "impressions": p["impressions"], "ctr_pct": round(p["ctr"] * 100, 2),
                "old_title": old_title, "new_title": "",
                "tier": "reject", "attempts": attempt_log, "skipped": True,
            }
            with HISTORY.open("a") as fp:
                fp.write(json.dumps(fail_record, ensure_ascii=False) + "\n")
            continue

        new_title = best["new_title"]
        tier = best["tier"]
        score = best["score"]
        stats[tier] = stats.get(tier, 0) + 1

        record = {
            "ts": ts, "url": url, "post_id": pid,
            "impressions": p["impressions"], "ctr_pct": round(p["ctr"] * 100, 2),
            "old_title": old_title, "new_title": new_title,
            "score": score, "tier": tier,
            "attempts": attempt_log,
        }

        mark = "✅" if tier == "full" else "🟡"
        print(f"  [{i:2d}] {mark} {tier}(score={score}): {new_title[:50]}")

        if args.dry_run:
            continue

        # Update WP
        try:
            curl_post(f"/wp-json/wp/v2/posts/{pid}", {"title": new_title})
            record["updated"] = True
            with HISTORY.open("a") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            if args.daily_log:
                daily_path = BASE / args.daily_log
                daily_path.parent.mkdir(parents=True, exist_ok=True)
                with daily_path.open("a") as fp:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"       ❌ WP update fail: {e}")
            stats["error"] += 1
            record["updated"] = False
            record["error"] = str(e)
            with HISTORY.open("a") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    print()
    print(f"[ctr_title_rewriter] full={stats['full']} provisional={stats['provisional']} "
          f"reject={stats['reject']} same={stats['same']} "
          f"retry_block={stats['retry_block']} error={stats['error']}")
    print(f"  履歴: {HISTORY}")


if __name__ == "__main__":
    main()
