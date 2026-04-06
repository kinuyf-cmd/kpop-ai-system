"""
サムネイル文言スコアリング v3

評価基準:
  1. 文字数 (1行あたり最大14文字、最大2行)
  2. 訴求ワード (感情を動かす強ワード)
  3. 数字 (具体性)
  4. アーティスト名 (具体性)
  5. 弱ワード (減点)
  6. 行数・文字切れリスク (減点)
  7. 感情訴求 (ファンの心を掴む表現)

通過基準: score >= 5
"""
import sys
import json

raw = sys.argv[1].strip()

# 2行テキストの場合、改行で分割
lines = raw.split("\n")
lines = [l.strip() for l in lines if l.strip()]

# 全体テキスト（スコアリング用）
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

# 2. 各行の文字数チェック
all_lines_ok = True
for i, line in enumerate(lines):
    line_len = len(line)
    if line_len <= 14:
        if i == 0:
            score += 2
            reasons.append(f"L{i+1}: {line_len}文字 OK +2")
    else:
        score -= 2
        reasons.append(f"L{i+1}: {line_len}文字 超過 -2")
        all_lines_ok = False

if all_lines_ok and lines:
    score += 1
    reasons.append("全行14文字以内 +1")

# 3. 訴求ワード（強ワード）
strong_words = [
    "速報", "ついに", "電撃", "初公開", "復活", "決定", "解禁",
    "発表", "判明", "大反響", "衝撃", "新曲", "カムバ",
    "最新", "注目", "始動", "来日決定", "本音", "真相",
    "神", "炎上", "暴露", "激白", "独占",
]
matched_strong = [w for w in strong_words if w in text]
if matched_strong:
    score += 3
    reasons.append(f"強ワード({','.join(matched_strong)}) +3")

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
    "号泣", "感動", "泣ける", "鳥肌", "神", "最高", "やばい",
    "待望", "念願", "奇跡", "伝説", "歴代", "歴史的",
]
if any(w in text for w in emotion_words):
    score += 1
    reasons.append("感情訴求 +1")

# 7. 弱ワード（減点）
weak_words = [
    "修正箇所", "特定", "まとめ", "整理", "解説", "情報", "レポート",
    "サマリー", "考察", "チェック", "確認",
]
for w in weak_words:
    if w in text:
        score -= 3
        reasons.append(f"弱ワード『{w}』 -3")

# 8. 大げさ表現
exaggerated = ["緊急", "史上最大級"]
for w in exaggerated:
    if w in text:
        score -= 1
        reasons.append(f"大げさ『{w}』 -1")

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
