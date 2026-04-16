#!/usr/bin/env python3
"""Pixel Lite – pipeline & agent activity CLI viewer.

Usage:
    python3 pixel_viewer.py            # latest pipeline.jsonl run
    python3 pixel_viewer.py --all      # all pipeline.jsonl runs
    python3 pixel_viewer.py --agents   # agent activity from all logs
    python3 pixel_viewer.py --posts    # today's published posts
    python3 pixel_viewer.py --full     # everything combined
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

LOGS = Path(__file__).parent / "logs"
JSONL_PATH = LOGS / "pipeline.jsonl"
KPI_POSTS  = LOGS / "kpi_posts.jsonl"
KPI_ERRORS = LOGS / "kpi_errors.jsonl"

# ── ANSI ──
G  = "\033[32m"   # green
R  = "\033[31m"   # red
Y  = "\033[33m"   # yellow
B  = "\033[34m"   # blue
C  = "\033[36m"   # cyan
M  = "\033[35m"   # magenta
W  = "\033[37m"   # white
DIM = "\033[2m"
BOLD = "\033[1m"
RST  = "\033[0m"

STATUS_COLOR = {
    "ok": G, "error": R, "skipped": Y,
    "approved": B, "rejected": R, "block": R,
}

# Agent name → display name mapping
AGENT_NAMES = {
    "deoxys": "デオキシス",   "metamon": "メタモン",
    "eevee": "イーブイ",      "jirachi": "ジラーチ",
    "arceus": "アルセウス",   "mewtwo": "ミュウツー",
    "butterfree": "バタフリー", "lapras": "ラプラス",
    "mimikyu": "ミミッキュ",  "wobbuffet": "ソーナンス",
    "venusaur": "フシギバナ",  "alakazam": "アラカザム",
    "gengar": "ゲンガー",
    "persian": "ペルシアン",
    "x_post_b": "X投稿B",     "wordpress_post": "WP投稿",
    "x_post": "X投稿A",
}

# ── Helpers ──

def colored(text: str, color: str) -> str:
    return f"{color}{text}{RST}"


def bar(value: int, max_val: int, width: int = 20) -> str:
    """Simple horizontal bar chart."""
    if max_val == 0:
        return DIM + "░" * width + RST
    filled = min(int(value / max_val * width), width)
    return G + "█" * filled + DIM + "░" * (width - filled) + RST


def fmt_status(status: str) -> str:
    c = STATUS_COLOR.get(status.lower(), "")
    return f"{c}{status.upper()}{RST}"


def fmt_size(b: int) -> str:
    if b == 0:
        return DIM + "  -" + RST
    if b < 1024:
        return f"{b:>5}B"
    return f"{b / 1024:>5.1f}K"


def fmt_duration_sec(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}m{s:02d}s"


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ── Section 1: pipeline.jsonl viewer ──

def load_pipeline_runs() -> dict[str, list[dict]]:
    if not JSONL_PATH.exists():
        return {}
    runs: dict[str, list[dict]] = {}
    for line in JSONL_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        runs.setdefault(entry["run_id"], []).append(entry)
    return runs


def print_pipeline_run(run_id: str, steps: list[dict]) -> None:
    try:
        times = [parse_ts(s["timestamp"]) for s in steps]
        duration = fmt_duration_sec((max(times) - min(times)).total_seconds())
    except (KeyError, ValueError):
        duration = "-"

    ok_count = sum(1 for s in steps if s["status"].lower() in ("ok", "approved"))
    total = len(steps)

    print(f"\n{BOLD}[RUN: {run_id}]{RST}  duration={duration}  "
          f"agents={colored(str(ok_count), G)}/{total}")
    print("─" * 60)

    prev_time = None
    for step in steps:
        name = step["step"]
        jp   = AGENT_NAMES.get(name, "")
        status = fmt_status(step["status"])
        size = fmt_size(step.get("size_bytes", 0))
        msg  = step.get("message", "")

        # Step-to-step duration
        try:
            cur_time = parse_ts(step["timestamp"])
            if prev_time:
                delta = (cur_time - prev_time).total_seconds()
                dt_str = f"{DIM}{delta:>5.0f}s{RST}"
            else:
                dt_str = f"{DIM}    -{RST}"
            prev_time = cur_time
        except (KeyError, ValueError):
            dt_str = f"{DIM}    -{RST}"

        disp_name = f"{name}" + (f" ({jp})" if jp else "")
        line = f"  {dt_str} {disp_name:<28} {status:<20} {size}"
        if msg:
            line += f"  {DIM}{msg}{RST}"
        print(line)
    print()


def show_pipeline(show_all: bool = False) -> None:
    runs = load_pipeline_runs()
    if not runs:
        print(f"{Y}No pipeline.jsonl data found.{RST}")
        return

    print(f"\n{BOLD}{'=' * 60}{RST}")
    print(f"{BOLD}  PIPELINE RUNS  (logs/pipeline.jsonl){RST}")
    print(f"{BOLD}{'=' * 60}{RST}")

    if show_all:
        for rid, steps in runs.items():
            print_pipeline_run(rid, steps)
    else:
        latest_id = list(runs.keys())[-1]
        print_pipeline_run(latest_id, runs[latest_id])


# ── Section 2: Agent activity from manual_run logs ──

# Patterns to extract agent steps from log lines
AGENT_STEP_RE = re.compile(
    r"(?:✓|❌|🚨)\s*\[([^\]]+)\]\s*(OK|ERROR|BLOCK|SKIPPED)"
    r"(?:\s*\((\d+)\s*bytes?\))?"
)
AGENT_HEADER_RE = re.compile(
    r"\[(\d+(?:[+\d]*)*/\d+)\]\s*(.+?)[:：]\s*(.+)"
)


def parse_manual_logs() -> list[dict]:
    """Parse all manual_run*.log files into structured runs."""
    runs = []
    for logfile in sorted(LOGS.glob("manual_run*.log")):
        run = {"file": logfile.name, "run_id": "", "pipeline": "", "agents": [], "result": ""}
        lines = logfile.read_text().splitlines()

        for line in lines:
            # Extract run_id
            if "実行ID:" in line:
                m = re.search(r"実行ID:\s*(\S+)", line)
                if m:
                    run["run_id"] = m.group(1).rstrip(" |")
            # Extract pipeline type
            if "パイプライン 開始" in line:
                if "戦略" in line:
                    run["pipeline"] = "strategy"
                else:
                    run["pipeline"] = "speed"
            # Extract agent step results
            m = AGENT_STEP_RE.search(line)
            if m:
                agent_name = m.group(1)
                status = m.group(2).lower()
                size = int(m.group(3)) if m.group(3) else 0
                run["agents"].append({
                    "name": agent_name, "status": status, "size": size
                })
            # Final result
            if "パイプライン完了" in line or "✅ 完了" in line:
                run["result"] = "ok"
            if "BLOCK:" in line or "stopped" in line.lower():
                run["result"] = "error"
            if "記事ID" in line:
                m2 = re.search(r"記事ID\s*[:：]\s*(\S*)", line)
                if m2 and m2.group(1):
                    run["post_id"] = m2.group(1)
            # WordPress投稿成功 = run成功
            if "WordPress投稿成功" in line or "投稿完了" in line:
                run["result"] = "ok"

        # エージェント全OK + 投稿IDあり → 成功とみなす
        if not run["result"] and run["agents"] and all(
            a["status"] == "ok" for a in run["agents"]
        ):
            if run.get("post_id"):
                run["result"] = "ok"
            else:
                run["result"] = "ok"  # agents all passed

        runs.append(run)
    return runs


def show_agents() -> None:
    runs = parse_manual_logs()
    if not runs:
        print(f"{Y}No manual_run logs found.{RST}")
        return

    print(f"\n{BOLD}{'=' * 60}{RST}")
    print(f"{BOLD}  AGENT ACTIVITY  (manual_run logs){RST}")
    print(f"{BOLD}{'=' * 60}{RST}")

    # Aggregate agent stats across all runs
    agent_stats: dict[str, dict] = {}  # name -> {ok, error, total_size, runs}

    for run in runs:
        run_status = colored("OK", G) if run["result"] == "ok" else colored("FAIL", R)
        pipe_label = colored(run["pipeline"], C) if run["pipeline"] else "-"
        print(f"\n  {BOLD}{run['file']}{RST}  id={run['run_id']}  "
              f"pipe={pipe_label}  result={run_status}")

        for ag in run["agents"]:
            name = ag["name"]
            status = fmt_status(ag["status"])
            size = fmt_size(ag["size"])
            print(f"    {name:<14} {status:<20} {size}")

            # Accumulate stats
            stats = agent_stats.setdefault(name, {"ok": 0, "error": 0, "total_size": 0, "runs": 0})
            stats["runs"] += 1
            if ag["status"] == "ok":
                stats["ok"] += 1
            else:
                stats["error"] += 1
            stats["total_size"] += ag["size"]

    # Summary scoreboard
    print(f"\n{BOLD}{'─' * 60}{RST}")
    print(f"{BOLD}  AGENT SCOREBOARD  (across all runs){RST}")
    print(f"{BOLD}{'─' * 60}{RST}")

    max_size = max((s["total_size"] for s in agent_stats.values()), default=1)
    for name, stats in sorted(agent_stats.items(), key=lambda x: x[1]["runs"], reverse=True):
        ok_rate = stats["ok"] / stats["runs"] * 100 if stats["runs"] else 0
        rate_color = G if ok_rate == 100 else (Y if ok_rate >= 50 else R)
        output_bar = bar(stats["total_size"], max_size, 15)
        total_k = f"{stats['total_size'] / 1024:.0f}K" if stats["total_size"] else "-"
        print(f"  {name:<14} runs={stats['runs']:>2}  "
              f"ok={rate_color}{ok_rate:>5.0f}%{RST}  "
              f"output={output_bar} {total_k:>6}")
    print()


# ── Section 3: Published posts summary ──

def show_posts() -> None:
    if not KPI_POSTS.exists():
        print(f"{Y}No kpi_posts.jsonl found.{RST}")
        return

    print(f"\n{BOLD}{'=' * 60}{RST}")
    print(f"{BOLD}  PUBLISHED POSTS  (kpi_posts.jsonl){RST}")
    print(f"{BOLD}{'=' * 60}{RST}")

    posts = []
    for line in KPI_POSTS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        posts.append(json.loads(line))

    if not posts:
        print("  No posts found.")
        return

    # Group by pipeline
    by_pipe: dict[str, list] = {}
    for p in posts:
        pipe = p.get("pipeline", "unknown")
        by_pipe.setdefault(pipe, []).append(p)

    total_chars = sum(p.get("char_count", 0) for p in posts)
    with_cta = sum(1 for p in posts if p.get("has_cta"))
    with_thumb = sum(1 for p in posts if p.get("has_thumbnail"))

    print(f"\n  Total: {BOLD}{len(posts)}{RST} posts  "
          f"chars={total_chars:,}  "
          f"CTA={colored(str(with_cta), G)}/{len(posts)}  "
          f"thumb={colored(str(with_thumb), G)}/{len(posts)}")

    for pipe, pp in by_pipe.items():
        print(f"\n  {colored(pipe, C)} ({len(pp)} posts):")
        # Show latest 5
        for p in pp[-5:]:
            pid = str(p.get("post_id", "?"))
            title = p.get("title", "")[:50]
            chars = p.get("char_count", 0)
            h2 = p.get("h2_count", 0)
            score = p.get("score", 0)
            cta = colored("CTA", G) if p.get("has_cta") else colored("---", DIM)
            thumb = colored("IMG", G) if p.get("has_thumbnail") else colored("---", DIM)
            print(f"    #{pid:<6} {chars:>5}字 h2={h2:<2} {cta} {thumb}  {DIM}{title}{RST}")
        if len(pp) > 5:
            print(f"    {DIM}... and {len(pp) - 5} more{RST}")
    print()


# ── Section 4: Errors ──

def show_errors() -> None:
    if not KPI_ERRORS.exists():
        return
    errors = []
    for line in KPI_ERRORS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        errors.append(json.loads(line))

    if not errors:
        return

    print(f"\n{BOLD}{'─' * 60}{RST}")
    print(f"{R}{BOLD}  ERRORS  ({len(errors)}){RST}")
    print(f"{BOLD}{'─' * 60}{RST}")
    for e in errors:
        ts = e.get("timestamp", "")[:19]
        msg = e.get("message", "")
        etype = e.get("error_type", "")
        print(f"  {DIM}{ts}{RST}  {R}{etype}{RST}  {msg}")
    print()


# ── Main ──

def main() -> None:
    args = set(sys.argv[1:])

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    full = "--full" in args

    if full or "--all" in args:
        show_pipeline(show_all=True)
    elif not args or args == {"--full"}:
        show_pipeline(show_all=False)
    if full or "--agents" in args:
        show_agents()
    if full or "--posts" in args:
        show_posts()
    if full:
        show_errors()

    if not args:
        print(f"{DIM}  Tip: --agents --posts --full --all{RST}")


if __name__ == "__main__":
    main()
