"""
SEO向きslug生成

日本語タイトルから ASCII slug を生成する。優先順位:
  1) ASCII単語（アー名・英字・数字）を抽出して結合
  2) 日付ベースフォールバック

Usage:
  python3 lib/slug.py "【戦略】BTS Arirang 2週連続Billboard1位"
  → bts-arirang-billboard-1-2026-04-08
"""
import re
import sys
from datetime import datetime


def make_slug(title, max_len=60, date_suffix=True):
    """日本語タイトルから ASCII slug を生成"""
    if not title:
        return ""

    # 1) 編集マーカー除去
    t = re.sub(r"【[^】]*】", "", title)
    t = re.sub(r"「[^」]*」", " ", t)
    t = re.sub(r"『[^』]*』", " ", t)
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"（[^）]*）", " ", t)

    # 2) ASCII単語を抽出（英字・数字、ハイフン許容）
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*|\d+", t)

    # 3) 小文字化＋短すぎる単語を除外（"a", "the" 等）
    tokens = [tok.lower() for tok in tokens if len(tok) >= 2 or tok.isdigit()]

    # 4) ストップワード除去
    stopwords = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or"}
    tokens = [tok for tok in tokens if tok not in stopwords]

    # 5) 重複除去（順序保持）
    seen = set()
    unique = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            unique.append(tok)

    if not unique:
        # 完全に日本語のみの場合は日付ベース
        return f"kpop-news-{datetime.now().strftime('%Y%m%d-%H%M')}"

    # 6) 結合
    slug = "-".join(unique)

    # 7) 日付サフィックス（一意性確保）
    if date_suffix:
        date_str = datetime.now().strftime("%Y%m%d")
        # 既に日付を含んでいなければ追加
        if not re.search(r"20\d{6}", slug):
            slug = f"{slug}-{date_str}"

    # 8) 長さ制限
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
        # 末尾が数字途中で切れてたら戻す
        slug = re.sub(r"-\d+$", "", slug) if len(slug) >= max_len - 4 else slug
        slug = slug.rstrip("-")

    # 9) 連続ハイフン整理
    slug = re.sub(r"-+", "-", slug).strip("-")

    return slug or f"kpop-news-{datetime.now().strftime('%Y%m%d-%H%M')}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 slug.py <title>")
        sys.exit(1)
    print(make_slug(sys.argv[1]))
