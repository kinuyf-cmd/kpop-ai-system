#!/usr/bin/env python3
"""
kpop_quiz_generator.py — K-POPインタラクティブクイズウィジェット生成

WordPress記事内に埋め込めるHTMLクイズウィジェットを生成する。

3種類のクイズ:
  1. group-match   — KPOPグループ診断（性格・好みから推しグループを判定）
  2. compatibility — 相性診断（推しメンバーとの相性を占う）
  3. member-quiz   — メンバー当てクイズ（ヒントから誰かを当てる）

Usage:
  python3 lib/kpop_quiz_generator.py group-match     # グループ診断HTML出力
  python3 lib/kpop_quiz_generator.py compatibility   # 相性診断HTML出力
  python3 lib/kpop_quiz_generator.py member-quiz     # メンバー当てクイズHTML出力
  python3 lib/kpop_quiz_generator.py all             # 全部出力
  python3 lib/kpop_quiz_generator.py --post-id 123   # WP記事に埋め込み
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _base_style() -> str:
    return """
<style>
.kpj-quiz{font-family:'Noto Sans JP',-apple-system,sans-serif;max-width:600px;margin:32px auto;
  background:linear-gradient(135deg,#14141F,#1E1E2E);border-radius:20px;padding:28px 24px;
  border:1px solid #2D2D3F;color:#F1F5F9;box-shadow:0 8px 32px rgba(0,0,0,0.3)}
.kpj-quiz h2{font-size:22px;font-weight:800;text-align:center;margin:0 0 6px;
  background:linear-gradient(135deg,#FF2D55,#7B61FF);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent}
.kpj-quiz .subtitle{text-align:center;font-size:13px;color:#94A3B8;margin-bottom:20px}
.kpj-quiz .q-step{display:none}.kpj-quiz .q-step.active{display:block}
.kpj-quiz .q-title{font-size:16px;font-weight:700;margin-bottom:14px;text-align:center}
.kpj-quiz .q-progress{height:4px;background:#1E293B;border-radius:2px;margin-bottom:16px;overflow:hidden}
.kpj-quiz .q-progress-bar{height:4px;background:linear-gradient(90deg,#FF2D55,#7B61FF);
  border-radius:2px;transition:width 0.4s ease}
.kpj-quiz .q-options{display:flex;flex-direction:column;gap:10px}
.kpj-quiz .q-opt{background:#0F172A;border:2px solid #2D2D3F;border-radius:12px;padding:14px 16px;
  cursor:pointer;font-size:14px;font-weight:600;transition:all 0.2s;text-align:left;color:#E2E8F0}
.kpj-quiz .q-opt:hover{border-color:#FF2D55;background:#1A1A2E;transform:translateX(4px)}
.kpj-quiz .q-opt.selected{border-color:#FF2D55;background:rgba(255,45,85,0.1)}
.kpj-quiz .result-card{text-align:center;padding:20px 0}
.kpj-quiz .result-group{font-size:28px;font-weight:900;margin:12px 0 8px;
  background:linear-gradient(135deg,#FF2D55,#7B61FF);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent}
.kpj-quiz .result-desc{font-size:14px;color:#94A3B8;line-height:1.7;margin-bottom:16px}
.kpj-quiz .result-pct{font-size:48px;font-weight:900;color:#FF2D55}
.kpj-quiz .share-btn{display:inline-block;padding:10px 24px;border-radius:10px;
  background:linear-gradient(135deg,#FF2D55,#7B61FF);color:#fff;font-weight:700;font-size:14px;
  text-decoration:none;border:none;cursor:pointer;transition:transform 0.2s}
.kpj-quiz .share-btn:hover{transform:scale(1.05)}
.kpj-quiz .retry-btn{display:inline-block;margin-top:10px;padding:8px 20px;border-radius:8px;
  background:transparent;border:1px solid #64748B;color:#94A3B8;font-size:13px;cursor:pointer}
</style>"""


def generate_group_match() -> str:
    """KPOPグループ診断クイズ"""
    return _base_style() + """
<div class="kpj-quiz" id="kpj-group-quiz">
  <h2>K-POPグループ診断</h2>
  <div class="subtitle">あなたにピッタリのK-POPグループは？</div>
  <div class="q-progress"><div class="q-progress-bar" id="gq-prog" style="width:0%"></div></div>
  <div id="gq-steps">
    <div class="q-step active" data-step="0">
      <div class="q-title">Q1. 休日の過ごし方は？</div>
      <div class="q-options">
        <div class="q-opt" data-scores="bts:2,txt:1">友達とカフェで語り合う</div>
        <div class="q-opt" data-scores="blackpink:2,itzy:1">ショッピング＆自撮り</div>
        <div class="q-opt" data-scores="seventeen:2,stray:1">スポーツや体を動かすこと</div>
        <div class="q-opt" data-scores="aespa:2,nj:1">家でゲームや動画鑑賞</div>
      </div>
    </div>
    <div class="q-step" data-step="1">
      <div class="q-title">Q2. 好きな音楽のジャンルは？</div>
      <div class="q-options">
        <div class="q-opt" data-scores="bts:2,seventeen:1">ヒップホップ・ラップ</div>
        <div class="q-opt" data-scores="blackpink:2,itzy:2">EDM・ダンスミュージック</div>
        <div class="q-opt" data-scores="txt:2,nj:2">ポップ・R&B</div>
        <div class="q-opt" data-scores="aespa:2,stray:1">ロック・エレクトロニック</div>
      </div>
    </div>
    <div class="q-step" data-step="2">
      <div class="q-title">Q3. 推しに求めるものは？</div>
      <div class="q-options">
        <div class="q-opt" data-scores="bts:2,txt:2">深い歌詞とメッセージ性</div>
        <div class="q-opt" data-scores="blackpink:2,aespa:1">圧倒的なビジュアルとカリスマ</div>
        <div class="q-opt" data-scores="seventeen:2,stray:2">パフォーマンスの完成度</div>
        <div class="q-opt" data-scores="nj:2,itzy:2">親しみやすさと元気</div>
      </div>
    </div>
    <div class="q-step" data-step="3">
      <div class="q-title">Q4. SNSの使い方は？</div>
      <div class="q-options">
        <div class="q-opt" data-scores="bts:1,nj:2">見る専門（ROM専）</div>
        <div class="q-opt" data-scores="blackpink:2,itzy:1">おしゃれな写真を投稿</div>
        <div class="q-opt" data-scores="seventeen:1,stray:2">面白い動画やネタ投稿</div>
        <div class="q-opt" data-scores="aespa:2,txt:1">考察や感想を長文で書く</div>
      </div>
    </div>
    <div class="q-step" data-step="4">
      <div class="q-title">Q5. コンサートで一番楽しみなのは？</div>
      <div class="q-options">
        <div class="q-opt" data-scores="bts:2,txt:1">メンバーのトーク・MC</div>
        <div class="q-opt" data-scores="blackpink:2,aespa:2">衣装とステージ演出</div>
        <div class="q-opt" data-scores="seventeen:2,stray:2">ダンスブレイク・パフォーマンス</div>
        <div class="q-opt" data-scores="nj:2,itzy:1">ファンとの一体感</div>
      </div>
    </div>
  </div>
  <div class="result-card" id="gq-result" style="display:none">
    <div style="font-size:14px;color:#64748B">あなたにピッタリのグループは...</div>
    <div class="result-group" id="gq-group-name"></div>
    <div class="result-desc" id="gq-group-desc"></div>
    <button class="share-btn" id="gq-share">結果をXでシェア</button><br>
    <button class="retry-btn" id="gq-retry">もう一度やる</button>
  </div>
</div>
<script>
(function(){
  var groups={
    bts:{name:'BTS',desc:'深い歌詞と社会的メッセージに共感できるあなた。ARMYとして世界を変える力を持っています！'},
    blackpink:{name:'BLACKPINK',desc:'トレンドに敏感でカリスマ性のあるあなた。BLINKとしてファッション・音楽の最前線に！'},
    seventeen:{name:'SEVENTEEN',desc:'チームワークとパフォーマンスを愛するあなた。CARATとして13人の才能を応援！'},
    stray:{name:'Stray Kids',desc:'独創的でエネルギッシュなあなた。STAYとして自分だけの道を切り拓く！'},
    aespa:{name:'aespa',desc:'未来的でクリエイティブなあなた。MYとして次世代K-POPの世界観に没入！'},
    nj:{name:'NewJeans',desc:'ナチュラルでトレンドに敏感なあなた。Bunnyとして新しいK-POPの風を感じて！'},
    txt:{name:'TXT',desc:'感受性豊かで物語を愛するあなた。MOAとして青春のストーリーを共に！'},
    itzy:{name:'ITZY',desc:'自信に満ちてポジティブなあなた。MIDZYとして「自分らしさ」を貫く！'}
  };
  var scores={};var step=0;var total=5;
  var steps=document.querySelectorAll('#gq-steps .q-step');
  var prog=document.getElementById('gq-prog');
  document.querySelectorAll('#kpj-group-quiz .q-opt').forEach(function(opt){
    opt.addEventListener('click',function(){
      var data=opt.getAttribute('data-scores').split(',');
      data.forEach(function(d){var p=d.split(':');scores[p[0]]=(scores[p[0]]||0)+parseInt(p[1]);});
      steps[step].classList.remove('active');
      step++;
      prog.style.width=(step/total*100)+'%';
      if(step<total){steps[step].classList.add('active');}
      else{showResult();}
    });
  });
  function showResult(){
    document.getElementById('gq-steps').style.display='none';
    var best='bts';var max=0;
    for(var k in scores){if(scores[k]>max){max=scores[k];best=k;}}
    var g=groups[best]||groups.bts;
    document.getElementById('gq-group-name').textContent=g.name;
    document.getElementById('gq-group-desc').textContent=g.desc;
    document.getElementById('gq-result').style.display='block';
    document.getElementById('gq-share').onclick=function(){
      window.open('https://x.com/intent/tweet?text='+encodeURIComponent('K-POPグループ診断の結果、私にピッタリなのは「'+g.name+'」でした！\\n\\n#KPOP診断 #KPOPJournal')+'&url='+encodeURIComponent(location.href),'_blank');
    };
    if(typeof gtag==='function')gtag('event','quiz_complete',{quiz_type:'group_match',result:g.name});
  }
  document.getElementById('gq-retry').addEventListener('click',function(){
    scores={};step=0;prog.style.width='0%';
    document.getElementById('gq-result').style.display='none';
    document.getElementById('gq-steps').style.display='block';
    steps.forEach(function(s,i){s.classList.toggle('active',i===0);});
  });
})();
</script>"""


def generate_compatibility() -> str:
    """相性診断"""
    return _base_style() + """
<div class="kpj-quiz" id="kpj-compat-quiz">
  <h2>K-POPアイドル相性診断</h2>
  <div class="subtitle">あなたと推しの相性は何%？</div>
  <div class="q-progress"><div class="q-progress-bar" id="cq-prog" style="width:0%"></div></div>
  <div id="cq-steps">
    <div class="q-step active" data-step="0">
      <div class="q-title">まず推しの名前を入力！</div>
      <div style="text-align:center;padding:10px 0">
        <input type="text" id="cq-name" placeholder="例: ジョングク、ジェニー、ウォニョン..."
               style="width:90%;max-width:300px;padding:12px 16px;border-radius:10px;border:2px solid #2D2D3F;
               background:#0F172A;color:#E2E8F0;font-size:15px;text-align:center;outline:none"
               autocomplete="off">
        <br><br>
        <button class="share-btn" id="cq-start" style="padding:12px 32px">診断スタート</button>
      </div>
    </div>
    <div class="q-step" data-step="1">
      <div class="q-title">Q1. 推しのどこが一番好き？</div>
      <div class="q-options">
        <div class="q-opt" data-pt="3">笑顔・表情</div>
        <div class="q-opt" data-pt="2">ダンス・パフォーマンス</div>
        <div class="q-opt" data-pt="4">歌声・ラップ</div>
        <div class="q-opt" data-pt="1">性格・人柄</div>
      </div>
    </div>
    <div class="q-step" data-step="2">
      <div class="q-title">Q2. 推しとデートするなら？</div>
      <div class="q-options">
        <div class="q-opt" data-pt="2">カフェでまったり</div>
        <div class="q-opt" data-pt="4">遊園地で全力！</div>
        <div class="q-opt" data-pt="1">家で映画鑑賞</div>
        <div class="q-opt" data-pt="3">街歩き＆フォトスポット巡り</div>
      </div>
    </div>
    <div class="q-step" data-step="3">
      <div class="q-title">Q3. 推しへの愛の表現方法は？</div>
      <div class="q-options">
        <div class="q-opt" data-pt="4">ファンレターを書く</div>
        <div class="q-opt" data-pt="2">SNSでひたすら布教</div>
        <div class="q-opt" data-pt="3">グッズを集めまくる</div>
        <div class="q-opt" data-pt="1">心の中で静かに応援</div>
      </div>
    </div>
  </div>
  <div class="result-card" id="cq-result" style="display:none">
    <div style="font-size:14px;color:#64748B">あなたと <span id="cq-oshi" style="color:#FF2D55;font-weight:700"></span> の相性は...</div>
    <div class="result-pct" id="cq-pct"></div>
    <div class="result-desc" id="cq-desc"></div>
    <button class="share-btn" id="cq-share">結果をXでシェア</button><br>
    <button class="retry-btn" id="cq-retry">もう一度やる</button>
  </div>
</div>
<script>
(function(){
  var name='';var pts=0;var step=0;var total=4;
  var steps=document.querySelectorAll('#cq-steps .q-step');
  var prog=document.getElementById('cq-prog');
  document.getElementById('cq-start').addEventListener('click',function(){
    name=document.getElementById('cq-name').value.trim();
    if(!name){document.getElementById('cq-name').style.borderColor='#FF2D55';return;}
    steps[0].classList.remove('active');step=1;
    steps[1].classList.add('active');prog.style.width='25%';
  });
  document.querySelectorAll('#kpj-compat-quiz .q-opt').forEach(function(opt){
    opt.addEventListener('click',function(){
      pts+=parseInt(opt.getAttribute('data-pt')||0);
      steps[step].classList.remove('active');step++;
      prog.style.width=(step/total*100)+'%';
      if(step<total){steps[step].classList.add('active');}
      else{showResult();}
    });
  });
  function showResult(){
    document.getElementById('cq-steps').style.display='none';
    // 名前のハッシュ + pts で相性%を計算（65-99%の範囲）
    var hash=0;for(var i=0;i<name.length;i++)hash=((hash<<5)-hash)+name.charCodeAt(i);
    var pct=65+Math.abs((hash+pts*7)%35);
    var descs={
      90:'運命的な相性！前世からの繋がりを感じます',
      80:'最高の相性！あなたの愛は確実に届いています',
      70:'素晴らしい相性！推し活を続ければもっと近づけるかも',
      0:'良い相性！これからもっと深まる予感'
    };
    var desc='';for(var t in descs){if(pct>=parseInt(t)){desc=descs[t];break;}}
    document.getElementById('cq-oshi').textContent=name;
    document.getElementById('cq-pct').textContent=pct+'%';
    document.getElementById('cq-desc').textContent=desc;
    document.getElementById('cq-result').style.display='block';
    document.getElementById('cq-share').onclick=function(){
      window.open('https://x.com/intent/tweet?text='+encodeURIComponent(name+'との相性は'+pct+'%でした！\\n'+desc+'\\n\\n#KPOP相性診断 #KPOPJournal')+'&url='+encodeURIComponent(location.href),'_blank');
    };
    if(typeof gtag==='function')gtag('event','quiz_complete',{quiz_type:'compatibility',result:pct+'%',oshi:name});
  }
  document.getElementById('cq-retry').addEventListener('click',function(){
    pts=0;step=0;prog.style.width='0%';name='';
    document.getElementById('cq-name').value='';
    document.getElementById('cq-result').style.display='none';
    document.getElementById('cq-steps').style.display='block';
    steps.forEach(function(s,i){s.classList.toggle('active',i===0);});
  });
})();
</script>"""


def generate_member_quiz() -> str:
    """メンバー当てクイズ"""
    return _base_style() + """
<div class="kpj-quiz" id="kpj-member-quiz">
  <h2>K-POPメンバー当てクイズ</h2>
  <div class="subtitle">ヒントからメンバーを当てよう！</div>
  <div id="mq-game">
    <div id="mq-score" style="text-align:center;font-size:13px;color:#64748B;margin-bottom:12px">
      スコア: <span id="mq-pts" style="color:#FF2D55;font-weight:700">0</span> / <span id="mq-total">0</span>
    </div>
    <div id="mq-hint-area" style="background:#0F172A;border-radius:14px;padding:20px;margin-bottom:16px;min-height:120px">
      <div id="mq-hint" style="font-size:15px;color:#E2E8F0;line-height:1.7;text-align:center"></div>
      <div id="mq-extra" style="font-size:13px;color:#94A3B8;margin-top:8px;text-align:center;display:none"></div>
    </div>
    <div id="mq-choices" class="q-options" style="margin-bottom:12px"></div>
    <div id="mq-feedback" style="text-align:center;font-size:15px;font-weight:700;padding:8px;display:none"></div>
    <div style="text-align:center;margin-top:10px">
      <button id="mq-next" class="share-btn" style="display:none;padding:10px 28px">次の問題</button>
      <button id="mq-hint-btn" style="background:transparent;border:1px solid #64748B;color:#94A3B8;
              padding:8px 16px;border-radius:8px;font-size:12px;cursor:pointer">ヒントをもう1つ</button>
    </div>
  </div>
  <div id="mq-final" class="result-card" style="display:none">
    <div style="font-size:14px;color:#64748B">最終スコア</div>
    <div class="result-pct" id="mq-final-score"></div>
    <div class="result-desc" id="mq-final-desc"></div>
    <button class="share-btn" id="mq-share">結果をXでシェア</button><br>
    <button class="retry-btn" id="mq-restart">もう一度挑戦</button>
  </div>
</div>
<script>
(function(){
  var questions=[
    {hints:['97年生まれ・BTS最年少','「黄金マンネ」の異名を持つ','ボーカル・ダンス・ラップ全てをこなす'],answer:'ジョングク',choices:['ジミン','ジョングク','V','RM']},
    {hints:['BLACKPINK所属・オーストラリア出身','ソロ曲「On The Ground」が大ヒット','本名はロザリン・パク'],answer:'ロゼ',choices:['ジェニー','ジス','リサ','ロゼ']},
    {hints:['aespa所属・日本人メンバー','SMエンタ初の日本人女性アイドル','AI「ナイニン」が存在する'],answer:'ジゼル',choices:['カリナ','ウィンター','ニンニン','ジゼル']},
    {hints:['IVE所属・元IZ*ONE','2004年生まれ・171cmの長身','「イブのマンネ」として人気'],answer:'ウォニョン',choices:['ユジン','ウォニョン','レイ','リズ']},
    {hints:['Stray Kids所属・リーダー','作詞作曲プロデュースを手がける','オーストラリア・シドニー出身'],answer:'バンチャン',choices:['バンチャン','リノ','ハン','ヒョンジン']},
    {hints:['NewJeans所属・最年長','2004年生まれ・韓国系オーストラリア人','「Hype Boy」のセンター'],answer:'ミンジ',choices:['ミンジ','ハニ','ダニエル','ヘリン']},
    {hints:['SEVENTEEN所属・パフォーマンスチームリーダー','中国出身・「チャイナのプリンス」','ダンスの実力がグループ随一'],answer:'ディエイト',choices:['ホシ','ディエイト','ジュン','ディノ']},
    {hints:['TWICE所属・日本人メンバー','「モモランド」ではなくTWICEのモモ','ダンスマシーンの異名'],answer:'モモ',choices:['サナ','モモ','ミナ','ツウィ']},
  ];
  var qi=0;var pts=0;var hintIdx=0;var answered=false;
  function shuffle(a){for(var i=a.length-1;i>0;i--){var j=Math.floor(Math.random()*(i+1));var t=a[i];a[i]=a[j];a[j]=t;}return a;}
  shuffle(questions);questions=questions.slice(0,5);
  function render(){
    if(qi>=questions.length){showFinal();return;}
    var q=questions[qi];hintIdx=0;answered=false;
    document.getElementById('mq-pts').textContent=pts;
    document.getElementById('mq-total').textContent=qi+'/'+questions.length;
    document.getElementById('mq-hint').textContent='ヒント1: '+q.hints[0];
    document.getElementById('mq-extra').style.display='none';
    document.getElementById('mq-feedback').style.display='none';
    document.getElementById('mq-next').style.display='none';
    document.getElementById('mq-hint-btn').style.display='inline-block';
    var ch=document.getElementById('mq-choices');ch.innerHTML='';
    shuffle([...q.choices]).forEach(function(c){
      var d=document.createElement('div');d.className='q-opt';d.textContent=c;
      d.addEventListener('click',function(){
        if(answered)return;answered=true;
        document.getElementById('mq-hint-btn').style.display='none';
        var fb=document.getElementById('mq-feedback');fb.style.display='block';
        if(c===q.answer){
          pts++;fb.textContent='正解！';fb.style.color='#22c55e';d.style.borderColor='#22c55e';
        }else{
          fb.textContent='不正解... 答えは「'+q.answer+'」';fb.style.color='#ef4444';d.style.borderColor='#ef4444';
          ch.querySelectorAll('.q-opt').forEach(function(o){if(o.textContent===q.answer)o.style.borderColor='#22c55e';});
        }
        document.getElementById('mq-pts').textContent=pts;
        document.getElementById('mq-next').style.display='inline-block';
      });
      ch.appendChild(d);
    });
  }
  document.getElementById('mq-hint-btn').addEventListener('click',function(){
    var q=questions[qi];hintIdx++;
    if(hintIdx<q.hints.length){
      var ex=document.getElementById('mq-extra');
      ex.textContent='ヒント'+(hintIdx+1)+': '+q.hints[hintIdx];
      ex.style.display='block';
    }
  });
  document.getElementById('mq-next').addEventListener('click',function(){qi++;render();});
  function showFinal(){
    document.getElementById('mq-game').style.display='none';
    var pct=Math.round(pts/questions.length*100);
    document.getElementById('mq-final-score').textContent=pts+'/'+questions.length;
    var descs={5:'完璧！あなたは真のK-POPマスター',4:'すごい！かなりのK-POP通',3:'なかなか！もっと知識を深めよう',0:'ドンマイ！K-POP Journalで勉強しよう'};
    var desc='';for(var t in descs){if(pts>=parseInt(t)){desc=descs[t];break;}}
    document.getElementById('mq-final-desc').textContent=desc;
    document.getElementById('mq-final').style.display='block';
    document.getElementById('mq-share').onclick=function(){
      window.open('https://x.com/intent/tweet?text='+encodeURIComponent('K-POPメンバー当てクイズで'+pts+'/'+questions.length+'問正解！\\n'+desc+'\\n\\n#KPOPクイズ #KPOPJournal')+'&url='+encodeURIComponent(location.href),'_blank');
    };
    if(typeof gtag==='function')gtag('event','quiz_complete',{quiz_type:'member_quiz',result:pts+'/'+questions.length});
  }
  document.getElementById('mq-restart').addEventListener('click',function(){
    qi=0;pts=0;shuffle(questions);
    document.getElementById('mq-final').style.display='none';
    document.getElementById('mq-game').style.display='block';
    render();
  });
  render();
})();
</script>"""


def main():
    ap = argparse.ArgumentParser(description="K-POPクイズウィジェット生成")
    ap.add_argument("type", nargs="?", default="all",
                    choices=["group-match", "compatibility", "member-quiz", "all"],
                    help="クイズタイプ")
    ap.add_argument("--output", "-o", help="出力ファイルパス")
    args = ap.parse_args()

    generators = {
        "group-match": generate_group_match,
        "compatibility": generate_compatibility,
        "member-quiz": generate_member_quiz,
    }

    if args.type == "all":
        html = "\n\n".join(g() for g in generators.values())
    else:
        html = generators[args.type]()

    if args.output:
        Path(args.output).write_text(html, encoding="utf-8")
        print(f"出力: {args.output} ({len(html):,} bytes)")
    else:
        print(html)


if __name__ == "__main__":
    main()
