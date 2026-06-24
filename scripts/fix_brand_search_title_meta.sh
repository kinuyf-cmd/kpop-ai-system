#!/usr/bin/env bash
# ブランド指名検索の取りこぼし対処(2026-06-24)
#   真因(GSC実測): 英字 k-journal(201imp)/k journal(127imp) が pos6・CTR0%
#     = サイトHTMLに英字「K-Journal」完全一致テキストが不在 → 順位6位止まり&スニペット非太字
#   + ホームmetaが #tagline のみ(19字)で指名検索者への誘引ゼロ → カタカナpos2-4でもCTR2%
#
# 打ち手(低リスク):
#   (1) blogdescription(=#tagline) に英字 (K-Journal) を織り込む
#       → home title と meta の両方に英字完全一致が同時に出現。#site_title(KPOP JOURNAL)は不変。
#   (2) AIOSEO global.metaDescription を #tagline → 独立した誘引文へ
#       → 二重エンコードJSONを厳密再現して更新(setup_og_default.sh の作法を踏襲)
#
# 安全策: 適用前に blogdescription と aioseo_options を ~/.kpop_recovery にバックアップ。
#         dry-run で変更前/後を必ず表示。実適用は owner が APPLY=1 で実行。
#
#   確認: sudo bash scripts/fix_brand_search_title_meta.sh
#   適用: sudo APPLY=1 bash scripts/fix_brand_search_title_meta.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
BK="${HOME:-/home/aiuser}/.kpop_recovery"
APPLY="${APPLY:-0}"
mkdir -p "$BK"

NEW_TAGLINE='Kジャーナル(K-Journal)｜日本最大級のK-POP専門メディア'
NEW_META='K-POP最新ニュース・カムバック速報・アイドル図鑑・来日公演情報まで。Kジャーナル(K-Journal)が毎日お届けする日本最大級のK-POP専門メディアです。'

echo "=== ブランド指名検索 title/meta 修正: $([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN) ==="

# ---- (1) blogdescription (=tagline) ----
CUR_TAGLINE=$($WP option get blogdescription 2>/dev/null || echo "")
echo
echo "[1] blogdescription (#tagline → home title/meta に反映)"
echo "  変更前: $CUR_TAGLINE"
echo "  変更後: $NEW_TAGLINE"
echo "  → 結果 home <title>: KPOP JOURNAL - $NEW_TAGLINE"

# ---- (2) AIOSEO global.metaDescription ----
RAW_FILE=$(mktemp /tmp/aioseo_raw.XXXXXX.json)
$WP option get aioseo_options --format=json > "$RAW_FILE" 2>/dev/null || true
echo
echo "[2] aioseo_options searchAppearance.global.metaDescription"
echo "  option 取得バイト長: $(wc -c < "$RAW_FILE")"

PAYLOAD_FILE=$(mktemp /tmp/aioseo_payload.XXXXXX.json)
RAW_FILE="$RAW_FILE" NEW_META="$NEW_META" PAYLOAD_FILE="$PAYLOAD_FILE" python3 - <<'PY'
import os, json
raw = open(os.environ["RAW_FILE"]).read().strip()
# wp option get --format=json は「二重エンコードJSON文字列」をさらにJSONエンコードして返す
inner = json.loads(raw)                      # -> str (AIOSEOの二重エンコード文字列)
if not isinstance(inner, str):
    raise SystemExit("予期せぬ形式: inner が文字列でない")
data = json.loads(inner)                      # -> dict
g = data.setdefault("searchAppearance", {}).setdefault("global", {})
old = g.get("metaDescription")
g["metaDescription"] = os.environ["NEW_META"]
print(f"  変更前: {old!r}")
print(f"  変更後: {g['metaDescription']!r}")
# 元の保存形式(二重エンコード)を厳密再現: dict -> 文字列 -> その文字列を再保存
encoded_inner = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
open(os.environ["PAYLOAD_FILE"], "w").write(encoded_inner)
PY

if [ "$APPLY" = 1 ]; then
  ts=$(date +%Y%m%d_%H%M%S)
  echo "$CUR_TAGLINE" > "$BK/blogdescription.backup_$ts.txt"
  cp "$RAW_FILE" "$BK/aioseo_options.backup_$ts.json"
  echo
  echo "  バックアップ: $BK/blogdescription.backup_$ts.txt"
  echo "             : $BK/aioseo_options.backup_$ts.json"

  $WP option update blogdescription "$NEW_TAGLINE"
  # aioseo_options は二重エンコード文字列をそのまま値として保存(--format=json は使わない)
  $WP option update aioseo_options "$(cat "$PAYLOAD_FILE")"
  echo "  ✅ 適用完了。AIOSEO キャッシュ purge:"
  $WP aioseo cache clear 2>/dev/null || echo "  (aioseo cache clear 不可: 手動 or 自然反映)"
  echo
  echo "  次手順: 本番HTML確認後に GSC 再インデックス:"
  echo "    venv_kpi/bin/python3 lib/gsc_indexing.py --url https://www.kpopjournal.tokyo/"
else
  echo
  echo "  (DRY-RUN: 適用するには sudo APPLY=1 bash $0)"
fi

rm -f "$RAW_FILE" "$PAYLOAD_FILE"
