#!/usr/bin/env bash
# patch_hero_credit.sh — single-idol_artist.php にヒーロー(集合写真)出所クレジット描画を追加する。
# オーナー実行(themeファイルは www-data 所有のため sudo 必須)。
#
# 変更点（2箇所、いずれも既存の logo_credit/member_photo_credit パターンを踏襲）:
#   (A) $member_photo_credit 読み込み直後に $hero_credit を postmeta から読む。
#       ACF Free 都合で member_photo_credit と同様に get_post_meta 直読（ACF変更不要）。
#   (B) credits footer の条件と本文に「メイン画像出典」行を追加。
#
# 冪等: 既にパッチ済み（hero_credit を含む）なら何もしない。
set -euo pipefail
F=/var/www/wp_stg/wp-content/themes/generatepress-kpop/single-idol_artist.php

if grep -q 'hero_credit' "$F"; then
  echo "[skip] already patched (hero_credit present)"
  exit 0
fi

# 反映前バックアップ（既存運用に倣い .bak.<epoch>）
cp -a "$F" "$F.bak.$(date +%s)"

# (A) member_photo_credit の行の直後に hero_credit 読み込みを挿入
perl -0pi -e 's{(\$member_photo_credit = get_post_meta\( \$artist_id, '"'"'member_photo_credit'"'"', true \);\n)}{$1\t/* ヒーロー(メイン=集合写真)画像の出所。featured 画像投入時は出所表示必須（オーナー方針 2026-05-26）。 */\n\t\$hero_credit = get_post_meta( \$artist_id, '"'"'hero_credit'"'"', true );\n}' "$F"

# (B) footer 条件に $hero_credit を追加
perl -0pi -e 's{<\?php if \( \$logo_url \|\| \$member_photo_credit \) : \?>}{<?php if ( \$logo_url || \$member_photo_credit || \$hero_credit ) : ?>}' "$F"

# (B) footer 本文に「メイン画像出典」行を logo 出典の前に挿入
#     <footer> 行は実ファイルでは tab×3。挿入する内側行は1段深い tab×4。
perl -0pi -e 's{(\t\t\t<footer class="kpop-idol-credits">\n)}{$1\t\t\t\t<?php if ( \$hero_credit ) : ?>\n\t\t\t\t\t<p>メイン画像出典: <?php echo esc_html( \$hero_credit ); ?></p>\n\t\t\t\t<?php endif; ?>\n}' "$F"

echo "[ok] patched. verifying php syntax..."
php -l "$F"
echo "[ok] grep check:"
grep -n 'hero_credit' "$F"
