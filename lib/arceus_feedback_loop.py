#!/usr/bin/env python3
"""
arceus_feedback_loop.py — arceus却下→deoxysリビジョン自動差し戻しエンジン v1.0

【責務】
  1. arceus出力から却下理由を構造化抽出
  2. 却下理由をカテゴリ分類（ソース不足/CTR弱/SEO不備/品質不足/フォーマット違反）
  3. deoxys向けリビジョンリクエスト（構造化プロンプト）を生成
  4. 却下履歴をarceus_rejections.jsonlに蓄積（学習用）
  5. リビジョン回数制限（最大2回）と最終エスカレーション

【パイプライン統合】
  kpop_pipeline.sh から以下のように呼ばれる:
    # arceus却下時
    REVISION_PROMPT=$(python3 lib/arceus_feedback_loop.py parse-rejection reports/3_arceus.md)
    # リビジョンリクエスト生成
    python3 lib/arceus_feedback_loop.py generate-revision \
      --arceus-report reports/3_arceus.md \
      --original-article reports/0_breaking.md \
      --attempt 1

Usage:
  python3 lib/arceus_feedback_loop.py parse-rejection reports/3_arceus.md
  python3 lib/arceus_feedback_loop.py generate-revision --arceus-report FILE --original-article FILE [--attempt N]
  python3 lib/arceus_feedback_loop.py stats                    # 却下統計を表示
  python3 lib/arceus_feedback_loop.py inject-learning          # 却下パターンをagentsに注入
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
REJECTION_LOG = LOGS / "arceus_rejections.jsonl"
AGENTS = BASE / "agents"
JST = timezone(timedelta(hours=9))

MAX_REVISION_ATTEMPTS = 2

# ── 却下理由カテゴリ ────────────────────────────────────────────

REJECTION_CATEGORIES = {
    "source_missing": {
        "label": "ソース不足・検証不可",
        "patterns": [
            r"一次ソース.*(?:不足|なし|未確認|不明)",
            r"ソース.*(?:信頼性|検証|確認)",
            r"情報源.*(?:不明|曖昧|不十分)",
            r"ファクトチェック.*(?:不合格|失敗|未実施)",
            r"未検証",
            r"出典.*(?:なし|不足)",
            r"裏付け.*(?:なし|不足|不十分)",
        ],
        "revision_instruction": "一次ソース（公式発表・大手メディア報道）をWebSearchで再確認し、記事内に情報源を明記すること。",
    },
    "ctr_weak": {
        "label": "CTR弱・タイトル問題",
        "patterns": [
            r"CTR.*(?:弱|低|不十分|改善)",
            r"タイトル.*(?:弱|汎用|一般的|改善|薄い)",
            r"フック.*(?:弱|なし|不足)",
            r"感情語.*(?:なし|不足)",
            r"数字.*(?:なし|不足)",
            r"(?:刺さ|引き).*(?:弱|ない)",
            r"クリック.*(?:弱|されない)",
        ],
        "revision_instruction": "タイトルに感情語+具体数字+アーティスト名を含め、CTRを意識した訴求力のあるフックに修正すること。",
    },
    "seo_deficiency": {
        "label": "SEO不備",
        "patterns": [
            r"(?:キーワード|KW).*(?:不足|なし|配置|密度)",
            r"SEO.*(?:不備|不足|改善)",
            r"見出し.*(?:不足|H2|構成)",
            r"(?:メタ|meta).*(?:不足|なし|説明)",
            r"構造.*(?:不備|改善|不十分)",
            r"(?:内部|関連)リンク.*(?:なし|不足)",
        ],
        "revision_instruction": "主要KWをH2見出しとリード文に配置し、適切な見出し構造（H2×4-6個）で記事を再構成すること。",
    },
    "quality_low": {
        "label": "品質不足・情報密度低",
        "patterns": [
            r"品質.*(?:不足|低|改善|不十分)",
            r"情報.*(?:密度|量|不足|薄)",
            r"(?:深堀|分析|考察).*(?:不足|なし|浅)",
            r"本文.*(?:短|少|不足)",
            r"(?:2000|文字).*(?:未満|不足|足りない)",
            r"内容.*(?:薄|浅|不十分)",
            r"独自.*(?:なし|不足)",
        ],
        "revision_instruction": "記事の情報密度を高め、独自の分析・考察を追加して2000文字以上の本文にすること。ファンが「読んで良かった」と感じる深さを目指すこと。",
    },
    "format_violation": {
        "label": "フォーマット違反",
        "patterns": [
            r"フォーマット.*(?:違反|不正|逸脱)",
            r"(?:AI|エージェント).*(?:混入|汚染|応答)",
            r"(?:マークダウン|md).*(?:混入|誤用)",
            r"出力.*(?:形式|フォーマット).*(?:不正|違反)",
            r"(?:コード|```|===).*(?:混入|残留)",
            r"プロンプト.*(?:漏洩|混入)",
        ],
        "revision_instruction": "出力フォーマットを厳守し、AI応答文・マークダウン記法・コードブロックが記事本文に混入しないよう徹底すること。",
    },
    "factual_error": {
        "label": "事実誤認・架空情報",
        "patterns": [
            r"(?:事実|ファクト).*(?:誤り|誤認|間違|不正確)",
            r"架空.*(?:情報|アーティスト|イベント|グループ)",
            r"(?:虚偽|嘘|捏造|でっち上げ)",
            r"(?:存在しない|実在しない)",
            r"未検証.*(?:情報|事実|データ)",
        ],
        "revision_instruction": "全事実をWebSearchで再検証し、確認が取れない情報は削除すること。架空のアーティスト・イベントは絶対に記載しないこと。",
    },
}


# ── 却下理由パーサー ────────────────────────────────────────────

def parse_rejection(arceus_report_path: str) -> dict:
    """
    arceus出力ファイルから却下理由を構造化抽出。

    Returns:
        {
            "rejected": bool,
            "rejection_line": str,          # 却下行そのもの
            "reason_text": str,             # 「：」以降の理由テキスト
            "categories": [str],            # マッチしたカテゴリID
            "category_labels": [str],       # カテゴリの日本語ラベル
            "agent_scores": dict,           # エージェント別採点（抽出できた場合）
            "improvement_notes": [str],     # 改善指摘事項
            "raw_excerpt": str,             # レポート末尾200文字
        }
    """
    path = Path(arceus_report_path)
    if not path.exists():
        return {"rejected": False, "error": "file not found"}

    text = path.read_text(encoding="utf-8", errors="replace")

    result = {
        "rejected": False,
        "rejection_line": "",
        "reason_text": "",
        "categories": [],
        "category_labels": [],
        "agent_scores": {},
        "improvement_notes": [],
        "raw_excerpt": text[-300:] if len(text) > 300 else text,
    }

    # 却下行の検出
    reject_patterns = [
        r'❌\s*投稿却下[：:]\s*(.*)',
        r'投稿判定.*却下[：:]\s*(.*)',
        r'却下.*[（(]REJECT[)）][：:]?\s*(.*)',
        r'REJECT[：:]\s*(.*)',
    ]
    for pat in reject_patterns:
        m = re.search(pat, text)
        if m:
            result["rejected"] = True
            result["rejection_line"] = m.group(0).strip()
            result["reason_text"] = m.group(1).strip() if m.group(1) else ""
            break

    if not result["rejected"]:
        # 「条件付き承認」も却下扱い
        if "条件付き承認" in text:
            result["rejected"] = True
            result["rejection_line"] = "条件付き承認（禁止表現 → 却下扱い）"
            result["reason_text"] = "禁止表現使用"
        # 承認行が見つからない場合
        elif not re.search(r'✅\s*投稿承認', text):
            result["rejected"] = True
            result["rejection_line"] = "承認確認不可（安全停止）"
            result["reason_text"] = "承認キーワード未検出"

    if not result["rejected"]:
        return result

    # 却下理由のカテゴリ分類
    full_text = result["reason_text"] + " " + text[-1000:]
    for cat_id, cat_def in REJECTION_CATEGORIES.items():
        for pat in cat_def["patterns"]:
            if re.search(pat, full_text, re.IGNORECASE):
                if cat_id not in result["categories"]:
                    result["categories"].append(cat_id)
                    result["category_labels"].append(cat_def["label"])
                break

    # カテゴリが特定できなかった場合 → quality_low をデフォルト
    if not result["categories"]:
        result["categories"].append("quality_low")
        result["category_labels"].append("品質不足・情報密度低")

    # エージェント別スコア抽出（「デオキシス: 35/50」形式）
    score_pattern = re.compile(
        r'(?:デオキシス|メタモン|ジラーチ|ラプラス|ミミッキュ|ウソッキー|フシギバナ|ミュウツー|アラカザム|ゲンガー|カイリュー|ペルシアン)[：:]\s*(\d+)/(\d+)',
    )
    for m in score_pattern.finditer(text):
        agent_name = m.group(0).split("：")[0].split(":")[0]
        result["agent_scores"][agent_name] = {
            "score": int(m.group(1)),
            "max": int(m.group(2)),
        }

    # 改善指摘の抽出（「改善」「修正」「必要」を含む行）
    for line in text.splitlines():
        line = line.strip()
        if re.search(r'(改善|修正|不足|要改善|推奨|すべき)', line) and len(line) > 10:
            # スコア行・判定行は除外
            if not re.search(r'^\d+|✅|❌|^#|^\||^-{3}', line):
                result["improvement_notes"].append(line[:150])

    result["improvement_notes"] = result["improvement_notes"][:10]

    return result


# ── リビジョンリクエスト生成 ────────────────────────────────────

def generate_revision_prompt(
    arceus_report_path: str,
    original_article_path: str,
    attempt: int = 1,
) -> str:
    """
    arceus却下理由からdeoxys向けリビジョンプロンプトを生成。

    Returns:
        deoxysに渡すリビジョン指示プロンプト文字列
    """
    rejection = parse_rejection(arceus_report_path)
    if not rejection["rejected"]:
        return ""

    original_path = Path(original_article_path)
    original_title = ""
    original_first_lines = ""
    if original_path.exists():
        content = original_path.read_text(encoding="utf-8", errors="replace")
        lines = content.strip().splitlines()
        if lines:
            original_title = lines[0].strip()
        original_first_lines = "\n".join(lines[:5])

    # カテゴリ別の修正指示を結合
    revision_instructions = []
    for cat_id in rejection["categories"]:
        cat_def = REJECTION_CATEGORIES.get(cat_id, {})
        instruction = cat_def.get("revision_instruction", "")
        if instruction:
            revision_instructions.append(f"- {instruction}")

    # arceusの個別指摘事項
    if rejection["improvement_notes"]:
        revision_instructions.append("")
        revision_instructions.append("【arceusからの具体的指摘】")
        for note in rejection["improvement_notes"][:5]:
            revision_instructions.append(f"- {note}")

    # リビジョン回数に応じた強度調整
    if attempt >= MAX_REVISION_ATTEMPTS:
        urgency = "これが最終リビジョンです。上記の修正を確実に反映してください。修正できない項目がある場合は、その理由を明記し可能な範囲で最善の記事を出力してください。"
    else:
        urgency = f"リビジョン{attempt}回目です。上記の指摘事項を修正した記事を再出力してください。"

    prompt = f"""DEOXYS_REVISION_REQUEST
---
【リビジョン指示（arceus却下からの差し戻し・{attempt}回目）】

元記事タイトル: {original_title}
却下理由: {rejection['reason_text']}
却下カテゴリ: {', '.join(rejection['category_labels'])}

【必須修正事項】
{chr(10).join(revision_instructions)}

【{urgency}】

【出力形式】1行目：タイトルのみ 2行目：空行 3行目以降：<h2>から始まるHTML
【重要】必ずWebSearchで最新情報を確認してから記事を修正せよ。
---

以下が元記事の冒頭です。この記事を上記の指摘に基づいて修正・改善してください:

{original_first_lines}
"""
    return prompt


# ── 却下ログ記録 ────────────────────────────────────────────────

def log_rejection(
    rejection: dict,
    run_id: str = "",
    attempt: int = 1,
    revision_result: str = "",
) -> None:
    """却下履歴をJSONLに追記"""
    LOGS.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "run_id": run_id,
        "attempt": attempt,
        "rejection_line": rejection.get("rejection_line", ""),
        "reason_text": rejection.get("reason_text", ""),
        "categories": rejection.get("categories", []),
        "agent_scores": rejection.get("agent_scores", {}),
        "improvement_notes": rejection.get("improvement_notes", []),
        "revision_result": revision_result,
    }
    with open(REJECTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 却下統計 ────────────────────────────────────────────────────

def print_rejection_stats():
    """却下パターンの統計を表示"""
    if not REJECTION_LOG.exists():
        print("却下ログなし（arceus_rejections.jsonl が空）")
        return

    records = []
    for line in REJECTION_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    if not records:
        print("却下ログなし")
        return

    total = len(records)
    cat_counts = Counter()
    revision_success = 0
    revision_fail = 0

    for r in records:
        for c in r.get("categories", []):
            cat_counts[c] += 1
        rv = r.get("revision_result", "")
        if rv == "approved_after_revision":
            revision_success += 1
        elif rv == "rejected_again":
            revision_fail += 1

    print(f"\n=== arceus却下統計 ===")
    print(f"  総却下数: {total}")
    print(f"  リビジョン成功: {revision_success} / リビジョン失敗: {revision_fail}")
    if revision_success + revision_fail > 0:
        rate = revision_success / (revision_success + revision_fail)
        print(f"  リビジョン成功率: {rate:.0%}")
    print(f"\n  カテゴリ別:")
    for cat, count in cat_counts.most_common():
        label = REJECTION_CATEGORIES.get(cat, {}).get("label", cat)
        print(f"    {label}: {count}件")
    print()


# ── 却下パターン→エージェント学習注入 ──────────────────────────

def inject_rejection_learning():
    """
    却下パターンの傾向をdeoxys_kpop.md / metamon_kpop.md の
    AUTO-LEARNEDセクションに注入する（apply_learning_to_agents.pyと連携）。
    """
    if not REJECTION_LOG.exists():
        print("却下ログなし — スキップ")
        return

    # 直近30日の却下を集計
    cutoff = (datetime.now(JST) - timedelta(days=30)).isoformat()
    records = []
    for line in REJECTION_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("timestamp", "") >= cutoff:
                records.append(r)
        except Exception:
            pass

    if not records:
        print("直近30日の却下なし — スキップ")
        return

    cat_counts = Counter()
    common_notes = Counter()
    for r in records:
        for c in r.get("categories", []):
            cat_counts[c] += 1
        for note in r.get("improvement_notes", []):
            # ノートを正規化してカウント
            norm = re.sub(r'[\d]+', 'N', note[:60])
            common_notes[norm] += 1

    # 学習データをJSONとして保存（apply_learning_to_agents.pyが読み込む）
    learning_data = {
        "updated_at": datetime.now(JST).isoformat(),
        "period_days": 30,
        "total_rejections": len(records),
        "category_counts": dict(cat_counts.most_common()),
        "top_improvement_notes": [
            {"note": note, "count": count}
            for note, count in common_notes.most_common(10)
        ],
        "revision_success_count": sum(
            1 for r in records if r.get("revision_result") == "approved_after_revision"
        ),
        "revision_fail_count": sum(
            1 for r in records if r.get("revision_result") == "rejected_again"
        ),
    }

    output_path = LOGS / "arceus_rejection_patterns.json"
    output_path.write_text(
        json.dumps(learning_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  却下パターン学習データ保存: {output_path}")
    print(f"  総却下: {len(records)}件 カテゴリ: {dict(cat_counts.most_common(3))}")

    return learning_data


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="arceus却下→deoxysリビジョンエンジン v1.0")
    sub = parser.add_subparsers(dest="command")

    p_parse = sub.add_parser("parse-rejection", help="arceus出力から却下理由を抽出")
    p_parse.add_argument("report", help="arceus出力ファイルパス")

    p_gen = sub.add_parser("generate-revision", help="リビジョンプロンプトを生成")
    p_gen.add_argument("--arceus-report", required=True)
    p_gen.add_argument("--original-article", required=True)
    p_gen.add_argument("--attempt", type=int, default=1)

    sub.add_parser("stats", help="却下統計を表示")
    sub.add_parser("inject-learning", help="却下パターンをagentsに注入")

    args = parser.parse_args()

    if args.command == "parse-rejection":
        result = parse_rejection(args.report)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "generate-revision":
        prompt = generate_revision_prompt(
            args.arceus_report,
            args.original_article,
            args.attempt,
        )
        if prompt:
            print(prompt)
        else:
            print("(却下ではありません — リビジョン不要)", file=sys.stderr)
            sys.exit(1)

    elif args.command == "stats":
        print_rejection_stats()

    elif args.command == "inject-learning":
        inject_rejection_learning()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
