#!/usr/bin/env python3
"""Dashboard v3 — dashboard.json を唯一のデータ源。正確値のみ表示。"""
import json, os
from datetime import datetime

DASH_JSON = '/home/aiuser/kpopjournal-frontend/public/data/dashboard.json'
OUT_HTML = '/home/aiuser/kpopjournal-frontend/public/dash-kx7m2p-v2/index.html'


def load():
    if not os.path.exists(DASH_JSON):
        return None
    try:
        return json.load(open(DASH_JSON, encoding='utf-8'))
    except Exception:
        return None


def fi(v, default='—'):
    if v is None: return default
    try: return f'{int(v):,}'
    except Exception: return str(v)


def fp(v):
    if v is None: return '—'
    try: return f'{float(v)*100:.2f}%'
    except Exception: return str(v)


def fy(v):
    if v is None: return '未計測'
    try: return f'&yen;{int(v):,}'
    except Exception: return str(v)


def build(d):
    if not d:
        return '<html><body><h1>Dashboard data not available</h1></body></html>'

    now = datetime.now()
    gen = d.get('generated_at', '?')
    t = d.get('kpi', {}).get('today', {})
    cs = d.get('content_stats', {})
    gsc = d.get('gsc', {})
    ga4 = d.get('ga4', {})
    ads = d.get('adsense', {})
    sig = d.get('signals_24h', 0)
    xp = d.get('x_posts_today', 0)
    au = d.get('audit_24h', d.get('audit_recent', {}))
    rp = d.get('recent_posts', [])

    gsc_rows = ''
    if gsc.get('available'):
        gsc_rows = f'''<tr><td>クリック (28日)</td><td><b>{fi(gsc.get("clicks"))}</b></td></tr>
<tr><td>表示回数</td><td>{fi(gsc.get("impressions"))}</td></tr>
<tr><td>CTR</td><td>{fp(gsc.get("ctr"))}</td></tr>
<tr><td>最新データ</td><td>{gsc.get("latest_date","?")}</td></tr>'''
    else:
        gsc_rows = '<tr><td colspan="2" class="err">GSC未接続</td></tr>'

    ga4_rows = ''
    if ga4.get('available'):
        ga4_rows = f'''<tr><td>昨日UU</td><td>{fi(ga4.get("yesterday_users"))}</td></tr>
<tr><td>昨日PV</td><td>{fi(ga4.get("yesterday_pv"))}</td></tr>
<tr><td>リアルタイム</td><td><b>{fi(ga4.get("realtime_users"))}</b>u / {fi(ga4.get("realtime_pv",0))}PV</td></tr>'''
    else:
        ga4_rows = '<tr><td colspan="2" class="err">GA4未接続</td></tr>'

    ads_rows = ''
    if ads.get('available'):
        ads_rows = f'''<tr><td>昨日</td><td>{fy(ads.get("yesterday_jpy"))}</td></tr>
<tr><td>過去7日</td><td>{fy(ads.get("7d_total_jpy"))}</td></tr>
<tr><td>過去30日</td><td>{fy(ads.get("30d_total_jpy"))}</td></tr>'''
    else:
        ads_rows = '<tr><td colspan="2" class="pending">招待承認待ち or CSVアップロードで暫定対応可</td></tr>'

    recent_li = ''.join(
        f'<li>{"🔴" if p.get("classification")=="breaking" else "📰"} {p.get("title","")[:70]} <small>{p.get("date","")[:16]}</small></li>'
        for p in rp[:10]
    )

    audit_info = f'{fi(au.get("total",0))}件'

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>KPOP JOURNAL Dashboard</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:860px;margin:20px auto;padding:16px;color:#222;background:#fafafa}}
h1{{font-size:20px;border-bottom:2px solid #333;padding-bottom:8px}}
h2{{font-size:16px;margin-top:24px;background:#333;color:#fff;padding:8px 12px;border-radius:4px}}
table{{width:100%;border-collapse:collapse;margin:8px 0;background:#fff}}
td{{padding:8px 12px;border-bottom:1px solid #eee;vertical-align:top}}
td:first-child{{font-weight:bold;width:38%;background:#f5f5f5}}
td b{{font-size:18px}}
.meta{{font-size:11px;color:#888;margin:4px 0 16px}}
ul{{margin:8px 0;padding-left:20px}} li{{margin:3px 0;font-size:13px}}
.err{{color:#c00;font-size:12px}} .pending{{color:#c80;font-size:12px}}
</style>
</head>
<body>
<h1>KPOP JOURNAL Dashboard</h1>
<p class="meta">データ更新: {gen} / HTML: {now.isoformat()[:19]}<br>
データ源: dashboard.json (唯一の正)。未計測項目は明示。</p>

<h2>📝 記事投稿</h2>
<table>
<tr><td>本日公開</td><td><b>{fi(t.get("published"))}</b> / {t.get("target",20)} (速報{t.get("breaking",0)}/他{t.get("other",0)})</td></tr>
<tr><td>週間 (7日)</td><td>{fi(cs.get("week_total"))}</td></tr>
<tr><td>月間</td><td>{fi(cs.get("month_total"))}</td></tr>
<tr><td>累計</td><td>{fi(cs.get("site_total"))}</td></tr>
</table>

<h2>🔍 Google Search Console</h2>
<table>{gsc_rows}</table>

<h2>📈 Google Analytics 4</h2>
<table>{ga4_rows}</table>

<h2>💰 AdSense</h2>
<table>{ads_rows}</table>

<h2>🤖 AI社員</h2>
<table>
<tr><td>signals 24h</td><td>{fi(sig)}</td></tr>
<tr><td>X投稿今日</td><td>{fi(xp)}</td></tr>
<tr><td>監査問題 24h</td><td>{audit_info}</td></tr>
</table>

<h2>📰 直近記事</h2>
<ul>{recent_li if recent_li else "<li>なし</li>"}</ul>

<script>setTimeout(()=>location.reload(),60000)</script>
<p class="meta" style="text-align:center;margin-top:30px;border-top:1px solid #ddd;padding-top:10px">
Dashboard v3 | <a href="/api/dashboard/" style="color:#06c">JSON API</a>
</p>
</body>
</html>'''


def main():
    d = load()
    html = build(d)
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    open(OUT_HTML, 'w', encoding='utf-8').write(html)
    k = (d or {}).get('kpi', {}).get('today', {})
    cs = (d or {}).get('content_stats', {})
    print(f"v3: today={k.get('published',0)} month={cs.get('month_total',0)} total={cs.get('site_total',0)} ({len(html)}B)")


if __name__ == '__main__':
    main()
