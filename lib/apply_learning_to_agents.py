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

    body = "\n".join(lines)
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

        body = "\n".join(lines)
        changed, reason = _rewrite_auto_section(agent_path, body)
        _log_applied(agent_file.replace(".md", ""), src.name,
                     f"hard_fail={hf} ngrams={len(ngrams)}",
                     len(body), "applied" if changed else reason)


def main():
    apply_to_raikou_thumb()
    apply_to_title_agents()
    # 完了サマリ
    print(f"[apply_learning_to_agents] {NOW.isoformat()} - 完了")


if __name__ == "__main__":
    main()
