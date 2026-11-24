"""監視対象(すでに扱っているアーティスト・イベント・ドラマ)を既存の設定から組み立てる。

出典(手で二重管理しないため、毎回ここから作り直す):
  - config/breaking_priority_artists.json … 速報対象の主要51組(owner決定 2026-10-14)
  - docs/yearend_event_calendar_2026.md  … 年末授賞式・特番と自社ハブ記事(post ID)
  - data/work_clusters.json              … 先回りクラスタで扱ったドラマ
既存の専用監視がある対象(紅白=kouhaku_announce_watch)は handled_elsewhere に入れ、
このパイプラインでは記事化しない(二重公開を防ぐ)。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from tools.content_pipeline.common import BASE, CONTENT, wp

HANDLED_ELSEWHERE = {
    "紅白": "tools/seo/kouhaku_announce_watch.py(11/13〜25 cron)と下書きで対応中",
}


def _events(today: date) -> list[dict]:
    md = (BASE / "docs" / "yearend_event_calendar_2026.md").read_text(encoding="utf-8")
    out = []
    section = ""
    for line in md.splitlines():
        if line.startswith("## "):
            section = line[3:]
        if not line.startswith("|") or "---" in line or "開催日" in line or "イベント |" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if section.startswith("日程が出ているもの") and len(cells) >= 6:
            hub = re.search(r"post (\d+)", cells[5])
            out.append({"event": cells[1], "dates": cells[0], "venue": cells[2],
                        "japan_viewing": cells[3], "hub_post_id": hub.group(1) if hub else "",
                        "status": "日程確定/報道"})
        elif section.startswith("2026年分が未発表") and len(cells) >= 3:
            out.append({"event": cells[0], "dates": "2026年分未発表(前年 " + cells[1] + ")",
                        "watch": cells[2], "hub_post_id": "", "status": "未発表"})
    for e in out:
        for k, why in HANDLED_ELSEWHERE.items():
            if k in e["event"]:
                e["handled_elsewhere"] = why
    return out


def _dramas(today: date) -> list[dict]:
    try:
        works = json.loads((BASE / "data" / "work_clusters.json").read_text(encoding="utf-8"))["works"]
    except (OSError, ValueError, KeyError):
        works = []
    keep = []
    for w in works:
        try:
            rel = date.fromisoformat(w.get("release", ""))
        except ValueError:
            rel = None
        # 配信日の変更・続編・吹替追加を拾うため、配信前〜配信後60日を対象にする
        if rel is None or rel >= today - timedelta(days=60):
            keep.append({"title": w["name"], "release": w.get("release", "")})
    # 先回りクラスタ以外で扱ったKドラマ(カテゴリ kdrama=term 19)の直近60日の記事
    after = (today - timedelta(days=60)).isoformat() + "T00:00:00"
    try:
        rows = wp("GET", f"/posts?status=publish&categories=19&after={after}&per_page=50"
                         "&_fields=id,title&orderby=date&order=desc")
        keep += [{"title": r["title"]["rendered"], "post_id": r["id"]} for r in rows]
    except RuntimeError:
        pass
    return keep


def recent_titles(days: int = 45, limit: int = 200) -> list[str]:
    """自社の最近の公開記事タイトル(重複記事を作らないための照合用)。"""
    after = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    titles = []
    for page in range(1, 3):
        try:
            rows = wp("GET", f"/posts?status=publish&after={after}&per_page=100&page={page}"
                             "&_fields=id,title,link&orderby=date&order=desc")
        except RuntimeError:
            break
        titles += [f"{r['id']}\t{r['title']['rendered']}" for r in rows]
        if len(rows) < 100:
            break
    return titles[:limit]


def build() -> dict:
    today = date.today()
    art = json.loads((BASE / "config" / "breaking_priority_artists.json").read_text(encoding="utf-8"))
    w = {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "artists": sorted(art["artists"].keys()),
         "events": _events(today),
         "dramas": _dramas(today),
         "handled_elsewhere": HANDLED_ELSEWHERE}
    CONTENT.mkdir(parents=True, exist_ok=True)
    (CONTENT / "watchlist.json").write_text(json.dumps(w, ensure_ascii=False, indent=1), encoding="utf-8")
    return w


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=1)[:3000])
