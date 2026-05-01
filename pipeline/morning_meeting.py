"""毎朝07:30 朝会 (全59名が独立人格でGPT発言)"""
import json, sys, os, time
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timedelta
from lib.discord_client import post_as_staff, post_to_channel


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    post_to_channel(
        "📅-朝会-終礼",
        f"## 🌅 朝会 {today}\n司会: デオキシス (CEO)\n各部門長から報告 → 各部員から本日業務予定。",
    )

    # 朝会冒頭: 全pipeline稼働状況報告 (4/27再発防止策)
    try:
        if os.path.exists('logs/pipeline_health_status.json'):
            health = json.load(open('logs/pipeline_health_status.json'))
            crit = len(health.get('critical', []))
            warn = len(health.get('warning', []))
            if crit > 0:
                lines = [f"**CRITICAL: pipeline停止 {crit}件検知。即時対応必要**"]
                for p in health.get('critical', [])[:5]:
                    silent = p.get('silent_min', '?')
                    detail = p.get('issue', f'{silent}分沈黙')
                    lines.append(f"  - `{p.get('pipeline')}`: {detail}")
                post_to_channel("📅-朝会-終礼", '\n'.join(lines))
            elif warn > 0:
                post_to_channel("📅-朝会-終礼", f"pipeline警告 {warn}件 (継続観察)")
            else:
                post_to_channel("📅-朝会-終礼", "全pipeline正常稼働")
    except Exception as e:
        print(f'pipeline health報告err: {e}')

    try:
        roster = json.load(open("config/staff_roster.json", encoding="utf-8"))
    except Exception:
        return

    for dept_name, dept in roster.get("departments", {}).items():
        head = dept.get("head", {})
        head_sid = head.get("staff_id")
        if not head_sid:
            continue
        members = dept.get("members", [])

        # 集計
        total_done = sum(
            1 for m in members
            for t in roster["individual_staff"].get(m.get("staff_id", ""), {}).get("completed_tasks", [])
            if str(t.get("ended_at", "")).startswith(yest)
        )
        total_queue = sum(
            len(roster["individual_staff"].get(m.get("staff_id", ""), {}).get("task_queue", []))
            for m in members
        )

        # 部門長報告 → #朝会-終礼 (テンプレートベース — GPT廃止でコスト削減 2026-04-30)
        code_name = head.get('code_name', head_sid)
        post_as_staff(head_sid,
                      f"【{dept_name}】{code_name}です。"
                      f"部員{len(members)}名、前日完了{total_done}件、本日待機{total_queue}件。業務開始します。")
        time.sleep(0.3)

    post_to_channel(
        "📅-朝会-終礼",
        "---\n以上、全社員出社確認。各部門業務開始。\n— デオキシス (CEO)",
    )
    print(f"[{datetime.now().isoformat()}] morning_meeting 完了: {len(roster.get('departments', {}))}部門")


if __name__ == "__main__":
    main()
