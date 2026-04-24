#!/usr/bin/env python3
"""
article_type_classifier.py — 記事タイプ分類と比率強制 (Phase 10)

NEWS:GUIDE:FEATURE = 70:20:10 を維持する。FEATUREは週2本上限。
パイプライン実行時にこのモジュールを呼び出し、上限超過時はNEWS/GUIDEに切替指示。

Usage:
  python3 lib/article_type_classifier.py "タイトル文字列"
  → type=NEWS / type=GUIDE / type=FEATURE
  → exit 0: OK / exit 2: FEATURE上限超過
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

FEATURE_WEEKLY_LIMIT = 2
LOG = Path(__file__).resolve().parent.parent / "logs" / "article_types.jsonl"


def classify_from_title(title: str) -> str:
    """タイトルから記事タイプを推測"""
    # FEATUREシグナル: 考察・分析系
    if re.search(r"考察|解剖|解説|年鑑|全貌|伏線|徹底|真相|論|なぜ|理由|秘密|裏側|異常", title):
        return "FEATURE"
    # GUIDEシグナル: 実用・まとめ系
    if re.search(r"ガイド|まとめ|一覧|情報|方法|手順|チケット|完全版|ランキング|TOP\d|おすすめ|比較", title):
        return "GUIDE"
    # NEWSシグナル: 速報・事実報道系
    if re.search(r"\d+月\d+日|カムバ|リリース|発表|開始|解禁|決定|公開|速報|ツアー|出演", title):
        return "NEWS"
    # デフォルトはNEWS（比率維持のため）
    return "NEWS"


def count_this_week_feature() -> int:
    """今週のFEATURE記事数を集計"""
    if not LOG.exists():
        return 0
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    cnt = 0
    for line in LOG.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            d = json.loads(line)
            if d.get("ts", "") >= cutoff and d.get("type") == "FEATURE":
                cnt += 1
        except (json.JSONDecodeError, KeyError):
            pass
    return cnt


def can_publish_as_feature() -> bool:
    """FEATUREを出せるか"""
    return count_this_week_feature() < FEATURE_WEEKLY_LIMIT


def record(post_id: int, title: str, article_type: str) -> None:
    """記録する"""
    entry = {
        "ts": datetime.now().isoformat(),
        "post_id": post_id,
        "title": title,
        "type": article_type,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: article_type_classifier.py <title>")
        sys.exit(1)
    title = sys.argv[1]
    t = classify_from_title(title)
    print(f"type={t}")
    if t == "FEATURE" and not can_publish_as_feature():
        wk = count_this_week_feature()
        print(f"⚠️ FEATURE週次上限({FEATURE_WEEKLY_LIMIT})到達(現在{wk}本)。NEWSかGUIDEに変更推奨")
        sys.exit(2)
    sys.exit(0)
