#!/usr/bin/env python3
"""
fix_candidates.py - 問題記事の修正候補リスト生成

Usage:
  python3 lib/fix_candidates.py

出力: logs/fix_candidates.json
"""
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
JST = timezone(timedelta(hours=9))
WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"

# ── 対象記事ID ────────────────────────────────────────────────────────────────
PROBLEM_POST_IDS = [2544, 2568, 2574, 2555, 2581, 2442, 2530, 2536, 2485, 2484, 2479, 2441]

# ── サムネイル問題レジストリ（thumbnail_audit.pyと同期） ─────────────────────
THUMBNAIL_ISSUES = {
    2544: {"problem": "数字分割・ARIRANGロゴ欠落", "severity": "CRITICAL",
           "suggested_copy": "BTS ARIRANG 初週641000枚"},
    2574: {"problem": "T.O.P→'..'フォント変換バグ", "severity": "CRITICAL",
           "suggested_copy": "TOP 13年ぶりソロ復帰"},
    2555: {"problem": "コピー誤割り当て「3市場の真相判明」", "severity": "CRITICAL",
           "suggested_copy": "BTS グローバル3市場戦略"},
    2581: {"problem": "テキストオーバーフロー右端切断", "severity": "HIGH",
           "suggested_copy": "IVE ウォニョン パリコレ2026"},
    2442: {"problem": "テキスト切れ「入門/ガイドまとめ20…」", "severity": "HIGH",
           "suggested_copy": "K-POP入門ガイド2026"},
    2536: {"problem": "汎用コピー・アーティスト名なし", "severity": "MEDIUM",
           "suggested_copy": "K-POP最新トレンド2026"},
    2485: {"problem": "プロフィール記事: アーティスト名なし", "severity": "MEDIUM",
           "suggested_copy": "K-POPアイドル完全プロフィール"},
    2484: {"problem": "プロフィール記事: アーティスト名なし", "severity": "MEDIUM",
           "suggested_copy": "K-POPアイドル完全プロフィール"},
    2479: {"problem": "コピー長すぎ・オーバーフロー懸念", "severity": "LOW",
           "suggested_copy": "K-POPアイドルプロフィール2026"},
    2441: {"problem": "テキスト長め・オーバーフロー懸念", "severity": "LOW",
           "suggested_copy": "K-POP完全解説2026"},
}

# ── スラッグ修正案（既知） ────────────────────────────────────────────────────
KNOWN_SLUG_FIXES = {
    2574: "top-another-dimension-13years-2026",
    2568: "bts-6years-return-arirang-2026",
    2530: None,  # 重複記事、削除候補（スラッグ修正より整理を優先）
}

# ── X投稿状況（tweet_id_db.tsvベースの既知情報） ──────────────────────────────
X_STATUS_KNOWN = {
    2581: "posted",   # 2026-04-14投稿済み
    2544: "posted",   # pipeline経由で投稿済み
    2574: "posted",   # 2026-04-13 22:47投稿済み
    2530: "unknown",
    2555: "unknown",
    2568: "unknown",
    2536: "unknown",
    2485: "skipped",  # プロフィール記事群、パイプライン外で作成
    2484: "skipped",
    2479: "skipped",
    2442: "unknown",
    2441: "unknown",
}

# ── 重複記事 ──────────────────────────────────────────────────────────────────
DUPLICATE_PAIRS = {
    2530: {"duplicate_of": 2555, "role": "drop_candidate"},
    2555: {"duplicate_of": 2530, "role": "keep"},
}


def _wp_fetch(endpoint: str, timeout: int = 8):
    """WP REST APIフェッチ（失敗時はNone）"""
    url = f"{WP_BASE}/{endpoint}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kpop-fix-candidates/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _fetch_post(post_id: int) -> dict:
    """WP APIで記事情報を取得"""
    data = _wp_fetch(f"posts/{post_id}?_fields=id,slug,title,meta,status,link")
    if not data or not isinstance(data, dict):
        return {}
    return data


def _extract_title(data: dict) -> str:
    t = data.get("title", {})
    if isinstance(t, dict):
        return t.get("rendered", "")
    return str(t)


def _check_meta_desc(data: dict) -> bool:
    """_aioseo_description が非空かチェック"""
    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        return False
    desc = meta.get("_aioseo_description", "")
    return bool(desc and len(desc.strip()) > 10)


def _determine_severity(post_id: int, thumb_issue: dict | None,
                         slug_problem: bool, meta_ok: bool, x_status: str,
                         is_duplicate: bool) -> str:
    if thumb_issue and thumb_issue.get("severity") == "CRITICAL":
        return "P0"
    if is_duplicate and DUPLICATE_PAIRS.get(post_id, {}).get("role") == "drop_candidate":
        return "P1"
    if thumb_issue and thumb_issue.get("severity") == "HIGH":
        return "P1"
    if slug_problem or not meta_ok:
        return "P1"
    if thumb_issue and thumb_issue.get("severity") == "MEDIUM":
        return "P2"
    if x_status in ("skipped", "unknown"):
        return "P2"
    return "P3"


def build_fix_candidate(post_id: int, wp_data: dict) -> dict:
    """1記事の修正候補データを構築"""
    current_slug = wp_data.get("slug", f"post-{post_id}")
    current_title = _extract_title(wp_data)
    meta_desc_ok = _check_meta_desc(wp_data)
    post_link = wp_data.get("link", "")
    post_status = wp_data.get("status", "unknown")

    # スラッグ問題チェック
    proposed_slug = KNOWN_SLUG_FIXES.get(post_id, current_slug)
    slug_has_problem = bool(
        re.match(r"^\d", current_slug) or
        re.match(r"^\d+$", current_slug) or
        (post_id in KNOWN_SLUG_FIXES and KNOWN_SLUG_FIXES[post_id] != current_slug)
    )

    # サムネイル問題
    thumb_info = THUMBNAIL_ISSUES.get(post_id)

    # X投稿状況
    x_status = X_STATUS_KNOWN.get(post_id, "unknown")

    # 重複
    dup_info = DUPLICATE_PAIRS.get(post_id)
    is_duplicate = dup_info is not None

    # 重大度
    severity = _determine_severity(
        post_id, thumb_info, slug_has_problem, meta_desc_ok, x_status, is_duplicate
    )

    result = {
        "post_id": post_id,
        "current_slug": current_slug,
        "proposed_slug": proposed_slug if slug_has_problem else current_slug,
        "slug_has_problem": slug_has_problem,
        "current_title": current_title,
        "post_link": post_link,
        "post_status": post_status,
        "meta_desc_ok": meta_desc_ok,
        "thumbnail_issue": thumb_info.get("problem", "") if thumb_info else "",
        "thumbnail_severity": thumb_info.get("severity", "") if thumb_info else "",
        "thumbnail_copy_candidate": thumb_info.get("suggested_copy", "") if thumb_info else "",
        "x_post_status": x_status,
        "is_duplicate": is_duplicate,
        "duplicate_info": dup_info or {},
        "severity": severity,
        "generated_at": datetime.now(JST).isoformat(),
    }

    return result


def main():
    print(f"fix_candidates.py: {len(PROBLEM_POST_IDS)}記事の修正候補を生成中...")

    candidates = []

    for post_id in PROBLEM_POST_IDS:
        print(f"  ID={post_id} 取得中...", end=" ", flush=True)

        wp_data = _fetch_post(post_id)
        if not wp_data:
            print("(WP API 失敗 → フォールバック使用)")
            wp_data = {"slug": f"post-{post_id}", "title": {"rendered": "(タイトル取得失敗)"}}
        else:
            slug = wp_data.get("slug", "")
            print(f"slug='{slug}' OK")

        candidate = build_fix_candidate(post_id, wp_data)
        candidates.append(candidate)

    # 重大度順にソート
    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    candidates.sort(key=lambda x: (severity_order.get(x["severity"], 9), x["post_id"]))

    # logs/fix_candidates.json に出力
    output_path = LOGS / "fix_candidates.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 出力完了: {output_path}")

    # 画面に表示
    print("\n=== 修正候補一覧 ===")
    for c in candidates:
        print(f"\n  [{c['severity']}] ID={c['post_id']}  slug='{c['current_slug']}'")
        print(f"    タイトル: {c['current_title'][:60]}")
        if c["slug_has_problem"]:
            print(f"    スラッグ修正: → '{c['proposed_slug']}'")
        if not c["meta_desc_ok"]:
            print(f"    メタディスク: NG（_aioseo_description未設定）")
        if c["thumbnail_issue"]:
            print(f"    サムネイル [{c['thumbnail_severity']}]: {c['thumbnail_issue']}")
            print(f"    推奨コピー: {c['thumbnail_copy_candidate']}")
        print(f"    X投稿状況: {c['x_post_status']}")
        if c["is_duplicate"]:
            dup = c["duplicate_info"]
            print(f"    重複: ID={dup.get('duplicate_of')} との重複 role={dup.get('role')}")

    print(f"\n{'='*55}")
    print(f"  P0件数: {sum(1 for c in candidates if c['severity']=='P0')}")
    print(f"  P1件数: {sum(1 for c in candidates if c['severity']=='P1')}")
    print(f"  P2件数: {sum(1 for c in candidates if c['severity']=='P2')}")
    print(f"  P3件数: {sum(1 for c in candidates if c['severity']=='P3')}")

    return candidates


if __name__ == "__main__":
    main()
