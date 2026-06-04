import { chromium } from 'playwright';
const UA='KPOP-JOURNAL-Bot/1.0 (+https://kpopjournal.tokyo; citation-only)';
const b=await chromium.launch({headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
const p=await b.newPage({userAgent:UA});
// カテゴリページ(検索より安定)から最新チャート記事を取る
const cats=[
  'https://www.soompi.com/category/music/soompi-music-chart',
  'https://www.soompi.com/tag/soompi-music-chart',
];
let found=[];
for(const c of cats){
  await p.goto(c,{waitUntil:'domcontentloaded',timeout:45000}).catch(()=>{});
  await p.waitForTimeout(3000);
  const links=await p.evaluate(()=>[...document.querySelectorAll('a')].map(a=>a.href).filter(h=>/\/article\/\d+wpp\/soompis-k-pop-music-chart-/.test(h)));
  if(links.length){ found=links; console.error(`source=${c} found=${links.length}`); break; }
}
await b.close();
// 記事IDが最大=最新 を選ぶ(week番号の年跨ぎに強い)
const best=found.map(u=>({u,id:parseInt((u.match(/article\/(\d+)wpp/)||[])[1]||0)})).sort((a,b)=>b.id-a.id)[0];
if(best) process.stdout.write(best.u); else process.exit(2);
