#!/usr/bin/env python3
"""koreaherald の除外を解除できるかを自動判定する(2026-08-17 設置)。

背景:
  koreaherald の収集は 2026-08-17 に根治した(commit c1b5de0。見出しを
  <p class="news_title"> から1件ずつ取るよう修正し、実HTMLで0件→25件)。
  しかし data/trend_signals.jsonl には修正前に書かれた壊れた行が残っており、
  実測で13件中11件が下流ガードをすり抜けた
  (「6 Twice's Jeongyeon leaves JYP…」「…collab Most Read K-pop」等)。
  そのため lib/x_trend_topics.py の UNRELIABLE_SOURCES で除外を継続している。

  壊れた行は鮮度窓(DEFAULT_WINDOW_H=48h)から自然に抜ける。抜けたら除外を
  解除してよいが、「48時間後に手で確認する」は忘れるので自動判定にする。

判定:
  鮮度窓内の koreaherald シグナルすべてが、除外なしでも安全に扱えるか
  (= _is_concatenated / _is_roundup をすり抜ける壊れた見出しが無いか)を見る。
  安全なら「解除可能」と報告し、Discord に一度だけ通知する。

usage:
  python3 tools/check_koreaherald_unblock.py             # 判定して必要なら通知
  python3 tools/check_koreaherald_unblock.py --dry-run   # 通知せず判定のみ
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))

# 同じ内容で毎朝鳴らさないための sentinel。解除作業をすれば不要になる。
SENTINEL = Path.home() / ".kpop_recovery" / ".koreaherald_unblock_notified"


def check() -> dict:
    """鮮度窓内の koreaherald シグナルを検査して判定結果を返す。"""
    from lib.x_trend_topics import (load_recent_signals, _clean_title,
                                    _is_concatenated, _is_roundup,
                                    UNRELIABLE_SOURCES)
    sigs = [s for s in load_recent_signals()
            if s.get("source_id") == "koreaherald"]
    leaks = []
    for s in sigs:
        t = _clean_title(s.get("title"))
        if not (_is_concatenated(t) or _is_roundup(t)):
            # ガードをすり抜ける = 壊れていても下流に流れてしまう行。
            # 修理後の正常な見出しもここに来るため、壊れているかは別途判定する。
            if _looks_broken(t):
                leaks.append(t)
    return {
        "still_excluded": "koreaherald" in UNRELIABLE_SOURCES,
        "signals_in_window": len(sigs),
        "broken_leaks": leaks,
        "can_unblock": "koreaherald" in UNRELIABLE_SOURCES and not leaks,
    }


def _looks_broken(title: str) -> bool:
    """修正前の壊れた見出しの特徴を持つか。

    修正後は「1記事=1見出し」になるため、以下は壊れた行にしか出ない:
      - 先頭に一覧の順位番号がある(「6 Twice's Jeongyeon leaves…」)
      - 末尾にサイトのUI文言が続く(「…collab Most Read K-pop」)
      - セクションラベルが文中に紛れる(「Weekender For these musicians…」)
    """
    import re
    t = str(title or "")
    if re.match(r"^\s*\d{1,2}\s+[A-Z\[]", t):
        return True
    if re.search(r"(?:Most Read|Recommended|From the Scene|KH Explains|Weekender)", t):
        return True
    # 80字での切断痕。長い見出しは正常でも存在するので、長さだけでは判定できない
    # (例: 「Ex-CN Blue member Lee Jong-hyun halts SNS return after…8-year hiatus」は正常)。
    # 切断の実際の印は **末尾の単語が語として成立していない** こと。
    # 実例「…tops 300m Spotify strea」= streams が strea で切れている。
    # 切断痕の確実な指標: 壊れた行は clean_title の上限で **ちょうど80字** になる。
    # 実測(壊れ11件 / 修理後25件)で長さ分布がきれいに分かれた:
    #   壊れ  : 59, 71, 74, 74, 74, 80, 80, 80, 80, 80, 80  ← 80で頭打ち
    #   修理後: 54, 57, 72, 82, 86 ...                      ← 80を超えられる
    # 末尾語が英単語として成立するかで判定しようとしたが、この環境に辞書が無く
    # (/usr/share/dict は空)、ホワイトリスト方式では誤検知が出た(1/25)。
    # 「80字ちょうど」は切断そのものの痕跡なので、こちらが確実。
    # 偶然80字ちょうどの正常見出しも壊れ扱いになる(実測で25件中1件)。
    # 誤検知の結果は「解除を1日見送る」だけなので、検出漏れより安全側。
    # 検出漏れは実測0件(既存の壊れ13件すべてを捕捉)。
    if len(t) == 80:
        return True
    return False


def notify(msg: str) -> bool:
    try:
        import urllib.request
        from lib.resolve_discord_webhook import resolve, DISCORD_USER_AGENT
        url = resolve("urgent_errors")
        if not url:
            return False
        req = urllib.request.Request(
            url, data=json.dumps({"content": msg}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": DISCORD_USER_AGENT})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="通知せず判定のみ")
    args = ap.parse_args()

    r = check()
    if not r["still_excluded"]:
        print("[koreaherald] 既に解除済み — このチェックは不要 "
              "(tools/check_koreaherald_unblock.py と cron を削除してよい)")
        return 0

    print(f"[koreaherald] 鮮度窓内シグナル {r['signals_in_window']}件 / "
          f"壊れた行のすり抜け {len(r['broken_leaks'])}件")
    for t in r["broken_leaks"][:5]:
        print(f"  残存: {t[:80]}")

    if not r["can_unblock"]:
        # 「まだ解除しない」は正常な状態なので exit 0。非ゼロを返すと cron や
        # 監視が異常として拾い、本当の障害と区別できなくなる。
        print("→ まだ解除しない(壊れた行が鮮度窓に残っている)")
        return 0

    msg = ("✅ **koreaherald の除外を解除できます**\n"
           "壊れたシグナルが鮮度窓(48h)から抜けました。\n"
           "`lib/x_trend_topics.py` の `UNRELIABLE_SOURCES` を `()` にして、\n"
           "`python3 -m pytest tests/ -q --ignore=tests/e2e` と "
           "`python3 lib/x_trend_topics.py` で確認してください。\n"
           "(解除後は本チェックの cron `koreaherald-unblock-check` を削除)")
    print("→ 解除可能")
    if args.dry_run:
        print("(--dry-run: 通知しない)")
        return 0
    if SENTINEL.exists():
        print("(既に通知済み — 再通知しない)")
        return 0
    if notify(msg):
        SENTINEL.parent.mkdir(exist_ok=True)
        SENTINEL.touch()
        print("→ Discord に通知しました")
    else:
        print("→ Discord 通知に失敗(判定自体は解除可能)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
