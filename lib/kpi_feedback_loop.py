#!/usr/bin/env python3
"""
kpi_feedback_loop.py — KPIデータ→エージェント自動注入 v1.0

【責務】
  1. GSC CTRデータ（low_ctr_pages.json）からCTR低下記事を検出
  2. 低CTR原因を自動分類（タイトル弱/SEO不備/コンテンツ薄/ポジション問題）
  3. 原因別にmetamon/deoxys/laprasへ改善指示を自動注入
  4. CTR改善実績を追跡し、勝ちパターンをwinning_title_patternsへ還元

【パイプライン統合】
  feedback_loop_orchestrator.py から毎日06:30 JST に呼ばれる。
  google_metrics/fetch_yesterday_metrics.py の実行後に走る前提。

Usage:
  python3 lib/kpi_feedback_loop.py                # 通常実行
  python3 lib/kpi_feedback_loop.py --dry-run      # 判定のみ
  python3 lib/kpi_feedback_loop.py --stats        # 統計表示
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
GOOGLE_METRICS = BASE / "google_metrics"
AGENTS = BASE / "agents"
CONFIG = BASE / "config"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# ── データソース ──
LOW_CTR_PATH = GOOGLE_METRICS / "low_ctr_pages.json"
METRICS_PATH = GOOGLE_METRICS / "metrics_yesterday.json"
WINNING_PATH = LOGS / "winning_title_patterns.json"
POST_LOG_PATH = LOGS / "post_log.json"
FEEDBACK_LOG = LOGS / "kpi_feedback_loop.jsonl"

# ── 閾値 ──
CTR_LOW_THRESHOLD = 0.02          # 2%未満 → 改善対象
CTR_CRITICAL_THRESHOLD = 0.005    # 0.5%未満 → 緊急改善
IMPRESSIONS_MIN = 100             # 表示回数がこれ未満は無視
POSITION_POOR_THRESHOLD = 20      # 掲載順位20位以下はSEO問題

# ── CTR低下原因カテゴリ ──
CTR_DECLINE_CATEGORIES = {
    "title_weak": {
        "label": "タイトル訴求力不足",
        "condition": "CTR低 + 掲載順位10位以内（見られているのにクリックされない）",
        "target_agents": ["metamon_kpop", "deoxys_kpop"],
        "instruction": (
            "このページはGoogle検索で上位表示されているのにCTRが低い。"
            "タイトルに感情語・具体数字・対比構造を追加し、クリック衝動を刺激するタイトルにリライトすること。"
        ),
    },
    "seo_position_low": {
        "label": "掲載順位問題（SEO不足）",
        "condition": "CTR低 + 掲載順位15位以下（そもそも見られていない）",
        "target_agents": ["lapras"],
        "instruction": (
            "このページは掲載順位が低くCTRも低い。"
            "H2見出しのKW最適化・内部リンク強化・コンテンツ量の追加でSEOを改善すること。"
        ),
    },
    "content_thin": {
        "label": "コンテンツ情報密度不足",
        "condition": "CTR低 + 表示回数多い + 掲載順位中位（改善余地大）",
        "target_agents": ["deoxys_kpop"],
        "instruction": (
            "このページは中位表示で一定のインプレッションがあるが、CTRが低い。"
            "独自分析・ファン視点の考察・最新情報を追加してコンテンツ密度を高めること。"
        ),
    },
    "meta_desc_weak": {
        "label": "メタディスクリプション訴求力不足",
        "condition": "CTR低 + 掲載順位5位以内（超上位なのにクリックされない）",
        "target_agents": ["metamon_kpop"],
        "instruction": (
            "このページは超上位表示なのにCTRが異常に低い。"
            "メタディスクリプションに具体的ベネフィット・疑問喚起・数字を含め、"
            "検索結果スニペットの訴求力を強化すること。"
        ),
    },
}


def _load_json(p: Path) -> dict | list:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _append_log(entry: dict):
    LOGS.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── CTR低下原因の自動分類 ──

def classify_low_ctr_pages() -> list[dict]:
    """low_ctr_pages.json を読み込み、原因を自動分類する。"""
    pages = _load_json(LOW_CTR_PATH)
    if not isinstance(pages, list):
        pages = pages.get("pages", []) if isinstance(pages, dict) else []

    classified = []
    for page in pages:
        ctr = page.get("ctr", 0)
        impressions = page.get("impressions", 0)
        position = page.get("position", 99)
        url = page.get("page", "")

        if impressions < IMPRESSIONS_MIN:
            continue
        if ctr >= CTR_LOW_THRESHOLD:
            continue

        # 原因分類（複数カテゴリに該当する場合あり）
        categories = []
        severity = "warning"

        if ctr < CTR_CRITICAL_THRESHOLD:
            severity = "critical"

        if position <= 5 and ctr < CTR_LOW_THRESHOLD:
            categories.append("meta_desc_weak")
        if position <= 10 and ctr < CTR_LOW_THRESHOLD:
            categories.append("title_weak")
        if position > 15:
            categories.append("seo_position_low")
        if 5 < position <= 15 and impressions >= 500:
            categories.append("content_thin")

        if not categories:
            categories.append("title_weak")  # デフォルト

        classified.append({
            "url": url,
            "ctr": ctr,
            "impressions": impressions,
            "position": position,
            "categories": categories,
            "severity": severity,
            "classified_at": NOW.isoformat(),
        })

    # CTRの低い順でソート
    classified.sort(key=lambda x: x["ctr"])
    return classified


def generate_agent_instructions(classified: list[dict]) -> dict[str, list[str]]:
    """分類結果からエージェント別の改善指示を生成する。"""
    agent_instructions: dict[str, list[str]] = {}

    for item in classified[:10]:  # 上位10件に絞る
        url = item["url"]
        ctr = item["ctr"]
        position = item["position"]
        impressions = item["impressions"]

        for cat_id in item["categories"]:
            cat = CTR_DECLINE_CATEGORIES.get(cat_id, {})
            for agent in cat.get("target_agents", []):
                if agent not in agent_instructions:
                    agent_instructions[agent] = []
                agent_instructions[agent].append(
                    f"- **{url}** (CTR: {ctr:.2%}, 順位: {position:.0f}, imp: {impressions:.0f})\n"
                    f"  原因: {cat.get('label', cat_id)} → {cat.get('instruction', '')}"
                )

    return agent_instructions


def inject_to_agents(agent_instructions: dict[str, list[str]], dry_run: bool = False) -> dict:
    """エージェントのAUTO-LEARNEDセクションにCTRフィードバックを注入する。"""
    # apply_learning_to_agents.py の仕組みを使って注入
    sys.path.insert(0, str(BASE / "lib"))
    from apply_learning_to_agents import _rewrite_auto_section, _log_applied, START_MARK, END_MARK

    results = {"injected": 0, "skipped": 0, "agents": []}

    for agent_name, instructions in agent_instructions.items():
        agent_path = AGENTS / f"{agent_name}.md"
        if not agent_path.exists():
            results["skipped"] += 1
            continue

        # 既存のAUTO-LEARNED内容を読む
        content = agent_path.read_text(encoding="utf-8")
        existing_block = ""
        pattern = re.compile(
            re.escape(START_MARK) + r"(.*?)" + re.escape(END_MARK),
            re.DOTALL,
        )
        m = pattern.search(content)
        if m:
            existing_block = m.group(1)

        # CTRフィードバックセクションを生成
        ctr_section = [
            "",
            "---",
            "",
            f"## 📉 CTR改善フィードバック（最終更新: {NOW.isoformat()}）",
            "",
            "**GSC実測データに基づく改善対象ページ。次回のリライト・新規記事で以下の傾向に注意。**",
            "",
        ]
        ctr_section.extend(instructions[:5])  # 最大5件
        ctr_section.append("")
        ctr_section.append("**対応**: リライト時は上記ページのタイトル・メタ・見出しを優先的に改善すること。")

        ctr_body = "\n".join(ctr_section)

        if dry_run:
            print(f"[DRY-RUN] {agent_name}: {len(instructions)}件の改善指示")
            results["agents"].append({"agent": agent_name, "count": len(instructions)})
            continue

        # 既存ブロックにCTRセクションを追加（既存CTRセクションは置換）
        ctr_marker = "## 📉 CTR改善フィードバック"
        if ctr_marker in existing_block:
            # 既存のCTRフィードバックセクションを置換
            parts = existing_block.split(ctr_marker)
            # ctr_marker以降の次の "## " または END_MARK までを置換
            before_ctr = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            # 次の ## セクションを探す
            next_section = re.search(r'\n## ', rest)
            if next_section:
                after_ctr = rest[next_section.start():]
            else:
                after_ctr = ""
            new_block = before_ctr.rstrip() + ctr_body + after_ctr
        else:
            new_block = existing_block.rstrip() + ctr_body

        changed, reason = _rewrite_auto_section(agent_path, new_block)
        if changed:
            results["injected"] += 1
            _log_applied(agent_name, "kpi_feedback_loop",
                         f"ctr_targets={len(instructions)}",
                         len(ctr_body), "applied")
        else:
            results["skipped"] += 1

        results["agents"].append({"agent": agent_name, "count": len(instructions), "changed": changed})

    return results


def save_ctr_classification(classified: list[dict]):
    """CTR分類結果をログに保存する。"""
    cat_counts = Counter()
    for item in classified:
        for cat in item["categories"]:
            cat_counts[cat] += 1

    entry = {
        "timestamp": NOW.isoformat(),
        "total_low_ctr_pages": len(classified),
        "critical_count": sum(1 for x in classified if x["severity"] == "critical"),
        "warning_count": sum(1 for x in classified if x["severity"] == "warning"),
        "category_distribution": dict(cat_counts),
        "top3_worst": [
            {"url": x["url"], "ctr": x["ctr"], "categories": x["categories"]}
            for x in classified[:3]
        ],
    }
    _append_log(entry)

    # 分類結果をJSONに保存（他システムから参照用）
    output_path = LOGS / "ctr_decline_classified.json"
    output_data = {
        "generated_at": NOW.isoformat(),
        "total": len(classified),
        "pages": classified[:20],
        "category_counts": dict(cat_counts),
    }
    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_stats():
    """CTRフィードバックの統計を表示する。"""
    if not FEEDBACK_LOG.exists():
        print("CTRフィードバックログなし")
        return

    records = []
    for line in FEEDBACK_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    if not records:
        print("記録なし")
        return

    print(f"\n=== CTRフィードバック統計 ===")
    print(f"  実行回数: {len(records)}")
    latest = records[-1]
    print(f"  最終実行: {latest.get('timestamp', '-')}")
    print(f"  低CTRページ数: {latest.get('total_low_ctr_pages', 0)}")
    print(f"  CRITICAL: {latest.get('critical_count', 0)}")
    print(f"  WARNING: {latest.get('warning_count', 0)}")
    cats = latest.get("category_distribution", {})
    if cats:
        print(f"\n  原因カテゴリ:")
        for cat, count in cats.items():
            label = CTR_DECLINE_CATEGORIES.get(cat, {}).get("label", cat)
            print(f"    {label}: {count}件")


def run(dry_run: bool = False) -> dict:
    """メイン実行。"""
    print(f"[kpi_feedback_loop] {NOW.isoformat()} 開始", file=sys.stderr)

    # 1. CTR低下ページを分類
    classified = classify_low_ctr_pages()
    print(f"  低CTRページ: {len(classified)}件", file=sys.stderr)

    if not classified:
        print("  低CTRページなし — スキップ", file=sys.stderr)
        return {"classified": 0, "injected": 0}

    # 2. 分類結果を保存
    save_ctr_classification(classified)

    # 3. エージェント別の改善指示を生成
    agent_instructions = generate_agent_instructions(classified)
    print(f"  改善指示生成: {sum(len(v) for v in agent_instructions.values())}件 → "
          f"{len(agent_instructions)}エージェント", file=sys.stderr)

    # 4. エージェントに注入
    inject_result = inject_to_agents(agent_instructions, dry_run=dry_run)
    print(f"  注入結果: injected={inject_result['injected']} "
          f"skipped={inject_result['skipped']}", file=sys.stderr)

    result = {
        "classified": len(classified),
        "critical": sum(1 for x in classified if x["severity"] == "critical"),
        "agents_updated": inject_result["injected"],
        "dry_run": dry_run,
    }
    print(f"[kpi_feedback_loop] 完了: {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KPIフィードバックループ v1.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        result = run(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
