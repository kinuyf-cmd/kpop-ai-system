"""経営指標 → Discord #📊-経営指標-board (毎日21:00)"""
import json, glob
from datetime import datetime
from lib.discord_client import post_as_staff

def main():
    today = datetime.now().strftime('%Y-%m-%d')
    post_as_staff('KPJ-0001', f'## 経営報告 {today} - デオキシス (CEO)\n全部門稼働中。')
    print(f"[{today}] board_daily_report 完了")

if __name__ == '__main__':
    main()
