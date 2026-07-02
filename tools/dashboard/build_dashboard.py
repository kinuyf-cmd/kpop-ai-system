#!/usr/bin/env python3
"""build_dashboard.py — KPIミニダッシュボードHTML生成(2026-07-02)

既存の成果物JSON(ヘルスチェック/週次レポート/公開ログ)だけを読んで
1ページの自己完結HTMLを生成する。API呼び出しなし=高速・無料・毎日再生成可。

セクション:
  1. ヘルスチェック最新結果(logs/health_check.jsonl 最終行)
  2. GSC 7d clicks 推移(health_check.jsonl の日次蓄積から)
  3. 直近7日の公開数×サムネsource内訳(unified_publish.jsonl)
  4. 週次 勝ち記事/急落(data/weekly_win_report.json)
  5. Lane C候補キュー(data/lane_c_candidates.json)

出力: data/dashboard.html(ローカル閲覧用。本番サイトには置かない)
使い方: venv_kpi/bin/python3 tools/dashboard/build_dashboard.py
        → file:///home/aiuser/kpop-ai-system/data/dashboard.html をブラウザで開く
"""
import collections
import datetime
import html
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
OUT = BASE / "data" / "dashboard.html"


def _tail_jsonl(path, n=None):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return rows[-n:] if n else rows


def _load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def esc(s):
    return html.escape(str(s))


def build():
    now = datetime.datetime.now()
    hc_all = _tail_jsonl(BASE / "logs/health_check.jsonl")
    hc = hc_all[-1] if hc_all else {}
    win = _load_json(BASE / "data/weekly_win_report.json")
    lane = _load_json(BASE / "data/lane_c_candidates.json")

    # 公開×サムネsource 日次(7日)
    pub = _tail_jsonl(BASE / "logs/unified_publish.jsonl")
    daily = collections.defaultdict(lambda: collections.Counter())
    for r in pub:
        ts = str(r.get("ts", ""))[:10]
        if not r.get("success") or not ts:
            continue
        if (now.date() - datetime.date.fromisoformat(ts)).days > 7:
            continue
        src = "no_thumb"
        for x in r.get("log", []):
            if "media_id:" in x and "(" in x:
                s = x.split("(", 1)[1].rstrip(")").lower()
                src = ("dalle" if "dalle" in s else
                       "og" if ("source_site" in s or ("og" in s and "artist" not in s)) else
                       "artist" if ("artist" in s or "cache" in s or "wikimedia" in s) else "other")
                break
        daily[ts][src] += 1

    # GSC clicks推移(health_check蓄積)
    trend = [(r["ts"][:10], r.get("digest", {}).get("gsc_7d_clicks"))
             for r in hc_all if r.get("digest", {}).get("gsc_7d_clicks") is not None]

    # ── HTML ──
    C = {"og": "#4caf7d", "artist": "#4a90d9", "dalle": "#e6a23c", "other": "#999", "no_thumb": "#d66"}
    P = []
    P.append(f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<title>KPOP JOURNAL 運用ダッシュボード</title>
<style>
 body{{font-family:'Hiragino Sans','Noto Sans JP',sans-serif;background:#f5f6f8;color:#222;margin:0;padding:24px}}
 h1{{font-size:20px}} h2{{font-size:15px;border-left:4px solid #e91e8c;padding-left:8px;margin-top:28px}}
 .cards{{display:flex;gap:12px;flex-wrap:wrap}}
 .card{{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 1px 4px rgba(0,0,0,.08);min-width:150px}}
 .num{{font-size:26px;font-weight:700}} .lbl{{font-size:11px;color:#888}}
 table{{border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);font-size:12px}}
 th,td{{padding:6px 10px;border-bottom:1px solid #eee;text-align:left}} th{{background:#fafafa;font-size:11px;color:#666}}
 .ok{{color:#2e7d32}} .warn{{color:#e6a23c;font-weight:600}} .fail{{color:#d32f2f;font-weight:700}}
 .bar{{display:flex;height:18px;border-radius:4px;overflow:hidden;min-width:200px}}
 .seg{{height:100%}} .legend span{{font-size:11px;margin-right:12px}}
 .dot{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:3px}}
 .spark{{display:flex;align-items:flex-end;gap:2px;height:48px}}
 .spark div{{width:14px;background:#e91e8c;border-radius:2px 2px 0 0}}
 .muted{{color:#999;font-size:11px}}
</style></head><body>
<h1>🎤 KPOP JOURNAL 運用ダッシュボード <span class="muted">生成 {now.strftime('%Y-%m-%d %H:%M')}</span></h1>""")

    # 1. サマリカード
    d = hc.get("digest", {})
    alerts = hc.get("active_alerts", "?")
    P.append('<div class="cards">')
    P.append(f'<div class="card"><div class="num {"ok" if alerts == 0 else "warn"}">{alerts}</div><div class="lbl">アクティブ異常(最終チェック {esc(hc.get("ts","?")[:16])})</div></div>')
    P.append(f'<div class="card"><div class="num">{d.get("gsc_7d_clicks","–")}</div><div class="lbl">GSC 7d clicks</div></div>')
    P.append(f'<div class="card"><div class="num">{d.get("published","–")}</div><div class="lbl">昨日の公開数</div></div>')
    dr = d.get("dalle_ratio")
    P.append(f'<div class="card"><div class="num {"warn" if (dr or 0) > .4 else "ok"}">{f"{dr*100:.0f}%" if dr is not None else "–"}</div><div class="lbl">DALL-Eサムネ率(昨日)</div></div>')
    P.append(f'<div class="card"><div class="num">{d.get("meta_null_3d","–")}</div><div class="lbl">メタ未設定(直近3日)</div></div>')
    P.append("</div>")

    # 2. GSC推移スパークバー
    if trend:
        mx = max(v for _, v in trend) or 1
        P.append("<h2>GSC 7d clicks 推移(日次ヘルスチェック蓄積)</h2><div class='spark'>")
        for dt, v in trend[-30:]:
            P.append(f'<div style="height:{max(3, v/mx*48):.0f}px" title="{dt}: {v:.0f}clk"></div>')
        P.append("</div>")

    # 3. 公開×サムネsource
    P.append("<h2>直近7日の公開 × サムネsource</h2>")
    P.append('<div class="legend">' + "".join(
        f'<span><i class="dot" style="background:{c}"></i>{k}</span>' for k, c in C.items()) + "</div>")
    P.append("<table><tr><th>日付</th><th>公開数</th><th>内訳</th></tr>")
    for dt in sorted(daily):
        cnt = daily[dt]
        total = sum(cnt.values())
        segs = "".join(f'<div class="seg" style="width:{v/total*100:.0f}%;background:{C[k]}" title="{k}:{v}"></div>'
                       for k, v in cnt.items() if v)
        P.append(f"<tr><td>{dt}</td><td>{total}</td><td><div class='bar'>{segs}</div></td></tr>")
    P.append("</table>")

    # 4. 勝ち記事/急落
    P.append(f"<h2>週次 勝ち記事 <span class='muted'>{esc(win.get('generated_at','')[:16])}</span></h2>")
    P.append("<table><tr><th></th><th>ページ</th><th>7d clicks</th><th>前週</th><th>pos</th></tr>")
    for w in win.get("wins", [])[:8]:
        P.append(f"<tr><td>🏆</td><td>{esc(w['page'][:60])}</td><td>{w['clicks_7d']:.0f}</td><td>{w['clicks_prev']:.0f}</td><td>{w.get('pos','')}</td></tr>")
    for l in win.get("losses", [])[:4]:
        P.append(f"<tr><td>📉</td><td>{esc(l['page'][:60])}</td><td class='warn'>{l['clicks_7d']:.0f}</td><td>{l['clicks_prev']:.0f}</td><td></td></tr>")
    P.append("</table>")

    # 5. Lane C候補
    P.append("<h2>Lane C 候補キュー(押し上げ余地)</h2>")
    P.append("<table><tr><th>imp</th><th>pos</th><th>クエリ</th><th>ページ</th></tr>")
    for c in lane.get("candidates", [])[:12]:
        P.append(f"<tr><td>{c['imp']:.0f}</td><td>{c['pos']}</td><td>{esc(c['query'][:34])}</td><td>{esc(c['page'][:44])}</td></tr>")
    P.append("</table>")

    # 6. ヘルスチェック明細
    P.append("<h2>ヘルスチェック明細(最新)</h2><table><tr><th>状態</th><th>項目</th></tr>")
    for r in hc.get("results", []):
        cls = {"PASS": "ok", "WARN": "warn", "FAIL": "fail"}.get(r["level"], "")
        P.append(f"<tr><td class='{cls}'>{r['level']}</td><td>{esc(r['msg'][:110])}</td></tr>")
    P.append("</table></body></html>")

    OUT.write_text("\n".join(P), encoding="utf-8")
    print(f"生成: {OUT} ({OUT.stat().st_size//1024}KB)")
    print(f"閲覧: file://{OUT}")


if __name__ == "__main__":
    build()
