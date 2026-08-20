#!/usr/bin/env python3
"""
thumbnail_audit.py - サムネイル品質監査

Usage:
  python3 lib/thumbnail_audit.py [post_id ...]
  python3 lib/thumbnail_audit.py 2544 2574 2555

出力: JSON（stdout）
"""
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
JST = timezone(timedelta(hours=9))

# ── サムネイル解像度の下限（2026-08-20 追加） ────────────────────────────────
# Google のモバイル検索 / Discover で大きなサムネイル表示になる要件が幅1200px。
# これを下回ると画像付きのリッチな表示にならず、順位が取れていてもクリックされない。
# 実害: 「鉄槌教師 声優一覧」(imp 15,460)が 299x168px / 5.2KB のまま公開されていた。
# imp>=300 の50記事中22本が該当し、同じ pos6-10 帯で層別しても
# CTR は 4.13%(1200px未満) vs 8.50%(1200px以上)と約2倍の差があった。
MIN_THUMBNAIL_WIDTH = 1200


def check_resolution(width, height) -> dict:
    """サムネイルの寸法が要件を満たすか判定する。

    width/height が 0 や None(取得失敗)の場合も「不合格」にする。
    取得できなかったものを黙って通すと、壊れたサムネイルが監査をすり抜けるため。
    """
    try:
        w = int(width or 0)
        h = int(height or 0)
    except (TypeError, ValueError):
        w = h = 0

    if w <= 0 or h <= 0:
        return {"ok": False, "width": w, "height": h,
                "issue": f"サムネイルの寸法を取得できない(幅{MIN_THUMBNAIL_WIDTH}px以上が必要)"}
    if w < MIN_THUMBNAIL_WIDTH:
        return {"ok": False, "width": w, "height": h,
                "issue": f"サムネイル幅が不足({w}x{h}px / {MIN_THUMBNAIL_WIDTH}px以上が必要)"}
    return {"ok": True, "width": w, "height": h, "issue": ""}


# ── アーティスト名リスト（検出用） ────────────────────────────────────────────
KNOWN_ARTISTS = [
    "BTS", "TOP", "T.O.P", "TWICE", "BLACKPINK", "IVE", "ILLIT", "aespa",
    "NewJeans", "ENHYPEN", "TXT", "Stray Kids", "SEVENTEEN", "MAMAMOO",
    "EXO", "NCT", "RIIZE", "ZEROBASEONE", "2NE1", "ATEEZ", "THE BOYZ",
    "GOT7", "MONSTA X", "LE SSERAFIM", "Red Velvet", "SuperM", "WayV",
    "ARIRANG", "BIGBANG", "SHINee", "SUPER JUNIOR",
]
_ARTIST_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in KNOWN_ARTISTS) + r")\b",
    re.IGNORECASE
)

# ── 既知問題レジストリ（ハードコード） ─────────────────────────────────────────
KNOWN_ISSUES_REGISTRY = {
    2544: {
        "thumbnail_copy": "BTS「ARIRANG」初週641,000枚——HANTEO・Billboard全チャートで3週連続1位の真相",
        "issues": ["数字分割バグ（641,000が行をまたいで表示）", "ARIRANGロゴ欠落"],
        "design_score": 30,
        "overflow_risk": True,
        "artist_detected": True,
        "title_mismatch": False,
        "suggested_copy": "BTS ARIRANG 初週641000枚",
    },
    2574: {
        "thumbnail_copy": "13年間、T.O.Pは何を溜めていたのか",
        "issues": ["T.O.P→'..'フォント変換バグ（ピリオドが空白になる）"],
        "design_score": 25,
        "overflow_risk": False,
        "artist_detected": False,  # バグにより検出不可
        "title_mismatch": False,
        "suggested_copy": "TOP 13年ぶりソロ復帰",
    },
    2555: {
        "thumbnail_copy": "3市場の真相判明",
        "issues": ["コピー誤割り当て（別記事用コピーが混入）", "アーティスト名なし"],
        "design_score": 20,
        "overflow_risk": False,
        "artist_detected": False,
        "title_mismatch": True,
        "suggested_copy": "BTS グローバル3市場戦略",
    },
    2581: {
        "thumbnail_copy": "IVEウォニョン、2026パリコレに完全参加決定",
        "issues": ["テキストオーバーフロー（右端切断）"],
        "design_score": 50,
        "overflow_risk": True,
        "artist_detected": True,
        "title_mismatch": False,
        "suggested_copy": "IVE ウォニョン パリコレ2026",
    },
    2442: {
        "thumbnail_copy": "K-POP入門/ガイドまとめ2026年版...",
        "issues": ["テキスト切れ（末尾が省略記号で終わる）"],
        "design_score": 55,
        "overflow_risk": True,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "K-POP入門ガイド2026",
    },
    2536: {
        "thumbnail_copy": "K-POPトレンド最新情報",
        "issues": ["アーティスト名未検出", "汎用コピー（SEO弱）"],
        "design_score": 60,
        "overflow_risk": False,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "K-POP最新トレンド2026",
    },
    2485: {
        "thumbnail_copy": "K-POPアイドルプロフィール",
        "issues": ["アーティスト名なし（プロフィール記事）"],
        "design_score": 65,
        "overflow_risk": False,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "K-POPアイドル完全プロフィール",
    },
    2484: {
        "thumbnail_copy": "K-POPアイドルプロフィール",
        "issues": ["アーティスト名なし（プロフィール記事）"],
        "design_score": 65,
        "overflow_risk": False,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "K-POPアイドル完全プロフィール",
    },
    2479: {
        "thumbnail_copy": "K-POPアイドル完全プロフィールガイド2026年版最新情報",
        "issues": ["コピー長すぎ（オーバーフロー懸念）"],
        "design_score": 70,
        "overflow_risk": True,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "K-POPアイドルプロフィール2026",
    },
    2441: {
        "thumbnail_copy": "K-POP完全解説ガイド2026年最新版まとめコンテンツ",
        "issues": ["テキスト長めでオーバーフロー懸念"],
        "design_score": 70,
        "overflow_risk": True,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "K-POP完全解説2026",
    },
}


def _wp_fetch(endpoint: str, timeout: int = 8) -> dict | list | None:
    """WP REST APIフェッチ（失敗時はNone）"""
    url = f"{WP_BASE}/{endpoint}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kpop-audit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _analyze_copy(copy_text: str, article_title: str = "") -> dict:
    """コピーテキストを分析して問題を検出"""
    issues = []

    if not copy_text:
        return {
            "issues": ["コピーテキストなし"],
            "overflow_risk": False,
            "artist_detected": False,
            "title_mismatch": True,
            "design_score": 0,
        }

    # 長さチェック
    overflow_risk = len(copy_text) > 30
    if overflow_risk:
        issues.append(f"コピー長={len(copy_text)}文字（30文字超、オーバーフロー懸念）")

    # アーティスト名検出
    artist_detected = bool(_ARTIST_RE.search(copy_text))
    if not artist_detected:
        issues.append("アーティスト名未検出")

    # T.O.P パターン（'..' バグ検出）
    if "T.O.P" in copy_text or re.search(r"\.\.+", copy_text):
        issues.append("T.O.P等ピリオド含む名前→フォントバグ懸念。TOPフォールバック推奨")

    # 「」 空パターン
    if "「」" in copy_text:
        issues.append("「」空パターン検出（テキスト欠落の疑い）")

    # ".." パターン
    if ".." in copy_text and "T.O.P" not in copy_text:
        issues.append("'..'パターン検出（テキスト化けの疑い）")

    # タイトル一致チェック
    title_mismatch = False
    if article_title:
        from_title_words = set(re.findall(r"[\w]+", article_title.lower()))
        from_copy_words = set(re.findall(r"[\w]+", copy_text.lower()))
        if from_title_words and from_copy_words:
            overlap = len(from_title_words & from_copy_words) / len(from_title_words)
            if overlap < 0.15:
                title_mismatch = True
                issues.append(f"タイトルとコピーのキーワード一致率低（{overlap:.0%}）")

    # デザインスコア
    design_score = 100
    design_score -= len(issues) * 15
    if overflow_risk:
        design_score -= 10
    if not artist_detected:
        design_score -= 10
    if title_mismatch:
        design_score -= 20
    design_score = max(0, design_score)

    return {
        "issues": issues,
        "overflow_risk": overflow_risk,
        "artist_detected": artist_detected,
        "title_mismatch": title_mismatch,
        "design_score": design_score,
    }


def _probe_image_size(url: str):
    """画像URLから (width, height) を返す。取得できなければ (0, 0)。

    Pillow が無い環境でも監査全体が落ちないよう、失敗は (0,0) に丸める
    ((0,0) は check_resolution 側で不合格として扱われる)。
    """
    if not url:
        return (0, 0)
    try:
        import io
        from PIL import Image
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return (0, 0)


def audit_post_thumbnail(post_id: int) -> dict:
    """1記事のサムネイル監査結果を返す"""
    result = {
        "post_id": post_id,
        "slug": "",
        "article_title": "",
        "thumbnail_url": "",
        "thumbnail_copy": "",
        "issues": [],
        "design_score": 100,
        "overflow_risk": False,
        "artist_detected": False,
        "title_mismatch": False,
        "suggested_copy": "",
        "source": "registry",
        "thumbnail_width": 0,
        "thumbnail_height": 0,
        "resolution_ok": None,
    }

    # 既知問題レジストリから先に読む（API呼び出しなし）
    if post_id in KNOWN_ISSUES_REGISTRY:
        reg = KNOWN_ISSUES_REGISTRY[post_id]
        result.update({
            "thumbnail_copy": reg.get("thumbnail_copy", ""),
            "issues": reg.get("issues", []),
            "design_score": reg.get("design_score", 100),
            "overflow_risk": reg.get("overflow_risk", False),
            "artist_detected": reg.get("artist_detected", False),
            "title_mismatch": reg.get("title_mismatch", False),
            "suggested_copy": reg.get("suggested_copy", ""),
            "source": "registry",
        })

    # WP APIからpost情報を取得（失敗しても結果を返す）
    post_data = _wp_fetch(f"posts/{post_id}?_fields=id,slug,title,featured_media")
    if post_data and isinstance(post_data, dict):
        result["slug"] = post_data.get("slug", "")
        title_raw = post_data.get("title", {})
        if isinstance(title_raw, dict):
            result["article_title"] = title_raw.get("rendered", "")
        elif isinstance(title_raw, str):
            result["article_title"] = title_raw

        media_id = post_data.get("featured_media", 0)
        if media_id:
            media_data = _wp_fetch(f"media/{media_id}?_fields=source_url")
            if media_data and isinstance(media_data, dict):
                result["thumbnail_url"] = media_data.get("source_url", "")

        # カスタムフィールドからコピーを取得（_thumbnail_copy_text）
        meta_data = _wp_fetch(f"posts/{post_id}?_fields=meta")
        if meta_data and isinstance(meta_data, dict):
            meta = meta_data.get("meta", {})
            if isinstance(meta, dict):
                copy_from_meta = meta.get("_thumbnail_copy_text", "")
                if copy_from_meta and not result["thumbnail_copy"]:
                    result["thumbnail_copy"] = copy_from_meta
                    result["source"] = "wp_meta"

        # コピーが取れた場合は分析を再実行
        if result["thumbnail_copy"] and result["source"] == "wp_meta":
            analysis = _analyze_copy(result["thumbnail_copy"], result["article_title"])
            if not result["issues"]:  # レジストリに問題がなければ分析結果を使用
                result.update(analysis)

    # 解像度チェック(2026-08-20 追加)。ここを検査していなかったため
    # 299x168px のサムネイルが imp 15,460 の記事に付いたまま残っていた。
    if result["thumbnail_url"]:
        w, h = _probe_image_size(result["thumbnail_url"])
        res = check_resolution(w, h)
        result["thumbnail_width"] = res["width"]
        result["thumbnail_height"] = res["height"]
        result["resolution_ok"] = res["ok"]
        if not res["ok"]:
            result["issues"] = list(result["issues"]) + [res["issue"]]
            result["design_score"] = min(result.get("design_score", 100), 50)

    return result


def main():
    post_ids_arg = sys.argv[1:]

    if post_ids_arg:
        try:
            post_ids = [int(x) for x in post_ids_arg]
        except ValueError:
            print("Usage: python3 thumbnail_audit.py [post_id ...]", file=sys.stderr)
            sys.exit(1)
    else:
        # デフォルト: 既知問題レジストリの全ID
        post_ids = list(KNOWN_ISSUES_REGISTRY.keys())

    results = []
    for pid in post_ids:
        result = audit_post_thumbnail(pid)
        results.append(result)

        # 見やすい出力
        print(f"\n{'─'*55}")
        print(f"  post_id={result['post_id']}  slug='{result['slug']}'")
        print(f"  タイトル: {result['article_title'][:60]}")
        print(f"  サムネURL: {result['thumbnail_url'][:70] or '(取得失敗)'}")
        print(f"  コピー: {result['thumbnail_copy']}")
        print(f"  デザインスコア: {result['design_score']}/100")
        print(f"  オーバーフロー: {'YES' if result['overflow_risk'] else 'NO'}  "
              f"アーティスト検出: {'YES' if result['artist_detected'] else 'NO'}  "
              f"タイトル不一致: {'YES' if result['title_mismatch'] else 'NO'}")
        if result["issues"]:
            print(f"  問題:")
            for issue in result["issues"]:
                print(f"    • {issue}")
        if result["suggested_copy"]:
            print(f"  推奨コピー: {result['suggested_copy']}")

    print(f"\n{'─'*55}")
    print("\n=== JSON出力 ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
