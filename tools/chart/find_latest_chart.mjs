// Soompi 最新 music chart 記事URLを発見(JS描画後のsearch/tagから)。stdout に URL。
import { chromium } from 'playwright';
const UA='KPOP-JOURNAL-Bot/1.0 (+https://kpopjournal.tokyo; citation-only)';
const b=await chromium.launch({headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
const p=await b.newPage({userAgent:UA});
const tries=[
  'https://www.soompi.com/?s=soompi%20k-pop%20music%20chart',
  'https://www.soompi.com/tag/soompi-music-chart',
];
let url='';
for(const t of tries){
  await p.goto(t,{waitUntil:'networkidle',timeout:45000}).catch(()=>{});
  await p.waitForTimeout(3500);
  const links=await p.evaluate(()=>[...document.querySelectorAll('a')].map(a=>a.href).filter(h=>/\/article\/\d+wpp\/soompis-k-pop-music-chart-/.test(h)));
  if(links.length){ url=links[0]; break; }
}
await b.close();
if(url) process.stdout.write(url); else process.exit(2);
