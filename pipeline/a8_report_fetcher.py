"""A8.net 収益レポート取得 (Playwright scraping)
cron: 0 7 * * * (A8 credentials設定後に有効化)
credentials: A8NET_LOGIN_ID / A8NET_PASSWORD in .env"""
import os, json
from datetime import datetime

def main():
    uid = os.getenv('A8NET_LOGIN_ID') or os.getenv('A8_USER')
    pw = os.getenv('A8NET_PASSWORD') or os.getenv('A8_PASS')
    today = datetime.now().strftime('%Y%m%d')

    if not uid or not pw:
        print('A8 credentials未設定 — .envにA8NET_LOGIN_ID/A8NET_PASSWORDを追加後に再実行')
        out = {'date': today, 'status': 'credentials_missing', 'data': None}
    else:
        try:
            from playwright.sync_api import sync_playwright
            # Playwright scraping logic here (to be implemented when credentials available)
            out = {'date': today, 'status': 'not_implemented', 'data': None}
        except ImportError:
            print('Playwright未インストール: pip install playwright && playwright install chromium')
            out = {'date': today, 'status': 'playwright_missing', 'data': None}

    os.makedirs('logs', exist_ok=True)
    with open(f'logs/a8_revenue_{today}.json', 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'A8 status: {out["status"]}')

if __name__ == '__main__':
    main()
