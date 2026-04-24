#!/usr/bin/env python3
"""
ab_test_manager.py — A/Bテスト完全自動化（Phase 4 / イルミーゼ強化）

既存title_ab_runner.pyのタイトルテストに加え、
サムネイル・メタディスクリプションのA/Bテストも自動化。
48h後のCTR比較で勝者を自動適用し、勝ちパターンをeevee/metamonに注入。

Usage:
  python3 lib/ab_test_manager.py design --type all --top 5
  python3 lib/ab_test_manager.py judge
  python3 lib/ab_test_manager.py inject-learnings
  python3 lib/ab_test_manager.py report
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
AGENTS_DIR = BASE / "agents"

AB_TEST_LOG = LOGS / "ab_test_full.jsonl"
ARTICLE_METRICS = LOGS / "article_metrics_latest.json"
GSC_METRICS = LOGS / "gsc_metrics_latest.json"
WINNING_PATTERNS = LOGS / "ab_winning_patterns.json"

WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH_FILE = Path.home() / ".wp_auth"
JST = timezone(timedelta(hours=9))

# 判定閾値
CTR_WIN_THRESHOLD = 0.003
CTR_LOSE_THRESHOLD = -0.002
MIN_IMPRESSIONS = 50
JUDGE_HOURS = 48


def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _get_auth_header():
    if not WP_AUTH_FILE.exists():
        return None, "AUTH_FAIL"
    try:
        content = WP_AUTH_FILE.read_text()
        m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
        if m:
            return m.group(1), None
        token = content.strip().split()[-1]
        return f"Basic {token}", None
    except Exception as e:
        return None, str(e)


def _wp_request(method, path, data=None):
    auth, err = _get_auth_header()
    if err:
        return None, err
    url = f"{WP_BASE}{path}"
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "kpop-ab-test/2.0",
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _append_jsonl(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _get_candidates(top: int = 5) -> list[dict]:
    """A/Bテスト候補を選定（CTR中間帯＋表示回数順）"""
    exclude_file = CONFIG / "growth_exclude_urls.json"
    excluded_urls = set()
    if exclude_file.exists():
        try:
            excluded_urls = set(json.loads(exclude_file.read_text()).get("urls", []))
        except Exception:
            pass

    existing = _load_jsonl(AB_TEST_LOG)
    active_post_ids = {
        r["post_id"] for r in existing
        if r.get("status") in ("pending", "testing")
    }

    metrics_file = ARTICLE_METRICS if ARTICLE_METRICS.exists() else GSC_METRICS
    if not metrics_file.exists():
        return []

    data = json.loads(metrics_file.read_text(encoding="utf-8"))
    if "merged_articles" in data:
        articles = data["merged_articles"]
    elif "gsc" in data and "articles" in data["gsc"]:
        articles = data["gsc"]["articles"]
    else:
        return []

    candidates = []
    for a in articles:
        url = a.get("url", a.get("path", ""))
        impressions = a.get("gsc_impressions", a.get("impressions", 0))
        ctr = a.get("gsc_ctr", a.get("ctr", 0))
        clicks = a.get("gsc_clicks", a.get("clicks", 0))

        if impressions < MIN_IMPRESSIONS:
            continue
        if ctr > 0.08 or ctr < 0.005:
            continue
        if url in excluded_urls:
            continue

        candidates.append({
            "url": url,
            "impressions": impressions,
            "ctr": round(ctr, 4),
            "clicks": clicks,
        })

    candidates.sort(key=lambda x: (-x["impressions"], x["ctr"]))

    result = []
    for c in candidates[:top * 2]:
        slug = ""
        m = re.match(r"https://www\.kpopjournal\.tokyo/([^/?#]+)/?$", c["url"])
        if m:
            slug = m.group(1)
        if not slug:
            continue

        try:
            posts, err = _wp_request("GET", f"/posts?slug={slug}&_fields=id,title,excerpt,link,featured_media")
            if err or not posts or not isinstance(posts, list) or not posts:
                continue
            post = posts[0]
            post_id = post["id"]
            if post_id in active_post_ids:
                continue
            title = post.get("title", {}).get("rendered", "")
            excerpt = post.get("excerpt", {}).get("rendered", "")
            featured_media = post.get("featured_media", 0)
            if not title or len(title) < 10:
                continue
            c["post_id"] = post_id
            c["current_title"] = title
            c["current_excerpt"] = _strip_html(excerpt)
            c["featured_media"] = featured_media
            result.append(c)
            if len(result) >= top:
                break
        except Exception:
            continue

    return result


def _strip_html(html: str) -> str:
    """HTMLタグを除去"""
    return re.sub(r"<[^>]+>", "", html).strip()


def _generate_variant(variant_type: str, current: str, url: str, ctr: float) -> str | None:
    """Claudeでバリアント生成"""
    prompts = {
        "meta_description": f"""K-POPメディアのメタディスクリプション改善スペシャリストとして、
以下のメタディスクリプションのCTR改善案を1つ出力。

【現メタディスクリプション】{current}
【現CTR】{ctr:.1%}
【URL】{url}

【ルール】
- 110〜130文字（厳守）
- 検索意図に応える具体的な情報を含む
- 好奇心を刺激する表現（「実は…」「〜の真相」等）
- 数字を含める
- 記事の核心を匂わせつつ全容は明かさない

メタディスクリプション案のみ1行で出力:""",

        "thumbnail_copy": f"""K-POPメディアのサムネイルコピー改善スペシャリストとして、
以下のサムネイル用2行コピーのCTR改善案を出力。

【現在のタイトル（参考）】{current}
【現CTR】{ctr:.1%}
【URL】{url}

【ルール】
- 1行目: アーティスト名やキーワード（10文字以内）
- 2行目: 感情を刺激するキャッチコピー（15文字以内）
- 数字・感情語・固有名詞を含める

JSON形式で出力（これだけ）:
{{"line1": "1行目", "line2": "2行目"}}""",
    }

    prompt = prompts.get(variant_type)
    if not prompt:
        return None

    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip().split("\n")[0].strip()
            output = output.strip('"\'')
            if len(output) >= 10:
                return output
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_design(args):
    """テスト設計: サムネイル・メタディスクリプション含むA/Bテスト"""
    test_types = []
    if args.type == "all":
        test_types = ["meta_description", "thumbnail_copy"]
    else:
        test_types = [args.type]

    print(f"[{_now_jst()[:16]}] A/Bテスト設計 (type={args.type}, top={args.top})")

    candidates = _get_candidates(top=args.top)
    if not candidates:
        print("  テスト候補なし")
        return

    print(f"  候補: {len(candidates)}記事 × {len(test_types)}タイプ")
    designed = 0

    for c in candidates:
        for test_type in test_types:
            print(f"\n  --- [{test_type}] post_id={c['post_id']} CTR={c['ctr']:.1%}")

            if test_type == "meta_description":
                current = c.get("current_excerpt", "")
                if not current or len(current) < 20:
                    print(f"    ⚠️ メタディスクリプションが短すぎ → スキップ")
                    continue
            elif test_type == "thumbnail_copy":
                current = c.get("current_title", "")
            else:
                continue

            if args.dry_run:
                print(f"    [dry-run] バリアント生成スキップ")
                designed += 1
                continue

            variant = _generate_variant(test_type, current, c["url"], c["ctr"])
            if not variant:
                print(f"    ⚠️ バリアント生成失敗 → スキップ")
                continue

            print(f"    案: {variant[:60]}")

            record = {
                "experiment_id": f"ab_{test_type}_{datetime.now(JST).strftime('%Y%m%d_%H%M')}_{c['post_id']}",
                "test_type": test_type,
                "post_id": c["post_id"],
                "url": c["url"],
                "original_value": current[:200],
                "variant_value": variant[:200],
                "baseline_ctr": c["ctr"],
                "baseline_impressions": c["impressions"],
                "status": "pending",
                "designed_at": _now_jst(),
                "applied_at": None,
                "judged_at": None,
                "result_ctr": None,
                "delta_ctr": None,
                "verdict": None,
            }
            _append_jsonl(AB_TEST_LOG, record)
            designed += 1
            print(f"    ✅ 記録: {record['experiment_id']}")

    print(f"\n設計完了: {designed}件")


def cmd_apply(args):
    """pending実験を適用"""
    experiments = _load_jsonl(AB_TEST_LOG)
    applied = 0
    new_records = []

    for exp in experiments:
        if exp.get("status") != "pending":
            new_records.append(exp)
            continue

        test_type = exp.get("test_type", "")
        post_id = exp["post_id"]
        variant = exp["variant_value"]

        if test_type == "meta_description":
            # WPのexcerpt + AIOSEO metaを更新
            update_data = {
                "excerpt": variant,
                "meta": {"aioseo_description": variant},
            }
        elif test_type == "thumbnail_copy":
            # サムネイルコピーはログのみ（make_thumbnail.pyが次回使用）
            exp["status"] = "testing"
            exp["applied_at"] = _now_jst()
            exp["note"] = "サムネコピーは次回サムネ再生成時に適用"
            new_records.append(exp)
            applied += 1
            print(f"  ✅ [{test_type}] post={post_id} コピー記録済み")
            continue
        else:
            new_records.append(exp)
            continue

        if args.dry_run:
            print(f"  [dry-run] [{test_type}] post={post_id}")
            new_records.append(exp)
            applied += 1
            continue

        resp, err = _wp_request("POST", f"/posts/{post_id}", update_data)
        if err:
            print(f"  ❌ [{test_type}] post={post_id} 適用失敗: {err}")
            new_records.append(exp)
            continue

        exp["status"] = "testing"
        exp["applied_at"] = _now_jst()
        new_records.append(exp)
        applied += 1
        print(f"  ✅ [{test_type}] post={post_id} 適用完了")

    if applied > 0 and not args.dry_run:
        with open(AB_TEST_LOG, "w", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n適用: {applied}件")


def cmd_judge(args):
    """48h経過した実験を判定"""
    experiments = _load_jsonl(AB_TEST_LOG)
    now = datetime.now(JST)
    judged = 0
    new_records = []

    current_metrics = {}
    if ARTICLE_METRICS.exists():
        try:
            data = json.loads(ARTICLE_METRICS.read_text(encoding="utf-8"))
            for a in data.get("merged_articles", []) + data.get("gsc", {}).get("articles", []):
                url = a.get("url", "")
                if url:
                    current_metrics[url] = {
                        "ctr": a.get("gsc_ctr", a.get("ctr", 0)),
                        "impressions": a.get("gsc_impressions", a.get("impressions", 0)),
                    }
        except Exception:
            pass

    for exp in experiments:
        if exp.get("status") != "testing":
            new_records.append(exp)
            continue

        applied_at = exp.get("applied_at", "")
        if not applied_at:
            new_records.append(exp)
            continue

        try:
            applied_dt = datetime.fromisoformat(applied_at)
        except Exception:
            new_records.append(exp)
            continue

        elapsed = (now - applied_dt).total_seconds() / 3600
        if elapsed < JUDGE_HOURS:
            new_records.append(exp)
            continue

        url = exp.get("url", "")
        current = current_metrics.get(url, {})
        result_ctr = current.get("ctr", 0)
        result_impressions = current.get("impressions", 0)
        baseline_ctr = exp.get("baseline_ctr", 0)

        if result_impressions < MIN_IMPRESSIONS:
            exp["status"] = "insufficient_data"
            exp["judged_at"] = _now_jst()
            new_records.append(exp)
            judged += 1
            continue

        delta_ctr = result_ctr - baseline_ctr
        exp["result_ctr"] = round(result_ctr, 4)
        exp["delta_ctr"] = round(delta_ctr, 4)
        exp["judged_at"] = _now_jst()

        if delta_ctr >= CTR_WIN_THRESHOLD:
            exp["status"] = "win"
            exp["verdict"] = f"CTR改善 +{delta_ctr:.4f}"
            icon = "✅"
        elif delta_ctr <= CTR_LOSE_THRESHOLD:
            exp["status"] = "lose"
            exp["verdict"] = f"CTR低下 {delta_ctr:.4f}"
            icon = "❌"
            # 負けは元に戻す
            if exp["test_type"] == "meta_description":
                _wp_request("POST", f"/posts/{exp['post_id']}", {
                    "excerpt": exp["original_value"],
                    "meta": {"aioseo_description": exp["original_value"]},
                })
                exp["reverted"] = True
        else:
            exp["status"] = "neutral"
            exp["verdict"] = f"有意差なし {delta_ctr:+.4f}"
            icon = "➡️"

        new_records.append(exp)
        judged += 1
        print(f"  {icon} [{exp['test_type']}] {exp['experiment_id'][:40]} {exp['verdict']}")

    if judged > 0:
        with open(AB_TEST_LOG, "w", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n判定完了: {judged}件")


def cmd_inject_learnings(args):
    """勝ちパターンをeevee/metamonのagentファイルに自動注入"""
    experiments = _load_jsonl(AB_TEST_LOG)
    wins = [e for e in experiments if e.get("status") == "win"]

    if not wins:
        print("勝ちパターンなし → 注入スキップ")
        return

    # 勝ちパターン分析
    patterns = {
        "title": [],
        "meta_description": [],
        "thumbnail_copy": [],
    }
    for w in wins:
        test_type = w.get("test_type", "title")
        patterns[test_type].append({
            "variant": w.get("variant_value", w.get("alt_title", "")),
            "delta_ctr": w.get("delta_ctr", 0),
            "original": w.get("original_value", w.get("original_title", "")),
        })

    # 勝ちパターンJSONを保存
    pattern_summary = {}
    for ptype, items in patterns.items():
        if items:
            items.sort(key=lambda x: -x.get("delta_ctr", 0))
            pattern_summary[ptype] = {
                "win_count": len(items),
                "avg_delta_ctr": round(sum(i["delta_ctr"] for i in items) / len(items), 4),
                "top_variants": [i["variant"][:60] for i in items[:5]],
            }

    pattern_summary["updated_at"] = _now_jst()
    WINNING_PATTERNS.write_text(
        json.dumps(pattern_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # eevee.mdに勝ちパターン注入
    _inject_to_agent("eevee.md", patterns, "title")
    # metamon_kpop.mdに注入
    _inject_to_agent("metamon_kpop.md", patterns, "meta_description")

    print(f"\n勝ちパターン注入完了: {sum(len(v) for v in patterns.values())}件")


def _inject_to_agent(agent_file: str, patterns: dict, focus_type: str):
    """agentファイルのAUTO-LEARNEDセクションに勝ちパターンを追記"""
    agent_path = AGENTS_DIR / agent_file
    if not agent_path.exists():
        print(f"  ⚠️ {agent_file} が見つかりません")
        return

    content = agent_path.read_text(encoding="utf-8")
    items = patterns.get(focus_type, [])
    if not items:
        return

    # A/Bテスト勝ちパターンセクション
    section = "\n\n## A/Bテスト勝ちパターン（自動注入）\n"
    section += f"更新: {date.today().isoformat()} / {len(items)}件のWINから抽出\n\n"
    for i, item in enumerate(items[:5], 1):
        section += f"- 勝ち案{i}: 「{item['variant'][:50]}」(CTR +{item['delta_ctr']:.4f})\n"
        section += f"  元: 「{item['original'][:50]}」\n"

    # 既存セクションを置換
    marker_start = "## A/Bテスト勝ちパターン（自動注入）"
    marker_end_pattern = r"\n## (?!A/Bテスト勝ちパターン)"

    if marker_start in content:
        # 既存セクションを探して置換
        start_idx = content.index(marker_start)
        # 前の改行を含める
        if start_idx > 0 and content[start_idx - 1] == "\n":
            start_idx -= 1
        if start_idx > 0 and content[start_idx - 1] == "\n":
            start_idx -= 1

        rest = content[content.index(marker_start) + len(marker_start):]
        m = re.search(marker_end_pattern, rest)
        if m:
            end_idx = content.index(marker_start) + len(marker_start) + m.start()
            content = content[:start_idx] + section + content[end_idx:]
        else:
            content = content[:start_idx] + section
    else:
        content += section

    agent_path.write_text(content, encoding="utf-8")
    print(f"  ✅ {agent_file} に{focus_type}勝ちパターン注入")


def cmd_report(args):
    """A/Bテスト統合レポート"""
    experiments = _load_jsonl(AB_TEST_LOG)
    if not experiments:
        print("A/Bテストデータなし")
        return

    by_type = {}
    for e in experiments:
        t = e.get("test_type", "title")
        if t not in by_type:
            by_type[t] = {"win": 0, "lose": 0, "neutral": 0, "testing": 0, "pending": 0, "total": 0}
        by_type[t]["total"] += 1
        status = e.get("status", "pending")
        if status in by_type[t]:
            by_type[t][status] += 1

    print("=" * 60)
    print(f"  A/Bテスト統合レポート  {_now_jst()[:16]}")
    print("=" * 60)

    for t, stats in by_type.items():
        win_rate = stats["win"] / max(stats["win"] + stats["lose"] + stats["neutral"], 1) * 100
        print(f"\n  [{t}] 総実験: {stats['total']}件")
        print(f"    ✅ WIN: {stats['win']}  ❌ LOSE: {stats['lose']}  ➡️ 中立: {stats['neutral']}")
        print(f"    ⏳ テスト中: {stats['testing']}  📋 未適用: {stats['pending']}")
        print(f"    勝率: {win_rate:.0f}%")

    # 全体の勝ちパターン
    wins = [e for e in experiments if e.get("status") == "win"]
    if wins:
        avg_delta = sum(w.get("delta_ctr", 0) for w in wins) / len(wins)
        print(f"\n  全体勝ちパターン平均CTR改善: +{avg_delta:.4f}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="A/Bテスト完全自動化")
    sub = parser.add_subparsers(dest="command")

    p_design = sub.add_parser("design")
    p_design.add_argument("--type", default="all", choices=["all", "meta_description", "thumbnail_copy"])
    p_design.add_argument("--top", type=int, default=5)
    p_design.add_argument("--dry-run", action="store_true")

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--dry-run", action="store_true")

    sub.add_parser("judge")
    sub.add_parser("inject-learnings")
    sub.add_parser("report")

    args = parser.parse_args()
    dispatch = {
        "design": cmd_design, "apply": cmd_apply, "judge": cmd_judge,
        "inject-learnings": cmd_inject_learnings, "report": cmd_report,
    }
    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
