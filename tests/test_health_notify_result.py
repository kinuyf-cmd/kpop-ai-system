#!/usr/bin/env python3
"""health_check の通知結果表示のテスト。

背景 (2026-08-31):
  notify_discord は失敗時に False を返すが、main はその戻り値を無視して
  無条件に「→ Discord通知送信」と出していた。
  送信できていなくても成功に見えるため、通知が死んでいることに気付けない
  ([[discord-notify-global-repair-20260602]] で全系統失効した実績があり、
   「成功ログを出しながら実は失敗」は [[aioseo-desc-write-traps]] と同じ罠)。

  なお 2026-08-31 時点の実測では全8チャネル HTTP 204 で到達している。
  これは「壊れているから直す」ではなく「壊れた時に分かるようにする」修正。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib  # noqa: E402
m = importlib.import_module("tools.health.daily_health_check")


def test_送信失敗はその旨を表示する(capsys, monkeypatch):
    monkeypatch.setattr(m, "notify_discord", lambda text: False)
    monkeypatch.setattr(sys, "argv", ["x", "--force-notify"])
    for fn in ("check_freshness", "check_publish_quality", "check_configs",
               "check_meta_null", "check_gsc_drop", "check_adsense_token",
               "check_disk_space", "check_jsonl_integrity"):
        monkeypatch.setattr(m, fn, lambda *a, **k: None)
    monkeypatch.setattr(m, "load_acks", lambda: set())
    monkeypatch.setattr(m, "LOG_OUT", Path("/dev/null"))
    try:
        m.main()
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "失敗" in out, f"失敗が表示されていない: {out!r}"


def test_送信成功は成功として表示する(capsys, monkeypatch):
    monkeypatch.setattr(m, "notify_discord", lambda text: True)
    monkeypatch.setattr(sys, "argv", ["x", "--force-notify"])
    for fn in ("check_freshness", "check_publish_quality", "check_configs",
               "check_meta_null", "check_gsc_drop", "check_adsense_token",
               "check_disk_space", "check_jsonl_integrity"):
        monkeypatch.setattr(m, fn, lambda *a, **k: None)
    monkeypatch.setattr(m, "load_acks", lambda: set())
    monkeypatch.setattr(m, "LOG_OUT", Path("/dev/null"))
    try:
        m.main()
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "送信" in out and "失敗" not in out
