"""
X/Twitter投稿文スコアリング

Usage:
  python3 google_metrics/score_x_post.py "投稿テキスト"

Output: JSON {"text", "score", "reasons", "pass"}
Pass threshold: score >= 5
"""
import re
import sys
import json

text = sys.argv[1].strip() if len(sys.argv) > 1 else ""

score = 0
reasons = []

# 1. 強い導入（結論ファースト）: +3
weak_openings = ["皆さん", "こんにちは", "お知らせ", "お疲れ", "今日は", "本日は"]
first_20 = text[:20]
if any(text.startswith(w) for w in weak_openings):
    score -= 3
    reasons.append("弱い導入 -3")
else:
    strong_words = [
        "速報", "緊急", "衝撃", "決定", "発表", "解禁", "判明", "ついに",
        "BTS", "BLACKPINK", "aespa", "SEVENTEEN", "Stray Kids", "NewJeans",
        "IVE", "LE SSERAFIM", "XG", "TWICE", "NCT", "ILLIT", "RIIZE",
    ]
    if any(w in first_20 for w in strong_words):
        score += 3
        reasons.append("強い導入 +3")
    elif len(first_20) > 5:
        score += 1
        reasons.append("導入普通 +1")

# 2. URL含む: +2
if "http" in text:
    score += 2
    reasons.append("URL含む +2")

# 3. ハッシュタグ数: 2-4 = +2, 1 = +1, 0/5+ = 0
hashtag_count = len(re.findall(r'#\S+', text))
if 2 <= hashtag_count <= 4:
    score += 2
    reasons.append(f"ハッシュタグ{hashtag_count}個 +2")
elif hashtag_count == 1:
    score += 1
    reasons.append("ハッシュタグ1個 +1")
elif hashtag_count == 0:
    reasons.append("ハッシュタグなし +0")
elif hashtag_count >= 5:
    score -= 1
    reasons.append(f"ハッシュタグ過多({hashtag_count}個) -1")

# 4. #KPOP含む: +1
if re.search(r'#[Kk]-?[Pp][Oo][Pp]', text):
    score += 1
    reasons.append("#KPOP含む +1")

# 5. 文字長 80-200文字: +2
text_len = len(text)
if 80 <= text_len <= 200:
    score += 2
    reasons.append(f"長さ適正({text_len}文字) +2")
elif 50 <= text_len < 80:
    score += 1
    reasons.append(f"やや短い({text_len}文字) +1")
elif text_len > 280:
    score -= 2
    reasons.append(f"文字数超過({text_len}文字) -2")

# 6. アーティスト/イベント名含む: +1
artist_keywords = [
    "bts", "blackpink", "aespa", "seventeen", "stray kids", "newjeans",
    "ive", "le sserafim", "xg", "twice", "nct", "illit", "riize",
    "babymonster", "zerobaseone", "itzy", "exo", "bigbang", "monsta x",
    "カムバック", "ツアー", "ライブ", "コンサート", "mv", "アルバム",
]
text_l = text.lower()
if any(k in text_l for k in artist_keywords):
    score += 1
    reasons.append("アーティスト/イベント名 +1")

# 7. 未確認情報の断定: -3
unverified_patterns = [r'確定(?!的)', r'100%', r'間違いない', r'絶対に']
for pat in unverified_patterns:
    if re.search(pat, text):
        score -= 3
        reasons.append(f"未確認情報の断定 -3")
        break

# 8. 過剰な感嘆符: -2
exclamation_count = text.count('!') + text.count('！')
if exclamation_count > 3:
    score -= 2
    reasons.append(f"感嘆符過多({exclamation_count}個) -2")

result = {
    "text": text[:100],
    "score": score,
    "length": text_len,
    "hashtags": hashtag_count,
    "reasons": reasons,
    "pass": score >= 5
}

print(json.dumps(result, ensure_ascii=False))
