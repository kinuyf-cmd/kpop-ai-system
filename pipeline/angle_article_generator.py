#!/usr/bin/env python3
"""angle_article_generator.py — 多角度テーマを記事にする(探索フェーズ)

owner方針(2026-08-18): しばらくは幅広にいろんな角度から記事を作成し、
データを集めて当たり筋を見つける。聖地巡礼(ロケ地)は放映後に効いてくる。

実装の前提になった発見:
  速報検知(breaking_news_detector)は「24-72h後に feature_article_generator が
  深掘り記事を自動生成する」というコメントを残してテーマを注入していたが、
  **その feature_article_generator は実在しなかった**。
  結果、focus_themes に295件が滞留し、実際に出ていたのは速報そのものだけ。
  直近14日の公開223本を切り口分類しても OST/ロケ地/文化解説は **0本** だった。

  本スクリプトがその消費側を担う。lib/article_angles.py が出す多角度テーマを
  1日 DAILY_CAP 本だけ記事化し、**どの角度が効いたかを後から集計できる形で記録**する。

設計方針:
  - 量産しない。探索が目的なので、角度を散らすことを優先する
  - 事実は Web 検索で裏取りし、裏が取れない主張は書かせない
  - 既存の pre_publish_gate / unified_publish を通す(品質ゲートを迂回しない)
  - status=skip は「書いた」記録にしない。dedup を汚染すると二度と書けなくなる
    ([[openai-credit-exhausted-publish-halt-20260816]] と同じ轍)

usage:
  venv_kpi/bin/python3 pipeline/angle_article_generator.py --dry-run
  venv_kpi/bin/python3 pipeline/angle_article_generator.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
    load_dotenv(str(BASE / ".env"))
except Exception:
    pass

DIRECTIVES = BASE / "config" / "auto_directives.json"
ANGLE_LOG = BASE / "logs" / "angle_articles.jsonl"

# 探索フェーズでも量産はしない。速報が別途日16本出ているため、
# ここを増やすと全体の品質と可視性のリスクが上がる。
DAILY_CAP = 2
# 直近この件数の記事を見て、角度の偏りを判断する
RECENT_WINDOW = 8


def load_angle_themes(path: Path | str = DIRECTIVES) -> list[dict]:
    """focus_themes から angle 由来のテーマだけを、期限内のものに絞って返す。

    breaking_followup(速報の深掘り)は役割が違うので巻き込まない。
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    today = date.today().isoformat()
    out = []
    for t in d.get("focus_themes", []):
        if not str(t.get("source", "")).startswith("angle:"):
            continue
        if (t.get("expires_at") or "9999") < today:
            continue
        out.append(t)
    return out


def _log_rows(log_path: Path | str = ANGLE_LOG) -> list[dict]:
    p = Path(log_path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def already_covered(topic: str, log_path: Path | str = ANGLE_LOG) -> bool:
    """その題材×角度を既に**公開できている**か。

    status='skip' を「書いた」と見なすと、一度失敗しただけで二度と書けなくなる。
    公開できたものだけを dedup の材料にする。
    """
    return any(r.get("topic") == topic and r.get("status") == "publish"
               for r in _log_rows(log_path))


def posted_today(log_path: Path | str = ANGLE_LOG) -> int:
    today = date.today().isoformat()
    return sum(1 for r in _log_rows(log_path)
               if r.get("status") == "publish" and str(r.get("ts", ""))[:10] == today)


def pick_theme(path: Path | str = DIRECTIVES,
               log_path: Path | str = ANGLE_LOG) -> dict | None:
    """次に書くテーマを1件選ぶ。角度が偏らないよう、直近で書いていない角度を優先。"""
    themes = [t for t in load_angle_themes(path)
              if not already_covered(t.get("topic", ""), log_path)]
    if not themes:
        return None
    recent = [r.get("angle") for r in _log_rows(log_path)[-RECENT_WINDOW:]
              if r.get("status") == "publish"]
    def rank(t):
        angle = str(t.get("source", "")).split(":", 1)[-1]
        # 直近に書いた角度ほど後回し(=探索の幅を優先)
        return (recent.count(angle), -float(t.get("buzz_score") or 0))
    themes.sort(key=rank)
    return themes[0]


def _quota_exhausted() -> bool:
    """検索APIが上限到達中か。環境要因のskipを記録から除くために使う。"""
    try:
        from lib.web_factcheck import _tavily_quota_exhausted
        return bool(_tavily_quota_exhausted())
    except Exception:
        return False


def _search_facts(topic: str) -> list[dict]:
    """テーマについて Web 検索し、根拠になりそうな結果を返す。

    裏が取れない題材で書かせないための材料。既存の web_factcheck の
    検索基盤を再利用する(Tavilyのクォータ管理もそちらに従う)。
    """
    try:
        from lib.web_factcheck import _search_tavily, _tavily_quota_exhausted
        if _tavily_quota_exhausted():
            return []
        return _search_tavily(topic, num_results=6) or []
    except Exception:
        return []


def _build_body(theme: dict, facts: list[dict]) -> tuple[str, str]:
    """(title, body_html) を返す。裏が取れなければ ('','') を返す。"""
    if not facts:
        return "", ""
    src = "\n".join(f"- {f.get('title','')}: {(f.get('content') or '')[:300]}"
                    for f in facts[:6])
    try:
        from lib.x_persona_voice import _call_llm
    except Exception:
        return "", ""
    system = (
        "あなたは K-POP・韓国エンタメ専門メディアの編集者です。"
        "与えられた検索結果**だけ**を根拠に、日本語の記事を書きます。"
        "\n【厳守】"
        "\n- 検索結果に無い事実・数字・固有名詞は書かない。推測で補わない"
        "\n- 分からない部分は書かずに飛ばす。断定できないことは『〜とされています』"
        "『公式発表では〜』のように出典の性質を示す"
        "\n- 事務所・アーティストの発表と、ファンの憶測を混ぜない"
        "\n- 煽り表現(衝撃の/驚愕の)、内容の無い定型句は使わない"
        "\n【形式】"
        "\n- 冒頭に3〜4行のリード。その後 <h2> で3〜5セクション"
        "\n- 各セクションは事実→補足の順。箇条書きも使ってよい"
        "\n- 全体で1200〜2000字。HTMLで出力(<h2><p><ul><li>のみ使用)"
        "\n- 最初の行に `TITLE: 記事タイトル` を書き、次の行から本文HTML"
        "\n- タイトルは32字以内で、**読者が検索する語を先頭に置く**"
    )
    user = (f"記事の題材: {theme['topic']}\n"
            f"書き方の指針: {theme.get('hint','')}\n\n"
            f"検索結果(この中の情報だけ使う):\n{src}\n\n"
            "記事:")
    out = (_call_llm(system, user, "editorial") or "").strip()
    if not out:
        return "", ""
    m = re.match(r"\s*TITLE:\s*(.+)", out)
    if not m:
        return "", ""
    title = m.group(1).strip()[:60]
    body = out[m.end():].strip()
    body = re.sub(r"^```(?:html)?|```$", "", body, flags=re.M).strip()
    if len(re.sub(r"<[^>]+>", "", body)) < 600:
        return "", ""
    return title, body


def record(theme: dict, status: str, **extra) -> None:
    ANGLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now().isoformat(),
           "topic": theme.get("topic", ""),
           "angle": str(theme.get("source", "")).split(":", 1)[-1],
           "status": status, **extra}
    with ANGLE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(dry_run: bool = False) -> dict:
    if posted_today() >= DAILY_CAP:
        print(f"[angle] 本日の上限 {DAILY_CAP} 本に到達")
        return {"published": 0, "reason": "daily_cap"}
    theme = pick_theme()
    if not theme:
        print("[angle] 出せるテーマなし(angle由来の期限内テーマが無い)")
        return {"published": 0, "reason": "no_theme"}
    print(f"[angle] 題材: {theme['topic']} ({theme['source']})")

    facts = _search_facts(theme["topic"])
    if not facts:
        # クォータ切れは「このテーマがダメ」ではなく環境要因なので記録しない。
        # 記録すると復帰までの日数×実行回数だけ同じ行が溜まってノイズになる
        # (2026-08-18 時点で Tavily は 9/1 まで上限到達中)。
        quota = _quota_exhausted()
        msg = "クォータ切れ(環境要因)" if quota else "検索結果なし"
        print(f"  裏付けが取れないため見送り: {msg}")
        if not quota:
            record(theme, "skip", reason="no_facts")
        return {"published": 0, "reason": "quota" if quota else "no_facts"}

    title, body = _build_body(theme, facts)
    if not title or not body:
        print("  本文生成に失敗(または短すぎ)")
        record(theme, "skip", reason="generate_fail")
        return {"published": 0, "reason": "generate_fail"}
    print(f"  生成: {title} ({len(re.sub(r'<[^>]+>','',body))}字)")

    if dry_run:
        print("  --dry-run のため公開しない")
        print(re.sub(r"<[^>]+>", "", body)[:300])
        return {"published": 0, "dry_run": True, "title": title}

    try:
        from lib.unified_publisher import unified_publish
        res = unified_publish(
            raw_title=title, body_html=body,
            source_url=(facts[0].get("url") if facts else None),
            kind="feature", confidence="medium",
        )
    except Exception as e:  # noqa: BLE001
        print(f"  公開失敗: {e}")
        record(theme, "skip", reason=f"publish_error: {e}")
        return {"published": 0, "reason": "publish_error"}

    if not res or not res.get("success"):
        reason = (res or {}).get("error", "unknown")
        print(f"  公開されず: {reason}")
        record(theme, "skip", reason=str(reason)[:200])
        return {"published": 0, "reason": "gate_or_publish_fail"}

    pid = res.get("post_id")
    print(f"  ✓ 公開 post_id={pid}")
    record(theme, "publish", post_id=pid, title=title, url=res.get("url", ""))
    return {"published": 1, "post_id": pid, "title": title}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
