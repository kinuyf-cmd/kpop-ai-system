#!/bin/bash
# ============================================================
# 編集制作部 日次朝会（毎日 06:40 JST）
# 部署長: デオキシス（編集長）
# 参加: デオキシス、イーブイ、フシギバナ、ソーナンス、サンダー、カビゴン
# 主旨: 当日の記事執筆プラン確定・focus_themes取り込み
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/editorial/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
CATEGORY_BALANCE=$(category_balance_summary 3)

# オーナー指示・注目テーマ（auto_directives.json の focus_themes を注入）
FOCUS_THEMES=$(python3 - <<'PYFT'
import json
from pathlib import Path
p = Path("/home/aiuser/kpop-ai-system/config/auto_directives.json")
if not p.exists():
    print("（なし）")
else:
    try:
        d = json.loads(p.read_text())
        themes = d.get("focus_themes", [])
        if not themes:
            print("（なし）")
        else:
            print(f"【オーナー指示・注目テーマ {len(themes)}件】")
            for t in themes:
                print(f"  ■ {t.get('topic','')}")
                print(f"    切り口ヒント: {t.get('hint','')}")
                if t.get("category_suggest"):
                    print(f"    推奨カテゴリ: {t['category_suggest']}")
    except Exception as e:
        print(f"（読込失敗: {e}）")
PYFT
)

# 前夜の役員会議レポート（run_ai_meeting）の明日記事TOP5を参照
PRIOR_NIGHT_TOPICS=""
LAST_MEETING="$HOME/ai_company/reports/mewtwo_decision.md"
if [ -f "$LAST_MEETING" ]; then
  PRIOR_NIGHT_TOPICS=$(grep -A20 '【明日書くべき記事 TOP5】' "$LAST_MEETING" | head -22 || echo "")
fi

echo "=== 編集制作部朝会 開始: $TODAY ==="

# 編集制作部の現場メンバーから朝の所感を集める（並列）
safe_claude eevee "
あなたはイーブイ（タイトル最終選定）です。編集制作部朝会で、
前夜の役員会議で決まった記事TOP5に対し、タイトル改善観点で所見を述べてください。

【前夜の決定TOP5】
${PRIOR_NIGHT_TOPICS}

${FOCUS_THEMES}

出力形式：
【担当】eevee
【タイトル改善ポイント】（各記事に1行）
【オーナー指示テーマのタイトル案】（あれば1〜2案）
" "$REPORTS/eevee.md" &

safe_claude venusaur "
あなたはフシギバナ（記事構成設計）です。編集制作部朝会で、
本日執筆予定の記事の構成・H2見出し設計の方針を述べてください。

【前夜の決定TOP5】
${PRIOR_NIGHT_TOPICS}

出力形式：
【担当】venusaur
【構成方針】（3行以内）
【H2見出し案（代表1記事分）】
" "$REPORTS/venusaur.md" &

safe_claude wobbuffet "
あなたはソーナンス（読者ニーズ分析）です。編集制作部朝会で、
本日執筆予定記事に対して読者ニーズの観点で意見を述べてください。

【前夜の決定TOP5】
${PRIOR_NIGHT_TOPICS}

出力形式：
【担当】wobbuffet
【読者ニーズ合致度】（各記事に1行）
【未カバーの読者ニーズ】
" "$REPORTS/wobbuffet.md" &

wait

# 編集長（デオキシス）による統括
safe_claude deoxys_kpop "
あなたはデオキシス（編集制作部長・編集長）です。
編集制作部朝会を主催し、本日の執筆プランを確定してください。

${CATEGORY_BALANCE}

${FOCUS_THEMES}
⚠ オーナー指示テーマが存在する場合、本日TOP3のうち最低1件には必ず組み込むこと。
   不適な場合は記事化予定日を明示（〇月〇日週）し、却下ならば理由を明記すること。

【前夜の役員会議決定TOP5】
${PRIOR_NIGHT_TOPICS}

【イーブイ（タイトル）】
$(cat "$REPORTS/eevee.md")

【フシギバナ（構成）】
$(cat "$REPORTS/venusaur.md")

【ソーナンス（読者ニーズ）】
$(cat "$REPORTS/wobbuffet.md")

出力形式：
【担当】deoxys（編集長）
【本日の執筆プラン】（3行以内）
【本日優先する記事TOP3】
  1. カテゴリ＋タイトル案＋担当（オーナー指示テーマは「[OWNER]」を冒頭に付与）
  2. 同上
  3. 同上
【オーナー指示テーマの処理】（各テーマごとに：本日組込 / 〇月〇日予定 / 却下理由）
【カテゴリバランス指示】（偏りがあれば是正策、なければ「均衡」）
【現場メンバー（eevee/venusaur/zapdos等）への当日指示】
【CEO（ミュウツー）への申し送り】
" "$REPORTS/decision.md"

# Discord送信
MSG="📝 編集制作部朝会 ($TODAY) — 編集長: デオキシス

$(grep -A20 '【本日の執筆プラン】\|【本日優先する記事TOP3】\|【カテゴリバランス指示】' "$REPORTS/decision.md" | head -30)"

meeting_discord_post "publishing_log" "$MSG"

echo "✅ 編集制作部朝会 完了: $REPORTS/decision.md"
