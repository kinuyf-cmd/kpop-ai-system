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


METRICS_YESTERDAY = Path(os.path.expanduser('~/google_metrics/metrics_yesterday.json'))
COST_LEDGER = ROOT / 'data' / 'cost_ledger.jsonl'
AB_LOG = ROOT / 'logs' / 'x_ab_log.jsonl'
RED_LOG = Path(os.path.expanduser('~/.kpop_recovery/red_team_log.jsonl'))
BLUE_LOG = Path(os.path.expanduser('~/.kpop_recovery/blue_team_log.jsonl'))
USD_JPY = 155  # 概算レート(売上/コストの円換算用、ブリーフ向け概算)


def _weekly_summary(today_iso: str) -> dict:
    """直近7日(today含む)の集計: 記事/コスト/X投稿。
    metrics_yesterday は日次スナップショットでないため売上は集計不可、コストと運用のみ。"""
    from datetime import datetime as _dt, timedelta as _td
    end = _dt.fromisoformat(today_iso).date()
    start = end - _td(days=6)
    week_dates = {(start + _td(days=i)).isoformat() for i in range(7)}

    articles = 0
    blocked = 0
    if PROCESSED.exists():
        with PROCESSED.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = (r.get('ts') or '')[:10]
                if d in week_dates:
                    k = r.get('kind', '')
                    if k in ('breaking', 'original'):
                        articles += 1
                    elif k in ('breaking_blocked', 'blocked'):
                        blocked += 1

    cost = 0.0
    if COST_LEDGER.exists():
        with COST_LEDGER.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('date') in week_dates:
                    cost += float(r.get('cost_usd', 0) or 0)

    x_posts = 0
    if AB_LOG.exists():
        with AB_LOG.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = (r.get('ts') or '')[:10]
                if d in week_dates and r.get('tweet_id'):
                    x_posts += 1

    return {
        'start': start.isoformat(), 'end': end.isoformat(),
        'articles': articles, 'blocked': blocked,
        'cost_usd': round(cost, 4), 'cost_jpy': int(cost * USD_JPY),
        'x_posts': x_posts,
    }


def _red_blue_summary(today_iso: str, days: int = 7) -> dict:
    """RED/BLUE 直近N日のイベント集計。本日分は別カウント。"""
    from datetime import datetime as _dt, timedelta as _td
    today_dt = _dt.fromisoformat(today_iso).date()
    cutoff = today_dt - _td(days=days)

    def _load(path: Path):
        if not path.exists():
            return []
        rows = []
        with path.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    d = _dt.fromisoformat(r['ts'].replace('+09:00', '')).date()
                except Exception:
                    continue
                if d >= cutoff:
                    rows.append((d, r))
        return rows

    red = _load(RED_LOG)
    blue = _load(BLUE_LOG)

    red_today_high = sum(1 for d, r in red if d == today_dt and r.get('severity') == 'HIGH')
    red_today_med = sum(1 for d, r in red if d == today_dt and r.get('severity') == 'MEDIUM')
    red_today_low = sum(1 for d, r in red if d == today_dt and r.get('severity') == 'LOW')
    blue_today_queued = sum(1 for d, r in blue if d == today_dt and r.get('result') == 'queued')
    blue_today_fixed = sum(1 for d, r in blue if d == today_dt and r.get('result') in ('fixed', 'resolved'))
    red_today_samples = [r for d, r in red if d == today_dt][:3]

    red_week = len(red)
    blue_week = len(blue)
    blue_week_fixed = sum(1 for d, r in blue if r.get('result') in ('fixed', 'resolved'))

    return {
        'red_today': {'HIGH': red_today_high, 'MEDIUM': red_today_med, 'LOW': red_today_low,
                      'samples': red_today_samples},
        'blue_today': {'queued': blue_today_queued, 'fixed': blue_today_fixed},
        'red_week': red_week, 'blue_week': blue_week, 'blue_week_fixed': blue_week_fixed,
    }


def _load_yesterday_metrics() -> dict:
    """朝バッチが生成した metrics_yesterday.json を読む。鮮度チェック付き。"""
    if not METRICS_YESTERDAY.exists():
        return {}
    try:
        return json.loads(METRICS_YESTERDAY.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _today_api_cost_usd(target_date: str) -> float:
    """data/cost_ledger.jsonl から本日分のAPIコスト合計(USD)。"""
    if not COST_LEDGER.exists():
        return 0.0
    total = 0.0
    with COST_LEDGER.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get('date') == target_date:
                total += float(r.get('cost_usd', 0) or 0)
    return round(total, 4)


def _ab_summary_brief(hours: int = 72) -> str:
    """logs/x_ab_log.jsonl から直近Nh分の variant別 imp/eng_rate を1-2行で返す。
    投稿が無い、または APIエラー時は空文字(ブロックを出さない)。"""
    if not AB_LOG.exists():
        return ''
    from datetime import datetime as _dt, timedelta as _td
    cutoff = _dt.now() - _td(hours=hours)
    entries = []
    with AB_LOG.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                if _dt.fromisoformat(r['ts']).replace(tzinfo=None) < cutoff:
                    continue
            except Exception:
                pass
            if r.get('tweet_id') and r.get('variant'):
                entries.append(r)
    if not entries:
        return ''
    # public_metrics 取得(失敗時は件数のみ)
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        from google_metrics.post_to_x import get_public_metrics, validate_credentials
        creds, _ = validate_credentials()
        if not creds:
            return f'AB log {len(entries)}件(認証NGで指標未取得)'
        metrics = get_public_metrics([e['tweet_id'] for e in entries], creds=creds)
    except Exception:
        return f'AB log {len(entries)}件(指標取得失敗)'
    from collections import defaultdict
    agg = defaultdict(lambda: {'n': 0, 'imp': 0, 'eng': 0})
    for e in entries:
        v = e['variant']
        m = metrics.get(e['tweet_id'], {})
        a = agg[v]
        a['n'] += 1
        a['imp'] += int(m.get('impression_count', 0))
        a['eng'] += (int(m.get('like_count', 0)) + int(m.get('retweet_count', 0))
                     + int(m.get('reply_count', 0)) + int(m.get('bookmark_count', 0)))
    parts = []
    for v in sorted(agg):
        a = agg[v]
        n = max(a['n'], 1)
        eng_rate = round(a['eng'] / max(a['imp'], 1) * 100, 2)
        parts.append(f"{v}: n={a['n']} imp_avg={round(a['imp']/n, 1)} eng={eng_rate}%")
    return ' / '.join(parts)


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

    metrics = _load_yesterday_metrics()
    ga4 = (metrics.get('ga4') or {}).get('summary') or {}
    ads = metrics.get('adsense') or {}
    gsc_top_pages = (metrics.get('gsc') or {}).get('top_pages') or []
    gsc_top_queries = (metrics.get('gsc') or {}).get('top_queries') or []
    gsc_label = (metrics.get('gsc') or {}).get('period_label', '?日前')
    metrics_date = metrics.get('date', '?')

    lines = []
    lines.append(f'## 🌙 夕ブリーフ — {now.strftime("%Y-%m-%d")} (17:00 JST)')
    lines.append('')

    # ━━━━━ 📊 経営サマリー(前日確定) ━━━━━
    lines.append(f'### 📊 経営サマリー(前日={metrics_date})')
    rev_usd = float(ads.get('ESTIMATED_EARNINGS', 0) or 0)
    rev_jpy = int(rev_usd * USD_JPY)
    ads_clicks = ads.get('CLICKS', '?')
    ads_rpm = ads.get('PAGE_VIEWS_RPM', '?')
    cost_usd = _today_api_cost_usd(today)
    cost_jpy = int(cost_usd * USD_JPY)
    profit_jpy = rev_jpy - cost_jpy
    margin = (profit_jpy / rev_jpy * 100) if rev_jpy > 0 else 0
    lines.append(f'- 売上: ¥{rev_jpy:,} (AdSense ${rev_usd} / clicks {ads_clicks} / RPM ${ads_rpm}) / A8: 管理画面参照')
    lines.append(f'- コスト(本日API): ¥{cost_jpy:,} (${cost_usd})')
    lines.append(f'- 粗利: ¥{profit_jpy:,} (利益率 {margin:.0f}%)')
    lines.append('')

    # ━━━━━ 📈 トラフィック(前日確定) ━━━━━
    lines.append(f'### 📈 トラフィック(GA4={metrics_date} / GSC={gsc_label})')
    sessions = ga4.get('sessions', '?')
    users = ga4.get('users', '?')
    pv = ga4.get('pageviews', '?')
    lines.append(f'- GA4: sessions {sessions} / users {users} / PV {pv}')
    if gsc_top_pages:
        gsc_clicks = sum(int(p.get('clicks', 0)) for p in gsc_top_pages)
        gsc_imp = sum(int(p.get('impressions', 0)) for p in gsc_top_pages)
        lines.append(f'- GSC: clicks {gsc_clicks} / imp {gsc_imp} (top_pages合算)')
    else:
        lines.append('- GSC: データなし')
    lines.append('')

    # ━━━━━ 🎯 SEO ハイライト ━━━━━
    if gsc_top_pages:
        lines.append('### 🎯 SEO上位ページ TOP3')
        for p in gsc_top_pages[:3]:
            slug = (p.get('page', '') or '').rstrip('/').rsplit('/', 1)[-1] or 'トップ'
            lines.append(f'- {slug}: clicks {int(p.get("clicks", 0))} / pos {p.get("position", 0):.1f}')
    if gsc_top_queries:
        lines.append('### 🔍 クエリ流入 TOP3')
        for q in gsc_top_queries[:3]:
            lines.append(f'- 「{q.get("query", "")}」 clicks {int(q.get("clicks", 0))} / pos {q.get("position", 0):.1f}')
    ab_line = _ab_summary_brief(hours=72)
    if ab_line:
        lines.append(f'### 🧪 M10 AB(直近72h): {ab_line}')
    lines.append('')

    # ━━━━━ 🔧 運用(本日進行中) ━━━━━
    lines.append('### 🔧 本日運用途中経過')

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

    # ━━━━━ 📅 週次サマリー(直近7日) ━━━━━
    wk = _weekly_summary(today)
    lines.append('')
    lines.append(f'### 📅 週次サマリー ({wk["start"]} 〜 {wk["end"]})')
    lines.append(f'- 記事公開: {wk["articles"]}本 / 停止 {wk["blocked"]}件')
    lines.append(f'- X投稿: {wk["x_posts"]}件')
    lines.append(f'- APIコスト(7日合計): ¥{wk["cost_jpy"]:,} (${wk["cost_usd"]})')

    # ━━━━━ 🛡️ RED/BLUE 監査チーム報告 ━━━━━
    rb = _red_blue_summary(today)
    rt = rb['red_today']
    bt = rb['blue_today']
    lines.append('')
    lines.append('### 🛡️ RED/BLUE 監査チーム')
    lines.append(f'- RED本日: HIGH {rt["HIGH"]} / MED {rt["MEDIUM"]} / LOW {rt["LOW"]} (週合計 {rb["red_week"]})')
    lines.append(f'- BLUE本日: 修復済 {bt["fixed"]} / queued(要オーナー判断) {bt["queued"]} (週合計修復 {rb["blue_week_fixed"]}/{rb["blue_week"]})')
    if rt['samples']:
        lines.append('  RED本日抜粋:')
        for s in rt['samples']:
            sev = s.get('severity', '?')
            msg = (s.get('message') or '')[:60]
            lines.append(f'  - [{sev}] {msg}')

    # ━━━━━ ⚠️ 要対処(赤信号項目の自動検出) ━━━━━
    alerts = []
    if proc['rate'] < 50:
        alerts.append(f'- 🔴 Pipeline稼働率 {proc["rate"]}% 危険(目標{tgt_uptime}%、半分以下)')
    elif proc['rate'] < tgt_uptime:
        alerts.append(f'- 🟡 Pipeline稼働率 {proc["rate"]}% 未達(目標{tgt_uptime}%)')
    if (metrics.get('errors') or {}).get('adsense'):
        alerts.append(f'- 🔴 AdSense取得失敗: {metrics["errors"]["adsense"][:80]}')
    if (metrics.get('errors') or {}).get('ga4'):
        alerts.append(f'- 🔴 GA4取得失敗: {metrics["errors"]["ga4"][:80]}')
    if (metrics.get('errors') or {}).get('gsc'):
        alerts.append(f'- 🔴 GSC取得失敗: {metrics["errors"]["gsc"][:80]}')
    if cost_usd > 5 and rev_jpy < cost_jpy:
        alerts.append(f'- 🔴 本日コスト ¥{cost_jpy:,} > 前日売上 ¥{rev_jpy:,} (赤字傾向)')
    if bt['queued'] >= 3:
        alerts.append(f'- 🟡 BLUE未処理queue 本日 {bt["queued"]}件 → オーナー判断要')
    if rt['HIGH'] >= 1:
        alerts.append(f'- 🔴 RED本日 HIGH {rt["HIGH"]}件 → エスカレ済(BLUE経由)')
    if metrics_date != '?':
        from datetime import datetime as _dt
        try:
            age_days = (_dt.fromisoformat(today) - _dt.fromisoformat(metrics_date)).days
            if age_days > 2:
                alerts.append(f'- 🟡 metrics_yesterday.json が {age_days}日古い(朝バッチ要確認)')
        except Exception:
            pass
    if alerts:
        lines.append('')
        lines.append('### ⚠️ 要対処')
        lines.extend(alerts)

    lines.append('')
    lines.append('### ✅ 翌朝(明朝)までの宿題')
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
