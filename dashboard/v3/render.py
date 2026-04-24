#!/usr/bin/env python3
"""Dashboard v4 - 経営ダッシュボード完全版 (dashboard.json唯一正)"""
import json, os
from datetime import datetime

DASH_JSON = '/home/aiuser/kpopjournal-frontend/public/data/dashboard.json'
OUT_HTML = '/home/aiuser/kpopjournal-frontend/public/dash-kx7m2p-v2/index.html'

def load():
    try: return json.load(open(DASH_JSON, encoding='utf-8'))
    except Exception: return None

def fi(v): return f'{int(v):,}' if v is not None else '—'
def fp(v): return f'{float(v)*100:.2f}%' if v is not None else '—'
def fy(v): return f'&yen;{int(v):,}' if v is not None else '—'

def bar(cur, tgt):
    if not tgt: return ''
    pct = min(100, round(cur / tgt * 100))
    c = '#080' if pct >= 100 else '#06c' if pct >= 60 else '#c80' if pct >= 30 else '#c00'
    return f'<div style="background:#e5e5e5;border-radius:3px;height:7px;margin-top:3px"><div style="width:{pct}%;background:{c};height:100%;border-radius:3px"></div></div><span style="font-size:10px;color:#666">{pct}%</span>'

def arrow(v):
    if v is None: return ''
    return f' <span style="color:#080">▲{v}%</span>' if v > 0 else f' <span style="color:#c00">▼{abs(v)}%</span>' if v < 0 else ''

def bars7(items, key, color='#06c'):
    if not items: return ''
    vals = [i.get(key, 0) for i in items]
    mx = max(vals) or 1
    h = ''
    for i in items:
        v = i.get(key, 0); ht = max(2, v / mx * 36)
        h += f'<div style="display:inline-block;text-align:center;margin:0 1px;width:36px"><div style="height:36px;display:flex;align-items:flex-end;justify-content:center"><div style="width:20px;height:{ht}px;background:{color}"></div></div><div style="font-size:8px;color:#888">{i.get("date","")[-5:]}</div><div style="font-size:9px;font-weight:bold">{v}</div></div>'
    return f'<div style="padding:4px 0;overflow-x:auto;white-space:nowrap">{h}</div>'

def build(d):
    if not d: return '<html><body><h1>No data</h1></body></html>'
    now = datetime.now()
    gen = d.get('generated_at', '')
    tg = d.get('targets', {})
    t = d.get('kpi', {}).get('today', {})
    y = d.get('kpi', {}).get('yesterday', {})
    cs = d.get('content_stats', {})
    a7 = d.get('articles_daily_7d', [])
    gsc = d.get('gsc', {})
    ga4 = d.get('ga4', {})
    ads = d.get('adsense', {})
    co = d.get('costs_24h', {})
    er = d.get('errors', {})
    ag = d.get('agents', [])
    sig = d.get('signals_24h', 0)
    xp = d.get('x_posts_today', 0)
    rp = d.get('recent_posts', [])

    # GSC
    if gsc.get('available'):
        gsc_h = f'''<tr><td>クリック (28日)</td><td><b>{fi(gsc.get("clicks"))}</b></td></tr>
<tr><td>表示回数</td><td>{fi(gsc.get("impressions"))}</td></tr>
<tr><td>CTR</td><td>{fp(gsc.get("ctr"))} / 目標{tg.get("monthly_ctr_pct",3)}%</td></tr>
<tr><td>7日推移</td><td>{bars7(gsc.get("daily_7d",[]),"clicks")}</td></tr>'''
    else:
        gsc_h = f'<tr><td colspan=2 class="err">GSC未接続</td></tr>'

    # GA4
    if ga4.get('available'):
        yp = ga4.get('yesterday_pv', 0); dp = ga4.get('day_before_yesterday_pv', 0)
        ga4_h = f'''<tr><td>リアルタイム</td><td><b>{ga4.get("realtime_users",0)}</b>u / {ga4.get("realtime_pv",0)}PV</td></tr>
<tr><td>昨日PV</td><td><b>{fi(yp)}</b>{arrow(round((yp-dp)/dp*100,1) if dp else None)} / 目標{tg.get("daily_pv",1000):,}{bar(yp,tg.get("daily_pv",1000))}</td></tr>
<tr><td>昨日UU / セッション</td><td>{fi(ga4.get("yesterday_users"))} / {fi(ga4.get("yesterday_sessions"))}</td></tr>
<tr><td>7日推移 (PV)</td><td>{bars7(ga4.get("daily_7d",[]),"pv","#080")}</td></tr>
<tr><td>7日合計</td><td>UU:{fi(ga4.get("7d_users"))} PV:{fi(ga4.get("7d_pv"))}</td></tr>
<tr><td>30日合計</td><td>PV:{fi(ga4.get("30d_pv"))} / 目標{tg.get("monthly_pv",30000):,}{bar(ga4.get("30d_pv",0),tg.get("monthly_pv",30000))}</td></tr>'''
    else:
        ga4_h = f'<tr><td colspan=2 class="err">GA4未接続</td></tr>'

    # AdSense
    if ads.get('available'):
        ads_h = f'''<tr><td>昨日</td><td><b>{fy(ads.get("yesterday_jpy"))}</b> / 目標{fy(tg.get("daily_revenue_jpy"))}{bar(ads.get("yesterday_jpy",0),tg.get("daily_revenue_jpy",1000))}</td></tr>
<tr><td>7日/30日</td><td>{fy(ads.get("7d_total_jpy"))} / {fy(ads.get("30d_total_jpy"))}</td></tr>'''
    else:
        ads_h = '<tr><td colspan=2 class="pend">未連携 (招待承認待ち or CSV)</td></tr>'

    # Cost
    bysvc = ''.join(f'<span style="font-size:10px;margin-right:8px">{k}:{fy(v)}</span>' for k,v in co.get('by_service',{}).items())
    rev = ads.get('yesterday_jpy', 0) if ads.get('available') else 0
    profit = rev - co.get('total_jpy', 0)
    cost_h = f'''<tr><td>24hコスト</td><td>{fy(co.get("total_jpy"))} ({co.get("calls",0)}呼出) {bysvc}</td></tr>
<tr><td>推定日次利益</td><td style="color:{"#080" if profit>=0 else "#c00"}"><b>{fy(profit)}</b></td></tr>'''

    # Agents
    hc = sum(1 for a in ag if a.get('healthy'))
    ag_h = ''.join(f'<tr><td>{"🟢" if a.get("healthy") else "🔴"} {a["name"]}</td><td>{a.get("count_24h",0)}件 <small style="color:#888">{a.get("last","—")}</small></td></tr>' for a in ag)

    # Errors
    et = ''.join(f'<li>{k}:{v}</li>' for k,v in sorted(er.get('by_type',{}).items(), key=lambda x:-x[1])[:5])
    inc = ''.join(f'<li>{"🗑️" if i["kind"]=="deleted" else "⚠️"} post={i.get("post_id")} {i.get("reason","")[:50]}</li>' for i in er.get('recent_incidents',[])[-3:])

    # Recent
    rl = ''.join(f'<li>{"🔴" if p.get("classification")=="breaking" else "📰"} {p.get("title","")[:65]} <small>{p.get("date","")[:16]}</small></li>' for p in rp[:10])

    return f'''<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>KPOP JOURNAL Dashboard</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:960px;margin:16px auto;padding:12px;color:#222;background:#f7f7f8;font-size:13px}}h1{{font-size:20px;border-bottom:3px solid #333;padding-bottom:8px}}h2{{font-size:15px;margin-top:20px;background:linear-gradient(90deg,#333,#555);color:#fff;padding:7px 12px;border-radius:4px}}table{{width:100%;border-collapse:collapse;margin:4px 0 10px;background:#fff;border-radius:4px;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.05)}}td{{padding:8px 12px;border-bottom:1px solid #eee;vertical-align:top}}td:first-child{{font-weight:bold;width:34%;background:#f8f8fa}}td b{{font-size:16px}}.meta{{font-size:10px;color:#888;margin:4px 0}}ul{{margin:4px 0;padding-left:16px}}li{{margin:2px 0;font-size:12px}}.err{{color:#c00;font-size:11px}}.pend{{color:#c80;font-size:11px}}</style></head><body>
<h1>📊 KPOP JOURNAL 経営ダッシュボード</h1>
<p class="meta">更新:{gen[:19]} / HTML:{now.isoformat()[:19]} / 自動:15分毎</p>

<h2>📝 記事投稿</h2><table>
<tr><td>本日</td><td><b>{t.get("published",0)}</b> / {tg.get("daily_articles",20)} (速報{t.get("breaking",0)}/他{t.get("other",0)}){arrow(t.get("vs_yesterday_pct"))}{bar(t.get("published",0),tg.get("daily_articles",20))}</td></tr>
<tr><td>昨日</td><td>{y.get("published",0)}本 (速報{y.get("breaking",0)}/他{y.get("other",0)})</td></tr>
<tr><td>7日推移</td><td>{bars7(a7,"total")}</td></tr>
<tr><td>月間 / 累計</td><td>{cs.get("month_total",0)} / 目標{tg.get("monthly_articles",600):,}{bar(cs.get("month_total",0),tg.get("monthly_articles",600))} | 累計{fi(cs.get("site_total"))}</td></tr>
</table>

<h2>📈 GA4</h2><table>{ga4_h}</table>
<h2>🔍 GSC</h2><table>{gsc_h}</table>
<h2>💰 AdSense</h2><table>{ads_h}</table>
<h2>💴 コスト</h2><table>{cost_h}</table>
<h2>👥 AI社員 ({hc}/{len(ag)}稼働)</h2><table>{ag_h}</table>

<h2>⚠️ エラー (24h: {er.get("today_total",0)}件, 重大{er.get("today_critical",0)})</h2>
<table><tr><td>主要</td><td><ul>{et or "<li>なし</li>"}</ul></td></tr><tr><td>インシデント</td><td><ul>{inc or "<li>なし</li>"}</ul></td></tr>
<tr><td>signals / X</td><td>{fi(sig)} / {fi(xp)} / 目標{tg.get("daily_x_posts",10)}{bar(xp,tg.get("daily_x_posts",10))}</td></tr></table>

<h2>📰 本日記事 ({len(rp)}件)</h2><ul>{rl or "<li>なし</li>"}</ul>

<script>setTimeout(()=>location.reload(),60000)</script>
<p class="meta" style="text-align:center;margin-top:20px;border-top:1px solid #ddd;padding-top:8px">Dashboard v4 | <a href="/api/dashboard/" style="color:#06c">JSON</a></p>
</body></html>'''

def main():
    d = load()
    html = build(d)
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    open(OUT_HTML, 'w', encoding='utf-8').write(html)
    print(f"v4 html: {len(html)}B")

if __name__ == '__main__':
    main()
