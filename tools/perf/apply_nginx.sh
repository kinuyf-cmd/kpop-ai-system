#!/usr/bin/env bash
# apply_nginx.sh — WebP透過配信+長期キャッシュの nginx conf を安全に適用する。
#   貼り付け改行分断を避けるため1スクリプト化。owner は短い1行のみ実行:
#     sudo bash tools/perf/apply_nginx.sh
#   手順: バックアップ → 完全版に差し替え → nginx -t → 成功なら reload / 失敗なら自動ロールバック。
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PROPOSED="$REPO/tools/perf/kpopjournal.conf.proposed"
# sites-enabled は sites-available へのシンボリックリンクが通例。実体を解決。
LIVE="/etc/nginx/sites-available/kpopjournal.conf"
[ -f "$LIVE" ] || LIVE="/etc/nginx/sites-enabled/kpopjournal.conf"

[ -f "$PROPOSED" ] || { echo "[FATAL] proposed conf が無い: $PROPOSED"; exit 1; }
[ -f "$LIVE" ]     || { echo "[FATAL] 既存 conf が無い: $LIVE"; exit 1; }

BAK="${LIVE}.bak.$(date +%s)"
echo "================ nginx WebP conf 適用 ================"
echo "  対象: $LIVE"
cp "$LIVE" "$BAK" || { echo "[FATAL] バックアップ失敗"; exit 1; }
echo "  バックアップ: $BAK"

cp "$PROPOSED" "$LIVE" || { echo "[FATAL] 差し替え失敗"; cp "$BAK" "$LIVE"; exit 1; }
echo "  差し替え完了 → 構文テスト"

if nginx -t; then
    systemctl reload nginx && echo "  ✅ reload 成功。WebP透過配信 有効化。"
else
    echo "  ⚠️ nginx -t 失敗 → 自動ロールバック"
    cp "$BAK" "$LIVE"
    nginx -t && echo "  復旧確認OK(元のconfに戻しました)。proposedを見直してください。"
    exit 1
fi

echo ""
echo "================ 適用後の自己検証 ================"
sleep 1
CT=$(curl -s -H "Accept: image/webp" -o /dev/null -w "%{content_type} %{size_download}" \
     "https://www.kpopjournal.tokyo/wp-content/uploads/2026/05/live.png" 2>/dev/null || echo "curl失敗")
echo "  live.png (Accept: webp) → $CT"
echo "  期待: image/webp + 小サイズ(従来 image/png 177827 → webp 約9KB)なら透過配信成功"
echo "================ 完了 ================"
