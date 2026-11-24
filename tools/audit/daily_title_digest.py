#!/usr/bin/env python3
"""前日(JST)に公開した記事のタイトル一覧を、毎朝 Discord の daily_ceo_report に送る(2026-11-18)。

目的: 速報・自律パイプラインには人のレビュー工程が無い。翻訳で化けた固有名詞
(ペク・ジヘン/体ポハゲッソ)は factcheck でも機械ゲートでも漏れうるため、
人が数十秒で目を通せる最低限の網を置く。表記ガードが反応した記事には ⚠ を付けて先頭に並べる。

  venv_kpi/bin/python3 tools/audit/daily_title_digest.py            # 送信
  venv_kpi/bin/python3 tools/audit/daily_title_digest.py --dry-run  # 標準出力のみ
"""
import argparse
import base64
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.notation_guard import check_notation  # noqa: E402

JST = timezone(timedelta(hours=9))
RO = ["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-ro", "db", "query"]
SITE = "https://www.kpopjournal.tokyo"
CHUNK = 1800


def fetch(day):
    start = day.strftime("%Y-%m-%d 00:00:00")
    end = (day + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    sql = ("SELECT ID, TO_BASE64(CONCAT(post_title, CHAR(1), post_content)) FROM wp_posts "
           "WHERE post_type='post' AND post_status='publish' "
           f"AND post_date >= '{start}' AND post_date < '{end}' ORDER BY post_date")
    out = subprocess.run(RO + [sql], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines()[1:]:
        if "\t" not in line:
            continue
        pid, b = line.split("\t", 1)
        # wp-ro は長い値に リテラル\n を挟む([[wp-ro-db-query-header-literal-newline-trap]])
        t, _, body = base64.b64decode(b.replace("\\n", "")).decode("utf-8").partition("\x01")
        rows.append((int(pid), t, body))
    return rows


def build(day, rows):
    flagged, plain = [], []
    for pid, t, body in rows:
        iss = check_notation(t, body)
        if iss:
            flagged.append(f"⚠ {t}\n   {iss[0]['detail']}\n   {SITE}/?p={pid}")
        else:
            plain.append(f"・{t}")
    head = f"{day:%m/%d} 公開 {len(rows)}本(表記ガード反応 {len(flagged)}本)"
    return head, flagged + plain


def chunks(lines):
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > CHUNK:
            yield buf
            buf = ""
        buf += ln + "\n"
    if buf:
        yield buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", help="YYYY-MM-DD(既定: 昨日 JST)")
    a = ap.parse_args()
    day = (datetime.strptime(a.date, "%Y-%m-%d") if a.date
           else datetime.now(JST).replace(tzinfo=None) - timedelta(days=1))
    head, lines = build(day, fetch(day))
    parts = list(chunks(lines or ["(公開なし)"]))
    if a.dry_run:
        print(head)
        print("\n---\n".join(parts))
        return 0
    from lib.discord_channel_router import ChannelType, send_to_channel
    for i, p in enumerate(parts, 1):
        title = f"📰 前日公開タイトル {head}" + (f" ({i}/{len(parts)})" if len(parts) > 1 else "")
        send_to_channel(ChannelType.MORNING, title, p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
