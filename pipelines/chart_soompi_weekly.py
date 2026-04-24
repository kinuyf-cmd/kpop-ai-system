#!/usr/bin/env python3
"""
chart_soompi_weekly.py — Soompi週次K-POPチャート記事生成パイプライン

毎週金曜09:00実行 (crontab)。
Soompi MusicチャートTop10を取得→記事化→WP公開。

2026-04-27 オーナー指示:
  Circle Chart / Billboard K-Pop / Monthly Chart を廃止。
  Soompiの週次チャートのみを記事化する。

TODO:
  - Soompi API/スクレイピングでTop10取得
  - デオキシスでストレートニュース記事生成
  - pre_publish_hookで品質検証
  - WP公開 + X投稿
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/kpop-ai-system'))


def main():
    print(f"[chart_soompi_weekly] start {datetime.now().isoformat()}")
    # Phase 1: 雛形。実データ取得は次バージョンで実装。
    print("[chart_soompi_weekly] 雛形のみ — Soompiスクレイピング実装はTODO")
    print("[chart_soompi_weekly] done")
    return 0


if __name__ == '__main__':
    sys.exit(main())
