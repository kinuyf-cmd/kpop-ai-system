#!/usr/bin/env python3
"""seo_auto_rollback.py — body_enrich による本文更新の事後効果が悪化した記事を、
backups/body_enrich/ に保存済みの更新前 HTML へ自動で差し戻す安全弁。

判定条件(いずれも満たした場合のみロールバック):
  - body_enrich.jsonl に result=updated の記録があり、実行から
    ROLLBACK_WINDOW_DAYS 日以上経過している
  - data/page_one_progress.jsonl に同一 slug の直近計測があり、
    clicks_delta が ROLLBACK_CLICKS_DELTA_THRESHOLD 以下(悪化)
  - 同一 slug に対し過去にロールバック済みでない(二重差し戻し防止)

ロールバックは「更新前バックアップの content で上書き」のみ(削除・改変ではなく
前の状態に戻すだけ)。実行結果は logs/seo_rollback.jsonl に記録し Discord 通知。

使い方:
  venv_kpi/bin/python3 lib/seo_auto_rollback.py --dry-run
  venv_kpi/bin/python3 lib/seo_auto_rollback.py
"""
import os
import sys
import json
import glob
import argparse
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

ENRICH_LOG = os.path.join(BASE_DIR, "logs", "body_enrich.jsonl")
PROGRESS = os.path.join(BASE_DIR, "data", "page_one_progress.jsonl")
BACKUP_DIR = os.path.join(BASE_DIR, "backups", "body_enrich")
ROLLBACK_LOG = os.path.join(BASE_DIR, "logs", "seo_rollback.jsonl")

ROLLBACK_WINDOW_DAYS = 7
ROLLBACK_CLICKS_DELTA_THRESHOLD = -3  # baseline比でこれ以下悪化していたら差し戻し


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _already_rolled_back(slugs_done, slug):
    return slug in slugs_done


def _latest_clicks_delta(progress_rows, slug):
    matches = [r for r in progress_rows if r.get("slug") == slug]
    if not matches:
        return None
    matches.sort(key=lambda r: r.get("week", ""))
    return matches[-1].get("clicks_delta")


def _candidates():
    enrich_rows = [r for r in _load_jsonl(ENRICH_LOG) if r.get("result") == "updated"]
    progress_rows = _load_jsonl(PROGRESS)
    done = {r.get("slug") for r in _load_jsonl(ROLLBACK_LOG)}
    now = datetime.now(timezone.utc)

    out = []
    for r in enrich_rows:
        slug = r.get("slug")
        if not slug or _already_rolled_back(done, slug):
            continue
        ts = r.get("ts")
        try:
            t = datetime.fromisoformat(ts)
        except Exception:
            continue
        if (now - t).days < ROLLBACK_WINDOW_DAYS:
            continue
        delta = _latest_clicks_delta(progress_rows, slug)
        if delta is None or delta > ROLLBACK_CLICKS_DELTA_THRESHOLD:
            continue
        # 対応するバックアップファイルを探す(slugプレフィックスの最新1件)
        backup = r.get("backup")
        if not backup or not os.path.exists(backup):
            candidates_files = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{slug}_*.html")))
            backup = candidates_files[-1] if candidates_files else None
        if not backup:
            continue
        out.append({"slug": slug, "post_id": r.get("post_id"), "backup": backup,
                     "clicks_delta": delta, "enrich_ts": ts})
    return out


def notify_discord(message):
    try:
        from lib.resolve_discord_webhook import resolve
        import urllib.request
        url = resolve("seo_insights")
        if not url:
            return
        body = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (compatible; KpopJournalBot/1.0)"},
            method="POST")
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  [rollback] discord通知失敗(続行): {e}", file=sys.stderr)


def run(dry_run=False):
    from lib.auto_rewriter import wp_request
    cands = _candidates()
    if not cands:
        print("[rollback] 対象なし")
        return 0

    os.makedirs(os.path.dirname(ROLLBACK_LOG), exist_ok=True)
    done_count = 0
    for c in cands:
        print(f"[rollback] {c['slug']} clicks_delta={c['clicks_delta']} backup={c['backup']}")
        if dry_run:
            continue
        original = open(c["backup"], encoding="utf-8").read()
        resp, err = wp_request("POST", f"/posts/{c['post_id']}", {"content": original})
        record = {"ts": datetime.now(timezone.utc).isoformat(), "slug": c["slug"],
                   "post_id": c["post_id"], "clicks_delta": c["clicks_delta"],
                   "backup": c["backup"], "wp_update_ok": bool(resp and resp.get("id")),
                   "error": err}
        with open(ROLLBACK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if record["wp_update_ok"]:
            done_count += 1
            notify_discord(f"↩️ seo_auto_rollback: {c['slug']} を更新前へ差し戻し "
                            f"(clicks_delta={c['clicks_delta']})")
        else:
            notify_discord(f"⚠️ seo_auto_rollback 失敗: {c['slug']} ({err})")
    print(f"[rollback] 完了: {done_count}/{len(cands)}件差し戻し")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
