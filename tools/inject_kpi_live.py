#!/usr/bin/env python3
"""render_dashboard.py実行後にkpi-liveセクションを注入する

cron: render_dashboard.py && cp ... && python3 inject_kpi_live.py
"""
import os, re

HTML_PATH = '/home/aiuser/kpopjournal-frontend/public/dash-kx7m2p-v2/index.html'

KPI_SECTION = '''<section id="kpi-live" style="background:#f5f5f7;padding:20px;margin:20px;border-radius:8px;">
  <h2 style="margin-top:0;">📊 Live KPI (15min data / 1min refresh)</h2>
  <div id="kpi-live-content">Loading...</div>
</section>
<script>
async function loadKPI(){
  try{
    const r=await fetch('/api/dashboard/?t='+Date.now(),{cache:'no-store'});
    const d=await r.json();
    const t=d.kpi?.today||{};
    const cs=d.content_stats||{};
    const gsc=d.gsc||{};
    const ga4=d.ga4||{};
    const gr=gsc.available
      ?'<tr><td>GSC 28日</td><td>clicks='+gsc.clicks+' imps='+gsc.impressions+' CTR='+(gsc.ctr*100).toFixed(2)+'%</td></tr>'
      :'<tr><td>GSC</td><td style="color:#c00">未接続</td></tr>';
    const g4=ga4.available
      ?'<tr><td>GA4 昨日</td><td>'+ga4.yesterday_users+'u / '+ga4.yesterday_pv+'PV</td></tr><tr><td>RT</td><td>'+ga4.realtime_users+'u / '+(ga4.realtime_pv||0)+'PV</td></tr>'
      :'<tr><td>GA4</td><td style="color:#c00">未接続</td></tr>';
    const ad=d.adsense||{};
    const ad_row=ad.available
      ?'<tr style="background:#e8e8e8"><th colspan=2 style="text-align:left;padding:4px">💰 AdSense</th></tr><tr><td>昨日</td><td>¥'+(ad.yesterday_jpy||0).toLocaleString()+'</td></tr><tr><td>7日/30日</td><td>¥'+(ad['7d_total_jpy']||0).toLocaleString()+' / ¥'+(ad['30d_total_jpy']||0).toLocaleString()+'</td></tr>'
      :'<tr style="background:#e8e8e8"><th colspan=2 style="text-align:left;padding:4px">💰 AdSense</th></tr><tr><td colspan=2 style="font-size:11px;color:#888">未連携 (AdSenseでSA招待が必要)</td></tr>';
    document.getElementById('kpi-live-content').innerHTML=
      '<p style="font-size:11px;color:#888;">'+d.generated_at+'</p>'+
      '<table style="width:100%;border-collapse:collapse;">'+
      '<tr style="background:#e8e8e8"><th colspan=2 style="text-align:left;padding:4px">📝 記事</th></tr>'+
      '<tr><td>本日公開</td><td><b>'+(t.published||0)+'</b>/'+(t.target||20)+' (速報'+(t.breaking||0)+'/他'+(t.other||0)+')</td></tr>'+
      '<tr><td>月間 / 累計</td><td>'+(cs.month_total||0)+' / '+(cs.site_total||0)+'</td></tr>'+
      '<tr style="background:#e8e8e8"><th colspan=2 style="text-align:left;padding:4px">🔍 GSC / 📈 GA4</th></tr>'+
      gr+g4+ad_row+
      '<tr style="background:#e8e8e8"><th colspan=2 style="text-align:left;padding:4px">🤖 AI社員</th></tr>'+
      '<tr><td>signals 24h</td><td>'+(d.signals_24h||0)+'</td></tr>'+
      '<tr><td>X投稿今日</td><td>'+(d.x_posts_today||0)+'</td></tr>'+
      '</table>'+
      '<h3 style="margin-top:16px">直近記事</h3><ul style="font-size:12px">'+
      (d.recent_posts||[]).map(function(p){return '<li>'+(p.classification==='breaking'?'🔴':'📰')+' '+p.title+' <small>'+p.date.slice(0,16)+'</small></li>'}).join('')+
      '</ul>';
  }catch(e){document.getElementById('kpi-live-content').textContent='Error: '+e;}
}
loadKPI();setInterval(loadKPI,60000);
</script>'''

def main():
    if not os.path.exists(HTML_PATH):
        return
    s = open(HTML_PATH, encoding='utf-8').read()
    # 既存kpi-live除去
    s = re.sub(r'<section id="kpi-live"[\s\S]+?</script>', '', s)
    # </body>直前に注入
    s = s.replace('</body>', KPI_SECTION + '\n</body>')
    open(HTML_PATH, 'w', encoding='utf-8').write(s)
    print(f"kpi-live injected into {HTML_PATH}")

if __name__ == '__main__':
    main()
