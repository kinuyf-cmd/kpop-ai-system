#!/usr/bin/env python3
"""seo_feedback_loop.py — 検証結果(page_one_progress.jsonl)を集計し、
SEO戦略パラメータ(config/seo_config.json)への調整案を「提案」として出力する。

自己改善ループの「検証→改善」フェーズを担う。ただし config/seo_config.json
への書き込みは行わない(影響範囲が全theme/全キーワード優先度に及ぶため、
owner承認を必須とする方針。2026-07-08 owner判断)。

処理:
  1. data/page_one_progress.jsonl の直近 LOOKBACK_WEEKS 分を集計
  2. body_enrich.jsonl / rewrite_actions.jsonl と slug/post_id を突き合わせ、
     「どの施策(enrich/rewrite)がどの記事に効いたか」を仕分け
  3. 施策別・theme別(enrich_queue由来のthemeが分かる範囲)に
     crossed_10率・clicks_delta平均を算出
  4. 効果が芳しくない group を検知したら、seo_config.json への変更案を
     logs/seo_config_proposals.jsonl に追記(自動適用はしない)
  5. Discord(seo_insights)へサマリ通知

使い方:
  venv_kpi/bin/python3 lib/seo_feedback_loop.py
依存: 読み取り専用(page_one_progress.jsonl / body_enrich.jsonl /
      rewrite_actions.jsonl / enrich_queue.json)。書き込みは
      logs/seo_config_proposals.jsonl のみ(seo_config.json 自体は不変)。
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

PROGRESS = os.path.join(BASE_DIR, "data", "page_one_progress.jsonl")
ENRICH_LOG = os.path.join(BASE_DIR, "logs", "body_enrich.jsonl")
REWRITE_LOG = os.path.join(BASE_DIR, "logs", "rewrite_actions.jsonl")
ENRICH_QUEUE = os.path.join(BASE_DIR, "data", "enrich_queue.json")
SEO_CONFIG = os.path.join(BASE_DIR, "config", "seo_config.json")
PROPOSALS_LOG = os.path.join(BASE_DIR, "logs", "seo_config_proposals.jsonl")

LOOKBACK_WEEKS = 4
# この閾値を下回る crossed_10率(1ページ目進入率)を「効果薄」とみなす
LOW_EFFECT_CROSSED10_RATE = 0.10
MIN_SAMPLES_FOR_JUDGEMENT = 5


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


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _recent_progress(weeks=LOOKBACK_WEEKS):
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).date().isoformat()
    rows = _load_jsonl(PROGRESS)
    return [r for r in rows if r.get("week", "") >= cutoff]


def _slug_theme_map():
    """enrich_queue.json(現行分)から slug -> theme のヒントを得る。
    処理済みでqueueから除去済みの記事は分からないため、あくまで補助情報。"""
    m = {}
    for r in _load_json(ENRICH_QUEUE, default=[]):
        if r.get("slug"):
            m[r["slug"]] = r.get("theme", "unknown")
    return m


def _route_map():
    """slug/post_id -> 実行された施策("enrich"/"rewrite") のマップ。"""
    routes = {}
    for r in _load_jsonl(ENRICH_LOG):
        if r.get("result") == "updated" and r.get("slug"):
            routes[("slug", r["slug"])] = "enrich"
    for r in _load_jsonl(REWRITE_LOG):
        if r.get("wp_update_ok") and r.get("post_id"):
            routes[("post_id", str(r["post_id"]))] = "rewrite"
    return routes


def aggregate():
    rows = _recent_progress()
    theme_map = _slug_theme_map()
    groups = {}  # key(theme or "unknown") -> list of rows
    for r in rows:
        theme = theme_map.get(r.get("slug", ""), "unknown")
        groups.setdefault(theme, []).append(r)
    summary = {}
    for theme, rs in groups.items():
        n = len(rs)
        crossed10 = sum(1 for r in rs if r.get("crossed_10"))
        clicks_delta_avg = sum(r.get("clicks_delta", 0) for r in rs) / n if n else 0
        summary[theme] = {
            "n": n,
            "crossed_10_rate": round(crossed10 / n, 3) if n else 0,
            "clicks_delta_avg": round(clicks_delta_avg, 2),
        }
    return summary, rows


def build_proposals(summary):
    """効果が芳しくない theme に対する seo_config.json 変更案(提案のみ)。"""
    proposals = []
    cfg = _load_json(SEO_CONFIG, default={})
    allocation = cfg.get("difficulty_article_allocation", {})
    for theme, stats in summary.items():
        if stats["n"] < MIN_SAMPLES_FOR_JUDGEMENT:
            continue
        if stats["crossed_10_rate"] < LOW_EFFECT_CROSSED10_RATE and stats["clicks_delta_avg"] <= 0:
            proposals.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "theme": theme,
                "observed": stats,
                "suggestion": (
                    f"theme='{theme}' は直近{LOOKBACK_WEEKS}週で crossed_10_rate="
                    f"{stats['crossed_10_rate']} / clicks_delta_avg={stats['clicks_delta_avg']} と効果薄。"
                    f"enrich対象からの一時除外、または min_word_count 引き上げを検討。"
                ),
                "config_target": "difficulty_article_allocation / ENRICH_BLOCKED_THEMES",
                "current_allocation_snapshot": allocation,
                "status": "pending_owner_review",
            })
    return proposals


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
        print(f"  [feedback_loop] discord通知失敗(続行): {e}", file=sys.stderr)


def run():
    summary, rows = aggregate()
    proposals = build_proposals(summary)

    if proposals:
        os.makedirs(os.path.dirname(PROPOSALS_LOG), exist_ok=True)
        with open(PROPOSALS_LOG, "a", encoding="utf-8") as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"[feedback_loop] 集計対象: {len(rows)}件(直近{LOOKBACK_WEEKS}週)")
    for theme, stats in sorted(summary.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  theme={theme}: n={stats['n']} crossed_10率={stats['crossed_10_rate']} "
              f"clicks_delta平均={stats['clicks_delta_avg']}")
    if proposals:
        print(f"[feedback_loop] config変更提案: {len(proposals)}件 → {PROPOSALS_LOG}(owner承認待ち)")
        lines = "\n".join(f"- {p['suggestion']}" for p in proposals)
        notify_discord(f"📊 SEO週次フィードバック: config変更提案{len(proposals)}件\n{lines}\n"
                        f"(owner承認待ち、logs/seo_config_proposals.jsonl 参照)")
    else:
        print("[feedback_loop] config変更提案なし")
        if rows:
            top = sorted(summary.items(), key=lambda kv: -kv[1]["n"])[:3]
            lines = "\n".join(f"- {t}: n={s['n']} crossed_10率={s['crossed_10_rate']}" for t, s in top)
            notify_discord(f"📊 SEO週次フィードバック: 集計{len(rows)}件、要調整なし\n{lines}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
