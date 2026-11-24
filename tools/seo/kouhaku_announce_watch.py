#!/usr/bin/env python3
"""紅白2026 出場歌手発表の検知 → Discord通知(2026-11-12 作成・期間限定)。

目的: 年末授賞式ハブの後継として、紅白のK-POP出場者ハブを【発表当日】に公開する。
     下書き = reports/event_articles/kouhaku-2026-kpop-hub-draft.html
     過去の当日追記は2日遅れが続いた([[pending-yearend-awards-hub-followups]])ので、人が見に行かなくても気づけるようにする。

検知: Google ニュース RSS で「紅白 出場歌手」を検索し、今日(JST)公開の見出しに
     「第77回」or「紅白」+「出場歌手」+(発表|決定|一覧) が2本以上あれば発表ありとみなす。
     内定報道(「内定」を含む見出し)は数えない。
一度通知したら data/kouhaku_announce_notified.json を書いて以後は黙る。
11/25 を過ぎたら何もしない(cron 撤去忘れでも害が出ない)。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARKER = os.path.join(BASE, "data", "kouhaku_announce_notified.json")
JST = timezone(timedelta(hours=9))
END = datetime(2026, 11, 25, tzinfo=JST)
QUERY = "紅白 出場歌手"
RSS = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
    {"q": QUERY, "hl": "ja", "gl": "JP", "ceid": "JP:ja"})


def is_announcement(title: str) -> bool:
    if any(w in title for w in ("内定", "予想", "第76回", "2025", "歴代")):
        return False
    return ("紅白" in title and "出場歌手" in title
            and re.search(r"発表|決定|一覧|初出場", title) is not None)


def fetch_items():
    req = urllib.request.Request(RSS, headers={"User-Agent": "Mozilla/5.0 (kpop-kouhaku-watch/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(JST)
        except Exception:
            continue
        yield title, link, pub


def notify_discord(text: str) -> bool:
    try:
        url = subprocess.run(
            [sys.executable, os.path.join(BASE, "lib/resolve_discord_webhook.py"), "alert_summary"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if not url.startswith("https://discord.com/api/webhooks/"):
            print("WARN: webhook解決失敗、通知スキップ", file=sys.stderr)
            return False
        body = json.dumps({"content": text[:1900]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "kpop-kouhaku-watch/1.0 (github.com/kpop-ai-system)"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"WARN: Discord通知失敗: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="通知・マーカー書込をしない")
    ap.add_argument("--any-day", action="store_true", help="今日以外の記事も数える(動作確認用)")
    args = ap.parse_args()

    now = datetime.now(JST)
    if now > END:
        print("期間終了(11/25以降)。何もしない")
        return 0
    if os.path.exists(MARKER) and not args.dry_run:
        print("通知済み。何もしない")
        return 0

    hits = [(t, l, p) for t, l, p in fetch_items()
            if is_announcement(t) and (args.any_day or p.date() == now.date())]
    print(f"{now:%Y-%m-%d %H:%M} 該当見出し {len(hits)} 本")
    for t, _, p in hits[:8]:
        print(f"  {p:%m/%d %H:%M} {t}")
    if len(hits) < 2:
        return 0

    msg = ("🎤 **紅白2026の出場歌手が発表されたようです**(ニュース見出し{}本)\n".format(len(hits))
           + "\n".join(f"・{t}" for t, _, _ in hits[:5])
           + "\n\n→ 今日中に K-POP出場者ハブを公開。下書き: reports/event_articles/kouhaku-2026-kpop-hub-draft.html"
           + "(冒頭コメントの公開手順どおり。【要記入】を全部埋めてから)"
           + "\n→ 年末番組まとめ post 27641 の紅白の節にもK-POP出場者を追記し、紅白ハブへリンク")
    if args.dry_run:
        print("--- dry-run 通知文 ---\n" + msg)
        return 0
    if notify_discord(msg):
        tmp = MARKER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"notified_at": now.isoformat(), "titles": [t for t, _, _ in hits[:10]]},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, MARKER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
