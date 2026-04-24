#!/usr/bin/env python3
"""
session_learning_logger.py
オーナー×Claudeのセッションで行われた改善を全社員に自動学習させるシステム

使い方：
  python3 lib/session_learning_logger.py --log "改善内容" --type "design" --lesson "なぜ" --action "どう直した" --prevention "再発防止"
  python3 lib/session_learning_logger.py --session-report
"""

import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = SCRIPT_DIR / "logs"
AGENTS_DIR = SCRIPT_DIR / "agents"

# 学習タイプと関連エージェントのマッピング
LEARNING_TYPE_AGENTS = {
    "design": ["showers", "sandaas", "buustaa"],
    "quality": ["gardevoir_hook_critic", "arceus", "darkrai", "gaadi"],
    "content": ["eevee", "metamon_kpop", "butterfree", "deoxys_kpop"],
    "system": ["porygon_z", "mewtwo", "lugia", "snorlax"],
    "revenue": ["snorlax", "porygon"],
    "seo": ["lapras", "illumise", "persian"],
    "sns": ["mimikyu", "persian", "wobbuffet"],
    "pipeline": ["gaadi", "eevee", "gardevoir_hook_critic", "metamon_kpop", "kairyu_kpop"],
    "all": None,
}


def log_session_learning(
    content: str,
    learning_type: str,
    lesson: str,
    action_taken: str,
    prevention: str = "",
):
    """改善内容を関連エージェントに学習させる"""

    timestamp = datetime.now().isoformat()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 1. session_learnings.jsonl に記録
    learning_entry = {
        "timestamp": timestamp,
        "date": date_str,
        "type": learning_type,
        "content": content,
        "lesson": lesson,
        "action_taken": action_taken,
        "prevention": prevention,
        "source": "owner_session",
    }

    session_log = LOGS_DIR / "session_learnings.jsonl"
    with open(session_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(learning_entry, ensure_ascii=False) + "\n")

    # 2. 関連エージェントの AUTO-LEARNED セクションに追記
    agents_to_update = LEARNING_TYPE_AGENTS.get(learning_type)
    if agents_to_update is None:
        agents_to_update = [f.stem for f in AGENTS_DIR.glob("*.md")]

    updated_agents = []
    new_entry = (
        f"\n### [{date_str}] セッション学習: {content[:50]}\n"
        f"- **問題**: {content}\n"
        f"- **原因**: {lesson}\n"
        f"- **対応**: {action_taken}\n"
    )
    if prevention:
        new_entry += f"- **再発防止**: {prevention}\n"

    for agent_name in agents_to_update:
        agent_file = AGENTS_DIR / f"{agent_name}.md"
        if not agent_file.exists():
            continue
        text = agent_file.read_text(encoding="utf-8")
        if "<!-- AUTO-LEARNED END -->" in text:
            text = text.replace(
                "<!-- AUTO-LEARNED END -->",
                new_entry + "<!-- AUTO-LEARNED END -->",
            )
            agent_file.write_text(text, encoding="utf-8")
            updated_agents.append(agent_name)

    # 3. winning_patterns.jsonl にも記録
    patterns_log = LOGS_DIR / "winning_patterns.jsonl"
    pattern_entry = {
        "timestamp": timestamp,
        "type": f"session_learning_{learning_type}",
        "result": "win",
        "lesson": lesson,
        "action_taken": action_taken,
        "prevention": prevention,
    }
    with open(patterns_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(pattern_entry, ensure_ascii=False) + "\n")

    print(f"✅ 学習完了: {len(updated_agents)}名に反映")
    if updated_agents:
        display = updated_agents[:5]
        suffix = f"... 他{len(updated_agents)-5}名" if len(updated_agents) > 5 else ""
        print(f"   対象: {', '.join(display)}{suffix}")

    return updated_agents


def generate_session_report():
    """本日のセッション学習レポートを生成・Discord送信"""

    date_str = datetime.now().strftime("%Y-%m-%d")
    session_log = LOGS_DIR / "session_learnings.jsonl"

    if not session_log.exists():
        print("セッション学習記録なし")
        return

    today_learnings = []
    for line in session_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("date") == date_str:
                today_learnings.append(entry)
        except json.JSONDecodeError:
            pass

    if not today_learnings:
        print(f"本日({date_str})のセッション学習なし")
        return

    msg = f"📚 **セッション学習レポート** {date_str}\n"
    msg += f"本日 {len(today_learnings)}件の改善を学習しました\n\n"

    for i, lr in enumerate(today_learnings, 1):
        msg += f"**{i}. {lr['content'][:50]}**\n"
        msg += f"   原因: {lr['lesson'][:80]}\n"
        msg += f"   対応: {lr['action_taken'][:80]}\n"
        if lr.get("prevention"):
            msg += f"   防止: {lr['prevention'][:80]}\n"
        msg += "\n"

    # Discord送信
    webhook = ""
    wh_file = SCRIPT_DIR / "config" / "discord_webhooks.json"
    if wh_file.exists():
        try:
            data = json.loads(wh_file.read_text())
            for key in ("daily_ceo_report", "alert_summary"):
                urls = data.get(key, [])
                if urls:
                    webhook = urls[0] if isinstance(urls, list) else urls
                    break
        except Exception:
            pass
    if not webhook:
        fallback = Path.home() / ".kpop_discord_webhook"
        if fallback.exists():
            webhook = fallback.read_text().strip()

    if webhook:
        from urllib.request import Request, urlopen

        body = json.dumps({"content": msg[:2000]}).encode()
        req = Request(webhook, data=body, headers={"Content-Type": "application/json"})
        try:
            urlopen(req, timeout=10)
            print("✅ Discord送信完了")
        except Exception as e:
            print(f"⚠️ Discord送信失敗: {e}")
    else:
        print("⚠️ Discord webhook未設定")

    print(msg)
    return today_learnings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="セッション学習ロガー")
    parser.add_argument("--log", help="改善内容")
    parser.add_argument("--type", default="all", help="学習タイプ")
    parser.add_argument("--lesson", default="", help="なぜ改善したか")
    parser.add_argument("--action", default="", help="どう直したか")
    parser.add_argument("--prevention", default="", help="再発防止策")
    parser.add_argument("--session-report", action="store_true")
    args = parser.parse_args()

    if args.session_report:
        generate_session_report()
    elif args.log:
        log_session_learning(
            content=args.log,
            learning_type=args.type,
            lesson=args.lesson,
            action_taken=args.action,
            prevention=args.prevention,
        )
    else:
        parser.print_help()
