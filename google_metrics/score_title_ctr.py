import re
import sys
import json

title = sys.argv[1].strip()

score = 0
reasons = []

# 1. アーティスト名
artist_keywords = [
    "bts", "blackpink", "bigbang", "aespa", "babymonster", "illit", "ive",
    "le sserafim", "seventeen", "twice", "stray kids", "newjeans", "xg",
    "nct", "riize", "monsta x", "zerobaseone", "exo", "itzy", "boa"
]
title_l = title.lower()

if any(k in title_l for k in artist_keywords):
    score += 3
    reasons.append("アーティスト名あり +3")

# 2. 数字・日付
if re.search(r'[0-9０-９]+', title):
    score += 2
    reasons.append("数字あり +2")

# 3. 具体イベント名
event_keywords = [
    "coachella", "billboard", "ツアー", "ワールドツアー", "来日", "ライブ",
    "カムバック", "アルバム", "新曲", "mv", "ファンミ", "コンサート",
    "mama", "人気歌謡", "music bank", "m countdown", "festival", "フェス"
]
if any(k.lower() in title_l for k in event_keywords):
    score += 2
    reasons.append("イベント名あり +2")

# 4. 感情ワード・強ワード
emotion_keywords = [
    "速報", "緊急", "衝撃", "ついに", "完全復活", "最新", "話題", "注目",
    "決定", "始動", "解禁", "発表", "判明"
]
if any(k in title for k in emotion_keywords):
    score += 2
    reasons.append("強ワードあり +2")

# 5. 長さ
length = len(title)
if 24 <= length <= 38:
    score += 1
    reasons.append("長さ適正 +1")

# 6. 弱いワード減点
weak_keywords = [
    "修正箇所", "特定", "サマリー", "まとめました", "解説しました",
    "考えてみた", "整理", "修正内容", "報告"
]
for wk in weak_keywords:
    if wk in title:
        score -= 3
        reasons.append(f"弱ワード『{wk}』 -3")

# 7. 汎用すぎるタイトル減点
if title in ["速報", "K-POP速報", "最新情報", "まとめ"]:
    score -= 5
    reasons.append("汎用タイトル -5")

result = {
    "title": title,
    "score": score,
    "length": length,
    "reasons": reasons,
    "pass": score >= 7
}

print(json.dumps(result, ensure_ascii=False))
