"""pytest 共通設定 — kpop-ai-system tests/

リポジトリルートを sys.path に追加し、tests/unit、tests/regression、tests/e2e から
`from lib.popup_event_fetcher import ...` 等で import 可能にする。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# テスト環境では anthropic SDK を読み込まないため stub を提供。
# lib.factcheck_v2 等は import 時に anthropic を解決する。
import types as _types
if 'anthropic' not in sys.modules:
    sys.modules['anthropic'] = _types.ModuleType('anthropic')
