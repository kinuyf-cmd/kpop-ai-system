import json
import sys

data = json.load(sys.stdin)

ga4 = data.get("ga4", {})
gsc = data.get("gsc", {})
ads = data.get("adsense", {})

SITE_URL = "https://www.kpopjournal.tokyo"

pages = {}

# === GA4 ===
for p in ga4.get("top_landing_pages", []):
    url = p["page"]
    if url and not url.startswith("http"):
        url = SITE_URL + url
    pages.setdefault(url, {})
    pages[url]["sessions"] = int(p.get("sessions", 0))
    pages[url]["engaged"] = int(p.get("engaged_sessions", 0))
    pages[url]["duration"] = float(p.get("avg_session_duration", 0))

# === GSC ===
for p in gsc.get("top_pages", []):
    url = p["page"]
    pages.setdefault(url, {})
    pages[url]["clicks"] = float(p.get("clicks", 0))
    pages[url]["impressions"] = float(p.get("impressions", 0))
    pages[url]["ctr"] = float(p.get("ctr", 0))
    pages[url]["position"] = float(p.get("position", 100))

# === スコア計算 ===
results = []

for url, v in pages.items():
    sessions = v.get("sessions", 0)
    engaged = v.get("engaged", 0)
    duration = v.get("duration", 0)
    ctr = v.get("ctr", 0)
    position = v.get("position", 100)

    # SEOスコア（順位）
    seo_score = max(0, 10 - (position / 10))

    # CTRスコア
    ctr_score = min(10, ctr * 100)

    # エンゲージスコア
    if sessions > 0:
        engage_rate = engaged / sessions
    else:
        engage_rate = 0

    engage_score = min(10, engage_rate * 10)

    # 滞在スコア
    duration_score = min(10, duration / 60)

    # 総合
    total = round(
        (seo_score * 0.3 +
         ctr_score * 0.3 +
         engage_score * 0.2 +
         duration_score * 0.2), 2
    )

    results.append({
        "url": url,
        "seo": round(seo_score, 1),
        "ctr": round(ctr_score, 1),
        "engage": round(engage_score, 1),
        "total": total
    })

# ソート
results = sorted(results, key=lambda x: x["total"], reverse=True)

print(json.dumps(results, indent=2, ensure_ascii=False))
