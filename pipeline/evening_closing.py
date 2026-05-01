"""毎夜23:00 終礼 (全59名が独立人格でGPT発言)"""
import json, sys, time
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime
from lib.discord_client import post_as_staff, post_to_channel


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    post_to_channel(
        "📅-朝会-終礼",
        f"## 🌙 終礼 {today}\n司会: デオキシス (CEO)\n各部門報告 → 各部員 本日完了報告。",
    )

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

        done = sum(
            1 for m in members
            for t in roster["individual_staff"].get(m.get("staff_id", ""), {}).get("completed_tasks", [])
            if str(t.get("ended_at", "")).startswith(today)
        )
        failed = sum(
            1 for m in members
            for t in roster["individual_staff"].get(m.get("staff_id", ""), {}).get("failed_tasks", [])
            if str(t.get("ended_at", "")).startswith(today)
        )

        # 部門長報告 (テンプレートベース — GPT廃止でコスト削減 2026-04-30)
        code_name = head.get('code_name', head_sid)
        post_as_staff(head_sid,
                      f"【{dept_name}】{code_name}です。本日完了{done}件、失敗{failed}件。お疲れさまでした。")
        time.sleep(0.3)

    post_to_channel(
        "📅-朝会-終礼",
        "---\n本日も全社員お疲れさまでした。\n— デオキシス (CEO)",
    )
    print(f"[{datetime.now().isoformat()}] evening_closing 完了: {len(roster.get('departments', {}))}部門")


if __name__ == "__main__":
    main()
