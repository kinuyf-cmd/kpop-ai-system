"""Anthropic API cost guard — 予防的サーキットブレーカー + 日次予算アラート

このモジュールは Anthropic API 呼出経路に挿入する軽量フックを提供する。

機能:
1. **Kill switch** (`ANTHROPIC_DISABLE=1` env): 緊急時に全 Claude 呼出を即停止。
2. **Test mode skip** (`KPJ_TEST_MODE=1`): pytest 経由の実 API call を遮断。
3. **日次 budget cap** (default $10): 超過したら warning ログ + Discord 通知 (block はしない)。
4. **rate anomaly detection** (1h 内 200 call 超過): warning ログ + Discord 通知。
5. **call ledger 自動記録**: usage を data/cost_ledger.jsonl に追記。

使い方:
    from lib.anthropic_cost_guard import guard_before_call, log_usage

    # 呼出直前
    if not guard_before_call('factcheck_v2'):
        return _fallback_result()  # kill switch or test mode

    response = client.messages.create(...)
    log_usage('factcheck_v2', model='claude-sonnet-4-6', usage=response.usage)

設計判断:
- guard_before_call は exception を投げず bool を返す (品質低下を防ぐ責任は caller 側)。
- 予算超過は warning のみで block しない (品質維持優先)。緊急停止は kill switch で手動。
- Discord 通知は 1h に1回 (rate limit)。
"""
from __future__ import annotations
import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

LEDGER_PATH = Path('/home/aiuser/kpop-ai-system/data/cost_ledger.jsonl')
ALERT_STATE_PATH = Path('/home/aiuser/kpop-ai-system/data/anthropic_alert_state.json')

# 1 MTok あたりの USD (Claude pricing 2026-05 時点)
PRICING = {
    'claude-sonnet-4-6': {'input': 3.0, 'output': 15.0, 'cache_write_5m': 3.75,
                          'cache_write_1h': 6.0, 'cache_read': 0.30},
    # 2026-07-15: Sonnet 5 移行。導入価格は $2/$10 (~2026-08-31) だが、予算アラートは
    # 保守側 (高め計上でアラートが早く鳴る) が安全なため正規価格 $3/$15 で計上。
    # 正規化後も 4.6 と同額のためアラート閾値の再調整は不要。
    'claude-sonnet-5':   {'input': 3.0, 'output': 15.0, 'cache_write_5m': 3.75,
                          'cache_write_1h': 6.0, 'cache_read': 0.30},
    'claude-haiku-4-5':  {'input': 1.0, 'output': 5.0, 'cache_write_5m': 1.25,
                          'cache_write_1h': 2.0, 'cache_read': 0.10},
    'claude-opus-4-7':   {'input': 15.0, 'output': 75.0, 'cache_write_5m': 18.75,
                          'cache_write_1h': 30.0, 'cache_read': 1.50},
}

# 閾値 (env で上書き可能)
DAILY_BUDGET_USD = float(os.environ.get('ANTHROPIC_DAILY_BUDGET_USD', '10.0'))
HOURLY_CALL_LIMIT = int(os.environ.get('ANTHROPIC_HOURLY_CALL_LIMIT', '200'))
ALERT_COOLDOWN_SEC = 3600  # 同種アラートは 1h に 1 回まで

log = logging.getLogger(__name__)


def _is_disabled() -> bool:
    """緊急 kill switch / test mode 判定"""
    return (
        os.environ.get('ANTHROPIC_DISABLE') == '1'
        or os.environ.get('KPJ_TEST_MODE') == '1'
    )


def _today_jst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def _today_usd() -> float:
    """本日 (JST) の累計コスト"""
    if not LEDGER_PATH.exists():
        return 0.0
    today = _today_jst()
    total = 0.0
    try:
        with open(LEDGER_PATH, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('date') == today:
                        total += float(d.get('cost_usd', 0))
                except Exception:
                    continue
    except OSError:
        return 0.0
    return total


def _recent_calls(hours: int = 1) -> int:
    """直近 N 時間の API call 件数"""
    if not LEDGER_PATH.exists():
        return 0
    cutoff = time.time() - hours * 3600
    n = 0
    try:
        with open(LEDGER_PATH, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('ts_epoch', 0) >= cutoff:
                        n += 1
                except Exception:
                    continue
    except OSError:
        return 0
    return n


def _load_alert_state() -> dict:
    if not ALERT_STATE_PATH.exists():
        return {}
    try:
        return json.loads(ALERT_STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_alert_state(state: dict) -> None:
    try:
        ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_PATH.write_text(json.dumps(state), encoding='utf-8')
    except OSError:
        pass


def _maybe_alert(kind: str, message: str) -> None:
    """同種アラートは 1h に 1 回まで Discord に通知"""
    state = _load_alert_state()
    last = state.get(kind, 0)
    if time.time() - last < ALERT_COOLDOWN_SEC:
        return
    state[kind] = time.time()
    _save_alert_state(state)
    # ログには必ず出す
    log.warning(f'[anthropic_cost_guard] {kind}: {message}')
    # Discord 通知 (best-effort, 失敗してもブロックしない)
    try:
        from lib.discord_channel_router import send_to_channel, ChannelType
        send_to_channel(ChannelType.ERROR, f'⚠️ Anthropic cost guard\n{kind}: {message}')
    except Exception:
        pass


def guard_before_call(caller: str) -> bool:
    """API 呼出直前のゲート判定

    Returns:
        True: 呼出してよい
        False: skip 必須 (kill switch / test mode)

    予算超過/rate超過は warning だけ出して True を返す (品質維持優先)。
    """
    if _is_disabled():
        return False

    # 予算チェック (warning のみ、block しない)
    today_usd = _today_usd()
    if today_usd > DAILY_BUDGET_USD:
        _maybe_alert(
            f'budget_exceeded_{_today_jst()}',
            f'本日累計 ${today_usd:.2f} が予算 ${DAILY_BUDGET_USD:.2f} を超過 '
            f'(caller={caller})。原因調査推奨。',
        )

    # rate チェック (1h)
    n_recent = _recent_calls(hours=1)
    if n_recent > HOURLY_CALL_LIMIT:
        _maybe_alert(
            'rate_anomaly',
            f'直近1h で {n_recent} call (上限 {HOURLY_CALL_LIMIT}) — '
            f'cron 暴走の可能性 (caller={caller})。',
        )

    return True


def _calc_cost(model: str, usage_dict: dict) -> float:
    """usage dict から USD 計算"""
    if not isinstance(usage_dict, dict):
        return 0.0
    p = PRICING.get(model, PRICING['claude-sonnet-4-6'])
    inp = usage_dict.get('input', usage_dict.get('input_tokens', 0))
    out = usage_dict.get('output', usage_dict.get('output_tokens', 0))
    cw5 = usage_dict.get('cache_create_5m', 0)
    cw1 = usage_dict.get('cache_create_1h', usage_dict.get('cache_create', 0))
    cr = usage_dict.get('cache_read', usage_dict.get('cache_read_input_tokens', 0))
    cost = (
        inp * p['input'] + out * p['output']
        + cw5 * p['cache_write_5m'] + cw1 * p['cache_write_1h']
        + cr * p['cache_read']
    ) / 1_000_000
    return round(cost, 6)


def log_usage(caller: str, model: str, usage) -> None:
    """API call の usage を ledger に追記

    Args:
        caller: 呼出元識別 ('factcheck_v2', 'translator_v2', ...)
        model: モデル名
        usage: anthropic Response.usage (オブジェクト or dict)
    """
    try:
        # usage は anthropic SDK Response 由来 (属性アクセス) or dict
        if hasattr(usage, 'input_tokens'):
            u = {
                'input': usage.input_tokens,
                'output': usage.output_tokens,
                'cache_create': getattr(usage, 'cache_creation_input_tokens', 0),
                'cache_read': getattr(usage, 'cache_read_input_tokens', 0),
            }
        elif isinstance(usage, dict):
            u = usage
        else:
            return
        cost = _calc_cost(model, u)
        rec = {
            'ts_epoch': time.time(),
            'ts': datetime.now(timezone.utc).isoformat(),
            'date': _today_jst(),
            'caller': caller,
            'model': model,
            'usage': u,
            'cost_usd': cost,
        }
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        # 記録失敗は呼出側を壊さない (品質維持優先)
        pass


def daily_summary() -> dict:
    """本日 (JST) の集計を返す — モニタリング用"""
    today = _today_jst()
    by_caller = {}
    total_cost = 0.0
    total_calls = 0
    if LEDGER_PATH.exists():
        try:
            with open(LEDGER_PATH, encoding='utf-8') as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        if d.get('date') != today:
                            continue
                        total_calls += 1
                        total_cost += float(d.get('cost_usd', 0))
                        caller = d.get('caller', '?')
                        c = by_caller.setdefault(caller, {'calls': 0, 'cost': 0.0})
                        c['calls'] += 1
                        c['cost'] += float(d.get('cost_usd', 0))
                    except Exception:
                        continue
        except OSError:
            pass
    return {
        'date': today,
        'total_calls': total_calls,
        'total_cost_usd': round(total_cost, 4),
        'budget_usd': DAILY_BUDGET_USD,
        'over_budget': total_cost > DAILY_BUDGET_USD,
        'by_caller': by_caller,
    }


def _format_summary_for_discord(s: dict) -> tuple[str, str]:
    """daily_summary を Discord 通知用の (title, body) に整形"""
    icon = '🚨' if s['over_budget'] else '💰'
    title = f"{icon} Claude API 日次コスト {s['date']}"
    lines = [
        f"**total calls**: {s['total_calls']:,}",
        f"**total cost**: ${s['total_cost_usd']:.2f} / budget ${s['budget_usd']:.2f}",
        '',
        '**caller breakdown** (cost desc):',
    ]
    callers = sorted(s['by_caller'].items(), key=lambda kv: -kv[1]['cost'])
    for caller, stats in callers[:10]:
        lines.append(f"  - `{caller}`: {stats['calls']} calls / ${stats['cost']:.4f}")
    if not callers:
        lines.append('  (本日は cost_ledger に記録なし — まだ Anthropic 呼出なし)')
    return title, '\n'.join(lines)


def send_daily_summary_to_discord(force: bool = False) -> bool:
    """日次サマリを Discord に push (cron から実行)

    Args:
        force: True なら通常モード (MORNING channel)、
               False で予算超過時のみ ERROR channel に通知

    Returns:
        通知成功 True / 失敗 False (best-effort)
    """
    s = daily_summary()
    if not force and not s['over_budget'] and s['total_calls'] == 0:
        # 通常時で call なしの日は通知しない (低 SN ratio 回避)
        return False
    title, body = _format_summary_for_discord(s)
    try:
        from lib.discord_channel_router import send_to_channel, ChannelType
        channel = ChannelType.ERROR if s['over_budget'] else ChannelType.MORNING
        send_to_channel(channel, title, body)
        return True
    except Exception as e:
        log.warning(f'discord notify failed: {e}')
        return False


if __name__ == '__main__':
    # CLI: 本日の集計を表示 + Discord 通知
    import pprint
    s = daily_summary()
    pprint.pprint(s)
    # cron 経由実行時は強制通知 (毎朝 8:30 cron で当日累計を見たい)
    send_daily_summary_to_discord(force=True)
