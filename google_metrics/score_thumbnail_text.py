"""
サムネイル文言スコアリング v5 (100点満点)

評価基準 (100点満点):
  1. 数字（例: 641,000 / 3週連続）→ +25
  2. 固有名詞（BTS/BLACKPINKなど）→ +25
  3. 対比構造（復帰/空白/異常/vs/→）→ +20
  4. 感情語（衝撃・異常・ついに・判明など）→ +15
  5. 2行構造適正（15文字以内×2行）→ +15

判定:
  score < 40   → pass: false, block: true
  40 ≤ score < 80 → pass: true, block: false, warning: true
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

    # 2026-04-16 Round7: 意味論BLOCK — 具体性ゼロの汎用テンプレ句パターンを構造的に落とす
    # これらの句は「どの記事にも成立してしまう」ため固有名・具体数字を欠いた状態では必ず不採用
    _GENERIC_PHRASES = [
        r'^\d+市場の?$',          # 「3市場の」「5市場」
        r'^真相判明$',             # 「真相判明」単独
        r'^全容判明$',
        r'^全容がこれ$',
        r'^なぜ勝てた$',
        r'^業界が驚いた$',
        r'^結論出た$',
        r'^結論が出た$',
        r'^衝撃の展開$',
        r'^ついに判明$',
        r'^完全ガイド$',
        r'^完全版$',
        r'^最新情報$',
        r'^知らないと損$',
    ]
    _generic_hits = []
    for line in lines:
        l = line.strip()
        for pat in _GENERIC_PHRASES:
            if re.fullmatch(pat, l):
                _generic_hits.append(l)
    # 2行とも汎用句 もしくは 1行汎用+もう1行も固有名/数字ゼロ の場合のみBLOCK
    if len(_generic_hits) >= 2:
        blocked = True
        block_reasons.append(f"汎用句のみで構成（具体性ゼロ）: {_generic_hits}")
    elif len(_generic_hits) == 1 and len(lines) >= 2:
        # 残り1行に固有名か数字（2桁以上 or 単位付き1桁）が無ければBLOCK
        other = [l for l in lines if l.strip() not in _generic_hits]
        if other:
            o = other[0]
            has_digit = bool(re.search(r'\d\d|\d[万億千百冠ぶり枚位週連続形態年日]', o))
            has_latin = bool(re.search(r'[A-Za-z]{3,}', o))  # aespa/IVE/BTS等（小文字含む）
            has_katakana_3 = bool(re.search(r'[ァ-ヴー]{3,}', o))
            # 既知アーティスト略称/メンバー名が含まれるかの直接判定（2文字でも許可）
            _quick_artists = ["BTS","IVE","NCT","EXO","TXT","XG","ITZY","SHINee",
                              "ジス","ジミン","ロゼ","リサ","ユナ","サナ","レイ"]
            has_known = any(a.lower() in o.lower() for a in _quick_artists)
            if not (has_digit or has_latin or has_katakana_3 or has_known):
                blocked = True
                block_reasons.append(f"汎用句+具体性欠落: {_generic_hits[0]} / {o}")

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
    # 2026-04-16: 日本語カタカナ略称を追加（raikou_thumbが10文字制約下で短縮形を使う実測に基づく）
    artist_words = [
        "BTS", "BLACKPINK", "BIGBANG", "aespa", "BABYMONSTER", "ILLIT", "IVE",
        "SEVENTEEN", "TWICE", "Stray Kids", "XG", "NewJeans", "LE SSERAFIM",
        "NCT", "RIIZE", "PLAVE", "KATSEYE", "KISS OF LIFE", "TXT", "ENHYPEN",
        "ITZY", "NMIXX", "(G)I-DLE", "RED VELVET", "EXO", "SHINee", "T.O.P",
        "G-DRAGON", "ZEROBASEONE", "Mark Lee", "JIMIN", "ジミン", "ジョングク",
        "テヒョン", "ソクジン", "ナムジュン", "ホソク", "ユンギ",
        "ジェニー", "ロゼ", "リサ", "ジス",
        # --- カタカナ略称（サムネで短縮されるため必須） ---
        "ベビモン", "ブルピン", "ルセラ", "ルセラフィム", "スキズ", "セブチ",
        "エスパ", "ニュジ", "トゥワイス", "ライズ", "アチズ", "エナプ",
        "アイヴ", "アイリット", "ウィンター", "カリナ", "ジードラゴン", "トップ",
        "ニュージーンズ", "防弾少年団", "ブラックピンク", "ビッグバン",
        # --- メンバー名（個人記事で頻出） ---
        "ウォニョン", "ユジン", "レイ", "リズ", "ガウル", "イソ",
        "チェウォン", "カズハ", "サクラ", "ユンジン", "ホユン",
        "ミンジ", "ハニ", "ダニエル", "ヘイン", "ヘリン",
        "ジス", "ジェニー", "ロゼ", "リサ",
        "カリナ", "ジゼル", "ニンニン",
        "ナヨン", "ジョンヨン", "モモ", "サナ", "ジヒョ", "ミナ", "ダヒョン", "チェヨン", "ツウィ",
        "ユナ", "リュジン", "イェジ", "チェリョン",
        "フェリックス", "バンチャン", "チャンビン", "リノ", "ハン", "ヒョンジン", "スンミン", "アイエン",
        "ジョンウン", "ソロン",  # IVE全員
        # --- SHINee メンバー ---
        "テミン", "オンユ", "ミンホ", "キー", "Taemin", "TAEMIN",
        # --- 楽曲・アルバム名（タイトルフックで頻出） ---
        "SWIM", "CHOOM", "FATE", "Supernova", "Whiplash",
        "Magnetic", "Cheer Up", "FEARLESS", "LOVE DIVE", "After Like",
        "HIPS", "Crazy", "Smart", "UNFORGIVEN",
    ]
    matched_artists = [w for w in artist_words if w.lower() in text.lower()]
    if matched_artists:
        score += 25
        reasons.append(f"固有名詞({','.join(matched_artists[:2])}) +25")

    # 3. 対比構造 (最大20点)
    # 2026-04-16追加: K-POP記事実測で頻出する達成・更新・選出系を追加
    contrast_patterns = ["復帰", "空白", "異常", " vs ", "VS", "→", "⇒", "急落", "急騰",
                         "一転", "激変", "崩壊", "解散", "脱退", "電撃", "電撃復帰",
                         "制覇", "独走", "独占", "塗替", "更新", "超え", "初めて", "歴代最", "圧倒",
                         # 選出・抜擢・受賞系（ファッション・広告記事で頻出）
                         "抜擢", "選出", "選抜", "起用", "受賞", "初選出", "最年少",
                         # 舞台・イベント系
                         "パリコレ", "ミラコレ", "アワード", "出演", "初出演", "降臨",
                         # デビュー・初系
                         "デビュー", "初登場", "初お披露目", "世界初",
                         # チャート・ランキング転換
                         "ランクイン", "陥落", "首位", "圏外"]
    matched_contrasts = [w for w in contrast_patterns if w in text]
    if matched_contrasts:
        score += 20
        reasons.append(f"対比構造({','.join(matched_contrasts[:2])}) +20")

    # 4. 感情語 (最大15点)
    # 2026-04-16追加: raikou_thumbの良質出力で頻出する具体語を辞書化
    emotion_words = [
        "衝撃", "異常", "ついに", "判明", "速報", "まさか", "爆発", "炎上",
        "暴露", "激白", "騒然", "完全", "神", "伝説", "歴史的", "奇跡",
        "待望", "号泣", "鳥肌", "やばい", "ヤバい", "バグ", "尊い",
        "真相", "解禁", "初公開", "大反響",
        # --- K-POP成功・達成系（raikou頻出） ---
        "快挙", "達成", "大成功", "爆誕", "激震", "異次元", "席巻", "完勝",
        "全解剖", "全公開", "全貌", "覚醒", "超絶", "本気", "神回",
        # --- 美容・ファッション記事の訴求語（beauty/fashionで頻出） ---
        "ガラス肌", "神コスメ", "神肌", "美肌", "神コーデ", "即完売",
        "爆売れ", "バズり", "神レシピ", "最強", "神選出",
        # --- CTRトリガー汎用語（2026-04-16 Round5追加） ---
        "秘密", "プロ直伝", "本音", "衝撃告白", "全部見せ",
        "完全網羅", "徹底ガイド", "必見", "保存版", "永久保存",
        # --- 3rd/4th 等の序数（アルバム順序）---
        "第3弾", "第4弾", "第5弾",
    ]
    matched_emotions = [w for w in emotion_words if w in text]
    if matched_emotions:
        # 2026-04-16 Round6: 密度ボーナス（2個以上マッチで+5点上乗せ）
        # 理由: アーティスト不在の美容/LP記事は artist/contrast を稼げず 55点止まりになる構造的問題の補正
        emo_score = 15 + (5 if len(matched_emotions) >= 2 else 0)
        score += emo_score
        reasons.append(f"感情語({','.join(matched_emotions[:2])}){'×' + str(len(matched_emotions)) if len(matched_emotions) >= 2 else ''} +{emo_score}")

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
    elif score < 40:
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
