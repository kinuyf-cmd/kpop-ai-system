import json
import sys

data = json.load(sys.stdin)

gsc = data.get("gsc", {})
pages = gsc.get("top_pages", [])

results = []

for p in pages:
    page = p.get("page", "")
    impressions = float(p.get("impressions", 0) or 0)
    ctr = float(p.get("ctr", 0) or 0)
    clicks = float(p.get("clicks", 0) or 0)
    position = float(p.get("position", 999) or 999)

    # 条件:
    # - ある程度表示されている
    # - CTRが低い
    # - 順位は悪すぎない（改善余地あり）
    if impressions >= 10 and ctr < 0.10 and position <= 30:
        results.append({
            "page": page,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": ctr,
            "position": position
        })

print(json.dumps(results, ensure_ascii=False, indent=2))
