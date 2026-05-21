"""pytest 共通設定 — kpop-ai-system tests/

リポジトリルートを sys.path に追加し、tests/unit、tests/regression、tests/e2e から
`from lib.popup_event_fetcher import ...` 等で import 可能にする。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
