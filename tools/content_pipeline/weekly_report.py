#!/usr/bin/env python3
"""週次レポート reports/weekly-<date>.md(毎週月曜 cron)。

中身:
  1. 倍増目標に対するトラフィック(GA4。基準=10月の Direct 除きセッション 11,565/月=373/日、
     目標はその2倍。Direct は滞在2〜4秒の bot が多いので除く [[mama-hub-is-36pct-of-organic-cliff-after-1121]])
  2. GSC: 直近7日 vs その前7日で伸びたクエリ・落ちたクエリ上位
  3. AI 経由の流入(ChatGPT/Perplexity/Gemini/Copilot 等。tools/ai_traffic_report.py の判定を流用)
  4. X の URL 位置 A/B: 配置(reply/body)ごとの投稿数・表示数(中央値/合計)・GA4 セッション
  5. 自律パイプラインの週次実績(発見・公開・却下)
  6. 来週に最も効果の大きい記事案3つ(上の数字+候補一覧から claude -p が選ぶ。失敗時は機械順位)

GA4・GSC とも確定に2〜3日かかるので、窓は各ツールの LAG に従う(直近の途中値を掴まない)。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.content_pipeline import common as C  # noqa: E402

BASELINE_OCT_NON_DIRECT = 11565      # 2026年10月 GA4 セッション(Direct/(not set) 除き)
BASELINE_PER_DAY = BASELINE_OCT_NON_DIRECT / 31
TARGET_PER_DAY = BASELINE_PER_DAY * 2


def traffic() -> dict:
    from tools.x_traffic_report import _run
    out = {}
    for label, days in (("7d", 7), ("28d", 28)):
        rows = _run(["sessionSource"], ["sessions"], days)
        total = sum(r["sessions"] for r in rows)
        direct = sum(r["sessions"] for r in rows if r["sessionSource"] in ("(direct)", "(not set)"))
        out[label] = {"days": days, "total": total, "direct": direct, "non_direct": total - direct,
                      "per_day": (total - direct) / days,
                      "top": sorted(rows, key=lambda r: -r["sessions"])[:6]}
    prev = _run(["sessionSource"], ["sessions"], 14)
    p_total = sum(r["sessions"] for r in prev)
    p_direct = sum(r["sessions"] for r in prev if r["sessionSource"] in ("(direct)", "(not set)"))
    out["prev7_per_day"] = ((p_total - p_direct) - out["7d"]["non_direct"]) / 7
    return out


def gsc_movers(n: int = 10) -> dict:
    from tools.seo.gsc_snapshot import _query, _range, _svc
    svc = _svc()
    cur = {r["keys"][0]: r for r in _query(svc, ["query"], 7, 0, 2000)}
    prv = {r["keys"][0]: r for r in _query(svc, ["query"], 7, 7, 2000)}
    tot = lambda rows: (sum(r["clicks"] for r in rows.values()), sum(r["impressions"] for r in rows.values()))  # noqa: E731
    deltas = []
    for q in set(cur) | set(prv):
        c, p = cur.get(q, {}), prv.get(q, {})
        deltas.append({"query": q, "clicks": c.get("clicks", 0), "prev_clicks": p.get("clicks", 0),
                       "imp": c.get("impressions", 0), "prev_imp": p.get("impressions", 0),
                       "pos": round(c.get("position", 0), 1), "prev_pos": round(p.get("position", 0), 1),
                       "d_clicks": c.get("clicks", 0) - p.get("clicks", 0),
                       "d_imp": c.get("impressions", 0) - p.get("impressions", 0)})
    key = lambda d: (d["d_clicks"], d["d_imp"])  # noqa: E731
    return {"window": _range(7, 0), "prev_window": _range(7, 7), "cur_total": tot(cur), "prev_total": tot(prv),
            "up": sorted(deltas, key=key, reverse=True)[:n], "down": sorted(deltas, key=key)[:n]}


def ai_traffic() -> dict:
    from tools.ai_traffic_report import collect
    return collect(7)


def ab_results() -> dict:
    """URL 位置 A/B。表示数は X API の public_metrics、セッションは GA4 の utm_content。"""
    from tools.x_auto_repause_guard import _impressions
    ids = {"reply": [], "body": []}
    for line in (C.BASE / "logs" / "x_ab_log.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("url_pos") in ids and d.get("ts", "") >= "2026-11-06T13" and d.get("tweet_id"):
            ids[d["url_pos"]].append(str(d["tweet_id"]))
    out = {}
    for pos, tids in ids.items():
        try:
            imps = _impressions(tids) if tids else []
        except Exception as e:  # noqa: BLE001
            imps, out[f"{pos}_error"] = [], str(e)[:120]
        out[pos] = {"posts": len(tids), "imp_measured": len(imps),
                    "imp_median": statistics.median(imps) if imps else None, "imp_total": sum(imps)}
    try:
        from tools.x_traffic_report import _run
        rows = _run(["sessionManualAdContent"], ["sessions", "userEngagementDuration"], 28)
        for r in rows:
            if r["sessionManualAdContent"] in ("reply", "body"):
                out[r["sessionManualAdContent"]]["ga4_sessions_28d"] = r["sessions"]
                out[r["sessionManualAdContent"]]["ga4_sec_per_session"] = round(
                    r["userEngagementDuration"] / r["sessions"], 1) if r["sessions"] else 0
    except Exception as e:  # noqa: BLE001
        out["ga4_error"] = str(e)[:120]
    try:
        out["state"] = json.loads((C.BASE / "data" / "x_url_pos_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out["state"] = {}
    return out


def pipeline_week() -> dict:
    since = (datetime.now() - timedelta(days=7)).isoformat()
    cnt: dict = {}
    if C.PIPELINE_LOG.exists():
        for line in C.PIPELINE_LOG.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("ts", "") >= since:
                cnt[e["stage"]] = cnt.get(e["stage"], 0) + (e.get("added", 1) if e["stage"] == "monitor" else 1)
    cost = 0.0
    if C.COST_LOG.exists():
        for line in C.COST_LOG.read_text(encoding="utf-8").splitlines():
            p = line.split("\t")
            if len(p) >= 3 and p[0] >= since:
                cost += float(p[2] or 0)
    placements = []
    if C.PLACEMENT_LOG.exists():
        placements = [l.split("\t") for l in C.PLACEMENT_LOG.read_text(encoding="utf-8").splitlines()[1:]
                      if l[:19] >= since[:19]]
    return {"counts": cnt, "cost_usd": round(cost, 2), "placements": placements,
            "hub_updates": [r for r in C.read_queue() if r["status"] == "HUB_UPDATE"]}


IDEA_PROMPT = """あなたは KPOP JOURNAL の編集長です。下のデータだけを根拠に、**来週({WEEK})に書く/直すと最も流入が増える記事案を3つ**選んでください。
効果の見積もり(週あたりの追加クリック/セッションの概算と根拠の数字)を必ず付けること。データに無い需要を想像で作らないこと。

このサイトで実測済みの教訓:
- 流入の柱は当たり記事数本。速報1本の平均は約1.7クリック、当たり1本は数百。量産は効かない
- 既存記事と同じ検索意図の新記事はカニバリになる → 既存記事のリライト/追記を優先
- 「相関図」クエリはゼロクリック(Kドラマ)。高順位×低CTRは意図不一致で追っても回収できない
- 検索語をタイトル先頭に置く。表記ゆれは両方入れる
- 授賞式・特番は「開催2〜3週間前にハブ、当日に結果追記」が勝ち筋。Bing 流入が Google より多い
- MAMA ハブ1本が自然検索の36%(11/20-21開催)。終了後は崖になるので後継の年末ハブが要る
- 公演ツアー・劇場映画の先回りは不発。Netflix 等の配信作と中継のある授賞式に絞る

## 倍増目標に対する現状
{TRAFFIC}

## GSC 伸びた/落ちたクエリ
{GSC}

## 今後の日程(監視対象)
{EVENTS}

## 伸ばせる候補(winnable_queue 上位)
{WINNABLE}

## 既存ハブへの追記候補(監視で検出)
{HUBS}

最後に ```json で {{"ideas": [{{"title": "記事案(新規 or 『既存記事名』に追記)", "type": "new|rewrite|update", "target_query": "...", "expected_weekly_clicks": 数値, "why": "根拠の数字", "deadline": "YYYY-MM-DD"}}]}} を返す。"""


def ideas(tr: dict, gs: dict, pw: dict, use_claude: bool = True) -> list[dict]:
    w = json.loads((C.CONTENT / "watchlist.json").read_text(encoding="utf-8")) \
        if (C.CONTENT / "watchlist.json").exists() else {"events": []}
    try:
        win = json.loads((C.BASE / "data" / "winnable_queue.json").read_text(encoding="utf-8"))
        win = (win if isinstance(win, list) else win.get("queue") or win.get("items") or [])[:15]
    except (OSError, ValueError):
        win = []
    today = date.today()
    prompt = IDEA_PROMPT.format(
        WEEK=f"{today + timedelta(days=(7 - today.weekday()) % 7 or 7)} の週",
        TRAFFIC=json.dumps({k: v for k, v in tr.items() if k != "28d"}, ensure_ascii=False, default=str)[:3000],
        GSC=json.dumps({"up": gs["up"], "down": gs["down"]}, ensure_ascii=False)[:5000],
        EVENTS=json.dumps(w.get("events", []), ensure_ascii=False)[:4000],
        WINNABLE=json.dumps(win, ensure_ascii=False)[:3000],
        HUBS=json.dumps([{k: h[k] for k in ("subject", "claim", "hub_post_id")} for h in pw["hub_updates"]],
                        ensure_ascii=False)[:2000])
    try:
        if not use_claude:
            raise LookupError("--no-ideas")
        out = C.run_claude("weekly_ideas", prompt, allowed_tools=[], budget_usd=0.8, timeout=600)
        got = C.extract_json(out).get("ideas", [])[:3]
        if got:
            return got
    except LookupError:
        pass
    except Exception as e:  # noqa: BLE001
        C.log_event("weekly_ideas_error", error=str(e)[:300])
    # 機械順位(claude が使えないときの予備): 表示が伸びたのに順位4〜15位でクリックが取り切れて
    # いないクエリ。目標CTR 5%(pos5-7帯の実測5.20%)との差を見込みとする。
    cand = []
    for g in sorted(gs["up"] + gs["down"], key=lambda g: -g["imp"]):
        gain = round(g["imp"] * 0.052 - g["clicks"], 1)
        if 4 <= g["pos"] <= 15 and gain > 0:
            cand.append({"title": f"「{g['query']}」の受け記事を上位へ(リライト)", "type": "rewrite",
                         "target_query": g["query"], "expected_weekly_clicks": gain,
                         "why": f"表示 {g['prev_imp']}→{g['imp']}・順位 {g['pos']}・クリック {g['clicks']}"
                                "(機械選定: claude 不可時の予備)", "deadline": ""})
    return cand[:3]


def _pct(a, b):
    return f"{(a - b) / b * 100:+.0f}%" if b else "—"


def render(tr, gs, ai, ab, pw, ids) -> str:
    t7 = tr["7d"]
    L = [f"# 週次レポート {date.today().isoformat()}", "",
         f"生成: {C.now()} / GA4・GSC は確定待ちのため数日前までの窓", "",
         "## 1. 倍増目標に対するトラフィック(GA4・Direct 除き)", "",
         "| 指標 | 値 |", "|---|---|",
         f"| 基準(2026年10月) | {BASELINE_PER_DAY:.0f} セッション/日 |",
         f"| 目標(基準の2倍) | {TARGET_PER_DAY:.0f} セッション/日 |",
         f"| 直近7日 | **{t7['per_day']:.0f} セッション/日**(目標の {t7['per_day'] / TARGET_PER_DAY * 100:.0f}%) |",
         f"| その前の7日 | {tr['prev7_per_day']:.0f} セッション/日({_pct(t7['per_day'], tr['prev7_per_day'])}) |",
         f"| 直近28日 | {tr['28d']['per_day']:.0f} セッション/日 |",
         f"| 直近7日の Direct(参考・bot 多) | {t7['direct']:,}({t7['direct'] / t7['total'] * 100:.0f}%) |", "",
         "流入元 上位(7日): " + "、".join(f"{r['sessionSource']} {r['sessions']:,}" for r in t7["top"]), "",
         "## 2. 検索クエリ(GSC・7日 vs 前7日)", "",
         f"窓 {gs['window'][0]}〜{gs['window'][1]}(前: {gs['prev_window'][0]}〜{gs['prev_window'][1]})。"
         f"クエリ別の合計(GSC が匿名化したクエリは含まない) クリック {gs['cur_total'][0]:,}({_pct(gs['cur_total'][0], gs['prev_total'][0])})・"
         f"表示 {gs['cur_total'][1]:,}({_pct(gs['cur_total'][1], gs['prev_total'][1])})", ""]
    for title, rows in (("伸びたクエリ", gs["up"]), ("落ちたクエリ", gs["down"])):
        L += [f"### {title}", "", "| クエリ | クリック | 表示 | 順位 |", "|---|---|---|---|"]
        L += [f"| {r['query']} | {r['prev_clicks']}→{r['clicks']}({r['d_clicks']:+d}) | "
              f"{r['prev_imp']}→{r['imp']} | {r['prev_pos'] or '—'}→{r['pos'] or '—'} |" for r in rows]
        L.append("")
    L += ["## 3. AI 経由の流入(GA4・7日)", "",
          f"期間 {ai.get('period', '')}: AI 経由 **{sum(ai.get('windows_ai', [0])):,}** セッション"
          f"(全体 {sum(ai.get('windows_total', [0])):,} の "
          f"{sum(ai.get('windows_ai', [0])) / max(1, sum(ai.get('windows_total', [1]))) * 100:.1f}%)", "",
          "内訳: " + ("、".join(f"{k} {v}" for k, v in ai.get("by_family", {}).items()) or "なし"), "",
          "着地ページ上位: " + "、".join(f"{p} {n}" for p, n in ai.get("top_landing", [])[:5]), "",
          "## 4. X の URL 位置 A/B(2026-11-06〜)", "",
          "| 配置 | 投稿数 | 表示数 中央値 | 表示数 合計 | GA4 セッション(28日) | 滞在秒/セッション |",
          "|---|---|---|---|---|---|"]
    for pos, name in (("reply", "返信に URL"), ("body", "本文に URL")):
        a = ab.get(pos, {})
        L.append(f"| {name}({pos}) | {a.get('posts', 0)} | {a.get('imp_median') or '—'} | "
                 f"{a.get('imp_total', 0):,} | {a.get('ga4_sessions_28d', 0)} | {a.get('ga4_sec_per_session', '—')} |")
    st = ab.get("state", {})
    n_min = min(ab.get("reply", {}).get("posts", 0), ab.get("body", {}).get("posts", 0))
    L += ["", f"判定: " + (f"勝者 **{st['winner']}**({st.get('decided_at', '')})" if st.get("winner") else
                         f"未決(各腕15本で判定の約束。少ない側 {n_min} 本)。パイプラインの投稿は A/B 割当に従っている"),
          ("body は停止中(ガード判定)" if st.get("body_enabled") is False else ""), "",
          "## 5. 自律パイプライン(7日)", "",
          "| 段 | 件数 |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(pw["counts"].items())] or ["| (実行なし) | 0 |"]
    L += ["", f"claude -p 費用: ${pw['cost_usd']}", ""]
    if pw["placements"]:
        L += ["X 投稿の配置記録:", ""] + [f"- {p[0][:16]} post {p[2]} → **{p[3]}**({p[4]})" for p in pw["placements"]] + [""]
    if pw["hub_updates"]:
        L += ["既存ハブへの追記待ち(人が追記):", ""] + \
             [f"- #{h['id']} post {h['hub_post_id']}: {h['claim'][:80]}" for h in pw["hub_updates"]] + [""]
    L += ["## 6. 来週に最も効果の大きい記事案", ""]
    for i, d in enumerate(ids, 1):
        L += [f"{i}. **{d.get('title')}**({d.get('type', '')}・狙う語「{d.get('target_query', '')}」・"
              f"見込み 週+{d.get('expected_weekly_clicks', '?')} クリック・期限 {d.get('deadline') or '—'})",
              f"   - 根拠: {d.get('why', '')}"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ideas", action="store_true", help="記事案の claude -p を呼ばない(機械順位のみ)")
    a = ap.parse_args()
    errs = []

    def safe(fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{fn.__name__}: {e}")
            return default
    tr = safe(traffic, {"7d": {"per_day": 0, "total": 1, "direct": 0, "top": []}, "28d": {"per_day": 0},
                        "prev7_per_day": 0})
    gs = safe(gsc_movers, {"window": ("", ""), "prev_window": ("", ""), "cur_total": (0, 0),
                           "prev_total": (0, 0), "up": [], "down": []})
    ai = safe(ai_traffic, {})
    ab = safe(ab_results, {})
    pw = safe(pipeline_week, {"counts": {}, "cost_usd": 0, "placements": [], "hub_updates": []})
    ids = ideas(tr, gs, pw, use_claude=not a.no_ideas)
    md = render(tr, gs, ai, ab, pw, ids)
    if errs:
        md += "\n## 取得できなかったデータ\n\n" + "\n".join(f"- {e}" for e in errs) + "\n"
    out = C.BASE / "reports" / f"weekly-{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    t7 = tr["7d"]["per_day"]
    C.notify("[週次レポート]", f"{out.name}: 直近7日 {t7:.0f}/日(目標 {TARGET_PER_DAY:.0f}/日の "
             f"{t7 / TARGET_PER_DAY * 100:.0f}%)。記事案1: {ids[0]['title'] if ids else '—'}",
             key=f"weekly_{date.today()}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
