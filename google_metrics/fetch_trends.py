import json
import sys
import warnings
warnings.filterwarnings("ignore")

trends = {"google": [], "x": [], "combined": []}

# === Google Trends (pytrends) ===
try:
    from pytrends.request import TrendReq
    pytrends = TrendReq(hl='ja-JP', tz=540, timeout=(10,25))
    pytrends.build_payload(["K-POP"], cat=0, timeframe='now 1-d', geo='JP')
    related = pytrends.related_queries()
    rising = related.get("K-POP", {}).get("rising")
    if rising is not None and not rising.empty:
        trends["google"] = rising["query"].head(10).tolist()
except Exception as e:
    trends["google_error"] = str(e)

# === X トレンド (WebSearch経由) ===
# pytrends で代替キーワードも取得
try:
    from pytrends.request import TrendReq
    pt = TrendReq(hl='ja-JP', tz=540, timeout=(10,25))
    # K-POP関連のトレンドキーワード
    keywords = ["BTS", "BLACKPINK", "aespa", "SEVENTEEN", "IVE"]
    interest = pt.trending_searches(pn='japan')
    if interest is not None and not interest.empty:
        kpop_trends = [t for t in interest[0].tolist() if any(
            k in t for k in ["BTS","BLACKPINK","K-POP","Kpop","韓国","アイドル","カムバック","コンサート"]
        )]
        trends["x"] = kpop_trends[:10]
except Exception as e:
    trends["x_error"] = str(e)

# 統合（重複除去）
combined = list(dict.fromkeys(trends["google"] + trends["x"]))
trends["combined"] = combined[:15]

print(json.dumps(trends, ensure_ascii=False, indent=2))
