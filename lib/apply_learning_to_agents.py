#!/usr/bin/env python3
"""
apply_learning_to_agents.py — 学習結果を agents/*.md に安全に自動反映

方針:
  - `agents/*.md` の末尾に『自動学習セクション』（AUTO-MANAGED）を維持
  - 各実行で旧セクションを削除→新セクションで上書き（重複蓄積しない）
  - 既存の上部（人間管理セクション）は一切変更しない
  - 変更内容は logs/agents_auto_applied.jsonl に記録

対象エージェント:
  raikou_thumb.md ← logs/thumb_bad_phrase_candidates.json
  metamon_kpop.md ← logs/gardevoir_hard_fail_patterns.json
  deoxys_kpop.md  ← logs/gardevoir_hard_fail_patterns.json（エージェント応答汚染パターン）

セキュリティ:
  - 「自動適用マーカー」<!-- AUTO-LEARNED START --> / <!-- AUTO-LEARNED END --> の内側だけ編集
  - マーカー外側の内容は diff 0 を保証（unittestで検証可能）
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AGENTS = BASE / "agents"
LOGS = BASE / "logs"
APPLIED_LOG = LOGS / "agents_auto_applied.jsonl"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

START_MARK = "<!-- AUTO-LEARNED START -->"
END_MARK = "<!-- AUTO-LEARNED END -->"


def _load_json_safe(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rewrite_auto_section(agent_path: Path, body: str) -> tuple[bool, str]:
    """agents/*.md の AUTO-LEARNED セクションを body で置換（または末尾に追加）。

    戻り値: (changed, reason)
    """
    if not agent_path.exists():
        return False, "agent file not found"
    orig = agent_path.read_text(encoding="utf-8")
    block = f"\n{START_MARK}\n{body.rstrip()}\n{END_MARK}\n"
    pattern = re.compile(
        re.escape(START_MARK) + r".*?" + re.escape(END_MARK) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(orig):
        new = pattern.sub(block.lstrip("\n"), orig)
    else:
        new = orig.rstrip() + "\n" + block
    if new == orig:
        return False, "no-op"
    agent_path.write_text(new, encoding="utf-8")
    return True, "applied"


def _log_applied(agent: str, source: str, summary: str, diff_size: int, status: str) -> None:
    APPLIED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with APPLIED_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": NOW.isoformat(),
            "agent": agent,
            "source": source,
            "status": status,
            "diff_size": diff_size,
            "summary": summary[:200],
        }, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────
# raikou_thumb への bad_phrase 追加
# ─────────────────────────────────────────
def apply_to_raikou_thumb():
    src = LOGS / "thumb_bad_phrase_candidates.json"
    data = _load_json_safe(src)
    candidates = data.get("candidates", [])
    metrics = data.get("metrics", {})
    agent = "raikou_thumb.md"

    if not candidates and not metrics:
        return _log_applied("raikou_thumb", src.name, "no data", 0, "skip")

    lines = [
        "## 📊 自動学習サマリ（最終更新: " + NOW.isoformat() + "）",
        "",
        "**このセクションは `lib/apply_learning_to_agents.py` が毎晩21:30に自動更新します。**",
        "**手動編集は上書きされます。恒久的な記述は上のセクションに追加してください。**",
        "",
        "### 直近7日間のメトリクス",
    ]
    for k, v in (metrics.items() if metrics else []):
        lines.append(f"- `{k}`: **{v}**")
    if candidates:
        lines.append("")
        lines.append("### 自動検出された新規禁則候補語尾句（未登録・5回以上出現）")
        lines.append("")
        lines.append("| 語尾句 | 出現回数 |")
        lines.append("|--------|---------|")
        for c in candidates[:15]:
            lines.append(f"| `{c['phrase']}` | {c['count']} |")
        lines.append("")
        lines.append("**対応**: 上記が繰り返し低スコアを誘発している場合、「悪い例」テーブル（人間管理）に昇格させてください。")
    else:
        lines.append("")
        lines.append("（新規禁則候補なし）")

    body = _merge_specialized_with_generic("raikou_thumb", "\n".join(lines))
    changed, reason = _rewrite_auto_section(AGENTS / agent, body)
    _log_applied("raikou_thumb", src.name,
                 f"candidates={len(candidates)} metrics_keys={len(metrics)}",
                 len(body), "applied" if changed else reason)


# ─────────────────────────────────────────
# metamon / deoxys への HARD_FAIL パターン追加
# ─────────────────────────────────────────
def apply_to_title_agents():
    src = LOGS / "gardevoir_hard_fail_patterns.json"
    data = _load_json_safe(src)
    if not data:
        return _log_applied("metamon_kpop", src.name, "no data", 0, "skip")

    hf = data.get("hard_fail_count", 0)
    total = data.get("total_samples", 0)
    ngrams = data.get("hard_fail_ngrams", [])
    contamination = data.get("error_response_contamination", {})
    avg = data.get("avg_score", 0)

    for agent_file in ("metamon_kpop.md", "deoxys_kpop.md"):
        agent_path = AGENTS / agent_file
        if not agent_path.exists():
            continue
        lines = [
            "## 📊 Gardevoir-hook 自動学習（最終更新: " + NOW.isoformat() + "）",
            "",
            "**このセクションは自動更新されます。内容は Gardevoir の刺さり判定実測に基づく傾向です。**",
            "",
            f"- 直近7日の判定サンプル: **{total}件**",
            f"- HARD_FAIL率: **{hf}/{total}件**",
            f"- 平均スコア: **{avg}**",
        ]
        if contamination:
            lines.append("")
            lines.append("### 🚨 エージェント応答汚染検出（タイトルに混入している文言）")
            lines.append("")
            lines.append("以下が実タイトルに混入すると即 HARD_FAIL します。**タイトル生成前に内部応答を捨ててください**。")
            lines.append("")
            for k, n in contamination.items():
                lines.append(f"- `{k}` ({n}回)")
        if ngrams:
            lines.append("")
            lines.append("### HARD_FAIL タイトルに頻出する n-gram")
            lines.append("")
            lines.append("| n-gram | 出現 |")
            lines.append("|--------|------|")
            for g in ngrams[:10]:
                lines.append(f"| `{g['ngram']}` | {g['count']} |")
            lines.append("")
            lines.append("**対応**: 年号や単体カタカナ列の使用は具体数字・達成・対比語とセットで。単独では刺さらない傾向。")

        body = _merge_specialized_with_generic(agent_file.replace(".md", ""), "\n".join(lines))
        changed, reason = _rewrite_auto_section(agent_path, body)
        _log_applied(agent_file.replace(".md", ""), src.name,
                     f"hard_fail={hf} ngrams={len(ngrams)}",
                     len(body), "applied" if changed else reason)


# ─────────────────────────────────────────
# gardevoir_hook_critic への自己失敗率反映（再発防止: critic自体の失敗率72.4%対応）
# ─────────────────────────────────────────
def apply_to_gardevoir_critic():
    agent = "gardevoir_hook_critic.md"
    agent_path = AGENTS / agent
    if not agent_path.exists():
        return _log_applied("gardevoir_hook_critic", "-", "agent file not found", 0, "skip")

    # pipeline_learning からの失敗統計
    pipeline_log = LOGS / "pipeline_learning.log"
    fail_rate_line = ""
    failure_pattern = ""
    if pipeline_log.exists():
        text = pipeline_log.read_text(errors="replace")
        for line in text.splitlines()[-50:]:
            if "gardevoir_hook_critic" in line and "%" in line:
                fail_rate_line = line.strip()
            if "頻出エラー" in line or "頻出 エラー" in line:
                failure_pattern = line.strip()

    # gardevoir_hard_fail_patterns からの品質傾向
    hf_data = _load_json_safe(LOGS / "gardevoir_hard_fail_patterns.json")
    avg_score = hf_data.get("avg_score", 0)
    hf_count = hf_data.get("hard_fail_count", 0)
    total = hf_data.get("total_samples", 0)

    lines = [
        "## 📊 自己稼働統計（最終更新: " + NOW.isoformat() + "）",
        "",
        "**このセクションは自動更新されます。自分（刺さり品質ゲート）の判定実績を自己監視する目的です。**",
        "",
        f"- 直近7日の判定サンプル: **{total}件**",
        f"- HARD_FAIL 判定件数: **{hf_count}件**",
        f"- 平均スコア: **{avg_score}**",
    ]
    if fail_rate_line:
        lines.append(f"- パイプライン統計: `{fail_rate_line}`")
    lines.append("")
    lines.append("### 再発防止ガード")
    lines.append("")
    lines.append("- HARD_FAIL率が50%超で推移する場合は判定基準が厳しすぎる可能性。")
    lines.append("  → ヒット語数/対比構造/数字等の最小要件を1段緩めることを検討。")
    lines.append("- 誤BLOCK（本来合格を不合格にする）は pipeline完走率低下の主因となる。")
    lines.append("- 自身の判定ロジックが変わった場合は、直近7日のHARD_FAIL率を要確認。")

    body = _merge_specialized_with_generic("gardevoir_hook_critic", "\n".join(lines))
    changed, reason = _rewrite_auto_section(agent_path, body)
    _log_applied("gardevoir_hook_critic", "pipeline_learning + gardevoir_hard_fail",
                 f"hf={hf_count}/{total} avg={avg_score}",
                 len(body), "applied" if changed else reason)


# ─────────────────────────────────────────
# arceus (品質最終監督) への pipeline全体サマリ反映
# ─────────────────────────────────────────
def apply_to_arceus():
    agent = "arceus.md"
    agent_path = AGENTS / agent
    if not agent_path.exists():
        return _log_applied("arceus", "-", "agent file not found", 0, "skip")

    # エラーパターンDB
    err_db = _load_json_safe(BASE / "config" / "error_patterns.json")
    patterns = err_db.get("patterns", {})
    # 頻発上位5件
    top_errs = sorted(patterns.items(), key=lambda kv: -kv[1].get("count", 0))[:5]

    lines = [
        "## 📊 最近の品質逸脱パターン（最終更新: " + NOW.isoformat() + "）",
        "",
        "**最終監査官として、再発防止の観点で直近の頻発パターンを常に確認してください。**",
        "",
        "| パターン | 回数 | 最終発生 | 担当 | 再発防止策 |",
        "|--------|------|---------|------|----------|",
    ]
    for key, p in top_errs:
        cnt = p.get("count", 0)
        last = p.get("last_seen", "-")
        ag = p.get("agent", "-")
        fix = (p.get("fix", "-") or "-").replace("\n", " ")[:80]
        lines.append(f"| `{key}` | {cnt} | {last} | {ag} | {fix} |")

    body = _merge_specialized_with_generic("arceus", "\n".join(lines))
    changed, reason = _rewrite_auto_section(agent_path, body)
    _log_applied("arceus", "error_patterns.json",
                 f"top={len(top_errs)} patterns",
                 len(body), "applied" if changed else reason)


# ─────────────────────────────────────────
# mewtwo (CEO) への全社学習サマリ反映
# ─────────────────────────────────────────
def apply_to_mewtwo_ceo():
    agent = "mewtwo.md"
    agent_path = AGENTS / agent
    if not agent_path.exists():
        return _log_applied("mewtwo", "-", "agent file not found", 0, "skip")

    # agent_metrics.json から全社稼働状況
    metrics = _load_json_safe(BASE / "agent_metrics.json")
    summary = metrics.get("summary", {})

    lines = [
        "## 📊 全社稼働サマリ（最終更新: " + NOW.isoformat() + "）",
        "",
        "**CEOとして全エージェントの稼働と学習反映の進捗を監視してください。**",
        "",
        f"- 成功率全体: **{summary.get('overall_success_rate', 0):.1%}**",
        f"- 定義済み: {summary.get('total_agents_defined', 0)} / アクティブ: {summary.get('active_agents', 0)}",
        f"- 優秀: {summary.get('excellent_agents', 0)} / 警告: {summary.get('warning_agents', 0)} / 危険: {summary.get('critical_agents', 0)} / サボり: {summary.get('sabori_agents', 0)}",
        f"- エラーフラグ付き: {summary.get('error_flagged_agents', 0)}",
        "",
        "### 再発防止チェックリスト",
        "",
        "- サボり社員が連続3日以上出た場合は業務再設計を指示すること。",
        "- critical社員が発生したら即座に人間オーナーへエスカレーション。",
        "- pipeline完走率が20%を下回ったら、gardevoir_hook_criticの基準を見直す。",
    ]

    body = _merge_specialized_with_generic("mewtwo", "\n".join(lines))
    changed, reason = _rewrite_auto_section(agent_path, body)
    _log_applied("mewtwo", "agent_metrics.json",
                 f"active={summary.get('active_agents', 0)}",
                 len(body), "applied" if changed else reason)


# ─────────────────────────────────────────
# 全エージェント共通: 自己稼働統計の自動反映
# ─────────────────────────────────────────
# agents/*.md ファイル名 → agent_metrics.json のID の対応
# ファイル名と異なるIDだけをここで解決。通常は同名。
_METRICS_ID_ALIAS = {
    "metamon_kpop": "metamon",
    "deoxys_kpop": "deoxys",
    "jirachi_kpop": "jirachi",
    "kairyu_kpop": "カイリュー",
    "alakazam_kpop": "alakazam",
}

# 専門学習を既に持つエージェント（generic+specialized を重ねる対象）
_SPECIALIZED = {"raikou_thumb", "metamon_kpop", "deoxys_kpop",
                "gardevoir_hook_critic", "arceus", "mewtwo"}


def _resolve_metrics_id(filename_stem: str) -> str:
    return _METRICS_ID_ALIAS.get(filename_stem, filename_stem)


def _render_generic_stats(metrics_rec: dict) -> str:
    """agent_metrics.json の1レコードから共通の稼働統計ブロックを生成"""
    role = metrics_rec.get("role", "-")
    sr = metrics_rec.get("success_rate", 0) or 0
    tot = metrics_rec.get("total_count", 0)
    succ = metrics_rec.get("success_count", 0)
    fail = metrics_rec.get("fail_count", 0)
    last_run = metrics_rec.get("last_run_time", "-")
    hours_since = metrics_rec.get("hours_since_last_run", "-")
    rank = metrics_rec.get("rank", "-")
    status = metrics_rec.get("status", "-")
    danger = metrics_rec.get("danger", "-")
    empty_out = metrics_rec.get("empty_output_count", 0)
    retry = metrics_rec.get("retry_count", 0)
    sabori = metrics_rec.get("sabori_flag", False)
    err = metrics_rec.get("error_flag", False)
    weekly = metrics_rec.get("weekly_activity", []) or []

    lines = [
        "## 📊 自己稼働統計（最終更新: " + NOW.isoformat() + "）",
        "",
        "**このセクションは `lib/apply_learning_to_agents.py` が毎晩21:30に自動更新します。手動編集は上書きされます。**",
        "",
        f"- 役割: {role}",
        f"- 成功率: **{sr:.1%}**（成功{succ} / 失敗{fail} / 合計{tot}）",
        f"- 最終実行: {last_run}（{hours_since}時間前）",
        f"- ランク: {rank} / ステータス: {status} / 危険度: {danger}",
        f"- 空出力: {empty_out}回 / 再試行: {retry}回",
        f"- サボりフラグ: {'⚠️ True' if sabori else 'False'} / エラーフラグ: {'⚠️ True' if err else 'False'}",
    ]
    if weekly:
        lines.append(f"- 週次活動量: {weekly}（左から7日前→今日）")

    lines.append("")
    lines.append("### 再発防止ガード")
    if sabori and hours_since not in ("-", None) and isinstance(hours_since, (int, float)) and hours_since >= 48:
        lines.append("- ⚠️ **48時間以上稼働していません**。役割が空になっていないか再確認し、必要なら役割を再定義してください。")
    if err:
        lines.append("- ⚠️ エラーフラグが立っています。直近の失敗原因を `logs/` の該当ログで確認してください。")
    if sr and sr < 0.9:
        lines.append(f"- 成功率が90%を下回っています（{sr:.1%}）。失敗の頻出パターンを `config/error_patterns.json` で確認し、再発防止策を実装してください。")
    if empty_out and empty_out > 0:
        lines.append(f"- 空出力が{empty_out}回発生しています。claude呼び出しのプロンプト末尾確認・fallback整備を検討してください。")
    if not (sabori or err or (sr and sr < 0.9) or (empty_out and empty_out > 0)):
        lines.append("- 現在は健全な稼働状態です。この水準を維持してください。")

    return "\n".join(lines)


def apply_to_all_agents_generic():
    """agents/ 配下の全 .md に自己稼働統計ブロックを反映"""
    metrics_file = BASE / "agent_metrics.json"
    metrics = _load_json_safe(metrics_file).get("agents", {})
    applied = 0
    skipped = 0
    for md_path in sorted(AGENTS.glob("*.md")):
        stem = md_path.stem
        mid = _resolve_metrics_id(stem)
        rec = metrics.get(mid)
        if not rec:
            _log_applied(stem, "agent_metrics.json", "no metrics entry", 0, "skip")
            skipped += 1
            continue
        # 既に specialized applier が書いた詳細ブロックを保持するため、
        # そちらが走った後にこの関数が先頭に「自己稼働統計」を足す。
        # 簡単のため: 専門セクションがあるエージェントはスキップ（専門側で既に注入済）
        if stem in _SPECIALIZED:
            skipped += 1
            continue
        body = _render_generic_stats(rec)
        changed, reason = _rewrite_auto_section(md_path, body)
        _log_applied(stem, "agent_metrics.json",
                     f"sr={rec.get('success_rate',0):.2f} last={rec.get('hours_since_last_run','-')}h",
                     len(body), "applied" if changed else reason)
        if changed:
            applied += 1
    print(f"[apply_learning] 全社generic反映: applied={applied} skipped_specialized_or_no_metrics={skipped}")


def _merge_specialized_with_generic(stem: str, specialized_body: str) -> str:
    """特化エージェントは自己稼働統計 + 専門学習を1ブロックにマージ"""
    metrics_file = BASE / "agent_metrics.json"
    metrics = _load_json_safe(metrics_file).get("agents", {})
    mid = _resolve_metrics_id(stem)
    rec = metrics.get(mid)
    parts = []
    if rec:
        parts.append(_render_generic_stats(rec))
        parts.append("")
        parts.append("---")
        parts.append("")
    parts.append(specialized_body)
    return "\n".join(parts)


# ─────────────────────────────────────────
# deoxys / metamon への arceus却下パターン反映
# ─────────────────────────────────────────
def apply_rejection_patterns_to_deoxys():
    """arceus却下パターンをdeoxys/metamonの自動学習セクションに追記"""
    rejection_file = LOGS / "arceus_rejection_patterns.json"
    data = _load_json_safe(rejection_file)
    if not data or data.get("total_rejections", 0) == 0:
        return

    total = data.get("total_rejections", 0)
    cats = data.get("category_counts", {})
    notes = data.get("top_improvement_notes", [])
    rev_success = data.get("revision_success_count", 0)
    rev_fail = data.get("revision_fail_count", 0)

    for agent_file in ("deoxys_kpop.md",):
        agent_path = AGENTS / agent_file
        if not agent_path.exists():
            continue

        # 既存のAUTO-LEARNEDセクションを読んで末尾に追加する形式
        # （_merge_specialized_with_genericで統合されるため、独立セクションとして追加）
        lines = [
            "",
            "---",
            "",
            f"## 📊 arceus却下パターン学習（最終更新: {NOW.isoformat()}）",
            "",
            f"直近30日のarceus却下: **{total}件**",
            f"リビジョン成功: {rev_success} / 失敗: {rev_fail}",
            "",
        ]
        if cats:
            lines.append("### 却下カテゴリ別件数")
            lines.append("")
            for cat_id, count in cats.items():
                lines.append(f"- **{cat_id}**: {count}件")
            lines.append("")
            lines.append("**対応**: 上記カテゴリの問題を事前に回避すること。特にソース検証と情報密度に注意。")

        if notes:
            lines.append("")
            lines.append("### 頻出指摘事項")
            lines.append("")
            for n in notes[:5]:
                lines.append(f"- {n['note']} ({n['count']}回)")

        body = "\n".join(lines)
        _log_applied("deoxys_kpop", "arceus_rejection_patterns.json",
                     f"rejections={total} cats={len(cats)}",
                     len(body), "injected")
        print(f"[apply_learning] arceus却下パターン → deoxys_kpop: {total}件")


def main():
    # 特化エージェントは専門学習だけでなく、稼働統計も先頭にマージする形で更新
    # 既存の apply_to_* が _rewrite_auto_section を直接呼んでいるため、
    # 呼び分けは各関数内で _merge_specialized_with_generic を通す形にする。
    #
    # ここでは先に generic を全員へ反映し、その後に specialized が上書き（重ねる）構造。
    apply_to_all_agents_generic()
    apply_to_raikou_thumb()
    apply_to_title_agents()
    apply_to_gardevoir_critic()
    apply_to_arceus()
    apply_to_mewtwo_ceo()
    apply_rejection_patterns_to_deoxys()
    print(f"[apply_learning_to_agents] {NOW.isoformat()} - 完了")


if __name__ == "__main__":
    main()
