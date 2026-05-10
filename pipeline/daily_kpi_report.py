#!/usr/bin/env python3
"""日次KPIレポート (2026-05-10)

毎日 22:00 JST 実行 (21:00観測の後):
1. analyze_x_kpi で engagement_trend 分析
2. テンプレ刷新前後 (5/10朝 cutoff) の比較サマリ
3. 結果をDiscord+JSONLに出力

Cron: 0 22 * * * cd /home/aiuser/kpop-ai-system && python3 pipeline/daily_kpi_report.py
"""
import os
import sys
import json
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from lib.kpi_analyzer import analyze_x_kpi

DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '')
LOG_PATH = '/home/aiuser/kpop-ai-system/logs/daily_kpi_report.jsonl'

# テンプレ刷新時刻 (commit 4344f49: 5/10 14:00 ごろ)
TEMPLATE_REVAMP_CUTOFF = datetime(2026, 5, 10, 14, 0)


def quick_template_compare():
    """ローカル簡易比較 (Claude analyzerと別 — sample size少なくてもOK)"""
    old, new = [], []
    old_best, new_best = [], []
    with open('/home/aiuser/kpop-ai-system/logs/x_kpi.jsonl') as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get('dry_run'): continue
                ts = datetime.fromisoformat(d['ts'].replace('+09:00',''))
                imp = d.get('total_impressions', 0)
                best = (d.get('best_tweet') or {}).get('impressions', 0)
                if imp == 0: continue
                if ts < TEMPLATE_REVAMP_CUTOFF:
                    old.append(imp); old_best.append(best)
                else:
                    new.append(imp); new_best.append(best)
            except: pass
    return {
        'old': {'count': len(old),
                'imp_avg': sum(old)/len(old) if old else 0,
                'best_avg': sum(old_best)/len(old_best) if old_best else 0,
                'imp_max': max(old) if old else 0},
        'new': {'count': len(new),
                'imp_avg': sum(new)/len(new) if new else 0,
                'best_avg': sum(new_best)/len(new_best) if new_best else 0,
                'imp_max': max(new) if new else 0},
    }


def post_discord(message: str):
    if not DISCORD_WEBHOOK: return
    try:
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=json.dumps({'content': message[:2000]}).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def main():
    # 1. local quick compare
    cmp = quick_template_compare()

    # 2. Claude engagement_trend分析 (chart付き)
    trend = analyze_x_kpi(focus='engagement_trend')
    insight_text = trend.get('summary', '')
    if 'ANALYSIS RESULT' in insight_text:
        idx = insight_text.find('ANALYSIS RESULT')
        insight = insight_text[idx:idx+1500]
    else:
        insight = '(analysis incomplete)'

    # 3. Discordレポート
    msg_lines = [
        f"📊 **Daily KPI Report** ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "",
        f"**テンプレ刷新前後比較** (cutoff: {TEMPLATE_REVAMP_CUTOFF:%m/%d %H:%M}):",
        f"- 旧 ({cmp['old']['count']}obs): avg_imp={cmp['old']['imp_avg']:.1f} / best_avg={cmp['old']['best_avg']:.1f} / max={cmp['old']['imp_max']}",
        f"- 新 ({cmp['new']['count']}obs): avg_imp={cmp['new']['imp_avg']:.1f} / best_avg={cmp['new']['best_avg']:.1f} / max={cmp['new']['imp_max']}",
        "",
    ]
    if cmp['new']['count'] >= 6:
        diff = cmp['new']['imp_avg'] - cmp['old']['imp_avg']
        sign = '+' if diff > 0 else ''
        msg_lines.append(f"**判定**: 新テンプレ avg_imp {sign}{diff:.1f} ({cmp['new']['count']}obs)")
    else:
        msg_lines.append(f"**判定**: 新テンプレ観測不足 ({cmp['new']['count']}/6 obs) — もう少し待機")
    msg_lines.append("")
    msg_lines.append("**Claude分析**:")
    msg_lines.append(insight[:800])

    msg = '\n'.join(msg_lines)
    post_discord(msg)
    print(msg)

    # 4. JSONL保存
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now().isoformat(),
            'template_compare': cmp,
            'analysis_excerpt': insight[:500],
            'charts': trend.get('charts', []),
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
