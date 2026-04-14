"""
サムネイル文言スコアリング v5 (100点満点)

評価基準 (100点満点):
  1. 数字（例: 641,000 / 3週連続）→ +25
  2. 固有名詞（BTS/BLACKPINKなど）→ +25
  3. 対比構造（復帰/空白/異常/vs/→）→ +20
  4. 感情語（衝撃・異常・ついに・判明など）→ +15
  5. 2行構造適正（15文字以内×2行）→ +15

判定:
  score < 60   → pass: false, block: true
  60 ≤ score < 80 → pass: true, block: false, warning: true
  score ≥ 80   → pass: true, block: false

禁止パターン (score関係なく block=true):
  - ".." または "…" を含む
  - 改行なし（1行のみ）
  - 1行15文字超
  - 数字が行をまたいで分割されている
"""
import sys
import json
import re

def score_thumbnail(raw: str) -> dict:
    lines = raw.split("\n")
    lines = [l.strip() for l in lines if l.strip()]
    text = "\n".join(lines)

    score = 0
    reasons = []
    block_reasons = []

    # ---- 禁止パターンチェック ----
    blocked = False

    # ".." または "…" を含む
    if ".." in text or "…" in text:
        blocked = True
        block_reasons.append("省略記号(.../…)を含む")

    # 改行なし（1行のみ）
    if len(lines) <= 1:
        blocked = True
        block_reasons.append("改行なし（1行のみ）")

    # 1行15文字超
    for i, line in enumerate(lines):
        if len(line) > 15:
            blocked = True
            block_reasons.append(f"L{i+1}が15文字超({len(line)}文字): {line}")

    # 数字が行をまたいで分割されている
    # 1行目末尾が数字で終わり、2行目先頭も数字で始まるケース
    if len(lines) >= 2:
        if re.search(r'\d$', lines[0]) and re.search(r'^\d', lines[1]):
            blocked = True
            block_reasons.append("数字が行をまたいで分割されている")

    # ---- スコアリング ----

    # 1. 数字 (最大25点)
    number_patterns = [
        r'\d[\d,，.万億千百]*[万億千百位週連続]?',  # 数字+単位
    ]
    has_number = any(re.search(p, text) for p in number_patterns) or any(ch.isdigit() for ch in text)
    if has_number:
        score += 25
        reasons.append("数字あり +25")

    # 2. 固有名詞 (最大25点)
    artist_words = [
        "BTS", "BLACKPINK", "BIGBANG", "aespa", "BABYMONSTER", "ILLIT", "IVE",
        "SEVENTEEN", "TWICE", "Stray Kids", "XG", "NewJeans", "LE SSERAFIM",
        "NCT", "RIIZE", "PLAVE", "KATSEYE", "KISS OF LIFE", "TXT", "ENHYPEN",
        "ITZY", "NMIXX", "(G)I-DLE", "RED VELVET", "EXO", "SHINee", "T.O.P",
        "G-DRAGON", "ZEROBASEONE", "Mark Lee", "JIMIN", "ジミン", "ジョングク",
        "テヒョン", "ソクジン", "ナムジュン", "ホソク", "ユンギ",
        "ジェニー", "ロゼ", "リサ", "ジス",
    ]
    matched_artists = [w for w in artist_words if w.lower() in text.lower()]
    if matched_artists:
        score += 25
        reasons.append(f"固有名詞({','.join(matched_artists[:2])}) +25")

    # 3. 対比構造 (最大20点)
    contrast_patterns = ["復帰", "空白", "異常", " vs ", "VS", "→", "⇒", "急落", "急騰",
                         "一転", "激変", "崩壊", "解散", "脱退", "電撃", "電撃復帰"]
    matched_contrasts = [w for w in contrast_patterns if w in text]
    if matched_contrasts:
        score += 20
        reasons.append(f"対比構造({','.join(matched_contrasts[:2])}) +20")

    # 4. 感情語 (最大15点)
    emotion_words = [
        "衝撃", "異常", "ついに", "判明", "速報", "まさか", "爆発", "炎上",
        "暴露", "激白", "騒然", "完全", "神", "伝説", "歴史的", "奇跡",
        "待望", "号泣", "鳥肌", "やばい", "ヤバい", "バグ", "尊い",
        "真相", "解禁", "初公開", "大反響",
    ]
    matched_emotions = [w for w in emotion_words if w in text]
    if matched_emotions:
        score += 15
        reasons.append(f"感情語({','.join(matched_emotions[:2])}) +15")

    # 5. 2行構造適正 (最大15点): 2行 かつ 全行15文字以内
    if len(lines) == 2 and all(len(l) <= 15 for l in lines):
        score += 15
        reasons.append("2行構造適正(15文字以内×2行) +15")
    elif len(lines) >= 2 and all(len(l) <= 15 for l in lines):
        score += 8
        reasons.append(f"多行構造({len(lines)}行、全行15文字以内) +8")

    score = min(score, 100)

    # ---- 判定 ----
    if blocked:
        pass_ = False
        block = True
        warning = False
    elif score < 60:
        pass_ = False
        block = True
        warning = False
    elif score < 80:
        pass_ = True
        block = False
        warning = True
    else:
        pass_ = True
        block = False
        warning = False

    return {
        "score": score,
        "pass": pass_,
        "block": block,
        "warning": warning,
        "block_reasons": block_reasons,
        "reasons": reasons,
        "lines": lines,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: score_thumbnail_text.py <text>"}, ensure_ascii=False))
        sys.exit(1)

    raw = sys.argv[1]
    result = score_thumbnail(raw)
    print(json.dumps(result, ensure_ascii=False))
