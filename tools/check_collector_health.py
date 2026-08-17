#!/usr/bin/env python3
"""コレクタの健全性を一覧し、無言で0件死しているものを検出する(2026-08-17設置)。

背景:
  koreaherald がサイト構造変更で正規表現に1件もマッチせず、**0件のまま無言で
  死んでいた**(commit c1b5de0 で根治)。0件でもログに何も出さないため気付けなかった。
  点検で同じ状態が更に2件見つかった(wowkorea / starnews)。偶然見つけただけで、
  仕組みが無ければ次も気付けない。

  lib/collectors/korean_base.py::save_signals が毎回の件数を
  logs/collector_health.jsonl に記録するようにしたので、本ツールがそれを集計する。

判定:
  「今回0件」は異常でない(深夜で新着なし・全部重複などがある)。
  **ZERO_ALERT_THRESHOLD 回連続で0件**なら壊れていると判断する。
  判定は重複除去**前**の候補件数で行う(除去後0件は正常な再取得)。

usage:
  python3 tools/check_collector_health.py             # 一覧+異常があればDiscord通知
  python3 tools/check_collector_health.py --dry-run   # 通知せず一覧のみ
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))

# 同じ故障で毎日鳴らさないための sentinel(故障の組み合わせが変わったら再通知)。
SENTINEL = Path.home() / ".kpop_recovery" / ".collector_health_alerted"


# K-POPニュースのシグナルではないもの(チケット在庫収集)。
# ticket_collector が pia/tickebo/eplus/ltike を扱うが、これは
# lib/ticket_signals_to_event_input.py 経由でイベント情報に使われる別系統で、
# 常時シグナルが出るものではない。本チェックの対象外にする。
NON_NEWS_SOURCES = {"pia", "tickebo", "eplus", "ltike"}

# 既知の故障で、修理を保留すると判断したもの(理由はコレクタ側に明記)。
# 毎日鳴らすと本当の新規故障が埋もれるため通知対象から外すが、一覧では表示する。
KNOWN_BROKEN = {
    # starnews: Naver検索が意図した媒体を返しておらず設計自体が破綻。
    # パターン修正では直らない(lib/collectors/starnews_collector.py 参照)。
    "starnews",
}


def known_collectors() -> list[str]:
    """実装が存在するコレクタの source_id を集める。

    ファイル名と source_id は一致しない(sportsseoul_collector.py →
    'sports_seoul')ので、コード中の source_id 文字列から拾う。
    """
    import re
    out = set()
    for p in sorted((BASE / "lib" / "collectors").glob("*_collector.py")):
        src = p.read_text(encoding="utf-8", errors="ignore")
        # save_signals(..., source_id='xxx') を最優先(健全性記録に使う実際の値)
        m = re.search(r"save_signals\([^)]*source_id=['\"]([^'\"]+)['\"]", src)
        if m:
            out.add(m.group(1))
            continue
        for v in re.findall(r"['\"]source_id['\"]:\s*['\"]([^'\"]+)['\"]", src):
            out.add(v)
        for v in re.findall(r"make_signal\(\s*['\"]([^'\"]+)['\"]", src):
            out.add(v)
    return sorted(out - NON_NEWS_SOURCES)


def report() -> dict:
    from lib.collectors.korean_base import (consecutive_zero_count,
                                            ZERO_ALERT_THRESHOLD,
                                            COLLECT_HEALTH)
    # 直近の実収集量(参考値): trend_signals から48h分を数える
    recent: dict[str, int] = {}
    cut = (datetime.now() - timedelta(hours=48)).isoformat()
    try:
        with open(BASE / "data" / "trend_signals.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("timestamp", "") >= cut:
                    sid = d.get("source_id")
                    recent[sid] = recent.get(sid, 0) + 1
    except OSError:
        pass

    rows = []
    for sid in known_collectors():
        zeros = consecutive_zero_count(sid)
        n48 = recent.get(sid, 0)
        # 2026-08-17: 連続0件の閾値だけでは、ガード導入直後(記録が1回しかない)に
        # 実際に壊れているコレクタを「ok」と表示してしまう(実測: wowkorea/starnews)。
        # 「直近48hのシグナルが0 かつ 最後の収集も0件」なら、記録の浅さに関わらず
        # 死亡疑いとして出す。閾値待ちで見逃さないため。
        suspect_dead = (n48 == 0 and zeros >= 1)
        rows.append({
            "source_id": sid,
            "consecutive_zeros": zeros,
            "signals_48h": n48,
            "broken": zeros >= ZERO_ALERT_THRESHOLD or suspect_dead,
            "suspect_dead": suspect_dead,
            # 記録が無く48hシグナルも0 = ガード導入後まだ走っていない(判定不能)
            "unknown": zeros == 0 and n48 == 0,
        })
    rows.sort(key=lambda r: (-r["consecutive_zeros"], r["source_id"]))
    return {"threshold": ZERO_ALERT_THRESHOLD,
            "health_log": str(COLLECT_HEALTH),
            "collectors": rows,
            "broken": [r["source_id"] for r in rows if r["broken"]],
            "suspect": [r["source_id"] for r in rows if r["unknown"]]}


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
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    r = report()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"=== コレクタ健全性 (連続0件 {r['threshold']}回以上で異常) ===")
        for c in r["collectors"]:
            if c["broken"]:
                mark = "✗異常"
            elif c["unknown"]:
                mark = "?不明"
            else:
                mark = "  ok "
            print(f" {mark} {c['source_id']:16s} 連続0件={c['consecutive_zeros']:2d} "
                  f"48hシグナル={c['signals_48h']:3d}")
        if r["suspect"]:
            print(f"\n  ?不明 = ガード導入後まだ走っていない、または48hシグナルが0。"
                  f"cronで走るまで判定できない: {', '.join(r['suspect'])}")

    if not r["broken"]:
        print("\n→ 壊れているコレクタはありません")
        SENTINEL.unlink(missing_ok=True)
        return 0

    # 既知の保留分は通知しない(本当の新規故障を埋もれさせないため)
    new_broken = [b for b in r["broken"] if b not in KNOWN_BROKEN]
    if not new_broken:
        print(f"(すべて既知の保留分: {', '.join(r['broken'])} — 通知しない)")
        return 0
    key = ",".join(sorted(new_broken))
    msg = ("⚠️ **コレクタが無言で0件になっています**\n"
           f"対象: {', '.join(new_broken)}\n"
           f"({r['threshold']}回連続で収集0件。HTML構造変更/403の可能性)\n"
           "`python3 tools/check_collector_health.py` で詳細、"
           "個別に実行して抽出パターンを確認してください。")
    print(f"\n→ 異常: {', '.join(r['broken'])}")
    if args.dry_run:
        print("(--dry-run: 通知しない)")
        return 0
    # 故障の組み合わせが同じなら再通知しない(毎日鳴らして無視されるのを防ぐ)
    prev = SENTINEL.read_text().strip() if SENTINEL.exists() else ""
    if prev == key:
        print("(同じ故障で既に通知済み — 再通知しない)")
        return 0
    if notify(msg):
        SENTINEL.parent.mkdir(exist_ok=True)
        SENTINEL.write_text(key)
        print("→ Discord に通知しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
