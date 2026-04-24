#!/usr/bin/env python3
"""
lib/meeting_digest_builder.py
会議体・議事録ダイジェスト生成
各ログから最新の要点を3〜5行に要約してダッシュボード表示用HTMLを生成する
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
MINUTES_DIR = LOGS / "meeting_minutes"

# ─── 会議体定義 ─────────────────────────────────────────────
MEETINGS = [
    {
        "id": "management",
        "label": "経営会議",
        "icon": "👑",
        "color": "#c084fc",
        "log_sources": ["logs/ai_meeting.log", "logs/morning_brief.log"],
        "description": "CEO・経営陣による日次方針決定",
    },
    {
        "id": "editorial",
        "label": "編集会議",
        "icon": "✍️",
        "color": "#818cf8",
        "log_sources": ["logs/breaking_pipeline.log", "logs/chart_pipeline.log"],
        "description": "記事企画・執筆・公開の進捗確認",
    },
    {
        "id": "seo",
        "label": "SEO会議",
        "icon": "🔍",
        "color": "#22d3ee",
        "log_sources": ["logs/category_health.log", "logs/metrics_fetch.log"],
        "description": "検索流入・キーワード戦略の確認",
    },
    {
        "id": "sns",
        "label": "SNS会議",
        "icon": "🐦",
        "color": "#34d399",
        "log_sources": ["logs/x_post.log", "logs/admin_actions.jsonl"],
        "description": "X投稿状況・SNS拡散の確認",
    },
    {
        "id": "audit",
        "label": "品質会議",
        "icon": "🛡️",
        "color": "#fbbf24",
        "log_sources": ["logs/audit_feedback.jsonl", "logs/auto_repair.log"],
        "description": "記事品質・エラー対応の確認",
    },
    {
        "id": "system",
        "label": "システム会議",
        "icon": "⚙️",
        "color": "#fb923c",
        "log_sources": ["logs/dashboard_refresh.log", "logs/ceo_execution_state.json"],
        "description": "インフラ・自動運用の安定確認",
    },
    {
        "id": "finance",
        "label": "財務会議",
        "icon": "💰",
        "color": "#a3e635",
        "log_sources": ["logs/kpi_monthly_snapshot.json", "logs/kpi_posts.jsonl"],
        "description": "収益・KPI進捗の確認",
    },
    {
        "id": "emergency",
        "label": "緊急対応会議",
        "icon": "🚨",
        "color": "#ef4444",
        "log_sources": ["logs/kpi_errors.jsonl", "logs/alert_queue.jsonl"],
        "description": "エラー・異常への緊急対応",
    },
]

def _read_log_tail(path: Path, max_lines: int = 50) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [l.strip() for l in lines[-max_lines:] if l.strip()]
    except Exception:
        return []

def _read_jsonl_tail(path: Path, max_records: int = 10) -> list[dict]:
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records[-max_records:]

def _get_log_last_time(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        mtime = path.stat().st_mtime
        dt = datetime.fromtimestamp(mtime, tz=timezone(timedelta(hours=9)))
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return ""

def _load_minutes(meeting_id: str) -> dict:
    """logs/meeting_minutes/<meeting_id>_latest.json を読む。なければ{}"""
    p = MINUTES_DIR / f"{meeting_id}_latest.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _summarize_meeting(meeting: dict) -> dict:
    """会議体ごとに最新ログから要点を抽出しdictで返す"""
    mid = meeting["id"]

    # まず保存済み議事録があれば使う
    saved = _load_minutes(mid)
    if saved:
        return {
            "last_held": saved.get("last_held", "—"),
            "topics": saved.get("topics", []),
            "decisions": saved.get("decisions", []),
            "issues": saved.get("issues", []),
            "has_data": True,
        }

    # ログから自動生成
    topics = []
    decisions = []
    issues = []
    last_held = "—"

    for src in meeting["log_sources"]:
        p = BASE / src
        if not p.exists():
            continue
        t = _get_log_last_time(p)
        if t and last_held == "—":
            last_held = t

        if src.endswith(".jsonl"):
            records = _read_jsonl_tail(p, 5)
            for r in reversed(records):
                action = r.get("action") or r.get("event") or ""
                msg = r.get("reason") or r.get("message") or r.get("title") or ""
                ts = (r.get("timestamp") or "")[:10]
                if action and msg:
                    topics.append(f"{ts} {_ja_action(action)}: {msg[:40]}")
                elif action:
                    topics.append(f"{ts} {_ja_action(action)}")
        else:
            lines = _read_log_tail(p, 30)
            for line in reversed(lines):
                if any(kw in line for kw in ["完了", "成功", "OK", "✅", "deployed", "generated"]):
                    decisions.append(line[:60])
                    if len(decisions) >= 2:
                        break
            for line in reversed(lines):
                if any(kw in line for kw in ["ERROR", "失敗", "エラー", "FAIL", "WARNING"]):
                    issues.append(line[:60])
                    if len(issues) >= 2:
                        break

    return {
        "last_held": last_held,
        "topics": topics[:3],
        "decisions": decisions[:2],
        "issues": issues[:2],
        "has_data": bool(topics or decisions or issues),
    }

def _ja_action(action: str) -> str:
    """英語アクション名を平易な日本語に変換"""
    m = {
        "draft_": "下書き化",
        "x_backfill_posted": "X投稿完了",
        "x_posted": "X投稿完了",
        "post_published": "記事公開",
        "rewrite_completed": "改善書き直し完了",
        "thumbnail": "サムネ更新",
        "error": "エラー発生",
        "pipeline_stop": "処理停止",
        "submitted": "申請済み",
    }
    for k, v in m.items():
        if k in action:
            return v
    return action[:20]

def _meeting_card_html(meeting: dict, summary: dict) -> str:
    color = meeting["color"]
    label = meeting["label"]
    icon = meeting["icon"]
    desc = meeting["description"]
    last_held = summary["last_held"]
    has_data = summary["has_data"]

    topics_html = ""
    for t in summary["topics"][:3]:
        topics_html += f'<li style="padding:2px 0;color:#94a3b8;font-size:0.75rem">{t[:50]}</li>'
    if not topics_html:
        topics_html = '<li style="color:#475569;font-size:0.72rem">ログ取得中…</li>'

    decisions_html = ""
    for d in summary["decisions"][:2]:
        decisions_html += f'<div style="color:#86efac;font-size:0.72rem;padding:2px 0">✅ {d[:50]}</div>'

    issues_html = ""
    for iss in summary["issues"][:2]:
        issues_html += f'<div style="color:#fca5a5;font-size:0.72rem;padding:2px 0">⚠️ {iss[:50]}</div>'

    border_color = "#ef444466" if summary["issues"] else f"{color}44"

    return f"""<div style="background:#111827;border:1px solid {border_color};border-top:3px solid {color};border-radius:10px;padding:14px;min-width:200px">
  <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
    <span style="font-size:1.1rem">{icon}</span>
    <span style="font-size:0.82rem;font-weight:800;color:{color}">{label}</span>
    <span style="margin-left:auto;font-size:0.65rem;color:#475569">{last_held}</span>
  </div>
  <div style="font-size:0.68rem;color:#475569;margin-bottom:8px">{desc}</div>
  <div style="margin-bottom:6px">
    <div style="font-size:0.65rem;color:#64748b;margin-bottom:4px;font-weight:700">最新議題</div>
    <ul style="margin:0;padding-left:12px">{topics_html}</ul>
  </div>
  {f'<div style="margin-bottom:6px">{decisions_html}</div>' if decisions_html else ''}
  {f'<div>{issues_html}</div>' if issues_html else ''}
</div>"""

# ─── CG. 会議体一覧 HTML ────────────────────────────────────
def build_cg_section() -> str:
    cards = ""
    for meeting in MEETINGS:
        summary = _summarize_meeting(meeting)
        cards += _meeting_card_html(meeting, summary)

    return f"""<div class="section" id="cg-meetings" style="margin-bottom:24px">
  <div class="section-title" style="border-bottom-color:#c084fc33;margin-bottom:16px">
    <span class="section-title-icon">🏛️</span>
    <span style="color:#c084fc;font-size:0.9rem;font-weight:900">CG. 会議体一覧</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">8つの定例会議 — 各会議の最新状況</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px">
    {cards}
  </div>
</div>"""

# ─── CH. 最新議事録 HTML ─────────────────────────────────────
def build_ch_section() -> str:
    """最新の重要決定・問題を横断的に表示"""
    today = datetime.now().strftime("%Y-%m-%d")

    all_decisions = []
    all_issues = []

    for meeting in MEETINGS:
        summary = _summarize_meeting(meeting)
        for d in summary["decisions"]:
            all_decisions.append({"label": meeting["label"], "icon": meeting["icon"],
                                   "color": meeting["color"], "text": d})
        for iss in summary["issues"]:
            all_issues.append({"label": meeting["label"], "icon": meeting["icon"],
                                "color": meeting["color"], "text": iss})

    dec_html = ""
    for item in all_decisions[:6]:
        dec_html += f"""<div style="display:flex;align-items:flex-start;gap:8px;padding:8px;background:#0d1117;border-radius:6px;margin-bottom:6px">
  <span style="font-size:0.9rem">{item['icon']}</span>
  <div>
    <div style="font-size:0.65rem;color:{item['color']};font-weight:700;margin-bottom:2px">{item['label']}</div>
    <div style="font-size:0.75rem;color:#86efac">✅ {item['text'][:60]}</div>
  </div>
</div>"""
    if not dec_html:
        dec_html = '<div style="color:#475569;font-size:0.75rem;padding:8px">本日の決定事項はまだありません</div>'

    iss_html = ""
    for item in all_issues[:4]:
        iss_html += f"""<div style="display:flex;align-items:flex-start;gap:8px;padding:8px;background:#0d1117;border-radius:6px;margin-bottom:6px">
  <span style="font-size:0.9rem">{item['icon']}</span>
  <div>
    <div style="font-size:0.65rem;color:{item['color']};font-weight:700;margin-bottom:2px">{item['label']}</div>
    <div style="font-size:0.75rem;color:#fca5a5">⚠️ {item['text'][:60]}</div>
  </div>
</div>"""
    if not iss_html:
        iss_html = '<div style="color:#22c55e;font-size:0.75rem;padding:8px">✅ 未解決の問題はありません</div>'

    return f"""<div class="section" id="ch-minutes" style="margin-bottom:24px">
  <div class="section-title" style="border-bottom-color:#34d39933;margin-bottom:16px">
    <span class="section-title-icon">📋</span>
    <span style="color:#34d399;font-size:0.9rem;font-weight:900">CH. 最新議事録</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">{today} 時点</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div>
      <div style="font-size:0.72rem;font-weight:800;color:#86efac;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #1e293b">本日の決定事項</div>
      {dec_html}
    </div>
    <div>
      <div style="font-size:0.72rem;font-weight:800;color:#fca5a5;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #1e293b">未解決の問題</div>
      {iss_html}
    </div>
  </div>
</div>"""


if __name__ == "__main__":
    html_cg = build_cg_section()
    html_ch = build_ch_section()
    print(f"CG section: {len(html_cg)} chars")
    print(f"CH section: {len(html_ch)} chars")
