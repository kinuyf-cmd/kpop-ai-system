#!/usr/bin/env python3
"""seo_auto_rollback.py — body_enrich による本文更新の事後効果が悪化した記事を、
backups/body_enrich/ に保存済みの更新前 HTML へ自動で差し戻す安全弁。

判定条件(いずれも満たした場合のみロールバック):
  - body_enrich.jsonl に result=updated の記録があり、実行から
    ROLLBACK_WINDOW_DAYS 日以上 ROLLBACK_MAX_AGE_DAYS 日以内
  - data/page_one_progress.jsonl の最新週で、記事合計の clicks_delta が
    ROLLBACK_CLICKS_DELTA_THRESHOLD 以下、かつ前週比 ROLLBACK_RELATIVE_DROP 以下
  - 強化後に記事が編集されていない(手動改稿を古いバックアップで潰さない)
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
# 強化からこれより古い記事は差し戻さない。上限が無いと、数か月前のバックアップで
# その後の手動改稿ごと上書きしてしまう。
ROLLBACK_MAX_AGE_DAYS = 28
# 前週比の実 delta 分布(2026-07-17〜10-09 の13週・201行)で決めた閾値。
#   p5=-1 / 中央値0 / 最小-8。-3以下は3行(1.5%)で、うち2行は週19〜28clkの主力記事の
#   自然な揺れ(-15%〜-30%)だった。絶対値だけだと主力記事の揺れを拾うので、
#   「記事合計で -5 以下」かつ「前週比 -30% 以下」の両方を満たしたときだけ差し戻す。
ROLLBACK_CLICKS_DELTA_THRESHOLD = -5
ROLLBACK_RELATIVE_DROP = -0.30


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
    """同一 slug の最新 clicks_delta。前週比定義(delta_basis='prev_week')の行のみ。

    過去行の clicks_delta は baseline(28日累積) 比で、定義が異なる。
    混ぜて判断すると閾値の意味が変わり過剰に差し戻す。
    移行第1週は全件 delta=0 になるため rollback は構造的に発火しない(想定内)。
    """
    matches = [r for r in progress_rows
               if r.get("slug") == slug and r.get("delta_basis") == "prev_week"]
    if not matches:
        return None
    matches.sort(key=lambda r: r.get("week", ""))
    return matches[-1].get("clicks_delta")


def _latest_week_totals(progress_rows, slug):
    """同一 slug の最新週について (clicks_delta 合計, 前週 clicks 合計) を返す。

    tracker はクエリ単位で行を書くので、1記事が同じ週に複数行を持つ。
    1行だけ見ると、どのクエリを引いたかで判定が変わる。
    """
    matches = [r for r in progress_rows
               if r.get("slug") == slug and r.get("delta_basis") == "prev_week"]
    if not matches:
        return None, None
    week = max(r.get("week", "") for r in matches)
    rows = [r for r in matches if r.get("week", "") == week]
    delta = sum(r.get("clicks_delta") or 0 for r in rows)
    prev = sum((r.get("clicks_abs") or 0) - (r.get("clicks_delta") or 0) for r in rows)
    return delta, prev


def _is_harmful(delta, prev):
    if delta is None or delta > ROLLBACK_CLICKS_DELTA_THRESHOLD:
        return False
    return prev > 0 and delta / prev <= ROLLBACK_RELATIVE_DROP


def _modified_after(post_id, enrich_ts, wp_request):
    """強化後に記事が編集されていれば True。確認できないときも True(差し戻さない)。"""
    resp, err = wp_request("GET", f"/posts/{post_id}?context=edit&_fields=modified_gmt")
    if not resp or not resp.get("modified_gmt"):
        print(f"[rollback] post {post_id} の更新日時を取得できない({err}) → 差し戻さない")
        return True
    modified = datetime.fromisoformat(resp["modified_gmt"]).replace(tzinfo=timezone.utc)
    return modified > datetime.fromisoformat(enrich_ts) + timedelta(minutes=10)


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
        if not ROLLBACK_WINDOW_DAYS <= (now - t).days <= ROLLBACK_MAX_AGE_DAYS:
            continue
        delta, prev = _latest_week_totals(progress_rows, slug)
        if not _is_harmful(delta, prev):
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
        if _modified_after(c["post_id"], c["enrich_ts"], wp_request):
            print(f"[rollback] {c['slug']} は強化後に編集されている → 差し戻さない")
            continue
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
    # 2026-10-11 に閾値を実分布から決めたので dry-run 固定は解除。旧フラグは互換のため受けるだけ。
    ap.add_argument("--i-have-set-the-threshold-from-observed-distribution",
                    action="store_true", dest="threshold_set", help=argparse.SUPPRESS)
    args = ap.parse_args()
    sys.exit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
