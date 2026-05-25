// soompi_chart_fetch.mjs — Soompi K-Pop Music Chart の最新 top10 を取得し JSON 出力。
// 最新チャート記事を検索で発見 → .current-rank widget から rank/song/artist を抽出。
// 実行: node tools/chart/soompi_chart_fetch.mjs  (出力: data/soompi_chart_top10.json)
// playwright は /tmp 等 npx 解決可能な場所から起動する前提(本file は cwd 非依存で import)。
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

const UA = 'KPOP-JOURNAL-Bot/1.0 (+https://kpopjournal.tokyo; citation-only)';
const OUT = process.env.CHART_OUT || 'data/soompi_chart_top10.json';

const b = await chromium.launch({ headless:true, args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'] });
const p = await b.newPage({ userAgent: UA });

// 1) 最新チャート記事URLを発見(検索ページをJS描画して最初のchart記事リンク)
let url = process.env.CHART_URL || '';
if (!url) {
  await p.goto('https://www.soompi.com/?s=soompi%20k-pop%20music%20chart', { waitUntil:'networkidle', timeout:60000 }).catch(()=>{});
  await p.waitForTimeout(3000);
  url = await p.evaluate(() => {
    const a = [...document.querySelectorAll('a[href*="soompis-k-pop-music-chart"]')]
      .map(x => x.href).filter(h => /\/article\/\d+wpp\//.test(h));
    return a[0] || '';
  });
}
if (!url) { console.error('ERR: 最新チャート記事URL発見失敗'); await b.close(); process.exit(1); }

// 2) チャート記事を開いて top10 抽出
await p.goto(url, { waitUntil:'networkidle', timeout:60000 }).catch(()=>{});
await p.waitForTimeout(5000);
const data = await p.evaluate(() => {
  const items = [];
  document.querySelectorAll('.current-rank').forEach(rk => {
    // current-rank の直近の .closest('div') は .title-container(rank+曲のみ)で
    // Artist/Band を含まない。Artist/Band を含む最小の祖先(li.item)まで登る。
    let row = rk.closest('li') ;
    if (!row || !/Artist\/Band/.test(row.innerText || '')) {
      let n = rk;
      for (let i = 0; i < 8 && n; i++) { if (/Artist\/Band/.test(n.innerText || '')) { row = n; break; } n = n.parentElement; }
    }
    if (!row) return;
    // innerText を行配列化(ラベルと値が別行になる構造に対応)
    const lines = row.innerText.split('\n').map(s => s.trim()).filter(Boolean);
    const t = lines.join('\n');
    const rank = (lines[0] && lines[0].match(/^(\d+)/)) ? lines[0].match(/^(\d+)/)[1] : '';
    // ラベル "X:" の次行 or 同行の値を拾うヘルパ
    const after = (label) => {
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(new RegExp('^' + label + '[:：]\\s*(.*)$'));
        if (m) return (m[1] && m[1].trim()) ? m[1].trim() : (lines[i+1] || '').trim();
      }
      return '';
    };
    const album  = after('Album');
    const artist = after('Artist\\/Band') || after('Artist');
    // 曲名: rank行(+変動)の次の、ラベルでない最初の行
    let song = '';
    for (let i = 1; i < lines.length; i++) {
      if (/^(Album|Artist|Music)[:：]/.test(lines[i])) break;
      if (/^\([^)]*\)$/.test(lines[i])) continue; // (+3) 等の変動行スキップ
      song = lines[i]; break;
    }
    if (rank && Number(rank) <= 10) items.push({ rank:Number(rank), song:(song||'').trim(), artist:(artist||'').trim(), album:(album||'').trim() });
  });
  return { url: location.href, title: document.title, items: items.sort((a,b)=>a.rank-b.rank).slice(0,10) };
});
await b.close();

if (!data.items.length) { console.error('ERR: top10抽出0件'); process.exit(1); }
data.fetched_at = new Date().toISOString();
writeFileSync(OUT, JSON.stringify(data, null, 1));
console.log(`OK: ${data.items.length}件 → ${OUT}`);
data.items.forEach(i => console.log(`  ${i.rank}. ${i.song} — ${i.artist}`));
