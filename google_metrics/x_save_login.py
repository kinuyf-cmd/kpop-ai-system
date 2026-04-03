"""
X/Twitterログインセッション保存スクリプト
ブラウザが開くので手動でログインし、ログイン完了後にターミナルでEnterを押す。
セッションが ~/google_metrics/x_login.json に保存される。

Usage: python3 ~/google_metrics/x_save_login.py
"""
from playwright.sync_api import sync_playwright
import os

STORAGE_PATH = os.path.expanduser("~/google_metrics/x_login.json")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    page.goto("https://x.com/login")
    print("")
    print("=" * 50)
    print("  ブラウザでXにログインしてください")
    print("  ログイン完了後、ホーム画面が表示されたら")
    print("  このターミナルでEnterを押してください")
    print("=" * 50)
    print("")

    input(">>> Enterで保存...")

    context.storage_state(path=STORAGE_PATH)
    browser.close()

print(f"✅ ログインセッション保存完了: {STORAGE_PATH}")
