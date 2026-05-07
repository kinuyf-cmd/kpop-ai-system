#!/usr/bin/env python3
"""
post_write_sanitize.py — AI語尾排除チェッカー (Track C)

AI特有の語尾・表現パターンを検出し、人間らしい文章になっているかを検証する。

Usage:
  # パイプラインから呼び出し
  from pipeline.post_write_sanitize import check_ai_phrases
  result = check_ai_phrases(article_text)

  # CLI: 記事IDを指定（data/drafts/ or WP API）
  python3 pipeline/post_write_sanitize.py --article-id 3866 3867

  # CLI: テキストを直接テスト
  python3 pipeline/post_write_sanitize.py --text "BTSのVが新曲を発表しましたよね"
"""
import re
import json
import os
import sys
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# ── 禁止フレーズ定義 ──
BANNED_PHRASES = [
    # AI語尾
    "ですよね",
    "でしょうか",
    "なのです",
    "でしょう",
    "と言えます",
    "ではないでしょうか",
    "のです",
    # AI常套句
    "皆さんもご存知の",
    "と言われています",
    "注目されています",
    # 過剰な副詞・修飾
    "きっと",
    "ぜひ",
    "まさに",
]

# 閾値
SOFT_RETRY_THRESHOLD = 5
HARD_FAIL_THRESHOLD = 10
EXCLAMATION_WARNING_THRESHOLD = 4


def check_ai_phrases(text: str) -> dict:
    """
    AI語尾・表現パターンを検出する。

    Args:
        text: 記事本文（HTMLタグ込み可）

    Returns:
        {
            "status": "PASS" | "SOFT_RETRY" | "HARD_FAIL",
            "detected": [{"phrase": str, "count": int}, ...],
            "counts": {"ですよね": 2, ...},
            "total_detected": int,
            "exclamation_count": int,
            "warnings": [str, ...]
        }
    """
    # HTMLタグ除去してプレーンテキスト化
    plain = re.sub(r'<[^>]+>', '', text)

    detected = []
    counts = {}
    total = 0

    for phrase in BANNED_PHRASES:
        count = plain.count(phrase)
        if count > 0:
            detected.append({"phrase": phrase, "count": count})
            counts[phrase] = count
            total += count

    # 感嘆符カウント（全角・半角両方）
    exclamation_count = plain.count("！") + plain.count("!")

    # ステータス判定
    if total >= HARD_FAIL_THRESHOLD:
        status = "HARD_FAIL"
    elif total >= SOFT_RETRY_THRESHOLD:
        status = "SOFT_RETRY"
    else:
        status = "PASS"

    # テンプレート残存・プレースホルダ検出
    template_patterns = [
        (r'XX[月日年時分]', 'XX月/XX日テンプレ残存'),
        (r'〇〇[月日年]', '〇〇テンプレ残存'),
        (r'△△', '△△テンプレ残存'),
        (r'(?<!\w)TBD(?!\w)', 'TBD残存'),
        (r'(?<!\w)TODO(?!\w)', 'TODO残存'),
        (r'(?<!\w)FIXME(?!\w)', 'FIXME残存'),
        (r'\[要確認\]|\[未定\]|\[確認中\]', '要確認マーカー残存'),
        (r'【[^】]*未定[^】]*】|【[^】]*要確認[^】]*】', '未定/要確認マーカー残存'),
        (r'```(?:html|python|json|css|javascript)', 'コードブロックマーカー混入'),
        (r'INSERT_.*?_HERE|PLACEHOLDER', '英語プレースホルダ残存'),
    ]
    template_hits = []
    for pat, label in template_patterns:
        matches = re.findall(pat, plain)
        if matches:
            template_hits.append({"pattern": label, "count": len(matches), "examples": matches[:3]})
            total += len(matches) * 2  # テンプレ残存は重めにカウント

    # テンプレ残存があればステータスを再判定
    if template_hits:
        if any(h['count'] >= 2 for h in template_hits):
            status = "HARD_FAIL"
        elif status == "PASS":
            status = "SOFT_RETRY"

    # 警告生成
    warnings = []
    for hit in template_hits:
        warnings.append(
            f"テンプレ残存検出: {hit['pattern']} x{hit['count']} ({', '.join(str(e) for e in hit['examples'][:2])})"
        )
    if exclamation_count >= EXCLAMATION_WARNING_THRESHOLD:
        warnings.append(
            f"感嘆符が多すぎます: {exclamation_count}個（推奨: {EXCLAMATION_WARNING_THRESHOLD - 1}個以下）"
        )
    if status == "SOFT_RETRY":
        warnings.append(
            f"AI語尾が{total}個検出されました（閾値: {SOFT_RETRY_THRESHOLD}）。リライトを推奨します。"
        )
    if status == "HARD_FAIL":
        warnings.append(
            f"AI語尾が{total}個検出されました（閾値: {HARD_FAIL_THRESHOLD}）。記事を差し戻してください。"
        )

    return {
        "status": status,
        "detected": detected,
        "counts": counts,
        "total_detected": total,
        "exclamation_count": exclamation_count,
        "warnings": warnings,
    }


def check_article_json(article: dict) -> dict:
    """
    記事JSON（"content"フィールド含む）をチェックする。

    Args:
        article: {"content": str, ...} 形式の記事データ

    Returns:
        check_ai_phrases() の結果
    """
    content = article.get("content", "")
    return check_ai_phrases(content)


def _load_draft(article_id: int) -> str | None:
    """data/drafts/ からドラフトを読み込む"""
    drafts_dir = BASE / "data" / "drafts"
    if not drafts_dir.exists():
        return None

    # JSON形式
    json_path = drafts_dir / f"{article_id}.json"
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("content", json.dumps(data, ensure_ascii=False))

    # HTML形式
    html_path = drafts_dir / f"{article_id}.html"
    if html_path.exists():
        with open(html_path, encoding="utf-8") as f:
            return f.read()

    # テキスト形式
    txt_path = drafts_dir / f"{article_id}.txt"
    if txt_path.exists():
        with open(txt_path, encoding="utf-8") as f:
            return f.read()

    return None


def _fetch_wp_post(article_id: int) -> str | None:
    """WP API から記事を取得"""
    try:
        import requests
    except ImportError:
        print("requests not installed, cannot fetch from WP API", file=sys.stderr)
        return None

    env = {}
    env_path = BASE / ".env"
    if not env_path.exists():
        print(".env not found, cannot fetch from WP API", file=sys.stderr)
        return None

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")

    wp_user = env.get("WP_USER")
    wp_pass = env.get("WP_PASS")
    if not wp_user or not wp_pass:
        print("WP_USER/WP_PASS not set in .env", file=sys.stderr)
        return None

    wp = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
    r = requests.get(
        f"{wp}/posts/{article_id}",
        auth=(wp_user, wp_pass),
        params={"context": "edit"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"Failed to fetch post {article_id}: HTTP {r.status_code}", file=sys.stderr)
        return None

    post = r.json()
    return post.get("content", {}).get("raw", "")


def _print_result(article_id: str, result: dict):
    """結果を表示"""
    status_icon = {"PASS": "✅", "SOFT_RETRY": "⚠️", "HARD_FAIL": "❌"}.get(
        result["status"], "?"
    )
    print(f"\n{'='*60}")
    print(f"Article: {article_id}")
    print(f"Status:  {status_icon} {result['status']}")
    print(f"AI phrases detected: {result['total_detected']}")
    print(f"Exclamation marks:   {result['exclamation_count']}")

    if result["detected"]:
        print(f"\nDetected phrases:")
        for item in result["detected"]:
            print(f"  - 「{item['phrase']}」 x{item['count']}")

    if result["warnings"]:
        print(f"\nWarnings:")
        for w in result["warnings"]:
            print(f"  ⚠ {w}")

    print(f"{'='*60}")


# ===== CLI =====
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AI語尾排除チェッカー (Track C)"
    )
    parser.add_argument(
        "--article-id",
        type=int,
        nargs="+",
        help="記事ID（data/drafts/ or WP APIから取得）",
    )
    parser.add_argument(
        "--text",
        type=str,
        help="直接テキストを指定してテスト",
    )
    args = parser.parse_args()

    if args.text:
        result = check_ai_phrases(args.text)
        _print_result("(direct text)", result)
        sys.exit(1 if result["status"] == "HARD_FAIL" else 0)

    elif args.article_id:
        exit_code = 0
        for aid in args.article_id:
            # まずローカルドラフトを試行、なければWP API
            content = _load_draft(aid)
            if content is None:
                content = _fetch_wp_post(aid)
            if content is None:
                print(f"\n❌ Article {aid}: not found in drafts or WP API")
                exit_code = 1
                continue

            result = check_ai_phrases(content)
            _print_result(str(aid), result)
            if result["status"] == "HARD_FAIL":
                exit_code = 1
        sys.exit(exit_code)

    else:
        parser.print_help()
