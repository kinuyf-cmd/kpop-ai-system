#!/bin/bash
# timeslot_override.sh — 投稿時刻別の content_type 自動最適化
#
# kpop_master_scheduler.sh の determine_content() 出力を、
# logs/timeslot_ranking.json の実測に基づいて上書きする。
#
# **信頼できるデータが無ければ一切手を加えない** 設計。
# 既存ハードコード挙動を安全に残しつつ、データが溜まった時点で自動で賢くなる。
#
# 使い方（bash source）:
#   source lib/timeslot_override.sh
#   new_info=$(apply_timeslot_override "$HOUR" "$CONTENT_INFO")
#
# 入力:  hour, "content_type|pipeline|focus" (determine_content出力)
# 出力:  同フォーマット（上書きされた場合は中身が変わる）
# 副作用: logs/timeslot_override.log に判断を記録

_TIMESLOT_RANKING="/home/aiuser/kpop-ai-system/logs/timeslot_ranking.json"
_TIMESLOT_LOG="/home/aiuser/kpop-ai-system/logs/timeslot_override.log"

# 設定: override を発動する最低条件
# - その時間帯のサンプル数 ≥ MIN_SAMPLES
# - PV 合計 ≥ MIN_TOTAL_PV（PVが流れるまで過剰最適化を防ぐ）
# - 最高PV pipeline と 現在選択 pipeline の avg_pv 差が RATIO 倍以上
_TS_MIN_SAMPLES=5
_TS_MIN_TOTAL_PV=20
_TS_RATIO=1.5

apply_timeslot_override() {
  local hour="$1"
  local current_info="$2"
  local current_type current_pipeline current_focus
  current_type=$(echo "$current_info" | cut -d'|' -f1)
  current_pipeline=$(echo "$current_info" | cut -d'|' -f2)
  current_focus=$(echo "$current_info" | cut -d'|' -f3-)

  # データファイル無し → 既存のまま
  [ ! -f "$_TIMESLOT_RANKING" ] && { echo "$current_info"; return 0; }

  # Python で判定（bash で JSON 処理は危険）
  local result
  result=$(python3 - "$_TIMESLOT_RANKING" "$hour" "$current_pipeline" \
                   "$_TS_MIN_SAMPLES" "$_TS_MIN_TOTAL_PV" "$_TS_RATIO" <<'PY'
import json, sys
path, hour, current_pipeline, min_samp, min_pv, ratio = sys.argv[1:7]
hour = int(hour); min_samp = int(min_samp); min_pv = int(min_pv); ratio = float(ratio)

try:
    d = json.load(open(path))
except Exception:
    print("KEEP|no_data"); sys.exit()

rows = d.get("slot_pipeline", [])
# 対象時間帯の行を抽出
same_hour = [r for r in rows if r.get("hour") == hour]
if not same_hour:
    print("KEEP|hour_no_data"); sys.exit()

# 条件: 1つでも MIN_SAMPLES / MIN_TOTAL_PV を満たさなければ hold
total_pv = sum(r["avg_pv"] * r["posts"] for r in same_hour)
total_posts = sum(r["posts"] for r in same_hour)
if total_posts < min_samp:
    print(f"KEEP|samples={total_posts}<{min_samp}"); sys.exit()
if total_pv < min_pv:
    print(f"KEEP|total_pv={total_pv}<{min_pv}"); sys.exit()

# 最高PVのpipelineを選定
best = max(same_hour, key=lambda r: r["avg_pv"])
current = next((r for r in same_hour if r["pipeline"] == current_pipeline), None)

# 現在選択pipelineのデータが無ければ（別のpipelineが既に本命）override
if current is None:
    if best["avg_pv"] > 0:
        print(f"OVERRIDE|{best['pipeline']}|current_untested_best={best['pipeline']}(avg_pv={best['avg_pv']})")
    else:
        print("KEEP|best_zero_pv")
    sys.exit()

# 現在pipelineと最高pipelineの差を評価
if best["pipeline"] == current_pipeline:
    print(f"KEEP|already_best(avg_pv={best['avg_pv']})"); sys.exit()
if current["avg_pv"] == 0:
    print(f"OVERRIDE|{best['pipeline']}|current_zero_vs_best={best['avg_pv']}")
    sys.exit()
if best["avg_pv"] / current["avg_pv"] >= ratio:
    print(f"OVERRIDE|{best['pipeline']}|best={best['avg_pv']}/current={current['avg_pv']}={round(best['avg_pv']/current['avg_pv'],2)}x")
else:
    print(f"KEEP|within_ratio={round(best['avg_pv']/current['avg_pv'],2)}x<{ratio}")
PY
)

  local verdict="${result%%|*}"
  local detail="${result#*|}"

  # ログ記録
  mkdir -p "$(dirname "$_TIMESLOT_LOG")"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] hour=$hour current=$current_pipeline verdict=$verdict detail=$detail" \
    >> "$_TIMESLOT_LOG"

  if [ "$verdict" = "OVERRIDE" ]; then
    local new_pipeline="${detail%%|*}"
    # pipelineに応じたcontent_typeにマッピング（既存roteterに合わせる）
    local new_type="$current_type"
    case "$new_pipeline" in
      kpop_pipeline) new_type="breaking" ;;
      kpop_strategy) new_type="strategy" ;;
      agent_council) new_type="council" ;;
    esac
    echo "${new_type}|${new_pipeline}|${current_focus} [timeslot_override: ${detail#*|}]"
  else
    echo "$current_info"
  fi
}
