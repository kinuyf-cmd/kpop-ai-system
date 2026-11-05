#!/usr/bin/env python3
"""AdSense自動広告の不自然な位置(表の中/更新お知らせ枠の中/見出し直後)を実描画で検査する。

背景(2026-11-05): mama-awards-2026-osaka-guide で表の行の間に広告が入っていた。
テーマ側(functions.php kpj_strip_ads_inside_tables)が除去するが、テーマ改修や
AdSense側の挙動変更で再発しうるため、表のある記事を優先して実描画で定期検査する。

使い方: python3 tools/audit/ad_misplacement_audit.py [--max 12] [--notify]
違反があれば exit 1。--notify で Discord(urgent_errors)へ通知。
実行は venv_kpi/bin/python (playwright 必須)。
"""
import argparse, json, os, re, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = "https://www.kpopjournal.tokyo"
ALWAYS = ["/mama-awards-2026-osaka-guide/"]  # 過去に再現した記事は毎回検査
JS = """()=>[...document.querySelectorAll('.google-auto-placed')].map(e=>{
 const pv=e.previousElementSibling;
 return {table:!!e.closest('table'),note:!!e.closest('.kpj-update-note'),
         heading:!!(pv&&/^H[1-6]$/.test(pv.tagName))}})"""

def get(url):
    r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")

def candidates(n):
    xml = re.sub(r"\s+", "", get(BASE + "/post-sitemap.xml"))
    urls = re.findall(r"<loc>(https://www\.kpopjournal\.tokyo/[a-z0-9%-]+/)</loc>", xml)
    out = []
    for u in urls[::-1][:60]:  # 新しい側から表のある記事を探す
        try:
            if "<table" in get(u):
                out.append(u)
        except Exception:
            pass
        if len(out) >= n:
            break
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    urls = [BASE + p for p in ALWAYS] + candidates(a.max)
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for u in dict.fromkeys(urls):
            pg = b.new_page(viewport={"width": 390, "height": 844})
            try:
                pg.goto(u, wait_until="domcontentloaded", timeout=60000)
                for _ in range(40):
                    pg.mouse.wheel(0, 700); pg.wait_for_timeout(200)
                pg.wait_for_timeout(5000)
                r = pg.evaluate(JS)
                n = {k: sum(1 for x in r if x[k]) for k in ("table", "note", "heading")}
                print(u, len(r), n)
                if any(n.values()):
                    bad.append((u, n))
            except Exception as e:
                print(u, "ERR", str(e)[:60])
            pg.close()
        b.close()
    if bad and a.notify:
        try:
            wh = subprocess.run([sys.executable, os.path.join(ROOT, "lib/resolve_discord_webhook.py"), "urgent_errors"],
                                capture_output=True, text=True).stdout.strip()
            msg = "広告の不自然な位置を検出(表/お知らせ枠/見出し直後)\n" + "\n".join(f"{u} {n}" for u, n in bad)
            req = urllib.request.Request(wh, data=json.dumps({"content": msg[:1900]}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "kpj-audit"})
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print("notify failed:", e)
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
