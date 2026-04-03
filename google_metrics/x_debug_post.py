"""デバッグ用: 各ステップでスクリーンショットを撮って状態を確認"""
from playwright.sync_api import sync_playwright
import os
from pathlib import Path

STORAGE_PATH = os.path.expanduser("~/google_metrics/x_login.json")
CHROME_PATH = os.path.expanduser("~/Library/Caches/ms-playwright/chromium-1208/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
DEBUG_DIR = os.path.expanduser("~/google_metrics/x_debug")
os.makedirs(DEBUG_DIR, exist_ok=True)

text = "K-POPジャーナル自動投稿テスト2 #KPOP #テスト"

with sync_playwright() as p:
    launch_args = {"headless": True}
    if Path(CHROME_PATH).exists():
        launch_args["executable_path"] = CHROME_PATH

    browser = p.chromium.launch(**launch_args)
    context = browser.new_context(
        storage_state=STORAGE_PATH,
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    # Step 1: compose画面を開く
    print("Step 1: compose画面を開く...")
    page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    page.screenshot(path=f"{DEBUG_DIR}/01_compose.png")
    print(f"  URL: {page.url}")
    print(f"  スクショ: {DEBUG_DIR}/01_compose.png")

    # Step 2: ページ内容を確認
    print("Step 2: ページ内容確認...")
    title = page.title()
    print(f"  タイトル: {title}")

    # ログイン状態確認
    if "login" in page.url.lower():
        print("  ❌ ログインページにリダイレクトされた → セッション無効")
        page.screenshot(path=f"{DEBUG_DIR}/02_login_redirect.png")
        browser.close()
        exit(1)

    # Step 3: テキストボックスを探す
    print("Step 3: テキストボックス探索...")
    textboxes = page.locator("div[role='textbox']")
    print(f"  textbox数: {textboxes.count()}")
    page.screenshot(path=f"{DEBUG_DIR}/03_before_input.png")

    if textboxes.count() == 0:
        print("  テキストボックスなし → HTML確認")
        html = page.content()
        with open(f"{DEBUG_DIR}/page.html", "w") as f:
            f.write(html)
        print(f"  HTML保存: {DEBUG_DIR}/page.html")
        browser.close()
        exit(1)

    # Step 4: テキスト入力
    print("Step 4: テキスト入力...")
    textboxes.first.click()
    page.wait_for_timeout(500)
    textboxes.first.fill(text)
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{DEBUG_DIR}/04_after_input.png")

    # Step 5: 投稿ボタン確認
    print("Step 5: 投稿ボタン探索...")
    btn1 = page.locator("button[data-testid='tweetButton']")
    btn2 = page.locator("button[data-testid='tweetButtonInline']")
    print(f"  tweetButton: {btn1.count()}")
    print(f"  tweetButtonInline: {btn2.count()}")

    post_btn = btn1 if btn1.count() > 0 else btn2
    if post_btn.count() > 0:
        is_disabled = post_btn.first.is_disabled()
        print(f"  disabled: {is_disabled}")
        aria = post_btn.first.get_attribute("aria-disabled")
        print(f"  aria-disabled: {aria}")

    # Step 6: 投稿クリック
    print("Step 6: 投稿ボタンクリック...")
    post_btn.first.click(force=True)
    page.wait_for_timeout(5000)
    page.screenshot(path=f"{DEBUG_DIR}/06_after_click.png")
    print(f"  URL: {page.url}")

    print(f"\nデバッグ画像: {DEBUG_DIR}/")
    browser.close()
