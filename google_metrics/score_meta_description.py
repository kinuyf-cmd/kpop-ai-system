import sys, json

meta = sys.argv[1]
score = 0

if 70 <= len(meta) <= 120:
    score += 4

if any(k in meta for k in ["BTS","BLACKPINK","BIGBANG","IVE","ILLIT","SEVENTEEN","TWICE"]):
    score += 3

if any(k in meta for k in ["まとめ","解説","最新","整理"]):
    score += 2

if any(k in meta for k in ["修正","サマリー","報告"]):
    score -= 3

print(json.dumps({
    "score": score,
    "pass": score >= 6
}))
