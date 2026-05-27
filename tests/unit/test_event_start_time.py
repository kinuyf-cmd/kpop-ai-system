"""イベント開演時刻の反映テスト(2026-05-27)
旧: add_event_date_meta は一律 19:00 固定だった。
新: start_date に "YYYY-MM-DD HH:MM" が来たらその時刻を使い、無ければ 19:00。
ここでは DRY_RUN でSQL文字列を捕捉して _EventStartDate / UTC を検証する。
"""
import os, io, contextlib, importlib


def _capture_meta(start_arg):
    os.environ['DRY_RUN'] = '1'
    import lib.popup_event_to_post as P
    importlib.reload(P)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        P.add_event_date_meta(999999, start_arg)
    return buf.getvalue()


def _val(out, key):
    import re
    m = re.search(rf"'{key}', '([^']+)'", out)
    return m.group(1) if m else None


class TestEventStartTime:
    def test_explicit_time_used(self):
        out = _capture_meta("2026-06-24 18:30")
        assert _val(out, "_EventStartDate") == "2026-06-24 18:30:00"
        # UTC = JST - 9h
        assert _val(out, "_EventStartDateUTC") == "2026-06-24 09:30:00"

    def test_default_time_when_absent(self):
        out = _capture_meta("2026-06-27")
        assert _val(out, "_EventStartDate") == "2026-06-27 19:00:00"
        assert _val(out, "_EventStartDateUTC") == "2026-06-27 10:00:00"

    def test_iso_t_separator(self):
        out = _capture_meta("2026-07-08T17:00")
        assert _val(out, "_EventStartDate") == "2026-07-08 17:00:00"

    def test_end_is_two_hours_after(self):
        out = _capture_meta("2026-06-24 18:30")
        assert _val(out, "_EventEndDate") == "2026-06-24 20:30:00"
