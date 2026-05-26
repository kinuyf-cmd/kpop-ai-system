#!/usr/bin/env python3
"""ライター8人のイラスト風アバターを生成する。

config/x_writer_personas.json の各 writer.avatar_prompt を gpt-image-1(既存
lib/dalle_thumbnail_gen.generate_thumbnail)で生成し、正方形 PNG として
assets/writer_avatars/{key}.png に保存する。

方針:
  - **架空人物・イラスト風**。実在アイドルに似せない/実写にしない(プロンプトで明示)。
  - 1024x1024 で生成。featured image 用途。
  - 既存があればスキップ(--force で再生成)。生成は OpenAI 課金(logs/dalle_cost.jsonl 計上)。

使い方:
  python3 scripts/gen_writer_avatars.py            # 未生成のみ
  python3 scripts/gen_writer_avatars.py --only yui # 指定ライターのみ
  python3 scripts/gen_writer_avatars.py --force    # 全件再生成
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.dalle_thumbnail_gen import generate_thumbnail  # noqa: E402

JSON_PATH = ROOT / "config" / "x_writer_personas.json"
OUT_DIR = ROOT / "assets" / "writer_avatars"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="特定ライターキーのみ生成")
    ap.add_argument("--force", action="store_true", help="既存があっても再生成")
    args = ap.parse_args()

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    writers = data.get("writers", {})
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    total_cost = 0.0
    for key, w in writers.items():
        if args.only and key != args.only:
            continue
        prompt = w.get("avatar_prompt")
        if not prompt:
            print(f"[skip] {key}: avatar_prompt なし")
            continue
        out = OUT_DIR / f"{key}.png"
        if out.exists() and not args.force:
            print(f"[skip] {key}: 既存 ({out.name})")
            continue
        print(f"[gen ] {key} ({w.get('name','')}) …")
        res = generate_thumbnail(prompt, str(out), size="1024x1024", quality="standard")
        if res.get("success"):
            total_cost += res.get("cost_usd", 0)
            print(f"       ✓ {out}  (${res.get('cost_usd',0)})")
        else:
            print(f"       ✗ 失敗: {res.get('reason')}")
    print(f"\n概算コスト: ${round(total_cost, 3)}")
    print(f"保存先: {OUT_DIR}")
    print("次: 各 writer 投稿の featured image に設定(runbook 参照)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
