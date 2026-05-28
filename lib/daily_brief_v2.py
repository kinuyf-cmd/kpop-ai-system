"""daily_brief_v2.py — KPOP JOURNAL 朝/夕 2回ブリーフィング (2026-05-28)

KPI設定(config/kpi_targets.json)と実績を突き合わせ、達成率を可視化した
ブリーフィングを生成する。

実行モード:
  python3 lib/daily_brief_v2.py --mode morning   # 朝 9:00 想定
  python3 lib/daily_brief_v2.py --mode evening   # 夕 20:00 想定
  python3 lib/daily_brief_v2.py --mode morning --send   # Discordへ送信

朝(morning): 前日確定値の振り返り + 当日の方針
夕(evening): 当日途中経過 + 当日達成見込み + 翌朝までの宿題

差別化のため、夕ブリーフは「速報」「未公開のブロッカー」「途中達成率」中心。
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path('/home/aiuser/kpop-ai-system')
KPI_CFG = ROOT / 'config/kpi_targets.json'
PROCESSED = ROOT / 'data/auto_article_processed.jsonl'
PUBLISH_LOG = ROOT / 'logs/unified_publish.jsonl'
X_LOG = ROOT / 'logs/x_posts.jsonl'
KPI_DAILY = ROOT / 'data/kpi_daily.jsonl'
ROADMAP = Path('/home/aiuser/.kpop_recovery/roadmap_state.json')


def _load_targets() -> dict:
    if not KPI_CFG.exists():
        return {}
    return json.loads(KPI_CFG.read_text(encoding='utf-8')).get('daily', {})


def _count_processed(target_date: str) -> dict:
    """指定日(YYYY-MM-DD)の記事処理状況。"""
    pub = blocked = total = 0
    if not PROCESSED.exists():
        return {'published': 0, 'blocked': 0, 'total': 0, 'rate': 0}
    with PROCESSED.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get('ts', '').startswith(target_date):
                continue
            k = r.get('kind', '')
            if k in ('breaking', 'original'):
                pub += 1
                total += 1
            elif k == 'breaking_blocked':
                blocked += 1
                total += 1
    rate = (100 * pub // total) if total else 0
    return {'published': pub, 'blocked': blocked, 'total': total, 'rate': rate}


def _x_posts_count(target_date: str) -> int:
    if not X_LOG.exists():
        return 0
    n = 0
    with X_LOG.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get('ts', '') or r.get('timestamp', '')
            if ts.startswith(target_date) and r.get('status') in ('posted', 'success', 'ok'):
                n += 1
    return n


def _gsc_metrics(target_date: str) -> dict:
    """GSC・GA4・AdSense は kpi_daily.jsonl から取れれば取る。なければ空。"""
    if not KPI_DAILY.exists():
        return {}
    last = None
    with KPI_DAILY.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get('date') == target_date:
                last = r
    return last or {}


def _achievement(actual: float, target: float) -> tuple[str, int]:
    """実績/目標 から達成率(0-200%程度)と絵文字記号。"""
    if target <= 0:
        return '—', 0
    pct = int(100 * actual / target)
    if pct >= 100:
        return '✅', pct
    if pct >= 70:
        return '🟢', pct
    if pct >= 40:
        return '🟡', pct
    return '🔴', pct


def _kpi_row(label: str, actual, target, unit: str) -> str:
    """KPI 1行: '✅ articles 5/5本 (100%)' 形式。"""
    sym, pct = _achievement(actual, target)
    return f'{sym} {label}: {actual}/{target}{unit} ({pct}%)'


def _roadmap_status() -> str:
    if not ROADMAP.exists():
        return ''
    d = json.loads(ROADMAP.read_text(encoding='utf-8'))
    done = sum(1 for it in d.get('items', []) if it.get('status') == 'done')
    total = len(d.get('items', []))
    return f'{done}/{total}項目 done'


def _build_morning(now: date) -> str:
    yesterday = (now - timedelta(days=1)).isoformat()
    targets = _load_targets()
    proc = _count_processed(yesterday)
    x_n = _x_posts_count(yesterday)
    gsc = _gsc_metrics(yesterday)

    lines = []
    lines.append(f'## 📋 朝ブリーフ — {now.strftime("%Y-%m-%d")} (9:00 JST)')
    lines.append('')
    lines.append(f'### 昨日({yesterday}) のKPI実績')

    tgt_articles = (targets.get('articles_posted') or {}).get('target', 5)
    tgt_x = (targets.get('x_posts') or {}).get('target', 4)
    tgt_sessions = (targets.get('sessions') or {}).get('target', 500)
    tgt_pv = (targets.get('pageviews') or {}).get('target', 700)
    tgt_revenue = (targets.get('revenue_jpy') or {}).get('target', 200)
    tgt_clicks = (targets.get('gsc_clicks') or {}).get('target', 50)
    tgt_uptime = (targets.get('pipeline_uptime') or {}).get('target', 95)

    lines.append(_kpi_row('記事公開', proc['published'], tgt_articles, '本'))
    lines.append(_kpi_row('X投稿', x_n, tgt_x, '件'))
    lines.append(_kpi_row('Pipeline稼働率',
                          proc['rate'], tgt_uptime, '%'))
    if gsc.get('sessions') is not None:
        lines.append(_kpi_row('セッション', gsc.get('sessions', 0), tgt_sessions, ''))
    if gsc.get('pageviews') is not None:
        lines.append(_kpi_row('PV', gsc.get('pageviews', 0), tgt_pv, ''))
    if gsc.get('gsc_clicks') is not None:
        lines.append(_kpi_row('GSCクリック',
                              gsc.get('gsc_clicks', 0), tgt_clicks, ''))
    if gsc.get('adsense_revenue') is not None:
        lines.append(_kpi_row('AdSense収益',
                              int(gsc.get('adsense_revenue', 0)),
                              tgt_revenue, '円'))

    lines.append('')
    lines.append(f'### 公開停止内訳: {proc["blocked"]}件ゲート停止 (品質ゲート正常動作)')

    rm = _roadmap_status()
    if rm:
        lines.append(f'### ロードマップ: {rm}')

    lines.append('')
    lines.append('### 本日の方針')
    lines.append(f'- 速報パイプライン継続(目標 {tgt_articles}本/日)')
    lines.append(f'- X投稿 目標 {tgt_x}件/日(scheduler自動配信)')
    lines.append('- 公開率<30%でアラート発火(`publish_rate_alert.sh`)')
    lines.append('- 夕ブリーフ 17:00 で当日進捗を再確認')
    return '\n'.join(lines)


def _build_evening(now: date) -> str:
    today = now.isoformat()
    targets = _load_targets()
    proc = _count_processed(today)
    x_n = _x_posts_count(today)
    gsc = _gsc_metrics(today)

    lines = []
    lines.append(f'## 🌙 夕ブリーフ — {now.strftime("%Y-%m-%d")} (17:00 JST)')
    lines.append('')
    lines.append('### 本日途中経過')

    tgt_articles = (targets.get('articles_posted') or {}).get('target', 5)
    tgt_x = (targets.get('x_posts') or {}).get('target', 4)
    tgt_uptime = (targets.get('pipeline_uptime') or {}).get('target', 95)

    lines.append(_kpi_row('記事公開', proc['published'], tgt_articles, '本'))
    lines.append(_kpi_row('X投稿(累計)', x_n, tgt_x, '件'))
    lines.append(_kpi_row('Pipeline稼働率', proc['rate'], tgt_uptime, '%'))

    # 達成見込み: 17時時点から22時までを1日の運用終了と想定し、現在ペースで外挿
    hour_now = datetime.now().hour
    elapsed_ratio = max(hour_now / 22, 0.5)  # 22時を1日の運用終了と想定
    forecast = int(proc['published'] / max(elapsed_ratio, 0.01))
    lines.append(f'### 本日最終予測(22時時点): 約{forecast}本公開見込み')

    lines.append('')
    lines.append(f'### 停止内訳: {proc["blocked"]}件 (品質ゲート停止)')

    # 主要ブロック理由 top3
    if PROCESSED.exists():
        from collections import Counter
        reasons = Counter()
        with PROCESSED.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not r.get('ts', '').startswith(today):
                    continue
                if r.get('kind') != 'breaking_blocked':
                    continue
                reason = (r.get('reason') or '')[:80]
                # 特徴語抽出
                for keyword in ['letterbox', 'factcheck', '類似テーマ',
                                '本文が壊滅的', 'タイトル', '所属事務所',
                                'メンバー数', '日付']:
                    if keyword in reason:
                        reasons[keyword] += 1
                        break
                else:
                    reasons['その他'] += 1
        top = reasons.most_common(3)
        if top:
            lines.append('### 停止理由 top3')
            for k, v in top:
                lines.append(f'- {k}: {v}件')

    lines.append('')
    lines.append('### 翌朝(明朝)までの宿題')
    rm_status = _roadmap_status()
    if rm_status:
        lines.append(f'- ロードマップ: {rm_status} → 翌朝ブリーフで未着手項目を再確認')
    lines.append('- 深夜の自動投稿(7時の朝バッチで翌朝ブリーフに反映)')

    return '\n'.join(lines)


def _send_discord(text: str, channel: str = 'daily_ceo_report') -> int:
    """Discord webhook 経由で送信。チャネルが取れなければ stdout のみ。"""
    # discord_channels.sh と同じロジックで webhook を解決
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    cfg_path = ROOT / 'config/discord_webhooks.json'
    if not cfg_path.exists():
        return 0
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    raw = cfg.get(channel, '')
    url = os.path.expandvars(raw or '')
    if url.startswith('${') or not url:
        print('[brief] webhook 未設定、stdout のみ出力')
        return 0
    import urllib.request
    payload = json.dumps({'content': text[:1900]}).encode()
    # 2026-05-28: Cloudflare error 1010 回避。Python-urllib デフォUAが bot 判定で
    # 403になる(本日17:00夕ブリーフが送信失敗した直接原因)。明示UAで204成功。
    req = urllib.request.Request(url, data=payload,
                                 headers={'Content-Type': 'application/json',
                                          'User-Agent': 'KPOPJournalBot/1.0 (+https://www.kpopjournal.tokyo)'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except Exception as e:
        print(f'[brief] Discord 送信失敗: {e}')
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['morning', 'evening'], required=True)
    ap.add_argument('--send', action='store_true',
                    help='Discord に送信する(デフォルトは stdout のみ)')
    ap.add_argument('--date', default=None, help='YYYY-MM-DD で日付固定 (テスト用)')
    args = ap.parse_args()

    base = date.fromisoformat(args.date) if args.date else date.today()
    if args.mode == 'morning':
        text = _build_morning(base)
    else:
        text = _build_evening(base)
    print(text)
    if args.send:
        status = _send_discord(text)
        print(f'\n[discord_status={status}]')


if __name__ == '__main__':
    main()
