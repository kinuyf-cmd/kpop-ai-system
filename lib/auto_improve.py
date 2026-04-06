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
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
DIRECTIVES_FILE = BASE / "config" / "auto_directives.json"
TITLE_PERF_FILE = BASE / "logs" / "title_performance.jsonl"
KPI_POSTS_FILE = BASE / "logs" / "kpi_posts.jsonl"


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


def main():
    parser = argparse.ArgumentParser(description="自律改善エンジン")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("extract", help="ルギアレポートからアクション抽出 (stdin)")
    sub.add_parser("show", help="現在のディレクティブ表示")

    p_dir = sub.add_parser("directive", help="エージェント別指示取得")
    p_dir.add_argument("--agent", required=True)

    sub.add_parser("update-titles", help="勝ちワード更新")

    args = parser.parse_args()
    if args.command == "extract":
        cmd_extract(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "directive":
        cmd_directive(args)
    elif args.command == "update-titles":
        cmd_update_titles(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
