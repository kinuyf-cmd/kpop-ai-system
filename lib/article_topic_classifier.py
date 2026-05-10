#!/usr/bin/env python3
"""
article_topic_classifier.py — Classify K-POP articles as concrete or abstract.

Concrete = about a specific artist, group, brand, place, or event.
Abstract = general topic (trends, guides, how-tos, culture, etc.).

Usage:
  python3 lib/article_topic_classifier.py --title "BTSのV、新曲MVが1億回再生突破"
"""

import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "concrete_vs_abstract.json"
THEME_CONFIG_PATH = BASE_DIR / "config" / "article_themes.json"


def _load_config() -> dict:
    """Load concrete_vs_abstract.json."""
    if not CONFIG_PATH.exists():
        sys.stderr.write(f"[classifier] config not found: {CONFIG_PATH}\n")
        return {"concrete_triggers": {}, "abstract_triggers": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def classify(title: str, body: str = "") -> dict:
    """
    Classify an article as concrete or abstract.

    Args:
        title: Article title (required)
        body: Article body text (optional, improves accuracy)

    Returns:
        {
            "type": "concrete" | "abstract",
            "subjects": [...found concrete names...],
            "triggers_found": [...matched trigger strings...],
            "confidence": float (0.0 - 1.0)
        }
    """
    config = _load_config()

    concrete_triggers = config.get("concrete_triggers", {})
    abstract_triggers = config.get("abstract_triggers", [])

    # タイトルと本文を分離して検索 — タイトルの主語が最優先
    title_subjects = []
    body_subjects = []
    concrete_found = []
    abstract_found = []

    def _match_trigger(trigger: str, text: str) -> bool:
        """トリガーがテキストに安全にマッチするか判定"""
        if trigger.isascii():
            if len(trigger) <= 3:
                # 短いASCII: 単語境界必須 (V→IVE誤マッチ防止)
                pat = re.compile(r'(?<![A-Za-z])' + re.escape(trigger) + r'(?![A-Za-z])', re.IGNORECASE)
            else:
                pat = re.compile(re.escape(trigger), re.IGNORECASE)
            return bool(pat.search(text))
        else:
            if len(trigger) <= 2:
                # 短い日本語: カタカナ連続内の部分一致を防止 (ジン→ユンジン防止)
                pat = re.compile(r'(?<![ァ-ヴー])' + re.escape(trigger) + r'(?![ァ-ヴー])')
                return bool(pat.search(text))
            return trigger in text

    # Step 1: タイトルだけでトリガー検索
    for category, triggers in concrete_triggers.items():
        for trigger in triggers:
            if _match_trigger(trigger, title):
                concrete_found.append(trigger)
                if category in ("artists", "members"):
                    title_subjects.append(trigger)

    # Step 2: 本文でトリガー検索（タイトルで見つからなかったもののみ）
    if body:
        body_text = body[:500]
        for category, triggers in concrete_triggers.items():
            for trigger in triggers:
                if trigger in concrete_found:
                    continue  # タイトルで既に検出済み
                if _match_trigger(trigger, body_text):
                    concrete_found.append(trigger)
                    if category in ("artists", "members"):
                        body_subjects.append(trigger)

    # subjects: タイトルのアーティストのみ。本文の言及はサムネ選択に使わない。
    # 理由: 本文で「BTSやBLACKPINKも〜」と書かれた汎用記事でBTSのサムネが使われる問題を防止。
    subjects = list(dict.fromkeys(title_subjects))

    # Scan for abstract triggers
    text = f"{title} {body}".strip()
    for trigger in abstract_triggers:
        if trigger in text:
            abstract_found.append(trigger)

    # Deduplicate
    subjects = list(dict.fromkeys(subjects))
    concrete_found = list(dict.fromkeys(concrete_found))
    abstract_found = list(dict.fromkeys(abstract_found))

    # Decision logic
    if concrete_found:
        # Concrete wins if any concrete trigger found
        article_type = "concrete"
        # Confidence based on number and type of matches
        base_conf = 0.7
        if len(concrete_found) >= 3:
            base_conf = 0.95
        elif len(concrete_found) >= 2:
            base_conf = 0.85
        elif subjects:
            base_conf = 0.80
        # Title match is stronger than body-only match
        title_matches = sum(1 for t in concrete_found if t.lower() in title.lower() or t in title)
        if title_matches > 0:
            base_conf = min(1.0, base_conf + 0.1)
        confidence = base_conf
        triggers_found = concrete_found
    elif abstract_found:
        article_type = "abstract"
        base_conf = 0.6
        if len(abstract_found) >= 3:
            base_conf = 0.85
        elif len(abstract_found) >= 2:
            base_conf = 0.75
        confidence = base_conf
        triggers_found = abstract_found
    else:
        # Default to concrete (safer for K-POP site)
        article_type = "concrete"
        confidence = 0.4
        triggers_found = []

    # subjects=[] かつ concrete記事 → タイトルから未登録アーティスト名を自動検出
    if not subjects and article_type == "concrete":
        detected = _detect_unknown_artist(title)
        if detected:
            subjects = [detected]
            sys.stderr.write(
                f"[classifier] 未登録アーティスト自動検出: '{detected}' → subjects に追加\n"
            )
            _auto_register_artist(detected)

    return {
        "type": article_type,
        "subjects": subjects,
        "triggers_found": triggers_found,
        "confidence": confidence,
    }


def _detect_unknown_artist(title: str) -> str:
    """タイトルから未登録のアーティスト名候補を自動検出。

    K-POPアーティスト名の典型パターン:
    - 大文字英語 2文字以上 (BTS, ILLIT, KATSEYE)
    - カタカナ 3文字以上の固有名詞風 (カリナ、ヒョンジン)
    - タイトル先頭 or 「の」「が」「は」の前にある名前

    検出できない場合は空文字を返す。
    """
    # 除外語: アーティスト名ではない一般的な語
    _EXCLUDE = {
        'THE', 'NEW', 'BEST', 'TOP', 'HOT', 'LIVE', 'MV', 'PV', 'CM', 'DJ',
        'SM', 'JYP', 'YG', 'HYBE', 'K-POP', 'KPOP', 'SNS', 'MBC', 'KBS',
        'SBS', 'JTBC', 'TVN', 'MNET', 'TV', 'DVD', 'CD', 'LP', 'EP',
        'OK', 'NG', 'VS', 'NO', 'GO', 'UP', 'ON', 'IN', 'AT', 'TO',
        'LOVE', 'STORM', 'FORMAT', 'NORMAL', 'SPECIAL', 'GLOBAL', 'WORLD',
        'DREAM', 'STAR', 'MUSIC', 'DANCE', 'STYLE', 'SUPER', 'POWER',
        'SHOW', 'STAGE', 'ROYAL', 'FINAL', 'FIRST', 'LAST', 'NEXT',
        'BREAKING', 'NEWS', 'JAPAN', 'KOREA', 'TOKYO', 'SEOUL',
        'CONCERT', 'FESTIVAL', 'AWARDS', 'ALBUM', 'SINGLE', 'TOUR',
    }

    # パターン1: タイトル先頭の大文字英語 (句読点・括弧の前まで)
    # 例: "KATSEYE「Pinky Up」..." → KATSEYE
    m = re.match(r'^([A-Z][A-Za-z0-9\-\.\']+(?:\s[A-Z][A-Za-z0-9\-\.\']+)?)', title)
    if m:
        candidate = m.group(1).strip()
        # 各単語が除外語でないか確認 + 2文字以下の英単語は除外 (BE, DO等の誤検出防止)
        words = candidate.upper().split()
        if all(w not in _EXCLUDE and len(w) >= 3 for w in words) and len(candidate) >= 3:
            return candidate

    # パターン2: 「【速報】」等の後の大文字英語
    m = re.search(r'【[^】]*】\s*([A-Z][A-Za-z0-9\-\.\']+(?:\s[A-Z][A-Za-z0-9\-\.\']+)?)', title)
    if m:
        candidate = m.group(1).strip()
        words = candidate.upper().split()
        if all(w not in _EXCLUDE and len(w) >= 3 for w in words) and len(candidate) >= 3:
            return candidate

    # パターン3: タイトル先頭のカタカナ固有名詞 (3文字以上)
    _KATAKANA_EXCLUDE = {
        'ソウル', 'トレンド', 'ランキング', 'コンサート', 'ライブ', 'ファッション',
        'メイク', 'スキンケア', 'ビューティー', 'チャート', 'バラエティ',
        'スタジアム', 'ドーム', 'アリーナ', 'フェス', 'イベント',
        'コーチェラ', 'サバイバル', 'オーディション', 'レビュー',
    }
    m = re.match(r'^([ァ-ヴー]{3,})', title)
    if m and m.group(1) not in _KATAKANA_EXCLUDE:
        return m.group(1)

    # パターン4: 「韓国の〜」「K-POPの〜」の後のカタカナ/英語名 (3文字以上)
    m = re.search(r'(?:韓国の|K-POPの|K-POP\s)(?:人気\s*)?(?:ラッパー|歌手|アイドル|グループ|アーティスト)?\s*([A-Za-z\'][A-Za-z0-9\-\'\.]{2,})', title)
    if m:
        candidate = m.group(1)
        if candidate.upper() not in _EXCLUDE and len(candidate) >= 3:
            return candidate

    return ""


def _auto_register_artist(name: str):
    """検出したアーティスト名をconcrete_vs_abstract.jsonに自動追加。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        artists = config.get("concrete_triggers", {}).get("artists", [])
        if name in artists:
            return  # 既に登録済み

        artists.append(name)
        config["concrete_triggers"]["artists"] = artists

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        sys.stderr.write(f"[classifier] '{name}' を concrete_vs_abstract.json に自動登録\n")
    except Exception as e:
        sys.stderr.write(f"[classifier] 自動登録失敗 '{name}': {e}\n")


def _load_theme_config() -> dict:
    """Load article_themes.json."""
    if not THEME_CONFIG_PATH.exists():
        sys.stderr.write(f"[classifier] theme config not found: {THEME_CONFIG_PATH}\n")
        return {"themes": {}, "default_theme": {}}
    try:
        with open(THEME_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"[classifier] theme config load error: {e}\n")
        return {"themes": {}, "default_theme": {}}


def classify_theme(title: str, body: str = "") -> dict:
    """
    記事のテーマを分類する（サムネイル画像ソース選択用）。

    Returns:
        {
            "theme": str,          # comeback/concert/chart/variety/award/fashion/personal/debut/general
            "theme_config": dict,  # youtube_order, unsplash_query, dalle_prompt
            "triggers_matched": list[str],
            "confidence": float,
        }
    """
    config = _load_theme_config()
    themes = config.get("themes", {})
    default = config.get("default_theme", {})
    text = f"{title} {body[:500]}".strip()

    best_theme = "general"
    best_count = 0
    best_triggers = []
    title_bonus = False

    for theme_name, theme_def in themes.items():
        triggers = theme_def.get("triggers", [])
        matched = []
        has_title_match = False
        for trigger in triggers:
            if trigger.isascii():
                pattern = re.compile(re.escape(trigger), re.IGNORECASE)
                if pattern.search(text):
                    matched.append(trigger)
                    if pattern.search(title):
                        has_title_match = True
            else:
                if trigger in text:
                    matched.append(trigger)
                    if trigger in title:
                        has_title_match = True

        # タイトルでのマッチは2倍の重みづけ
        score = len(matched) + (2 if has_title_match else 0)
        if score > best_count:
            best_count = score
            best_theme = theme_name
            best_triggers = matched
            title_bonus = has_title_match

    # confidence 計算
    if best_count == 0:
        confidence = 0.3
    elif best_count >= 5:
        confidence = 0.95
    elif best_count >= 3:
        confidence = 0.85
    elif title_bonus:
        confidence = 0.80
    else:
        confidence = 0.65

    # テーマ設定を返す
    theme_config = themes.get(best_theme, default)
    return {
        "theme": best_theme,
        "theme_config": {
            "youtube_order": theme_config.get("youtube_order", default.get("youtube_order", "viewCount")),
            "unsplash_query": theme_config.get("unsplash_query", default.get("unsplash_query", "")),
            "dalle_prompt": theme_config.get("dalle_prompt", default.get("dalle_prompt", "")),
        },
        "triggers_matched": best_triggers,
        "confidence": confidence,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Article Topic Classifier")
    parser.add_argument("--title", required=True, help="Article title")
    parser.add_argument("--body", default="", help="Article body (optional)")
    args = parser.parse_args()

    result = classify(args.title, args.body)
    theme_result = classify_theme(args.title, args.body)
    result["theme"] = theme_result
    print(json.dumps(result, ensure_ascii=False, indent=2))
