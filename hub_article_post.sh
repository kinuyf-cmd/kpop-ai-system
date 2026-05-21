#!/bin/bash
# ハブ記事投稿スクリプト
# 使用方法: bash hub_article_post.sh
# 前提: ~/.wp_auth に有効なApplication Passwordが設定されていること

BASE="https://www.kpopjournal.tokyo/wp-json/wp/v2"

# 認証テスト
AUTH_TEST=$(curl -s -X GET "$BASE/users/me" -K ~/.wp_auth)
if echo "$AUTH_TEST" | grep -q "rest_not_logged_in\|rest_cannot_create"; then
  echo "❌ 認証失敗: ~/.wp_auth のApplication Passwordを確認してください"
  exit 1
fi
echo "✅ 認証OK"

# 記事本文の構築・投稿をPythonで完結（シェル変数経由のUnicodeエスケープ問題を回避）
RESPONSE=$(python3 << 'PYEOF'
import json, re, requests, os, base64

def _wp_auth_header():
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\n]+)"?', line.strip())
                if m:
                    return m.group(1)
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
    return f"Authorization: Basic {token}"

auth_value = _wp_auth_header()
token_part = auth_value.split(": ", 1)[1] if ": " in auth_value else auth_value
headers = {"Authorization": token_part, "Content-Type": "application/json"}

TARGET_URL = "https://www.kpopjournal.tokyo/kpop-idol-glass-skin-complete-guide-2026/"

content = f"""<p>TWICEサナ、IVEウォニョン、BLACKPINKジス——K-POPアイドルといえば、ステージパフォーマンスだけでなく、その透き通るような美肌と洗練されたビジュアルでも世界中のファンを魅了しています。「あの肌はどうやって作るの？」「普段どんなコスメを使っているの？」——そんな疑問に応えるため、当サイトに蓄積されたK-POP美容コンテンツを一か所にまとめました。</p>

<p>スキンケアの基礎から美容医療、メイクテクニックまで、アイドルが実践する美容法を分野ごとに整理しています。中でも、<a href="{TARGET_URL}">K-POPアイドルのガラス肌の作り方を徹底解説した総合ガイド</a>は、韓国式スキンケアの全体像を把握したい方に特におすすめです。</p>

<h2>① スキンケア｜アイドルが毎日実践する肌作りの基本</h2>

<p>K-POPアイドルの美肌は、生まれつきではなく日々のスキンケアルーティンによって作られています。クレンジング・化粧水・美容液・クリームという基本ステップに加え、シートマスクやCICAケアなど韓国発の手法が組み合わさって、あの透明感が生まれます。</p>

<ul>
<li><strong>美肌ルーティンの全体像を知りたい方へ：</strong><a href="https://www.kpopjournal.tokyo/kpop-skincare-routine/">K-POPアイドルの美肌ルーティン徹底解剖！</a><br>クレンジングから保湿・スリーピングマスクまで、アイドルの一日のスキンケアを順を追って解説しています。</li>
</ul>

<ul>
<li><strong>乾燥肌・敏感肌の方に：</strong><a href="https://www.kpopjournal.tokyo/cica-skincare-dry-sensitive-idols-2025/">乾燥肌アイドルのリアルケア習慣｜CICAスキンケア特集</a><br>長時間メイクや強い照明にさらされる現場でも肌トラブルを防ぐ、CICAを軸にした低刺激ケアの実践法を紹介。</li>
</ul>

<ul>
<li><strong>シートマスクの正しい使い方：</strong><a href="https://www.kpopjournal.tokyo/sheet-mask-daily-korean-skincare/">シートマスクは毎日使う？韓国アイドル流の使い分け術</a><br>肌タイプや目的に合わせた選び方と、朝・夜・特別ケアの使い分け方を徹底解説。</li>
</ul>

<p>これらのスキンケアステップをひとつの体系としてまとめたものが、<a href="{TARGET_URL}">アイドルが実践する韓国式スキンケアの完全ガイド</a>です。サナ・ウォニョン・カリナら複数アイドルのルーティンを比較しながら、自分に合ったステップを見つけることができます。</p>

<h2>② コスメ｜アイドル御用達の韓国コスメをカテゴリ別に紹介</h2>

<p>韓国コスメ（K-ビューティ）は、その高い品質とコスパのよさから世界中で支持されています。アイドルがSNSで紹介したり、ステージで使用したりすることで話題になったアイテムは、ファンの間でも即売り切れになるほど。ここでは、カテゴリ別に注目コスメをまとめました。</p>

<ul>
<li><strong>ベースメイクを極めたい方へ：</strong><a href="https://www.kpopjournal.tokyo/kpop-idol-base-makeup/">舞台裏メイクを支える！K-POPアイドルが使うベースメイク</a><br>HERA・CLIO・LANEIGEなどアイドル御用達のクッションファンデや下地を比較。崩れないステージメイクの作り方も解説。</li>
</ul>

<ul>
<li><strong>アイメイクにこだわりたい方へ：</strong><a href="https://www.kpopjournal.tokyo/korean-eyeshadow-palette-itzy-2025/">ITZYも愛用？韓国最新トレンドアイパレット特集</a><br>3CE・CLIO・ETUDEなど人気ブランドのアイパレットを厳選紹介。2025年最新のカラートレンドも合わせて解説しています。</li>
</ul>

<ul>
<li><strong>リップにこだわりたい方へ：</strong><a href="https://www.kpopjournal.tokyo/kpop-lip-best5-2025/">ステージでも崩れない！K-POPアイドル愛用リップ5選</a><br>長時間の公演でも色落ちしないティントやリップを厳選。BLACKPINKやSEVENTEEN愛用品など実際に使われているアイテムを紹介。</li>
</ul>

<p>コスメ選びに迷ったときは、アイドルのスキンケア全体の文脈で理解すると選びやすくなります。素肌の透明感を最大限に引き出すための考え方が、<a href="{TARGET_URL}">韓国アイドルが実践するガラス肌の作り方まとめ</a>に詳しく書かれています。</p>

<h2>③ 美容医療｜アイドルが通うクリニック・施術の最新情報</h2>

<p>日々のスキンケアに加えて、K-POPアイドルは美容皮膚科や専門クリニックでのケアも積極的に取り入れています。水光注射・ハイドラフェイシャル・小顔矯正など、短期間で効果を発揮するプロの施術が、あの輝く肌の背景にあります。</p>

<ul>
<li><strong>美容クリニック選びの参考に：</strong><a href="https://www.kpopjournal.tokyo/kpop-skinclinic-2025/">K-POP界で話題の美容皮膚科3選【2025年最新版】</a><br>ソウルの人気クリニック（Oracle・Renewme・ID Hospital）を詳細比較。日本語対応や施術内容、料金目安も掲載。</li>
</ul>

<ul>
<li><strong>透明感を高める注射治療：</strong><a href="https://www.kpopjournal.tokyo/suikou-injection-effect-price/">アイドルが受けている"水光注射"とは？効果と価格まとめ</a><br>ヒアルロン酸などを皮膚の浅い部分に注入することで内側からうるおいを補給する施術。効果・持続期間・価格帯をわかりやすく解説。</li>
</ul>

<ul>
<li><strong>フェイスラインを整えたい方に：</strong><a href="https://www.kpopjournal.tokyo/korean-beauty-face-slimming/">整形ではなく"骨格調整"？K-POPアイドルも実践する小顔テクニック</a><br>メスを使わずに顔の歪みやむくみを改善する「コルギ（骨格調整）」の仕組みと、ソウルの人気サロン情報を紹介。</li>
</ul>

<h2>④ ガラス肌｜最終目標はアイドル級の透明感ある素肌</h2>

<p>スキンケア・コスメ・美容医療——これらすべての美容法が目指す先にあるのが「ガラス肌（Glass Skin）」です。ガラスのように滑らかで内側から光を放つような透明感のある肌は、K-POPアイドルのビジュアルを象徴するキーワードとして世界的に広まっています。</p>

<p>ガラス肌を作るためのステップは、単なる保湿だけでなく、角質ケア・美白・紫外線対策・成分選びまで多岐にわたります。TWICEサナが実践する「7スキン法」、BLACKPINKジスの「3ステップ完結型ルーティン」、aespaカリナの「CICAファースト」など、トップアイドルそれぞれのアプローチを徹底比較した記事が話題です。</p>

<p>それらをすべて一か所にまとめた決定版として、<a href="{TARGET_URL}"><strong>K-POPアイドルのガラス肌の作り方【2026年決定版】</strong></a>を公開しています。2026年最新の注目成分（PDRNなど）や、予算別おすすめスターターセットまで網羅した完全ガイドです。ガラス肌に興味がある方は、まずこちらをご覧ください。</p>

<h2>⑤ このサイトについて｜K-POPと美容を深掘りするメディア</h2>

<p>K-POP JOURNAL TOKYOは、K-POPの音楽・ライブ情報に加えて、アイドルの美容・ファッション・ライフスタイルも深掘りする総合メディアです。韓国コスメの成分解説から、渡韓美容クリニックのリポートまで、ファン目線のリアルな情報をお届けしています。</p>

<p>「推しと同じスキンケアを試してみたい」「韓国コスメをどこから始めればいいかわからない」——そんな方は、ぜひ各記事を参考にしてみてください。K-POPアイドルの美容習慣を知ることで、スキンケアへの理解が格段に深まるはずです。</p>"""

payload = {
    "title": "【完全まとめ】K-POPアイドル美容法｜スキンケア・コスメ・美肌ルーティン総集編",
    "content": content,
    "status": "publish",
    "slug": "kpop-idol-beauty-skincare-complete-hub",
    "categories": [12],
}
# ensure_ascii=False で日本語をそのままUTF-8として送信
res = requests.post(
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts",
    headers=headers,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    timeout=30,
)
print(json.dumps({"status_code": res.status_code, **res.json()}, ensure_ascii=False))
PYEOF
)

POST_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id','ERROR'))" 2>/dev/null)
POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)

if [[ "$POST_ID" =~ ^[0-9]+$ ]]; then
  echo "✅ ハブ記事投稿成功!"
  echo "   post_id: $POST_ID"
  echo "   URL: $POST_URL"

  # ─── 投稿後自動監査 ──────────────────────────────────────────────────────
  echo "=== 投稿後自動監査 ==="
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "【完全まとめ】K-POPアイドル美容法｜スキンケア・コスメ・美肌ルーティン総集編" "" 2>&1 || true
  
  # KPIログに記録
  python3 -c "
import json
from datetime import datetime
entry = {
    'timestamp': datetime.now().isoformat(),
    'date': datetime.now().strftime('%Y-%m-%d'),
    'event': 'post_published',
    'post_id': '$POST_ID',
    'title': '【完全まとめ】K-POPアイドル美容法｜スキンケア・コスメ・美肌ルーティン総集編',
    'url': '$POST_URL',
    'slug': 'kpop-idol-beauty-skincare-complete-hub',
    'article_type': 'hub',
    'categories': [12],
    'has_cta': True,
    'internal_links_to_2214': 3,
    'internal_links_total': 12
}
with open('/home/aiuser/kpop-ai-system/logs/kpi_posts.jsonl', 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
print('KPIログ記録完了')
"
else
  echo "❌ 投稿失敗:"
  echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('code',''), d.get('message',''))" 2>/dev/null
fi
