"""
サムネイル文言スコアリング v4

評価基準:
  1. 文字数 (1行あたり最大10文字、最大2行)
  2. 強ワード (感情を動かす表現 必須)
  3. 数字 (具体性)
  4. アーティスト名
  5. 弱ワード・抽象表現 (減点)
  6. 感情訴求

通過基準: score >= 5
"""
import sys
import json

raw = sys.argv[1].strip()

lines = raw.split("\n")
lines = [l.strip() for l in lines if l.strip()]

text = " ".join(lines)

score = 0
reasons = []

# 1. 行数チェック
if len(lines) > 2:
    score -= 3
    reasons.append(f"3行以上({len(lines)}行) -3")
elif len(lines) == 2:
    score += 1
    reasons.append("2行構成 +1")

# 2. 各行の文字数チェック（10文字制限）
all_lines_ok = True
for i, line in enumerate(lines):
    line_len = len(line)
    if line_len <= 10:
        if i == 0:
            score += 2
            reasons.append(f"L{i+1}: {line_len}文字 OK +2")
    else:
        score -= 2
        reasons.append(f"L{i+1}: {line_len}文字 超過 -2")
        all_lines_ok = False

if all_lines_ok and lines:
    score += 1
    reasons.append("全行10文字以内 +1")

# 3. 強ワード（感情を動かす表現 = 必須）
strong_words = [
    "衝撃", "速報", "ついに", "電撃", "判明", "復活", "決定", "解禁",
    "初公開", "大反響", "騒然", "まさか", "完全", "即完売",
    "神", "炎上", "暴露", "激白", "独占",
    "レベチ", "バグ", "尊い", "やばい", "ヤバい",
    "真相", "裏側", "闇", "結論",
]
matched_strong = [w for w in strong_words if w in text]
if matched_strong:
    score += 3
    reasons.append(f"強ワード({','.join(matched_strong[:3])}) +3")
else:
    score -= 2
    reasons.append("強ワードなし -2")

# 4. 数字
if any(ch.isdigit() for ch in text):
    score += 2
    reasons.append("数字あり +2")

# 5. アーティスト名
artist_words = [
    "BTS", "BLACKPINK", "BIGBANG", "aespa", "BABYMONSTER", "ILLIT", "IVE",
    "SEVENTEEN", "TWICE", "Stray Kids", "XG", "NewJeans", "LE SSERAFIM",
    "NCT", "RIIZE", "PLAVE", "KATSEYE", "KISS OF LIFE", "TXT", "ENHYPEN",
    "ITZY", "NMIXX", "(G)I-DLE", "RED VELVET", "EXO", "SHINee", "T.O.P",
    "G-DRAGON", "ZEROBASEONE", "Mark Lee",
]
if any(w.lower() in text.lower() for w in artist_words):
    score += 2
    reasons.append("アーティスト名あり +2")

# 6. 感情訴求
emotion_words = [
    "号泣", "感動", "泣ける", "鳥肌", "神", "最高",
    "待望", "念願", "奇跡", "伝説", "歴代", "歴史的",
    "尊い", "沼", "推せる",
]
if any(w in text for w in emotion_words):
    score += 1
    reasons.append("感情訴求 +1")

# 7. 弱ワード・抽象表現（厳しく減点）
weak_words = [
    "修正箇所", "特定", "まとめ", "整理", "情報", "レポート",
    "サマリー", "チェック", "確認", "最新情報",
]
for w in weak_words:
    if w in text:
        score -= 3
        reasons.append(f"弱ワード『{w}』 -3")

# 8. 説明的・抽象的表現（NG）
abstract_patterns = [
    "日ぶりの", "についてまとめ", "を紹介", "を解説",
]
for p in abstract_patterns:
    if p in text:
        score -= 2
        reasons.append(f"抽象表現『{p}』 -2")

# 9. コロン使用
if "：" in text or ":" in text:
    score -= 1
    reasons.append("コロン使用 -1")

result = {
    "text": raw,
    "lines": lines,
    "score": score,
    "line_count": len(lines),
    "line_lengths": [len(l) for l in lines],
    "reasons": reasons,
    "pass": score >= 5
}

print(json.dumps(result, ensure_ascii=False))
