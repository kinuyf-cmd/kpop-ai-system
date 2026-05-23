#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""記事生成の真のコストを3台帳横断で集計する(2026-05-23)。

背景: コストが3台帳に分散していて anthropic_cost_guard の daily_summary だけ見ると
過小評価になっていた(translate=OpenAI gpt-4o-mini / DALL-E=gpt-image-1 は別台帳)。
量産採算判断の前提として「1記事あたり総コスト」を正確に出す。

台帳:
  - data/cost_ledger.jsonl     : anthropic(factcheck_v2/proofread 等)
  - logs/translation.jsonl     : OpenAI gpt-4o-mini(タイトル/本文 翻訳)
  - logs/dalle_cost.jsonl      : OpenAI gpt-image-1(サムネ画像) ← 最大変動費

使い方:
  python3 article_cost_summary.py            # 本日合計
  python3 article_cost_summary.py --date 2026-05-23
"""
import json
import argparse
from datetime import date

BASE = "/home/aiuser/kpop-ai-system"
LEDGERS = [
    ("anthropic(factcheck/proofread)", f"{BASE}/data/cost_ledger.jsonl"),
    ("OpenAI翻訳(gpt-4o-mini)",          f"{BASE}/logs/translation.jsonl"),
    ("DALL-E画像(gpt-image-1)",          f"{BASE}/logs/dalle_cost.jsonl"),
]


def _ledger_total(path: str, target_date: str):
    """指定日の cost 合計と件数。日付は date フィールド優先、無ければ ts 先頭10字。"""
    total, n = 0.0, 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                dt = d.get("date") or (d.get("ts", "")[:10])
                if dt != target_date:
                    continue
                c = d.get("cost_usd")
                if c is None:
                    c = d.get("cost", 0)
                total += float(c or 0)
                n += 1
    except FileNotFoundError:
        return None, 0
    return total, n


def summarize(target_date: str) -> dict:
    rows = []
    grand = 0.0
    for name, path in LEDGERS:
        total, n = _ledger_total(path, target_date)
        if total is None:
            rows.append((name, None, 0))
            continue
        rows.append((name, total, n))
        grand += total
    return {"date": target_date, "rows": rows, "grand_total": grand}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()
    s = summarize(args.date)
    print(f"=== 記事生成コスト集計 {s['date']} (3台帳横断) ===")
    for name, total, n in s["rows"]:
        if total is None:
            print(f"  {name}: 台帳なし")
        else:
            print(f"  {name}: ${total:.4f} ({n}件)")
    print(f"  --- 合計: ${s['grand_total']:.4f} ---")
    print("  ※ DALL-E画像が最大変動費。translate は極安。anthropic_cost_guard 単体では過小評価になる")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
