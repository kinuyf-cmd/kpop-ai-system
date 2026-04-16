#!/usr/bin/env python3
"""
自律改善エンジン

ルギアの週次戦略レポートから構造化アクションを抽出し、
config/auto_directives.json に保存する。
次回パイプライン実行時にエージェントのプロンプトへ自動注入される。

Usage:
  # ルギアのレポートからアクション抽出
  python3 lib/auto_improve.py extract < weekly_reviews/lugia_report.md

  # 現在のディレクティブ表示
  python3 lib/auto_improve.py show

  # タイトル学習のpendingを一括更新（measure_initial_performanceから呼ぶ）
  python3 lib/auto_improve.py update-titles

  # 特定エージェントへの指示を取得（パイプラインから呼ぶ）
  python3 lib/auto_improve.py directive --agent deoxys
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
DIRECTIVES_FILE = BASE / "config" / "auto_directives.json"
ERROR_PATTERNS_FILE = BASE / "config" / "error_patterns.json"
TITLE_PERF_FILE = BASE / "logs" / "title_performance.jsonl"
KPI_POSTS_FILE = BASE / "logs" / "kpi_posts.jsonl"
AUDIT_FEEDBACK_FILE = BASE / "logs" / "audit_feedback.jsonl"


def load_directives() -> dict:
    if DIRECTIVES_FILE.exists():
        return json.loads(DIRECTIVES_FILE.read_text())
    return {
        "updated_at": "",
        "focus_themes": [],
        "agent_directives": {},
        "stop_doing": [],
        "keep_doing": [],
        "winning_words": [],
    }


def save_directives(data: dict) -> None:
    DIRECTIVES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    DIRECTIVES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )


def extract_from_lugia(report: str) -> dict:
    """ルギアのレポートから構造化アクションを抽出"""
    directives = load_directives()

    # 重点テーマ抽出
    themes = []
    theme_section = re.search(
        r"(?:重点テーマ|来週の重点).*?\n((?:[-・\d].+\n?)+)", report
    )
    if theme_section:
        for line in theme_section.group(1).strip().split("\n"):
            line = line.strip().lstrip("-・0123456789. ")
            if line and len(line) > 2:
                themes.append(line[:80])
    directives["focus_themes"] = themes[:5]

    # エージェント改善指示
    agent_section = re.search(
        r"エージェント改善指示.*?\n((?:[|｜].+\n?)+)", report
    )
    if agent_section:
        for line in agent_section.group(1).strip().split("\n"):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 3 and cols[0] not in ("エージェント", "---", ""):
                agent_name = cols[0].lower().strip()
                # 日本語名→英語名変換
                name_map = {
                    "デオキシス": "deoxys", "メタモン": "metamon",
                    "ジラーチ": "jirachi", "アルセウス": "arceus",
                    "イーブイ": "eevee", "ミュウツー": "mewtwo",
                    "バタフリー": "butterfree", "ラプラス": "lapras",
                    "フシギバナ": "venusaur", "ゲンガー": "gengar",
                }
                agent_key = name_map.get(agent_name, agent_name)
                directive_text = cols[2] if len(cols) > 2 else cols[1]
                directives["agent_directives"][agent_key] = {
                    "problem": cols[1] if len(cols) > 2 else "",
                    "action": directive_text,
                    "set_at": datetime.now().strftime("%Y-%m-%d"),
                }

    # やめること
    stop_section = re.search(
        r"(?:やめること|減らすこと).*?\n((?:[-・].+\n?)+)", report
    )
    if stop_section:
        items = []
        for line in stop_section.group(1).strip().split("\n"):
            line = line.strip().lstrip("-・ ")
            if line:
                items.append(line[:100])
        directives["stop_doing"] = items[:5]

    # 続けること
    keep_section = re.search(
        r"(?:続けること|増やすこと).*?\n((?:[-・].+\n?)+)", report
    )
    if keep_section:
        items = []
        for line in keep_section.group(1).strip().split("\n"):
            line = line.strip().lstrip("-・ ")
            if line:
                items.append(line[:100])
        directives["keep_doing"] = items[:5]

    save_directives(directives)
    return directives


def get_agent_directive(agent: str) -> str:
    """特定エージェントへの改善指示を取得（パイプラインのプロンプトに注入用）"""
    directives = load_directives()

    parts = []

    # エージェント固有の指示
    ad = directives.get("agent_directives", {}).get(agent)
    if ad:
        parts.append(f"【週次改善指示（自動適用）】{ad['action']}")

    # 重点テーマ（全エージェント共通）
    themes = directives.get("focus_themes", [])
    if themes:
        parts.append("【今週の重点テーマ】" + "、".join(themes[:3]))

    # 勝ちワード（メタモン・イーブイ用）
    if agent in ("metamon", "eevee"):
        ww = directives.get("winning_words", [])
        if ww:
            parts.append("【勝ちワード】" + "、".join(ww[:5]))

    return "\n".join(parts)


def update_winning_words() -> None:
    """title_performance.jsonl の win タイトルから勝ちワードを更新"""
    strong_words = [
        "ついに", "完全", "衝撃", "レベチ", "まさか", "神", "電撃",
        "復活", "速報", "判明", "解禁", "決定", "炎上", "暴露",
    ]
    if not TITLE_PERF_FILE.exists():
        return

    from collections import Counter
    counter: Counter = Counter()
    for line in TITLE_PERF_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("result") != "win":
            continue
        title = r.get("title", "")
        for w in strong_words:
            if w in title:
                counter[w] += 1

    directives = load_directives()
    directives["winning_words"] = [w for w, _ in counter.most_common(10)]
    save_directives(directives)


def load_error_patterns() -> dict:
    """蓄積エラーパターンを読み込む"""
    if ERROR_PATTERNS_FILE.exists():
        try:
            return json.loads(ERROR_PATTERNS_FILE.read_text())
        except Exception:
            pass
    return {
        "updated_at": "",
        "patterns": {},          # pattern_key -> {count, last_seen, example, fix}
        "recurring_errors": [],  # 3回以上発生したエラー
        "resolved_errors": [],   # 自動修正に成功したエラー
        "agent_failure_counts": {},  # エージェント別エラー回数
    }


def save_error_patterns(data: dict) -> None:
    ERROR_PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    ERROR_PATTERNS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )


def audit_feedback(post_id: str, issues: list, fixes: list,
                   title: str, pipeline: str) -> None:
    """
    監査結果をフィードバックとして記録し、エラーパターンを更新する。
    - audit_feedback.jsonlに詳細記録
    - error_patterns.jsonにパターン蓄積
    - auto_directives.jsonにエージェント改善指示を書き込む
    """
    ts = datetime.now().isoformat()
    record = {
        "ts": ts,
        "post_id": post_id,
        "title": title[:80],
        "pipeline": pipeline,
        "issues": issues,
        "fixes": fixes,
        "issue_count": len(issues),
        "fix_count": len(fixes),
    }
    # audit_feedback.jsonlに追記
    AUDIT_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # エラーパターン分類と蓄積
    patterns = load_error_patterns()
    today = datetime.now().strftime("%Y-%m-%d")

    # エラーパターンのカテゴリ分類
    PATTERN_RULES = [
        # (正規表現, パターンキー, エージェント, 推奨アクション)
        (r"サムネイル.*不一致|thumbnail.*mismatch", "thumbnail_mismatch",
         "make_thumbnail", "サムネイル生成時にarticle_titleとthumb_textの整合性チェックを強化"),
        (r"BTSカテゴリ|誤.*カテゴリ|カテゴリ.*不一致", "wrong_category",
         "mewtwo", "カテゴリ割り当て時にタイトルと記事本文でアーティスト名を照合すること"),
        (r"ALT.*空|altテキスト.*空", "missing_alt_text",
         "pipeline", "アイキャッチアップロード時にALTテキストを必ず設定すること"),
        (r"メタ説明.*流用|メタ説明.*冒頭", "meta_desc_copied",
         "pipeline", "メタ説明はSEO最適化された独立した文章で設定すること（本文コピー禁止）"),
        (r"X投稿.*スキップ|プレフライト不合格", "x_post_failed",
         "persian", "X投稿テンプレートを更新し強ワード・疑問形を優先使用すること"),
        (r"条件付き承認|禁止表現", "arceus_format_violation",
         "arceus", "最終判定は✅ 投稿承認か❌ 投稿却下のみ。中間表現は絶対禁止"),
        (r"本文.*800文字未満|文字数.*短", "content_too_short",
         "deoxys", "記事本文は最低1500文字以上を確保すること"),
        (r"GSC.*登録できず|インデックス.*失敗", "gsc_index_failed",
         "pipeline", "GSCインデックス登録のリトライロジックを確認"),
        (r"アイキャッチ.*未設定", "no_featured_image",
         "pipeline", "投稿前にアイキャッチ画像の存在を必ず確認すること"),
        (r"ファクトチェック.*不明|架空|検証不能", "factcheck_issue",
         "jirachi", "未確認情報は記事核心に使用しないこと。速報でも一次ソース必須"),
    ]

    agent_failures = defaultdict(int, patterns.get("agent_failure_counts", {}))

    for issue in issues:
        matched = False
        for pattern_re, pattern_key, agent, fix_action in PATTERN_RULES:
            if re.search(pattern_re, issue):
                matched = True
                p = patterns["patterns"].setdefault(pattern_key, {
                    "count": 0, "last_seen": "", "example": "", "fix": fix_action, "agent": agent
                })
                p["count"] += 1
                p["last_seen"] = today
                p["example"] = issue[:100]
                p["fix"] = fix_action
                agent_failures[agent] += 1
                break
        if not matched:
            # 未分類エラー
            key = f"unknown_{abs(hash(issue)) % 10000}"
            p = patterns["patterns"].setdefault(key, {
                "count": 0, "last_seen": "", "example": "", "fix": "調査が必要", "agent": "unknown"
            })
            p["count"] += 1
            p["last_seen"] = today
            p["example"] = issue[:100]

    patterns["agent_failure_counts"] = dict(agent_failures)

    # 3回以上発生パターンを recurring_errors に昇格
    patterns["recurring_errors"] = [
        {"key": k, **v} for k, v in patterns["patterns"].items()
        if v.get("count", 0) >= 3
    ]

    # 修正済みを resolved_errors に記録
    for fix in fixes:
        patterns["resolved_errors"].append({
            "ts": today, "fix": fix[:100], "post_id": post_id
        })
    # 直近50件のみ保持
    patterns["resolved_errors"] = patterns["resolved_errors"][-50:]

    save_error_patterns(patterns)

    # auto_directives.jsonにエージェント別改善指示を反映
    directives = load_directives()
    for pattern_key, pdata in patterns["patterns"].items():
        if pdata.get("count", 0) >= 2:  # 2回以上発生したパターンを指示化
            agent = pdata.get("agent", "")
            if agent and agent not in ("pipeline", "unknown"):
                existing = directives["agent_directives"].get(agent, {})
                # より新しい指示で上書き（カウント多い方を優先）
                existing_count = existing.get("error_count", 0)
                if pdata["count"] > existing_count:
                    directives["agent_directives"][agent] = {
                        "problem": pdata.get("example", "")[:80],
                        "action": pdata["fix"],
                        "error_count": pdata["count"],
                        "set_at": today,
                        "source": "audit_feedback",
                    }
    save_directives(directives)


def get_improvement_report() -> str:
    """自己改善レポートを生成（improvement_engine.shから呼ぶ）"""
    patterns = load_error_patterns()
    directives = load_directives()

    lines = [f"## 自己改善レポート ({datetime.now().strftime('%Y-%m-%d %H:%M')})"]
    lines.append("")

    # 頻発エラー
    recurring = sorted(
        patterns.get("patterns", {}).items(),
        key=lambda x: x[1].get("count", 0), reverse=True
    )[:5]
    if recurring:
        lines.append("### 頻発エラーパターン（要対処）")
        for key, pdata in recurring:
            lines.append(f"- [{pdata['count']}回] {key}: {pdata.get('example','')[:60]}")
            lines.append(f"  → 対処: {pdata.get('fix','')}")
        lines.append("")

    # エージェント別エラー数
    af = patterns.get("agent_failure_counts", {})
    if af:
        lines.append("### エージェント別エラー発生数")
        for agent, count in sorted(af.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {agent}: {count}回")
        lines.append("")

    # 適用中の改善指示
    ad = directives.get("agent_directives", {})
    if ad:
        lines.append("### 適用中の改善指示")
        for agent, info in ad.items():
            src = info.get("source", "manual")
            cnt = info.get("error_count", "?")
            lines.append(f"- {agent} [{src}, {cnt}回エラー]: {info.get('action','')[:80]}")
        lines.append("")

    # 最近の修正実績
    resolved = patterns.get("resolved_errors", [])[-5:]
    if resolved:
        lines.append("### 直近の自動修正実績")
        for r in reversed(resolved):
            lines.append(f"- {r.get('ts','')}: {r.get('fix','')[:80]}")

    return "\n".join(lines)


def cmd_extract(args):
    report = sys.stdin.read()
    if not report.strip():
        print("Empty input", file=sys.stderr)
        sys.exit(1)
    result = extract_from_lugia(report)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_show(args):
    d = load_directives()
    if not d.get("updated_at"):
        print("ディレクティブなし（週次レビュー未実行）")
        return
    print(f"更新日時: {d['updated_at']}")
    if d.get("focus_themes"):
        print(f"重点テーマ: {', '.join(d['focus_themes'])}")
    if d.get("agent_directives"):
        print("エージェント指示:")
        for agent, info in d["agent_directives"].items():
            print(f"  {agent}: {info.get('action', '')}")
    if d.get("stop_doing"):
        print(f"やめること: {', '.join(d['stop_doing'])}")
    if d.get("winning_words"):
        print(f"勝ちワード: {', '.join(d['winning_words'])}")


def cmd_directive(args):
    result = get_agent_directive(args.agent)
    print(result)


def cmd_update_titles(args):
    update_winning_words()
    print("勝ちワード更新完了")


def cmd_audit_feedback(args):
    issues = [i.strip() for i in (args.issues or "").split("|") if i.strip()]
    fixes  = [f.strip() for f in (args.fixes  or "").split("|") if f.strip()]
    audit_feedback(
        post_id=args.post_id or "",
        issues=issues,
        fixes=fixes,
        title=args.title or "",
        pipeline=args.pipeline or "unknown",
    )
    print(f"フィードバック記録: issues={len(issues)}, fixes={len(fixes)}")


def cmd_report(args):
    print(get_improvement_report())


def cmd_errors(args):
    patterns = load_error_patterns()
    print(json.dumps(patterns, ensure_ascii=False, indent=2))


def cmd_learn(args):
    """X投稿スコア・title_performance・audit_feedbackを統合してagent指令を自動更新する。
    improvement_engine.shから毎日呼ばれる自律学習ループの中核。
    """
    now = datetime.now().isoformat()
    patterns = load_error_patterns()
    directives = load_directives()
    changed = []

    # ── 1. 蓄積エラーパターン → 未昇格の高頻度パターンを agent_directives に昇格 ──
    agent_dirs = directives.get("agent_directives", {})
    for pattern_name, info in patterns.get("patterns", {}).items():
        count = info.get("count", 0)
        agent = info.get("agent", "pipeline")
        fix = info.get("fix", "")
        if count >= 2 and fix and pattern_name not in patterns.get("recurring_errors", []):
            key = f"learn_{pattern_name}"
            if key not in agent_dirs:
                agent_dirs[key] = {
                    "action": fix,
                    "source": "auto_learn",
                    "error_count": count,
                    "promoted_at": now,
                }
                changed.append(f"  昇格: [{pattern_name}] → {agent}: {fix[:60]}")

    # ── 2. title_performance から win率の高いワード特性を抽出 ──
    if TITLE_PERF_FILE.exists():
        win_titles, lose_titles = [], []
        for line in TITLE_PERF_FILE.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                t = r.get("title", "")
                if r.get("result") == "win" and t:
                    win_titles.append(t)
                elif r.get("result") == "lose" and t:
                    lose_titles.append(t)
            except Exception:
                continue

        if len(win_titles) >= 3:
            import re as _re
            win_words: Counter = Counter()
            lose_words: Counter = Counter()
            for t in win_titles:
                for w in _re.findall(r'[A-Za-z]{3,}|[\u30A0-\u30FF\u4E00-\u9FFF]{2,4}', t):
                    win_words[w] += 1
            for t in lose_titles:
                for w in _re.findall(r'[A-Za-z]{3,}|[\u30A0-\u30FF\u4E00-\u9FFF]{2,4}', t):
                    lose_words[w] += 1
            # winに多くloseに少ないワード
            strong_words = [
                w for w, c in win_words.most_common(20)
                if c >= 2 and lose_words.get(w, 0) < c
            ]
            if strong_words:
                existing = set(directives.get("winning_words", []))
                new_words = [w for w in strong_words if w not in existing][:5]
                if new_words:
                    directives["winning_words"] = list(existing) + new_words
                    changed.append(f"  勝ちワード追加: {new_words}")

    # ── 3. audit_feedbackから繰り返し問題のstop_doingを更新 ──
    if AUDIT_FEEDBACK_FILE.exists():
        issue_counter: Counter = Counter()
        for line in AUDIT_FEEDBACK_FILE.read_text(errors="replace").splitlines()[-100:]:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                for issue in r.get("issues", []):
                    if issue:
                        # 先頭15字をキーに
                        issue_counter[issue[:15]] += 1
            except Exception:
                continue
        top_issues = [issue for issue, cnt in issue_counter.most_common(5) if cnt >= 2]
        existing_stop = set(directives.get("stop_doing", []))
        new_stops = [i for i in top_issues if i not in existing_stop]
        if new_stops:
            directives["stop_doing"] = list(existing_stop) + new_stops
            changed.append(f"  stop_doing追加: {new_stops}")

    # ── 保存 ──
    directives["agent_directives"] = agent_dirs
    directives["updated_at"] = now
    DIRECTIVES_FILE.parent.mkdir(parents=True, exist_ok=True)
    DIRECTIVES_FILE.write_text(json.dumps(directives, ensure_ascii=False, indent=2))

    if changed:
        print(f"✅ learn完了 ({len(changed)}件更新):")
        for c in changed:
            print(c)
    else:
        print("✅ learn完了 (新規学習なし)")


def cmd_inject(args):
    """蓄積されたerror_patternsを全エージェントのauto_directives.jsonに一括注入する。
    improvement_engine.sh の 'inject' ステップから呼ばれる。
    """
    patterns = load_error_patterns()
    directives = load_directives()
    agent_dirs = directives.get("agent_directives", {})
    now = datetime.now().isoformat()
    injected = 0

    for pattern_name, info in patterns.get("patterns", {}).items():
        count = info.get("count", 0)
        fix = info.get("fix", "")
        agent = info.get("agent", "pipeline")
        if count >= 2 and fix:
            key = f"inject_{pattern_name}"
            if key not in agent_dirs:
                agent_dirs[key] = {
                    "action": fix,
                    "source": "error_pattern_inject",
                    "error_count": count,
                    "promoted_at": now,
                }
                injected += 1

    directives["agent_directives"] = agent_dirs
    directives["updated_at"] = now
    DIRECTIVES_FILE.write_text(json.dumps(directives, ensure_ascii=False, indent=2))
    print(f"✅ inject完了: {injected}件のパターンをagent_directivesに注入")


def main():
    parser = argparse.ArgumentParser(description="自律改善エンジン")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("extract", help="ルギアレポートからアクション抽出 (stdin)")
    sub.add_parser("show", help="現在のディレクティブ表示")

    p_dir = sub.add_parser("directive", help="エージェント別指示取得")
    p_dir.add_argument("--agent", required=True)

    sub.add_parser("update-titles", help="勝ちワード更新")

    # 監査フィードバック
    p_fb = sub.add_parser("audit-feedback", help="監査結果をフィードバック記録")
    p_fb.add_argument("--post-id", default="")
    p_fb.add_argument("--issues", default="")    # "|"区切り
    p_fb.add_argument("--fixes", default="")     # "|"区切り
    p_fb.add_argument("--title", default="")
    p_fb.add_argument("--pipeline", default="unknown")

    # 改善レポート
    sub.add_parser("report", help="自己改善レポート表示")

    # エラーパターン表示
    sub.add_parser("errors", help="蓄積エラーパターン表示")

    # 自律学習（title_performance + audit_feedback → agent_directives更新）
    sub.add_parser("learn", help="X/titleスコア・監査結果からagent指令を自動学習")

    # エラーパターン一括注入
    sub.add_parser("inject", help="error_patternsをagent_directivesに一括注入")

    args = parser.parse_args()
    if args.command == "extract":
        cmd_extract(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "directive":
        cmd_directive(args)
    elif args.command == "update-titles":
        cmd_update_titles(args)
    elif args.command == "audit-feedback":
        cmd_audit_feedback(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "errors":
        cmd_errors(args)
    elif args.command == "learn":
        cmd_learn(args)
    elif args.command == "inject":
        cmd_inject(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
