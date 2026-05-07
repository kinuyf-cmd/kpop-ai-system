"""イベント/カムバックJSON出力の健全性チェック+アラート

build_events.py / build_comebacks.py の最後に呼ばれ、出力件数0件が
連続した場合に Discord へ警告。silent rot (静かな腐敗) の再発防止。

経緯: 2026-04-24 の build_events.py 厳格化で 0件出力が約2週間継続したが、
UIが空状態を表示するだけで誰も気づかなかった。memory rule
「再発防止の徹底」(設定JSON+共通lib+学習対象+error_patterns 4層) の共通lib層。
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path('/home/aiuser/kpop-ai-system')
HEALTH_LOG = BASE / 'logs' / 'event_data_health.jsonl'
JST = timezone(timedelta(hours=9))


def record_and_alert(builder: str, output_path: str, item_count: int, *, dry_run: bool = False) -> dict:
    """ビルダー出力を記録し、必要ならDiscord通知

    Args:
        builder: 'events' or 'comebacks'
        output_path: 書き出した JSON のパス (ログ用)
        item_count: 出力件数

    Returns:
        {'alerted': bool, 'reason': str|None}
    """
    HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'ts': datetime.now(JST).isoformat(),
        'builder': builder,
        'output': output_path,
        'count': item_count,
    }
    with open(HEALTH_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    if item_count > 0:
        return {'alerted': False, 'reason': None}

    consecutive = _consecutive_zero_count(builder)
    if consecutive < 2:
        return {'alerted': False, 'reason': f'first/single zero (consecutive={consecutive})'}

    msg = (
        f'{builder}.json 出力 0件 が {consecutive} 回連続。\n'
        f'data/{builder}_manual.json の手動キュレーション、または'
        f' tools/build_{builder}.py のシグナル抽出ロジックを確認してください。'
    )
    if dry_run:
        return {'alerted': False, 'reason': f'dry_run (would alert: {msg[:80]})'}

    try:
        from lib.discord_notifier import send_discord
        result = send_discord(
            channel='alert_summary',
            title=f'{builder}.json 0件継続 ({consecutive}回)',
            body=msg,
            color=0xFFA500,
            event_key=f'event_data_zero_output__{builder}',
            severity='WARNING',
        )
        return {'alerted': result == 'sent', 'reason': f'discord={result}: {msg[:80]}'}
    except Exception as e:
        return {'alerted': False, 'reason': f'discord notifier unavailable: {e}'}


def _consecutive_zero_count(builder: str) -> int:
    """直近のbuilder出力で末尾連続0件回数を返す"""
    if not HEALTH_LOG.exists():
        return 0
    consecutive = 0
    with open(HEALTH_LOG, encoding='utf-8') as f:
        rows = [json.loads(l) for l in f if l.strip()]
    for r in reversed(rows):
        if r.get('builder') != builder:
            continue
        if r.get('count', 0) == 0:
            consecutive += 1
        else:
            break
    return consecutive


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        b = sys.argv[1]
        c = int(sys.argv[2])
        print(record_and_alert(b, '<cli>', c, dry_run='--dry-run' in sys.argv))
    else:
        print('Usage: event_data_health.py <events|comebacks> <count> [--dry-run]')
