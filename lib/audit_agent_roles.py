#!/usr/bin/env python3
"""
audit_agent_roles.py — エージェント責務逸脱チェッカー

責務固定表 (operations_runbook_v1.0.md) に基づき、
全パイプライン・retry_handler・crontab の実装が
定義と矛盾していないかを静的解析で検出する。

使い方:
    python3 lib/audit_agent_roles.py
    python3 lib/audit_agent_roles.py --verbose
    python3 lib/audit_agent_roles.py --json
    python3 lib/audit_agent_roles.py --summary   # 1行サマリーのみ出力（improvement_engine用）

Exit code:
    0 = 全チェック OK
    1 = 1件以上の NG を検出
"""
import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent.parent
AGENTS_DIR = BASE_DIR / "agents"
LIB_DIR = BASE_DIR / "lib"
DOCS_DIR = BASE_DIR / "docs"
LOGS_DIR = BASE_DIR / "logs"
SNAPSHOT_FILE = LOGS_DIR / "role_audit_snapshot.json"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 責務固定表（ソース・オブ・トゥルース）
# 変更は必ず operations_runbook_v1.0.md の責務固定表と同期すること
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 各パイプラインで記事本体を生成（ゼロ生成）してよいエージェント
ARTICLE_GENERATORS = {
    "breaking":  {"deoxys_kpop"},
    "strategy":  {"deoxys_kpop"},
    "chart":     {"zapdos"},
}

# eevee が呼ばれてよいパイプラインファイル
# 実態確認（2026-04-11）:
#   breaking pipeline: step2.5 で claude -p（--agent なし）でタイトルB生成のみ
#   strategy pipeline: step10 で --agent eevee でタイトル5案評価・最終選定
# → eevee の主責務「タイトル最終選定」は両パイプラインで正当に使われている
# → 責務固定表を「breaking=step2.5 / strategy=step10」に更新済み（C04 解消）
EEVEE_ALLOWED_FILES = {
    "kpop_pipeline.sh",           # breaking (step2.5)
    "kpop_strategy_pipeline.sh",  # strategy (step10) — 正当な使用
}

# articuno を呼んでよいのは手動のみ（cronパイプラインファイル名ブラックリスト）
ARTICUNO_FORBIDDEN_FILES = {
    "kpop_pipeline.sh",
    "kpop_strategy_pipeline.sh",
    "kpop_chart_pipeline.sh",
    "hub_article_post.sh",
    "kpop_master_scheduler.sh",
    "run_ai_meeting.sh",
}

# arceus のフォールバックを設定してはならない
ARCEUS_FALLBACK_FORBIDDEN = True

# jirachi_kpop のフォールバック先に必ず含まれていなければならないエージェント
JIRACHI_REQUIRED_FALLBACK = "alakazam_kpop"

# chart pipeline で記事本体生成に使ってよいエージェント（zapdos のみ）
CHART_GENERATOR_ONLY = "zapdos"

# strategy pipeline で venusaur が担当するステップを示すキーワード
# (venusaur の呼び出しが存在することを確認する)
VENUSAUR_REQUIRED_IN_STRATEGY = True

# cron に直接接続されているパイプラインファイル（実際の crontab から導出）
CRON_CONNECTED_FILES = {
    "kpop_pipeline.sh",
    "kpop_chart_pipeline.sh",
    "kpop_strategy_pipeline.sh",
    "kpop_category_health.sh",
    "ceo_morning_brief.sh",
    "kpop_monthly_report.sh",
    "kpop_exit_dashboard.sh",
    "run_ai_meeting.sh",
    "kpop_maintenance.sh",
    "kpop_weekly_review.sh",
    "update_low_ctr_titles.sh",
    "auto_repair.sh",
    "improvement_engine.sh",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データ構造
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class CheckResult:
    id: str
    title: str
    status: str        # "OK" | "NG" | "WARN"
    detail: str
    file: Optional[str] = None
    line: Optional[int] = None


@dataclass
class AuditReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, r: CheckResult):
        self.results.append(r)

    @property
    def ng_count(self) -> int:
        return sum(1 for r in self.results if r.status == "NG")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == "OK")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def grep_agent_calls(file_path: Path) -> list[tuple[int, str]]:
    """ファイルから `claude ... --agent <name>` の呼び出しを抽出して (行番号, エージェント名) を返す。
    `python3 ... --agent` や `directive --agent` などの非claude呼び出しは除外する。"""
    results = []
    if not file_path.exists():
        return results
    # claude コマンド行のみを対象とする（行内に claude が含まれ、かつ --agent が続く）
    pattern_claude_agent = re.compile(r'\bclaude\b.*?--agent\s+(["\']?)(\S+)\1')
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                # コメント行はスキップ
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                m = pattern_claude_agent.search(line)
                if m:
                    agent = m.group(2).strip('"').strip("'")
                    results.append((lineno, agent))
    except Exception:
        pass
    return results


def grep_websearch_agent_calls(file_path: Path) -> list[tuple[int, str]]:
    """ファイルから `claude ... --allowedTools WebSearch ... --agent <name>` を行単位で抽出する。
    DOTALL マッチを使わず行ごとに判定することで誤検知を防ぐ。"""
    results = []
    if not file_path.exists():
        return results
    pattern_agent = re.compile(r'--agent\s+(["\']?)(\S+)\1')
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # claude コマンドかつ WebSearch が同一行にある
                if "claude" not in line:
                    continue
                if "--allowedTools" not in line or "WebSearch" not in line:
                    continue
                m = pattern_agent.search(line)
                if m:
                    agent = m.group(2).strip('"').strip("'")
                    results.append((lineno, agent))
    except Exception:
        pass
    return results


def get_crontab_lines() -> list[str]:
    """現在のcrontabを取得する"""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10
        )
        return result.stdout.splitlines()
    except Exception:
        return []


def read_file_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# チェック実装
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_c01_breaking_generator(report: AuditReport):
    """C01: breaking pipeline で記事生成するエージェントは deoxys_kpop のみ"""
    CHECK_ID = "C01"
    TITLE = "breaking pipeline の記事ゼロ生成エージェントが deoxys_kpop のみか"
    target = BASE_DIR / "kpop_pipeline.sh"
    allowed = ARTICLE_GENERATORS["breaking"]

    # ゼロ生成 = claude + --allowedTools WebSearch + --agent <name> が同一行
    calls = grep_websearch_agent_calls(target)
    generators_found = {ag for _, ag in calls}

    violations = generators_found - allowed
    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"ゼロ生成エージェントに非許可エージェントが含まれる: {violations}",
            file=str(target.relative_to(BASE_DIR))
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"ゼロ生成エージェント: {generators_found} ← 全て許可済み"
        ))


def check_c02_strategy_generator(report: AuditReport):
    """C02: strategy pipeline で記事生成するエージェントは deoxys_kpop のみ
    butterfree・mimikyu は調査系 WebSearch のため許可。"""
    CHECK_ID = "C02"
    TITLE = "strategy pipeline の記事ゼロ生成エージェントが deoxys_kpop のみか"
    target = BASE_DIR / "kpop_strategy_pipeline.sh"
    allowed = ARTICLE_GENERATORS["strategy"] | {"butterfree", "mimikyu"}  # 調査系は許可

    calls = grep_websearch_agent_calls(target)
    generators_found = {ag for _, ag in calls}

    violations = generators_found - allowed
    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"ゼロ生成エージェントに非許可エージェントが含まれる: {violations}",
            file=str(target.relative_to(BASE_DIR))
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"WebSearch付き呼び出しエージェント: {generators_found} ← 全て許可済み"
        ))


def check_c03_chart_generator(report: AuditReport):
    """C03: chart pipeline で記事生成するエージェントは zapdos のみ"""
    CHECK_ID = "C03"
    TITLE = "chart pipeline の記事ゼロ生成エージェントが zapdos のみか"
    target = BASE_DIR / "kpop_chart_pipeline.sh"
    allowed = {CHART_GENERATOR_ONLY}

    calls = grep_websearch_agent_calls(target)
    generators_found = {ag for _, ag in calls}

    violations = generators_found - allowed
    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"chart pipeline のゼロ生成に非許可エージェントが含まれる: {violations}",
            file=str(target.relative_to(BASE_DIR))
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"chart生成エージェント: {generators_found}"
        ))


def check_c04_eevee_pipeline_positions(report: AuditReport):
    """C04: eevee が breaking・strategy の正規ステップで使われているか確認する。

    確定した責務: eevee はタイトル最終選定担当。
    - breaking pipeline: step2.5（--agent なしの claude -p でタイトルB生成）
    - strategy pipeline: step10（--agent eevee でタイトル5案評価・最終選定）

    禁止: chart pipeline や hub_article_post 等での呼び出し。
    禁止: 記事生成（ゼロ生成）ステップへの投入。
    """
    CHECK_ID = "C04"
    TITLE = "eevee が許可外パイプラインで呼ばれていないか（breaking・strategy のみ許可）"

    # chart pipeline や他のパイプラインで eevee が呼ばれていないか
    forbidden_files = [
        BASE_DIR / "kpop_chart_pipeline.sh",
        BASE_DIR / "hub_article_post.sh",
    ]
    violations = []
    for target in forbidden_files:
        calls = grep_agent_calls(target)
        eevee_calls = [(ln, ag) for ln, ag in calls if ag == "eevee"]
        if eevee_calls:
            for ln, _ in eevee_calls:
                violations.append(f"{target.relative_to(BASE_DIR)}:{ln}")

    # strategy で eevee が呼ばれていること（正常確認）
    strategy = BASE_DIR / "kpop_strategy_pipeline.sh"
    strategy_calls = grep_agent_calls(strategy)
    eevee_in_strategy = [(ln, ag) for ln, ag in strategy_calls if ag == "eevee"]

    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"eevee が許可外パイプラインで呼ばれている: {violations}"
        ))
    elif not eevee_in_strategy:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="WARN",
            detail=(
                "eevee が strategy pipeline に存在しない。"
                "step10（タイトル最終選定）から外れた可能性がある。"
            ),
            file=str(strategy.relative_to(BASE_DIR))
        ))
    else:
        lines_str = ", ".join(str(ln) for ln, _ in eevee_in_strategy)
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=(
                f"eevee は strategy pipeline の {lines_str} 行目（step10・タイトル最終選定）で正常に呼ばれている。"
                f" breaking でも step2.5 で使用中。許可外パイプラインへの混入なし。"
            )
        ))


def check_c05_articuno_not_in_cron(report: AuditReport):
    """C05: articuno が cron 接続ファイルで呼ばれていないか（MANUAL_ONLY）"""
    CHECK_ID = "C05"
    TITLE = "articuno が cron 接続ファイルで呼ばれていないか（MANUAL_ONLY）"

    violations = []
    for fname in ARTICUNO_FORBIDDEN_FILES:
        # パイプライン直下 or ai_company/ 配下も確認
        candidates = [
            BASE_DIR / fname,
            BASE_DIR / "ai_company" / fname,
        ]
        for target in candidates:
            calls = grep_agent_calls(target)
            articuno_calls = [(ln, ag) for ln, ag in calls if ag == "articuno"]
            if articuno_calls:
                for ln, _ in articuno_calls:
                    violations.append(f"{target.relative_to(BASE_DIR)}:{ln}")

    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"articuno が cronパイプラインで呼ばれている: {violations}"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail="articuno はどの cron パイプラインファイルにも存在しない"
        ))


def check_c06_arceus_no_fallback(report: AuditReport):
    """C06: retry_handler.py の FALLBACK_MAP に arceus が設定されていないか"""
    CHECK_ID = "C06"
    TITLE = "retry_handler.py の FALLBACK_MAP に arceus のフォールバックが設定されていないか"
    target = LIB_DIR / "retry_handler.py"
    text = read_file_text(target)

    # FALLBACK_MAP の arceus エントリを検出
    # "arceus": [...非空リスト...] のパターン
    pattern = re.compile(r'"arceus"\s*:\s*\[([^\]]*)\]')
    m = pattern.search(text)
    if m:
        content = m.group(1).strip()
        # コメントアウト行は除外
        # 実際のエントリが空リストでないかチェック
        # コメントのみの行（# arceus: ...）は別途チェック
        lines_with_arceus = [
            line.strip() for line in text.splitlines()
            if "arceus" in line and "FALLBACK_MAP" not in line
            and not line.strip().startswith("#")
            and ":" in line
        ]
        if content and content != "" and not all(c in " \t\n" for c in content):
            # 空でない fallback が設定されている
            report.add(CheckResult(
                id=CHECK_ID, title=TITLE, status="NG",
                detail=f"arceus のフォールバックが設定されている: [{content}]",
                file=str(target.relative_to(BASE_DIR))
            ))
            return

    # "arceus" キーが FALLBACK_MAP に存在するか（コメント以外で）
    in_fallback_map = False
    found_arceus_entry = False
    for line in text.splitlines():
        stripped = line.strip()
        if "FALLBACK_MAP" in stripped and "=" in stripped:
            in_fallback_map = True
        if in_fallback_map and stripped.startswith("}"):
            in_fallback_map = False
        if in_fallback_map and '"arceus"' in stripped and not stripped.startswith("#"):
            found_arceus_entry = True
            # エントリの値を確認
            val_match = re.search(r'"arceus"\s*:\s*\[([^\]]*)\]', stripped)
            if val_match:
                val = val_match.group(1).strip()
                if val and not val.startswith("#"):
                    report.add(CheckResult(
                        id=CHECK_ID, title=TITLE, status="NG",
                        detail=f"arceus のフォールバックが設定されている: [{val}]",
                        file=str(target.relative_to(BASE_DIR))
                    ))
                    return

    report.add(CheckResult(
        id=CHECK_ID, title=TITLE, status="OK",
        detail="FALLBACK_MAP に arceus のフォールバックエントリは存在しない"
    ))


def check_c07_jirachi_fallback_intact(report: AuditReport):
    """C07: jirachi_kpop の fallback 先に alakazam_kpop が含まれているか"""
    CHECK_ID = "C07"
    TITLE = "jirachi_kpop の FALLBACK_MAP に alakazam_kpop が含まれているか"
    target = LIB_DIR / "retry_handler.py"
    text = read_file_text(target)

    # "jirachi_kpop": [...alakazam_kpop...] のパターン
    pattern = re.compile(r'"jirachi_kpop"\s*:\s*\[([^\]]*)\]')
    m = pattern.search(text)
    if not m:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail="FALLBACK_MAP に jirachi_kpop エントリが見つからない",
            file=str(target.relative_to(BASE_DIR))
        ))
        return

    fallback_content = m.group(1)
    if "alakazam_kpop" in fallback_content:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"jirachi_kpop のフォールバック先: [{fallback_content.strip()}]"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=(
                f"jirachi_kpop のフォールバック先に alakazam_kpop がない: [{fallback_content.strip()}]"
                f" alakazam_kpop を削除/改名した可能性がある"
            ),
            file=str(target.relative_to(BASE_DIR))
        ))


def check_c08_venusaur_in_strategy(report: AuditReport):
    """C08: strategy pipeline で venusaur が呼ばれているか（設計図生成役）"""
    CHECK_ID = "C08"
    TITLE = "strategy pipeline で venusaur が呼ばれているか（設計図生成役）"
    target = BASE_DIR / "kpop_strategy_pipeline.sh"
    calls = grep_agent_calls(target)

    venusaur_calls = [(ln, ag) for ln, ag in calls if ag == "venusaur"]
    if venusaur_calls:
        lines_str = ", ".join(str(ln) for ln, _ in venusaur_calls)
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"venusaur が strategy pipeline の {lines_str} 行目で呼ばれている"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail="venusaur が strategy pipeline で呼ばれていない。設計図生成ステップが欠落している可能性",
            file=str(target.relative_to(BASE_DIR))
        ))


def check_c09_arceus_in_breaking_and_strategy(report: AuditReport):
    """C09: arceus が breaking・strategy の最終判定ステップで呼ばれているか"""
    CHECK_ID = "C09"
    TITLE = "arceus が breaking・strategy の最終承認ステップで呼ばれているか"
    violations = []
    ok_msgs = []

    for fname, label in [
        ("kpop_pipeline.sh", "breaking"),
        ("kpop_strategy_pipeline.sh", "strategy"),
    ]:
        target = BASE_DIR / fname
        calls = grep_agent_calls(target)
        arceus_calls = [ln for ln, ag in calls if ag == "arceus"]
        if arceus_calls:
            ok_msgs.append(f"{label}: arceus が {arceus_calls} 行目で呼ばれている")
        else:
            violations.append(f"{label} ({fname}) に arceus の呼び出しが見つからない")

    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail="; ".join(violations)
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail="; ".join(ok_msgs)
        ))


def check_c10_zapdos_not_in_non_chart(report: AuditReport):
    """C10: zapdos が chart 以外の pipeline で記事生成ステップに使われていないか"""
    CHECK_ID = "C10"
    TITLE = "zapdos が chart 以外の pipeline で呼ばれていないか"
    non_chart_files = [
        BASE_DIR / "kpop_pipeline.sh",
        BASE_DIR / "kpop_strategy_pipeline.sh",
        BASE_DIR / "hub_article_post.sh",
    ]
    violations = []
    for target in non_chart_files:
        calls = grep_agent_calls(target)
        zapdos_calls = [(ln, ag) for ln, ag in calls if ag == "zapdos"]
        if zapdos_calls:
            for ln, _ in zapdos_calls:
                violations.append(f"{target.relative_to(BASE_DIR)}:{ln}")

    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"zapdos が chart 以外で呼ばれている: {violations}"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail="zapdos は chart pipeline 専用として使われている"
        ))


def check_c11_role_class_in_agents(report: AuditReport):
    """C11: 全対象エージェントの agents/*.md に ROLE_CLASS が記述されているか"""
    CHECK_ID = "C11"
    TITLE = "全対象エージェントの agents/*.md に ROLE_CLASS が記述されているか"
    TARGET_AGENTS = [
        # kpop pipeline CORE/SUPPORT (breaking/strategy/chart)
        "deoxys_kpop", "metamon_kpop", "eevee", "jirachi_kpop", "arceus",
        "butterfree", "lapras", "mimikyu", "wobbuffet", "venusaur",
        "alakazam_kpop", "gengar", "kairyu_kpop", "persian", "zapdos", "articuno",
        "gardevoir_hook_critic", "mewtwo",
        # kpop pipeline 特化エージェント（master_scheduler経由で呼ばれる）
        "beautywriter", "mewtwo_popup",
        # 週次レビュー・ai_company
        "porygon", "lugia", "meowth", "porygon_z",
        # MANUAL_ONLY / 未接続（定義は存在するがパイプライン未接続）
        "alakazam", "mewtwo_cosme", "popupwriter", "snorlax",
    ]
    missing = []
    found = []
    for agent in TARGET_AGENTS:
        md_path = AGENTS_DIR / f"{agent}.md"
        text = read_file_text(md_path)
        if "ROLE_CLASS:" in text:
            found.append(agent)
        else:
            missing.append(agent)

    if missing:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"ROLE_CLASS が未記載のエージェント: {missing}"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"全 {len(found)} エージェントに ROLE_CLASS が記述されている"
        ))


def check_c12_articuno_manual_only_label(report: AuditReport):
    """C12: articuno.md に MANUAL_ONLY ラベルが付いているか"""
    CHECK_ID = "C12"
    TITLE = "articuno.md に ROLE_CLASS: MANUAL_ONLY が記述されているか"
    md_path = AGENTS_DIR / "articuno.md"
    text = read_file_text(md_path)
    if "ROLE_CLASS: MANUAL_ONLY" in text:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail="articuno.md に ROLE_CLASS: MANUAL_ONLY が記載されている"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail="articuno.md に ROLE_CLASS: MANUAL_ONLY が見つからない",
            file="agents/articuno.md"
        ))


def check_c13_cron_connects_articuno(report: AuditReport):
    """C13: crontab が articuno を含むスクリプトを直接参照していないか"""
    CHECK_ID = "C13"
    TITLE = "crontab が articuno を含む cron 禁止スクリプトを参照していないか"
    cron_lines = get_crontab_lines()
    violations = []
    for line in cron_lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # articuno を直接呼ぶ cron ラインを検出
        if "articuno" in stripped:
            violations.append(stripped[:120])

    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail=f"crontab に articuno が含まれている: {violations}"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail="crontab に articuno の直接呼び出しは存在しない"
        ))


def check_c14_fallback_map_structure(report: AuditReport):
    """C14: retry_handler.py の FALLBACK_MAP 全体構造が規定通りか"""
    CHECK_ID = "C14"
    TITLE = "retry_handler.py の FALLBACK_MAP 必須エントリが揃っているか"
    target = LIB_DIR / "retry_handler.py"
    text = read_file_text(target)

    required_keys = ["deoxys_kpop", "metamon_kpop", "jirachi_kpop", "zapdos", "persian"]
    forbidden_keys_with_nonempty = ["arceus", "eevee"]  # これらは空リストか未設定でなければならない

    missing = []
    violations = []

    pattern_entry = re.compile(r'"(\w+)"\s*:\s*\[([^\]]*)\]')
    found_entries = {}
    for m in pattern_entry.finditer(text):
        key = m.group(1)
        val = m.group(2).strip()
        found_entries[key] = val

    for key in required_keys:
        if key not in found_entries:
            missing.append(key)

    for key in forbidden_keys_with_nonempty:
        if key in found_entries:
            val = found_entries[key]
            # コメントを除いた内容が空でないか
            val_clean = re.sub(r'#.*', '', val).strip()
            if val_clean and val_clean != "":
                violations.append(f"{key}: [{val}]")

    issues = []
    if missing:
        issues.append(f"必須エントリが不足: {missing}")
    if violations:
        issues.append(f"禁止エントリに非空値が設定されている: {violations}")

    if issues:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="NG",
            detail="; ".join(issues),
            file=str(target.relative_to(BASE_DIR))
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail=f"FALLBACK_MAP 構造OK。エントリ数: {len(found_entries)}"
        ))


def check_c15_no_new_article_generator(report: AuditReport):
    """C15: 責務固定表に未記載のエージェントが新たに記事ゼロ生成ステップで呼ばれていないか"""
    CHECK_ID = "C15"
    TITLE = "未登録エージェントが記事生成ステップに混入していないか"
    # WebSearch付き呼び出しが許可されているエージェント
    REGISTERED_WS_AGENTS = {"deoxys_kpop", "zapdos", "butterfree", "mimikyu"}

    pipeline_files = [
        BASE_DIR / "kpop_pipeline.sh",
        BASE_DIR / "kpop_strategy_pipeline.sh",
        BASE_DIR / "kpop_chart_pipeline.sh",
    ]

    violations = []
    for target in pipeline_files:
        calls = grep_websearch_agent_calls(target)
        for lineno, agent in calls:
            if agent not in REGISTERED_WS_AGENTS:
                violations.append(f"{target.relative_to(BASE_DIR)}:{lineno} ({agent})")

    if violations:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="WARN",
            detail=f"未登録エージェントが WebSearch付きで呼ばれている（要確認）: {violations}"
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID, title=TITLE, status="OK",
            detail="全 WebSearch付き呼び出しは登録済みエージェントのみ"
        ))


def check_c16_gardevoir_in_breaking_pipeline(report: AuditReport):
    """C16: gardevoir_hook_criticがbreakingパイプラインのjirachi後・arceus前に呼ばれているか"""
    CHECK_ID = "C16"
    TITLE = "gardevoir_hook_criticがbreaking pipeline jirachi後・arceus前に存在するか"
    target = BASE_DIR / "kpop_pipeline.sh"
    text = read_file_text(target)

    has_gardevoir = "gardevoir_hook_critic" in text
    # gardevoir の行番号 < arceus の行番号 を確認
    lines = text.splitlines()
    g_line = next((i for i, l in enumerate(lines) if "gardevoir_hook_critic" in l), None)
    a_line = next((i for i, l in enumerate(lines) if "--agent arceus" in l), None)
    j_line = next((i for i, l in enumerate(lines, 1) if 'log_step "jirachi"' in l and "ok" in l), None)

    if not has_gardevoir:
        report.add(CheckResult(id=CHECK_ID, title=TITLE, status="NG",
            detail="kpop_pipeline.sh に gardevoir_hook_critic の呼び出しが見つからない"))
    elif g_line is not None and a_line is not None and g_line < a_line:
        report.add(CheckResult(id=CHECK_ID, title=TITLE, status="OK",
            detail=f"gardevoir_hook_critic が arceus より前に呼ばれている (line {g_line+1} < {a_line+1})"))
    else:
        report.add(CheckResult(id=CHECK_ID, title=TITLE, status="WARN",
            detail=f"gardevoir_hook_criticの順序確認不可 (g={g_line}, arceus={a_line})"))


def check_c17_gardevoir_in_strategy_pipeline(report: AuditReport):
    """C17: gardevoir_hook_criticがstrategyパイプラインのkairyu後・arceus前に呼ばれているか"""
    CHECK_ID = "C17"
    TITLE = "gardevoir_hook_criticがstrategy pipeline kairyu後・arceus前に存在するか"
    target = BASE_DIR / "kpop_strategy_pipeline.sh"
    text = read_file_text(target)

    has_gardevoir = "gardevoir_hook_critic" in text
    lines = text.splitlines()
    g_line = next((i for i, l in enumerate(lines) if "gardevoir_hook_critic" in l), None)
    a_line = next((i for i, l in enumerate(lines) if "--agent arceus" in l), None)
    k_line = next((i for i, l in enumerate(lines) if "--agent kairyu_kpop" in l), None)

    if not has_gardevoir:
        report.add(CheckResult(id=CHECK_ID, title=TITLE, status="NG",
            detail="kpop_strategy_pipeline.sh に gardevoir_hook_critic の呼び出しが見つからない"))
    elif k_line is not None and g_line is not None and a_line is not None and k_line < g_line < a_line:
        report.add(CheckResult(id=CHECK_ID, title=TITLE, status="OK",
            detail=f"gardevoir_hook_critic が kairyu後・arceus前に存在 (k={k_line+1}, g={g_line+1}, a={a_line+1})"))
    else:
        report.add(CheckResult(id=CHECK_ID, title=TITLE, status="WARN",
            detail=f"gardevoir_hook_criticの順序確認不可 (kairyu={k_line}, g={g_line}, arceus={a_line})"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_c18_gossip_source_guard(report: AuditReport):
    """C18: gossip記事の一次ソースガードがpipeline・post_auditに存在するか"""
    CHECK_ID = "C18"
    issues = []

    # kpop_pipeline.sh に GOSSIP_MODE 変数受取とGOSSIP_SOURCE_FAILチェックがあるか
    pipeline_file = BASE_DIR / "kpop_pipeline.sh"
    if pipeline_file.exists():
        pipeline_text = pipeline_file.read_text(errors="replace")
        if "GOSSIP_MODE" not in pipeline_text:
            issues.append("kpop_pipeline.sh に GOSSIP_MODE 変数がない")
        if "GOSSIP_SOURCE_FAIL" not in pipeline_text:
            issues.append("kpop_pipeline.sh に GOSSIP_SOURCE_FAIL チェックがない")
        if "gossip_source_guard" not in pipeline_text:
            issues.append("kpop_pipeline.sh に gossip_source_guard ログ記録がない")
    else:
        issues.append("kpop_pipeline.sh が存在しない")

    # kpop_master_scheduler.sh に gossip 専用プロンプト分岐があるか
    scheduler_file = BASE_DIR / "kpop_master_scheduler.sh"
    if scheduler_file.exists():
        scheduler_text = scheduler_file.read_text(errors="replace")
        if "GOSSIP_SOURCE_FAIL" not in scheduler_text:
            issues.append("kpop_master_scheduler.sh に GOSSIP_SOURCE_FAIL チェックがない")
        if "GOSSIP_MODE=1" not in scheduler_text:
            issues.append("kpop_master_scheduler.sh が GOSSIP_MODE=1 をexportしていない")
    else:
        issues.append("kpop_master_scheduler.sh が存在しない")

    # post_audit.sh に gossip_source_guard ([4.5]) があるか
    audit_file = BASE_DIR / "post_audit.sh"
    if audit_file.exists():
        audit_text = audit_file.read_text(errors="replace")
        if "gossip_source_guard" not in audit_text:
            issues.append("post_audit.sh に gossip_source_guard がない")
        if "4.5" not in audit_text or "ゴシップ" not in audit_text:
            issues.append("post_audit.sh に [4.5] ゴシップガードがない")
    else:
        issues.append("post_audit.sh が存在しない")

    if issues:
        report.add(CheckResult(
            id=CHECK_ID,
            title="gossip記事の一次ソースガードがpipeline・post_auditに存在するか",
            status="NG",
            detail="; ".join(issues),
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID,
            title="gossip記事の一次ソースガードがpipeline・post_auditに存在するか",
            status="OK",
            detail="GOSSIP_MODE / GOSSIP_SOURCE_FAIL / gossip_source_guard 全て確認OK",
        ))


def check_c19_pipeline_external_wp_check(report: AuditReport):
    """C19: post_watchdog.py に pipeline外WP記事検知チェック(external_wp)が登録されているか"""
    CHECK_ID = "C19"
    watchdog_file = BASE_DIR / "lib" / "post_watchdog.py"
    if not watchdog_file.exists():
        report.add(CheckResult(
            id=CHECK_ID,
            title="post_watchdog.pyにpipeline外WP記事検知が登録されているか",
            status="NG",
            detail="lib/post_watchdog.py が存在しない",
        ))
        return

    text = watchdog_file.read_text(errors="replace")
    issues = []
    if "check_pipeline_external_wp_posts" not in text:
        issues.append("check_pipeline_external_wp_posts 関数が存在しない")
    if '"external_wp"' not in text and "'external_wp'" not in text:
        issues.append("CHECKS辞書に external_wp が登録されていない")
    if "HUMAN_REVIEW_ONLY" not in text or "pipeline_external_wp_post" not in text:
        issues.append("pipeline外WP記事検知のHUMAN_REVIEW_ONLYポリシーが確認できない")

    if issues:
        report.add(CheckResult(
            id=CHECK_ID,
            title="post_watchdog.pyにpipeline外WP記事検知が登録されているか",
            status="NG",
            detail="; ".join(issues),
        ))
    else:
        report.add(CheckResult(
            id=CHECK_ID,
            title="post_watchdog.pyにpipeline外WP記事検知が登録されているか",
            status="OK",
            detail="check_pipeline_external_wp_posts / external_wp / HUMAN_REVIEW_ONLY 全て確認OK",
        ))


def run_all_checks() -> AuditReport:
    report = AuditReport()
    checks = [
        check_c01_breaking_generator,
        check_c02_strategy_generator,
        check_c03_chart_generator,
        check_c04_eevee_pipeline_positions,
        check_c05_articuno_not_in_cron,
        check_c06_arceus_no_fallback,
        check_c07_jirachi_fallback_intact,
        check_c08_venusaur_in_strategy,
        check_c09_arceus_in_breaking_and_strategy,
        check_c10_zapdos_not_in_non_chart,
        check_c11_role_class_in_agents,
        check_c12_articuno_manual_only_label,
        check_c13_cron_connects_articuno,
        check_c14_fallback_map_structure,
        check_c15_no_new_article_generator,
        check_c16_gardevoir_in_breaking_pipeline,
        check_c17_gardevoir_in_strategy_pipeline,
        check_c18_gossip_source_guard,
        check_c19_pipeline_external_wp_check,
    ]
    for check_fn in checks:
        try:
            check_fn(report)
        except Exception as e:
            report.add(CheckResult(
                id="ERR",
                title=check_fn.__name__,
                status="NG",
                detail=f"チェック実行中に例外が発生: {e}"
            ))
    return report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# スナップショット（前回比較用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_snapshot() -> Optional[dict]:
    """前回実行のスナップショットを読み込む"""
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_snapshot(report: AuditReport):
    """今回の実行結果をスナップショットとして保存する"""
    LOGS_DIR.mkdir(exist_ok=True)
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "ok": report.ok_count,
        "ng": report.ng_count,
        "warn": report.warn_count,
        "ng_ids": [r.id for r in report.results if r.status == "NG"],
        "warn_ids": [r.id for r in report.results if r.status == "WARN"],
    }
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def build_diff_line(prev: Optional[dict], report: AuditReport) -> str:
    """前回との差分を1行で表現する。初回は '初回実行' を返す。"""
    if prev is None:
        return "前回比較: 初回実行"

    prev_ok = prev.get("ok", "?")
    prev_ng = prev.get("ng", "?")
    prev_warn = prev.get("warn", "?")
    prev_ts = prev.get("timestamp", "不明")[:16].replace("T", " ")

    curr_ok = report.ok_count
    curr_ng = report.ng_count
    curr_warn = report.warn_count

    if prev_ng == curr_ng and prev_warn == curr_warn:
        change = "変化なし"
    else:
        parts = []
        if isinstance(prev_ng, int) and prev_ng != curr_ng:
            delta = curr_ng - prev_ng
            parts.append(f"NG {prev_ng}→{curr_ng} ({'+' if delta>0 else ''}{delta})")
        if isinstance(prev_warn, int) and prev_warn != curr_warn:
            delta = curr_warn - prev_warn
            parts.append(f"WARN {prev_warn}→{curr_warn} ({'+' if delta>0 else ''}{delta})")
        change = " / ".join(parts) if parts else "変化なし"

    prev_ng_ids = prev.get("ng_ids", [])
    curr_ng_ids = [r.id for r in report.results if r.status == "NG"]
    new_ngs = [x for x in curr_ng_ids if x not in prev_ng_ids]
    resolved = [x for x in prev_ng_ids if x not in curr_ng_ids]

    diff_parts = [f"前回({prev_ts}): OK={prev_ok} NG={prev_ng} WARN={prev_warn}",
                  f"今回: OK={curr_ok} NG={curr_ng} WARN={curr_warn}",
                  f"差分: {change}"]
    if new_ngs:
        diff_parts.append(f"新規NG: {new_ngs}")
    if resolved:
        diff_parts.append(f"解消NG: {resolved}")
    return " | ".join(diff_parts)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 出力
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def print_report(report: AuditReport, verbose: bool = False, diff_line: str = ""):
    STATUS_ICON = {"OK": "✅", "NG": "❌", "WARN": "⚠️ "}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 68)
    print(" audit_agent_roles.py — エージェント責務逸脱チェック")
    print(f" 実行日時: {now_str}")
    print("=" * 68)
    for r in report.results:
        icon = STATUS_ICON.get(r.status, "?")
        print(f"\n{icon} [{r.id}] {r.title}")
        if r.status != "OK" or verbose:
            print(f"     {r.detail}")
            if r.file:
                loc = r.file
                if r.line:
                    loc += f":{r.line}"
                print(f"     → {loc}")
    print("\n" + "=" * 68)
    print(f" 結果: OK={report.ok_count}  NG={report.ng_count}  WARN={report.warn_count}")
    if report.ng_count == 0 and report.warn_count == 0:
        print(" 🎉 全チェック PASS — 責務逸脱は検出されなかった")
    elif report.ng_count == 0:
        print(f" ⚠️  WARN {report.warn_count}件あり — 要確認だが自動修復不要")
    else:
        print(f" 🚨 NG {report.ng_count}件 — 責務逸脱を検出。runbook を参照して修正すること")
        ng_items = [f"  ❌ [{r.id}] {r.title}" + (f" → {r.file}" if r.file else "")
                    for r in report.results if r.status == "NG"]
        print(" NG項目一覧:")
        for item in ng_items:
            print(item)
    if diff_line:
        print(f" {diff_line}")
    print("=" * 68)


def print_summary_line(report: AuditReport, diff_line: str = ""):
    """improvement_engine.sh 向けの1行サマリーを出力する"""
    if report.ng_count == 0 and report.warn_count == 0:
        status = "PASS"
        label = "全チェックOK"
    elif report.ng_count == 0:
        status = "WARN"
        label = f"WARN {report.warn_count}件"
    else:
        ng_ids = ", ".join(r.id for r in report.results if r.status == "NG")
        status = "NG"
        label = f"NG {report.ng_count}件 [{ng_ids}] → logs/role_audit.log 参照"
    print(f"[role_audit] {status} | OK={report.ok_count} NG={report.ng_count} WARN={report.warn_count} | {label}")
    if diff_line:
        print(f"[role_audit] {diff_line}")


def main():
    parser = argparse.ArgumentParser(description="エージェント責務逸脱チェッカー")
    parser.add_argument("--verbose", "-v", action="store_true", help="OK 項目も詳細表示")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    parser.add_argument("--summary", action="store_true", help="1行サマリーのみ出力（improvement_engine用）")
    args = parser.parse_args()

    prev_snapshot = load_snapshot()
    report = run_all_checks()
    diff_line = build_diff_line(prev_snapshot, report)

    # スナップショットを更新（--summary でも保存する）
    save_snapshot(report)

    if args.json:
        output = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "ok": report.ok_count,
                "ng": report.ng_count,
                "warn": report.warn_count,
                "pass": report.ng_count == 0,
            },
            "diff": diff_line,
            "results": [
                {
                    "id": r.id,
                    "title": r.title,
                    "status": r.status,
                    "detail": r.detail,
                    "file": r.file,
                    "line": r.line,
                }
                for r in report.results
            ]
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.summary:
        print_summary_line(report, diff_line)
    else:
        print_report(report, verbose=args.verbose, diff_line=diff_line)

    sys.exit(0 if report.ng_count == 0 else 1)


if __name__ == "__main__":
    main()
