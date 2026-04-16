import re
import sys
import json

title = sys.argv[1].strip()

score = 0
reasons = []

# 1. 主要キーワード（アーティスト名・番組名・サービス名）
main_keywords = [
    "bts", "blackpink", "bigbang", "aespa", "babymonster", "illit", "ive",
    "le sserafim", "seventeen", "twice", "stray kids", "newjeans", "xg",
    "nct", "riize", "monsta x", "zerobaseone", "exo", "itzy", "boa",
    "スウパ", "swf", "プデュ", "produce", "i-land", "ボイプラ", "boys planet",
    "abema", "mnet", "hulu", "tving", "wavve",
    # 2026-04-16 Round8: GSC実績で impr 上位の勝ちトピックを追加
    "demon hunters", "デモンハンターズ", "shinee", "taemin", "テミン",
    "g-dragon", "gd", "t.o.p", "mamamoo", "enhypen", "txt",
    "katseye", "nmixx", "(g)i-dle", "jimin", "ジミン", "jungkook",
]
title_l = title.lower()

if any(k in title_l for k in main_keywords):
    score += 3
    reasons.append("主要キーワードあり +3")

# 2. 数字・日付
if re.search(r'[0-9０-９]+', title):
    score += 2
    reasons.append("数字あり +2")

# 3. 具体イベント名
event_keywords = [
    "coachella", "billboard", "ツアー", "ワールドツアー", "来日", "ライブ",
    "カムバック", "アルバム", "新曲", "mv", "ファンミ", "コンサート",
    "mama", "人気歌謡", "music bank", "m countdown", "festival", "フェス",
    "視聴方法", "見る方法", "無料", "見逃し", "比較", "料金", "配信", "放送"
]
if any(k.lower() in title_l for k in event_keywords):
    score += 2
    reasons.append("イベント名あり +2")

# 4. 感情ワード・強ワード（2026-04-16 Round8: 辞書拡充）
emotion_keywords = [
    "速報", "緊急", "衝撃", "ついに", "完全復活", "最新", "話題", "注目",
    "決定", "始動", "解禁", "発表", "判明",
    # 強化: 異常/驚愕/完全/暴露/爆発 系
    "異常", "驚愕", "まさか", "完全", "暴露", "激白", "爆発", "炎上",
    "神", "レベチ", "制覇", "首位", "1位", "伝説", "奇跡", "快挙",
]
if any(k in title for k in emotion_keywords):
    score += 2
    reasons.append("強ワードあり +2")

# 4b. 対比構造（2026-04-16 Round8 新規）
#     vs / → / から / 空白 / 復帰 / 崩壊 / 逆転 / なのに / でも / ただし / 一転 等
contrast_patterns = [
    "vs ", "VS ", "→", "⇒", "から", "でも", "なのに", "ただし",
    "なぜ", "なのか", "——", "―", "本当か",
    "空白", "復帰", "崩壊", "逆転", "一転", "激変", "急転", "転機",
    "再び", "リベンジ", "塗替", "更新", "超え", "制覇", "異次元",
    "年ぶり", "週連続", "日連続", "回連続", "連覇", "連続1位",
]
if any(p in title for p in contrast_patterns):
    score += 2
    reasons.append("対比構造あり +2")

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

# 最大スコア = 3+2+2+2+2+1 = 12（対比+2 追加により拡張）
# 2026-04-16 Round8: 二段階判定
#   score >= 8 (60% 想定で本来の 12 * 0.8 = 9.6 だが、12点システム下で 8 をfull合格とする)
#   score >= 6 → provisional (仮採用) : 要素不足でも明らかに前より良ければ通す
#   score <  6 → reject
TITLE_MAX = 12
pass_full = score >= 8
pass_provisional = score >= 6

result = {
    "title": title,
    "score": score,
    "score_pct": round(score / TITLE_MAX * 100, 1),
    "length": length,
    "reasons": reasons,
    "pass": pass_full,                    # 後方互換（既存コード）
    "pass_provisional": pass_provisional, # 仮採用フラグ
    "tier": "full" if pass_full else ("provisional" if pass_provisional else "reject"),
}

print(json.dumps(result, ensure_ascii=False))
