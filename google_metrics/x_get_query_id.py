"""X内部APIのCreateTweetのqueryIdを最新取得"""
from playwright.sync_api import sync_playwright
import os, re, json
from pathlib import Path

STORAGE_PATH = os.path.expanduser("~/google_metrics/x_login.json")
CHROME_PATH = os.path.expanduser("~/Library/Caches/ms-playwright/chromium-1208/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")

with sync_playwright() as p:
    launch_args = {"headless": True}
    if Path(CHROME_PATH).exists():
        launch_args["executable_path"] = CHROME_PATH
    launch_args["args"] = ["--disable-blink-features=AutomationControlled"]

    browser = p.chromium.launch(**launch_args)
    context = browser.new_context(
        storage_state=STORAGE_PATH,
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    # main.jsを読んでqueryIdを見つける
    query_ids = {}

    def handle_response(response):
        if "client-web" in response.url and response.url.endswith(".js"):
            try:
                body = response.text()
                # CreateTweetのqueryIdを検索
                matches = re.findall(r'\{queryId:"([^"]+)"[^}]*operationName:"(CreateTweet)"', body)
                for qid, name in matches:
                    query_ids[name] = qid
                    print(f"  Found: {name} = {qid}")
            except:
                pass

    page.on("response", handle_response)
    page.goto("https://x.com/home", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(5000)

    if "CreateTweet" in query_ids:
        print(f"\n✅ CreateTweet queryId: {query_ids['CreateTweet']}")
        # 保存
        with open(os.path.expanduser("~/google_metrics/x_query_ids.json"), "w") as f:
            json.dump(query_ids, f, indent=2)
    else:
        print("\n⚠ CreateTweet queryIdが見つからず")
        print(f"  取得済み: {list(query_ids.keys())}")

    browser.close()
