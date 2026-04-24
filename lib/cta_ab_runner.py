#!/usr/bin/env python3
"""cta_ab_runner.py — CTA 3パターン生成 + A/Bテスト記録

対象:
  logs/gsc_metrics_latest.json から pages を読み、impressions > N
  の記事に対して CTA 3パターンを生成し、ランダムに1つを割り当てて
  WP 本文末尾の <div data-cta="ab-test"> ブロックを差し替える。

出力:
  logs/cta_ab_test.jsonl — 1行 = 1割り当て記録（post_id / variant / inserted_at）

変数別 headline / description / button_text の3バリアント:
  A: 緊急性訴求  - 「今すぐチェック」系
  B: 限定・特別  - 「ファン限定」系
  C: 比較・検証  - 「比較して選ぶ」系

使い方:
  python3 lib/cta_ab_runner.py --top 10              # impr上位10記事に割当
  python3 lib/cta_ab_runner.py --top 5 --dry-run
  python3 lib/cta_ab_runner.py --post-id 12345       # 特定記事のみ
"""
from __future__ import annotations
import argparse
import json
import random
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
METRICS = LOGS / "gsc_metrics_latest.json"
AB_LOG = LOGS / "cta_ab_test.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

VARIANTS = {
    "A": {
        "headline": "⏰ 今すぐK-POP最新情報をチェック",
        "description": "毎日更新される最新チャート・カムバック情報・ライブレポートで、推し活に後れを取らない。",
        "button_text": "最新記事をまとめて読む →",
        "color": "#ff4d6d",
    },
    "B": {
        "headline": "💎 ファン限定の深掘り情報をお届け",
        "description": "メディアでは見られない舞台裏・チャート分析・ファンダム文化を、K-POP JOURNAL だけで。",
        "button_text": "ファン向け記事を読む →",
        "color": "#7b61ff",
    },
    "C": {
        "headline": "🔍 情報の裏付けを比較で検証",
        "description": "公式発表・Billboard公式・韓国主要紙の3軸で情報を検証。誇張のない K-POP メディア。",
        "button_text": "比較記事を読む →",
        "color": "#2c5282",
    },
}

CTA_MARKER_RE = re.compile(
    r'<div[^>]+data-cta="ab-test"[^>]*>.*?</div>\s*',
    flags=re.DOTALL,
)


def curl_get(path: str):
    out = subprocess.check_output(
        ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH], timeout=30
    ).decode()
    return json.loads(out)


def curl_post(path: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def slug_from_url(url: str) -> str:
    m = re.match(r"https://www\.kpopjournal\.tokyo/([^/?#]+)/?$", url)
    return m.group(1) if m else ""


def build_cta_html(variant_key: str, hub_link: str = "/kpop-beginner-hub-2026/") -> str:
    v = VARIANTS[variant_key]
    return (
        f'<div data-cta="ab-test" data-variant="{variant_key}" '
        f'style="margin:32px 0;padding:20px;border:2px solid {v["color"]};'
        f'border-radius:12px;background:#fff;text-align:center;">'
        f'<p style="margin:0 0 8px;font-size:1.15em;font-weight:700;color:{v["color"]};">'
        f'{v["headline"]}</p>'
        f'<p style="margin:0 0 14px;color:#555;line-height:1.7;">{v["description"]}</p>'
        f'<a href="{hub_link}" '
        f'style="display:inline-block;background:{v["color"]};color:#fff;'
        f'padding:10px 28px;border-radius:8px;text-decoration:none;font-weight:700;">'
        f'{v["button_text"]}</a></div>'
    )


def load_top_urls(top: int) -> list[dict]:
    if not METRICS.exists():
        return []
    d = json.loads(METRICS.read_text())
    pages = d.get("pages", [])
    from growth_exclude import is_excluded
    out = []
    for p in pages:
        u = p["url"]
        if is_excluded(u)[0]:
            continue
        out.append(p)
    out.sort(key=lambda x: -x["impressions"])
    return out[:top]


def already_assigned(post_id: int) -> str | None:
    if not AB_LOG.exists():
        return None
    latest = None
    for line in AB_LOG.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("post_id") == post_id and d.get("status") == "inserted":
                latest = d.get("variant")
        except Exception:
            continue
    return latest


def assign_variant(post_id: int) -> str:
    # 既存があればそれを維持、新規ならランダム割当
    prev = already_assigned(post_id)
    if prev in VARIANTS:
        return prev
    return random.choice(list(VARIANTS.keys()))


def process_post(post_id: int, url: str, dry_run: bool) -> dict:
    ts = datetime.now(tz=JST).isoformat()
    variant = assign_variant(post_id)
    cta_html = build_cta_html(variant)

    try:
        post = curl_get(f"/wp-json/wp/v2/posts/{post_id}?context=edit&_fields=id,content")
    except Exception as e:
        return {"ts": ts, "post_id": post_id, "url": url, "variant": variant,
                "status": "fetch_error", "error": str(e)}

    raw = post.get("content", {}).get("raw", "") or post.get("content", {}).get("rendered", "")
    if not raw:
        return {"ts": ts, "post_id": post_id, "url": url, "variant": variant,
                "status": "empty_content"}

    # 既存のab-testブロックを置換、なければ末尾に追記
    new_content, n = CTA_MARKER_RE.subn("", raw)
    new_content = new_content.rstrip() + "\n\n" + cta_html

    if dry_run:
        return {"ts": ts, "post_id": post_id, "url": url, "variant": variant,
                "status": "dry_run", "replaced": n > 0, "content_len": len(new_content)}

    try:
        curl_post(f"/wp-json/wp/v2/posts/{post_id}", {"content": new_content})
        return {"ts": ts, "post_id": post_id, "url": url, "variant": variant,
                "status": "inserted", "replaced": n > 0}
    except Exception as e:
        return {"ts": ts, "post_id": post_id, "url": url, "variant": variant,
                "status": "update_error", "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--post-id", type=int, default=0,
                    help="特定のpost_idだけに割当（--topより優先）")
    args = ap.parse_args()

    random.seed(datetime.now(tz=JST).strftime("%Y%m%d"))

    targets = []
    if args.post_id:
        try:
            p = curl_get(f"/wp-json/wp/v2/posts/{args.post_id}?_fields=id,link")
            if p.get("id"):
                targets.append({"post_id": p["id"], "url": p.get("link", "")})
        except Exception as e:
            print(f"[cta_ab_runner] post_id={args.post_id} 取得失敗: {e}")
            return
    else:
        cand = load_top_urls(args.top)
        for p in cand:
            slug = slug_from_url(p["url"])
            if not slug:
                continue
            try:
                r = curl_get(f"/wp-json/wp/v2/posts?slug={slug}&_fields=id,link")
                if isinstance(r, list) and r:
                    targets.append({"post_id": r[0]["id"], "url": r[0].get("link", p["url"])})
            except Exception:
                continue

    print(f"[cta_ab_runner] 対象 {len(targets)} 記事 dry_run={args.dry_run}")

    AB_LOG.parent.mkdir(parents=True, exist_ok=True)
    stats = {"A": 0, "B": 0, "C": 0, "error": 0, "dry": 0}

    with AB_LOG.open("a") as fp:
        for i, t in enumerate(targets, 1):
            rec = process_post(t["post_id"], t["url"], args.dry_run)
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            v = rec.get("variant", "?")
            st = rec.get("status", "?")
            mark = "✅" if st == "inserted" else ("🟡" if st == "dry_run" else "❌")
            print(f"  [{i:2d}] {mark} post={t['post_id']} variant={v} status={st}")
            if st == "inserted":
                stats[v] = stats.get(v, 0) + 1
            elif st == "dry_run":
                stats["dry"] += 1
            else:
                stats["error"] += 1

    print()
    print(f"[cta_ab_runner] A={stats['A']} B={stats['B']} C={stats['C']} "
          f"dry={stats['dry']} error={stats['error']}")
    print(f"  ログ: {AB_LOG}")


if __name__ == "__main__":
    main()
