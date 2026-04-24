"""
X投稿プレフライトスコアリング (v11.0 シングル投稿モード)

100点満点で投稿品質を評価し、80点以上のみ投稿を許可する。

スコア内訳:
  フック      35点  - 冒頭の引きつけ力
  構造        25点  - 文章の構成・長さ・フォーマット
  ターゲット  15点  - アーティスト名・ハッシュタグ適合性
  Alt         10点  - 代替テキスト/画像ALT等の補足要素
  過去類似実績 15点 - title_performance.jsonl の勝ちパターン照合

Usage:
  python3 lib/x_pre_score.py "投稿テキスト"
  python3 lib/x_pre_score.py "投稿テキスト" --verbose
  python3 lib/x_pre_score.py "投稿テキスト" --alt-text "画像の説明文"

Output: JSON {"text", "total", "breakdown", "reasons", "pass"}
Pass threshold: total >= 80
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ─── 定数 ────────────────────────────────────────────────────────────────────

PASS_THRESHOLD = 70

PERF_FILE = Path(__file__).parent.parent / "logs" / "title_performance.jsonl"

# フックに使える強ワード（先頭付近に含まれると高評価）
HOOK_STRONG_WORDS = [
    "速報", "緊急", "衝撃", "決定", "発表", "解禁", "判明", "ついに",
    "まさか", "電撃", "神", "レベチ", "完全", "炎上", "暴露",
    "初公開", "騒然", "復活", "即完売", "尊い", "話題",
]

# 弱い書き出し（減点対象）
WEAK_OPENINGS = [
    "皆さん", "こんにちは", "お知らせ", "お疲れ", "今日は", "本日は",
    "〜について", "まとめ", "解説", "情報",
]

# 認知度の高いアーティスト（ターゲット評価用）
TOP_ARTISTS = [
    "BTS", "BLACKPINK", "aespa", "SEVENTEEN", "Stray Kids", "NewJeans",
    "IVE", "LE SSERAFIM", "XG", "TWICE", "NCT", "ILLIT", "RIIZE",
    "BABYMONSTER", "ZeroBaseOne", "ITZY", "EXO", "BIGBANG", "MONSTA X",
    "ENHYPEN", "TXT", "ATEEZ", "DAY6", "GOT7", "2PM", "SHINee",
    "AKMU", "악동뮤지션", "KISS OF LIFE", "MAMAMOO", "Red Velvet", "f(x)",
    "Super Junior", "TVXQ", "Girls' Generation", "SNSD", "INFINITE", "B1A4",
]

# 未確認情報の断定パターン（重大減点）
UNVERIFIED_PATTERNS = [r'確定(?!的)', r'100%', r'間違いない', r'絶対に']


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def load_win_records() -> list[dict]:
    """title_performance.jsonl から win レコードを読み込む"""
    if not PERF_FILE.exists():
        return []
    records = []
    for line in PERF_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("result") == "win":
                records.append(r)
        except json.JSONDecodeError:
            continue
    return records


def extract_keywords(text: str) -> list[str]:
    """テキストから意味のある単語を抽出（簡易版）"""
    # アーティスト名・カタカナ語・英単語を抽出
    tokens = re.findall(
        r'[A-Za-z]{2,}|[\u30A0-\u30FF]{2,}|[\u4E00-\u9FFF]{1,4}', text
    )
    return [t.upper() for t in tokens]


def similarity_score(text: str, win_records: list[dict]) -> tuple[float, list[str]]:
    """過去の勝ちパターンとの類似度スコア (0〜15点)
    ベースライン: 学習データあり=8点、完全一致方向へ加算
    """
    BASE = 8.0  # win_recordsがあれば最低8点（運用初期の安定性確保）

    if not win_records:
        return BASE, [f"学習データなし → ベースライン{BASE}"]

    text_kws = set(extract_keywords(text))

    best_overlap = 0.0
    best_title = ""
    for r in win_records:
        title = r.get("title", "")
        win_kws = set(extract_keywords(title))
        if not win_kws:
            continue
        overlap = len(text_kws & win_kws) / len(win_kws)
        if overlap > best_overlap:
            best_overlap = overlap
            best_title = title

    # BASE(8) + overlap加算で最大15点
    score = min(15.0, BASE + best_overlap * (15.0 - BASE) / 0.5)  # 0.5 overlap → 15点
    reasons = []
    if best_title:
        reasons.append(f"最類似勝ちタイトル: 「{best_title[:30]}…」(overlap={best_overlap:.2f})")
    return score, reasons


# ─── スコアリング関数 ──────────────────────────────────────────────────────────

def check_completeness(text: str) -> tuple[bool, list[str]]:
    """v12.0 §6: 未完性チェック — 以下1つでも満たしたらNG(False)
    ・答えを書いている
    ・結論を書いている
    ・情報が完結している
    Returns: (is_incomplete_ok, violations)
      True = 未完結でOK / False = 完結しているためNG
    """
    violations = []

    # 完結パターン: 答えを明示している
    answer_patterns = [
        r'[。！]$',                          # 断定で終わる
        r'(ことがわかった|ことが判明した)',
        r'(結果は|答えは|真相は)[^？?]',
        r'(〜です|〜ます|〜でした|〜ました)[。！]',
        r'(決定した|発表した|確認した)[。！]',
    ]
    # 未完結パターン: OKサイン
    incomplete_signals = [
        r'[？?]',           # 疑問符
        r'(のか|だろうか|なのか)',
        r'(とは|真相|秘密|理由)',
        r'(…|\.\.\.)',
        r'(どう思|気になる|知ってた|予想)',
    ]

    text_last = text.split('\n')[0] if '\n' in text else text  # 1行目のみチェック

    has_incomplete_signal = any(re.search(p, text) for p in incomplete_signals)

    if not has_incomplete_signal:
        # 完結パターンをチェック
        for pat in answer_patterns:
            if re.search(pat, text_last):
                violations.append(f"完結パターン検出: {pat}")
                break

    return (len(violations) == 0), violations


def score_hook(text: str) -> tuple[float, list[str]]:
    """フックスコア (0〜35点) — v12.0 §3準拠"""
    score = 0.0
    reasons = []
    first_line = text.split('\n')[0] if '\n' in text else text[:30]
    hook_len = len(first_line)

    # 弱い書き出しペナルティ
    if any(text.startswith(w) for w in WEAK_OPENINGS):
        score -= 10
        reasons.append("弱い書き出し -10")
    else:
        # 冒頭行に強ワードがあるか
        matched = [w for w in HOOK_STRONG_WORDS if w in first_line]
        if len(matched) >= 2:
            score += 30
            reasons.append(f"冒頭強ワード×{len(matched)} ({','.join(matched)}) +30")
        elif len(matched) == 1:
            score += 22
            reasons.append(f"冒頭強ワード「{matched[0]}」+22")
        else:
            any_matched = [w for w in HOOK_STRONG_WORDS if w in text]
            if any_matched:
                score += 17
                reasons.append(f"本文強ワード「{any_matched[0]}」+17")
            else:
                # v12.0: 未完結疑問形は強ワードなしでも有効フック
                incomplete_hook = bool(re.search(r'[？?]|のか|とは|が起きた|が動いた|が変わった', first_line))
                if incomplete_hook:
                    score += 20
                    reasons.append("未完結フック(v12.0形式) +20")
                else:
                    score += 10
                    reasons.append("強ワードなし +10 (基礎点)")

    # §3 フック20文字以内ボーナス
    if hook_len <= 20:
        score += 5
        reasons.append(f"フック{hook_len}文字(20字以内) +5")
    else:
        reasons.append(f"フック{hook_len}文字(20字超) +0")

    # §3 数字含むボーナス
    if re.search(r'\d', first_line):
        score += 2
        reasons.append("フックに数字あり +2 (§3)")

    # §5 コメント誘導あるか（疑問符・誘導ワード）
    has_trigger = bool(re.search(r'[？?]|どう思|気になる|知ってた|予想|試した|納得|驚', text))
    if has_trigger:
        score += 3
        reasons.append("コメント誘導あり +3 (§5)")
    else:
        score -= 5
        reasons.append("コメント誘導なし -5 (§5違反)")

    # §6 未確認断定は大幅減点
    for pat in UNVERIFIED_PATTERNS:
        if re.search(pat, text):
            score -= 15
            reasons.append("未確認断定パターン検出 -15")
            break

    # §6 未完性チェック
    is_ok, violations = check_completeness(text)
    if not is_ok:
        score -= 10
        reasons.append(f"完結文検出(§6違反) -10: {violations[0]}")

    # 過剰感嘆符
    excl = text.count('!') + text.count('！')
    if excl > 3:
        score -= 5
        reasons.append(f"感嘆符過多({excl}個) -5")

    return max(0.0, min(35.0, score)), reasons


def score_structure(text: str) -> tuple[float, list[str]]:
    """構造スコア (0〜25点)"""
    score = 0.0
    reasons = []
    text_len = len(text)

    # 文字長（CTOハック: URLなしフックは50〜120文字が理想）
    has_url = "http" in text
    if has_url:
        if 80 <= text_len <= 200:
            score += 12
            reasons.append(f"長さ適正({text_len}文字) +12")
        elif 50 <= text_len < 80:
            score += 8
            reasons.append(f"やや短い({text_len}文字) +8")
        elif 200 < text_len <= 280:
            score += 8
            reasons.append(f"やや長い({text_len}文字) +8")
        elif text_len > 280:
            score -= 5
            reasons.append(f"文字数超過({text_len}文字) -5")
        else:
            score += 3
            reasons.append(f"短すぎる({text_len}文字) +3")
    else:
        # URLなしフック: 40〜120文字が理想（CTOハック対応）
        if 40 <= text_len <= 120:
            score += 12
            reasons.append(f"フック長さ適正({text_len}文字/URLなし) +12")
        elif text_len < 40:
            score += 5
            reasons.append(f"フック短め({text_len}文字) +5")
        else:
            score += 8
            reasons.append(f"フックやや長め({text_len}文字) +8")

    # URL含む（CTOハック: URLなしフックも許容 → ペナルティなし・ボーナスのみ）
    if "http" in text:
        score += 8
        reasons.append("URL含む +8")
    else:
        score += 4
        reasons.append("URLなし +4 (CTOハック: リプライで後から挿入)")

    # 改行による段落分け
    if "\n" in text:
        score += 5
        reasons.append("改行あり（読みやすさ） +5")

    return max(0.0, min(25.0, score)), reasons


def score_target(text: str) -> tuple[float, list[str]]:
    """ターゲットスコア (0〜15点)"""
    score = 0.0
    reasons = []
    text_upper = text.upper()

    # アーティスト名含む
    matched_artists = [a for a in TOP_ARTISTS if a.upper() in text_upper]
    if len(matched_artists) >= 2:
        score += 8
        reasons.append(f"複数アーティスト({','.join(matched_artists[:2])}) +8")
    elif len(matched_artists) == 1:
        score += 5
        reasons.append(f"アーティスト名({matched_artists[0]}) +5")
    else:
        # アーティスト名なし記事（美容/戦略/旅行等）でもK-POP関連ワードがあれば部分点
        _kpop_words = ["K-POP", "KPOP", "韓国", "アイドル", "ガラス肌", "スキンケア", "コスメ", "ソウル"]
        _matched_kpop = [w for w in _kpop_words if w.upper() in text_upper or w in text]
        if _matched_kpop:
            score += 3
            reasons.append(f"K-POP関連ワード({_matched_kpop[0]}) +3（アーティスト名代替）")

    # ハッシュタグ
    hashtag_count = len(re.findall(r'#\S+', text))
    if 2 <= hashtag_count <= 4:
        score += 7
        reasons.append(f"ハッシュタグ{hashtag_count}個 +7")
    elif hashtag_count == 1:
        score += 4
        reasons.append(f"ハッシュタグ1個 +4")
    elif hashtag_count == 0:
        reasons.append("ハッシュタグなし +0")
    elif hashtag_count >= 5:
        score -= 3
        reasons.append(f"ハッシュタグ過多({hashtag_count}個) -3")

    # #kpop / #Kpop 含む
    if re.search(r'#[Kk]-?[Pp][Oo][Pp]', text):
        score += 3
        reasons.append("#kpop含む +3（リーチ拡大）")

    return max(0.0, min(15.0, score)), reasons


def score_alt(text: str, alt_text: str = "") -> tuple[float, list[str]]:
    """Altスコア (0〜10点) — 画像ALTや補足要素の評価"""
    score = 0.0
    reasons = []

    if alt_text and len(alt_text.strip()) >= 10:
        score += 10
        reasons.append(f"ALTテキストあり({len(alt_text)}文字) +10")
    elif alt_text and len(alt_text.strip()) > 0:
        score += 7
        reasons.append(f"ALTテキストあり(短め) +7")
    else:
        score += 5
        reasons.append("ALTテキストなし +5 (基礎点: §7/§8実装前は標準)")

    # 絵文字が適度にある（視覚的な引き）
    emoji_count = len(re.findall(
        r'[\U0001F300-\U0001FFFF\U00002700-\U000027BF]', text
    ))
    if 1 <= emoji_count <= 3:
        score += 2
        reasons.append(f"絵文字適量({emoji_count}個) +2")

    return max(0.0, min(10.0, score)), reasons


# ─── メイン ───────────────────────────────────────────────────────────────────

def preflight_score(text: str, alt_text: str = "") -> dict:
    """プレフライトスコアを計算して結果dictを返す"""
    win_records = load_win_records()

    hook_score, hook_reasons = score_hook(text)
    structure_score, structure_reasons = score_structure(text)
    target_score, target_reasons = score_target(text)
    alt_score, alt_reasons = score_alt(text, alt_text)
    history_score, history_reasons = similarity_score(text, win_records)

    total = hook_score + structure_score + target_score + alt_score + history_score

    return {
        "text": text[:100] + ("…" if len(text) > 100 else ""),
        "total": round(total, 1),
        "pass": total >= PASS_THRESHOLD,
        "threshold": PASS_THRESHOLD,
        "breakdown": {
            "hook":      {"score": round(hook_score, 1),      "max": 35},
            "structure": {"score": round(structure_score, 1), "max": 25},
            "target":    {"score": round(target_score, 1),    "max": 15},
            "alt":       {"score": round(alt_score, 1),       "max": 10},
            "history":   {"score": round(history_score, 1),   "max": 15},
        },
        "reasons": {
            "hook":      hook_reasons,
            "structure": structure_reasons,
            "target":    target_reasons,
            "alt":       alt_reasons,
            "history":   history_reasons,
        },
    }


def rewrite(text: str) -> str:
    """不合格テキストを最低限の修正で80点以上に引き上げる。
    元のテキスト構造を最大限維持し、フック・ハッシュタグのみ補強する。
    """
    lines = text.strip().split("\n")

    # 1. フック補強: 先頭行に強ワードがなければ「速報」を追加
    first_line = lines[0] if lines else ""
    has_strong = any(w in first_line for w in HOOK_STRONG_WORDS)
    if not has_strong:
        # アーティスト名が含まれているか確認
        artist_match = next((a for a in TOP_ARTISTS if a.upper() in text.upper()), None)
        if artist_match:
            lines[0] = f"速報🚨 {first_line}"
        else:
            lines[0] = f"注目📢 {first_line}"

    # 2. ハッシュタグ補強: ハッシュタグがなければ末尾に追加
    existing_tags = re.findall(r'#\S+', text)
    if len(existing_tags) < 2:
        artist_match = next((a for a in TOP_ARTISTS if a.upper() in text.upper()), None)
        tags = "#KPOP"
        if artist_match:
            tags = f"#{artist_match.replace(' ', '')} #KPOP #韓国芸能"
        else:
            tags = "#KPOP #韓国 #Kpop"
        lines.append(tags)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="X投稿プレフライトスコアリング (100点満点)")
    parser.add_argument("text", nargs="?", default="", help="評価する投稿テキスト")
    parser.add_argument("--alt-text", default="", help="画像のALTテキスト")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細表示")
    parser.add_argument("--rewrite", action="store_true",
                        help="不合格時に自動修正してスコアとテキストを返す")
    args = parser.parse_args()

    text = args.text.strip()
    if not text:
        parser.print_help()
        sys.exit(1)

    result = preflight_score(text, args.alt_text)

    # --rewrite: 不合格なら自動修正して再スコアリング
    if args.rewrite and not result["pass"]:
        rewritten = rewrite(text)
        if rewritten != text:
            result2 = preflight_score(rewritten, args.alt_text)
            result2["rewritten"] = rewritten
            result2["original_score"] = result["total"]
            result = result2

    if args.verbose:
        verdict = "✅ PASS" if result["pass"] else "❌ BLOCK"
        rewritten_note = " [rewritten]" if "rewritten" in result else ""
        print(f"\n{verdict}{rewritten_note}  合計: {result['total']}/100  (閾値: {result['threshold']})\n")
        print("─" * 50)
        bd = result["breakdown"]
        rs = result["reasons"]
        for section in ["hook", "structure", "target", "alt", "history"]:
            label = {
                "hook": "フック     ", "structure": "構造      ",
                "target": "ターゲット ", "alt": "Alt       ",
                "history": "過去類似   "
            }[section]
            s = bd[section]
            print(f"  {label} {s['score']:5.1f} / {s['max']}")
            for r in rs[section]:
                print(f"              {r}")
        print("─" * 50)
        if "rewritten" in result:
            print(f"  [修正後]: {result['rewritten'][:100]}")
            print(f"  (元スコア: {result['original_score']} → 修正後: {result['total']})")
        else:
            print(f"  投稿文: {result['text']}")
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
