#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# deploy_pwa_quiz_comments.sh
# PWA設置 + クイズウィジェット埋め込み + コメント機能有効化
#
# 実行: bash wordpress/deploy_pwa_quiz_comments.sh [--dry-run]
#
# 自動処理:
#   1. 人気記事TOP3にグループ診断クイズ挿入
#   2. 初心者ガイド記事に相性診断クイズ挿入
#   3. WPディスカッション設定の確認
#   4. コメントモデレーション初回実行
#
# 手動対応:
#   - wp-content/mu-plugins/ に以下をアップロード:
#     a) kpj-pwa-comments.php （mu-plugin本体）
#     b) kpj-manifest.json    （manifest.json 内容）
#     c) kpj-sw.js            （Service Worker 内容）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
SITE_URL="${SITE_URL:-https://www.kpopjournal.tokyo}"
DRY_RUN="${1:-}"

# .env 読み込み
if [[ -f "${BASE_DIR}/.env" ]]; then
    set -a; source "${BASE_DIR}/.env"; set +a
fi

echo "════════════════════════════════════════════"
echo " PWA + クイズ + コメント 一括デプロイ"
echo "════════════════════════════════════════════"
if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo " ⚠️  DRY-RUN モード（変更なし）"
fi
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1: PWA ファイル確認
# ━━━━━━━━━━━━━━━━━━━━━━━━
echo "[1/5] PWA ファイル確認..."
for f in manifest.json sw.js kpj-pwa-comments.php; do
    if [[ -f "${SCRIPT_DIR}/${f}" ]]; then
        echo "  ✅ ${f} 存在確認OK"
    else
        echo "  ❌ ${f} が見つかりません"
        exit 1
    fi
done

# mu-plugins用のコピーを準備
echo "  mu-plugins 用ファイル準備..."
cp "${SCRIPT_DIR}/manifest.json" "${SCRIPT_DIR}/kpj-manifest.json"
cp "${SCRIPT_DIR}/sw.js" "${SCRIPT_DIR}/kpj-sw.js"
echo "  ✅ kpj-manifest.json / kpj-sw.js 作成完了"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2: 人気記事TOP3 取得 → グループ診断クイズ挿入
# ━━━━━━━━━━━━━━━━━━━━━━━━
echo "[2/5] 人気記事TOP3 にグループ診断クイズ挿入..."

# WP人気記事をページビュー順で取得（WP Popular Posts プラグイン or 最近の記事で代用）
# 通常記事（カテゴリ113/112の初心者記事は除外）
TOP3_IDS=$(python3 -c "
import json, urllib.request, base64, os

site = '${SITE_URL}'
user = os.environ.get('WP_USER', '')
passwd = os.environ.get('WP_PASS', '')
token = base64.b64encode(f'{user}:{passwd}'.encode()).decode()

# 最新公開記事をページビューの多い順（popularソートがなければ日付順で代用）
# 初心者カテゴリ(112,113)を除外
url = f'{site}/wp-json/wp/v2/posts?per_page=20&status=publish&orderby=date&order=desc&_fields=id,title,categories'
req = urllib.request.Request(url)
req.add_header('Authorization', f'Basic {token}')

with urllib.request.urlopen(req, timeout=30) as res:
    posts = json.loads(res.read())

# 初心者カテゴリ除外
exclude_cats = {112, 113}
filtered = [p for p in posts if not set(p.get('categories', [])) & exclude_cats][:3]

for p in filtered:
    title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
    print(f\"{p['id']}|{title}\")
" 2>/dev/null)

if [[ -z "$TOP3_IDS" ]]; then
    echo "  ⚠️  人気記事の取得に失敗しました（REST API確認要）"
else
    # グループ診断HTMLをキャッシュファイルに生成
    python3 "${BASE_DIR}/lib/kpop_quiz_generator.py" group-match -o "${BASE_DIR}/lib/_quiz_group_cache.html"

    echo "$TOP3_IDS" | while IFS='|' read -r POST_ID TITLE; do
        echo "  📝 #${POST_ID}: ${TITLE}"

        # 既にクイズが埋め込まれていないか確認
        EXISTING=$(curl -s -K ~/.wp_auth \
            "${SITE_URL}/wp-json/wp/v2/posts/${POST_ID}?_fields=content" 2>/dev/null \
            | python3 -c "import json,sys; print('YES' if 'kpj-group-quiz' in json.load(sys.stdin).get('content',{}).get('rendered','') else 'NO')" 2>/dev/null || echo "ERROR")

        if [[ "$EXISTING" == "YES" ]]; then
            echo "    ⏭️  既に挿入済み、スキップ"
            continue
        fi

        if [[ "$DRY_RUN" == "--dry-run" ]]; then
            echo "    [DRY-RUN] 挿入スキップ"
            continue
        fi

        # 記事末尾にクイズを追加
        python3 -c "
import json, urllib.request, base64, os, sys

site = '${SITE_URL}'
user = os.environ.get('WP_USER', '')
passwd = os.environ.get('WP_PASS', '')
token = base64.b64encode(f'{user}:{passwd}'.encode()).decode()

post_id = ${POST_ID}

# 現在のコンテンツ取得
url = f'{site}/wp-json/wp/v2/posts/{post_id}?_fields=content'
req = urllib.request.Request(url)
req.add_header('Authorization', f'Basic {token}')
with urllib.request.urlopen(req, timeout=30) as res:
    current = json.loads(res.read())

content = current.get('content', {}).get('raw', '') or current.get('content', {}).get('rendered', '')

# クイズHTML
quiz_html = '''
<!-- KPJ グループ診断クイズ -->
<div style=\"margin-top:40px;padding-top:20px;border-top:1px solid #2D2D3F\">
<p style=\"text-align:center;font-size:14px;color:#94A3B8;margin-bottom:0\">🎮 あなたにピッタリのグループは？</p>
</div>
''' + open('${BASE_DIR}/lib/_quiz_group_cache.html').read()

# 更新
data = json.dumps({'content': content + quiz_html}).encode()
req2 = urllib.request.Request(f'{site}/wp-json/wp/v2/posts/{post_id}', data=data, method='POST')
req2.add_header('Authorization', f'Basic {token}')
req2.add_header('Content-Type', 'application/json')
with urllib.request.urlopen(req2, timeout=30) as res:
    result = json.loads(res.read())
    print(f'    ✅ 挿入完了 (post #{post_id})')
" 2>&1 || echo "    ❌ 挿入失敗"
    done
fi
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3: 初心者ガイド記事に相性診断挿入
# ━━━━━━━━━━━━━━━━━━━━━━━━
echo "[3/5] 初心者ガイド記事に相性診断クイズ挿入..."

# カテゴリ113の記事一覧（ハブ記事除外）
BEGINNER_IDS=$(python3 -c "
import json, urllib.request, base64, os

site = '${SITE_URL}'
user = os.environ.get('WP_USER', '')
passwd = os.environ.get('WP_PASS', '')
token = base64.b64encode(f'{user}:{passwd}'.encode()).decode()

url = f'{site}/wp-json/wp/v2/posts?categories=113&per_page=20&status=publish&_fields=id,title,slug'
req = urllib.request.Request(url)
req.add_header('Authorization', f'Basic {token}')

with urllib.request.urlopen(req, timeout=30) as res:
    posts = json.loads(res.read())

# ハブ記事は除外（ハブは短い仕様なのでクイズ不要）
for p in posts:
    slug = p.get('slug', '')
    if 'hub' in slug:
        continue
    title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
    print(f\"{p['id']}|{title}\")
" 2>/dev/null)

if [[ -z "$BEGINNER_IDS" ]]; then
    echo "  ⚠️  初心者記事の取得に失敗しました"
else
    # 相性診断HTMLを生成してキャッシュ
    python3 "${BASE_DIR}/lib/kpop_quiz_generator.py" compatibility -o "${BASE_DIR}/lib/_quiz_compat_cache.html"

    echo "$BEGINNER_IDS" | while IFS='|' read -r POST_ID TITLE; do
        echo "  📝 #${POST_ID}: ${TITLE}"

        EXISTING=$(curl -s -K ~/.wp_auth \
            "${SITE_URL}/wp-json/wp/v2/posts/${POST_ID}?_fields=content" 2>/dev/null \
            | python3 -c "import json,sys; print('YES' if 'kpj-compat-quiz' in json.load(sys.stdin).get('content',{}).get('rendered','') else 'NO')" 2>/dev/null || echo "ERROR")

        if [[ "$EXISTING" == "YES" ]]; then
            echo "    ⏭️  既に挿入済み、スキップ"
            continue
        fi

        if [[ "$DRY_RUN" == "--dry-run" ]]; then
            echo "    [DRY-RUN] 挿入スキップ"
            continue
        fi

        python3 -c "
import json, urllib.request, base64, os

site = '${SITE_URL}'
user = os.environ.get('WP_USER', '')
passwd = os.environ.get('WP_PASS', '')
token = base64.b64encode(f'{user}:{passwd}'.encode()).decode()

post_id = ${POST_ID}

url = f'{site}/wp-json/wp/v2/posts/{post_id}?_fields=content'
req = urllib.request.Request(url)
req.add_header('Authorization', f'Basic {token}')
with urllib.request.urlopen(req, timeout=30) as res:
    current = json.loads(res.read())

content = current.get('content', {}).get('raw', '') or current.get('content', {}).get('rendered', '')

quiz_html = '''
<!-- KPJ 相性診断クイズ -->
<div style=\"margin-top:40px;padding-top:20px;border-top:1px solid #2D2D3F\">
<p style=\"text-align:center;font-size:14px;color:#94A3B8;margin-bottom:0\">💕 推しとの相性を診断してみよう！</p>
</div>
''' + open('${BASE_DIR}/lib/_quiz_compat_cache.html').read()

data = json.dumps({'content': content + quiz_html}).encode()
req2 = urllib.request.Request(f'{site}/wp-json/wp/v2/posts/{post_id}', data=data, method='POST')
req2.add_header('Authorization', f'Basic {token}')
req2.add_header('Content-Type', 'application/json')
with urllib.request.urlopen(req2, timeout=30) as res:
    result = json.loads(res.read())
    print(f'    ✅ 挿入完了 (post #{post_id})')
" 2>&1 || echo "    ❌ 挿入失敗"
    done
fi
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4: WPコメント設定確認
# ━━━━━━━━━━━━━━━━━━━━━━━━
echo "[4/5] WordPress コメント設定確認..."

python3 -c "
import json, urllib.request, base64, os

site = '${SITE_URL}'
user = os.environ.get('WP_USER', '')
passwd = os.environ.get('WP_PASS', '')
token = base64.b64encode(f'{user}:{passwd}'.encode()).decode()

# WP設定取得
url = f'{site}/wp-json/wp/v2/settings'
req = urllib.request.Request(url)
req.add_header('Authorization', f'Basic {token}')
try:
    with urllib.request.urlopen(req, timeout=30) as res:
        settings = json.loads(res.read())

    cs = settings.get('default_comment_status', 'unknown')
    print(f'  デフォルトコメント: {cs}')
    if cs == 'open':
        print('  ✅ コメントは有効です')
    else:
        print('  ⚠️  コメントが無効です — WP管理画面で有効化してください')
        print('  　  設定 → ディスカッション → 「新しい投稿へのコメントを許可」にチェック')
except Exception as e:
    print(f'  ⚠️  設定取得失敗: {e}')
    print('  　  手動で確認してください: WP管理画面 → 設定 → ディスカッション')
" 2>&1
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 5: コメントモデレーション実行
# ━━━━━━━━━━━━━━━━━━━━━━━━
echo "[5/5] コメントモデレーション（スパムフィルタ）実行..."
if [[ "$DRY_RUN" == "--dry-run" ]]; then
    python3 "${BASE_DIR}/lib/comment_manager.py" --moderate --dry-run 2>&1 | sed 's/^/  /'
else
    python3 "${BASE_DIR}/lib/comment_manager.py" --moderate 2>&1 | sed 's/^/  /'
fi
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━
# 完了サマリ
# ━━━━━━━━━━━━━━━━━━━━━━━━
echo "════════════════════════════════════════════"
echo " 完了サマリ"
echo "════════════════════════════════════════════"
echo ""
echo " ✅ 自動完了:"
echo "   - グループ診断クイズ → 人気記事TOP3に挿入"
echo "   - 相性診断クイズ → 初心者ガイド記事に挿入"
echo "   - スパムフィルタ → コメントモデレーション実行"
echo ""
echo " 🔧 手動対応（ConoHaファイルマネージャー）:"
echo "   wp-content/mu-plugins/ に以下3ファイルをアップロード:"
echo ""
echo "   1. kpj-pwa-comments.php  ← mu-plugin本体"
echo "      場所: wordpress/kpj-pwa-comments.php"
echo ""
echo "   2. kpj-manifest.json     ← PWA manifest"
echo "      場所: wordpress/kpj-manifest.json"
echo ""
echo "   3. kpj-sw.js             ← Service Worker"
echo "      場所: wordpress/kpj-sw.js"
echo ""
echo " 📋 WP管理画面で確認する設定:"
echo "   設定 → ディスカッション:"
echo "     ☑ コメントの手動承認を必須にする"
echo "     ☑ 既承認者のコメントは自動承認"
echo "     ☑ 名前とメールアドレスの入力を必須にする"
echo "   プラグイン:"
echo "     ☑ Akismet が有効化済み（APIキー設定済み）"
echo ""
echo " 🔍 動作確認URL:"
echo "   PWA:      ${SITE_URL}/manifest.json"
echo "   SW:       ${SITE_URL}/sw.js"
echo "   API:      ${SITE_URL}/wp-json/kpopjournal/v1/comment-reaction"
echo "════════════════════════════════════════════"
