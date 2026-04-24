"""
投稿前バリデータ: WordPressに投稿する前の最終チェック

検出する致命的問題:
1. Claude CLI JSONメタデータ混入（"type":"result", "modelUsage" 等）
2. wpautop破壊された script タグ（<script><br />）
3. URL-encoded日本語slug
4. 短すぎる/不正なslug
5. 空タイトル/空本文

Usage:
  echo '{"title":"...","content":"...","slug":"..."}' | python3 lib/validate_post.py
  → exit 0 if OK, exit 1 with errors on stderr
"""
import json
import re
import sys
from collections import Counter


def validate(post):
    errors = []
    warnings = []

    title = post.get("title", "")
    content = post.get("content", "")
    slug = post.get("slug", "")

    # === タイトル検証 ===
    if not title or len(title.strip()) < 5:
        errors.append("title: 空または短すぎる (5文字未満)")
    if len(title) > 200:
        warnings.append(f"title: 長すぎる ({len(title)}文字)")

    # === 本文検証 ===
    if not content or len(content.strip()) < 100:
        errors.append("content: 空または短すぎる (100文字未満)")

    # [致命的] Claude CLI JSON混入
    if re.search(r'\{"type"\s*:\s*"result"', content):
        errors.append("content: Claude CLI JSON結果が混入 ('type':'result')")
    if re.search(r'"modelUsage"\s*:\s*\{', content):
        errors.append("content: Claude modelUsage メタデータ混入")
    if re.search(r'"terminal_reason"\s*:', content):
        errors.append("content: Claude terminal_reason メタデータ混入")
    if re.search(r'"session_id"\s*:\s*"[a-f0-9-]{36}"', content):
        errors.append("content: Claude session_id メタデータ混入")

    # [致命的] wpautop破壊された script タグ
    if re.search(r'<script[^>]*>[^<]*<br\s*/?>', content):
        errors.append("content: <script><br /> 破壊検出（wpautop被害、AdSense動作不能）")
    if re.search(r'\.push\(\{\}\);<br\s*/?>', content):
        errors.append("content: AdSense .push({}) 後の <br /> 検出")

    # [警告] AdSense scriptが本文に保存されている (本来はプラグインで動的挿入されるべき)
    if "googlesyndication.com" in content or "adsbygoogle" in content:
        warnings.append("content: AdSense scriptが本文に保存されている (rendered baked-in疑い)")

    # === 重複文検出 (同一文3回以上 = HARD_FAIL) ===
    plain_text = re.sub(r'<[^>]+>', '', content)
    sentences = [s.strip() for s in re.split(r'[。．.！!？?\n]', plain_text) if len(s.strip()) > 20]
    sentence_counts = Counter(sentences)
    for sentence, count in sentence_counts.items():
        if count >= 3:
            errors.append(f"content: 重複文検出 (HARD_FAIL) — 同一文が{count}回出現: 「{sentence[:50]}...」")

    # === Slug検証 ===
    if not slug:
        warnings.append("slug: 未指定 (WordPressが自動生成→日本語URL化リスク)")
    else:
        # URL-encoded日本語 (%XX% パターン)
        if re.search(r'%[0-9a-fA-F]{2}%[0-9a-fA-F]{2}', slug):
            errors.append(f"slug: URL-encoded日本語が含まれる ({slug[:60]})")
        # 非ASCII
        if not all(ord(c) < 128 for c in slug):
            errors.append(f"slug: 非ASCII文字が含まれる ({slug[:60]})")
        # 短すぎる (5文字未満)
        if len(slug) < 5:
            warnings.append(f"slug: 短すぎる ({slug})")
        # 全部数字
        if slug.isdigit():
            warnings.append(f"slug: 全部数字 ({slug})")
        # __trashed サフィックス（WordPressゴミ箱記事の残骸 → SEO致命的）
        if "__trashed" in slug:
            errors.append(f"slug: '__trashed'サフィックスが含まれる → 同名スラッグの削除済み記事が存在する可能性。スラッグを変更すること ({slug[:60]})")
        # 数字-数字-... のみのパターン（意味のないスラッグ）
        if re.match(r'^[\d\-]+$', slug):
            warnings.append(f"slug: 数字とハイフンのみで意味がない ({slug})")

    return errors, warnings


def main():
    try:
        if sys.argv[1:] and sys.argv[1] == "--file":
            with open(sys.argv[2]) as f:
                post = json.load(f)
        else:
            post = json.load(sys.stdin)
    except Exception as e:
        sys.stderr.write(f"[validate_post] JSON parse error: {e}\n")
        sys.exit(2)

    errors, warnings = validate(post)

    for w in warnings:
        sys.stderr.write(f"[validate_post] WARN: {w}\n")
    for e in errors:
        sys.stderr.write(f"[validate_post] ERROR: {e}\n")

    if errors:
        sys.stderr.write(f"[validate_post] ❌ FAIL ({len(errors)} errors, {len(warnings)} warnings)\n")
        sys.exit(1)

    sys.stderr.write(f"[validate_post] ✅ OK ({len(warnings)} warnings)\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
