"""
サムネイル学習システム

logs/thumbnail_performance.jsonl に各投稿のサムネ生成メタ情報を記録し、
CTR データと突き合わせて勝ちパターンを抽出する。

レコード形式:
{
  "post_id": "1234",
  "thumb_text": "BIGBANG 20周年復活",
  "genre": "comeback",
  "layout": "v2",
  "has_image": true,
  "eng_hero": "BIGBANG",
  "image_source": "wikimedia",  // wikimedia/gemini/typo
  "ctr_score": 0.0,              // 後で更新
  "result": "pending",            // pending/win/lose
  "timestamp": "..."
}

Usage:
  python3 lib/thumbnail_learner.py record --post-id X --thumb-text "..." --genre comeback --layout v2 --has-image true --eng-hero BIGBANG
  python3 lib/thumbnail_learner.py update --post-id X --score 75
  python3 lib/thumbnail_learner.py winners
  python3 lib/thumbnail_learner.py report
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PERF_FILE = Path("/home/aiuser/kpop-ai-system/logs/thumbnail_performance.jsonl")


def load_records():
    if not PERF_FILE.exists():
        return []
    out = []
    with open(PERF_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def save_record(record):
    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PERF_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def score_to_result(score):
    return "win" if score >= 50 else "lose"


def cmd_record(args):
    record = {
        "post_id": str(args.post_id),
        "thumb_text": args.thumb_text or "",
        "genre": args.genre or "",
        "layout": args.layout or "v2",
        "has_image": (str(args.has_image).lower() in ("true", "1", "yes")),
        "eng_hero": args.eng_hero or "",
        "image_source": args.image_source or "",
        "ctr_score": 0.0,
        "result": "pending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    save_record(record)
    print(f"recorded: post_id={record['post_id']} genre={record['genre']} layout={record['layout']} has_image={record['has_image']}")


def cmd_update(args):
    records = load_records()
    updated = 0
    new_records = []
    for r in records:
        if r.get("post_id") == str(args.post_id) and r.get("result") == "pending":
            r["ctr_score"] = args.score
            r["result"] = score_to_result(args.score)
            updated += 1
        new_records.append(r)
    if updated == 0:
        print(f"No pending thumbnail records found for post_id={args.post_id}")
        return
    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PERF_FILE, "w", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Updated {updated} thumbnail records for post_id={args.post_id} → score={args.score}")


def cmd_winners(args):
    records = load_records()
    winners = [r for r in records if r.get("result") == "win"]
    print(f"=== サムネ勝ちパターン {len(winners)}件 ===")
    for r in winners[-20:]:
        print(f"  score={r.get('ctr_score'):3.0f} | genre={r.get('genre','?'):10s} | layout={r.get('layout','?')} | has_image={r.get('has_image',False)} | hero={r.get('eng_hero','-'):15s} | {r.get('thumb_text','')[:40]}")


def cmd_report(args):
    """ジャンル別 / レイアウト別 / 画像有無別の勝率レポート"""
    records = load_records()
    confirmed = [r for r in records if r.get("result") in ("win", "lose")]
    if not confirmed:
        print("確定済みレコードがありません")
        return

    print(f"=== サムネ学習レポート ({len(confirmed)} 件) ===\n")

    def winrate(rs):
        if not rs:
            return None
        wins = sum(1 for r in rs if r.get("result") == "win")
        return wins / len(rs)

    # ジャンル別
    by_genre = {}
    for r in confirmed:
        by_genre.setdefault(r.get("genre", "?"), []).append(r)
    print("【ジャンル別 勝率】")
    for genre, rs in sorted(by_genre.items(), key=lambda x: -(winrate(x[1]) or 0)):
        wr = winrate(rs)
        print(f"  {genre:12s}: {wr*100:5.1f}% ({sum(1 for r in rs if r.get('result')=='win')}/{len(rs)})")

    # レイアウト別
    by_layout = {}
    for r in confirmed:
        by_layout.setdefault(r.get("layout", "?"), []).append(r)
    print("\n【レイアウト別 勝率】")
    for layout, rs in sorted(by_layout.items(), key=lambda x: -(winrate(x[1]) or 0)):
        wr = winrate(rs)
        print(f"  {layout:6s}: {wr*100:5.1f}% ({sum(1 for r in rs if r.get('result')=='win')}/{len(rs)})")

    # 画像有無別
    with_img = [r for r in confirmed if r.get("has_image")]
    without_img = [r for r in confirmed if not r.get("has_image")]
    print("\n【画像有無別 勝率】")
    if with_img:
        print(f"  画像あり: {winrate(with_img)*100:5.1f}% ({sum(1 for r in with_img if r.get('result')=='win')}/{len(with_img)})")
    if without_img:
        print(f"  画像なし: {winrate(without_img)*100:5.1f}% ({sum(1 for r in without_img if r.get('result')=='win')}/{len(without_img)})")

    # ヒーロー有無別
    with_hero = [r for r in confirmed if r.get("eng_hero")]
    without_hero = [r for r in confirmed if not r.get("eng_hero")]
    print("\n【英字ヒーロー有無別 勝率】")
    if with_hero:
        print(f"  ヒーローあり: {winrate(with_hero)*100:5.1f}% ({sum(1 for r in with_hero if r.get('result')=='win')}/{len(with_hero)})")
    if without_hero:
        print(f"  ヒーローなし: {winrate(without_hero)*100:5.1f}% ({sum(1 for r in without_hero if r.get('result')=='win')}/{len(without_hero)})")


def main():
    ap = argparse.ArgumentParser(description="サムネ学習システム")
    sub = ap.add_subparsers(dest="cmd")

    rec = sub.add_parser("record")
    rec.add_argument("--post-id", required=True)
    rec.add_argument("--thumb-text", default="")
    rec.add_argument("--genre", default="")
    rec.add_argument("--layout", default="v2")
    rec.add_argument("--has-image", default="false")
    rec.add_argument("--eng-hero", default="")
    rec.add_argument("--image-source", default="")
    rec.set_defaults(func=cmd_record)

    upd = sub.add_parser("update")
    upd.add_argument("--post-id", required=True)
    upd.add_argument("--score", type=float, required=True)
    upd.set_defaults(func=cmd_update)

    win = sub.add_parser("winners")
    win.set_defaults(func=cmd_winners)

    rep = sub.add_parser("report")
    rep.set_defaults(func=cmd_report)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
