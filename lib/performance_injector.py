#!/usr/bin/env python3
"""
performance_injector.py — 記事パフォーマンス→エージェント事前注入 v1.0

【責務】
  パイプ���イン実行**前**にwinning_patterns/title_performance/arceus_rejections
  のデータを集約し、各エージェントが参照できる��造化ディレクティブを生成する。

  既存の auto_directives.json (事後学習) とは��なり、
  パイプライン開始時に最新パフォーマンスデータを直接注入する。

【注入先エージェント】
  deoxys_kpop   : 勝ちパターン（カテゴリ/タイト���構造/公開時間帯）
  metamon_kpop  : CTRスコア上位タイトル・タイトル要素分析
  persian       : X投稿の勝ちパターン（フック/ハッシュタグ/時間帯）
  mewtwo        : 全体パフォーマンスサマリ（戦略判断用）
  gardevoir_hook_critic : CTR予測精度の自己校正データ

【使い方】
  # パイプライン開始時に呼び出し
  PERF_DIRECTIVE=$(python3 lib/performance_injector.py directive --agent deoxys)

  # 全エージェント分のディレクティブを生成＆ファイル保存
  python3 lib/performance_injector.py generate-all

  # サマリ表示
  python3 lib/performance_injector.py summary
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

WIN_PATTERNS = LOGS / "winning_patterns.jsonl"
TITLE_PERF = LOGS / "title_performance.jsonl"
KPI_POSTS = LOGS / "kpi_posts.jsonl"
REJECTION_LOG = LOGS / "arceus_rejections.jsonl"
REJECTION_PATTERNS = LOGS / "arceus_rejection_patterns.json"
AUTO_DIRECTIVES = CONFIG / "auto_directives.json"
PERF_DIRECTIVES = LOGS / "performance_directives.json"  # 生成したディレクティブを保存

JST = timezone(timedelta(hours=9))
LOOKBACK_DAYS = 14


def _load_jsonl(path: Path, max_lines: int = 0) -> list:
    if not path.exists():
        return []
    records = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if max_lines:
            lines = lines[-max_lines:]
        for line in lines:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── データ集約 ──────────────────────────────────────────────────

def collect_performance_data(days: int = LOOKBACK_DAYS) -> dict:
    """直近N日のパフォーマンスデータを集約"""
    cutoff = (datetime.now(JST) - timedelta(days=days)).isoformat()

    # winning_patterns
    patterns = [p for p in _load_jsonl(WIN_PATTERNS) if p.get("recorded_at", "") >= cutoff]

    # 勝ち/負け分類
    wins = [p for p in patterns if p.get("result") == "win"]
    loses = [p for p in patterns if p.get("result") == "lose"]

    # カテゴリ別勝率
    cat_stats = defaultdict(lambda: {"win": 0, "lose": 0, "pending": 0})
    for p in patterns:
        cat = p.get("category", "other")
        res = p.get("result", "pending")
        cat_stats[cat][res] = cat_stats[cat].get(res, 0) + 1

    # タイトル要素の勝ち分析
    win_elements = Counter()
    lose_elements = Counter()
    for p in wins:
        if p.get("has_number"):
            win_elements["数字あり"] += 1
        if p.get("has_proper_noun"):
            win_elements["固有名詞あり"] += 1
        if p.get("has_emotion_word"):
            win_elements["感情語あり"] += 1
        if p.get("has_contrast"):
            win_elements["対比構造あり"] += 1
    for p in loses:
        if p.get("has_number"):
            lose_elements["数字あり"] += 1
        if p.get("has_proper_noun"):
            lose_elements["固有名詞あり"] += 1
        if p.get("has_emotion_word"):
            lose_elements["感情語あり"] += 1
        if p.get("has_contrast"):
            lose_elements["対比構造あり"] += 1

    # 公開時間帯の勝率
    hour_stats = defaultdict(lambda: {"win": 0, "lose": 0})
    for p in patterns:
        h = p.get("publish_hour")
        res = p.get("result", "pending")
        if h is not None and res in ("win", "lose"):
            hour_stats[h][res] += 1

    # 勝ちタイトル上位（CTR or eval_72h）
    scored = [(p, p.get("eval_72h") or p.get("eval_48h") or p.get("eval_24h") or 0)
              for p in patterns if p.get("result") == "win"]
    scored.sort(key=lambda x: -x[1])
    top_titles = [
        {"title": p["title"][:60], "score": s, "category": p.get("category", "")}
        for p, s in scored[:5]
    ]

    # X投稿パフォーマンス
    x_posted = [p for p in patterns if p.get("x_posted_status") == "posted"]
    x_hooks = [p.get("x_hook_score", 0) for p in x_posted if p.get("x_hook_score")]

    # タイトル長の傾向
    win_lengths = [p.get("title_length", 0) for p in wins if p.get("title_length")]
    lose_lengths = [p.get("title_length", 0) for p in loses if p.get("title_length")]

    # arceus却下パターン
    rejection_data = _load_json(REJECTION_PATTERNS)

    return {
        "period_days": days,
        "total_articles": len(patterns),
        "wins": len(wins),
        "loses": len(loses),
        "win_rate": len(wins) / max(len(wins) + len(loses), 1),
        "category_stats": dict(cat_stats),
        "win_elements": dict(win_elements),
        "lose_elements": dict(lose_elements),
        "hour_stats": dict(hour_stats),
        "top_titles": top_titles,
        "avg_win_title_length": round(sum(win_lengths) / max(len(win_lengths), 1), 1),
        "avg_lose_title_length": round(sum(lose_lengths) / max(len(lose_lengths), 1), 1),
        "x_posted_count": len(x_posted),
        "avg_x_hook_score": round(sum(x_hooks) / max(len(x_hooks), 1), 1),
        "rejection_patterns": rejection_data,
    }


# ── エージェント別ディレクティブ生成 ────────────────────────────

def generate_deoxys_directive(perf: dict) -> str:
    """deoxys向け: 勝ちパターン＋却下回避指示"""
    lines = [
        "【パフォーマンス学習ディレクティブ（自動注入）】",
        f"直近{perf['period_days']}日: {perf['total_articles']}記事中 勝ち{perf['wins']} 負け{perf['loses']} (勝率{perf['win_rate']:.0%})",
    ]

    # 勝ちカテゴリ
    cat_stats = perf.get("category_stats", {})
    if cat_stats:
        best_cats = sorted(
            cat_stats.items(),
            key=lambda kv: kv[1].get("win", 0) / max(kv[1].get("win", 0) + kv[1].get("lose", 0), 1),
            reverse=True,
        )[:3]
        cat_str = ", ".join(f"{c}(勝率{v['win']}/{v['win']+v['lose']})" for c, v in best_cats if v.get("win", 0) + v.get("lose", 0) > 0)
        if cat_str:
            lines.append(f"勝ちカテゴリ: {cat_str}")

    # タイトル要素
    we = perf.get("win_elements", {})
    if we:
        elements = sorted(we.items(), key=lambda x: -x[1])
        lines.append(f"勝ちタイトル要素: {', '.join(f'{k}({v})' for k,v in elements[:4])}")

    # 最適タ���トル長
    if perf.get("avg_win_title_length"):
        lines.append(f"勝ちタイトル平均長: {perf['avg_win_title_length']}文字 (負け: {perf.get('avg_lose_title_length', '-')}文字)")

    # 勝ちタイトル例
    top = perf.get("top_titles", [])
    if top:
        lines.append("最近の勝ちタイトル例:")
        for t in top[:3]:
            lines.append(f"  - [{t['category']}] {t['title']}")

    # 却下パターン回避
    rp = perf.get("rejection_patterns", {})
    if rp and rp.get("total_rejections", 0) > 0:
        cats = rp.get("category_counts", {})
        if cats:
            lines.append(f"直近却下パターン({rp['total_rejections']}件): {', '.join(f'{k}({v})' for k,v in list(cats.items())[:3])}")
            lines.append("上記パターンの再発を回避すること。")

    return "\n".join(lines)


def generate_metamon_directive(perf: dict) -> str:
    """metamon向け: CTRリライト用の勝ちパターン"""
    lines = [
        "【CTRリライト学習ディレクティブ（自動注入）】",
        f"直近勝率: {perf['win_rate']:.0%} ({perf['wins']}/{perf['wins']+perf['loses']})",
    ]

    we = perf.get("win_elements", {})
    le = perf.get("lose_elements", {})
    if we:
        lines.append("勝ちタイトルの共通要素:")
        for k, v in sorted(we.items(), key=lambda x: -x[1]):
            lose_count = le.get(k, 0)
            lines.append(f"  - {k}: 勝ち{v}回 / 負け{lose_count}回")

    if perf.get("avg_win_title_length"):
        lines.append(f"推奨タイトル長: {perf['avg_win_title_length']:.0f}文字前後")

    top = perf.get("top_titles", [])
    if top:
        lines.append("参考: 高スコアタイトル")
        for t in top[:3]:
            lines.append(f"  - {t['title']} (score={t['score']})")

    return "\n".join(lines)


def generate_persian_directive(perf: dict) -> str:
    """persian向け: X投稿の勝ちパターン"""
    lines = [
        "【X投稿学習ディレクティブ（自動注入）】",
        f"X投稿済み: {perf.get('x_posted_count', 0)}件",
    ]
    if perf.get("avg_x_hook_score"):
        lines.append(f"平均フックスコア: {perf['avg_x_hook_score']}")

    # 公開時間帯
    hour_stats = perf.get("hour_stats", {})
    if hour_stats:
        best_hours = sorted(
            hour_stats.items(),
            key=lambda kv: kv[1].get("win", 0) / max(kv[1].get("win", 0) + kv[1].get("lose", 0), 1),
            reverse=True,
        )[:3]
        hours_str = ", ".join(f"{h}時台" for h, _ in best_hours)
        lines.append(f"勝ち時間帯: {hours_str}")

    we = perf.get("win_elements", {})
    if we:
        top_elem = max(we, key=we.get)
        lines.append(f"最強要素: {top_elem} → フックに必ず含めること")

    return "\n".join(lines)


def generate_mewtwo_directive(perf: dict) -> str:
    """mewtwo向け: 全体パフォーマンスサマリ"""
    lines = [
        "【パフォーマンスサマリ（自動注入）】",
        f"直近{perf['period_days']}日: 勝率{perf['win_rate']:.0%} ({perf['wins']}勝/{perf['loses']}敗/{perf['total_articles']}総記事)",
    ]

    cat_stats = perf.get("category_stats", {})
    if cat_stats:
        lines.append("カテゴリ別:")
        for cat, stats in sorted(cat_stats.items()):
            w = stats.get("win", 0)
            l = stats.get("lose", 0)
            total = w + l
            if total > 0:
                lines.append(f"  - {cat}: {w}/{total} ({w/total:.0%})")

    rp = perf.get("rejection_patterns", {})
    if rp and rp.get("total_rejections", 0) > 0:
        lines.append(f"arceus却下: {rp['total_rejections']}件 (リビジ���ン成功: {rp.get('revision_success_count', 0)})")

    return "\n".join(lines)


def generate_gardevoir_directive(perf: dict) -> str:
    """gardevoir向け: CTR予測精度の校正データ"""
    lines = [
        "【CTR予測校正ディレクティブ（自動注入）】",
        f"実績勝率: {perf['win_rate']:.0%}",
    ]
    we = perf.get("win_elements", {})
    if we:
        lines.append(f"実績で勝つタイトル要素: {', '.join(f'{k}' for k in sorted(we, key=we.get, reverse=True)[:3])}")
        lines.append("上記要素を含むタイトルを過度にHARD_FAILしていないか自己検証すること。")

    return "\n".join(lines)


# ── ディレクティブマップ ──────────────────────────────────────

AGENT_GENERATORS = {
    "deoxys": generate_deoxys_directive,
    "metamon": generate_metamon_directive,
    "persian": generate_persian_directive,
    "mewtwo": generate_mewtwo_directive,
    "gardevoir_hook_critic": generate_gardevoir_directive,
}


# ── CLI ──────────────────────────────────────────────────────────

def cmd_directive(args):
    """特定エージェントのディレクティブを標準出力"""
    agent = args.agent
    gen = AGENT_GENERATORS.get(agent)
    if not gen:
        print(f"(未対応エージェント: {agent})", file=sys.stderr)
        sys.exit(1)
    perf = collect_performance_data()
    print(gen(perf))


def cmd_generate_all(args):
    """全エージェントのディレクティブを生成して保存"""
    perf = collect_performance_data()
    directives = {}
    for agent, gen in AGENT_GENERATORS.items():
        directives[agent] = gen(perf)
        print(f"  [{agent}] {len(directives[agent])}文字")

    output = {
        "generated_at": datetime.now(JST).isoformat(),
        "period_days": perf["period_days"],
        "total_articles": perf["total_articles"],
        "win_rate": perf["win_rate"],
        "directives": directives,
    }
    PERF_DIRECTIVES.parent.mkdir(parents=True, exist_ok=True)
    PERF_DIRECTIVES.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  保存: {PERF_DIRECTIVES}")
    print(f"  パイプライ��から読み込み:")
    print(f"    DEOXYS_PERF=$(python3 lib/performance_injector.py directive --agent deoxys)")


def cmd_summary(args):
    """パフォーマンスサマリを表示"""
    perf = collect_performance_data()

    print(f"\n{'='*60}")
    print(f"  記事パフォーマンスサマリ（直近{perf['period_days']}日）")
    print(f"{'='*60}")
    print(f"  総記事数: {perf['total_articles']}")
    print(f"  勝ち: {perf['wins']} / 負け: {perf['loses']} / 勝率: {perf['win_rate']:.0%}")
    print()

    cat_stats = perf.get("category_stats", {})
    if cat_stats:
        print("  カテゴリ別勝率:")
        for cat, stats in sorted(cat_stats.items()):
            w = stats.get("win", 0)
            l = stats.get("lose", 0)
            p = stats.get("pending", 0)
            total = w + l
            rate = f"{w/total:.0%}" if total > 0 else "-"
            print(f"    {cat:<12} 勝ち{w} 負け{l} 待機{p} 勝率{rate}")
        print()

    we = perf.get("win_elements", {})
    if we:
        print("  タイトル要素（勝ち記事）:")
        for k, v in sorted(we.items(), key=lambda x: -x[1]):
            lose_v = perf.get("lose_elements", {}).get(k, 0)
            print(f"    {k}: 勝ち{v} / 負け{lose_v}")
        print()

    if perf.get("avg_win_title_length"):
        print(f"  タイトル長: 勝ち平均{perf['avg_win_title_length']}文字 / 負け平均{perf.get('avg_lose_title_length', '-')}文字")

    top = perf.get("top_titles", [])
    if top:
        print(f"\n  勝ちタイトル TOP-{len(top)}:")
        for i, t in enumerate(top, 1):
            print(f"    {i}. [{t['category']}] {t['title']} (score={t['score']})")

    rp = perf.get("rejection_patterns", {})
    if rp and rp.get("total_rejections", 0) > 0:
        print(f"\n  arceus却��統計:")
        print(f"    総却下: {rp['total_rejections']}件")
        print(f"    リビジョン成功: {rp.get('revision_success_count', 0)} / 失敗: {rp.get('revision_fail_count', 0)}")
        cats = rp.get("category_counts", {})
        if cats:
            print(f"    カテゴリ: {', '.join(f'{k}({v})' for k,v in cats.items())}")

    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="記事パフォーマンス→エージェント事前注入 v1.0")
    sub = parser.add_subparsers(dest="command")

    p_dir = sub.add_parser("directive", help="エージェント別ディレクティブ��力")
    p_dir.add_argument("--agent", required=True, choices=list(AGENT_GENERATORS.keys()))

    sub.add_parser("generate-all", help="全エージェント分を生成＆保存")
    sub.add_parser("summary", help="パフォーマンスサマリ表示")

    args = parser.parse_args()

    if args.command == "directive":
        cmd_directive(args)
    elif args.command == "generate-all":
        cmd_generate_all(args)
    elif args.command == "summary":
        cmd_summary(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
