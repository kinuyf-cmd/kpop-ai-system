#!/usr/bin/env python3
"""
title_ab_runner.py — タイトルA/Bテスト自動化（イルミーゼ管轄）

対象記事を自動選定し、代替タイトルを生成→WP適用→48h後にGSC CTRで勝敗判定する。

フロー:
  1. design  — GSCデータからテスト対象を選定し、代替タイトル案をClaude生成
  2. apply   — 勝ち候補タイトルをWPに適用（元タイトルをバックアップ）
  3. judge   — 48h以上経過した実験をGSC CTR差分で判定
  4. revert  — 負けタイトルを元に戻す
  5. report  — 実験状況レポート

Usage:
  python3 lib/title_ab_runner.py design --top 5          # 上位5記事でテスト設計
  python3 lib/title_ab_runner.py design --top 5 --dry-run
  python3 lib/title_ab_runner.py apply                   # pending実験を適用
  python3 lib/title_ab_runner.py judge                   # 48h経過分を判定
  python3 lib/title_ab_runner.py revert --id <exp_id>    # 特定実験をrevert
  python3 lib/title_ab_runner.py report                  # レポート表示
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
GMETRICS = BASE / "google_metrics"

TITLE_AB_LOG  = LOGS / "title_ab_test.jsonl"
GSC_METRICS   = LOGS / "gsc_metrics_latest.json"
ARTICLE_METRICS = LOGS / "article_metrics_latest.json"

WP_BASE      = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH_FILE = Path.home() / ".wp_auth"
JST = timezone(timedelta(hours=9))

# 判定閾値
CTR_WIN_THRESHOLD  = 0.003   # +0.3% で勝ち
CTR_LOSE_THRESHOLD = -0.002  # -0.2% で負け
MIN_IMPRESSIONS    = 50      # 判定に必要な最低表示回数
JUDGE_HOURS        = 48      # 判定までの最低経過時間


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
        "User-Agent": "kpop-title-ab/1.0",
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


def _get_test_candidates(top: int = 5) -> list[dict]:
    """GSCデータからA/Bテスト候補を選定（中CTR帯＝改善余地大）"""
    # growth_excludeを読み込み
    exclude_file = BASE / "config" / "growth_exclude_urls.json"
    excluded_urls = set()
    if exclude_file.exists():
        try:
            excluded_urls = set(json.loads(exclude_file.read_text()).get("urls", []))
        except Exception:
            pass

    # 既存テスト中のpost_idを除外
    existing = _load_jsonl(TITLE_AB_LOG)
    active_post_ids = {
        r["post_id"] for r in existing
        if r.get("status") in ("pending", "applied", "testing")
    }

    # メトリクスから候補を選定
    candidates = []
    metrics_file = ARTICLE_METRICS if ARTICLE_METRICS.exists() else GSC_METRICS
    if not metrics_file.exists():
        return []

    data = json.loads(metrics_file.read_text(encoding="utf-8"))

    # article_metrics_latest.json の場合
    if "merged_articles" in data:
        articles = data["merged_articles"]
    elif "gsc" in data and "articles" in data["gsc"]:
        articles = data["gsc"]["articles"]
    elif "pages" in data:
        articles = data["pages"]
    else:
        return []

    for a in articles:
        url = a.get("url", a.get("path", ""))
        impressions = a.get("gsc_impressions", a.get("impressions", 0))
        ctr = a.get("gsc_ctr", a.get("ctr", 0))
        clicks = a.get("gsc_clicks", a.get("clicks", 0))

        # フィルタ: 表示回数50以上、CTR 1-8%（改善余地あり）
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

    # CTRが中間帯（改善効果が大きい）＋表示回数順でソート
    candidates.sort(key=lambda x: (-x["impressions"], x["ctr"]))

    # WPからpost_id＋現タイトルを取得
    result = []
    for c in candidates[:top * 2]:  # 余分に取得してフィルタ
        slug = ""
        m = re.match(r"https://www\.kpopjournal\.tokyo/([^/?#]+)/?$", c["url"])
        if m:
            slug = m.group(1)
        if not slug:
            continue

        try:
            posts, err = _wp_request("GET", f"/posts?slug={slug}&_fields=id,title,link")
            if err or not posts or not isinstance(posts, list) or not posts:
                continue
            post = posts[0]
            post_id = post["id"]
            if post_id in active_post_ids:
                continue
            title = post.get("title", {}).get("rendered", "")
            if not title or len(title) < 10:
                continue
            c["post_id"] = post_id
            c["current_title"] = title
            result.append(c)
            if len(result) >= top:
                break
        except Exception:
            continue

    return result


def _generate_alt_title(current_title: str, url: str, ctr: float) -> str | None:
    """Claudeを使って代替タイトル案を生成"""
    prompt = f"""あなたはK-POPメディアのCTR最適化スペシャリストです。

以下の記事タイトルのCTR改善案を1つだけ出力してください。

【現タイトル】{current_title}
【現CTR】{ctr:.1%}
【URL】{url}

【改善ルール】
- 25〜40文字で出力（厳守）
- 数字・感情ワード・固有名詞のうち2つ以上を含める
- 事実と異なる誇張は禁止
- 「まとめ」「解説」「紹介」等の弱ワードを避ける
- 検索意図を維持しつつ、クリック衝動を高める

タイトル案のみを1行で出力（前置き・説明・引用符なし）:"""

    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            title = result.stdout.strip().split("\n")[0].strip()
            # 基本検証
            title = title.strip('"\'「」')
            if 10 <= len(title) <= 60 and title != current_title:
                return title
    except Exception:
        pass
    return None


def cmd_design(args):
    """テスト設計: 候補選定→代替タイトル生成→ログ記録"""
    print(f"[{_now_jst()[:16]}] タイトルA/Bテスト設計 (top={args.top})")

    candidates = _get_test_candidates(top=args.top)
    if not candidates:
        print("  テスト候補なし（対象記事不足またはGSCデータなし）")
        return

    print(f"  候補: {len(candidates)}記事")

    designed = 0
    for c in candidates:
        print(f"\n  --- post_id={c['post_id']} CTR={c['ctr']:.1%} impr={c['impressions']}")
        print(f"  現: {c['current_title'][:50]}")

        if args.dry_run:
            print(f"  [dry-run] タイトル生成スキップ")
            designed += 1
            continue

        alt = _generate_alt_title(c["current_title"], c["url"], c["ctr"])
        if not alt:
            print(f"  ⚠️ 代替タイトル生成失敗 → スキップ")
            continue

        print(f"  案: {alt}")

        record = {
            "experiment_id": f"title_ab_{datetime.now(JST).strftime('%Y%m%d_%H%M')}_{c['post_id']}",
            "post_id": c["post_id"],
            "url": c["url"],
            "original_title": c["current_title"],
            "alt_title": alt,
            "baseline_ctr": c["ctr"],
            "baseline_impressions": c["impressions"],
            "baseline_clicks": c["clicks"],
            "status": "pending",
            "designed_at": _now_jst(),
            "applied_at": None,
            "judged_at": None,
            "result_ctr": None,
            "delta_ctr": None,
            "verdict": None,
        }
        _append_jsonl(TITLE_AB_LOG, record)
        designed += 1
        print(f"  ✅ 記録完了: {record['experiment_id']}")

    print(f"\n設計完了: {designed}件")


def cmd_apply(args):
    """pending実験のタイトルをWPに適用"""
    experiments = _load_jsonl(TITLE_AB_LOG)
    applied = 0
    new_records = []

    for exp in experiments:
        if exp.get("status") != "pending":
            new_records.append(exp)
            continue

        post_id = exp["post_id"]
        alt_title = exp["alt_title"]

        if args.dry_run:
            print(f"  [dry-run] post={post_id} → {alt_title[:40]}")
            new_records.append(exp)
            applied += 1
            continue

        resp, err = _wp_request("POST", f"/posts/{post_id}", {"title": alt_title})
        if err:
            print(f"  ❌ post={post_id} 適用失敗: {err}")
            new_records.append(exp)
            continue

        exp["status"] = "testing"
        exp["applied_at"] = _now_jst()
        new_records.append(exp)
        applied += 1
        print(f"  ✅ post={post_id} タイトル変更完了 → 48h後に判定")

    # ファイル書き戻し
    if applied > 0 and not args.dry_run:
        with open(TITLE_AB_LOG, "w", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n適用: {applied}件")


def cmd_judge(args):
    """48h以上経過した実験をGSC CTRで判定"""
    experiments = _load_jsonl(TITLE_AB_LOG)
    now = datetime.now(JST)
    judged = 0
    new_records = []

    # 現在のGSCメトリクスを取得
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
                        "clicks": a.get("gsc_clicks", a.get("clicks", 0)),
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
            print(f"  ⏳ {exp['experiment_id']} 経過{elapsed:.0f}h（{JUDGE_HOURS}h未満）")
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
            exp["note"] = f"表示回数不足: {result_impressions} < {MIN_IMPRESSIONS}"
            new_records.append(exp)
            judged += 1
            print(f"  ⚠️ {exp['experiment_id']} データ不足 (impr={result_impressions})")
            continue

        delta_ctr = result_ctr - baseline_ctr
        exp["result_ctr"] = round(result_ctr, 4)
        exp["delta_ctr"] = round(delta_ctr, 4)
        exp["result_impressions"] = result_impressions
        exp["judged_at"] = _now_jst()

        if delta_ctr >= CTR_WIN_THRESHOLD:
            exp["status"] = "win"
            exp["verdict"] = f"CTR改善 +{delta_ctr:.4f} ({baseline_ctr:.1%} → {result_ctr:.1%})"
            icon = "✅"
        elif delta_ctr <= CTR_LOSE_THRESHOLD:
            exp["status"] = "lose"
            exp["verdict"] = f"CTR低下 {delta_ctr:.4f} ({baseline_ctr:.1%} → {result_ctr:.1%})"
            icon = "❌"
        else:
            exp["status"] = "neutral"
            exp["verdict"] = f"有意差なし {delta_ctr:+.4f}"
            icon = "➡️"

        new_records.append(exp)
        judged += 1
        print(f"  {icon} {exp['experiment_id']} {exp['verdict']}")

    # ファイル書き戻し
    if judged > 0:
        with open(TITLE_AB_LOG, "w", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 負け実験の自動revert
    for exp in new_records:
        if exp.get("status") == "lose" and not exp.get("reverted"):
            _revert_title(exp)

    print(f"\n判定完了: {judged}件")


def _revert_title(exp: dict):
    """負けタイトルを元に戻す"""
    post_id = exp["post_id"]
    original = exp["original_title"]
    resp, err = _wp_request("POST", f"/posts/{post_id}", {"title": original})
    if err:
        print(f"  ⚠️ post={post_id} revert失敗: {err}")
        return
    exp["reverted"] = True
    exp["reverted_at"] = _now_jst()
    print(f"  🔄 post={post_id} タイトルを元に戻しました")

    # ログ更新
    experiments = _load_jsonl(TITLE_AB_LOG)
    with open(TITLE_AB_LOG, "w", encoding="utf-8") as f:
        for r in experiments:
            if r.get("experiment_id") == exp["experiment_id"]:
                r["reverted"] = True
                r["reverted_at"] = _now_jst()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def cmd_revert(args):
    """特定実験を手動revert"""
    experiments = _load_jsonl(TITLE_AB_LOG)
    found = False
    for exp in experiments:
        if exp.get("experiment_id") == args.id:
            _revert_title(exp)
            found = True
            break
    if not found:
        print(f"❌ 実験 '{args.id}' が見つかりません")


def cmd_report(args):
    """実験状況レポート"""
    experiments = _load_jsonl(TITLE_AB_LOG)
    if not experiments:
        print("タイトルA/Bテスト実験データなし")
        return

    wins = [e for e in experiments if e.get("status") == "win"]
    loses = [e for e in experiments if e.get("status") == "lose"]
    testing = [e for e in experiments if e.get("status") == "testing"]
    pending = [e for e in experiments if e.get("status") == "pending"]
    neutral = [e for e in experiments if e.get("status") == "neutral"]

    print("=" * 60)
    print(f"  タイトルA/Bテスト レポート  {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"  総実験: {len(experiments)}件")
    print(f"  ✅ WIN: {len(wins)}  ❌ LOSE: {len(loses)}  ➡️ 中立: {len(neutral)}")
    print(f"  ⏳ テスト中: {len(testing)}  📋 未適用: {len(pending)}")
    print()

    if wins:
        total_delta = sum(w.get("delta_ctr", 0) for w in wins)
        print(f"  勝ちタイトルの平均CTR改善: +{total_delta/len(wins):.4f}")
        print()

    # 直近10件
    print("─── 直近の実験 ───")
    for exp in experiments[-10:]:
        icon = {"win": "✅", "lose": "❌", "testing": "⏳", "pending": "📋",
                "neutral": "➡️", "insufficient_data": "⚠️"}.get(exp.get("status"), "?")
        title = exp.get("alt_title", "")[:35]
        delta = exp.get("delta_ctr")
        delta_str = f" CTR{delta:+.4f}" if delta else ""
        print(f"  {icon} {exp.get('experiment_id', '?')[:35]}")
        print(f"     元: {exp.get('original_title', '')[:40]}")
        print(f"     案: {title}{delta_str}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="タイトルA/Bテスト自動化")
    sub = parser.add_subparsers(dest="command")

    p_design = sub.add_parser("design", help="テスト設計")
    p_design.add_argument("--top", type=int, default=5)
    p_design.add_argument("--dry-run", action="store_true")

    p_apply = sub.add_parser("apply", help="タイトル適用")
    p_apply.add_argument("--dry-run", action="store_true")

    sub.add_parser("judge", help="48h判定")

    p_revert = sub.add_parser("revert", help="手動revert")
    p_revert.add_argument("--id", required=True)

    sub.add_parser("report", help="レポート")

    args = parser.parse_args()
    dispatch = {
        "design": cmd_design, "apply": cmd_apply, "judge": cmd_judge,
        "revert": cmd_revert, "report": cmd_report,
    }
    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
