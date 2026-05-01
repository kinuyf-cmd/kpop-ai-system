"""部門内雑談 (各部門で1名が業務状況を発言、朝夕2回)
GPT廃止 — テンプレートベースでコスト削減 (2026-04-30)
"""
import json, sys, time
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.discord_client import post_as_staff
from lib.staff_persona import get_random_active_member


def main():
    try:
        roster = json.load(open("config/staff_roster.json", encoding="utf-8"))
    except Exception:
        return

    for dept_name in roster.get("departments", {}):
        sid = get_random_active_member(dept_name)
        if not sid:
            continue
        info = roster["individual_staff"].get(sid, {})
        code = info.get("code_name", sid)
        queue = len(info.get("task_queue", []))
        done = len(info.get("completed_tasks", []))
        post_as_staff(sid, f"{code}です。キュー{queue}件、累計完了{done}件。業務継続中。")
        time.sleep(0.3)

    from datetime import datetime
    print(f"[{datetime.now().isoformat()}] dept_chatter 完了: {len(roster.get('departments', {}))}部門")


if __name__ == "__main__":
    main()
