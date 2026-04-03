import sys
import json

text = sys.argv[1].strip()

score = 0
reasons = []

length = len(text)

# 1. 長さ
if 4 <= length <= 14:
    score += 3
    reasons.append("長さ適正 +3")
elif 15 <= length <= 20:
    score += 1
    reasons.append("やや長いが許容 +1")
else:
    score -= 2
    reasons.append("長すぎ or 短すぎ -2")

# 2. 強ワード
strong_words = [
    "速報", "緊急", "衝撃", "ついに", "完全復活", "最新", "注目",
    "決定", "始動", "解禁", "発表", "判明", "史上最大級", "来日決定",
    "復活", "初公開", "大反響", "電撃", "本音", "真相"
]
if any(w in text for w in strong_words):
    score += 3
    reasons.append("強ワードあり +3")

# 3. 数字
if any(ch.isdigit() for ch in text):
    score += 2
    reasons.append("数字あり +2")

# 4. 具体性
specific_words = [
    "BTS", "BLACKPINK", "BIGBANG", "aespa", "BABYMONSTER", "ILLIT", "IVE",
    "SEVENTEEN", "TWICE", "Stray Kids", "XG", "Coachella", "MAMA",
    "ツアー", "カムバック", "新曲", "ライブ"
]
if any(w.lower() in text.lower() for w in specific_words):
    score += 2
    reasons.append("具体性あり +2")

# 5. 弱いワード
weak_words = [
    "修正箇所", "特定", "まとめ", "整理", "解説", "情報", "レポート",
    "サマリー", "考察", "チェック", "確認"
]
for w in weak_words:
    if w in text:
        score -= 3
        reasons.append(f"弱ワード『{w}』 -3")

# 6. 記号だらけ防止
if "：" in text or ":" in text:
    score -= 1
    reasons.append("記号がやや弱い -1")

result = {
    "text": text,
    "score": score,
    "length": length,
    "reasons": reasons,
    "pass": score >= 5
}

print(json.dumps(result, ensure_ascii=False))
