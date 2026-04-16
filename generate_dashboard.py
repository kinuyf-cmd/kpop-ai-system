#!/usr/bin/env python3
"""
generate_dashboard.py — AI会社 統合監視ダッシュボード v2.0
オーナー向け経営画面（CEO=ミュウツー / オーナー=人間閲覧専用）
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "dashboard.html"
JST = timezone(timedelta(hours=9))

def load(fname):
    p = BASE / fname
    return json.loads(p.read_text()) if p.exists() else {}

def rank_color(rank):
    return {"🟢": "#22c55e", "🟡": "#eab308", "🔴": "#ef4444"}.get(rank, "#64748b")

def rank_bg(rank):
    return {
        "🟢": "rgba(34,197,94,0.10)",
        "🟡": "rgba(234,179,8,0.10)",
        "🔴": "rgba(239,68,68,0.12)",
    }.get(rank, "rgba(100,116,139,0.08)")

def sev_color(s):
    return {"high": "#ef4444", "medium": "#eab308", "low": "#22c55e"}.get(s, "#64748b")

def status_badge(status):
    c = {"稼働中":"#22c55e","注意":"#eab308","要改善":"#ef4444","停止":"#6b7280","待機":"#3b82f6","待機中":"#3b82f6"}.get(status,"#6b7280")
    return f'<span style="background:{c}22;color:{c};border:1px solid {c}44;padding:2px 8px;border-radius:99px;font-size:0.72rem;font-weight:700">{status}</span>'

def bar(val, max_val=1.0, color="#22c55e", width=80, height=6):
    pct = min(100, int(val / max_val * 100)) if max_val else 0
    w = int(width * pct / 100)
    return f'<div style="background:#1e293b;border-radius:3px;height:{height}px;width:{width}px;display:inline-block;vertical-align:middle"><div style="background:{color};height:{height}px;border-radius:3px;width:{w}px"></div></div>'

def sparkbar(counts, color="#818cf8"):
    if not counts or all(c == 0 for c in counts):
        return '<span style="color:#374151;font-size:0.72rem">データなし</span>'
    mx = max(counts) or 1
    bars = ""
    days = ["月","火","水","木","金","土","日"]
    for i, c in enumerate(counts):
        h = max(4, int(c / mx * 28))
        bars += f'<div title="{days[i]}:{c}回" style="width:10px;height:{h}px;background:{color};border-radius:2px 2px 0 0;display:inline-block;vertical-align:bottom;margin:0 1px"></div>'
    return f'<div style="display:inline-flex;align-items:flex-end;height:32px">{bars}</div>'

def medal(n):
    return {1:"🥇",2:"🥈",3:"🥉"}.get(n,"")

def fmt_ts(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(JST)
        return dt.strftime("%m/%d %H:%M")
    except:
        return ts[:16]

def pct(v):
    return f"{v:.1%}"

def load_jsonl_safe(fname):
    """JSONLファイルを安全に読み込む（欠損・破損行は無視）"""
    p = BASE / fname
    if not p.exists():
        return []
    records = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return records


def generate():
    # ─── 新セクション群ロード (CA-CJ) ───
    import sys as _sys
    _sys.path.insert(0, str(BASE / "lib"))

    # CA/CB/CC/CD: KPIボード
    try:
        from kpi_dashboard_builder import build_kpi_sections as _build_kpi
        _kpi_parts = _build_kpi(do_snapshot=False)
        _kpi_cd_html = _kpi_parts["cd_html"]
        _kpi_ca_cb_cc_html = _kpi_parts["ca_cb_cc_html"]
    except Exception as _e:
        _kpi_cd_html = f'<div style="color:#ef4444;padding:12px">KPIボード読み込みエラー: {_e}</div>'
        _kpi_ca_cb_cc_html = ""

    # CE/CF: 組織図・部署一覧
    try:
        from org_section_builder import build_org_parts as _build_org
        _org_parts = _build_org()
        _ce_section_html = _org_parts["ce_html"]
        _cf_section_html = _org_parts["cf_html"]
    except Exception as _e:
        _ce_section_html = f'<div style="color:#ef4444;padding:12px">組織図読み込みエラー: {_e}</div>'
        _cf_section_html = ""

    # CG/CH: 会議体・議事録
    try:
        from meeting_digest_builder import build_cg_section as _build_cg, build_ch_section as _build_ch
        _cg_section_html = _build_cg()
        _ch_section_html = _build_ch()
    except Exception as _e:
        _cg_section_html = f'<div style="color:#ef4444;padding:12px">会議体読み込みエラー: {_e}</div>'
        _ch_section_html = ""

    # CJ: 財務ダッシュボード
    try:
        from finance_dashboard_builder import build_cj_section as _build_cj
        _cj_section_html = _build_cj()
    except Exception as _e:
        _cj_section_html = f'<div style="color:#ef4444;padding:12px">財務ダッシュボード読み込みエラー: {_e}</div>'

    # CK: イルミーゼ CTA最適化ダッシュボード
    def _build_ck_section():
        import json as _j
        _logs = BASE / "logs"
        _cta_recs  = []
        _exp_recs  = []
        _kpi_recs  = []
        _cta_file  = _logs / "ui_cta_events.jsonl"
        _exp_file  = _logs / "ui_experiments.jsonl"
        _kpi_file  = _logs / "ui_kpi_snapshots.jsonl"
        if _cta_file.exists():
            for _l in _cta_file.read_text().splitlines()[-7:]:
                try: _cta_recs.append(_j.loads(_l))
                except: pass
        if _exp_file.exists():
            for _l in _exp_file.read_text().splitlines()[-20:]:
                try: _exp_recs.append(_j.loads(_l))
                except: pass
        if _kpi_file.exists():
            for _l in _kpi_file.read_text().splitlines()[-7:]:
                try: _kpi_recs.append(_j.loads(_l))
                except: pass

        _latest_cta = _cta_recs[-1] if _cta_recs else {}
        _latest_kpi = _kpi_recs[-1] if _kpi_recs else {}

        _total_clicks = _latest_cta.get("total_cta_clicks", 0) or 0
        _cta_ctr = _latest_cta.get("cta_ctr_real") or 0
        _imp  = _latest_cta.get("fixed_cta_impression", 0) or 0
        _fclk = _latest_cta.get("cta_click_fixed_bar", 0) or 0
        _fcls = _latest_cta.get("fixed_cta_close", 0) or 0
        _fclk_rate = _fclk / _imp if _imp > 0 else 0
        _fcls_rate = _fcls / _imp if _imp > 0 else 0

        _top  = _latest_cta.get("cta_click_top", 0) or 0
        _mid  = _latest_cta.get("cta_click_middle", 0) or 0
        _bot  = _latest_cta.get("cta_click_bottom", 0) or 0
        _ttl  = max(_total_clicks, 1)

        _win_exp  = [e for e in _exp_recs if e.get("status") == "win"]
        _lose_exp = [e for e in _exp_recs if e.get("status") == "lose"]
        _pend_exp = [e for e in _exp_recs if e.get("status") == "pending"]
        _prov_exp = [e for e in _exp_recs if e.get("status") in ("provisional_win","provisional_lose")]

        _cta_src  = _latest_kpi.get("cta_source", "proxy")
        _src_badge_color = "#22c55e" if _cta_src == "ga4_real" else "#f59e0b"
        _src_label = "🔬 GA4実測" if _cta_src == "ga4_real" else "📊 代替指標"

        _recent_loses = sum(1 for e in _exp_recs[-5:] if e.get("status") == "lose")
        _ui_state = "🟢 GOOD" if _recent_loses == 0 else ("🟡 WATCH" if _recent_loses < 3 else "🔴 DANGER")
        _state_color = {"🟢 GOOD":"#22c55e","🟡 WATCH":"#f59e0b","🔴 DANGER":"#ef4444"}.get(_ui_state,"#64748b")

        # 記事タイプ×位置クロス集計
        _type_rows = ""
        _type_data = _latest_cta.get("type_breakdown", {})
        for _at, _pm in sorted(_type_data.items()):
            _cells = "".join(
                f'<td style="text-align:center;color:#e2e8f0">{_pm.get(p,0)}</td>'
                for p in ["top","middle","bottom","fixed_bar"]
            )
            _type_rows += f'<tr><td style="color:#94a3b8;font-size:0.78rem">{_at}</td>{_cells}</tr>'
        if not _type_rows:
            _type_rows = '<tr><td colspan="5" style="color:#374151;text-align:center;padding:8px">データなし</td></tr>'

        # 最新実験リスト
        _exp_rows = ""
        for _exp in reversed(_exp_recs[-5:]):
            _st = _exp.get("status","?")
            _icon = {"win":"✅","lose":"❌","pending":"⏳","neutral":"➡️","provisional_win":"🔬✅","provisional_lose":"🔬❌","rollback":"🔄"}.get(_st,"?")
            _eid  = _exp.get("experiment_id","?")[-16:]
            _dctr = _exp.get("delta_ctr", 0)
            _ddwl = _exp.get("delta_dwell", 0)
            _dcta = _exp.get("delta_cta", 0)
            _jmode = "final" if _exp.get("judgment_mode") == "final" else ("仮" if _st in ("provisional_win","provisional_lose") else "—")
            _exp_rows += f"""<tr>
              <td style="font-size:0.72rem;color:#94a3b8">{_eid}</td>
              <td style="text-align:center">{_icon}</td>
              <td style="text-align:right;color:{'#22c55e' if _dctr >= 0 else '#ef4444'};font-size:0.72rem">{_dctr:+.4f}</td>
              <td style="text-align:right;color:{'#22c55e' if _ddwl >= 0 else '#ef4444'};font-size:0.72rem">{_ddwl:+.1f}s</td>
              <td style="text-align:center;font-size:0.65rem;color:#94a3b8">{_jmode}</td>
            </tr>"""
        if not _exp_rows:
            _exp_rows = '<tr><td colspan="5" style="color:#374151;text-align:center;padding:8px">実験なし</td></tr>'

        return f"""
<div class="section" id="ck-cta-optimizer" style="margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
    <h2 style="font-size:1.05rem;font-weight:800;color:#f8fafc;margin:0">🎨 CK: UIデザイン最適化（イルミーゼ）</h2>
    <span style="background:{_state_color}22;border:1px solid {_state_color}55;color:{_state_color};padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">{_ui_state}</span>
    <span style="background:{_src_badge_color}22;border:1px solid {_src_badge_color}55;color:{_src_badge_color};padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">{_src_label}</span>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px">
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:1.6rem;font-weight:800;color:#f472b6">{_total_clicks}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:2px">CTAクリック総数（昨日）</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:1.6rem;font-weight:800;color:#818cf8">{_cta_ctr:.2%}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:2px">CTA率（PV比）</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:1.6rem;font-weight:800;color:#34d399">{_fclk_rate:.2%}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:2px">固定バークリック率</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:1.6rem;font-weight:800;color:#f59e0b">{_fcls_rate:.2%}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:2px">固定バー閉じる率</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:1.6rem;font-weight:800;color:#a78bfa">{_imp}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:2px">固定バー表示回数</div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
    <!-- 位置別クリック分布 -->
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px">
      <div style="font-size:0.8rem;font-weight:700;color:#e2e8f0;margin-bottom:10px">📍 位置別クリック分布</div>
      {''.join(f'''<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <span style="font-size:0.72rem;color:#94a3b8;width:60px">{lbl}</span>
        <div style="flex:1;background:#1e293b;border-radius:3px;height:8px;overflow:hidden">
          <div style="background:{clr};height:8px;border-radius:3px;width:{pct:.0f}%"></div>
        </div>
        <span style="font-size:0.72rem;color:#e2e8f0;width:32px;text-align:right">{cnt}</span>
      </div>''' for lbl,cnt,clr,pct in [
          ("TOP",   _top,  "#f472b6", _top /_ttl*100),
          ("MIDDLE",_mid,  "#818cf8", _mid /_ttl*100),
          ("BOTTOM",_bot,  "#34d399", _bot /_ttl*100),
          ("固定バー",_fclk,"#f59e0b",_fclk/_ttl*100),
      ])}
    </div>

    <!-- 実験サマリ -->
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px">
      <div style="font-size:0.8rem;font-weight:700;color:#e2e8f0;margin-bottom:10px">🧪 実験状況</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
        <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 10px;border-radius:12px;font-size:0.72rem">✅ WIN {len(_win_exp)}</span>
        <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:2px 10px;border-radius:12px;font-size:0.72rem">❌ LOSE {len(_lose_exp)}</span>
        <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:2px 10px;border-radius:12px;font-size:0.72rem">⏳ 計測中 {len(_pend_exp)}</span>
        <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:2px 10px;border-radius:12px;font-size:0.72rem">🔬 仮判定 {len(_prov_exp)}</span>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
        <thead><tr style="border-bottom:1px solid #1e293b">
          <th style="text-align:left;padding:3px 4px;color:#64748b">実験ID</th>
          <th style="text-align:center;color:#64748b">結果</th>
          <th style="text-align:right;color:#64748b">ΔCTR</th>
          <th style="text-align:right;color:#64748b">Δ滞在</th>
          <th style="text-align:center;color:#64748b">判定</th>
        </tr></thead>
        <tbody>{_exp_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- 記事タイプ×位置クロス集計 -->
  <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px">
    <div style="font-size:0.8rem;font-weight:700;color:#e2e8f0;margin-bottom:10px">📊 記事タイプ × CTA位置 クロス集計（昨日）</div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:0.75rem;min-width:400px">
        <thead><tr style="border-bottom:1px solid #1e293b">
          <th style="text-align:left;padding:4px 8px;color:#64748b">記事タイプ</th>
          <th style="text-align:center;padding:4px;color:#f472b6">TOP</th>
          <th style="text-align:center;padding:4px;color:#818cf8">MIDDLE</th>
          <th style="text-align:center;padding:4px;color:#34d399">BOTTOM</th>
          <th style="text-align:center;padding:4px;color:#f59e0b">固定バー</th>
        </tr></thead>
        <tbody>{_type_rows}</tbody>
      </table>
    </div>
  </div>
</div>"""
    try:
        _ck_section_html = _build_ck_section()
    except Exception as _e:
        _ck_section_html = f'<div style="color:#ef4444;padding:12px">CTAダッシュボード読み込みエラー: {_e}</div>'

    # CX: 復旧KPI (2026-04-16障害からの回復/成長指標)
    _cx_recovery_html = ""
    try:
        _rkpi_path = BASE / "dashboard_kpi_recovery.json"
        if _rkpi_path.exists():
            _rkpi = json.loads(_rkpi_path.read_text())
            k = _rkpi.get("kpis", {})
            _phases = _rkpi.get("recovery_phase", {})
            def _val(v):
                return "—" if v is None else v
            def _stat(ok):
                return ('<span style="color:#22c55e">✅</span>' if ok else
                        '<span style="color:#eab308">⏳</span>')
            _p1 = _phases.get("phase1_seo_recovery", {})
            _p3 = _phases.get("phase3_monetization", {})
            _p4 = _phases.get("phase4_disaster_prevention", {})
            _cx_recovery_html = f"""
<div class="section" id="cx-recovery" style="margin-bottom:14px">
  <div style="background:linear-gradient(135deg,#0c1629,#0f172a);border:1px solid #1e293b;border-left:4px solid #22d3ee;border-radius:12px;padding:16px 20px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
      <h2 style="font-size:0.95rem;color:#22d3ee;margin:0">🚑 CX — 復旧＆成長KPI</h2>
      <span style="font-size:0.7rem;color:#64748b">generated: {_rkpi.get('generated_at','')[:19]}</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin-bottom:14px">
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">GSC再送(24h)</div>
        <div style="font-size:1.25rem;font-weight:900;color:#22d3ee">{_val(k.get('gsc_indexed_24h'))}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">GSC累計</div>
        <div style="font-size:1.25rem;font-weight:900;color:#e2e8f0">{_val(k.get('gsc_indexed_total'))}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">CTR(avg)</div>
        <div style="font-size:1.25rem;font-weight:900;color:#e2e8f0">{_val(k.get('ctr_avg_pct'))}%</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">表示回数</div>
        <div style="font-size:1.25rem;font-weight:900;color:#e2e8f0">{_val(k.get('impressions_total'))}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">CTA更新(7d)</div>
        <div style="font-size:1.25rem;font-weight:900;color:#22c55e">{_val(k.get('cta_updated_7d'))}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">内部リンク(7d)</div>
        <div style="font-size:1.25rem;font-weight:900;color:#22c55e">{_val(k.get('internal_links_added_7d'))}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">公開記事</div>
        <div style="font-size:1.25rem;font-weight:900;color:#e2e8f0">{_val(k.get('posts_publish'))}</div>
      </div>
      <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:10px 12px">
        <div style="font-size:0.68rem;color:#64748b">X投稿(24h)</div>
        <div style="font-size:1.25rem;font-weight:900;color:#e2e8f0">{_val(k.get('x_posts_24h'))}</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px">
      <div style="background:#0d1117;border-radius:6px;padding:8px 10px;font-size:0.75rem">
        <strong style="color:#22d3ee">P1 SEO復旧</strong><br>
        {_stat(_p1.get('gsc_resubmit'))} GSC再送TOP30
        {_stat(_p1.get('internal_links_fixed'))} 内部リンク修復
        {_stat(_p1.get('x_revival_queue_built'))} X再投稿キュー
      </div>
      <div style="background:#0d1117;border-radius:6px;padding:8px 10px;font-size:0.75rem">
        <strong style="color:#f97316">P3 収益化</strong><br>
        {_stat(_p3.get('cta_injected_50posts'))} CTA 50記事注入
        {_stat(_p3.get('cv_articles_drafted'))} CV記事draft生成
      </div>
      <div style="background:#0d1117;border-radius:6px;padding:8px 10px;font-size:0.75rem">
        <strong style="color:#a855f7">P4 再発防止</strong><br>
        {_stat(_p4.get('backup_script_installed'))} バックアップ自動化
        {_stat(_p4.get('recovery_snapshot_today'))} 本日スナップショット
      </div>
    </div>
  </div>
</div>"""
    except Exception as _e:
        _cx_recovery_html = f'<div style="color:#ef4444;padding:12px">復旧KPI読み込みエラー: {_e}</div>'

    # エージェント表示名マップ読み込み
    try:
        import json as _jj
        _adm_path = BASE / "config" / "agent_display_map.json"
        _agent_display_map = _jj.loads(_adm_path.read_text(encoding="utf-8")) if _adm_path.exists() else {}
    except Exception:
        _agent_display_map = {}

    def _display(agent_id: str, fallback: str) -> str:
        return _agent_display_map.get(agent_id, {}).get("display_name") or fallback

    summary = load("dashboard_summary.json")
    am = load("agent_metrics.json")
    opt = load("optimization_actions.json")
    rev = load("revenue_metrics.json")
    org = load("org_map.json")

    # 通知履歴・キュー（JSONL）
    notif_history = load_jsonl_safe("logs/discord_alert_history.jsonl")
    notif_queue   = load_jsonl_safe("logs/alert_queue.jsonl")
    # CEO実行命令キュー（JSONL）
    ceo_action_queue = load_jsonl_safe("logs/ceo_action_queue.jsonl")
    # CEO実行履歴・状態
    ceo_exec_history = load_jsonl_safe("logs/ceo_execution_history.jsonl")
    ceo_safe_history        = load_jsonl_safe("logs/ceo_safe_action_history.jsonl")
    ceo_improvement_queue   = load_jsonl_safe("logs/ceo_improvement_queue.jsonl")
    ceo_ready_queue         = load_jsonl_safe("logs/ceo_ready_queue.jsonl")
    ceo_ready_review_history = load_jsonl_safe("logs/ceo_ready_review_history.jsonl")
    try:
        import json as _json
        _state_path = Path("logs/ceo_execution_state.json")
        ceo_exec_state = _json.loads(_state_path.read_text()) if _state_path.exists() else {}
    except Exception:
        ceo_exec_state = {}

    agents = am.get("agents", {})
    actions = opt.get("actions", [])
    am_summary = am.get("summary", {})

    # 生成時刻
    gen_at = am.get("generated_at","")
    try:
        _dt = datetime.fromisoformat(gen_at.replace("Z","+00:00"))
        if _dt.tzinfo is not None:
            _dt = _dt.astimezone(JST)
        gen_str = _dt.strftime("%Y-%m-%d %H:%M JST")
    except:
        gen_str = gen_at[:16]

    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

    # アクティブエージェント（全体: 成功率降順）
    active = {k:v for k,v in agents.items() if v.get("total_count",0)>0 and k!="pipeline"}
    sorted_active = sorted(active.items(), key=lambda x: x[1]["success_rate"], reverse=True)

    # 危険度順ソート（AI社員カード用）
    def _agent_danger_key(item):
        k, v = item
        return (
            not v.get("sabori_flag", False),   # サボり優先
            not v.get("error_flag", False),    # エラー優先
            v.get("success_rate", 0),          # 成功率昇順
            -v.get("total_count", 0),          # 実行数降順
        )
    danger_sorted_active = sorted(active.items(), key=_agent_danger_key)

    overall_rate = summary.get("overall_success_rate", 0)
    excellent = summary.get("excellent_count", 0)
    warning = summary.get("warning_count", 0)
    critical = summary.get("critical_count", 0)
    sabori = summary.get("sabori_count", 0)
    err_agents = summary.get("error_agent_count", 0)
    high_actions = summary.get("high_priority_actions", 0)
    today_posts = summary.get("today_posts", 0)
    week_posts = summary.get("week_posts", 0)

    # CEO意思決定フィールド
    ceo_immediate   = summary.get("ceo_immediate_action", "—")
    ceo_today_fix   = summary.get("ceo_today_fix", "—")
    ceo_rev_lever   = summary.get("ceo_revenue_lever", "—")
    ceo_ignore      = summary.get("ceo_ignore_today", "—")
    ceo_reason      = summary.get("ceo_reason_short", "")
    ceo_confidence  = summary.get("ceo_confidence", "—")
    # CEO実行命令フィールド
    ceo_act_priority = summary.get("ceo_action_priority", "—")
    ceo_act_type     = summary.get("ceo_action_type", "—")
    ceo_act_agent    = summary.get("ceo_target_agent", "")
    ceo_act_log      = summary.get("ceo_target_log", "")
    ceo_act_metric   = summary.get("ceo_target_metric", "")
    ceo_act_effect   = summary.get("ceo_expected_effect", "")
    ceo_act_reason   = summary.get("ceo_blocker_reason", "")
    ceo_act_exec     = summary.get("ceo_execute_recommended", False)
    ceo_act_ver      = summary.get("ceo_action_version", "—")
    # CEO実行エンジン集計フィールド
    ceo_exec_processed = summary.get("ceo_exec_processed", 0)
    ceo_exec_done      = summary.get("ceo_exec_done", 0)
    ceo_exec_failed    = summary.get("ceo_exec_failed", 0)
    ceo_exec_blocked   = summary.get("ceo_exec_blocked", 0)
    ceo_exec_skipped     = summary.get("ceo_exec_skipped", 0)
    ceo_exec_safe_retry        = summary.get("ceo_exec_safe_retry", 0)
    ceo_exec_safe_inspect      = summary.get("ceo_exec_safe_inspect", 0)
    ceo_exec_improvement_queued= summary.get("ceo_exec_improvement_queued", 0)
    ceo_exec_result      = summary.get("ceo_exec_result", "—")
    ceo_exec_reason      = summary.get("ceo_exec_reason", "")
    ceo_exec_summary_t   = summary.get("ceo_exec_summary", "")
    ceo_exec_next_t      = summary.get("ceo_exec_next", "")

    rev_summary = rev.get("summary", {})
    avg_rev_score = rev_summary.get("avg_revenue_score", 0)
    cta_rate = rev_summary.get("cta_rate", 0)
    thumb_rate = rev_summary.get("thumbnail_rate", 0)
    avg_chars = rev_summary.get("avg_char_count", 0)
    contaminated = rev_summary.get("contaminated_title_count", 0)

    # ─── セクションA: 経営サマリー ───
    top3 = summary.get("top3_agents", [])
    worst3 = summary.get("worst3_agents", [])
    insights = rev.get("management_insights", {})
    urgent = insights.get("urgent_actions", [])

    top3_html = ""
    for i, a in enumerate(top3, 1):
        c = rank_color(a.get("rank","🟢"))
        top3_html += f"""
        <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:#0f172a;border-radius:8px;margin-bottom:8px">
          <span style="font-size:1.4rem">{medal(i)}</span>
          <div>
            <div style="font-weight:700">{a['name']}</div>
            <div style="font-size:0.8rem;color:{c};font-weight:800">{pct(a['rate'])}</div>
          </div>
        </div>"""

    worst3_html = ""
    for i, a in enumerate(worst3, 1):
        c = rank_color(a.get("rank","🔴"))
        worst3_html += f"""
        <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:#0f172a;border-radius:8px;margin-bottom:8px;border-left:3px solid {c}">
          <span style="font-size:1.2rem">{'💀' if i==1 else '⚠️'}</span>
          <div>
            <div style="font-weight:700">{a['name']}</div>
            <div style="font-size:0.8rem;color:{c};font-weight:800">{pct(a['rate'])}</div>
          </div>
        </div>"""

    urgent_html = "".join(f'<li style="padding:4px 0;font-size:0.85rem;color:#e2e8f0">{u}</li>' for u in urgent)

    # ─── セクションB: AI社員カード（危険度高い順）───
    agent_cards = ""
    for i, (mid, m) in enumerate(danger_sorted_active, 1):
        rank = m.get("rank","🟡")
        rate = m.get("success_rate",0)
        name = _display(mid, m.get("name_ja", mid))
        role = _agent_display_map.get(mid, {}).get("role") or m.get("role","")
        dept = _agent_display_map.get(mid, {}).get("department", "")
        status = m.get("status","")
        total = m.get("total_count",0)
        ok = m.get("success_count",0)
        empty = m.get("empty_output_count",0)
        cont = m.get("contamination_count",0)
        retry = m.get("retry_count",0)
        hard_fail = m.get("hard_fail_count",0)
        last_ts = m.get("last_run_time","")
        activity = m.get("weekly_activity",[0]*7)
        h_since = m.get("hours_since_last_run",0)
        sabori_flag = m.get("sabori_flag",False)
        err_flag = m.get("error_flag",False)
        avg_size = m.get("avg_output_size",0)
        danger = m.get("danger","🟢 低")
        rc = rank_color(rank)
        rbg = rank_bg(rank)

        # 状態バッジ群
        def _badge(label, color):
            return f'<span style="background:{color}22;color:{color};border:1px solid {color}44;padding:1px 6px;border-radius:99px;font-size:0.68rem;font-weight:700;margin-right:3px">{label}</span>'
        badges = ""
        if status == "停止":       badges += _badge("停止中",   "#ef4444")
        if sabori_flag:            badges += _badge("サボり",   "#ef4444")
        if empty >= 3:             badges += _badge("空出力",   "#f97316")
        if hard_fail >= 3:         badges += _badge("HARD_FAIL","#dc2626")
        if cont > 0:               badges += _badge("汚染",     "#8b5cf6")
        if not badges:             badges  = _badge("正常",     "#22c55e")

        # サボり・エラーコメント
        comment = ""
        if sabori_flag and hard_fail == 0 and empty >= 3:
            comment = f'<div style="margin-top:6px;font-size:0.72rem;color:#ef4444">⚠ 空出力{empty}回 — サボり疑い</div>'
        elif err_flag and cont > 0:
            comment = f'<div style="margin-top:6px;font-size:0.72rem;color:#f97316">⚠ 出力汚染{cont}件 — フォーマット違反</div>'
        elif hard_fail >= 5:
            comment = f'<div style="margin-top:6px;font-size:0.72rem;color:#ef4444">⚠ HARD_FAIL {hard_fail}回 — 品質改善必要</div>'
        elif rate >= 0.95 and total >= 10:
            comment = f'<div style="margin-top:6px;font-size:0.72rem;color:#22c55e">✅ 安定稼働中</div>'

        medal_str = medal(i) if i <= 3 else ("💀" if i == len(danger_sorted_active) else f"#{i}")

        # ガルデvoir専用情報
        extra = ""
        if mid == "gardevoir_hook_critic":
            g_pass = m.get("gardevoir_pass",0)
            g_fail = m.get("gardevoir_fail",0)
            g_err = m.get("gardevoir_error",0)
            g_score = m.get("gardevoir_avg_score",0)
            extra = f'<div style="margin-top:6px;font-size:0.72rem;color:#94a3b8">PASS:{g_pass} HARD_FAIL:{g_fail} ERROR:{g_err} 平均スコア:{g_score}</div>'

        agent_cards += f"""
        <div class="agent-card" style="background:{rbg};border:1px solid {rc}33;border-top:3px solid {rc}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
            <div>
              <div style="font-size:1.0rem;font-weight:800">{medal_str} {name}</div>
              <div style="font-size:0.75rem;color:#64748b;margin-top:2px">{role}</div>
              {f'<div style="font-size:0.62rem;color:#475569;margin-top:1px">🏢 {dept}</div>' if dept else ''}
            </div>
            {status_badge(status)}
          </div>
          <div style="margin-bottom:8px">{badges}</div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="font-size:1.6rem;font-weight:900;color:{rc}">{pct(rate)}</span>
            <div>{bar(rate,1.0,rc,80,8)}</div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.75rem;color:#94a3b8;margin-bottom:8px">
            <span>✅ 成功: {ok}/{total}</span>
            <span>🔄 リトライ: {retry}</span>
            <span>📭 空出力: {empty}</span>
            <span>💀 HARD_FAIL: {hard_fail}</span>
            <span>🦠 汚染: {cont}</span>
            <span>⏱ {h_since:.0f}h前</span>
          </div>
          <div style="margin-bottom:6px">
            <div style="font-size:0.68rem;color:#475569;margin-bottom:2px">週間稼働（月〜日）</div>
            {sparkbar(activity)}
          </div>
          <div style="font-size:0.72rem;color:#475569">最終: {fmt_ts(last_ts)} | 平均出力: {avg_size:,}bytes</div>
          {extra}{comment}
        </div>"""

    # ─── セクションC: MVP / ワースト ───
    mvp_html = ""
    for i, (mid, m) in enumerate(sorted_active[:3], 1):
        rc = rank_color(m.get("rank","🟢"))
        _mname = _display(mid, m.get("name_ja", mid))
        _mrole = _agent_display_map.get(mid, {}).get("role") or m.get("role","")
        mvp_html += f"""
        <div style="background:#0f172a;border:2px solid {rc};border-radius:12px;padding:18px;text-align:center;flex:1">
          <div style="font-size:2rem">{medal(i)}</div>
          <div style="font-size:1.0rem;font-weight:800;margin:6px 0">{_mname}</div>
          <div style="font-size:0.78rem;color:#64748b;margin-bottom:8px">{_mrole}</div>
          <div style="font-size:1.8rem;font-weight:900;color:{rc}">{pct(m['success_rate'])}</div>
          <div style="font-size:0.72rem;color:#64748b;margin-top:4px">{m['success_count']}/{m['total_count']}件成功</div>
        </div>"""

    worst_html = ""
    worst_sorted = sorted(active.items(), key=lambda x: x[1]["success_rate"])[:3]
    icons = ["💀","⚠️","⚡"]
    for i, (mid, m) in enumerate(worst_sorted):
        rc = rank_color(m.get("rank","🔴"))
        _wname = _display(mid, m.get("name_ja", mid))
        _wrole = _agent_display_map.get(mid, {}).get("role") or m.get("role","")
        worst_html += f"""
        <div style="background:#0f172a;border:2px solid {rc};border-radius:12px;padding:18px;text-align:center;flex:1">
          <div style="font-size:2rem">{icons[i]}</div>
          <div style="font-size:1.0rem;font-weight:800;margin:6px 0">{_wname}</div>
          <div style="font-size:0.78rem;color:#64748b;margin-bottom:8px">{_wrole}</div>
          <div style="font-size:1.8rem;font-weight:900;color:{rc}">{pct(m['success_rate'])}</div>
          <div style="font-size:0.72rem;color:#64748b;margin-top:4px">{m['fail_count']}回失敗</div>
        </div>"""

    # ─── セクションD: 異常検知ログ ───
    anomalies_html = ""
    # タイトル崩壊
    cont_titles = rev_summary.get("contaminated_titles", [])
    if cont_titles:
        for ct in cont_titles:
            anomalies_html += f"""
            <div class="anomaly-row" style="border-left-color:#ef4444">
              <span class="anomaly-badge" style="background:#ef444422;color:#ef4444">タイトル崩壊</span>
              <span style="font-size:0.85rem">post_id={ct.get('post_id','?')} — {ct.get('title','')[:70]}</span>
            </div>"""
    # サーナイトHARD_FAIL
    gdv = agents.get("gardevoir_hook_critic",{})
    hf_titles = gdv.get("hard_fail_titles",[])
    for t in hf_titles[-3:]:
        anomalies_html += f"""
        <div class="anomaly-row" style="border-left-color:#f97316">
          <span class="anomaly-badge" style="background:#f9731622;color:#f97316">HARD_FAIL</span>
          <span style="font-size:0.85rem">{t[:70]}</span>
        </div>"""
    # サボり検知
    sabori_agents = [(k,v) for k,v in active.items() if v.get("sabori_flag")]
    for sid, sv in sabori_agents[:5]:
        anomalies_html += f"""
        <div class="anomaly-row" style="border-left-color:#eab308">
          <span class="anomaly-badge" style="background:#eab30822;color:#eab308">サボり疑い</span>
          <span style="font-size:0.85rem">{_display(sid, sv.get('name_ja','?'))} — 空出力{sv.get('empty_output_count',0)}回 / 最終稼働{sv.get('hours_since_last_run',0):.0f}時間前</span>
        </div>"""
    # 汚染エージェント
    cont_agents = [(k,v) for k,v in active.items() if v.get("contamination_count",0)>0]
    for cid, cv in cont_agents[:5]:
        anomalies_html += f"""
        <div class="anomaly-row" style="border-left-color:#8b5cf6">
          <span class="anomaly-badge" style="background:#8b5cf622;color:#8b5cf6">出力汚染</span>
          <span style="font-size:0.85rem">{_display(cid, cv.get('name_ja','?'))} — {cv.get('contamination_count',0)}件のタイトル品質問題を検知</span>
        </div>"""
    # pipeline stop
    kpi_err = load("revenue_metrics.json").get("summary",{})
    stop_count = sum(1 for v in active.values() if v.get("hard_fail_count",0)>=3)
    if stop_count:
        anomalies_html += f"""
        <div class="anomaly-row" style="border-left-color:#ef4444">
          <span class="anomaly-badge" style="background:#ef444422;color:#ef4444">停止連発</span>
          <span style="font-size:0.85rem">{stop_count}エージェントでHARD_FAIL多発 → pipeline_stop誘発</span>
        </div>"""
    if not anomalies_html:
        anomalies_html = '<div style="color:#22c55e;padding:16px">✅ 異常なし</div>'

    # ─── セクションE: 売上最大化 ───
    top_articles = rev.get("top_articles",[])[:5]
    bot_articles = rev.get("bottom_articles",[])[-5:]
    art_targets = rev.get("kpi_targets",{})
    pipeline_analysis = rev.get("pipeline_analysis",{})

    top_art_html = ""
    for a in top_articles:
        score = a.get("revenue_score",0)
        rc = "#22c55e" if score >= 0.8 else ("#eab308" if score >= 0.6 else "#ef4444")
        url = a.get("url","#")
        title = a.get("title","")[:45]
        top_art_html += f"""
        <tr>
          <td><a href="{url}" target="_blank" style="color:#60a5fa;text-decoration:none">{title}…</a></td>
          <td style="color:{rc};font-weight:800;text-align:center">{score:.2f}</td>
          <td style="text-align:center">{a.get('char_count',0):,}</td>
          <td style="text-align:center">{'✅' if a.get('has_cta') else '❌'}</td>
          <td style="text-align:center">{'✅' if a.get('has_thumbnail') else '❌'}</td>
          <td style="text-align:center">{bar(score,1.0,rc,60,6)}</td>
        </tr>"""

    bot_art_html = ""
    for a in bot_articles:
        score = a.get("revenue_score",0)
        rc = "#ef4444"
        url = a.get("url","#")
        title = a.get("title","")[:40]
        reasons = []
        if not a.get("has_cta"): reasons.append("CTA無")
        if a.get("char_count",0)<3000: reasons.append("文字数不足")
        if a.get("is_contaminated"): reasons.append("タイトル汚染")
        reason_str = "、".join(reasons) if reasons else "低スコア"
        bot_art_html += f"""
        <tr>
          <td><a href="{url}" target="_blank" style="color:#f87171;text-decoration:none">{title}…</a></td>
          <td style="color:#ef4444;font-weight:800;text-align:center">{score:.2f}</td>
          <td style="text-align:center;color:#94a3b8">{reason_str}</td>
        </tr>"""

    # 改善アクション
    action_html = ""
    for a in actions:
        sev = a.get("severity","low")
        sc = sev_color(sev)
        action_html += f"""
        <div class="action-card">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
            <span style="background:{sc};color:#fff;padding:2px 10px;border-radius:99px;font-size:0.72rem;font-weight:800">{sev.upper()}</span>
            <span style="font-weight:700;font-size:0.9rem">{a.get('agent_name','')}</span>
            <span style="background:#1e293b;color:#94a3b8;padding:2px 8px;border-radius:4px;font-size:0.72rem">{a.get('action_type','')}</span>
          </div>
          <div style="font-size:0.82rem;color:#94a3b8;margin-bottom:6px">📌 {a.get('reason','')}</div>
          <div style="font-size:0.85rem;color:#e2e8f0;margin-bottom:4px">→ {a.get('suggested_fix','')}</div>
          <div style="font-size:0.75rem;color:#64748b">期待効果: {a.get('expected_effect','')}</div>
        </div>"""

    # ─── 組織マップ ───
    org_agents = org.get("departments",{})
    core_list = org_agents.get("core",{}).get("agents",[])
    support_list = org_agents.get("support",{}).get("agents",[])
    infra_list = org_agents.get("infra",{}).get("agents",[])
    manual_list = org_agents.get("manual",{}).get("agents",[])

    def dept_html(agent_list):
        html = ""
        for a in agent_list:
            rc = rank_color(a.get("rank","🟡"))
            st = a.get("status","")
            html += f"""
            <div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:#0f172a;border-radius:6px;margin-bottom:4px;border-left:3px solid {rc}">
              <span style="font-size:0.85rem;font-weight:700;min-width:100px">{_display(a.get('id',''), a.get('name_ja',''))}</span>
              <span style="font-size:0.72rem;color:#64748b;flex:1">{_agent_display_map.get(a.get('id',''),{}).get('role') or a.get('role','')}</span>
              {status_badge(st)}
              <span style="font-size:0.8rem;font-weight:700;color:{rc};min-width:40px;text-align:right">{pct(a.get('success_rate',0))}</span>
            </div>"""
        return html if html else '<div style="color:#374151;font-size:0.8rem;padding:8px">なし</div>'

    # ─── パイプライン分析 ───
    pl_html = ""
    for pl, v in pipeline_analysis.items():
        avg = v.get("avg_revenue_score",0)
        rc = "#22c55e" if avg>=0.8 else ("#eab308" if avg>=0.6 else "#ef4444")
        pl_html += f"""
        <div style="background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:14px;flex:1;min-width:160px">
          <div style="font-size:0.75rem;color:#64748b;text-transform:uppercase;margin-bottom:6px">{pl}</div>
          <div style="font-size:1.4rem;font-weight:800;color:{rc}">{avg:.2f}</div>
          <div style="font-size:0.72rem;color:#94a3b8;margin-top:4px">{v.get('count',0)}記事 | CTA率{v.get('cta_rate',0):.0%}</div>
          <div style="margin-top:6px">{bar(avg,1.0,rc,100,6)}</div>
        </div>"""

    # 勝ち/負けパターン
    win = rev.get("winning_patterns",{})
    lose = rev.get("losing_patterns",{})

    # ─── G〜K: 通知・ランキング・売上阻害セクション ───
    # 通知統計（dashboard_summary から取得）
    notif_sent     = summary.get("notification_success_count", 0)
    notif_fail     = summary.get("notification_failure_count", 0)
    notif_supp     = summary.get("notification_suppressed_count", 0)
    notif_pend     = summary.get("notification_pending_count", 0)
    notif_perm     = summary.get("notification_permanent_failed_count", 0)
    latest_sent_at = summary.get("latest_notification_sent_at", "")
    latest_fail_at = summary.get("latest_notification_failed_at", "")
    top_fail_rsn   = summary.get("top_notification_failure_reason", "")
    unres_crit     = summary.get("unresolved_critical_count", 0)
    unres_warn     = summary.get("unresolved_warning_count", 0)

    def _notif_card(label, value, color, sub=""):
        return f'''<div class="kpi-card" style="border-color:{color}33">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value" style="color:{color}">{value}</div>
          {f'<div class="kpi-sub">{sub}</div>' if sub else ''}
        </div>'''

    # 通知KPI: 仕様順（未解決CRITICAL→WARNING→pending→permanent_failed→送信成功→失敗→抑制→最終通知）
    notif_cards = (
        _notif_card("未解決CRITICAL", unres_crit, "#ef4444" if unres_crit > 0 else "#22c55e", "即対応必要") +
        _notif_card("未解決WARNING", unres_warn, "#f59e0b" if unres_warn > 0 else "#22c55e", "要注視") +
        _notif_card("pending", notif_pend, "#f59e0b" if notif_pend > 0 else "#22c55e", "次回再送待ち") +
        _notif_card("永続失敗", notif_perm, "#ef4444" if notif_perm > 0 else "#22c55e", "要手動確認") +
        _notif_card("送信成功", notif_sent, "#22c55e", "通算累計") +
        _notif_card("送信失敗", notif_fail, "#ef4444" if notif_fail > 0 else "#22c55e", "累計") +
        _notif_card("抑制（重複）", notif_supp, "#64748b", "30分/6h重複除外") +
        _notif_card("最終通知", fmt_ts(latest_sent_at), "#818cf8", f"失敗: {fmt_ts(latest_fail_at)}")
    )

    # 最新失敗理由カード
    fail_reason_card = f"""<div style="background:#111827;border:1px solid {'#ef444466' if top_fail_rsn else '#1e293b'};border-left:4px solid {'#ef4444' if top_fail_rsn else '#22c55e'};border-radius:10px;padding:14px 18px;margin-top:14px">
  <div style="font-size:0.7rem;font-weight:800;color:#64748b;text-transform:uppercase;margin-bottom:6px">最新失敗理由</div>
  <div style="font-size:1.1rem;font-weight:800;color:{'#ef4444' if top_fail_rsn else '#22c55e'}">{top_fail_rsn or '失敗なし'}</div>
  <div style="font-size:0.75rem;color:#475569;margin-top:4px">最終失敗: {fmt_ts(latest_fail_at)}</div>
</div>"""

    # H: 未解決アラート（pendingキュー）
    pending_items = [q for q in notif_queue if q.get("status") == "pending"]
    pending_items.sort(key=lambda x: (0 if x.get("severity") == "CRITICAL" else 1, x.get("queued_at", "")))
    pending_rows = ""
    for q in pending_items[:20]:
        sev = q.get("severity", "WARNING")
        sc  = "#ef4444" if sev == "CRITICAL" else "#f59e0b"
        pending_rows += f"""<tr>
          <td><span style="color:{sc};font-weight:700">{sev}</span></td>
          <td style="font-size:0.78rem">{q.get('event_key','')}</td>
          <td style="font-size:0.78rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{q.get('title','')}</td>
          <td style="font-size:0.72rem;color:#64748b">{q.get('retry_count',0)}回</td>
          <td style="font-size:0.72rem;color:#94a3b8">{fmt_ts(q.get('queued_at',''))}</td>
          <td style="font-size:0.72rem;color:#ef4444">{q.get('last_error','')[:60]}</td>
        </tr>"""
    if not pending_rows:
        pending_rows = '<tr><td colspan="6" style="color:#22c55e;text-align:center;padding:16px">✅ 未解決アラートなし</td></tr>'

    # I: 通知履歴（最新20件）
    hist_recent = sorted(notif_history, key=lambda x: x.get("sent_at",""), reverse=True)[:20]
    hist_rows = ""
    for h in hist_recent:
        res = h.get("result","")
        rc = {"sent":"#22c55e","suppressed":"#64748b","webhook_not_set":"#94a3b8"}.get(res, "#ef4444")
        sev = h.get("severity","")
        sc2 = "#ef4444" if sev=="CRITICAL" else ("#f59e0b" if sev=="WARNING" else "#64748b")
        hist_rows += f"""<tr>
          <td style="font-size:0.72rem;color:#94a3b8">{fmt_ts(h.get('sent_at',''))}</td>
          <td><span style="color:{sc2};font-weight:700;font-size:0.75rem">{sev}</span></td>
          <td style="font-size:0.72rem;color:#64748b">{h.get('rule','')}</td>
          <td style="font-size:0.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{h.get('title','')}</td>
          <td><span style="color:{rc};font-size:0.75rem;font-weight:700">{res}</span></td>
          <td style="font-size:0.72rem;color:#64748b">{h.get('channel','')}</td>
        </tr>"""
    if not hist_rows:
        hist_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:16px">通知履歴なし</td></tr>'

    # J: AI稼働異常ランキング（danger複合スコア top10、_kpop除外）
    def _danger_composite(v):
        r = 1.0 - v.get("success_rate", 0)
        s = 1.5 if v.get("sabori_flag") else 0.0
        e = 0.8 if v.get("error_flag") else 0.0
        hf = v.get("hard_fail_count", 0) * 0.1
        return r + s + e + hf

    danger_agents = sorted(
        [(k, v) for k, v in agents.items() if v.get("total_count", 0) > 0 and k != "pipeline"],
        key=lambda x: _danger_composite(x[1]), reverse=True
    )[:10]
    rank_rows = ""
    for i, (aid, v) in enumerate(danger_agents, 1):
        score = _danger_composite(v)
        rc = rank_color(v.get("rank", "🟡"))
        medal_icon = {1:"🥇",2:"🥈",3:"🥉"}.get(i, f"#{i}")
        flags = []
        if v.get("sabori_flag"): flags.append("サボり")
        if v.get("error_flag"):  flags.append("エラー")
        rank_rows += f"""<tr>
          <td style="text-align:center">{medal_icon}</td>
          <td style="font-weight:700;color:{rc}">{_display(aid, v.get('name_ja', aid))}</td>
          <td style="font-size:0.72rem;color:#64748b">{(_agent_display_map.get(aid,{}).get('role') or v.get('role',''))[:30]}</td>
          <td><span style="color:{rc};font-weight:700">{pct(v.get('success_rate',0))}</span></td>
          <td style="font-size:0.75rem;color:#f59e0b">{' '.join(flags) or '—'}</td>
          <td style="font-size:0.72rem;color:#94a3b8">{score:.2f}</td>
        </tr>"""
    if not rank_rows:
        rank_rows = '<tr><td colspan="6" style="color:#22c55e;text-align:center;padding:16px">✅ 異常エージェントなし</td></tr>'

    # K: 売上阻害ボトルネック
    BLOCKER_INFO = {
        "wp_poster":  ("WordPress投稿失敗", "記事が公開されず売上0",  "pipeline_steps.jsonl"),
        "sanai":      ("サーナイト品質低下", "タイトル汚染→CVR低下",   "pipeline_steps.jsonl"),
        "butterfree": ("バタフリーSEO最適化遅延", "検索流入減→CTR低下", "pipeline_steps.jsonl"),
        "kairyu":     ("カイリュー配信遅延", "速報記事の鮮度劣化→PV低下","pipeline_steps.jsonl"),
        "arceus":     ("アルセウス品質ゲート却下", "高品質記事が止まるリスク","pipeline_steps.jsonl"),
    }
    blocker_html = ""
    rev_blockers = summary.get("revenue_blocker_top3", [])
    for blk in rev_blockers:
        aid = blk.get("id", "")
        info = BLOCKER_INFO.get(aid, ("", "", ""))
        prob, impact, log = info
        rate = blk.get("rate", 0)
        rnk  = blk.get("rank", "🟡")
        rc   = rank_color(rnk)
        blocker_html += f"""
        <div style="background:#0f172a;border:1px solid #1e293b;border-left:4px solid {rc};border-radius:8px;padding:14px 16px;margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
            <span style="font-size:1.0rem;font-weight:700;color:{rc}">{_display(aid, blk.get('name',''))}</span>
            <span style="font-size:0.72rem;background:{rc}22;color:{rc};border-radius:4px;padding:2px 7px">{pct(rate)}</span>
            {status_badge(blk.get('status',''))}
          </div>
          <div style="font-size:0.8rem;color:#e2e8f0">🔥 問題: {prob or '—'}</div>
          <div style="font-size:0.8rem;color:#f59e0b;margin-top:4px">💰 影響: {impact or '—'}</div>
          <div style="font-size:0.72rem;color:#475569;margin-top:6px">📄 ログ: {log}</div>
        </div>"""
    if not blocker_html:
        blocker_html = '<div style="color:#22c55e;padding:12px">✅ 売上阻害ボトルネックなし</div>'

    # ─── オーナー判断バー ───
    top_blocker = rev_blockers[0] if rev_blockers else None
    blocker_label = (
        f"{top_blocker['name']} {pct(top_blocker['rate'])} ({top_blocker['status']})"
        if top_blocker else "なし"
    )
    blocker_color = rank_color(top_blocker.get("rank","🟢")) if top_blocker else "#22c55e"

    def _obar_card(label, value, color, urgent=False):
        border = f"border:2px solid {color}" if urgent else f"border:1px solid {color}33"
        pulse_style = f"animation:pulse 1.5s infinite;box-shadow:0 0 0 4px {color}33" if urgent else ""
        return f'''<div style="background:#111827;{border};border-radius:10px;padding:12px 14px;flex:1;min-width:120px;{pulse_style}">
          <div style="font-size:0.62rem;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px">{label}</div>
          <div style="font-size:1.6rem;font-weight:900;color:{color};line-height:1.1;word-break:break-all">{value}</div>
        </div>'''

    owner_bar_html = f"""<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;padding:16px;background:#0d1117;border:1px solid {'#ef444488' if unres_crit>0 else '#1e293b'};border-radius:14px">
  <div style="font-size:0.7rem;font-weight:800;color:#475569;writing-mode:vertical-rl;text-orientation:mixed;padding-right:8px;border-right:1px solid #1e293b;margin-right:4px">オーナー<br>判断</div>
  {_obar_card('① 要対応アラート', unres_crit, '#ef4444', unres_crit>0)}
  {_obar_card('② 収益阻害', blocker_label, blocker_color)}
  {_obar_card('③ 社員全体成功率', pct(overall_rate), '#22c55e' if overall_rate>=0.85 else '#eab308' if overall_rate>=0.6 else '#ef4444')}
  {_obar_card('④ 今日の投稿数', today_posts, '#60a5fa')}
  {_obar_card('⑤ 通知失敗数', notif_fail, '#ef4444' if notif_fail>0 else '#22c55e', notif_fail>0)}
  {_obar_card('⑥ 通知対応待ち', notif_pend, '#f59e0b' if notif_pend>0 else '#22c55e')}
</div>"""

    # ─── オーナー3行サマリー（断定・短文）───
    if unres_crit > 0:
        line1 = f"🔴 今すぐ: CRITICAL {unres_crit}件がキュー滞留 — bash run_alert_retry.sh を実行"
    elif sabori > 0:
        sb = [_display(k, v.get("name_ja","?")) for k,v in active.items() if v.get("sabori_flag")][:2]
        line1 = f"🟡 今すぐ: {'・'.join(sb)} が長期未稼働 — 記録ファイル(pipeline_steps.jsonl)を確認"
    elif high_actions >= 5:
        line1 = f"🟡 今すぐ: HIGH優先アクション {high_actions}件 — optimization_actions.json を対処"
    else:
        line1 = "✅ 緊急対応なし"

    if top_blocker and top_blocker.get("rank","🟢") != "🟢":
        line2 = f"💰 今日触る: {top_blocker['name']}（{pct(top_blocker['rate'])}） — pipeline_steps.jsonl で直近3runを確認"
    elif contaminated > 0:
        line2 = f"💰 今日触る: タイトル汚染 {contaminated}件 — audit_feedback.jsonl でサーナイト出力を検証"
    elif avg_rev_score < 0.7:
        line2 = f"💰 今日触る: 収益スコア {avg_rev_score:.2f} — CTA/文字数/サムネを修正"
    else:
        line2 = f"💰 今日触る: 上位記事パターン（スコア{avg_rev_score:.2f}）を次の記事へ横展開"

    green_agents = sum(1 for v in active.values() if v["rank"]=="🟢")
    line3 = f"😴 放置OK: 正常AI {green_agents}名・週間投稿 {week_posts}件 — 介入不要"

    owner_summary_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid {'#ef4444' if unres_crit>0 else '#22c55e' if sabori==0 and high_actions<5 else '#eab308'};border-radius:10px;padding:14px 20px;margin-bottom:14px">
  <div style="font-size:0.6rem;font-weight:800;color:#374151;text-transform:uppercase;letter-spacing:0.12em;margin-bottom:10px">📋 オーナー判断サマリー — {now_str}</div>
  <div style="font-size:0.95rem;font-weight:800;color:#f1f5f9;margin-bottom:6px">{line1}</div>
  <div style="font-size:0.85rem;color:#94a3b8;margin-bottom:5px">{line2}</div>
  <div style="font-size:0.8rem;color:#475569">{line3}</div>
</div>"""

    # 異常ランキング: 複数バッジ（視認性強化：背景塗りつぶし）
    def _flag_badges(v):
        def fb(label, color):
            return f'<span style="background:{color};color:#fff;padding:2px 7px;border-radius:4px;font-size:0.7rem;font-weight:800;margin-right:3px;white-space:nowrap">{label}</span>'
        out = ""
        if v.get("sabori_flag"):               out += fb("サボり",   "#dc2626")
        if v.get("status")=="停止":            out += fb("停止",     "#475569")
        if v.get("hard_fail_count",0)>=3:      out += fb("HARD_FAIL","#b91c1c")
        if v.get("empty_output_count",0)>=3:   out += fb("空出力",   "#d97706")
        if v.get("contamination_count",0)>0:   out += fb("汚染",     "#7c3aed")
        if v.get("error_flag") and not out:    out += fb("エラー",   "#ea580c")
        return out or fb("—","#374151")

    rank_rows = ""
    for i, (aid, v) in enumerate(danger_agents, 1):
        score = _danger_composite(v)
        rc = rank_color(v.get("rank", "🟡"))
        medal_icon = {1:"🥇",2:"🥈",3:"🥉"}.get(i, f"#{i}")
        rank_rows += f"""<tr>
          <td style="text-align:center;font-weight:700">{medal_icon}</td>
          <td style="font-weight:700;color:{rc}">{_display(aid, v.get('name_ja', aid))}</td>
          <td style="font-size:0.72rem;color:#64748b;max-width:160px">{(_agent_display_map.get(aid,{}).get('role') or v.get('role',''))[:28]}</td>
          <td><span style="color:{rc};font-weight:800">{pct(v.get('success_rate',0))}</span></td>
          <td>{_flag_badges(v)}</td>
          <td>{status_badge(v.get('status',''))}</td>
          <td style="font-size:0.8rem;color:#94a3b8;font-weight:700">{score:.2f}</td>
        </tr>"""
    if not rank_rows:
        rank_rows = '<tr><td colspan="7" style="color:#22c55e;text-align:center;padding:16px">✅ 異常エージェントなし</td></tr>'

    # 売上阻害ボトルネック: カード化（4行固定）
    BLOCKER_ACTIONS = {
        "wp_poster":  "pipeline_steps.jsonl で直近3runのwp_posterステップを確認 → HTTP/認証エラーを修正",
        "sanai":      "audit_feedback.jsonl で汚染タイトルを特定 → サーナイトのプロンプトtemperatureを下げる",
        "butterfree": "pipeline_steps.jsonl のseo_scoreフィールドを確認 → 対象記事にキーワードを追記",
        "kairyu":     "pipeline_steps.jsonl のtimestampを確認 → breaking_pipelineの優先度キューを上げる",
        "arceus":     "pipeline_steps.jsonl のrejected記事タイトルを確認 → 品質閾値スコアを5%下げて再投入",
    }
    BLOCKER_INFO2 = {
        "wp_poster":  ("WordPress投稿が失敗している", "記事が公開されず広告収入・アフィリエイト収入が発生しない"),
        "sanai":      ("品質スコアが低下している",     "タイトル汚染が発生しCVR・SEO評価が下がる"),
        "butterfree": ("SEO最適化が遅延している",      "検索流入が減りCTRが低下する"),
        "kairyu":     ("速報配信が遅延している",        "記事の鮮度が落ちPV・エンゲージが低下する"),
        "arceus":     ("品質ゲートで記事を却下している", "良質記事がパイプラインを通過できないリスクがある"),
    }
    blocker_html = ""
    for blk in rev_blockers:
        aid  = blk.get("id","")
        prob, impact = BLOCKER_INFO2.get(aid, ("—","—"))
        action = BLOCKER_ACTIONS.get(aid, "logs/pipeline_steps.jsonl を確認し、直近3runの失敗原因を切り分ける")
        log    = "logs/pipeline_steps.jsonl"
        rate   = blk.get("rate", 0)
        rnk    = blk.get("rank","🟡")
        rc     = rank_color(rnk)
        blocker_html += f"""
        <div style="background:#111827;border:1px solid #1e293b;border-left:4px solid {rc};border-radius:10px;padding:18px 20px;margin-bottom:14px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
            <span style="font-size:1.05rem;font-weight:800;color:{rc}">{blk.get('name','')}</span>
            <span style="background:{rc}22;color:{rc};border-radius:4px;padding:2px 8px;font-size:0.75rem;font-weight:700">{pct(rate)}</span>
            {status_badge(blk.get('status',''))}
          </div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:0.83rem;line-height:1.6">
            <span style="color:#64748b;font-weight:700;white-space:nowrap">🔥 問題</span>
            <span style="color:#f1f5f9">{prob}</span>
            <span style="color:#64748b;font-weight:700;white-space:nowrap">💰 売上影響</span>
            <span style="color:#fbbf24">{impact}</span>
            <span style="color:#64748b;font-weight:700;white-space:nowrap">📄 今見るログ</span>
            <span style="color:#60a5fa;font-family:monospace">{log}</span>
            <span style="color:#64748b;font-weight:700;white-space:nowrap">▶ 次アクション</span>
            <span style="color:#22c55e">{action}</span>
          </div>
        </div>"""
    if not blocker_html:
        blocker_html = '<div style="color:#22c55e;padding:16px;background:#111827;border-radius:10px">✅ 売上阻害ボトルネックなし</div>'

    # 通知履歴フィルタ付き行（data属性付与）
    hist_rows_filtered = ""
    for h in hist_recent:
        res = h.get("result","")
        rc_h = {"sent":"#22c55e","suppressed":"#64748b","webhook_not_set":"#94a3b8"}.get(res, "#ef4444")
        sev = h.get("severity","")
        sc2 = "#ef4444" if sev=="CRITICAL" else ("#f59e0b" if sev=="WARNING" else "#64748b")
        is_fail = "fail" if res not in ("sent","suppressed","skipped","webhook_not_set") else ""
        row_class = f"hrow sev-{sev.lower() if sev else 'other'} res-{res if res else 'other'} {is_fail}"
        hist_rows_filtered += f"""<tr class="{row_class}" data-sev="{sev}" data-res="{res}">
          <td style="font-size:0.72rem;color:#94a3b8;white-space:nowrap">{fmt_ts(h.get('sent_at',''))}</td>
          <td><span style="color:{sc2};font-weight:700;font-size:0.75rem">{sev}</span></td>
          <td style="font-size:0.72rem;color:#64748b">{h.get('rule','')}</td>
          <td style="font-size:0.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{h.get('title','')}</td>
          <td><span style="color:{rc_h};font-size:0.75rem;font-weight:700">{res}</span></td>
          <td style="font-size:0.72rem;color:#64748b">{h.get('channel','')}</td>
        </tr>"""
    if not hist_rows_filtered:
        hist_rows_filtered = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:16px">通知履歴なし</td></tr>'

    # ─── CEO意思決定ボード ───
    conf_color = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}.get(ceo_confidence, "#64748b")
    conf_label = {"HIGH": "🔴 HIGH — 今すぐ動く", "MEDIUM": "🟡 MEDIUM — 今日中に動く", "LOW": "🟢 LOW — 通常監視"}.get(ceo_confidence, ceo_confidence)

    def _ceo_row(icon, label, text, color="#e2e8f0", highlight=False):
        bg = f"background:{color}12;border-left:3px solid {color}" if highlight else "border-left:3px solid #1e293b"
        return f'''<div style="{bg};padding:10px 16px;border-radius:0 6px 6px 0;margin-bottom:6px">
          <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">
            <span style="font-size:0.7rem;font-weight:800;color:{color};text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;min-width:90px">{icon} {label}</span>
            <span style="font-size:0.88rem;font-weight:600;color:#f1f5f9;line-height:1.4">{text}</span>
          </div>
        </div>'''

    ceo_board_html = f"""<div style="background:linear-gradient(135deg,#0c0f1a,#111827);border:1px solid #1e293b;border-top:3px solid {conf_color};border-radius:12px;padding:18px 20px;margin-bottom:14px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
    <div>
      <div style="font-size:0.65rem;font-weight:800;color:#475569;text-transform:uppercase;letter-spacing:0.12em">👑 ミュウツー CEO — 意思決定ボード</div>
      <div style="font-size:0.72rem;color:{conf_color};font-weight:700;margin-top:3px">{conf_label}</div>
    </div>
    <div style="margin-left:auto;font-size:0.68rem;color:#374151">{now_str}</div>
  </div>
  {_ceo_row('🩸', '今すぐ止血', ceo_immediate, '#ef4444', True)}
  {_ceo_row('🔧', '今日直す1点', ceo_today_fix, '#f59e0b', True)}
  {_ceo_row('💰', '今日の売上レバー', ceo_rev_lever, '#22c55e', False)}
  {_ceo_row('😴', '今は触らない', ceo_ignore, '#475569', False)}
  <div style="margin-top:12px;padding-top:10px;border-top:1px solid #1e293b">
    <div style="font-size:0.65rem;font-weight:700;color:#374151;margin-bottom:4px">📋 判断理由</div>
    <div style="font-size:0.78rem;color:#64748b;line-height:1.6">{ceo_reason if ceo_reason else '—'}</div>
  </div>
</div>"""

    # ─── セクションL: CEO実行命令キュー ───
    PRIO_COLOR  = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    ATYPE_LABEL = {
        "retry_alert_queue":       "再送実行",
        "inspect_agent_failure":   "エージェント調査",
        "inspect_revenue_blocker": "売上阻害調査",
        "monitor_only":            "監視継続",
    }
    STATUS_COLOR = {
        "pending":            "#f59e0b",
        "in_progress":        "#60a5fa",
        "done":               "#22c55e",
        "failed":             "#ef4444",
        "blocked":            "#64748b",
        "skipped_duplicate":  "#475569",
        "skipped_unsafe":     "#374151",
        "skipped":            "#475569",
    }

    # 最新10件（新しい順）
    ceo_queue_recent = list(reversed(ceo_action_queue))[:10]

    # Lセクション用件数サマリー
    q_pending_cnt  = sum(1 for r in ceo_action_queue if r.get("status") == "pending")
    q_blocked_cnt  = sum(1 for r in ceo_action_queue if r.get("status") == "blocked")
    q_skipped_cnt  = sum(1 for r in ceo_action_queue if r.get("status") in ("skipped_duplicate","skipped_unsafe"))
    q_done_cnt     = sum(1 for r in ceo_action_queue if r.get("status") == "done")

    ceo_queue_rows = ""
    for rec in ceo_queue_recent:
        status   = rec.get("status", "pending")
        pc       = PRIO_COLOR.get(rec.get("priority","LOW"), "#64748b")
        at       = ATYPE_LABEL.get(rec.get("action_type","monitor_only"), rec.get("action_type",""))
        sc       = STATUS_COLOR.get(status, "#64748b")
        exec_rec = rec.get("execute_recommended", False)
        # execute_recommended=false は行全体をグレー化
        row_opacity = "opacity:1" if exec_rec else "opacity:0.45"
        exe_badge = (
            '<span style="background:#22c55e;color:#fff;padding:2px 6px;border-radius:4px;font-size:0.68rem;font-weight:800">推奨</span>'
            if exec_rec else
            '<span style="background:#374151;color:#64748b;padding:2px 6px;border-radius:4px;font-size:0.68rem">不要</span>'
        )
        ceo_queue_rows += f"""<tr style="{row_opacity}">
          <td><span style="background:{pc};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{rec.get('priority','—')}</span></td>
          <td style="font-size:0.78rem;font-weight:700;color:#e2e8f0">{at}</td>
          <td style="font-size:0.8rem;font-weight:700;color:{pc}">{rec.get('target_agent','—') or '—'}</td>
          <td style="font-size:0.72rem;color:#60a5fa;font-family:monospace">{rec.get('target_log','') or '—'}</td>
          <td style="font-size:0.78rem;color:#94a3b8;max-width:200px">{rec.get('expected_effect','')[:55]}{'…' if len(rec.get('expected_effect',''))>55 else ''}</td>
          <td><span style="background:{sc};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700">{status}</span></td>
          <td>{exe_badge}</td>
          <td style="font-size:0.68rem;color:#374151;white-space:nowrap">{fmt_ts(rec.get('generated_at',''))}</td>
        </tr>"""
    if not ceo_queue_rows:
        ceo_queue_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">命令キューなし</td></tr>'

    # 最新命令ハイライトカード
    latest_cmd = ceo_queue_recent[0] if ceo_queue_recent else {}
    lc_prio    = latest_cmd.get("priority","—")
    lc_color   = PRIO_COLOR.get(lc_prio, "#64748b")
    lc_type    = ATYPE_LABEL.get(latest_cmd.get("action_type",""), latest_cmd.get("action_type","—"))
    lc_agent   = latest_cmd.get("target_agent","") or "—"
    lc_log     = latest_cmd.get("target_log","") or "—"
    lc_effect  = latest_cmd.get("expected_effect","") or "—"
    lc_reason  = latest_cmd.get("reason","") or "—"
    lc_exec    = "✅ 実行推奨" if latest_cmd.get("execute_recommended") else "— 実行不要"
    lc_exec_color = "#22c55e" if latest_cmd.get("execute_recommended") else "#475569"

    latest_cmd_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid {lc_color};border-radius:10px;padding:16px 20px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
    <span style="background:{lc_color};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{lc_prio}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{lc_type}</span>
    <span style="font-size:0.82rem;font-weight:700;color:{lc_color}">{lc_agent}</span>
    <span style="margin-left:auto;font-size:0.75rem;font-weight:700;color:{lc_exec_color}">{lc_exec}</span>
  </div>
  <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:0.8rem;line-height:1.7">
    <span style="color:#475569;font-weight:700">📄 対象ログ</span>
    <span style="color:#60a5fa;font-family:monospace">{lc_log}</span>
    <span style="color:#475569;font-weight:700">💡 期待効果</span>
    <span style="color:#22c55e">{lc_effect}</span>
    <span style="color:#475569;font-weight:700">🔍 根拠</span>
    <span style="color:#94a3b8">{lc_reason}</span>
  </div>
</div>""" if latest_cmd else ""

    ceo_queue_section_html = f"""<div class="section" id="ceo-queue">
  <div class="section-title">
    <span class="section-title-icon">🧾</span>
    L. CEO実行命令キュー — ミュウツー v{ceo_act_ver}
    <span style="margin-left:auto;font-size:0.72rem;color:{PRIO_COLOR.get(ceo_act_priority,'#64748b')}">最新: {ceo_act_priority} / {ATYPE_LABEL.get(ceo_act_type, ceo_act_type)}</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🕐 pending {q_pending_cnt}</span>
    <span style="background:#64748b22;border:1px solid #64748b55;color:#94a3b8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {q_blocked_cnt}</span>
    <span style="background:#47556922;border:1px solid #47556955;color:#64748b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⏭ skipped {q_skipped_cnt}</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ done {q_done_cnt}</span>
  </div>
  {latest_cmd_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:720px">
      <thead><tr>
        <th>優先度</th><th>命令種別</th><th>対象AI</th><th>対象ログ</th><th>期待効果</th><th>状態</th><th>実行推奨</th><th>生成日時</th>
      </tr></thead>
      <tbody>{ceo_queue_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ⚠️ これは命令の記録のみです。自動実行はしません。execute_recommended=true の場合のみ手動で対処してください。
  </div>
</div>"""

    # ─── セクションM: CEO命令実行ログ ───
    RESULT_COLOR = {
        "done":               "#22c55e",
        "failed":             "#ef4444",
        "blocked":            "#64748b",
        "skipped":            "#475569",
        "skipped_duplicate":  "#475569",
        "skipped_unsafe":     "#374151",
        "in_progress":        "#60a5fa",
        "no_pending":         "#334155",
    }
    REASON_LABEL = {
        "unsupported_action_type":  "未対応タイプ",
        "missing_target_log":       "対象ログ欠落",
        "no_recent_data":           "データなし",
        "duplicate_in_progress":    "実行中重複",
        "skipped_duplicate_done":   "直近済み重複",
        "unsafe_operation_denied":  "実行推奨なし",
        "exception_during_exec":    "例外エラー",
        "queue_write_failure":      "キュー書込失敗",
    }

    ceo_exec_recent = list(reversed(ceo_exec_history))[:10]

    # pending残件数（queueから）
    exec_pending_remaining = sum(1 for r in ceo_action_queue if r.get("status") == "pending")
    exec_blocked_in_q      = sum(1 for r in ceo_action_queue if r.get("status") == "blocked")
    exec_skipped_in_q      = sum(1 for r in ceo_action_queue if r.get("status") in ("skipped_duplicate","skipped_unsafe"))

    # セクションM 上部 実行サマリーカード
    ls_state   = ceo_exec_state
    ls_result  = ls_state.get("last_result", "—")
    ls_color   = RESULT_COLOR.get(ls_result, "#94a3b8")
    ls_type    = ATYPE_LABEL.get(ls_state.get("last_action_type",""), ls_state.get("last_action_type","—"))
    ls_agent   = ls_state.get("last_target_agent","") or "—"
    ls_summ    = ls_state.get("last_summary","") or "—"
    ls_reason  = REASON_LABEL.get(ls_state.get("last_reason",""), ls_state.get("last_reason","") or "—")
    ls_at      = fmt_ts(ls_state.get("last_executed_at","")) if ls_state else "未実行"
    ls_proc       = ls_state.get("processed_count_this_run", ceo_exec_processed)
    ls_done       = ls_state.get("done_count_this_run", ceo_exec_done)
    ls_failed     = ls_state.get("failed_count_this_run", ceo_exec_failed)
    ls_blocked    = ls_state.get("blocked_count_this_run", ceo_exec_blocked)
    ls_safe_retry = ls_state.get("safe_retry_count_this_run", ceo_exec_safe_retry)
    ls_safe_insp  = ls_state.get("safe_inspect_count_this_run", ceo_exec_safe_inspect)

    exec_summary_card_html = f"""<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:10px;margin-bottom:16px">
  <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#e2e8f0">{ls_proc}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">今回処理</div>
  </div>
  <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#22c55e">{ls_done}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">done</div>
  </div>
  <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#ef4444">{ls_failed}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">failed</div>
  </div>
  <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#64748b">{ls_blocked}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">blocked</div>
  </div>
  <div style="background:#0d1117;border:1px solid #60a5fa44;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#60a5fa">{ls_safe_retry}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">retry成功</div>
  </div>
  <div style="background:#0d1117;border:1px solid #818cf844;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#818cf8">{ls_safe_insp}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">inspect保存</div>
  </div>
  <div style="background:#0d1117;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center">
    <div style="font-size:1.4rem;font-weight:900;color:#f59e0b">{exec_pending_remaining}</div>
    <div style="font-size:0.68rem;color:#64748b;margin-top:4px">pending残</div>
  </div>
</div>
<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid {ls_color};border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:{ls_color};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{ls_result}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{ls_type}</span>
    <span style="font-size:0.82rem;font-weight:700;color:#818cf8">{ls_agent}</span>
    {'<span style="font-size:0.72rem;color:#f59e0b;background:#1e1408;border:1px solid #78350f;padding:2px 8px;border-radius:4px">' + ls_reason + '</span>' if ls_reason != '—' else ''}
    <span style="margin-left:auto;font-size:0.68rem;color:#374151">{ls_at}</span>
  </div>
  <div style="font-size:0.78rem;color:#94a3b8;line-height:1.6">{ls_summ}</div>
</div>"""

    # 実行ログテーブル（フィルタ付き、reason列追加）
    exec_rows = ""
    for eh in ceo_exec_recent:
        res  = eh.get("result","—")
        rc   = RESULT_COLOR.get(res, "#94a3b8")
        at   = ATYPE_LABEL.get(eh.get("action_type",""), eh.get("action_type","—"))
        summ = eh.get("summary","")
        nxt  = eh.get("next_recommendation","")
        rsn  = REASON_LABEL.get(eh.get("reason",""), eh.get("reason","") or "—")
        # data-result 属性でフィルタリング用
        res_group = res if res in ("done","failed","blocked") else "skipped"
        exec_rows += f"""<tr data-exres="{res_group}">
          <td style="font-size:0.68rem;color:#475569;white-space:nowrap">{fmt_ts(eh.get('executed_at',''))}</td>
          <td style="font-size:0.78rem;font-weight:700;color:#e2e8f0">{at}</td>
          <td style="font-size:0.8rem;font-weight:700;color:{PRIO_COLOR.get(eh.get('priority','LOW'),'#64748b')}">{eh.get('target_agent','') or '—'}</td>
          <td><span style="background:{rc};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{res}</span></td>
          <td style="font-size:0.72rem;color:#f59e0b">{rsn}</td>
          <td style="font-size:0.75rem;color:#94a3b8;max-width:220px">{summ[:75]}{'…' if len(summ)>75 else ''}</td>
          <td style="font-size:0.72rem;color:#64748b;max-width:160px">{nxt[:55]}{'…' if len(nxt)>55 else ''}</td>
        </tr>"""
    if not exec_rows:
        exec_rows = '<tr><td colspan="7" style="color:#64748b;text-align:center;padding:16px">実行履歴なし（初回実行後に表示されます）</td></tr>'

    ceo_exec_section_html = f"""<div class="section" id="ceo-exec">
  <div class="section-title">
    <span class="section-title-icon">⚡</span>
    M. CEO命令実行ログ — 自律改善実行エンジン v2.0
    <span style="margin-left:auto;font-size:0.72rem;color:{ls_color}">最新: {ls_result}</span>
  </div>
  {exec_summary_card_html}
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
    <span style="font-size:0.78rem;font-weight:700;color:#818cf8">📋 実行履歴（最新10件）</span>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-left:auto">
      <button class="hfilter active" data-exfilter="all"     onclick="filterExec('all')">全件</button>
      <button class="hfilter" data-exfilter="done"    onclick="filterExec('done')">done</button>
      <button class="hfilter" data-exfilter="failed"  onclick="filterExec('failed')">failed</button>
      <button class="hfilter" data-exfilter="blocked" onclick="filterExec('blocked')">blocked</button>
      <button class="hfilter" data-exfilter="skipped" onclick="filterExec('skipped')">skipped</button>
    </div>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="exec-table" style="min-width:760px">
      <thead><tr>
        <th>実行日時</th><th>命令種別</th><th>対象AI</th><th>結果</th><th>理由</th><th>要約</th><th>次の推奨</th>
      </tr></thead>
      <tbody>{exec_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ⚠️ 実行エンジンはログ読み取り・集計のみ行います。記事・WordPress・パイプライン本体は変更しません。
  </div>
</div>"""

    # ─── セクションN: 安全実行アクション履歴 ───
    SAFE_REC_TYPE_LABEL = {
        "prompt_fix":       "プロンプト修正",
        "timeout_fix":      "タイムアウト修正",
        "retry_config":     "リトライ設定",
        "manual_restart":   "手動再起動",
        "monitor_continue": "監視継続",
        "alert_retry":      "アラート再送",
        "check_config":     "設定確認",
    }
    SAFE_REC_COLOR = {
        "prompt_fix":       "#f59e0b",
        "timeout_fix":      "#60a5fa",
        "retry_config":     "#818cf8",
        "manual_restart":   "#ef4444",
        "monitor_continue": "#22c55e",
        "alert_retry":      "#06b6d4",
        "check_config":     "#f97316",
    }

    safe_recent = list(reversed(ceo_safe_history))[:15]
    safe_rows = ""
    for sh in safe_recent:
        res   = sh.get("result", "—")
        rc    = RESULT_COLOR.get(res, "#94a3b8")
        at    = ATYPE_LABEL.get(sh.get("action_type",""), sh.get("action_type","—"))
        rtype = sh.get("recommendation_type","")
        rtl   = SAFE_REC_TYPE_LABEL.get(rtype, rtype or "—")
        rtc   = SAFE_REC_COLOR.get(rtype, "#64748b")
        prop  = sh.get("proposed_next_step","")
        res_grp = res if res in ("done","failed","blocked","skipped") else "skipped"
        safe_rows += f"""<tr data-saferes="{res_grp}">
          <td style="font-size:0.68rem;color:#475569;white-space:nowrap">{fmt_ts(sh.get('executed_at',''))}</td>
          <td style="font-size:0.78rem;font-weight:700;color:#e2e8f0">{at}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{sh.get('target_agent','') or '—'}</td>
          <td><span style="background:{rc};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{res}</span></td>
          <td><span style="background:{rtc}22;border:1px solid {rtc}55;color:{rtc};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;white-space:nowrap">{rtl}</span></td>
          <td style="font-size:0.75rem;color:#94a3b8;max-width:280px">{prop[:85]}{'…' if len(prop)>85 else ''}</td>
        </tr>"""
    if not safe_rows:
        safe_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:16px">安全実行履歴なし（初回実行後に表示されます）</td></tr>'

    # safe action 件数サマリー（今日分）
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _today = _dt.now(_tz(+_td(hours=9))).strftime("%Y-%m-%d")
    safe_today = [h for h in ceo_safe_history if h.get("executed_at","").startswith(_today)]
    safe_today_retry   = sum(1 for h in safe_today if h.get("action_type")=="retry_alert_queue" and h.get("result")=="done")
    safe_today_inspect = sum(1 for h in safe_today if h.get("action_type") in ("inspect_agent_failure","inspect_revenue_blocker") and h.get("result")=="done")
    safe_today_skip    = sum(1 for h in safe_today if h.get("result")=="skipped")
    safe_total         = len(ceo_safe_history)
    # recommendation_type 件数（全履歴 done のみ）
    safe_done_all      = [h for h in ceo_safe_history if h.get("result")=="done"]
    safe_cnt_prompt    = sum(1 for h in safe_done_all if h.get("recommendation_type")=="prompt_fix")
    safe_cnt_timeout   = sum(1 for h in safe_done_all if h.get("recommendation_type")=="timeout_fix")
    safe_cnt_monitor   = sum(1 for h in safe_done_all if h.get("recommendation_type")=="monitor_continue")
    safe_cnt_restart   = sum(1 for h in safe_done_all if h.get("recommendation_type")=="manual_restart")
    # 改善候補生成件数（improvement_queue）
    imp_from_safe      = sum(1 for r in ceo_improvement_queue if r.get("status")=="pending")

    ceo_safe_section_html = f"""<div class="section" id="ceo-safe">
  <div class="section-title">
    <span class="section-title-icon">🛡️</span>
    N. 安全実行アクション履歴 — safe actions only
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">累計 {safe_total}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
    <span style="background:#06b6d422;border:1px solid #06b6d455;color:#06b6d4;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔁 今日retry {safe_today_retry}件</span>
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔍 今日inspect {safe_today_inspect}件</span>
    <span style="background:#47556922;border:1px solid #47556955;color:#64748b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⏭ 今日skip {safe_today_skip}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔨 prompt_fix {safe_cnt_prompt}件</span>
    <span style="background:#60a5fa22;border:1px solid #60a5fa55;color:#60a5fa;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⏱ timeout_fix {safe_cnt_timeout}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ monitor {safe_cnt_monitor}件</span>
    {'<span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚨 手動再起動 ' + str(safe_cnt_restart) + '件</span>' if safe_cnt_restart > 0 else ''}
    <span style="background:#a78bfa22;border:1px solid #a78bfa55;color:#a78bfa;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🧩 改善候補生成 {imp_from_safe}件</span>
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
    <span style="font-size:0.78rem;font-weight:700;color:#818cf8">📋 実行履歴（最新15件）</span>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-left:auto">
      <button class="hfilter active" data-safefilter="all"     onclick="filterSafe('all')">全件</button>
      <button class="hfilter" data-safefilter="done"    onclick="filterSafe('done')">done</button>
      <button class="hfilter" data-safefilter="skipped" onclick="filterSafe('skipped')">skipped</button>
      <button class="hfilter" data-safefilter="failed"  onclick="filterSafe('failed')">failed</button>
    </div>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="safe-table" style="min-width:700px">
      <thead><tr>
        <th>実行日時</th><th>命令種別</th><th>対象AI</th><th>結果</th><th>推奨タイプ</th><th>次の改善提案</th>
      </tr></thead>
      <tbody>{safe_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🛡️ safe actionsはログ読み取り・再送・改善提案保存のみ行います。記事・WordPress・パイプラインは変更しません。
  </div>
</div>"""

    # ─── セクションO: CEO改善候補キュー ───
    IMP_TYPE_LABEL = {
        "prompt_fix":       "プロンプト修正",
        "timeout_fix":      "タイムアウト修正",
        "monitor_continue": "監視継続",
        "retry_config":     "リトライ設定",
    }
    IMP_TYPE_COLOR = {
        "prompt_fix":       "#f59e0b",
        "timeout_fix":      "#60a5fa",
        "monitor_continue": "#22c55e",
        "retry_config":     "#818cf8",
    }

    # ready_queue 昇格済みの duplicate_key セット（セクションO の列表示用）
    ready_promoted_keys = set(
        r.get("duplicate_key","")
        for r in ceo_ready_queue
        if r.get("status") in ("pending", "done") and r.get("duplicate_key")
    )

    imp_recent   = list(reversed(ceo_improvement_queue))[:20]
    imp_pending  = [r for r in ceo_improvement_queue if r.get("status")=="pending"]
    imp_high     = sum(1 for r in imp_pending if r.get("priority")=="HIGH")
    imp_medium   = sum(1 for r in imp_pending if r.get("priority")=="MEDIUM")
    imp_low      = sum(1 for r in imp_pending if r.get("priority")=="LOW")
    imp_safe_n   = sum(1 for r in imp_pending if r.get("safety_class")=="SAFE")
    imp_review_n = sum(1 for r in imp_pending if r.get("safety_class")=="REVIEW")
    imp_blocked_n= sum(1 for r in imp_pending if r.get("safety_class")=="BLOCKED")
    imp_exec_true= sum(1 for r in imp_pending if r.get("execute_recommended") is True)
    imp_latest   = imp_recent[0] if imp_recent else {}

    SAFETY_COLOR = {"SAFE": "#22c55e", "REVIEW": "#f59e0b", "BLOCKED": "#ef4444"}

    imp_rows = ""
    for ir in imp_recent:
        status   = ir.get("status","pending")
        prio     = ir.get("priority","LOW")
        pc       = PRIO_COLOR.get(prio, "#64748b")
        itype    = ir.get("improvement_type","")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        sc_stat  = STATUS_COLOR.get(status, "#64748b")
        reason   = ir.get("reason","")
        rec_reason = ir.get("recommendation_reason","")
        proposed = ir.get("proposed_change","")
        exec_rec = ir.get("execute_recommended", False)
        sc_cls   = ir.get("safety_class","")
        hr       = ir.get("human_review_required", True)
        sc_col   = SAFETY_COLOR.get(sc_cls, "#64748b")
        row_op   = "opacity:1" if status=="pending" else "opacity:0.5"
        exec_badge = (
            '<span style="color:#22c55e;font-weight:800;font-size:0.8rem">✅ 推奨</span>'
            if exec_rec else
            '<span style="color:#64748b;font-size:0.75rem">— 保留</span>'
        )
        sc_badge = (
            f'<span style="background:{sc_col}22;border:1px solid {sc_col}55;color:{sc_col};'
            f'padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{sc_cls or "—"}</span>'
        )
        hr_badge = (
            '<span style="color:#f59e0b;font-size:0.68rem">👁 要確認</span>'
            if hr else
            '<span style="color:#22c55e;font-size:0.68rem">自動OK</span>'
        )
        tooltip_reason = rec_reason.replace('"', '&quot;')[:160] if rec_reason else reason[:160]
        dup_key_ir = f"{ir.get('target_agent','')}|{ir.get('improvement_type','')}|{proposed}"
        is_ready = dup_key_ir in ready_promoted_keys
        ready_badge = (
            '<span style="color:#22c55e;font-size:0.72rem;font-weight:800">✅ READY</span>'
            if is_ready else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        imp_rows += f"""<tr class="imp-row" data-sc="{sc_cls}" data-exec="{str(exec_rec).lower()}" style="{row_op}">
          <td><span style="background:{pc};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{prio}</span></td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ir.get('target_agent','') or '—'}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="font-size:0.75rem;color:#94a3b8;max-width:160px" title="{tooltip_reason}">{(rec_reason or reason)[:50]}{'…' if len(rec_reason or reason)>50 else ''}</td>
          <td style="font-size:0.75rem;color:#e2e8f0;max-width:200px">{proposed[:60]}{'…' if len(proposed)>60 else ''}</td>
          <td><span style="background:{sc_stat};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700">{status}</span></td>
          <td style="text-align:center">{exec_badge}</td>
          <td style="text-align:center">{sc_badge}</td>
          <td style="text-align:center">{hr_badge}</td>
          <td style="text-align:center">{ready_badge}</td>
        </tr>"""
    if not imp_rows:
        imp_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">改善候補キューなし（inspect実行後に生成されます）</td></tr>'

    # 最新ハイライト
    il_prio    = imp_latest.get("priority","—")
    il_color   = PRIO_COLOR.get(il_prio, "#64748b")
    il_agent   = imp_latest.get("target_agent","") or "—"
    il_type    = IMP_TYPE_LABEL.get(imp_latest.get("improvement_type",""), imp_latest.get("improvement_type","—"))
    il_reason  = imp_latest.get("reason","") or "—"
    il_prop    = imp_latest.get("proposed_change","") or "—"
    il_sc_cls  = imp_latest.get("safety_class","")
    il_sc_col  = SAFETY_COLOR.get(il_sc_cls, "#64748b")
    il_exec    = imp_latest.get("execute_recommended", False)
    il_rec_rsn = imp_latest.get("recommendation_reason","") or il_reason
    il_hr      = imp_latest.get("human_review_required", True)
    latest_imp_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid {il_sc_col if il_sc_cls else il_color};border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:{il_color};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{il_prio}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{il_type}</span>
    <span style="font-size:0.82rem;font-weight:700;color:#818cf8">{il_agent}</span>
    {'<span style="background:' + il_sc_col + '22;border:1px solid ' + il_sc_col + '55;color:' + il_sc_col + ';padding:2px 10px;border-radius:4px;font-size:0.72rem;font-weight:800">' + il_sc_cls + '</span>' if il_sc_cls else ''}
    <span style="margin-left:auto;font-size:0.72rem;{'color:#22c55e;font-weight:800' if il_exec else 'color:#64748b'}">{'✅ 実行推奨' if il_exec else '— 保留'}</span>
    {'<span style="font-size:0.68rem;color:#f59e0b">👁 要人間確認</span>' if il_hr else '<span style="font-size:0.68rem;color:#22c55e">自動OK</span>'}
  </div>
  <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:0.8rem;line-height:1.7">
    <span style="color:#475569;font-weight:700">📋 判定根拠</span><span style="color:#94a3b8">{il_rec_rsn[:140]}{'…' if len(il_rec_rsn)>140 else ''}</span>
    <span style="color:#475569;font-weight:700">🔨 改善案</span><span style="color:#e2e8f0">{il_prop[:120]}{'…' if len(il_prop)>120 else ''}</span>
  </div>
</div>""" if imp_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">改善候補なし</div>'

    ceo_improvement_section_html = f"""<div class="section" id="ceo-improvement">
  <div class="section-title">
    <span class="section-title-icon">🧩</span>
    O. CEO改善候補キュー — ミュウツー
    <span style="margin-left:auto;font-size:0.72rem;color:{PRIO_COLOR.get('HIGH','#ef4444') if imp_high>0 else '#64748b'}">pending {len(imp_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {imp_high}</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {imp_medium}</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {imp_low}</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_improvement_queue)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 SAFE {imp_safe_n}</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 REVIEW {imp_review_n}</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 BLOCKED {imp_blocked_n}</span>
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ 実行推奨 {imp_exec_true}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterImp('all')" id="imp-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="imp-filter-btn imp-active">全件</button>
    <button onclick="filterImp('SAFE')" id="imp-btn-SAFE" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="imp-filter-btn">SAFE</button>
    <button onclick="filterImp('REVIEW')" id="imp-btn-REVIEW" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="imp-filter-btn">REVIEW</button>
    <button onclick="filterImp('BLOCKED')" id="imp-btn-BLOCKED" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="imp-filter-btn">BLOCKED</button>
    <button onclick="filterImp('exec_true')" id="imp-btn-exec_true" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="imp-filter-btn">実行推奨=true</button>
    <button onclick="filterImp('exec_false')" id="imp-btn-exec_false" style="background:#1e293b;color:#64748b;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="imp-filter-btn">実行推奨=false</button>
  </div>
  {latest_imp_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th>優先度</th><th>対象AI</th><th>改善タイプ</th><th>判定根拠</th><th>改善案</th><th>状態</th><th>実行推奨</th><th>安全クラス</th><th>要確認</th><th>READY</th>
      </tr></thead>
      <tbody id="imp-tbody">{imp_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧩 改善候補キューは safe action 調査結果から自動生成されます。SAFE=自動実行推奨 / REVIEW=条件未達 / BLOCKED=手動のみ。実行はオーナーが判断してください。
  </div>
</div>
<script>
function filterImp(mode) {{
  document.querySelectorAll('.imp-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('imp-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.imp-row').forEach(function(row) {{
    var sc   = row.getAttribute('data-sc') || '';
    var exec = row.getAttribute('data-exec') || 'false';
    var show = false;
    if (mode === 'all')        show = true;
    else if (mode === 'SAFE')  show = sc === 'SAFE';
    else if (mode === 'REVIEW') show = sc === 'REVIEW';
    else if (mode === 'BLOCKED') show = sc === 'BLOCKED';
    else if (mode === 'exec_true')  show = exec === 'true';
    else if (mode === 'exec_false') show = exec === 'false';
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションP: 実行準備キュー (SAFE昇格) ───
    rq_recent  = list(reversed(ceo_ready_queue))[:20]
    rq_pending = [r for r in ceo_ready_queue if r.get("status") == "pending"]
    rq_high    = sum(1 for r in rq_pending if r.get("priority") == "HIGH")
    rq_medium  = sum(1 for r in rq_pending if r.get("priority") == "MEDIUM")
    rq_dup_cnt = sum(1 for r in ceo_ready_queue if r.get("status") == "promoted_duplicate")
    rq_latest  = rq_recent[0] if rq_recent else {}

    rq_rows = ""
    for rr in rq_recent:
        status   = rr.get("status", "pending")
        prio     = rr.get("priority", "LOW")
        pc_rq    = PRIO_COLOR.get(prio, "#64748b")
        sc_stat_rq = STATUS_COLOR.get(status, "#64748b")
        itype    = rr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = rr.get("target_agent", "") or "—"
        proposed = rr.get("proposed_change", "")
        promoted_at = rr.get("promoted_at", "")[:16].replace("T", " ")
        exec_badge_rq = '<span style="color:#22c55e;font-weight:800;font-size:0.8rem">✅ 推奨</span>'
        sc_badge_rq   = '<span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">SAFE</span>'
        row_op_rq  = "opacity:1" if status == "pending" else "opacity:0.5"
        rq_rows += f"""<tr class="rq-row" data-prio="{prio}" data-sc="SAFE" data-status="{status}" style="{row_op_rq}">
          <td style="font-size:0.72rem;color:#475569;white-space:nowrap">{promoted_at}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td><span style="background:{pc_rq};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{prio}</span></td>
          <td style="text-align:center">{sc_badge_rq}</td>
          <td style="text-align:center">{exec_badge_rq}</td>
          <td style="font-size:0.75rem;color:#e2e8f0;max-width:240px">{proposed[:80]}{'…' if len(proposed)>80 else ''}</td>
          <td><span style="background:{sc_stat_rq};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700">{status}</span></td>
        </tr>"""
    if not rq_rows:
        rq_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">実行準備キューなし（SAFE候補がimprovement_queueに積まれると自動生成されます）</td></tr>'

    rq_latest_agent = rq_latest.get("target_agent", "") or "—"
    rq_latest_type  = IMP_TYPE_LABEL.get(rq_latest.get("improvement_type",""), rq_latest.get("improvement_type","—"))
    rq_latest_prio  = rq_latest.get("priority", "—")
    rq_latest_prop  = rq_latest.get("proposed_change", "") or "—"
    rq_latest_promoted = rq_latest.get("promoted_at","")[:16].replace("T"," ") if rq_latest else "—"
    rq_lc  = PRIO_COLOR.get(rq_latest_prio, "#64748b")
    rq_latest_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #22c55e;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">SAFE</span>
    <span style="background:{rq_lc};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{rq_latest_prio}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{rq_latest_type}</span>
    <span style="font-size:0.82rem;font-weight:700;color:#818cf8">{rq_latest_agent}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#374151;background:#1e293b;padding:2px 8px;border-radius:4px">昇格: {rq_latest_promoted}</span>
  </div>
  <div style="font-size:0.8rem;color:#e2e8f0;line-height:1.7">
    <span style="color:#475569;font-weight:700">🔨 改善案: </span>{rq_latest_prop[:150]}{'…' if len(rq_latest_prop)>150 else ''}
  </div>
</div>""" if rq_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">実行準備候補なし</div>'

    ceo_ready_section_html = f"""<div class="section" id="ceo-ready">
  <div class="section-title">
    <span class="section-title-icon">🚀</span>
    P. 実行準備キュー — SAFEのみ
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">pending {len(rq_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 SAFE pending {len(rq_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {rq_high}</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {rq_medium}</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">重複抑止 {rq_dup_cnt}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_ready_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterRQ('all')" id="rq-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rq-filter-btn rq-active">全件</button>
    <button onclick="filterRQ('HIGH')" id="rq-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rq-filter-btn">HIGH</button>
    <button onclick="filterRQ('MEDIUM')" id="rq-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rq-filter-btn">MEDIUM</button>
    <button onclick="filterRQ('SAFE')" id="rq-btn-SAFE" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rq-filter-btn">SAFE</button>
    <button onclick="filterRQ('pending')" id="rq-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rq-filter-btn">pending</button>
  </div>
  {rq_latest_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:860px">
      <thead><tr>
        <th>昇格日時</th><th>対象AI</th><th>改善タイプ</th><th>優先度</th><th>安全クラス</th><th>実行推奨</th><th>改善案</th><th>状態</th>
      </tr></thead>
      <tbody id="rq-tbody">{rq_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🚀 SAFE判定の改善候補のみ自動昇格。実行はオーナーが判断してください。REVIEW/BLOCKEDはここには表示されません。
  </div>
</div>
<script>
function filterRQ(mode) {{
  document.querySelectorAll('.rq-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('rq-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.rq-row').forEach(function(row) {{
    var prio   = row.getAttribute('data-prio') || '';
    var sc     = row.getAttribute('data-sc') || '';
    var status = row.getAttribute('data-status') || '';
    var show = false;
    if (mode === 'all')     show = true;
    else if (mode === 'HIGH')    show = prio === 'HIGH';
    else if (mode === 'MEDIUM')  show = prio === 'MEDIUM';
    else if (mode === 'SAFE')    show = sc === 'SAFE';
    else if (mode === 'pending') show = status === 'pending';
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションR/S/T: 実行候補レーン + シミュレーション + 優先順位 ───
    ceo_exec_ready_queue   = load_jsonl_safe("logs/ceo_execution_ready_queue.jsonl")
    ceo_exec_ready_history = load_jsonl_safe("logs/ceo_execution_ready_history.jsonl")
    ceo_sim_queue          = load_jsonl_safe("logs/ceo_execution_simulation.jsonl")
    ceo_ranked_queue       = load_jsonl_safe("logs/ceo_execution_ranked_queue.jsonl")

    # EXECUTION_READY昇格済み duplicate_key セット（セクションQ列表示用）
    exec_ready_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_exec_ready_queue
        if r.get("status") in ("pending",) and r.get("duplicate_key")
    )
    # SIMULATION登録済み duplicate_key セット（セクションR列表示用）
    sim_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_sim_queue
        if r.get("status") in ("pending", "done") and r.get("duplicate_key")
    )
    # RANKED登録済み duplicate_key セット（セクションS列表示用）
    ranked_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_ranked_queue
        if r.get("status") in ("pending", "held") and r.get("duplicate_key")
    )
    # PACKET queue読み込みとPACKET済みキーセット（セクションT列表示用）
    ceo_packet_queue = load_jsonl_safe("logs/ceo_execution_packet_queue.jsonl")
    packet_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_packet_queue
        if r.get("packet_status") in ("pending", "archived") and r.get("duplicate_key")
    )
    # DISPATCH queue読み込みとDISPATCH済みキーセット（セクションU列表示用）
    ceo_dispatch_queue = load_jsonl_safe("logs/ceo_execution_dispatch_request_queue.jsonl")
    dispatch_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_dispatch_queue
        if r.get("dispatch_status") in ("pending", "archived") and r.get("duplicate_key")
    )
    # STUB/DRYRUN/CANDIDATE queue読み込みとキーセット
    ceo_stub_queue          = load_jsonl_safe("logs/ceo_execution_executor_stub_queue.jsonl")
    ceo_dry_run_queue       = load_jsonl_safe("logs/ceo_execution_dry_run_result_queue.jsonl")
    ceo_candidate_queue     = load_jsonl_safe("logs/ceo_execution_candidate_queue.jsonl")
    ceo_limited_exec_queue     = load_jsonl_safe("logs/ceo_limited_execution_queue.jsonl")
    ceo_guard_result_queue     = load_jsonl_safe("logs/ceo_execution_guard_result_queue.jsonl")
    ceo_patch_plan_queue       = load_jsonl_safe("logs/ceo_config_patch_plan_queue.jsonl")
    ceo_config_apply_queue     = load_jsonl_safe("logs/ceo_config_apply_queue.jsonl")
    ceo_config_apply_result    = load_jsonl_safe("logs/ceo_config_apply_result_queue.jsonl")
    ceo_exec_result_queue      = load_jsonl_safe("logs/ceo_agent_execution_result_queue.jsonl")
    ceo_perf_eval_queue        = load_jsonl_safe("logs/ceo_performance_evaluation_queue.jsonl")
    ceo_feedback_loop_queue    = load_jsonl_safe("logs/ceo_feedback_loop_queue.jsonl")
    ceo_reinject_priority_queue  = load_jsonl_safe("logs/ceo_reinject_priority_queue.jsonl")
    ceo_reinject_dispatch_queue  = load_jsonl_safe("logs/ceo_reinject_dispatch_queue.jsonl")
    ceo_reinject_return_queue    = load_jsonl_safe("logs/ceo_reinject_limited_return_queue.jsonl")
    ceo_reinject_gate_queue      = load_jsonl_safe("logs/ceo_reinject_gate_queue.jsonl")
    ceo_reinject_patch_ready     = load_jsonl_safe("logs/ceo_reinject_patch_ready_queue.jsonl")
    ceo_reinject_patch_reserve   = load_jsonl_safe("logs/ceo_reinject_patch_reserve_queue.jsonl")
    ceo_reinject_commit_queue    = load_jsonl_safe("logs/ceo_reinject_patch_commit_queue.jsonl")
    ceo_reinject_apply_gate      = load_jsonl_safe("logs/ceo_reinject_apply_gate_queue.jsonl")
    ceo_reinject_apply_ready     = load_jsonl_safe("logs/ceo_reinject_apply_ready_queue.jsonl")
    ceo_reinject_unlock_candidate = load_jsonl_safe("logs/ceo_reinject_apply_unlock_candidate_queue.jsonl")
    ceo_reinject_unlock_judge     = load_jsonl_safe("logs/ceo_reinject_unlock_judge_queue.jsonl")
    ceo_unlock_execute_queue      = load_jsonl_safe("logs/ceo_unlock_execute_queue.jsonl")
    ceo_apply_execute_queue       = load_jsonl_safe("logs/ceo_apply_execute_queue.jsonl")
    ceo_apply_execute_result      = load_jsonl_safe("logs/ceo_apply_execute_result_queue.jsonl")
    ceo_unlock_expiry_queue       = load_jsonl_safe("logs/ceo_unlock_expiry_queue.jsonl")
    ceo_post_apply_lock_queue     = load_jsonl_safe("logs/ceo_post_apply_lock_queue.jsonl")
    ceo_rollback_request_queue    = load_jsonl_safe("logs/ceo_rollback_request_queue.jsonl")
    ceo_stale_operation_queue     = load_jsonl_safe("logs/ceo_stale_operation_queue.jsonl")
    ceo_post_apply_judge_queue    = load_jsonl_safe("logs/ceo_post_apply_judge_queue.jsonl")
    ceo_rollback_dispatch_queue   = load_jsonl_safe("logs/ceo_rollback_dispatch_queue.jsonl")
    ceo_rollback_watch_queue      = load_jsonl_safe("logs/ceo_rollback_watch_queue.jsonl")
    ceo_stale_cleanup_plan_queue  = load_jsonl_safe("logs/ceo_stale_cleanup_plan_queue.jsonl")
    ceo_invariant_violation_queue = load_jsonl_safe("logs/ceo_invariant_violation_queue.jsonl")
    ceo_auto_exec_log_queue       = load_jsonl_safe("logs/ceo_auto_exec_log_queue.jsonl")
    ceo_auto_rollback_result      = load_jsonl_safe("logs/ceo_auto_rollback_result_queue.jsonl")
    ceo_safe_auto_gate_queue      = load_jsonl_safe("logs/ceo_safe_auto_gate_queue.jsonl")
    ceo_stale_resolution_queue    = load_jsonl_safe("logs/ceo_stale_resolution_queue.jsonl")
    ceo_unlock_pick_queue         = load_jsonl_safe("logs/ceo_unlock_pick_queue.jsonl")
    ceo_mode_transition_queue     = load_jsonl_safe("logs/ceo_mode_transition_queue.jsonl")
    ceo_unlock_explain_queue      = load_jsonl_safe("logs/ceo_unlock_explain_queue.jsonl")
    ceo_apply_explain_queue       = load_jsonl_safe("logs/ceo_apply_explain_queue.jsonl")
    ceo_final_block_queue         = load_jsonl_safe("logs/ceo_final_block_queue.jsonl")
    ceo_post_command_checklist    = load_jsonl_safe("logs/ceo_post_command_checklist_queue.jsonl")
    try:
        import json as _ljson
        _lp = Path("lifecycle_traces.json")
        lifecycle_traces = _ljson.loads(_lp.read_text()) if _lp.exists() else []
    except Exception:
        lifecycle_traces = []
    # dispatch済みキーセット（AHセクションのDISPATCH列用）
    dispatched_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_dispatch_queue
        if r.get("dispatch_status") in ("pending", "archived")
    }
    # gate済みキーセット（AJセクションのGATE列用）
    gated_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_gate_queue
        if r.get("gate_status") in ("pending", "blocked", "archived")
    }
    # reserve済みキーセット（ALセクションのRESERVE列用）
    reserved_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_patch_reserve
        if r.get("reserve_status") in ("pending", "archived")
    }
    # commit済みキーセット（AMセクションのCOMMIT列用）
    committed_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_commit_queue
        if r.get("commit_status") in ("pending", "archived")
    }
    # apply_ready済みキーセット（ANセクションのAPPLY_READY列用）
    apply_ready_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_apply_ready
        if r.get("apply_ready_status") in ("pending", "archived")
    }
    # unlock_candidate済みキーセット（APセクションのUNLOCK列用）
    unlock_candidate_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_unlock_candidate
        if r.get("unlock_candidate_status") in ("pending", "archived")
    }
    # unlock_judge済みキーセット（AQセクションのJUDGED列用）
    unlock_judge_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_reinject_unlock_judge
        if r.get("judge_status") in ("pending", "archived")
    }
    # unlock_execute済みキーセット（ARセクションのUNLOCK_EXEC列用）
    unlock_exec_dup_keys = {
        r.get("duplicate_key", "")
        for r in ceo_unlock_execute_queue
        if r.get("unlock_status") in ("pending", "unlocked", "archived")
    }
    # apply_execute 結果（AUセクション用）
    apply_exec_applied = [r for r in ceo_apply_execute_result if r.get("result_status") == "applied"]
    apply_exec_failed  = [r for r in ceo_apply_execute_result if r.get("result_status") == "failed"]
    stub_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_stub_queue
        if r.get("stub_status") in ("pending", "archived") and r.get("duplicate_key")
    )
    dry_run_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_dry_run_queue
        if r.get("dry_run_status") in ("pending", "archived") and r.get("duplicate_key")
    )
    candidate_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_candidate_queue
        if r.get("candidate_status") in ("pending", "archived") and r.get("duplicate_key")
    )
    # LIMITED_EXECUTION / GUARD 昇格済みキーセット
    limited_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_limited_exec_queue
        if r.get("limited_status") in ("pending", "archived") and r.get("duplicate_key")
    )
    guard_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_guard_result_queue
        if r.get("guard_status") in ("allowed", "blocked", "pending") and r.get("duplicate_key")
    )
    # PATCH_PLAN / APPLY / RESULT 昇格済みキーセット
    patch_plan_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_patch_plan_queue
        if r.get("plan_status") in ("pending", "applied", "archived") and r.get("duplicate_key")
    )
    apply_queue_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_config_apply_queue
        if r.get("apply_status") in ("pending", "applied", "archived") and r.get("duplicate_key")
    )
    result_promoted_keys = set(
        r.get("duplicate_key", "")
        for r in ceo_config_apply_result
        if r.get("result_status") in ("applied", "blocked", "failed") and r.get("duplicate_key")
    )

    er_recent   = list(reversed(ceo_exec_ready_queue))[:20]
    er_pending  = [r for r in ceo_exec_ready_queue if r.get("status") == "pending"]
    er_high     = sum(1 for r in er_pending if r.get("priority") == "HIGH")
    er_medium   = sum(1 for r in er_pending if r.get("priority") == "MEDIUM")
    er_dup_hist = sum(1 for h in ceo_exec_ready_history if h.get("status") == "exec_ready_duplicate")
    er_latest   = er_recent[0] if er_recent else {}

    er_rows = ""
    for er in er_recent:
        status   = er.get("status", "pending")
        prio     = er.get("priority", "LOW")
        pc_er    = PRIO_COLOR.get(prio, "#64748b")
        itype    = er.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = er.get("target_agent", "") or "—"
        proposed = er.get("proposed_change", "")
        sc_cls   = er.get("safety_class", "SAFE")
        promoted_at = er.get("promoted_at", "")[:16].replace("T", " ")
        row_op_er = "opacity:1" if status == "pending" else "opacity:0.5"
        er_dup_key = er.get("duplicate_key", "")
        er_simulated = er_dup_key in sim_promoted_keys
        er_sim_badge = (
            '<span style="color:#a78bfa;font-size:0.72rem;font-weight:800">🧪 SIMULATED</span>'
            if er_simulated else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        er_rows += f"""<tr style="{row_op_er}">
          <td style="font-size:0.68rem;color:#475569;white-space:nowrap">{promoted_at}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td><span style="background:{pc_er};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{prio}</span></td>
          <td style="text-align:center"><span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{sc_cls}</span></td>
          <td style="text-align:center;color:#22c55e;font-weight:800;font-size:0.8rem">✅</td>
          <td style="font-size:0.75rem;color:#e2e8f0;max-width:200px">{proposed[:70]}{'…' if len(proposed)>70 else ''}</td>
          <td style="text-align:center"><span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700">{status}</span></td>
          <td style="text-align:center">{er_sim_badge}</td>
        </tr>"""
    if not er_rows:
        er_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">実行候補なし（READYキューからSAFE候補が昇格されると表示されます）</td></tr>'

    er_lc = PRIO_COLOR.get(er_latest.get("priority","—"), "#64748b")
    er_latest_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #f59e0b;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:{er_lc};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{er_latest.get('priority','—')}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{IMP_TYPE_LABEL.get(er_latest.get('improvement_type',''), er_latest.get('improvement_type','—'))}</span>
    <span style="font-size:0.82rem;font-weight:700;color:#818cf8">{er_latest.get('target_agent','') or '—'}</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 10px;border-radius:4px;font-size:0.72rem;font-weight:800">SAFE</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#f59e0b;font-weight:700">🧠 ミュウツーCEO判断済み</span>
  </div>
  <div style="font-size:0.8rem;color:#e2e8f0;line-height:1.7">
    <span style="color:#475569;font-weight:700">🔨 改善案: </span>{(er_latest.get('proposed_change','') or '—')[:150]}
  </div>
</div>""" if er_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">実行候補なし</div>'

    ceo_exec_ready_section_html = f"""<div class="section" id="ceo-exec-ready">
  <div class="section-title">
    <span class="section-title-icon">🧠</span>
    R. 実行候補レーン — ミュウツーCEO判断済み
    <span style="margin-left:auto;font-size:0.72rem;color:#f59e0b">pending {len(er_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(er_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {er_high}</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {er_medium}</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">重複抑止 {er_dup_hist}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_exec_ready_queue)}件</span>
  </div>
  {er_latest_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:860px">
      <thead><tr>
        <th>昇格日時</th><th>対象AI</th><th>改善タイプ</th><th>優先度</th><th>安全クラス</th><th>実行推奨</th><th>改善案</th><th>状態</th><th>シミュ</th>
      </tr></thead>
      <tbody>{er_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧠 ミュウツーCEOが自律判断でREADYキューから選別した実行候補。今回は実行しない。次フェーズで実行エンジンへ接続予定。
  </div>
</div>"""

    # ─── セクションS: 実行シミュレーション ───
    RISK_COLOR = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}
    SIM_TYPE_LABEL = {
        "prompt_change_simulation":  "プロンプト変更シミュ",
        "timeout_change_simulation": "タイムアウト変更シミュ",
        "monitor_only_simulation":   "監視継続シミュ",
        "generic_simulation":        "汎用シミュ",
    }

    sim_recent   = list(reversed(ceo_sim_queue))[:20]
    sim_pending  = [r for r in ceo_sim_queue if r.get("status") == "pending"]
    sim_high_r   = sum(1 for r in sim_pending if r.get("risk_level") == "high")
    sim_med_r    = sum(1 for r in sim_pending if r.get("risk_level") == "medium")
    sim_low_r    = sum(1 for r in sim_pending if r.get("risk_level") == "low")
    sim_latest   = sim_recent[0] if sim_recent else {}

    sim_rows = ""
    for sr in sim_recent:
        status   = sr.get("status", "pending")
        prio     = sr.get("priority", "LOW")
        pc_s     = PRIO_COLOR.get(prio, "#64748b")
        itype    = sr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = sr.get("target_agent", "") or "(全体)"
        sim_type = sr.get("simulation_type", "")
        stl      = SIM_TYPE_LABEL.get(sim_type, sim_type or "—")
        risk     = sr.get("risk_level", "high")
        rc       = RISK_COLOR.get(risk, "#64748b")
        effect   = sr.get("predicted_effect", "")
        tfiles   = sr.get("target_files", [])
        tlogs    = sr.get("target_logs", [])
        wscope   = sr.get("write_scope", "none")
        simulated_at = sr.get("simulated_at", "")[:16].replace("T", " ")
        row_op_s = "opacity:1" if status == "pending" else "opacity:0.5"
        tf_html = "<br>".join(f'<code style="font-size:0.65rem;color:#60a5fa">{f}</code>' for f in tfiles) if tfiles else '<span style="color:#374151;font-size:0.68rem">—</span>'
        tl_html = "<br>".join(f'<code style="font-size:0.65rem;color:#94a3b8">{l}</code>' for l in tlogs) if tlogs else '<span style="color:#374151;font-size:0.68rem">—</span>'
        sr_dup_key = sr.get("duplicate_key", "")
        sr_ranked  = sr_dup_key in ranked_promoted_keys
        sr_rank_badge = (
            '<span style="color:#fbbf24;font-size:0.72rem;font-weight:800">🏁 RANKED</span>'
            if sr_ranked else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        sim_rows += f"""<tr class="sim-row" data-risk="{risk}" data-status="{status}" style="{row_op_s}">
          <td style="font-size:0.68rem;color:#475569;white-space:nowrap">{simulated_at}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="font-size:0.72rem;color:#e2e8f0;white-space:nowrap">{stl}</td>
          <td style="text-align:center"><span style="background:{rc}22;border:1px solid {rc}55;color:{rc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{risk}</span></td>
          <td style="font-size:0.72rem;line-height:1.5">{tf_html}</td>
          <td style="font-size:0.72rem;line-height:1.5">{tl_html}</td>
          <td style="font-size:0.72rem;color:#94a3b8;max-width:160px">{effect}</td>
          <td style="text-align:center"><span style="background:#37415122;border:1px solid #37415155;color:#64748b;padding:2px 6px;border-radius:4px;font-size:0.65rem">{wscope}</span></td>
          <td style="text-align:center"><span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{status}</span></td>
          <td style="text-align:center">{sr_rank_badge}</td>
        </tr>"""
    if not sim_rows:
        sim_rows = '<tr><td colspan="11" style="color:#64748b;text-align:center;padding:16px">シミュレーションなし（execution_ready_queueから自動登録されます）</td></tr>'

    sl_prio  = sim_latest.get("priority","—")
    sl_color = PRIO_COLOR.get(sl_prio, "#64748b")
    sl_risk  = sim_latest.get("risk_level","—")
    sl_rc    = RISK_COLOR.get(sl_risk, "#64748b")
    sl_agent = sim_latest.get("target_agent","") or "(全体)"
    sl_stype = SIM_TYPE_LABEL.get(sim_latest.get("simulation_type",""), sim_latest.get("simulation_type","—"))
    sl_effect= sim_latest.get("predicted_effect","") or "—"
    sl_prop  = sim_latest.get("proposed_change","") or "—"
    sim_latest_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #a78bfa;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:{sl_color};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{sl_prio}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{sl_stype}</span>
    <span style="font-size:0.82rem;font-weight:700;color:#818cf8">{sl_agent}</span>
    <span style="background:{sl_rc}22;border:1px solid {sl_rc}55;color:{sl_rc};padding:2px 10px;border-radius:4px;font-size:0.72rem;font-weight:800">risk: {sl_risk}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#a78bfa;font-weight:700">🧪 シミュレーション</span>
  </div>
  <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:0.8rem;line-height:1.7">
    <span style="color:#475569;font-weight:700">🎯 予測効果</span><span style="color:#94a3b8">{sl_effect}</span>
    <span style="color:#475569;font-weight:700">🔨 改善案</span><span style="color:#e2e8f0">{sl_prop[:120]}{'…' if len(sl_prop)>120 else ''}</span>
  </div>
</div>""" if sim_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">シミュレーションなし</div>'

    # ─── セクションT: 実行優先順位 ───
    PRIO_SCORE_COLOR = lambda s: "#22c55e" if s >= 0.75 else ("#f59e0b" if s >= 0.60 else "#ef4444")
    ORDER_COLOR      = lambda o: "#fbbf24" if o == 1 else ("#f59e0b" if o == 2 else "#94a3b8")

    rk_recent   = list(reversed(ceo_ranked_queue))[:20]
    rk_pending  = [r for r in ceo_ranked_queue if r.get("status") == "pending"]
    rk_held     = [r for r in ceo_ranked_queue if r.get("status") == "held"]
    rk_high_p   = sum(1 for r in ceo_ranked_queue if r.get("priority") == "HIGH")
    rk_med_p    = sum(1 for r in ceo_ranked_queue if r.get("priority") == "MEDIUM")
    rk_low_p    = sum(1 for r in ceo_ranked_queue if r.get("priority") == "LOW")
    # 1位候補
    rk_top1     = next((r for r in sorted(rk_pending, key=lambda x: x.get("execution_order", 999)) if r.get("execution_order", 0) > 0), {})
    rk_latest   = rk_recent[0] if rk_recent else {}

    rk_rows = ""
    for rr in rk_recent:
        status   = rr.get("status", "pending")
        prio     = rr.get("priority", "LOW")
        pc_r     = PRIO_COLOR.get(prio, "#64748b")
        itype    = rr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = rr.get("target_agent", "") or "(全体)"
        imp_s    = rr.get("impact_score", 0.0)
        risk_s   = rr.get("risk_score", 0.0)
        p_s      = rr.get("priority_score", 0.0)
        scope    = rr.get("estimated_scope", "—")
        exec_rec = rr.get("execute_recommended", True)
        hold_r   = rr.get("hold_reason", "")
        exe_ord  = rr.get("execution_order", 0)
        sc_r     = "#818cf8" if status == "pending" else "#374151"
        ps_col   = PRIO_SCORE_COLOR(p_s)
        ord_col  = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">held</span>'
        row_op_r = "opacity:1" if status == "pending" else "opacity:0.55"
        rk_dup_key   = rr.get("duplicate_key", "")
        rk_packeted  = rk_dup_key in packet_promoted_keys
        rk_pkt_badge = (
            '<span style="color:#34d399;font-size:0.72rem;font-weight:800">📦 PACKET</span>'
            if rk_packeted else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        rk_rows += f"""<tr class="rk-row" data-status="{status}" data-prio="{prio}" style="{row_op_r}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right;font-size:0.8rem;font-weight:700;color:#60a5fa">{imp_s:.3f}</td>
          <td style="text-align:right;font-size:0.8rem;color:#f87171">{risk_s:.3f}</td>
          <td style="text-align:right"><span style="color:{ps_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="text-align:center;font-size:0.72rem;color:#94a3b8">{scope}</td>
          <td style="text-align:center;font-size:0.8rem">{'✅' if exec_rec else '—'}</td>
          <td style="font-size:0.68rem;color:#f59e0b;max-width:120px">{hold_r or '—'}</td>
          <td style="text-align:center"><span style="background:{sc_r}22;border:1px solid {sc_r}55;color:{sc_r};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{status}</span></td>
          <td style="text-align:center">{rk_pkt_badge}</td>
        </tr>"""
    if not rk_rows:
        rk_rows = '<tr><td colspan="11" style="color:#64748b;text-align:center;padding:16px">優先順位なし（simulationキューから自動登録されます）</td></tr>'

    rk_top1_agent = rk_top1.get("target_agent","") or "(全体)"
    rk_top1_score = rk_top1.get("priority_score", 0.0)
    rk_top1_type  = IMP_TYPE_LABEL.get(rk_top1.get("improvement_type",""), rk_top1.get("improvement_type","—"))
    rk_top1_pc    = PRIO_SCORE_COLOR(rk_top1_score)
    rk_latest_p   = rk_latest.get("priority","—")
    rk_latest_lc  = PRIO_COLOR.get(rk_latest_p, "#64748b")
    rk_latest_agent = rk_latest.get("target_agent","") or "(全体)"
    rk_latest_ps  = rk_latest.get("priority_score", 0.0)
    rk_latest_ord = rk_latest.get("execution_order", 0)
    rk_latest_sc  = PRIO_SCORE_COLOR(rk_latest_ps)

    rk_latest_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #fbbf24;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:#fbbf2422;border:1px solid #fbbf2455;color:#fbbf24;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🏁 1位: {rk_top1_agent}</span>
    <span style="font-size:0.82rem;font-weight:800;color:#f1f5f9">{rk_top1_type}</span>
    <span style="background:{rk_top1_pc}22;border:1px solid {rk_top1_pc}55;color:{rk_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {rk_top1_score:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#fbbf24;font-weight:700">🧠 ミュウツーCEO判断</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新登録: <span style="color:#818cf8;font-weight:700">{rk_latest_agent}</span>
    / score <span style="color:{rk_latest_sc};font-weight:700">{rk_latest_ps:.3f}</span>
    / order <span style="color:#94a3b8">{rk_latest_ord if rk_latest_ord > 0 else 'held'}</span>
  </div>
</div>""" if rk_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">送信候補なし（simulationキューから自動登録されます）</div>'

    ceo_ranked_section_html = f"""<div class="section" id="ceo-ranked">
  <div class="section-title">
    <span class="section-title-icon">🏁</span>
    T. 実行優先順位 — ミュウツーCEO送信候補
    <span style="margin-left:auto;font-size:0.72rem;color:#fbbf24">pending {len(rk_pending)}件 / held {len(rk_held)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(rk_pending)}件</span>
    <span style="background:#37415122;border:1px solid #37415155;color:#94a3b8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⏸ held {len(rk_held)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {rk_high_p}</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {rk_med_p}</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {rk_low_p}</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_ranked_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterRK('all')" id="rk-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rk-filter-btn">全件</button>
    <button onclick="filterRK('pending')" id="rk-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rk-filter-btn">pending</button>
    <button onclick="filterRK('held')" id="rk-btn-held" style="background:#37415122;color:#94a3b8;border:1px solid #37415155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rk-filter-btn">held</button>
    <button onclick="filterRK('HIGH')" id="rk-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rk-filter-btn">HIGH</button>
    <button onclick="filterRK('MEDIUM')" id="rk-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rk-filter-btn">MEDIUM</button>
    <button onclick="filterRK('LOW')" id="rk-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rk-filter-btn">LOW</button>
  </div>
  {rk_latest_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:920px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">impact</th><th style="text-align:right">risk</th><th style="text-align:right">priority_score</th><th>scope</th><th>実行推奨</th><th>hold_reason</th><th>状態</th><th>📦 PACKET</th>
      </tr></thead>
      <tbody id="rk-tbody">{rk_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🏁 priority_score = (impact×0.65) + ((1-risk)×0.35)。pending=送信候補 / held=スコア不足保留。実行はしない。
  </div>
</div>
<script>
function filterRK(mode) {{
  document.querySelectorAll('.rk-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('rk-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.rk-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var prio   = row.getAttribute('data-prio') || '';
    var show = false;
    if (mode === 'all')     show = true;
    else if (mode === 'pending' || mode === 'held') show = status === mode;
    else show = prio === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションU: CEO送信パケット ───
    pkt_pending  = [r for r in ceo_packet_queue if r.get("packet_status") == "pending"]
    pkt_high     = sum(1 for r in pkt_pending if r.get("priority") == "HIGH")
    pkt_medium   = sum(1 for r in pkt_pending if r.get("priority") == "MEDIUM")
    pkt_low      = sum(1 for r in pkt_pending if r.get("priority") == "LOW")
    pkt_top1     = next((r for r in sorted(pkt_pending, key=lambda x: x.get("execution_order", 999))
                         if r.get("execution_order", 0) > 0), {})
    pkt_latest   = ceo_packet_queue[-1] if ceo_packet_queue else {}

    pkt_top1_agent  = pkt_top1.get("target_agent", "") or "(全体)"
    pkt_top1_score  = pkt_top1.get("priority_score", 0.0)
    pkt_top1_type   = IMP_TYPE_LABEL.get(pkt_top1.get("improvement_type", ""), pkt_top1.get("improvement_type", "—"))
    pkt_top1_pc     = PRIO_SCORE_COLOR(pkt_top1_score)

    pkt_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #34d399;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#34d39922;border:1px solid #34d39955;color:#34d399;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">📦 1位: {pkt_top1_agent}</span>
    <span style="font-size:0.82rem;font-weight:800;color:#f1f5f9">{pkt_top1_type}</span>
    <span style="background:{pkt_top1_pc}22;border:1px solid {pkt_top1_pc}55;color:{pkt_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {pkt_top1_score:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#34d399;font-weight:700">🧠 ミュウツーCEO実行前パケット化</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{pkt_latest.get('target_agent','') or '(全体)'}</span>
    / score <span style="color:{PRIO_SCORE_COLOR(pkt_latest.get('priority_score',0.0))};font-weight:700">{pkt_latest.get('priority_score',0.0):.3f}</span>
    / order <span style="color:#94a3b8">{pkt_latest.get('execution_order',0) if pkt_latest.get('execution_order',0)>0 else '—'}</span>
    / <span style="color:#34d399">{pkt_latest.get('packet_status','—')}</span>
  </div>
</div>""" if pkt_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">パケットなし（ranked queueから自動登録されます）</div>'

    pkt_rows = ""
    for pr in list(reversed(ceo_packet_queue))[:20]:
        ps       = pr.get("packet_status", "pending")
        ps_col   = "#34d399" if ps == "pending" else "#374151"
        prio     = pr.get("priority", "LOW")
        pc_p     = PRIO_COLOR.get(prio, "#64748b")
        itype    = pr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = pr.get("target_agent", "") or "(全体)"
        p_s      = pr.get("priority_score", 0.0)
        risk_l   = pr.get("risk_level", "low")
        scope    = pr.get("estimated_scope", "—")
        exe_ord  = pr.get("execution_order", 0)
        p_s_col  = PRIO_SCORE_COLOR(p_s)
        ord_col  = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op_p = "opacity:1" if ps == "pending" else "opacity:0.55"
        rc_p     = RISK_COLOR.get(risk_l, "#64748b")
        pkt_dup_key     = pr.get("duplicate_key", "")
        pkt_dispatched  = pkt_dup_key in dispatch_promoted_keys
        pkt_disp_badge  = (
            '<span style="color:#a78bfa;font-size:0.72rem;font-weight:800">📨 DISPATCH</span>'
            if pkt_dispatched else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        pkt_rows += f"""<tr class="pkt-row" data-status="{ps}" data-prio="{prio}" style="{row_op_p}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{p_s_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="text-align:center"><span style="background:{rc_p}22;border:1px solid {rc_p}55;color:{rc_p};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{risk_l}</span></td>
          <td style="text-align:center;font-size:0.72rem;color:#94a3b8">{scope}</td>
          <td style="text-align:center"><span style="background:{ps_col}22;border:1px solid {ps_col}55;color:{ps_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ps}</span></td>
          <td style="text-align:center">{pkt_disp_badge}</td>
        </tr>"""
    if not pkt_rows:
        pkt_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">パケットなし（ranked queueから自動登録されます）</td></tr>'

    ceo_packet_section_html = f"""<div class="section" id="ceo-packet">
  <div class="section-title">
    <span class="section-title-icon">📦</span>
    U. CEO送信パケット — 実行エンジン受け渡し前
    <span style="margin-left:auto;font-size:0.72rem;color:#34d399">pending {len(pkt_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#34d39922;border:1px solid #34d39955;color:#34d399;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">📦 pending {len(pkt_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {pkt_high}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {pkt_medium}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {pkt_low}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_packet_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterPkt('all')" id="pkt-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="pkt-filter-btn">全件</button>
    <button onclick="filterPkt('pending')" id="pkt-btn-pending" style="background:#34d39922;color:#34d399;border:1px solid #34d39955;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="pkt-filter-btn">pending</button>
    <button onclick="filterPkt('HIGH')" id="pkt-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="pkt-filter-btn">HIGH</button>
    <button onclick="filterPkt('MEDIUM')" id="pkt-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="pkt-filter-btn">MEDIUM</button>
    <button onclick="filterPkt('LOW')" id="pkt-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="pkt-filter-btn">LOW</button>
  </div>
  {pkt_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">priority_score</th><th>risk</th><th>scope</th><th>状態</th><th>📨 DISPATCH</th>
      </tr></thead>
      <tbody id="pkt-tbody">{pkt_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📦 ranked queueのpending+ceo_send_recommended=true+execution_order>0を自動パケット化。実行はしない。
  </div>
</div>
<script>
function filterPkt(mode) {{
  document.querySelectorAll('.pkt-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('pkt-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.pkt-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var prio   = row.getAttribute('data-prio') || '';
    var show = false;
    if (mode === 'all')    show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = prio === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションV: 実行要求パケット（dispatch_request） ───
    dsp_pending  = [r for r in ceo_dispatch_queue if r.get("dispatch_status") == "pending"]
    dsp_high     = sum(1 for r in dsp_pending if r.get("priority") == "HIGH")
    dsp_medium   = sum(1 for r in dsp_pending if r.get("priority") == "MEDIUM")
    dsp_low      = sum(1 for r in dsp_pending if r.get("priority") == "LOW")
    dsp_top1     = next((r for r in sorted(dsp_pending, key=lambda x: x.get("execution_order", 999))
                         if r.get("execution_order", 0) > 0), {})
    dsp_latest   = ceo_dispatch_queue[-1] if ceo_dispatch_queue else {}

    dsp_top1_agent = dsp_top1.get("target_agent", "") or "(全体)"
    dsp_top1_score = dsp_top1.get("priority_score", 0.0)
    dsp_top1_type  = IMP_TYPE_LABEL.get(dsp_top1.get("improvement_type", ""), dsp_top1.get("improvement_type", "—"))
    dsp_top1_pc    = PRIO_SCORE_COLOR(dsp_top1_score)

    dsp_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #a78bfa;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#a78bfa22;border:1px solid #a78bfa55;color:#a78bfa;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">📨 1位: {dsp_top1_agent}</span>
    <span style="font-size:0.82rem;font-weight:800;color:#f1f5f9">{dsp_top1_type}</span>
    <span style="background:{dsp_top1_pc}22;border:1px solid {dsp_top1_pc}55;color:{dsp_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {dsp_top1_score:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#a78bfa;font-weight:700">🧠 ミュウツーCEO実行要求パケット</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{dsp_latest.get('target_agent','') or '(全体)'}</span>
    / score <span style="color:{PRIO_SCORE_COLOR(dsp_latest.get('priority_score',0.0))};font-weight:700">{dsp_latest.get('priority_score',0.0):.3f}</span>
    / order <span style="color:#94a3b8">{dsp_latest.get('execution_order',0) if dsp_latest.get('execution_order',0)>0 else '—'}</span>
    / <span style="color:#a78bfa">{dsp_latest.get('dispatch_status','—')}</span>
    / execution_blocked=<span style="color:#ef4444;font-weight:700">{str(dsp_latest.get('execution_blocked',True)).lower()}</span>
  </div>
</div>""" if dsp_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">dispatch要求なし（packet queueから自動登録されます）</div>'

    dsp_rows = ""
    for dr in list(reversed(ceo_dispatch_queue))[:20]:
        ds       = dr.get("dispatch_status", "pending")
        ds_col   = "#a78bfa" if ds == "pending" else "#374151"
        prio     = dr.get("priority", "LOW")
        pc_d     = PRIO_COLOR.get(prio, "#64748b")
        itype    = dr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = dr.get("target_agent", "") or "(全体)"
        p_s      = dr.get("priority_score", 0.0)
        risk_l   = dr.get("risk_level", "low")
        scope    = dr.get("estimated_scope", "—")
        exe_ord  = dr.get("execution_order", 0)
        d_ready  = dr.get("dispatch_ready", True)
        ex_blk   = dr.get("execution_blocked", True)
        p_s_col  = PRIO_SCORE_COLOR(p_s)
        ord_col  = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op_d = "opacity:1" if ds == "pending" else "opacity:0.55"
        rc_d     = RISK_COLOR.get(risk_l, "#64748b")
        dsp_dup_key   = dr.get("duplicate_key", "")
        dsp_stubbed   = dsp_dup_key in stub_promoted_keys
        dsp_stub_badge = (
            '<span style="color:#fb923c;font-size:0.72rem;font-weight:800">🧩 STUB</span>'
            if dsp_stubbed else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        dsp_rows += f"""<tr class="dsp-row" data-status="{ds}" data-prio="{prio}" style="{row_op_d}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{p_s_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="text-align:center"><span style="background:{rc_d}22;border:1px solid {rc_d}55;color:{rc_d};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{risk_l}</span></td>
          <td style="text-align:center;font-size:0.72rem;color:#94a3b8">{scope}</td>
          <td style="text-align:center"><span style="color:{'#22c55e' if d_ready else '#ef4444'};font-size:0.75rem;font-weight:800">{'✅' if d_ready else '—'}</span></td>
          <td style="text-align:center"><span style="color:#ef4444;font-size:0.72rem;font-weight:800">{'🔒 true' if ex_blk else '—'}</span></td>
          <td style="text-align:center"><span style="background:{ds_col}22;border:1px solid {ds_col}55;color:{ds_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ds}</span></td>
          <td style="text-align:center">{dsp_stub_badge}</td>
        </tr>"""
    if not dsp_rows:
        dsp_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">dispatch要求なし（packet queueから自動登録されます）</td></tr>'

    ceo_dispatch_section_html = f"""<div class="section" id="ceo-dispatch">
  <div class="section-title">
    <span class="section-title-icon">📨</span>
    V. 実行要求パケット — 実行エンジン送信前
    <span style="margin-left:auto;font-size:0.72rem;color:#a78bfa">pending {len(dsp_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#a78bfa22;border:1px solid #a78bfa55;color:#a78bfa;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">📨 pending {len(dsp_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {dsp_high}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {dsp_medium}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {dsp_low}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_dispatch_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterDsp('all')" id="dsp-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dsp-filter-btn">全件</button>
    <button onclick="filterDsp('pending')" id="dsp-btn-pending" style="background:#a78bfa22;color:#a78bfa;border:1px solid #a78bfa55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dsp-filter-btn">pending</button>
    <button onclick="filterDsp('HIGH')" id="dsp-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dsp-filter-btn">HIGH</button>
    <button onclick="filterDsp('MEDIUM')" id="dsp-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dsp-filter-btn">MEDIUM</button>
    <button onclick="filterDsp('LOW')" id="dsp-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dsp-filter-btn">LOW</button>
  </div>
  {dsp_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:820px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">priority_score</th><th>risk</th><th>scope</th><th>dispatch_ready</th><th>execution_blocked</th><th>状態</th><th>🧩 STUB</th>
      </tr></thead>
      <tbody id="dsp-tbody">{dsp_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📨 packet queueのpending+execution_order>0を実行要求パケットに整形。dispatch_ready=true / execution_blocked=true 固定。実行はしない。
  </div>
</div>
<script>
function filterDsp(mode) {{
  document.querySelectorAll('.dsp-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('dsp-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.dsp-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var prio   = row.getAttribute('data-prio') || '';
    var show = false;
    if (mode === 'all')    show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = prio === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションW: CEO実行スタブ ───
    stb_pending = [r for r in ceo_stub_queue if r.get("stub_status") == "pending"]
    stb_high    = sum(1 for r in stb_pending if r.get("priority") == "HIGH")
    stb_medium  = sum(1 for r in stb_pending if r.get("priority") == "MEDIUM")
    stb_low     = sum(1 for r in stb_pending if r.get("priority") == "LOW")
    stb_top1    = next((r for r in sorted(stb_pending, key=lambda x: x.get("execution_order", 999))
                        if r.get("execution_order", 0) > 0), {})
    stb_latest  = ceo_stub_queue[-1] if ceo_stub_queue else {}

    stb_top1_agent = stb_top1.get("target_agent", "") or "(全体)"
    stb_top1_score = stb_top1.get("priority_score", 0.0)
    stb_top1_type  = IMP_TYPE_LABEL.get(stb_top1.get("improvement_type", ""), stb_top1.get("improvement_type", "—"))
    stb_top1_pc    = PRIO_SCORE_COLOR(stb_top1_score)

    stb_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #fb923c;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#fb923c22;border:1px solid #fb923c55;color:#fb923c;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🧩 1位: {stb_top1_agent}</span>
    <span style="font-size:0.82rem;font-weight:800;color:#f1f5f9">{stb_top1_type}</span>
    <span style="background:{stb_top1_pc}22;border:1px solid {stb_top1_pc}55;color:{stb_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {stb_top1_score:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#fb923c;font-weight:700">🧠 ミュウツーCEO実行前スタブ化</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{stb_latest.get('target_agent','') or '(全体)'}</span>
    / score <span style="color:{PRIO_SCORE_COLOR(stb_latest.get('priority_score',0.0))};font-weight:700">{stb_latest.get('priority_score',0.0):.3f}</span>
    / order <span style="color:#94a3b8">{stb_latest.get('execution_order',0) if stb_latest.get('execution_order',0)>0 else '—'}</span>
    / <span style="color:#fb923c">{stb_latest.get('stub_status','—')}</span>
  </div>
</div>""" if stb_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">スタブなし（dispatch queueから自動登録されます）</div>'

    stb_rows = ""
    for sr in list(reversed(ceo_stub_queue))[:20]:
        ss      = sr.get("stub_status", "pending")
        ss_col  = "#fb923c" if ss == "pending" else "#374151"
        prio    = sr.get("priority", "LOW")
        itype   = sr.get("improvement_type", "")
        itl     = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc     = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta      = sr.get("target_agent", "") or "(全体)"
        p_s     = sr.get("priority_score", 0.0)
        exe_ord = sr.get("execution_order", 0)
        t_logs  = sr.get("target_logs", [])
        t_files = sr.get("target_files", [])
        dry_only = sr.get("dry_run_only", True)
        p_s_col  = PRIO_SCORE_COLOR(p_s)
        ord_col  = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op   = "opacity:1" if ss == "pending" else "opacity:0.55"
        tl_html  = "<br>".join(f'<code style="font-size:0.62rem;color:#94a3b8">{l}</code>' for l in t_logs) if t_logs else '—'
        tf_html  = "<br>".join(f'<code style="font-size:0.62rem;color:#60a5fa">{f}</code>' for f in t_files) if t_files else '—'
        # DRYRUNバッジ
        stb_dup_key    = sr.get("duplicate_key", "")
        stb_dryrun     = stb_dup_key in dry_run_promoted_keys
        stb_dr_badge   = (
            '<span style="color:#38bdf8;font-size:0.72rem;font-weight:800">🧪 DRYRUN</span>'
            if stb_dryrun else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        stb_rows += f"""<tr class="stb-row" data-status="{ss}" data-prio="{prio}" style="{row_op}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{p_s_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="font-size:0.62rem;line-height:1.6">{tl_html}</td>
          <td style="font-size:0.62rem;line-height:1.6">{tf_html}</td>
          <td style="text-align:center;font-size:0.72rem;color:{'#22c55e' if dry_only else '#ef4444'}">{'✅' if dry_only else '—'}</td>
          <td style="text-align:center"><span style="background:{ss_col}22;border:1px solid {ss_col}55;color:{ss_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ss}</span></td>
          <td style="text-align:center">{stb_dr_badge}</td>
        </tr>"""
    if not stb_rows:
        stb_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">スタブなし（dispatch queueから自動登録されます）</td></tr>'

    ceo_stub_section_html = f"""<div class="section" id="ceo-stub">
  <div class="section-title">
    <span class="section-title-icon">🧩</span>
    W. CEO実行スタブ — 実行エンジン入力整形前
    <span style="margin-left:auto;font-size:0.72rem;color:#fb923c">pending {len(stb_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#fb923c22;border:1px solid #fb923c55;color:#fb923c;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🧩 pending {len(stb_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {stb_high}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {stb_medium}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {stb_low}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_stub_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterStb('all')" id="stb-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="stb-filter-btn">全件</button>
    <button onclick="filterStb('pending')" id="stb-btn-pending" style="background:#fb923c22;color:#fb923c;border:1px solid #fb923c55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="stb-filter-btn">pending</button>
    <button onclick="filterStb('HIGH')" id="stb-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="stb-filter-btn">HIGH</button>
    <button onclick="filterStb('MEDIUM')" id="stb-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="stb-filter-btn">MEDIUM</button>
    <button onclick="filterStb('LOW')" id="stb-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="stb-filter-btn">LOW</button>
  </div>
  {stb_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">priority_score</th><th>target_logs</th><th>target_files</th><th>dry_run_only</th><th>状態</th><th>🧪 DRYRUN</th>
      </tr></thead>
      <tbody id="stb-tbody">{stb_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧩 dispatch queueのpending+dispatch_ready=true+execution_order>0を実行エンジン入力形式に整形。dry_run_only=true / execution_blocked=true 固定。実行はしない。
  </div>
</div>
<script>
function filterStb(mode) {{
  document.querySelectorAll('.stb-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('stb-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.stb-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var prio   = row.getAttribute('data-prio') || '';
    var show = false;
    if (mode === 'all')    show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = prio === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションX: CEOドライラン結果 ───
    dr_pending  = [r for r in ceo_dry_run_queue if r.get("dry_run_status") == "pending"]
    dr_high_r   = sum(1 for r in dr_pending if r.get("predicted_risk") == "high")
    dr_med_r    = sum(1 for r in dr_pending if r.get("predicted_risk") == "medium")
    dr_low_r    = sum(1 for r in dr_pending if r.get("predicted_risk") == "low")
    dr_top1     = next((r for r in sorted(dr_pending, key=lambda x: x.get("execution_order", 999))
                        if r.get("execution_order", 0) > 0), {})
    dr_latest   = ceo_dry_run_queue[-1] if ceo_dry_run_queue else {}

    dr_top1_agent  = dr_top1.get("target_agent", "") or "(全体)"
    dr_top1_benefit = dr_top1.get("predicted_benefit_score", 0.0)
    dr_top1_type   = IMP_TYPE_LABEL.get(dr_top1.get("improvement_type", ""), dr_top1.get("improvement_type", "—"))
    dr_top1_pc     = PRIO_SCORE_COLOR(dr_top1_benefit)

    dr_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #38bdf8;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#38bdf822;border:1px solid #38bdf855;color:#38bdf8;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🧪 1位: {dr_top1_agent}</span>
    <span style="font-size:0.82rem;font-weight:800;color:#f1f5f9">{dr_top1_type}</span>
    <span style="background:{dr_top1_pc}22;border:1px solid {dr_top1_pc}55;color:{dr_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">benefit {dr_top1_benefit:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#38bdf8;font-weight:700">🧠 ミュウツーCEO実行前ドライラン</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{dr_latest.get('target_agent','') or '(全体)'}</span>
    / benefit <span style="color:{PRIO_SCORE_COLOR(dr_latest.get('predicted_benefit_score',0.0))};font-weight:700">{dr_latest.get('predicted_benefit_score',0.0):.3f}</span>
    / risk <span style="color:{RISK_COLOR.get(dr_latest.get('predicted_risk','high'),'#64748b')}">{dr_latest.get('predicted_risk','—')}</span>
    / <span style="color:#38bdf8">{dr_latest.get('dry_run_status','—')}</span>
  </div>
</div>""" if dr_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">ドライランなし（stub queueから自動登録されます）</div>'

    dr_rows = ""
    for dr in list(reversed(ceo_dry_run_queue))[:20]:
        ds_d     = dr.get("dry_run_status", "pending")
        ds_col_d = "#38bdf8" if ds_d == "pending" else "#374151"
        prio     = dr.get("priority", "LOW")
        itype    = dr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = dr.get("target_agent", "") or "(全体)"
        benefit  = dr.get("predicted_benefit_score", 0.0)
        p_risk   = dr.get("predicted_risk", "high")
        changes  = dr.get("predicted_changes", [])
        w_scope  = dr.get("write_scope", "none")
        exe_ord  = dr.get("execution_order", 0)
        b_col    = PRIO_SCORE_COLOR(benefit)
        rc_dr    = RISK_COLOR.get(p_risk, "#64748b")
        ord_col  = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op   = "opacity:1" if ds_d == "pending" else "opacity:0.55"
        ch_html  = "<br>".join(f'<span style="font-size:0.65rem;color:#e2e8f0">・{c}</span>' for c in changes) if changes else '—'
        # CANDIDATEバッジ
        dr_dup_key      = dr.get("duplicate_key", "")
        dr_candidated   = dr_dup_key in candidate_promoted_keys
        dr_cand_badge   = (
            '<span style="color:#4ade80;font-size:0.72rem;font-weight:800">🎯 CANDIDATE</span>'
            if dr_candidated else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        dr_rows += f"""<tr class="dr-row" data-status="{ds_d}" data-risk="{p_risk}" style="{row_op}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{b_col};font-weight:800;font-size:0.85rem">{benefit:.3f}</span></td>
          <td style="text-align:center"><span style="background:{rc_dr}22;border:1px solid {rc_dr}55;color:{rc_dr};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{p_risk}</span></td>
          <td style="font-size:0.65rem;line-height:1.7;max-width:180px">{ch_html}</td>
          <td style="text-align:center"><span style="background:#37415122;border:1px solid #37415155;color:#64748b;padding:2px 6px;border-radius:4px;font-size:0.65rem">{w_scope}</span></td>
          <td style="text-align:center"><span style="background:{ds_col_d}22;border:1px solid {ds_col_d}55;color:{ds_col_d};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ds_d}</span></td>
          <td style="text-align:center">{dr_cand_badge}</td>
        </tr>"""
    if not dr_rows:
        dr_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">ドライランなし（stub queueから自動登録されます）</td></tr>'

    ceo_dry_run_section_html = f"""<div class="section" id="ceo-dryrun">
  <div class="section-title">
    <span class="section-title-icon">🧪</span>
    X. CEOドライラン結果 — 実行影響予測
    <span style="margin-left:auto;font-size:0.72rem;color:#38bdf8">pending {len(dr_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#38bdf822;border:1px solid #38bdf855;color:#38bdf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🧪 pending {len(dr_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 high {dr_high_r}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 medium {dr_med_r}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 low {dr_low_r}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_dry_run_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterDr('all')" id="dr-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dr-filter-btn">全件</button>
    <button onclick="filterDr('pending')" id="dr-btn-pending" style="background:#38bdf822;color:#38bdf8;border:1px solid #38bdf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dr-filter-btn">pending</button>
    <button onclick="filterDr('high')" id="dr-btn-high" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dr-filter-btn">high</button>
    <button onclick="filterDr('medium')" id="dr-btn-medium" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dr-filter-btn">medium</button>
    <button onclick="filterDr('low')" id="dr-btn-low" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="dr-filter-btn">low</button>
  </div>
  {dr_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">benefit_score</th><th>predicted_risk</th><th>predicted_changes</th><th>write_scope</th><th>状態</th><th>🎯 CANDIDATE</th>
      </tr></thead>
      <tbody id="dr-tbody">{dr_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧪 stub queueの各レコードに対し「実行したらどうなるか」を完全決定論で予測。実ファイル変更なし。write_scope=none / execution_blocked=true 固定。
  </div>
</div>
<script>
function filterDr(mode) {{
  document.querySelectorAll('.dr-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('dr-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.dr-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var risk   = row.getAttribute('data-risk') || '';
    var show = false;
    if (mode === 'all')    show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = risk === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションY: CEO最終実行候補 ───
    cnd_pending = [r for r in ceo_candidate_queue if r.get("candidate_status") == "pending"]
    cnd_high    = sum(1 for r in cnd_pending if r.get("priority") == "HIGH")
    cnd_medium  = sum(1 for r in cnd_pending if r.get("priority") == "MEDIUM")
    cnd_low     = sum(1 for r in cnd_pending if r.get("priority") == "LOW")
    cnd_top1    = next((r for r in sorted(cnd_pending, key=lambda x: x.get("execution_order", 999))
                        if r.get("execution_order", 0) > 0), {})
    cnd_latest  = ceo_candidate_queue[-1] if ceo_candidate_queue else {}

    cnd_top1_agent  = cnd_top1.get("target_agent", "") or "(全体)"
    cnd_top1_score  = cnd_top1.get("priority_score", 0.0)
    cnd_top1_type   = IMP_TYPE_LABEL.get(cnd_top1.get("improvement_type", ""), cnd_top1.get("improvement_type", "—"))
    cnd_top1_benefit = cnd_top1.get("predicted_benefit_score", 0.0)
    cnd_top1_pc     = PRIO_SCORE_COLOR(cnd_top1_score)

    cnd_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #4ade80;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#4ade8022;border:1px solid #4ade8055;color:#4ade80;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🎯 1位: {cnd_top1_agent}</span>
    <span style="font-size:0.82rem;font-weight:800;color:#f1f5f9">{cnd_top1_type}</span>
    <span style="background:{cnd_top1_pc}22;border:1px solid {cnd_top1_pc}55;color:{cnd_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {cnd_top1_score:.3f}</span>
    <span style="background:#4ade8022;border:1px solid #4ade8055;color:#4ade80;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">benefit {cnd_top1_benefit:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#4ade80;font-weight:700">🧠 ミュウツーCEO最終実行候補 — 実行はしない</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{cnd_latest.get('target_agent','') or '(全体)'}</span>
    / score <span style="color:{PRIO_SCORE_COLOR(cnd_latest.get('priority_score',0.0))};font-weight:700">{cnd_latest.get('priority_score',0.0):.3f}</span>
    / <span style="color:#4ade80">{cnd_latest.get('candidate_status','—')}</span>
    / execution_blocked=<span style="color:#ef4444;font-weight:700">{str(cnd_latest.get('execution_blocked',True)).lower()}</span>
  </div>
</div>""" if cnd_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">最終候補なし（dry_run queueから自動登録されます）</div>'

    cnd_rows = ""
    for cr in list(reversed(ceo_candidate_queue))[:20]:
        cs      = cr.get("candidate_status", "pending")
        cs_col  = "#4ade80" if cs == "pending" else "#374151"
        prio    = cr.get("priority", "LOW")
        pc_c    = PRIO_COLOR.get(prio, "#64748b")
        itype   = cr.get("improvement_type", "")
        itl     = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc     = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta      = cr.get("target_agent", "") or "(全体)"
        p_s     = cr.get("priority_score", 0.0)
        benefit = cr.get("predicted_benefit_score", 0.0)
        p_risk  = cr.get("predicted_risk", "medium")
        c_ready = cr.get("candidate_ready", True)
        ex_blk  = cr.get("execution_blocked", True)
        exe_ord = cr.get("execution_order", 0)
        p_s_col = PRIO_SCORE_COLOR(p_s)
        b_col   = PRIO_SCORE_COLOR(benefit)
        rc_c    = RISK_COLOR.get(p_risk, "#64748b")
        ord_col = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op  = "opacity:1" if cs == "pending" else "opacity:0.55"
        cnd_lim_key = cr.get("duplicate_key", "")
        cnd_lim_badge = ('<span style="background:#fb923c22;border:1px solid #fb923c55;color:#fb923c;padding:2px 8px;border-radius:4px;font-size:0.65rem;font-weight:800">🚦 LIMITED</span>'
                         if cnd_lim_key in limited_promoted_keys else
                         '<span style="color:#374151;font-size:0.68rem">—</span>')
        cnd_rows += f"""<tr class="cnd-row" data-status="{cs}" data-prio="{prio}" style="{row_op}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{p_s_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="text-align:right"><span style="color:{b_col};font-weight:800;font-size:0.85rem">{benefit:.3f}</span></td>
          <td style="text-align:center"><span style="background:{rc_c}22;border:1px solid {rc_c}55;color:{rc_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{p_risk}</span></td>
          <td style="text-align:center"><span style="color:{'#22c55e' if c_ready else '#ef4444'};font-size:0.75rem;font-weight:800">{'✅' if c_ready else '—'}</span></td>
          <td style="text-align:center"><span style="color:#ef4444;font-size:0.72rem;font-weight:800">{'🔒 true' if ex_blk else '—'}</span></td>
          <td style="text-align:center">{cnd_lim_badge}</td>
          <td style="text-align:center"><span style="background:{cs_col}22;border:1px solid {cs_col}55;color:{cs_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{cs}</span></td>
        </tr>"""
    if not cnd_rows:
        cnd_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">最終候補なし（dry_run queueから自動登録されます）</td></tr>'

    ceo_candidate_section_html = f"""<div class="section" id="ceo-candidate">
  <div class="section-title">
    <span class="section-title-icon">🎯</span>
    Y. CEO最終実行候補 — まだ実行しない
    <span style="margin-left:auto;font-size:0.72rem;color:#4ade80">pending {len(cnd_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#4ade8022;border:1px solid #4ade8055;color:#4ade80;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🎯 pending {len(cnd_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {cnd_high}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {cnd_medium}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {cnd_low}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_candidate_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterCnd('all')" id="cnd-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="cnd-filter-btn">全件</button>
    <button onclick="filterCnd('pending')" id="cnd-btn-pending" style="background:#4ade8022;color:#4ade80;border:1px solid #4ade8055;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="cnd-filter-btn">pending</button>
    <button onclick="filterCnd('HIGH')" id="cnd-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="cnd-filter-btn">HIGH</button>
    <button onclick="filterCnd('MEDIUM')" id="cnd-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="cnd-filter-btn">MEDIUM</button>
    <button onclick="filterCnd('LOW')" id="cnd-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="cnd-filter-btn">LOW</button>
  </div>
  {cnd_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">priority_score</th><th style="text-align:right">benefit_score</th><th>predicted_risk</th><th>candidate_ready</th><th>execution_blocked</th><th style="text-align:center">🚦 LIMITED</th><th>状態</th>
      </tr></thead>
      <tbody id="cnd-tbody">{cnd_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🎯 dry_run結果のうち predicted_risk=low/medium かつ benefit_score≥0.60 のみ昇格。execution_blocked=true / write_scope=none 固定。実行はしない。これが最終候補。
  </div>
</div>
<script>
function filterCnd(mode) {{
  document.querySelectorAll('.cnd-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('cnd-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.cnd-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var prio   = row.getAttribute('data-prio') || '';
    var show = false;
    if (mode === 'all')    show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = prio === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションZ: CEO限定実行候補 — config_only ───
    lim_pending = [r for r in ceo_limited_exec_queue if r.get("limited_status") == "pending"]
    lim_high    = sum(1 for r in lim_pending if r.get("priority") == "HIGH")
    lim_medium  = sum(1 for r in lim_pending if r.get("priority") == "MEDIUM")
    lim_low     = sum(1 for r in lim_pending if r.get("priority") == "LOW")
    lim_top1    = next((r for r in sorted(lim_pending, key=lambda x: x.get("execution_order", 999))
                        if r.get("execution_order", 0) > 0), {})
    lim_latest  = ceo_limited_exec_queue[-1] if ceo_limited_exec_queue else {}

    lim_top1_agent  = lim_top1.get("target_agent", "") or "(全体)"
    lim_top1_score  = lim_top1.get("priority_score", 0.0)
    lim_top1_benefit = lim_top1.get("predicted_benefit_score", 0.0)
    lim_top1_pc     = PRIO_SCORE_COLOR(lim_top1_score)

    lim_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #fb923c;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#fb923c22;border:1px solid #fb923c55;color:#fb923c;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🚦 1位: {lim_top1_agent}</span>
    <span style="background:{lim_top1_pc}22;border:1px solid {lim_top1_pc}55;color:{lim_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {lim_top1_score:.3f}</span>
    <span style="background:#fb923c22;border:1px solid #fb923c55;color:#fb923c;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">benefit {lim_top1_benefit:.3f}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#fb923c;font-weight:700">🚦 ミュウツーCEO限定実行候補 — execution_allowed=false</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{lim_latest.get('target_agent','') or '(全体)'}</span>
    / score <span style="color:{PRIO_SCORE_COLOR(lim_latest.get('priority_score',0.0))};font-weight:700">{lim_latest.get('priority_score',0.0):.3f}</span>
    / execution_mode=<span style="color:#fb923c;font-weight:700">{lim_latest.get('execution_mode','—')}</span>
    / write_scope=<span style="color:#22c55e;font-weight:700">{lim_latest.get('write_scope','—')}</span>
  </div>
</div>""" if lim_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">限定実行候補なし（execution_candidate queueから自動登録されます）</div>'

    lim_rows = ""
    for lr in list(reversed(ceo_limited_exec_queue))[:20]:
        ls      = lr.get("limited_status", "pending")
        ls_col  = "#fb923c" if ls == "pending" else "#374151"
        prio    = lr.get("priority", "LOW")
        pc_c    = PRIO_COLOR.get(prio, "#64748b")
        itype   = lr.get("improvement_type", "")
        itl     = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc     = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta      = lr.get("target_agent", "") or "(全体)"
        p_s     = lr.get("priority_score", 0.0)
        benefit = lr.get("predicted_benefit_score", 0.0)
        tf_disp = ", ".join(lr.get("target_files", [])) or "—"
        em      = lr.get("execution_mode", "—")
        ws      = lr.get("write_scope", "—")
        p_s_col = PRIO_SCORE_COLOR(p_s)
        b_col   = PRIO_SCORE_COLOR(benefit)
        exe_ord = lr.get("execution_order", 0)
        ord_col = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op  = "opacity:1" if ls == "pending" else "opacity:0.55"
        lim_rows += f"""<tr class="lim-row" data-status="{ls}" data-prio="{prio}" style="{row_op}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{p_s_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="text-align:right"><span style="color:{b_col};font-weight:800;font-size:0.85rem">{benefit:.3f}</span></td>
          <td style="font-size:0.68rem;color:#94a3b8">{tf_disp}</td>
          <td style="font-size:0.68rem;color:#64748b">{em}</td>
          <td style="font-size:0.68rem;color:#22c55e;font-weight:700">{ws}</td>
          <td style="text-align:center"><span style="background:{ls_col}22;border:1px solid {ls_col}55;color:{ls_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ls}</span></td>
        </tr>"""
    if not lim_rows:
        lim_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">限定実行候補なし（execution_candidate queueから自動登録されます）</td></tr>'

    ceo_limited_section_html = f"""<div class="section" id="ceo-limited">
  <div class="section-title">
    <span class="section-title-icon">🚦</span>
    Z. CEO限定実行候補 — config_only
    <span style="margin-left:auto;font-size:0.72rem;color:#fb923c">pending {len(lim_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#fb923c22;border:1px solid #fb923c55;color:#fb923c;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚦 pending {len(lim_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 HIGH {lim_high}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {lim_medium}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {lim_low}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_limited_exec_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterLim('all')" id="lim-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="lim-filter-btn">全件</button>
    <button onclick="filterLim('pending')" id="lim-btn-pending" style="background:#fb923c22;color:#fb923c;border:1px solid #fb923c55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="lim-filter-btn">pending</button>
    <button onclick="filterLim('HIGH')" id="lim-btn-HIGH" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="lim-filter-btn">HIGH</button>
    <button onclick="filterLim('MEDIUM')" id="lim-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="lim-filter-btn">MEDIUM</button>
    <button onclick="filterLim('LOW')" id="lim-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="lim-filter-btn">LOW</button>
  </div>
  {lim_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:960px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">priority_score</th><th style="text-align:right">benefit_score</th><th>target_files</th><th>execution_mode</th><th>write_scope</th><th>状態</th>
      </tr></thead>
      <tbody id="lim-tbody">{lim_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🚦 prompt_fix かつ config/agent_directives.json のみ対象。execution_allowed=false / execution_blocked=true / write_scope=config_only 固定。実行はしない。
  </div>
</div>
<script>
function filterLim(mode) {{
  document.querySelectorAll('.lim-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('lim-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.lim-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var prio   = row.getAttribute('data-prio') || '';
    var show = false;
    if (mode === 'all')    show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = prio === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションAA: CEO実行ガード結果 — 最終許可判定 ───
    grd_allowed = [r for r in ceo_guard_result_queue if r.get("guard_status") == "allowed"]
    grd_blocked = [r for r in ceo_guard_result_queue if r.get("guard_status") == "blocked"]
    grd_top1    = next((r for r in sorted(grd_allowed, key=lambda x: x.get("execution_order", 999))
                        if r.get("execution_order", 0) > 0), {})
    grd_latest  = ceo_guard_result_queue[-1] if ceo_guard_result_queue else {}

    grd_top1_agent  = grd_top1.get("target_agent", "") or "(全体)"
    grd_top1_score  = grd_top1.get("priority_score", 0.0)
    grd_top1_pc     = PRIO_SCORE_COLOR(grd_top1_score)

    grd_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #a78bfa;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#a78bfa22;border:1px solid #a78bfa55;color:#a78bfa;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🛡 1位(allowed): {grd_top1_agent}</span>
    <span style="background:{grd_top1_pc}22;border:1px solid {grd_top1_pc}55;color:{grd_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {grd_top1_score:.3f}</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">candidate_for_real_execution=true</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#a78bfa;font-weight:700">🛡 ミュウツーCEO実行ガード判定 — 完全決定論</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{grd_latest.get('target_agent','') or '(全体)'}</span>
    / <span style="color:{'#22c55e' if grd_latest.get('guard_status')=='allowed' else '#ef4444'};font-weight:700">{grd_latest.get('guard_status','—')}</span>
    / <span style="color:#64748b">{grd_latest.get('guard_reason','—')}</span>
  </div>
</div>""" if grd_top1 or grd_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">ガード判定なし（limited_execution queueから自動判定されます）</div>'

    grd_rows = ""
    for gr in list(reversed(ceo_guard_result_queue))[:20]:
        gs      = gr.get("guard_status", "blocked")
        gs_col  = "#22c55e" if gs == "allowed" else "#ef4444"
        prio    = gr.get("priority", "LOW")
        itype   = gr.get("improvement_type", "")
        itl     = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc     = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta      = gr.get("target_agent", "") or "(全体)"
        p_s     = gr.get("priority_score", 0.0)
        p_risk  = gr.get("predicted_risk", "medium")
        rc_c    = RISK_COLOR.get(p_risk, "#64748b")
        p_s_col = PRIO_SCORE_COLOR(p_s)
        cfre    = gr.get("candidate_for_real_execution", False)
        cfre_disp = ('<span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">✅ true</span>'
                     if cfre else
                     '<span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">✗ false</span>')
        exe_ord = gr.get("execution_order", 0)
        ord_col = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        reason  = gr.get("guard_reason", "")
        row_op  = "opacity:1" if gs == "allowed" else "opacity:0.7"
        grd_dk  = gr.get("duplicate_key", "")
        grd_patch_badge = ('<span style="background:#6366f122;border:1px solid #6366f155;color:#6366f1;padding:2px 8px;border-radius:4px;font-size:0.65rem;font-weight:800">🧩 PATCH</span>'
                           if grd_dk in patch_plan_promoted_keys else
                           '<span style="color:#374151;font-size:0.68rem">—</span>')
        grd_rows += f"""<tr class="grd-row" data-status="{gs}" data-prio="{prio}" style="{row_op}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td style="text-align:right"><span style="color:{p_s_col};font-weight:800;font-size:0.85rem">{p_s:.3f}</span></td>
          <td style="text-align:center"><span style="background:{rc_c}22;border:1px solid {rc_c}55;color:{rc_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{p_risk}</span></td>
          <td style="text-align:center">{cfre_disp}</td>
          <td style="text-align:center"><span style="background:{gs_col}22;border:1px solid {gs_col}55;color:{gs_col};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{gs}</span></td>
          <td style="font-size:0.68rem;color:#94a3b8">{reason}</td>
          <td style="text-align:center">{grd_patch_badge}</td>
        </tr>"""
    if not grd_rows:
        grd_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">ガード判定なし（limited_execution queueから自動判定されます）</td></tr>'

    ceo_guard_section_html = f"""<div class="section" id="ceo-guard">
  <div class="section-title">
    <span class="section-title-icon">🛡</span>
    AA. CEO実行ガード結果 — 最終許可判定
    <span style="margin-left:auto;font-size:0.72rem;color:#a78bfa">allowed {len(grd_allowed)}件 / blocked {len(grd_blocked)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ allowed {len(grd_allowed)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(grd_blocked)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_guard_result_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterGrd('all')" id="grd-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="grd-filter-btn">全件</button>
    <button onclick="filterGrd('allowed')" id="grd-btn-allowed" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="grd-filter-btn">allowed</button>
    <button onclick="filterGrd('blocked')" id="grd-btn-blocked" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="grd-filter-btn">blocked</button>
  </div>
  {grd_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>改善タイプ</th><th style="text-align:right">priority_score</th><th>predicted_risk</th><th style="text-align:center">candidate_for_real_execution</th><th style="text-align:center">guard_status</th><th>guard_reason</th><th style="text-align:center">🧩 PATCH</th>
      </tr></thead>
      <tbody id="grd-tbody">{grd_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🛡 完全決定論。allowed のみ candidate_for_real_execution=true。実行はしない。ミュウツーCEOが次に本当に実行接続できる候補を確定。
  </div>
</div>
<script>
function filterGrd(mode) {{
  document.querySelectorAll('.grd-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('grd-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.grd-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var show = (mode === 'all') || (status === mode);
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションAB: CEO設定変更計画 — patch plan ───
    pp_pending = [r for r in ceo_patch_plan_queue if r.get("plan_status") == "pending"]
    pp_held    = [r for r in ceo_patch_plan_queue if r.get("plan_status") == "held"]
    pp_top1    = next((r for r in sorted(pp_pending, key=lambda x: x.get("execution_order", 999))
                       if r.get("execution_order", 0) > 0), {})
    pp_latest  = ceo_patch_plan_queue[-1] if ceo_patch_plan_queue else {}

    pp_top1_agent = pp_top1.get("target_agent", "") or "(全体)"
    pp_top1_score = pp_top1.get("priority_score", 0.0)
    pp_top1_path  = pp_top1.get("patch_path", "—")
    pp_top1_pc    = PRIO_SCORE_COLOR(pp_top1_score)

    pp_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #6366f1;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
    <span style="background:#6366f122;border:1px solid #6366f155;color:#6366f1;padding:3px 12px;border-radius:4px;font-size:0.88rem;font-weight:800">🧩 1位: {pp_top1_agent}</span>
    <span style="background:{pp_top1_pc}22;border:1px solid {pp_top1_pc}55;color:{pp_top1_pc};padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">score {pp_top1_score:.3f}</span>
    <span style="font-size:0.7rem;color:#94a3b8">{pp_top1_path}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#6366f1;font-weight:700">🧩 ミュウツーCEO設定変更計画 — まだ書き込まない</span>
  </div>
  <div style="font-size:0.75rem;color:#94a3b8">
    最新: <span style="color:#818cf8;font-weight:700">{pp_latest.get('target_agent','') or '(全体)'}</span>
    / <span style="color:#6366f1;font-weight:700">{pp_latest.get('plan_status','—')}</span>
    / target_config=<span style="color:#22c55e">{pp_latest.get('target_config','—')}</span>
  </div>
</div>""" if pp_top1 or pp_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">変更計画なし（execution_guard allowed から自動生成されます）</div>'

    pp_rows = ""
    for pr in list(reversed(ceo_patch_plan_queue))[:20]:
        ps      = pr.get("plan_status", "pending")
        ps_col  = "#6366f1" if ps == "pending" else ("#22c55e" if ps == "applied" else "#374151")
        ta      = pr.get("target_agent", "") or "(全体)"
        pp_path = pr.get("patch_path", "—")
        bv      = (pr.get("before_value", "") or "")[:60].replace("<", "&lt;")
        av      = (pr.get("after_value", "") or "")[:60].replace("<", "&lt;")
        dp      = (pr.get("diff_preview", "") or "").replace("<", "&lt;").replace("\n", " │ ")[:120]
        exe_ord = pr.get("execution_order", 0)
        ord_col = ORDER_COLOR(exe_ord) if exe_ord > 0 else "#374151"
        ord_disp = f'<span style="color:{ord_col};font-weight:800;font-size:0.9rem">{exe_ord}位</span>' if exe_ord > 0 else '<span style="color:#374151;font-size:0.72rem">—</span>'
        row_op  = "opacity:1" if ps == "pending" else "opacity:0.6"
        # APPLY バッジ
        pp_dk = pr.get("duplicate_key", "")
        pp_apply_badge = ('<span style="background:#0ea5e922;border:1px solid #0ea5e955;color:#0ea5e9;padding:2px 8px;border-radius:4px;font-size:0.65rem;font-weight:800">📝 APPLY</span>'
                          if pp_dk in apply_queue_promoted_keys else
                          '<span style="color:#374151;font-size:0.68rem">—</span>')
        pp_rows += f"""<tr class="pp-row" data-status="{ps}" style="{row_op}">
          <td style="text-align:center">{ord_disp}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="font-size:0.65rem;color:#a78bfa">{pp_path}</td>
          <td style="font-size:0.65rem;color:#94a3b8;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{bv or '—'}</td>
          <td style="font-size:0.65rem;color:#22c55e;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{av or '—'}</td>
          <td style="font-size:0.62rem;color:#64748b;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{dp or '—'}</td>
          <td style="text-align:center">{pp_apply_badge}</td>
          <td style="text-align:center"><span style="background:{ps_col}22;border:1px solid {ps_col}55;color:{ps_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ps}</span></td>
        </tr>"""
    if not pp_rows:
        pp_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">変更計画なし（execution_guard allowed から自動生成されます）</td></tr>'

    ceo_patch_plan_section_html = f"""<div class="section" id="ceo-patch-plan">
  <div class="section-title">
    <span class="section-title-icon">🧩</span>
    AB. CEO設定変更計画 — patch plan
    <span style="margin-left:auto;font-size:0.72rem;color:#6366f1">pending {len(pp_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#6366f122;border:1px solid #6366f155;color:#6366f1;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🧩 pending {len(pp_pending)}件</span>
    <span style="background:#37415122;border:1px solid #37415155;color:#94a3b8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">hold {len(pp_held)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_patch_plan_queue)}件</span>
  </div>
  {pp_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:1000px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>対象AI</th><th>patch_path</th><th>before</th><th>after</th><th>diff_preview</th><th style="text-align:center">📝 APPLY</th><th>状態</th>
      </tr></thead>
      <tbody id="pp-tbody">{pp_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧩 config/agent_directives.json への単一キー変更計画。まだ書き込まない。backup_required=true 固定。
  </div>
</div>"""

    # ─── セクションAC: CEO設定適用待ち — apply queue ───
    aq_pending = [r for r in ceo_config_apply_queue if r.get("apply_status") == "pending"]
    aq_top1    = next((r for r in aq_pending), {})
    aq_latest  = ceo_config_apply_queue[-1] if ceo_config_apply_queue else {}

    aq_rows = ""
    for ar in list(reversed(ceo_config_apply_queue))[:20]:
        ast     = ar.get("apply_status", "pending")
        ast_col = "#0ea5e9" if ast == "pending" else ("#22c55e" if ast == "applied" else "#374151")
        ta      = ar.get("target_agent", "") or "(全体)"
        tc      = ar.get("target_config", "—")
        pp_path = ar.get("patch_path", "—")
        ws      = ar.get("write_scope", "—")
        row_op  = "opacity:1" if ast == "pending" else "opacity:0.6"
        # RESULT バッジ
        aq_dk = ar.get("duplicate_key", "")
        aq_result_badge = ('<span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 8px;border-radius:4px;font-size:0.65rem;font-weight:800">✅ RESULT</span>'
                           if aq_dk in result_promoted_keys else
                           '<span style="color:#374151;font-size:0.68rem">—</span>')
        aq_rows += f"""<tr class="aq-row" data-status="{ast}" style="{row_op}">
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="font-size:0.68rem;color:#22c55e">{tc}</td>
          <td style="font-size:0.65rem;color:#a78bfa">{pp_path}</td>
          <td style="font-size:0.68rem;color:#22c55e;font-weight:700">{ws}</td>
          <td style="text-align:center">{aq_result_badge}</td>
          <td style="text-align:center"><span style="background:{ast_col}22;border:1px solid {ast_col}55;color:{ast_col};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:700">{ast}</span></td>
        </tr>"""
    if not aq_rows:
        aq_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:16px">適用待ちなし（config_patch_plan から自動登録されます）</td></tr>'

    aq_top1_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #0ea5e9;border-radius:10px;padding:12px 16px;margin-bottom:14px">
  <span style="color:#0ea5e9;font-weight:800;font-size:0.85rem">📝 1位: {aq_top1.get('target_agent','') or '—'}</span>
  <span style="color:#64748b;font-size:0.72rem;margin-left:8px">{aq_top1.get('patch_path','—')}</span>
  <span style="margin-left:auto;color:#22c55e;font-size:0.68rem;font-weight:700;float:right">write_scope={aq_top1.get('write_scope','—')}</span>
</div>""" if aq_top1 else '<div style="color:#374151;padding:12px;font-size:0.78rem">適用待ちなし</div>'

    ceo_apply_queue_section_html = f"""<div class="section" id="ceo-apply-queue">
  <div class="section-title">
    <span class="section-title-icon">📝</span>
    AC. CEO設定適用待ち — apply queue
    <span style="margin-left:auto;font-size:0.72rem;color:#0ea5e9">pending {len(aq_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#0ea5e922;border:1px solid #0ea5e955;color:#0ea5e9;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">📝 pending {len(aq_pending)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_config_apply_queue)}件</span>
  </div>
  {aq_top1_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr>
        <th>対象AI</th><th>target_config</th><th>patch_path</th><th>write_scope</th><th style="text-align:center">✅ RESULT</th><th>状態</th>
      </tr></thead>
      <tbody id="aq-tbody">{aq_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📝 config/agent_directives.json への実際の書き込み直前キュー。write_scope=config_only 固定。
  </div>
</div>"""

    # ─── セクションAD: CEO設定変更結果 — apply result ───
    ar_applied = [r for r in ceo_config_apply_result if r.get("result_status") == "applied"]
    ar_blocked = [r for r in ceo_config_apply_result if r.get("result_status") == "blocked"]
    ar_failed  = [r for r in ceo_config_apply_result if r.get("result_status") == "failed"]
    ar_latest  = ceo_config_apply_result[-1] if ceo_config_apply_result else {}

    ar_rows = ""
    for rr in list(reversed(ceo_config_apply_result))[:20]:
        rs      = rr.get("result_status", "failed")
        rs_col  = "#22c55e" if rs == "applied" else ("#ef4444" if rs == "blocked" else "#f59e0b")
        ta      = rr.get("target_agent", "") or "(全体)"
        rr_reason = (rr.get("result_reason", "") or "")[:80].replace("<", "&lt;")
        bk_path = rr.get("backup_path", "") or "—"
        df_path = rr.get("diff_path", "") or "—"
        pp_path = rr.get("patch_path", "—")
        ap_at   = (rr.get("applied_at", "") or "")[:16]
        row_op  = "opacity:1" if rs == "applied" else "opacity:0.7"
        ar_rows += f"""<tr class="ar-row" data-status="{rs}" style="{row_op}">
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{rs_col}22;border:1px solid {rs_col}55;color:{rs_col};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{rs}</span></td>
          <td style="font-size:0.68rem;color:#94a3b8">{rr_reason}</td>
          <td style="font-size:0.62rem;color:#64748b">{bk_path}</td>
          <td style="font-size:0.62rem;color:#a78bfa">{df_path}</td>
          <td style="font-size:0.62rem;color:#6366f1">{pp_path}</td>
          <td style="font-size:0.68rem;color:#64748b">{ap_at}</td>
        </tr>"""
    if not ar_rows:
        ar_rows = '<tr><td colspan="7" style="color:#64748b;text-align:center;padding:16px">変更結果なし（config_apply_queue から自動実行されます）</td></tr>'

    ar_latest_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid {'#22c55e' if ar_latest.get('result_status')=='applied' else '#ef4444'};border-radius:10px;padding:12px 16px;margin-bottom:14px">
  <span style="color:{'#22c55e' if ar_latest.get('result_status')=='applied' else '#ef4444'};font-weight:800">{'✅' if ar_latest.get('result_status')=='applied' else '🚫'} 最新: {ar_latest.get('target_agent','') or '—'}</span>
  <span style="color:#64748b;font-size:0.72rem;margin-left:8px">{ar_latest.get('result_status','—')}</span>
  <div style="font-size:0.68rem;color:#64748b;margin-top:4px">diff: <span style="color:#a78bfa">{ar_latest.get('diff_path','—')}</span> / backup: <span style="color:#94a3b8">{ar_latest.get('backup_path','—')}</span></div>
</div>""" if ar_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">変更結果なし</div>'

    ceo_apply_result_section_html = f"""<div class="section" id="ceo-apply-result">
  <div class="section-title">
    <span class="section-title-icon">✅</span>
    AD. CEO設定変更結果 — apply result
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">applied {len(ar_applied)}件 / blocked {len(ar_blocked)}件 / failed {len(ar_failed)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ applied {len(ar_applied)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(ar_blocked)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⚠️ failed {len(ar_failed)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_config_apply_result)}件</span>
  </div>
  {ar_latest_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th>対象AI</th><th style="text-align:center">result_status</th><th>result_reason</th><th>backup_path</th><th>diff_path</th><th>patch_path</th><th>applied_at</th>
      </tr></thead>
      <tbody id="ar-tbody">{ar_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ✅ 完全決定論。applied のみ実際に config/agent_directives.json へ反映。rollback は <code style="color:#a78bfa">python3 lib/ceo_config_executor.py rollback [agent名]</code> で実行。
  </div>
</div>"""

    # ─── セクションAE: 実行結果観測 ───
    _EVAL_COLOR = {"improved": "#22c55e", "no_change": "#f59e0b", "degraded": "#ef4444"}
    _FB_COLOR   = {"keep": "#22c55e", "minor_adjust": "#f59e0b", "urgent_fix": "#ef4444"}

    aer_success = [r for r in ceo_exec_result_queue if r.get("status") == "success"]
    aer_fail    = [r for r in ceo_exec_result_queue if r.get("status") == "fail"]
    aer_latest  = ceo_exec_result_queue[-1] if ceo_exec_result_queue else {}

    aer_rows = ""
    for rr in list(reversed(ceo_exec_result_queue))[:20]:
        st    = rr.get("status", "fail")
        sc    = "#22c55e" if st == "success" else "#ef4444"
        ta    = rr.get("target_agent", "") or "—"
        rid   = rr.get("run_id", "—")
        out   = (rr.get("output", "") or "")[:60].replace("<","&lt;")
        et    = rr.get("error_type", "") or "—"
        lat   = rr.get("latency", 0.0)
        chash = rr.get("config_version_hash", "—")
        ts    = (rr.get("pipeline_timestamp", "") or "")[:16]
        aer_rows += f"""<tr>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{sc}22;border:1px solid {sc}55;color:{sc};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{st}</span></td>
          <td style="font-size:0.68rem;color:#64748b">{rid}</td>
          <td style="font-size:0.68rem;color:#94a3b8">{out}</td>
          <td style="font-size:0.68rem;color:#ef4444">{et}</td>
          <td style="text-align:right;font-size:0.68rem;color:#64748b">{lat:.3f}</td>
          <td style="font-size:0.62rem;color:#a78bfa">{chash}</td>
          <td style="font-size:0.65rem;color:#64748b">{ts}</td>
        </tr>"""
    if not aer_rows:
        aer_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">実行結果なし（config_apply_result から自動収集されます）</td></tr>'

    ceo_exec_result_section_html = f"""<div class="section" id="ceo-exec-result">
  <div class="section-title">
    <span class="section-title-icon">📊</span>
    AE. CEO実行結果観測 — agent execution result
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">success {len(aer_success)}件 / fail {len(aer_fail)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ success {len(aer_success)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">❌ fail {len(aer_fail)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_exec_result_queue)}件</span>
    <span style="margin-left:auto;font-size:0.7rem;color:#64748b">最新: <span style="color:#818cf8;font-weight:700">{aer_latest.get('target_agent','—')}</span> / <span style="color:{'#22c55e' if aer_latest.get('status')=='success' else '#ef4444'}">{aer_latest.get('status','—')}</span> / config={aer_latest.get('config_version_hash','—')}</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr>
        <th>対象AI</th><th style="text-align:center">status</th><th>run_id</th><th>output</th><th>error_type</th><th style="text-align:right">latency</th><th>config_hash</th><th>timestamp</th>
      </tr></thead>
      <tbody>{aer_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📊 pipeline.jsonl から自動収集。config適用後の直近{20}件を表示。読み取り専用。
  </div>
</div>"""

    # ─── セクションAF: パフォーマンス評価 ───
    ape_improved  = [r for r in ceo_perf_eval_queue if r.get("evaluation_result") == "improved"]
    ape_nochange  = [r for r in ceo_perf_eval_queue if r.get("evaluation_result") == "no_change"]
    ape_degraded  = [r for r in ceo_perf_eval_queue if r.get("evaluation_result") == "degraded"]
    ape_latest    = ceo_perf_eval_queue[-1] if ceo_perf_eval_queue else {}

    ape_rows = ""
    for pr in list(reversed(ceo_perf_eval_queue))[:20]:
        ta    = pr.get("target_agent", "") or "—"
        er    = pr.get("evaluation_result", "no_change")
        er_c  = _EVAL_COLOR.get(er, "#64748b")
        sr    = pr.get("success_rate", 0.0)
        fr    = pr.get("fail_rate", 0.0)
        hfr   = pr.get("hard_fail_rate", 0.0)
        lat   = pr.get("latency_avg", 0.0)
        delta = pr.get("performance_delta", "—")
        base  = pr.get("baseline_success_rate", "N/A")
        base_s = f"{base:.1%}" if isinstance(base, float) else str(base)
        delta_c = "#22c55e" if "+" in str(delta) else ("#ef4444" if "-" in str(delta) else "#64748b")
        ape_rows += f"""<tr>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:right;font-weight:800;color:#22c55e">{sr:.1%}</td>
          <td style="text-align:right;color:#ef4444">{fr:.1%}</td>
          <td style="text-align:right;color:#f59e0b">{hfr:.1%}</td>
          <td style="text-align:right;color:#64748b">{lat:.3f}</td>
          <td style="text-align:center;color:#94a3b8">{base_s}</td>
          <td style="text-align:center"><span style="color:{delta_c};font-weight:800;font-size:0.88rem">{delta}</span></td>
          <td style="text-align:center"><span style="background:{er_c}22;border:1px solid {er_c}55;color:{er_c};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{er}</span></td>
        </tr>"""
    if not ape_rows:
        ape_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">評価なし（execution_result から自動評価されます）</td></tr>'

    ceo_perf_eval_section_html = f"""<div class="section" id="ceo-perf-eval">
  <div class="section-title">
    <span class="section-title-icon">📈</span>
    AF. CEO パフォーマンス評価 — performance evaluation
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">improved {len(ape_improved)} / no_change {len(ape_nochange)} / degraded {len(ape_degraded)}</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">📈 improved {len(ape_improved)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">➡️ no_change {len(ape_nochange)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">📉 degraded {len(ape_degraded)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_perf_eval_queue)}件</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:880px">
      <thead><tr>
        <th>対象AI</th><th style="text-align:right">success_rate</th><th style="text-align:right">fail_rate</th><th style="text-align:right">hard_fail_rate</th><th style="text-align:right">latency_avg</th><th style="text-align:center">baseline</th><th style="text-align:center">delta</th><th style="text-align:center">評価結果</th>
      </tr></thead>
      <tbody>{ape_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📈 improved=+5%以上 / degraded=-3%以下 / それ以外=no_change。ルールベース完全決定論。
  </div>
</div>"""

    # ─── セクションAG: フィードバックループ ───
    afb_keep   = [r for r in ceo_feedback_loop_queue if r.get("feedback_type") == "keep"]
    afb_adjust = [r for r in ceo_feedback_loop_queue if r.get("feedback_type") == "minor_adjust"]
    afb_fix    = [r for r in ceo_feedback_loop_queue if r.get("feedback_type") == "urgent_fix"]
    afb_latest = ceo_feedback_loop_queue[-1] if ceo_feedback_loop_queue else {}

    afb_rows = ""
    for fr in list(reversed(ceo_feedback_loop_queue))[:20]:
        ta    = fr.get("target_agent", "") or "—"
        ft    = fr.get("feedback_type", "minor_adjust")
        ft_c  = _FB_COLOR.get(ft, "#64748b")
        prio  = fr.get("priority", "MEDIUM")
        pc    = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}.get(prio, "#64748b")
        hint  = (fr.get("next_improvement_hint", "") or "")[:80].replace("<","&lt;")
        delta = fr.get("performance_delta", "—")
        delta_c = "#22c55e" if "+" in str(delta) else ("#ef4444" if "-" in str(delta) else "#64748b")
        sr    = fr.get("success_rate", 0.0)
        afb_rows += f"""<tr>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center"><span style="background:{pc}22;border:1px solid {pc}55;color:{pc};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{prio}</span></td>
          <td style="text-align:right;font-weight:800;color:#22c55e">{sr:.1%}</td>
          <td style="text-align:center;color:{delta_c};font-weight:800">{delta}</td>
          <td style="font-size:0.65rem;color:#94a3b8;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{hint}</td>
        </tr>"""
    if not afb_rows:
        afb_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:16px">フィードバックなし（performance_evaluation から自動生成されます）</td></tr>'

    ceo_feedback_section_html = f"""<div class="section" id="ceo-feedback">
  <div class="section-title">
    <span class="section-title-icon">🔁</span>
    AG. CEO フィードバックループ — 次改善指示
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">keep {len(afb_keep)} / adjust {len(afb_adjust)} / fix {len(afb_fix)}</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ keep {len(afb_keep)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔧 minor_adjust {len(afb_adjust)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚨 urgent_fix {len(afb_fix)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_feedback_loop_queue)}件</span>
  </div>
  <div style="background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.72rem;color:#64748b">
    🔁 <strong style="color:#818cf8">完全自動ループ:</strong>
    improvement → ready → execution_ready → simulation → ranked → packet → dispatch → stub → dry_run → candidate → limited → guard → <span style="color:#fb923c">patch_plan</span> → <span style="color:#0ea5e9">apply</span> → <span style="color:#22c55e">result</span> → <span style="color:#a78bfa">execution</span> → <span style="color:#f59e0b">evaluation</span> → <span style="color:#ef4444">feedback</span> → <span style="color:#818cf8">improvement</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:800px">
      <thead><tr>
        <th>対象AI</th><th style="text-align:center">feedback_type</th><th style="text-align:center">priority</th><th style="text-align:right">success_rate</th><th style="text-align:center">delta</th><th>next_improvement_hint</th>
      </tr></thead>
      <tbody>{afb_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔁 improved→keep（再投入なし） / no_change→minor_adjust / degraded→urgent_fix。improvement_queueへ自動再投入。
  </div>
</div>"""

    # ─── セクションAH: 再投入優先順位 ───
    _RI_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    ri_pending  = [r for r in ceo_reinject_priority_queue if r.get("status") == "pending"]
    ri_critical = [r for r in ri_pending if r.get("reinject_priority_label") == "CRITICAL"]
    ri_high     = [r for r in ri_pending if r.get("reinject_priority_label") == "HIGH"]
    ri_medium   = [r for r in ri_pending if r.get("reinject_priority_label") == "MEDIUM"]
    ri_low      = [r for r in ri_pending if r.get("reinject_priority_label") == "LOW"]

    # ソート済みリスト（reinject_order基準、なければスコア降順）
    ri_sorted = sorted(ri_pending, key=lambda r: (r.get("reinject_order", 999), -r.get("reinject_priority_score", 0)))
    ri_top1   = ri_sorted[0] if ri_sorted else {}

    # top1 ハイライトカード
    if ri_top1:
        top1_lbl = ri_top1.get("reinject_priority_label", "LOW")
        top1_c   = _RI_COLOR.get(top1_lbl, "#64748b")
        top1_hint = (ri_top1.get("next_improvement_hint", "") or "")[:100].replace("<", "&lt;")
        ri_top1_card_html = f"""<div style="background:linear-gradient(135deg,{top1_c}18,#0d1117);border:1px solid {top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">#{ri_top1.get('reinject_order',1)} {top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{ri_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{top1_c}">score {ri_top1.get('reinject_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">feedback_type: <strong style="color:#e2e8f0">{ri_top1.get('feedback_type','—')}</strong></div>
      <div style="font-size:0.70rem;color:#64748b;margin-bottom:4px">{top1_hint}</div>
      <div style="font-size:0.68rem;color:#374151">{ri_top1.get('ceo_judgment','')}</div>
    </div>"""
    else:
        ri_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">再投入候補なし</div>'

    ri_rows = ""
    for rr in ri_sorted[:30]:
        lbl   = rr.get("reinject_priority_label", "LOW")
        lbl_c = _RI_COLOR.get(lbl, "#64748b")
        ft    = rr.get("feedback_type", "")
        ft_c  = _FB_COLOR.get(ft, "#64748b")
        ta    = rr.get("target_agent", "—")
        sr    = rr.get("success_rate", 0.0)
        delta = rr.get("performance_delta", "—")
        delta_c = "#22c55e" if "+" in str(delta) else ("#ef4444" if "-" in str(delta) else "#64748b")
        rv    = rr.get("revenue_impact_score", 0.0)
        seo   = rr.get("seo_impact_score", 0.0)
        cvr   = rr.get("cvr_impact_score", 0.0)
        fresh = rr.get("freshness_urgency_score", 0.0)
        score = rr.get("reinject_priority_score", 0.0)
        action = (rr.get("proposed_reinject_action", "") or "")[:60].replace("<", "&lt;")
        status = rr.get("status", "pending")
        order = rr.get("reinject_order", "—")
        dup_key = rr.get("duplicate_key", "")
        is_dispatched = dup_key in dispatched_dup_keys
        disp_badge = '<span style="background:#0ea5e922;border:1px solid #0ea5e955;color:#0ea5e9;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">📨 DISPATCH</span>' if is_dispatched else '<span style="color:#374151;font-size:0.65rem">—</span>'
        ri_rows += f"""<tr class="ri-row" data-label="{lbl}" data-status="{status}">
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:right;font-weight:800;color:#22c55e">{sr:.1%}</td>
          <td style="text-align:center;color:{delta_c};font-weight:800">{delta}</td>
          <td style="text-align:center;font-weight:800;color:#f59e0b">{rv:.2f}</td>
          <td style="text-align:center;font-weight:800;color:#0ea5e9">{seo:.2f}</td>
          <td style="text-align:center;font-weight:800;color:#a78bfa">{cvr:.2f}</td>
          <td style="text-align:center;font-weight:800;color:#22d3ee">{fresh:.2f}</td>
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{score:.3f}</td>
          <td style="text-align:center"><span style="background:{lbl_c}22;border:1px solid {lbl_c}55;color:{lbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{lbl}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{action}</td>
          <td style="text-align:center">{disp_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{status}</td>
        </tr>"""
    if not ri_rows:
        ri_rows = '<tr><td colspan="14" style="color:#64748b;text-align:center;padding:16px">再投入候補なし（フィードバックループ完了後に自動生成されます）</td></tr>'

    ceo_reinject_section_html = f"""<div class="section" id="ceo-reinject">
  <div class="section-title">
    <span class="section-title-icon">♻️</span>
    AH. 再投入優先順位 — 売上影響ベース
    <span style="margin-left:auto;font-size:0.72rem;color:#f97316">pending {len(ri_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 CRITICAL {len(ri_critical)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH {len(ri_high)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {len(ri_medium)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {len(ri_low)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_reinject_priority_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterRI('all')" id="ri-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ri-filter-btn">全件</button>
    <button onclick="filterRI('CRITICAL')" id="ri-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ri-filter-btn">CRITICAL</button>
    <button onclick="filterRI('HIGH')" id="ri-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ri-filter-btn">HIGH</button>
    <button onclick="filterRI('MEDIUM')" id="ri-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ri-filter-btn">MEDIUM</button>
    <button onclick="filterRI('LOW')" id="ri-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ri-filter-btn">LOW</button>
    <button onclick="filterRI('pending')" id="ri-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ri-filter-btn">pending</button>
  </div>
  {ri_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="ri-table" style="min-width:1200px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:right">success_rate</th>
        <th style="text-align:center">delta</th>
        <th style="text-align:center">revenue</th>
        <th style="text-align:center">seo</th>
        <th style="text-align:center">cvr</th>
        <th style="text-align:center">freshness</th>
        <th style="text-align:center">score</th>
        <th style="text-align:center">ラベル</th>
        <th>proposed_action</th>
        <th style="text-align:center">DISPATCH</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="ri-tbody">{ri_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ♻️ 再投入優先順位 = revenue×0.40 + seo×0.20 + cvr×0.20 + freshness×0.20 | 実行はしない。ミュウツーCEOが判断する優先順位付けのみ。
  </div>
  <script>
  function filterRI(label) {{
    document.querySelectorAll('.ri-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('ri-btn-'+label).style.opacity='1';
    document.querySelectorAll('#ri-tbody .ri-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === 'pending' ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAI: 再投入ディスパッチ ───
    _DI_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    di_pending  = [r for r in ceo_reinject_dispatch_queue if r.get("dispatch_status") == "pending"]
    di_high     = [r for r in di_pending if r.get("reinject_priority_label") in ("CRITICAL", "HIGH")]
    di_medium   = [r for r in di_pending if r.get("reinject_priority_label") == "MEDIUM"]
    di_sorted   = sorted(di_pending, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    di_top1     = di_sorted[0] if di_sorted else {}

    if di_top1:
        di_top1_lbl = di_top1.get("reinject_priority_label", "LOW")
        di_top1_c   = _DI_COLOR.get(di_top1_lbl, "#64748b")
        di_top1_hint = (di_top1.get("next_improvement_hint", "") or "")[:100].replace("<", "&lt;")
        di_top1_card_html = f"""<div style="background:linear-gradient(135deg,{di_top1_c}18,#0d1117);border:1px solid {di_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{di_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">#{di_top1.get('reinject_order',1)} {di_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{di_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{di_top1_c}">score {di_top1.get('reinject_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">feedback_type: <strong style="color:#e2e8f0">{di_top1.get('feedback_type','—')}</strong></div>
      <div style="font-size:0.70rem;color:#64748b">{di_top1_hint}</div>
    </div>"""
    else:
        di_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">ディスパッチ候補なし</div>'

    di_rows = ""
    for dr in di_sorted[:30]:
        lbl   = dr.get("reinject_priority_label", "LOW")
        lbl_c = _DI_COLOR.get(lbl, "#64748b")
        ft    = dr.get("feedback_type", "")
        ft_c  = _FB_COLOR.get(ft, "#64748b")
        ta    = dr.get("target_agent", "—")
        score = dr.get("reinject_priority_score", 0.0)
        hint  = (dr.get("next_improvement_hint", "") or "")[:70].replace("<", "&lt;")
        dstatus = dr.get("dispatch_status", "pending")
        order   = dr.get("reinject_order", "—")
        di_rows += f"""<tr class="di-row" data-label="{lbl}" data-status="{dstatus}">
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{score:.3f}</td>
          <td style="text-align:center"><span style="background:{lbl_c}22;border:1px solid {lbl_c}55;color:{lbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{lbl}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{hint}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{dstatus}</td>
        </tr>"""
    if not di_rows:
        di_rows = '<tr><td colspan="7" style="color:#64748b;text-align:center;padding:16px">ディスパッチ候補なし（再投入優先順位から自動生成されます）</td></tr>'

    ceo_dispatch_section_html = f"""<div class="section" id="ceo-reinject-dispatch">
  <div class="section-title">
    <span class="section-title-icon">📨</span>
    AI. 再投入ディスパッチ — 再投入候補の交通整理
    <span style="margin-left:auto;font-size:0.72rem;color:#f97316">pending {len(di_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(di_pending)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH+ {len(di_high)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {len(di_medium)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_reinject_dispatch_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterDI('all')" id="di-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="di-filter-btn">全件</button>
    <button onclick="filterDI('HIGH')" id="di-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="di-filter-btn">HIGH+</button>
    <button onclick="filterDI('MEDIUM')" id="di-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="di-filter-btn">MEDIUM</button>
    <button onclick="filterDI('LOW')" id="di-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="di-filter-btn">LOW</button>
    <button onclick="filterDI('pending')" id="di-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="di-filter-btn">pending</button>
  </div>
  {di_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="di-table" style="min-width:800px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">score</th>
        <th style="text-align:center">ラベル</th>
        <th>next_improvement_hint</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="di-tbody">{di_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📨 reinject_priority_queue(CRITICAL/HIGH/MEDIUM) → reinject_dispatch_queue。execution_blocked=true / write_scope=none。実行しない。
  </div>
  <script>
  function filterDI(label) {{
    document.querySelectorAll('.di-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('di-btn-'+label).style.opacity='1';
    document.querySelectorAll('#di-tbody .di-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === 'pending' ? '' : 'none'; return; }}
      if (label === 'HIGH') {{ row.style.display = ['CRITICAL','HIGH'].includes(row.dataset.label) ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAJ: 限定再投入候補 ───
    rj_pending  = [r for r in ceo_reinject_return_queue if r.get("return_status") == "pending"]
    rj_high     = [r for r in rj_pending if r.get("reinject_priority_label") in ("CRITICAL", "HIGH")]
    rj_medium   = [r for r in rj_pending if r.get("reinject_priority_label") == "MEDIUM"]
    rj_sorted   = sorted(rj_pending, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    rj_top1     = rj_sorted[0] if rj_sorted else {}

    if rj_top1:
        rj_top1_lbl = rj_top1.get("reinject_priority_label", "LOW")
        rj_top1_c   = _DI_COLOR.get(rj_top1_lbl, "#64748b")
        rj_top1_action = (rj_top1.get("proposed_reinject_action", "") or "")[:100].replace("<", "&lt;")
        rj_top1_card_html = f"""<div style="background:linear-gradient(135deg,{rj_top1_c}18,#0d1117);border:1px solid {rj_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{rj_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">#{rj_top1.get('reinject_order',1)} {rj_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{rj_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{rj_top1_c}">score {rj_top1.get('reinject_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{rj_top1_action}</div>
      <div style="font-size:0.68rem;color:#0ea5e9">→ {rj_top1.get('return_target_lane','limited_execution_queue')}</div>
    </div>"""
    else:
        rj_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">限定再投入候補なし</div>'

    rj_rows = ""
    for rr in rj_sorted[:30]:
        lbl   = rr.get("reinject_priority_label", "LOW")
        lbl_c = _DI_COLOR.get(lbl, "#64748b")
        ft    = rr.get("feedback_type", "")
        ft_c  = _FB_COLOR.get(ft, "#64748b")
        ta    = rr.get("target_agent", "—")
        score = rr.get("reinject_priority_score", 0.0)
        action = (rr.get("proposed_reinject_action", "") or "")[:60].replace("<", "&lt;")
        lane   = rr.get("return_target_lane", "limited_execution_queue")
        rstatus = rr.get("return_status", "pending")
        order   = rr.get("reinject_order", "—")
        dup_key_rj = rr.get("duplicate_key", "")
        is_gated = dup_key_rj in gated_dup_keys
        gate_badge = '<span style="background:#6366f122;border:1px solid #6366f155;color:#6366f1;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🛡 GATED</span>' if is_gated else '<span style="color:#374151;font-size:0.65rem">—</span>'
        rj_rows += f"""<tr class="rj-row" data-label="{lbl}" data-status="{rstatus}">
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{score:.3f}</td>
          <td style="text-align:center"><span style="background:{lbl_c}22;border:1px solid {lbl_c}55;color:{lbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{lbl}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{action}</td>
          <td style="text-align:center;font-size:0.65rem;color:#0ea5e9;font-weight:700">{lane}</td>
          <td style="text-align:center">{gate_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{rstatus}</td>
        </tr>"""
    if not rj_rows:
        rj_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">限定再投入候補なし（dispatch_queue から自動生成されます）</td></tr>'

    ceo_reinject_return_section_html = f"""<div class="section" id="ceo-reinject-return">
  <div class="section-title">
    <span class="section-title-icon">♻️</span>
    AJ. 限定再投入候補 — limited_execution 戻し前
    <span style="margin-left:auto;font-size:0.72rem;color:#0ea5e9">pending {len(rj_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(rj_pending)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH+ {len(rj_high)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {len(rj_medium)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_reinject_return_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterRJ('all')" id="rj-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rj-filter-btn">全件</button>
    <button onclick="filterRJ('HIGH')" id="rj-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rj-filter-btn">HIGH+</button>
    <button onclick="filterRJ('MEDIUM')" id="rj-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rj-filter-btn">MEDIUM</button>
    <button onclick="filterRJ('pending')" id="rj-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rj-filter-btn">pending</button>
  </div>
  {rj_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="rj-table" style="min-width:900px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">score</th>
        <th style="text-align:center">ラベル</th>
        <th>proposed_action</th>
        <th style="text-align:center">return_target_lane</th>
        <th style="text-align:center">GATE</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="rj-tbody">{rj_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ♻️ dispatch_queue(CRITICAL/HIGH + MEDIUM×売上直結AI) → limited_return_queue。return_target_lane=limited_execution_queue 固定。実際の書き戻しは未実装（ミュウツーCEO承認待ち）。
  </div>
  <script>
  function filterRJ(label) {{
    document.querySelectorAll('.rj-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('rj-btn-'+label).style.opacity='1';
    document.querySelectorAll('#rj-tbody .rj-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === 'pending' ? '' : 'none'; return; }}
      if (label === 'HIGH') {{ row.style.display = ['CRITICAL','HIGH'].includes(row.dataset.label) ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAK: 再投入ゲート判定 ───
    ak_all     = ceo_reinject_gate_queue
    ak_pending = [r for r in ak_all if r.get("gate_status") == "pending"]
    ak_blocked = [r for r in ak_all if r.get("gate_status") == "blocked"]
    ak_sorted  = sorted(ak_pending, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    ak_top1    = ak_sorted[0] if ak_sorted else {}

    if ak_top1:
        ak_top1_lbl = ak_top1.get("reinject_priority_label", "LOW")
        ak_top1_c   = _DI_COLOR.get(ak_top1_lbl, "#64748b")
        ak_top1_hint = (ak_top1.get("next_improvement_hint", "") or "")[:100].replace("<", "&lt;")
        ak_top1_card_html = f"""<div style="background:linear-gradient(135deg,{ak_top1_c}18,#0d1117);border:1px solid {ak_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{ak_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">#{ak_top1.get('reinject_order',1)} {ak_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{ak_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{ak_top1_c}">score {ak_top1.get('reinject_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">feedback_type: <strong style="color:#e2e8f0">{ak_top1.get('feedback_type','—')}</strong></div>
      <div style="font-size:0.70rem;color:#64748b">{ak_top1_hint}</div>
    </div>"""
    else:
        ak_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">ゲート通過候補なし</div>'

    ak_rows = ""
    for gr in (ak_sorted + ak_blocked)[:30]:
        lbl     = gr.get("reinject_priority_label", "LOW")
        lbl_c   = _DI_COLOR.get(lbl, "#64748b")
        ft      = gr.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = gr.get("target_agent", "—")
        score   = gr.get("reinject_priority_score", 0.0)
        gstat   = gr.get("gate_status", "pending")
        gpassed = gr.get("gate_passed", False)
        greason = (gr.get("gate_reason", "") or "")[:60].replace("<", "&lt;")
        order   = gr.get("reinject_order", "—")
        gstat_c = "#22c55e" if gstat == "pending" else ("#ef4444" if gstat == "blocked" else "#64748b")
        passed_badge = '<span style="color:#22c55e;font-weight:900">✅ pass</span>' if gpassed else '<span style="color:#ef4444;font-weight:900">❌ fail</span>'
        ak_rows += f"""<tr class="ak-row" data-label="{lbl}" data-status="{gstat}">
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{score:.3f}</td>
          <td style="text-align:center"><span style="background:{lbl_c}22;border:1px solid {lbl_c}55;color:{lbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{lbl}</span></td>
          <td style="text-align:center">{passed_badge}</td>
          <td style="font-size:0.60rem;color:#94a3b8;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{greason}</td>
          <td style="text-align:center;font-size:0.68rem;color:{gstat_c};font-weight:700">{gstat}</td>
        </tr>"""
    if not ak_rows:
        ak_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:16px">ゲート判定なし（limited_return_queue から自動生成されます）</td></tr>'

    ceo_gate_section_html = f"""<div class="section" id="ceo-reinject-gate">
  <div class="section-title">
    <span class="section-title-icon">🛡</span>
    AK. 再投入ゲート判定 — patch戻し前安全確認
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">pending {len(ak_pending)}件 / blocked {len(ak_blocked)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ pending {len(ak_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">❌ blocked {len(ak_blocked)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ak_all)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAK('all')" id="ak-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ak-filter-btn">全件</button>
    <button onclick="filterAK('pending')" id="ak-btn-pending" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ak-filter-btn">pending</button>
    <button onclick="filterAK('blocked')" id="ak-btn-blocked" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ak-filter-btn">blocked</button>
    <button onclick="filterAK('HIGH')" id="ak-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ak-filter-btn">HIGH+</button>
    <button onclick="filterAK('MEDIUM')" id="ak-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ak-filter-btn">MEDIUM</button>
  </div>
  {ak_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="ak-table" style="min-width:900px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">score</th>
        <th style="text-align:center">ラベル</th>
        <th style="text-align:center">gate_passed</th>
        <th>gate_reason</th>
        <th style="text-align:center">gate_status</th>
      </tr></thead>
      <tbody id="ak-tbody">{ak_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🛡 ゲートチェック: execution_blocked=true / write_scope=none / target_agent非空 / feedback_type正当 / priority_label正当 の5条件。全Pass→pending / いずれかFail→blocked。
  </div>
  <script>
  function filterAK(label) {{
    document.querySelectorAll('.ak-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('ak-btn-'+label).style.opacity='1';
    document.querySelectorAll('#ak-tbody .ak-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending' || label === 'blocked') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      if (label === 'HIGH') {{ row.style.display = ['CRITICAL','HIGH'].includes(row.dataset.label) ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAL: 再投入パッチ接続候補 ───
    al_pending = [r for r in ceo_reinject_patch_ready if r.get("patch_ready_status") == "pending"]
    al_high    = [r for r in al_pending if r.get("reinject_priority_label") in ("CRITICAL", "HIGH")]
    al_medium  = [r for r in al_pending if r.get("reinject_priority_label") == "MEDIUM"]
    al_sorted  = sorted(al_pending, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    al_top1    = al_sorted[0] if al_sorted else {}

    if al_top1:
        al_top1_lbl = al_top1.get("reinject_priority_label", "LOW")
        al_top1_c   = _DI_COLOR.get(al_top1_lbl, "#64748b")
        al_top1_action = (al_top1.get("proposed_reinject_action", "") or "")[:100].replace("<", "&lt;")
        al_top1_card_html = f"""<div style="background:linear-gradient(135deg,{al_top1_c}18,#0d1117);border:1px solid {al_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{al_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">#{al_top1.get('reinject_order',1)} {al_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{al_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{al_top1_c}">score {al_top1.get('reinject_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{al_top1_action}</div>
      <div style="font-size:0.68rem;color:#6366f1">→ patch_target_lane: {al_top1.get('patch_target_lane','ceo_config_patch_plan_queue')}</div>
    </div>"""
    else:
        al_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">パッチ接続候補なし</div>'

    al_rows = ""
    for ar in al_sorted[:30]:
        lbl    = ar.get("reinject_priority_label", "LOW")
        lbl_c  = _DI_COLOR.get(lbl, "#64748b")
        ft     = ar.get("feedback_type", "")
        ft_c   = _FB_COLOR.get(ft, "#64748b")
        ta     = ar.get("target_agent", "—")
        score  = ar.get("reinject_priority_score", 0.0)
        action = (ar.get("proposed_reinject_action", "") or "")[:60].replace("<", "&lt;")
        ptlane = ar.get("patch_target_lane", "ceo_config_patch_plan_queue")
        pstatus = ar.get("patch_ready_status", "pending")
        order   = ar.get("reinject_order", "—")
        dup_key_al = ar.get("duplicate_key", "")
        is_reserved = dup_key_al in reserved_dup_keys
        res_badge = '<span style="background:#f43f5e22;border:1px solid #f43f5e55;color:#f43f5e;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">📌 RESERVED</span>' if is_reserved else '<span style="color:#374151;font-size:0.65rem">—</span>'
        al_rows += f"""<tr class="al-row" data-label="{lbl}" data-status="{pstatus}">
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{lbl_c}">{score:.3f}</td>
          <td style="text-align:center"><span style="background:{lbl_c}22;border:1px solid {lbl_c}55;color:{lbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{lbl}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{action}</td>
          <td style="text-align:center;font-size:0.63rem;color:#6366f1;font-weight:700">{ptlane}</td>
          <td style="text-align:center">{res_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{pstatus}</td>
        </tr>"""
    if not al_rows:
        al_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">パッチ接続候補なし（gate_queue から自動生成されます）</td></tr>'

    ceo_patch_ready_section_html = f"""<div class="section" id="ceo-reinject-patch-ready">
  <div class="section-title">
    <span class="section-title-icon">🧩</span>
    AL. 再投入パッチ接続候補 — patch_plan 戻し前
    <span style="margin-left:auto;font-size:0.72rem;color:#6366f1">pending {len(al_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(al_pending)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH+ {len(al_high)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {len(al_medium)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_reinject_patch_ready)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAL('all')" id="al-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="al-filter-btn">全件</button>
    <button onclick="filterAL('HIGH')" id="al-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="al-filter-btn">HIGH+</button>
    <button onclick="filterAL('MEDIUM')" id="al-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="al-filter-btn">MEDIUM</button>
    <button onclick="filterAL('pending')" id="al-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="al-filter-btn">pending</button>
  </div>
  {al_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="al-table" style="min-width:950px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">score</th>
        <th style="text-align:center">ラベル</th>
        <th>proposed_reinject_action</th>
        <th style="text-align:center">patch_target_lane</th>
        <th style="text-align:center">RESERVE</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="al-tbody">{al_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧩 patch_target_lane=ceo_config_patch_plan_queue 固定。実際の書き戻しは未実装（ミュウツーCEO承認待ち）。execution_blocked=true / write_scope=none。
  </div>
  <script>
  function filterAL(label) {{
    document.querySelectorAll('.al-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('al-btn-'+label).style.opacity='1';
    document.querySelectorAll('#al-tbody .al-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === 'pending' ? '' : 'none'; return; }}
      if (label === 'HIGH') {{ row.style.display = ['CRITICAL','HIGH'].includes(row.dataset.label) ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAM: 再接続予約レーン ───
    _AM_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    am_pending  = [r for r in ceo_reinject_patch_reserve if r.get("reserve_status") == "pending"]
    am_critical = [r for r in am_pending if r.get("reserve_label") == "CRITICAL"]
    am_high     = [r for r in am_pending if r.get("reserve_label") == "HIGH"]
    am_medium   = [r for r in am_pending if r.get("reserve_label") == "MEDIUM"]
    am_low      = [r for r in am_pending if r.get("reserve_label") == "LOW"]
    am_sorted   = sorted(am_pending, key=lambda r: (int(r.get("reserve_order", 999)), -float(r.get("reserve_priority_score", 0))))
    am_top1     = am_sorted[0] if am_sorted else {}

    if am_top1:
        am_top1_lbl = am_top1.get("reserve_label", "LOW")
        am_top1_c   = _AM_COLOR.get(am_top1_lbl, "#64748b")
        am_top1_action = (am_top1.get("proposed_reinject_action", "") or "")[:100].replace("<", "&lt;")
        am_top1_card_html = f"""<div style="background:linear-gradient(135deg,{am_top1_c}18,#0d1117);border:1px solid {am_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{am_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">#{am_top1.get('reserve_order',1)} {am_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{am_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{am_top1_c}">reserve score {am_top1.get('reserve_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{am_top1_action}</div>
      <div style="font-size:0.68rem;color:#f43f5e">📌 → {am_top1.get('patch_target_lane','ceo_config_patch_plan_queue')}</div>
    </div>"""
    else:
        am_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">再接続予約なし</div>'

    am_rows = ""
    for ar in am_sorted[:30]:
        rlbl   = ar.get("reserve_label", "LOW")
        rlbl_c = _AM_COLOR.get(rlbl, "#64748b")
        ft     = ar.get("feedback_type", "")
        ft_c   = _FB_COLOR.get(ft, "#64748b")
        ta     = ar.get("target_agent", "—")
        ri_score = ar.get("reinject_priority_score", 0.0)
        r_score  = ar.get("reserve_priority_score", 0.0)
        action   = (ar.get("proposed_reinject_action", "") or "")[:60].replace("<", "&lt;")
        ptlane   = ar.get("patch_target_lane", "ceo_config_patch_plan_queue")
        rstatus  = ar.get("reserve_status", "pending")
        order    = ar.get("reserve_order", "—")
        dup_key_am = ar.get("duplicate_key", "")
        is_committed = dup_key_am in committed_dup_keys
        commit_badge = '<span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">✅ COMMITTED</span>' if is_committed else '<span style="color:#374151;font-size:0.65rem">—</span>'
        am_rows += f"""<tr class="am-row" data-label="{rlbl}" data-status="{rstatus}">
          <td style="text-align:center;font-weight:900;color:{rlbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:800;color:#94a3b8">{ri_score:.3f}</td>
          <td style="text-align:center;font-weight:900;color:{rlbl_c}">{r_score:.3f}</td>
          <td style="text-align:center"><span style="background:{rlbl_c}22;border:1px solid {rlbl_c}55;color:{rlbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{rlbl}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{action}</td>
          <td style="text-align:center;font-size:0.63rem;color:#6366f1;font-weight:700">{ptlane}</td>
          <td style="text-align:center">{commit_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{rstatus}</td>
        </tr>"""
    if not am_rows:
        am_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">再接続予約なし（patch_ready_queue から自動生成されます）</td></tr>'


    ceo_reserve_section_html = f"""<div class="section" id="ceo-reinject-reserve">
  <div class="section-title">
    <span class="section-title-icon">📌</span>
    AM. 再接続予約レーン — patch_plan 戻し順
    <span style="margin-left:auto;font-size:0.72rem;color:#f43f5e">pending {len(am_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(am_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 CRITICAL {len(am_critical)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH {len(am_high)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {len(am_medium)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 LOW {len(am_low)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_reinject_patch_reserve)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAM('all')" id="am-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="am-filter-btn">全件</button>
    <button onclick="filterAM('CRITICAL')" id="am-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="am-filter-btn">CRITICAL</button>
    <button onclick="filterAM('HIGH')" id="am-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="am-filter-btn">HIGH</button>
    <button onclick="filterAM('MEDIUM')" id="am-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="am-filter-btn">MEDIUM</button>
    <button onclick="filterAM('LOW')" id="am-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="am-filter-btn">LOW</button>
    <button onclick="filterAM('pending')" id="am-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="am-filter-btn">pending</button>
  </div>
  {am_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="am-table" style="min-width:1050px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">reinject_score</th>
        <th style="text-align:center">reserve_score</th>
        <th style="text-align:center">reserve_label</th>
        <th>proposed_action</th>
        <th style="text-align:center">patch_target_lane</th>
        <th style="text-align:center">COMMIT</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="am-tbody">{am_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📌 reserve_score = reinject_score×0.45 + freshness×0.20 + revenue_restore×0.25 + patch_simplicity×0.10 | patch_target_lane=ceo_config_patch_plan_queue 宣言のみ。実書き戻し未実装。execution_blocked=true。
  </div>
  <script>
  function filterAM(label) {{
    document.querySelectorAll('.am-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('am-btn-'+label).style.opacity='1';
    document.querySelectorAll('#am-tbody .am-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === 'pending' ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAN: patch_plan 再投入コミット ───
    _AN_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    an_pending  = [r for r in ceo_reinject_commit_queue if r.get("commit_status") == "pending"]
    an_sorted   = sorted(an_pending, key=lambda r: (int(r.get("reserve_order", 999)), -float(r.get("reserve_priority_score", 0))))
    an_top1     = an_sorted[0] if an_sorted else {}
    # patch_plan に reinject_commit で投入済みのレコード数
    an_promoted = sum(1 for r in ceo_patch_plan_queue if r.get("source") == "reinject_commit")
    an_history  = load_jsonl_safe("logs/ceo_reinject_patch_commit_history.jsonl")
    an_dup_count = sum(1 for r in an_history if r.get("commit_status") in ("commit_duplicate", "patch_plan_duplicate"))

    if an_top1:
        an_top1_lbl = an_top1.get("reserve_label", "LOW")
        an_top1_c   = _AN_COLOR.get(an_top1_lbl, "#64748b")
        an_top1_action = (an_top1.get("proposed_reinject_action", "") or "")[:100].replace("<", "&lt;")
        an_top1_card_html = f"""<div style="background:linear-gradient(135deg,{an_top1_c}18,#0d1117);border:1px solid {an_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{an_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{an_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{an_top1.get('target_agent','—')}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{an_top1_c}">score {an_top1.get('reserve_priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{an_top1_action}</div>
      <div style="font-size:0.68rem;color:#22c55e">✅ → {an_top1.get('patch_target_lane','ceo_config_patch_plan_queue')}</div>
    </div>"""
    else:
        an_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">コミット待ちなし</div>'

    an_rows = ""
    for cr in an_sorted[:30]:
        rlbl   = cr.get("reserve_label", "LOW")
        rlbl_c = _AN_COLOR.get(rlbl, "#64748b")
        ft     = cr.get("feedback_type", "")
        ft_c   = _FB_COLOR.get(ft, "#64748b")
        ta     = cr.get("target_agent", "—")
        r_score  = cr.get("reserve_priority_score", 0.0)
        action   = (cr.get("proposed_reinject_action", "") or "")[:60].replace("<", "&lt;")
        ptlane   = cr.get("patch_target_lane", "ceo_config_patch_plan_queue")
        cstatus  = cr.get("commit_status", "pending")
        order    = cr.get("reserve_order", "—")
        dup_key_an = cr.get("duplicate_key", "")
        is_apply_ready = dup_key_an in apply_ready_dup_keys
        apply_ready_badge = '<span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🚦 APPLY_READY</span>' if is_apply_ready else '<span style="color:#374151;font-size:0.65rem">—</span>'
        an_rows += f"""<tr class="an-row" data-label="{rlbl}" data-status="{cstatus}">
          <td style="text-align:center;font-weight:900;color:{rlbl_c}">{order}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{rlbl_c}">{r_score:.3f}</td>
          <td style="text-align:center"><span style="background:{rlbl_c}22;border:1px solid {rlbl_c}55;color:{rlbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{rlbl}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{action}</td>
          <td style="text-align:center;font-size:0.63rem;color:#22c55e;font-weight:700">{ptlane}</td>
          <td style="text-align:center">{apply_ready_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{cstatus}</td>
        </tr>"""
    if not an_rows:
        an_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">コミット待ちなし（patch_reserve_queue から自動生成されます）</td></tr>'

    ceo_commit_section_html = f"""<div class="section" id="ceo-reinject-commit">
  <div class="section-title">
    <span class="section-title-icon">✅</span>
    AN. patch_plan 再投入コミット — 実接続直前
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">pending {len(an_pending)}件 / promoted {an_promoted}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(an_pending)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ patch_plan promoted {an_promoted}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔁 duplicate {an_dup_count}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_reinject_commit_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAN('all')" id="an-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="an-filter-btn">全件</button>
    <button onclick="filterAN('pending')" id="an-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="an-filter-btn">pending</button>
    <button onclick="filterAN('CRITICAL')" id="an-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="an-filter-btn">CRITICAL</button>
    <button onclick="filterAN('HIGH')" id="an-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="an-filter-btn">HIGH</button>
    <button onclick="filterAN('MEDIUM')" id="an-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="an-filter-btn">MEDIUM</button>
    <button onclick="filterAN('LOW')" id="an-btn-LOW" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="an-filter-btn">LOW</button>
  </div>
  {an_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="an-table" style="min-width:1050px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">reserve_score</th>
        <th style="text-align:center">reserve_label</th>
        <th>proposed_action</th>
        <th style="text-align:center">patch_target_lane</th>
        <th style="text-align:center">APPLY_READY</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="an-tbody">{an_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ✅ reserve_order=1 のみ commit → ceo_config_patch_plan_queue に append-only 再投入。write_scope=queue_only / execution_blocked=true。config本体未変更。
  </div>
  <script>
  function filterAN(label) {{
    document.querySelectorAll('.an-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('an-btn-'+label).style.opacity='1';
    document.querySelectorAll('#an-tbody .an-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === 'pending' ? '' : 'none'; return; }}
      row.style.display = row.dataset.label === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAO: apply解放ゲート ───
    _AO_COLOR = {"HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    ao_recs     = ceo_reinject_apply_gate
    ao_pending  = [r for r in ao_recs if r.get("gate_status") == "pending"]
    ao_blocked  = [r for r in ao_recs if r.get("gate_status") == "blocked"]
    ao_sorted   = sorted(ao_pending, key=lambda r: -float(r.get("priority_score", 0)))
    ao_top1     = ao_sorted[0] if ao_sorted else {}

    if ao_top1:
        ao_top1_lbl = ao_top1.get("priority", "LOW")
        ao_top1_c   = _AO_COLOR.get(ao_top1_lbl, "#64748b")
        ao_top1_agent = ao_top1.get("target_agent", "—")
        ao_top1_after = (ao_top1.get("after_value", "") or "")[:100].replace("<", "&lt;")
        ao_top1_card_html = f"""<div style="background:linear-gradient(135deg,{ao_top1_c}18,#0d1117);border:1px solid {ao_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{ao_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{ao_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{ao_top1_agent}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{ao_top1_c}">score {ao_top1.get('priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{ao_top1_after}</div>
      <div style="font-size:0.68rem;color:#f59e0b">🛡 → apply_ready_queue 昇格待ち</div>
    </div>"""
    else:
        ao_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">apply解放ゲート待ちなし</div>'

    ao_rows = ""
    for gr in ao_sorted[:30]:
        gpri    = gr.get("priority", "LOW")
        gpri_c  = _AO_COLOR.get(gpri, "#64748b")
        ft      = gr.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = gr.get("target_agent", "—")
        gscore  = gr.get("priority_score", 0.0)
        gstatus = gr.get("gate_status", "pending")
        gpassed = gr.get("gate_passed", False)
        after_v = (gr.get("after_value", "") or "")[:60].replace("<", "&lt;")
        ppath   = gr.get("patch_path", "")
        checks  = gr.get("gate_checks", {})
        chk_str = " ".join("✅" if v else "❌" for v in checks.values())
        dup_key_ao = gr.get("duplicate_key", "")
        is_ar = dup_key_ao in apply_ready_dup_keys
        ar_badge = '<span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🚦 READY</span>' if is_ar else '<span style="color:#374151;font-size:0.65rem">—</span>'
        ao_rows += f"""<tr class="ao-row" data-priority="{gpri}" data-status="{gstatus}">
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{gpri_c}">{gscore:.3f}</td>
          <td style="text-align:center"><span style="background:{gpri_c}22;border:1px solid {gpri_c}55;color:{gpri_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{gpri}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{after_v}</td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="text-align:center;font-size:0.68rem;letter-spacing:2px">{chk_str}</td>
          <td style="text-align:center">{ar_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#{'22c55e' if gstatus=='pending' else '374151'}">{gstatus}</td>
        </tr>"""
    if not ao_rows:
        ao_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">apply解放ゲート待ちなし（ceo_config_patch_plan_queue から自動生成されます）</td></tr>'

    ceo_apply_gate_section_html = f"""<div class="section" id="ceo-reinject-apply-gate">
  <div class="section-title">
    <span class="section-title-icon">🛡</span>
    AO. apply解放ゲート — queue_only 安全確認
    <span style="margin-left:auto;font-size:0.72rem;color:#f59e0b">pending {len(ao_pending)}件 / blocked {len(ao_blocked)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(ao_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(ao_blocked)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ao_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAO('all')" id="ao-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ao-filter-btn">全件</button>
    <button onclick="filterAO('pending')" id="ao-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ao-filter-btn">pending</button>
    <button onclick="filterAO('blocked')" id="ao-btn-blocked" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ao-filter-btn">blocked</button>
    <button onclick="filterAO('HIGH')" id="ao-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ao-filter-btn">HIGH</button>
    <button onclick="filterAO('MEDIUM')" id="ao-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ao-filter-btn">MEDIUM</button>
  </div>
  {ao_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="ao-table" style="min-width:1000px">
      <thead><tr>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">priority_score</th>
        <th style="text-align:center">priority</th>
        <th>after_value</th>
        <th style="text-align:center">patch_path</th>
        <th style="text-align:center">gate_checks(6)</th>
        <th style="text-align:center">APPLY_READY</th>
        <th style="text-align:center">gate_status</th>
      </tr></thead>
      <tbody id="ao-tbody">{ao_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🛡 source=reinject_commit の patch_plan レコードを6条件チェック。config本体未変更。execution_blocked=true / write_scope=queue_only。
  </div>
  <script>
  function filterAO(label) {{
    document.querySelectorAll('.ao-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('ao-btn-'+label).style.opacity='1';
    document.querySelectorAll('#ao-tbody .ao-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending' || label === 'blocked') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      row.style.display = row.dataset.priority === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAP: apply候補レーン ───
    _AP_COLOR = {"HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    ap_recs    = ceo_reinject_apply_ready
    ap_pending = [r for r in ap_recs if r.get("apply_ready_status") == "pending"]
    ap_high    = [r for r in ap_pending if r.get("priority") == "HIGH"]
    ap_medium  = [r for r in ap_pending if r.get("priority") == "MEDIUM"]
    ap_sorted  = sorted(ap_pending, key=lambda r: -float(r.get("priority_score", 0)))
    ap_top1    = ap_sorted[0] if ap_sorted else {}

    if ap_top1:
        ap_top1_lbl = ap_top1.get("priority", "MEDIUM")
        ap_top1_c   = _AP_COLOR.get(ap_top1_lbl, "#64748b")
        ap_top1_agent = ap_top1.get("target_agent", "—")
        ap_top1_after = (ap_top1.get("after_value", "") or "")[:100].replace("<", "&lt;")
        ap_top1_card_html = f"""<div style="background:linear-gradient(135deg,{ap_top1_c}18,#0d1117);border:1px solid {ap_top1_c}55;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{ap_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{ap_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{ap_top1_agent}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{ap_top1_c}">score {ap_top1.get('priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{ap_top1_after}</div>
      <div style="font-size:0.68rem;color:#f59e0b">🚦 next: {ap_top1.get('next_executor','ceo_config_executor.py')} — {ap_top1.get('next_condition','execution_blocked を false にした時のみ apply 可')}</div>
    </div>"""
    else:
        ap_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">apply候補なし</div>'

    ap_rows = ""
    for pr in ap_sorted[:30]:
        ppri    = pr.get("priority", "MEDIUM")
        ppri_c  = _AP_COLOR.get(ppri, "#64748b")
        ft      = pr.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = pr.get("target_agent", "—")
        pscore  = pr.get("priority_score", 0.0)
        pstatus = pr.get("apply_ready_status", "pending")
        after_v = (pr.get("after_value", "") or "")[:60].replace("<", "&lt;")
        ppath   = pr.get("patch_path", "")
        nexec   = pr.get("next_executor", "ceo_config_executor.py")
        dup_key_ap = pr.get("duplicate_key", "")
        is_uc = dup_key_ap in unlock_candidate_dup_keys
        uc_badge = '<span style="background:#a855f722;border:1px solid #a855f755;color:#a855f7;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🔓 UNLOCK_CANDIDATE</span>' if is_uc else '<span style="color:#374151;font-size:0.65rem">—</span>'
        ap_rows += f"""<tr class="ap-row" data-priority="{ppri}" data-status="{pstatus}">
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{ppri_c}">{pscore:.3f}</td>
          <td style="text-align:center"><span style="background:{ppri_c}22;border:1px solid {ppri_c}55;color:{ppri_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{ppri}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{after_v}</td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="font-size:0.65rem;color:#f59e0b">{nexec}</td>
          <td style="text-align:center"><span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🔒 BLOCKED</span></td>
          <td style="text-align:center">{uc_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#374151">{pstatus}</td>
        </tr>"""
    if not ap_rows:
        ap_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">apply候補なし（apply_gate_queue から自動生成されます）</td></tr>'

    ceo_apply_ready_section_html = f"""<div class="section" id="ceo-reinject-apply-ready">
  <div class="section-title">
    <span class="section-title-icon">🚦</span>
    AP. apply候補レーン — execution_blocked 解除前
    <span style="margin-left:auto;font-size:0.72rem;color:#f59e0b">pending {len(ap_pending)}件 HIGH {len(ap_high)}件 MEDIUM {len(ap_medium)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(ap_pending)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH {len(ap_high)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 MEDIUM {len(ap_medium)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔒 execution_blocked=true</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ap_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAP('all')" id="ap-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ap-filter-btn">全件</button>
    <button onclick="filterAP('pending')" id="ap-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ap-filter-btn">pending</button>
    <button onclick="filterAP('HIGH')" id="ap-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ap-filter-btn">HIGH</button>
    <button onclick="filterAP('MEDIUM')" id="ap-btn-MEDIUM" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ap-filter-btn">MEDIUM</button>
  </div>
  {ap_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="ap-table" style="min-width:1100px">
      <thead><tr>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">priority_score</th>
        <th style="text-align:center">priority</th>
        <th>after_value</th>
        <th style="text-align:center">patch_path</th>
        <th style="text-align:center">next_executor</th>
        <th style="text-align:center">execution_blocked</th>
        <th style="text-align:center">UNLOCK候補</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="ap-tbody">{ap_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🚦 apply候補。execution_blocked=true の間は apply 不可。config本体未変更。write_scope=queue_only。next_executor=ceo_config_executor.py 宣言のみ。
  </div>
  <script>
  function filterAP(label) {{
    document.querySelectorAll('.ap-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('ap-btn-'+label).style.opacity='1';
    document.querySelectorAll('#ap-tbody .ap-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      row.style.display = row.dataset.priority === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAQ: 最終解放候補レーン ───
    _AQ_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    aq_recs     = ceo_reinject_unlock_candidate
    aq_pending  = [r for r in aq_recs if r.get("unlock_candidate_status") == "pending"]
    aq_critical = [r for r in aq_pending if r.get("priority") == "CRITICAL"]
    aq_high     = [r for r in aq_pending if r.get("priority") == "HIGH"]
    aq_history  = load_jsonl_safe("logs/ceo_reinject_apply_unlock_candidate_history.jsonl")
    aq_blocked  = [r for r in aq_history if (r.get("status") or "").startswith("blocked_")]
    aq_sorted   = sorted(aq_pending, key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
    aq_top1     = aq_sorted[0] if aq_sorted else {}

    if aq_top1:
        aq_top1_pri   = aq_top1.get("priority", "HIGH")
        aq_top1_c     = _AQ_COLOR.get(aq_top1_pri, "#64748b")
        aq_top1_agent = aq_top1.get("target_agent", "—")
        aq_top1_path  = aq_top1.get("patch_path", "—")
        aq_top1_after = (aq_top1.get("after_value", "") or "")[:100].replace("<", "&lt;")
        aq_top1_card_html = f"""<div style="background:linear-gradient(135deg,{aq_top1_c}18,#0d1117);border:2px solid {aq_top1_c}88;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{aq_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{aq_top1_pri}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{aq_top1_agent}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{aq_top1_c}">score {aq_top1.get('priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{aq_top1_after}</div>
      <div style="font-size:0.68rem;color:#a855f7">🔓 patch_path: {aq_top1_path}</div>
      <div style="font-size:0.68rem;color:#f59e0b;margin-top:4px">次にやること: execution_blocked を false にした時のみ {aq_top1.get('next_executor','ceo_config_executor.py')} が apply 実行可</div>
    </div>"""
    else:
        aq_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">最終解放候補なし</div>'

    aq_rows = ""
    for i, qr in enumerate(aq_sorted[:30], 1):
        qpri    = qr.get("priority", "HIGH")
        qpri_c  = _AQ_COLOR.get(qpri, "#64748b")
        ft      = qr.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = qr.get("target_agent", "—")
        qscore  = qr.get("priority_score", 0.0)
        qstatus = qr.get("unlock_candidate_status", "pending")
        after_v = (qr.get("after_value", "") or "")[:60].replace("<", "&lt;")
        ppath   = qr.get("patch_path", "")
        nexec   = qr.get("next_executor", "ceo_config_executor.py")
        wscope  = qr.get("write_scope", "queue_only")
        dup_key_aq = qr.get("duplicate_key", "")
        is_judged  = dup_key_aq in unlock_judge_dup_keys
        judged_badge = '<span style="background:#10b98122;border:1px solid #10b98155;color:#10b981;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">⚖️ JUDGED</span>' if is_judged else '<span style="color:#374151;font-size:0.65rem">—</span>'
        aq_rows += f"""<tr class="aq-row" data-priority="{qpri}" data-status="{qstatus}">
          <td style="text-align:center;font-weight:900;color:{qpri_c}">{i}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#a855f7">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{qpri_c}">{qscore:.3f}</td>
          <td style="text-align:center"><span style="background:{qpri_c}22;border:1px solid {qpri_c}55;color:{qpri_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{qpri}</span></td>
          <td style="font-size:0.62rem;color:#94a3b8;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{after_v}</td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="font-size:0.65rem;color:#f59e0b">{nexec}</td>
          <td style="text-align:center"><span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🔒 true</span></td>
          <td style="text-align:center;font-size:0.65rem;color:#374151">{wscope}</td>
          <td style="text-align:center">{judged_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#{'a855f7' if qstatus=='pending' else '374151'}">{qstatus}</td>
        </tr>"""
    if not aq_rows:
        aq_rows = '<tr><td colspan="12" style="color:#64748b;text-align:center;padding:16px">最終解放候補なし（apply_ready_queue から自動生成されます）</td></tr>'

    ceo_apply_unlock_section_html = f"""<div class="section" id="ceo-reinject-apply-unlock">
  <div class="section-title">
    <span class="section-title-icon">🔓</span>
    AQ. 最終解放候補 — execution_blocked 解除直前
    <span style="margin-left:auto;font-size:0.72rem;color:#a855f7">pending {len(aq_pending)}件 CRITICAL {len(aq_critical)}件 HIGH {len(aq_high)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(aq_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 CRITICAL {len(aq_critical)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH {len(aq_high)}件</span>
    <span style="background:#64748b22;border:1px solid #64748b55;color:#64748b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(aq_blocked)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔒 execution_blocked=true</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(aq_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAQ('all')" id="aq-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="aq-filter-btn">全件</button>
    <button onclick="filterAQ('CRITICAL')" id="aq-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="aq-filter-btn">CRITICAL</button>
    <button onclick="filterAQ('HIGH')" id="aq-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="aq-filter-btn">HIGH</button>
    <button onclick="filterAQ('pending')" id="aq-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="aq-filter-btn">pending</button>
  </div>
  {aq_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="aq-table" style="min-width:1200px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">priority_score</th>
        <th style="text-align:center">priority</th>
        <th>after_value</th>
        <th style="text-align:center">patch_path</th>
        <th style="text-align:center">next_executor</th>
        <th style="text-align:center">execution_blocked</th>
        <th style="text-align:center">write_scope</th>
        <th style="text-align:center">JUDGED</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="aq-tbody">{aq_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔓 最終解放候補。execution_blocked=true のまま可視化専用。config本体未変更。write_scope=queue_only。解放するならこの1件から。
  </div>
  <script>
  function filterAQ(label) {{
    document.querySelectorAll('.aq-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('aq-btn-'+label).style.opacity='1';
    document.querySelectorAll('#aq-tbody .aq-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      row.style.display = row.dataset.priority === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAR: 最終解放判定 ───
    _AR_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    ar_recs     = ceo_reinject_unlock_judge
    ar_pending  = [r for r in ar_recs if r.get("judge_status") == "pending"]
    ar_critical = [r for r in ar_pending if r.get("priority") == "CRITICAL"]
    ar_high     = [r for r in ar_pending if r.get("priority") == "HIGH"]
    ar_history  = load_jsonl_safe("logs/ceo_reinject_unlock_judge_history.jsonl")
    ar_blocked  = [r for r in ar_history if (r.get("status") or "").startswith("blocked_")]
    ar_sorted   = sorted(ar_pending, key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
    ar_top1     = ar_sorted[0] if ar_sorted else {}

    if ar_top1:
        ar_top1_pri    = ar_top1.get("priority", "HIGH")
        ar_top1_c      = _AR_COLOR.get(ar_top1_pri, "#64748b")
        ar_top1_agent  = ar_top1.get("target_agent", "—")
        ar_top1_path   = ar_top1.get("patch_path", "—")
        ar_top1_after  = (ar_top1.get("after_value", "") or "")[:100].replace("<", "&lt;")
        ar_top1_result = ar_top1.get("judge_result", "unlockable_if_unblocked")
        ar_top1_reason = (ar_top1.get("judge_reason", "") or "")[:120].replace("<", "&lt;")
        ar_top1_card_html = f"""<div style="background:linear-gradient(135deg,{ar_top1_c}18,#0d1117);border:2px solid {ar_top1_c}cc;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{ar_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{ar_top1_pri}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{ar_top1_agent}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{ar_top1_c}">score {ar_top1.get('priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{ar_top1_after}</div>
      <div style="font-size:0.68rem;color:#10b981;margin-bottom:2px">⚖️ judge_result: {ar_top1_result}</div>
      <div style="font-size:0.68rem;color:#6366f1;margin-bottom:2px">patch_path: {ar_top1_path}</div>
      <div style="font-size:0.67rem;color:#374151;margin-top:4px">次にやること: execution_blocked を false に変更すれば {ar_top1.get('next_executor','ceo_config_executor.py')} が apply 実行可 — 今回はまだ実行しない</div>
    </div>"""
    else:
        ar_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">最終解放判定済みレコードなし</div>'

    ar_rows = ""
    for i, jr in enumerate(ar_sorted[:30], 1):
        jpri    = jr.get("priority", "HIGH")
        jpri_c  = _AR_COLOR.get(jpri, "#64748b")
        ft      = jr.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = jr.get("target_agent", "—")
        jscore  = jr.get("priority_score", 0.0)
        jstatus = jr.get("judge_status", "pending")
        jresult = jr.get("judge_result", "unlockable_if_unblocked")
        ppath   = jr.get("patch_path", "")
        nexec   = jr.get("next_executor", "ceo_config_executor.py")
        wscope  = jr.get("write_scope", "queue_only")
        dup_key_ar = jr.get("duplicate_key", "")
        is_unlock_exec = dup_key_ar in unlock_exec_dup_keys
        unlock_exec_badge = '<span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🔓 EXEC待ち</span>' if is_unlock_exec else '<span style="color:#374151;font-size:0.65rem">—</span>'
        ar_rows += f"""<tr class="ar-row" data-priority="{jpri}" data-status="{jstatus}">
          <td style="text-align:center;font-weight:900;color:{jpri_c}">{i}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#10b981">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{jpri_c}">{jscore:.3f}</td>
          <td style="text-align:center"><span style="background:{jpri_c}22;border:1px solid {jpri_c}55;color:{jpri_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{jpri}</span></td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="font-size:0.65rem;color:#f59e0b">{nexec}</td>
          <td style="text-align:center"><span style="background:#10b98122;border:1px solid #10b98155;color:#10b981;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">{jresult}</span></td>
          <td style="text-align:center"><span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">🔒 true</span></td>
          <td style="text-align:center;font-size:0.65rem;color:#374151">{wscope}</td>
          <td style="text-align:center">{unlock_exec_badge}</td>
          <td style="text-align:center;font-size:0.68rem;color:#{'10b981' if jstatus=='pending' else '374151'}">{jstatus}</td>
        </tr>"""
    if not ar_rows:
        ar_rows = '<tr><td colspan="12" style="color:#64748b;text-align:center;padding:16px">最終解放判定済みレコードなし（unlock_candidate_queue から自動生成されます）</td></tr>'

    ceo_unlock_judge_section_html = f"""<div class="section" id="ceo-reinject-unlock-judge">
  <div class="section-title">
    <span class="section-title-icon">⚖️</span>
    AR. 最終解放判定 — unblock 前の最終判断
    <span style="margin-left:auto;font-size:0.72rem;color:#10b981">pending {len(ar_pending)}件 CRITICAL {len(ar_critical)}件 HIGH {len(ar_high)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(ar_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 CRITICAL {len(ar_critical)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟠 HIGH {len(ar_high)}件</span>
    <span style="background:#64748b22;border:1px solid #64748b55;color:#64748b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(ar_blocked)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔒 execution_blocked=true</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ar_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAR('all')" id="ar-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ar-filter-btn">全件</button>
    <button onclick="filterAR('CRITICAL')" id="ar-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ar-filter-btn">CRITICAL</button>
    <button onclick="filterAR('HIGH')" id="ar-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ar-filter-btn">HIGH</button>
    <button onclick="filterAR('pending')" id="ar-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ar-filter-btn">pending</button>
    <button onclick="filterAR('blocked_history')" id="ar-btn-blocked" style="background:#64748b22;color:#64748b;border:1px solid #64748b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="ar-filter-btn">blocked履歴 {len(ar_blocked)}件</button>
  </div>
  {ar_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="ar-table" style="min-width:1200px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">priority_score</th>
        <th style="text-align:center">priority</th>
        <th style="text-align:center">patch_path</th>
        <th style="text-align:center">next_executor</th>
        <th style="text-align:center">judge_result</th>
        <th style="text-align:center">execution_blocked</th>
        <th style="text-align:center">write_scope</th>
        <th style="text-align:center">UNLOCK_EXEC</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="ar-tbody">{ar_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ⚖️ 再投入パート終端。全件 judge_result=unlockable_if_unblocked。execution_blocked=true のまま可視化専用。config本体未変更。unlock / apply 実行は別パートで実装。
  </div>
  <script>
  function filterAR(label) {{
    document.querySelectorAll('.ar-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('ar-btn-'+label).style.opacity='1';
    document.querySelectorAll('#ar-tbody .ar-row').forEach(row => {{
      if (label === 'all' || label === 'blocked_history') {{ row.style.display = label === 'all' ? '' : 'none'; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      row.style.display = row.dataset.priority === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAS: 解放実行待ち ───
    _AS_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    as_recs      = ceo_unlock_execute_queue
    as_pending   = [r for r in as_recs if r.get("unlock_status") == "pending"]
    as_unlocked  = [r for r in as_recs if r.get("unlock_status") == "unlocked"]
    as_sorted    = sorted(as_pending, key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
    as_top1      = as_sorted[0] if as_sorted else (as_unlocked[-1] if as_unlocked else {})

    if as_top1:
        as_top1_lbl   = as_top1.get("priority", "HIGH")
        as_top1_c     = _AS_COLOR.get(as_top1_lbl, "#64748b")
        as_top1_agent = as_top1.get("target_agent", "—")
        as_top1_status = as_top1.get("unlock_status", "pending")
        as_top1_path  = as_top1.get("patch_path", "—")
        as_top1_card_html = f"""<div style="background:linear-gradient(135deg,{as_top1_c}18,#0d1117);border:2px solid {as_top1_c}88;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{as_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{as_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{as_top1_agent}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{as_top1_c}">score {as_top1.get('priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.68rem;color:#6366f1;margin-bottom:2px">patch_path: {as_top1_path}</div>
      <div style="font-size:0.68rem;color:#f97316">unlock_status: {as_top1_status} / unlock_action: {as_top1.get('unlock_action','set_execution_blocked_false_candidate')}</div>
      <div style="font-size:0.67rem;color:#374151;margin-top:4px">※ unlock するには: python3 lib/ceo_unlock_executor.py unlock &lt;duplicate_key&gt;</div>
    </div>"""
    else:
        as_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">解放実行待ちなし</div>'

    as_rows = ""
    for i, ur in enumerate(sorted(as_recs, key=lambda r: (-float(r.get("priority_score",0)), r.get("target_agent",""))), 1):
        upri    = ur.get("priority", "HIGH")
        upri_c  = _AS_COLOR.get(upri, "#64748b")
        ft      = ur.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = ur.get("target_agent", "—")
        uscore  = ur.get("priority_score", 0.0)
        ustatus = ur.get("unlock_status", "pending")
        ppath   = ur.get("patch_path", "")
        akey    = ur.get("agent_key", "")
        actual  = "✅ true" if ur.get("actual_unlocked") else "⏳ false"
        ucolor  = "#22c55e" if ustatus == "unlocked" else ("#818cf8" if ustatus == "pending" else "#374151")
        as_rows += f"""<tr class="as-row" data-priority="{upri}" data-status="{ustatus}">
          <td style="text-align:center;font-weight:900;color:{upri_c}">{i}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#f97316">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{upri_c}">{uscore:.3f}</td>
          <td style="text-align:center"><span style="background:{upri_c}22;border:1px solid {upri_c}55;color:{upri_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{upri}</span></td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="font-size:0.60rem;color:#94a3b8">{akey}</td>
          <td style="text-align:center;font-size:0.68rem;font-weight:700;color:#{'22c55e' if 'true' in actual else '#f59e0b'}">{actual}</td>
          <td style="text-align:center;font-size:0.68rem;color:{ucolor};font-weight:700">{ustatus}</td>
        </tr>"""
    if not as_rows:
        as_rows = '<tr><td colspan="9" style="color:#64748b;text-align:center;padding:16px">解放実行待ちなし（unlock_judge_queue から自動生成されます）</td></tr>'

    ceo_unlock_execute_section_html = f"""<div class="section" id="ceo-unlock-execute">
  <div class="section-title">
    <span class="section-title-icon">🔓</span>
    AS. 解放実行待ち — 明示 unlock で actual_unlocked=true に変更
    <span style="margin-left:auto;font-size:0.72rem;color:#f97316">pending {len(as_pending)}件 / unlocked {len(as_unlocked)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⏳ pending {len(as_pending)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ unlocked {len(as_unlocked)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(as_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAS('all')" id="as-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="as-filter-btn">全件</button>
    <button onclick="filterAS('pending')" id="as-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="as-filter-btn">pending</button>
    <button onclick="filterAS('unlocked')" id="as-btn-unlocked" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="as-filter-btn">unlocked</button>
    <button onclick="filterAS('HIGH')" id="as-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="as-filter-btn">HIGH</button>
    <button onclick="filterAS('CRITICAL')" id="as-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="as-filter-btn">CRITICAL</button>
  </div>
  {as_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="as-table" style="min-width:1000px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">priority_score</th>
        <th style="text-align:center">priority</th>
        <th style="text-align:center">patch_path</th>
        <th style="text-align:center">agent_key</th>
        <th style="text-align:center">actual_unlocked</th>
        <th style="text-align:center">unlock_status</th>
      </tr></thead>
      <tbody id="as-tbody">{as_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔓 unlock_judge_queue から自動昇格。actual_unlocked は明示実行まで false。unlock: python3 lib/ceo_unlock_executor.py unlock &lt;duplicate_key&gt;
  </div>
  <script>
  function filterAS(label) {{
    document.querySelectorAll('.as-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('as-btn-'+label).style.opacity='1';
    document.querySelectorAll('#as-tbody .as-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending' || label === 'unlocked') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      row.style.display = row.dataset.priority === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAT: apply実行待ち ───
    _AT_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}
    at_recs    = ceo_apply_execute_queue
    at_pending = [r for r in at_recs if r.get("apply_execute_status") == "pending"]
    at_sorted  = sorted(at_pending, key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
    at_top1    = at_sorted[0] if at_sorted else {}

    if at_top1:
        at_top1_lbl   = at_top1.get("priority", "HIGH")
        at_top1_c     = _AT_COLOR.get(at_top1_lbl, "#64748b")
        at_top1_agent = at_top1.get("target_agent", "—")
        at_top1_path  = at_top1.get("patch_path", "—")
        at_top1_after = (at_top1.get("after_value", "") or "")[:100].replace("<", "&lt;")
        at_top1_card_html = f"""<div style="background:linear-gradient(135deg,{at_top1_c}18,#0d1117);border:2px solid {at_top1_c}cc;border-radius:10px;padding:14px 18px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{at_top1_c};color:#fff;padding:2px 10px;border-radius:4px;font-size:0.75rem;font-weight:900">{at_top1_lbl}</span>
        <span style="font-weight:800;color:#e2e8f0;font-size:0.9rem">{at_top1_agent}</span>
        <span style="margin-left:auto;font-size:0.85rem;font-weight:900;color:{at_top1_c}">score {at_top1.get('priority_score',0):.3f}</span>
      </div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-bottom:4px">{at_top1_after}</div>
      <div style="font-size:0.68rem;color:#6366f1;margin-bottom:2px">patch_path: {at_top1_path}</div>
      <div style="font-size:0.67rem;color:#374151;margin-top:4px">apply 実行: python3 lib/ceo_unlock_executor.py apply</div>
    </div>"""
    else:
        at_top1_card_html = '<div style="color:#374151;font-size:0.72rem;padding:10px">apply実行待ちなし（unlock 実行後に自動昇格されます）</div>'

    at_rows = ""
    for i, ar_r in enumerate(at_sorted[:30], 1):
        apri    = ar_r.get("priority", "HIGH")
        apri_c  = _AT_COLOR.get(apri, "#64748b")
        ft      = ar_r.get("feedback_type", "")
        ft_c    = _FB_COLOR.get(ft, "#64748b")
        ta      = ar_r.get("target_agent", "—")
        ascore  = ar_r.get("priority_score", 0.0)
        astatus = ar_r.get("apply_execute_status", "pending")
        after_v = (ar_r.get("after_value", "") or "")[:60].replace("<", "&lt;")
        ppath   = ar_r.get("patch_path", "")
        akey    = ar_r.get("agent_key", "")
        tconf   = ar_r.get("target_config", "config/agent_directives.json")
        at_rows += f"""<tr class="at-row" data-priority="{apri}" data-status="{astatus}">
          <td style="text-align:center;font-weight:900;color:{apri_c}">{i}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#22c55e">{ta}</td>
          <td style="text-align:center"><span style="background:{ft_c}22;border:1px solid {ft_c}55;color:{ft_c};padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{ft}</span></td>
          <td style="text-align:center;font-weight:900;color:{apri_c}">{ascore:.3f}</td>
          <td style="text-align:center"><span style="background:{apri_c}22;border:1px solid {apri_c}55;color:{apri_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:900">{apri}</span></td>
          <td style="font-size:0.60rem;color:#94a3b8;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{after_v}</td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="font-size:0.60rem;color:#94a3b8">{akey}</td>
          <td style="font-size:0.60rem;color:#22c55e">{tconf}</td>
          <td style="text-align:center;font-size:0.68rem;color:#22c55e;font-weight:700">{astatus}</td>
        </tr>"""
    if not at_rows:
        at_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">apply実行待ちなし（unlock 実行後に自動昇格されます）</td></tr>'

    ceo_apply_execute_section_html = f"""<div class="section" id="ceo-apply-execute">
  <div class="section-title">
    <span class="section-title-icon">📝</span>
    AT. apply実行待ち — unlock済み候補の config 書き込み待ち
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">pending {len(at_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(at_pending)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">📝 write_scope=config_single_key</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(at_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAT('all')" id="at-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="at-filter-btn">全件</button>
    <button onclick="filterAT('pending')" id="at-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="at-filter-btn">pending</button>
    <button onclick="filterAT('HIGH')" id="at-btn-HIGH" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="at-filter-btn">HIGH</button>
    <button onclick="filterAT('CRITICAL')" id="at-btn-CRITICAL" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="at-filter-btn">CRITICAL</button>
  </div>
  {at_top1_card_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="at-table" style="min-width:1050px">
      <thead><tr>
        <th style="text-align:center">順位</th>
        <th>対象AI</th>
        <th style="text-align:center">feedback_type</th>
        <th style="text-align:center">priority_score</th>
        <th style="text-align:center">priority</th>
        <th>after_value</th>
        <th style="text-align:center">patch_path</th>
        <th style="text-align:center">agent_key</th>
        <th style="text-align:center">target_config</th>
        <th style="text-align:center">状態</th>
      </tr></thead>
      <tbody id="at-tbody">{at_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📝 apply 実行: python3 lib/ceo_unlock_executor.py apply — unlock済み候補のみ config_single_key スコープで config/agent_directives.json に書き込む
  </div>
  <script>
  function filterAT(label) {{
    document.querySelectorAll('.at-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('at-btn-'+label).style.opacity='1';
    document.querySelectorAll('#at-tbody .at-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      if (label === 'pending') {{ row.style.display = row.dataset.status === label ? '' : 'none'; return; }}
      row.style.display = row.dataset.priority === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクションAU: apply実行結果 ───
    au_recs    = ceo_apply_execute_result
    au_applied = [r for r in au_recs if r.get("result_status") == "applied"]
    au_failed  = [r for r in au_recs if r.get("result_status") == "failed"]
    au_blocked = [r for r in au_recs if r.get("result_status") == "blocked"]
    au_sorted  = list(reversed(au_recs))[:30]

    au_rows = ""
    for rr in au_sorted:
        rstatus = rr.get("result_status", "—")
        rstatus_c = {"applied": "#22c55e", "failed": "#ef4444", "blocked": "#f97316", "skipped_duplicate": "#374151"}.get(rstatus, "#64748b")
        ta      = rr.get("target_agent", "—")
        ppath   = rr.get("patch_path", "")
        akey    = rr.get("agent_key", "")
        before  = (rr.get("before_value", "") or "")[:40].replace("<", "&lt;")
        after_v = (rr.get("after_value", "") or "")[:40].replace("<", "&lt;")
        bkup    = rr.get("backup_path", "—")
        diff    = rr.get("diff_path", "—")
        chash   = rr.get("config_hash", "—")
        reason  = (rr.get("result_reason", "") or "")[:50].replace("<", "&lt;")
        ts      = rr.get("applied_at", "—")
        au_rows += f"""<tr class="au-row" data-status="{rstatus}">
          <td style="font-size:0.7rem;color:#374151">{ts}</td>
          <td style="font-size:0.8rem;font-weight:700;color:#{'22c55e' if rstatus=='applied' else '#ef4444'}">{ta}</td>
          <td style="font-size:0.60rem;color:#6366f1">{ppath}</td>
          <td style="font-size:0.60rem;color:#94a3b8;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{before}</td>
          <td style="font-size:0.60rem;color:#22c55e;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{after_v}</td>
          <td style="font-size:0.58rem;color:#374151">{bkup}</td>
          <td style="font-size:0.58rem;color:#374151">{diff}</td>
          <td style="font-size:0.60rem;color:#94a3b8">{chash}</td>
          <td style="font-size:0.62rem;color:#94a3b8">{reason}</td>
          <td style="text-align:center"><span style="background:{rstatus_c}22;border:1px solid {rstatus_c}55;color:{rstatus_c};padding:2px 6px;border-radius:4px;font-size:0.65rem;font-weight:800">{rstatus}</span></td>
        </tr>"""
    if not au_rows:
        au_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">apply実行結果なし（apply 実行後に記録されます）</td></tr>'

    ceo_apply_result_exec_section_html = f"""<div class="section" id="ceo-apply-execute-result">
  <div class="section-title">
    <span class="section-title-icon">✅</span>
    AU. apply実行結果 — config/agent_directives.json 変更ログ
    <span style="margin-left:auto;font-size:0.72rem;color:#22c55e">applied {len(au_applied)}件 / failed {len(au_failed)}件 / blocked {len(au_blocked)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ applied {len(au_applied)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">❌ failed {len(au_failed)}件</span>
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(au_blocked)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(au_recs)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterAU('all')" id="au-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="au-filter-btn">全件</button>
    <button onclick="filterAU('applied')" id="au-btn-applied" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="au-filter-btn">applied</button>
    <button onclick="filterAU('failed')" id="au-btn-failed" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="au-filter-btn">failed</button>
    <button onclick="filterAU('blocked')" id="au-btn-blocked" style="background:#f9731622;color:#f97316;border:1px solid #f9731655;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="au-filter-btn">blocked</button>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" id="au-table" style="min-width:1200px">
      <thead><tr>
        <th>applied_at</th>
        <th>対象AI</th>
        <th style="text-align:center">patch_path</th>
        <th>before</th>
        <th>after</th>
        <th style="text-align:center">backup_path</th>
        <th style="text-align:center">diff_path</th>
        <th style="text-align:center">config_hash</th>
        <th>result_reason</th>
        <th style="text-align:center">status</th>
      </tr></thead>
      <tbody id="au-tbody">{au_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ✅ config/agent_directives.json 変更ログ。backup / diff はそれぞれ backups/ diffs/ に保存済み。rollback: python3 lib/ceo_config_executor.py rollback &lt;target_agent&gt;
  </div>
  <script>
  function filterAU(label) {{
    document.querySelectorAll('.au-filter-btn').forEach(b => b.style.opacity='0.5');
    document.getElementById('au-btn-'+label).style.opacity='1';
    document.querySelectorAll('#au-tbody .au-row').forEach(row => {{
      if (label === 'all') {{ row.style.display=''; return; }}
      row.style.display = row.dataset.status === label ? '' : 'none';
    }});
  }}
  </script>
</div>"""

    # ─── セクション BB: 今打つべき1コマンド ───
    _nc_cmd      = summary.get("ceo_next_command", "bash run_agent_monitor.sh")
    _nc_target   = summary.get("ceo_next_target", "—") or "—"
    _nc_reason   = summary.get("ceo_next_reason", "—")
    _nc_priority = summary.get("ceo_next_priority", "LOW")
    _nc_stage    = summary.get("ceo_next_stage", "monitor_only")
    _nc_pcolor   = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#22c55e"}.get(_nc_priority, "#64748b")

    ceo_next_command_section_html = f"""<div class="section" id="ceo-next-command" style="border:3px solid {_nc_pcolor}66;border-radius:14px;padding:20px 24px;background:linear-gradient(135deg,{_nc_pcolor}10,#080c14);margin-bottom:20px">
  <div class="section-title" style="border-bottom-color:{_nc_pcolor}44;margin-bottom:16px">
    <span style="font-size:1.1rem">⚡</span>
    <span style="color:{_nc_pcolor};font-size:0.9rem;font-weight:900">BB. 今打つべき1コマンド</span>
    <span style="margin-left:auto;background:{_nc_pcolor}22;color:{_nc_pcolor};border:1px solid {_nc_pcolor}55;padding:4px 14px;border-radius:20px;font-size:0.78rem;font-weight:900">{_nc_priority}</span>
  </div>
  <div style="font-family:monospace;font-size:0.92rem;color:{_nc_pcolor};background:#0d1117;border:1px solid {_nc_pcolor}44;border-radius:10px;padding:14px 18px;margin-bottom:14px;word-break:break-all;font-weight:700">{_nc_cmd}</div>
  <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:0.78rem">
    <div><span style="color:#64748b">対象:</span> <b style="color:#e2e8f0">{_nc_target}</b></div>
    <div><span style="color:#64748b">stage:</span> <span style="color:#94a3b8">{_nc_stage}</span></div>
    <div style="color:#64748b;max-width:400px">{_nc_reason}</div>
  </div>
</div>"""

    # ─── セクション BC: post-apply judge ───
    bc_keep   = [r for r in ceo_post_apply_judge_queue if r.get("judge_label") == "keep_monitoring"]
    bc_adj    = [r for r in ceo_post_apply_judge_queue if r.get("judge_label") == "re_adjust_minor"]
    bc_roll   = [r for r in ceo_post_apply_judge_queue if r.get("judge_label") == "rollback_recommended"]
    bc_latest = ceo_post_apply_judge_queue[-1] if ceo_post_apply_judge_queue else {}

    bc_rows = ""
    for rr in list(reversed(ceo_post_apply_judge_queue))[:20]:
        lbl = rr.get("judge_label", "—")
        lbl_c = {"keep_monitoring": "#22c55e", "re_adjust_minor": "#f59e0b", "rollback_recommended": "#ef4444"}.get(lbl, "#64748b")
        ta   = rr.get("target_agent", "—")
        delta = float(rr.get("performance_delta", 0))
        reason = (rr.get("judge_reason", "") or "")[:60].replace("<","&lt;")
        ts   = rr.get("judged_at", "—")
        bc_rows += f"""<tr>
          <td style="font-size:0.7rem;color:#374151">{ts}</td>
          <td style="font-weight:700;color:#e2e8f0">{ta}</td>
          <td style="font-size:0.72rem;color:#94a3b8">{delta:+.3f}</td>
          <td style="font-size:0.72rem;color:#94a3b8">{reason}</td>
          <td style="text-align:center"><span style="background:{lbl_c}22;border:1px solid {lbl_c}55;color:{lbl_c};padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:800">{lbl}</span></td>
        </tr>"""
    if not bc_rows:
        bc_rows = '<tr><td colspan="5" style="color:#64748b;text-align:center;padding:16px">apply後判定なし（apply実行後に自動分類されます）</td></tr>'

    ceo_post_apply_judge_section_html = f"""<div class="section" id="ceo-post-apply-judge">
  <div class="section-title">
    <span class="section-title-icon">🔍</span>
    BC. apply後判定 — keep / re-adjust / rollback 自動分類
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">全{len(ceo_post_apply_judge_queue)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ keep {len(bc_keep)}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔧 re-adjust {len(bc_adj)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">↩️ rollback推奨 {len(bc_roll)}件</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr><th>judged_at</th><th>対象AI</th><th>delta</th><th>理由</th><th>判定</th></tr></thead>
      <tbody>{bc_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔍 判定: improved+hard_fail低下→keep / no_change→re-adjust / degraded・fail増加→rollback推奨
  </div>
</div>"""

    # ─── セクション BD: rollback dispatch / watch ───
    bd_dispatch = [r for r in ceo_rollback_dispatch_queue if r.get("router_status") == "pending"]
    bd_watch    = [r for r in ceo_rollback_watch_queue    if r.get("router_status") == "pending"]
    bd_top_d    = bd_dispatch[-1] if bd_dispatch else {}
    bd_top_w    = bd_watch[-1]    if bd_watch    else {}

    def _rb_row(rr: dict, color: str) -> str:
        ta   = rr.get("target_agent", "—")
        cmd  = rr.get("rollback_command", "—")
        rsn  = (rr.get("route_reason", "") or "")[:60].replace("<","&lt;")
        ts   = rr.get("routed_at", "—")
        delta = float(rr.get("performance_delta", 0))
        return f"""<tr>
          <td style="font-size:0.7rem;color:#374151">{ts}</td>
          <td style="font-weight:700;color:{color}">{ta}</td>
          <td style="font-size:0.72rem;color:#94a3b8">{delta:+.3f}</td>
          <td style="font-size:0.68rem;color:#94a3b8">{rsn}</td>
          <td style="font-family:monospace;font-size:0.65rem;color:{color}">{cmd}</td>
        </tr>"""

    bd_d_rows = "".join(_rb_row(r, "#ef4444") for r in list(reversed(bd_dispatch))[:10]) or \
        '<tr><td colspan="5" style="color:#64748b;text-align:center;padding:10px">dispatch候補なし</td></tr>'
    bd_w_rows = "".join(_rb_row(r, "#f59e0b") for r in list(reversed(bd_watch))[:10]) or \
        '<tr><td colspan="5" style="color:#64748b;text-align:center;padding:10px">watch候補なし</td></tr>'

    ceo_rollback_router_section_html = f"""<div class="section" id="ceo-rollback-router">
  <div class="section-title">
    <span class="section-title-icon">🚦</span>
    BD. rollback振り分け — dispatch（即時確認）/ watch（様子見）
    <span style="margin-left:auto;font-size:0.72rem;color:#ef4444">dispatch {len(bd_dispatch)}件</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div>
      <div style="font-size:0.72rem;font-weight:700;color:#ef4444;margin-bottom:8px">🔴 rollback_dispatch（即時確認）{len(bd_dispatch)}件</div>
      {"" if not bd_top_d else f'<div style="background:#ef444410;border:1px solid #ef444444;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:0.72rem"><b style=\"color:#ef4444\">{bd_top_d.get("target_agent","—")}</b><br><code style=\"font-size:0.65rem;color:#ef4444\">{bd_top_d.get("rollback_command","—")}</code></div>'}
      <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:8px">
        <table class="data-table" style="min-width:400px"><thead><tr><th>日時</th><th>対象</th><th>delta</th><th>理由</th><th>command</th></tr></thead><tbody>{bd_d_rows}</tbody></table>
      </div>
    </div>
    <div>
      <div style="font-size:0.72rem;font-weight:700;color:#f59e0b;margin-bottom:8px">🟡 rollback_watch（様子見）{len(bd_watch)}件</div>
      {"" if not bd_top_w else f'<div style="background:#f59e0b10;border:1px solid #f59e0b44;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:0.72rem"><b style=\"color:#f59e0b\">{bd_top_w.get("target_agent","—")}</b><br><span style=\"font-size:0.65rem;color:#94a3b8\">{bd_top_w.get("route_reason","—")}</span></div>'}
      <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:8px">
        <table class="data-table" style="min-width:400px"><thead><tr><th>日時</th><th>対象</th><th>delta</th><th>理由</th><th>command</th></tr></thead><tbody>{bd_w_rows}</tbody></table>
      </div>
    </div>
  </div>
</div>"""

    # ─── セクション BE: stale cleanup plan ───
    be_pending  = [r for r in ceo_stale_cleanup_plan_queue if r.get("plan_status") == "pending"]
    be_by_cat: dict = {}
    for r in be_pending:
        cat = r.get("category", "other")
        be_by_cat[cat] = be_by_cat.get(cat, 0) + 1
    be_top = be_pending[-1] if be_pending else {}
    be_cat_badges = "".join(
        f'<span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:2px 8px;border-radius:12px;font-size:0.68rem;margin:2px">{k}: {v}件</span>'
        for k, v in be_by_cat.items()
    ) or '<span style="color:#374151;font-size:0.68rem">なし</span>'
    be_cmd = be_top.get("cleanup_command", "—")
    be_agent = be_top.get("target_agent", "—")

    ceo_stale_cleanup_section_html = f"""<div class="section" id="ceo-stale-cleanup">
  <div class="section-title">
    <span class="section-title-icon">🧹</span>
    BE. stale cleanup計画 — 種類別整理提案
    <span style="margin-left:auto;font-size:0.72rem;color:#f59e0b">pending {len(be_pending)}件</span>
  </div>
  <div style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:4px">{be_cat_badges}</div>
  {"" if not be_top else f'<div style="background:#f59e0b10;border:1px solid #f59e0b44;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:0.75rem"><b style=\"color:#f59e0b\">最新 cleanup対象:</b> {be_agent}<br><code style=\"font-size:0.68rem;color:#f59e0b\">{be_cmd}</code></div>'}
  <div style="font-size:0.68rem;color:#374151;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧹 cleanup は自動実行しない。上記コマンドを手動確認後に実行すること。
  </div>
</div>"""

    # ─── セクション BF: lifecycle trace ───
    bf_traces  = lifecycle_traces[:20] if lifecycle_traces else []
    bf_top3    = bf_traces[:3]

    def _trace_row(t: dict, i: int) -> str:
        medal_str = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, "")
        agent   = t.get("agent", "—")
        lane_ct = t.get("lane_count", 0)
        last_ln = t.get("latest_lane", "—")
        last_st = t.get("latest_status", "—")
        summary_str = t.get("lane_summary", "")
        dup_key = (t.get("duplicate_key", "") or "")[:50]
        return f"""<tr>
          <td>{medal_str}</td>
          <td style="font-weight:700;color:#e2e8f0">{agent}</td>
          <td style="text-align:center;color:#818cf8">{lane_ct}</td>
          <td style="font-size:0.70rem;color:#22c55e">{last_ln}</td>
          <td style="font-size:0.65rem;color:#64748b">{last_st}</td>
          <td style="font-size:0.65rem;color:#374151;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{summary_str}</td>
        </tr>"""

    bf_rows = "".join(_trace_row(t, i) for i, t in enumerate(bf_traces)) or \
        '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:16px">トレースデータなし（agent_monitor 実行後に生成されます）</td></tr>'

    ceo_lifecycle_trace_section_html = f"""<div class="section" id="ceo-lifecycle-trace">
  <div class="section-title">
    <span class="section-title-icon">🗺️</span>
    BF. ライフサイクルトレース — duplicate_key の到達レーン一覧
    <span style="margin-left:auto;font-size:0.72rem;color:#818cf8">{len(bf_traces)}件</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr><th></th><th>agent</th><th style="text-align:center">到達レーン数</th><th>最終レーン</th><th>最終status</th><th>レーン経路（末尾5）</th></tr></thead>
      <tbody>{bf_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🗺️ improvement から rollback_dispatch/watch までの全レーンを追跡。最大20件表示。
  </div>
</div>"""

    # ─── セクション BG: safety invariants ───
    bg_violations = [r for r in ceo_invariant_violation_queue if r.get("violation_status") == "pending"]
    bg_by_rule: dict = {}
    for r in bg_violations:
        rule = r.get("rule", "unknown")
        bg_by_rule[rule] = bg_by_rule.get(rule, 0) + 1
    bg_top     = bg_violations[-1] if bg_violations else {}
    bg_critical = len(bg_violations) > 0
    bg_color   = "#ef4444" if bg_critical else "#22c55e"

    bg_rows = ""
    for rr in list(reversed(bg_violations))[:15]:
        rule   = rr.get("rule", "—")
        ta     = rr.get("target_agent", "—")
        detail = (rr.get("detail", "") or "")[:80].replace("<","&lt;")
        qname  = rr.get("queue_name", "—")
        ts     = rr.get("detected_at", "—")
        bg_rows += f"""<tr>
          <td style="font-size:0.7rem;color:#374151">{ts}</td>
          <td style="font-weight:700;color:#ef4444">{ta}</td>
          <td style="font-size:0.72rem;color:#f97316">{rule}</td>
          <td style="font-size:0.65rem;color:#94a3b8">{qname}</td>
          <td style="font-size:0.65rem;color:#94a3b8">{detail}</td>
        </tr>"""
    if not bg_rows:
        bg_rows = '<tr><td colspan="5" style="color:#22c55e;text-align:center;padding:16px">✅ 不変条件違反なし</td></tr>'

    ceo_safety_invariants_section_html = f"""<div class="section" id="ceo-safety-invariants" style="border:2px solid {bg_color}44;border-radius:12px;padding:16px">
  <div class="section-title" style="border-bottom-color:{bg_color}44">
    <span class="section-title-icon">{'🚨' if bg_critical else '✅'}</span>
    <span style="color:{bg_color}">BG. 安全不変条件 — 逸脱検知</span>
    <span style="margin-left:auto;background:{bg_color}22;color:{bg_color};border:1px solid {bg_color}55;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:900">{"⚠️ 違反 " + str(len(bg_violations)) + "件" if bg_critical else "✅ 正常"}</span>
  </div>
  {"" if not bg_top else f'<div style="background:#ef444410;border:1px solid #ef444444;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:0.75rem"><b style=\"color:#ef4444\">最新違反:</b> rule={bg_top.get("rule","—")} agent={bg_top.get("target_agent","—")}<br><span style=\"color:#94a3b8;font-size:0.68rem\">{(bg_top.get("detail","") or "")[:80]}</span></div>'}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:600px">
      <thead><tr><th>detected_at</th><th>対象AI</th><th>rule</th><th>queue</th><th>detail</th></tr></thead>
      <tbody>{bg_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔐 監視ルール: write_scope不正 / backup_required欠如 / target_config不正 / patch_path不正 / after_value空 / 想定外unblocked
  </div>
</div>"""

    # ─── セクション BN: SAFE_AUTO移行判定 ───
    bn_gate    = ceo_safe_auto_gate_queue[-1] if ceo_safe_auto_gate_queue else {}
    bn_ready   = bn_gate.get("safe_auto_ready", False)
    bn_blocked = bn_gate.get("blocked_reasons", [])
    bn_actions = bn_gate.get("required_actions", [])
    bn_info    = bn_gate.get("informational", [])
    bn_top_cmd = bn_gate.get("top_required_command", "bash run_agent_monitor.sh")
    bn_top_tgt = bn_gate.get("top_required_target", "—")
    bn_conf    = bn_gate.get("confidence", "LOW")
    bn_color   = "#22c55e" if bn_ready else "#ef4444"
    bn_label   = "✅ SAFE_AUTO移行可能" if bn_ready else "🚫 SAFE_AUTO移行ブロック中"

    bn_reason_html = ""
    for r in bn_blocked:
        bn_reason_html += f'<li style="color:#ef4444;font-size:0.72rem;margin:3px 0">{r.replace("<","&lt;")}</li>'
    if not bn_reason_html:
        bn_reason_html = '<li style="color:#22c55e;font-size:0.72rem">ブロック理由なし</li>'

    bn_action_html = ""
    for a in bn_actions[:3]:
        cmd_str = (a.get("command") or "—")[:100].replace("<", "&lt;")
        reason_str = (a.get("reason") or "—")[:80].replace("<", "&lt;")
        bn_action_html += f'<div style="background:#111827;border-left:3px solid #f59e0b;padding:8px 12px;margin:4px 0;border-radius:4px;font-size:0.7rem"><b style="color:#fbbf24">{a.get("action","—")}</b>: <code style="color:#a5f3fc">{cmd_str}</code><br><span style="color:#64748b">{reason_str}</span></div>'

    bn_info_html = "".join(f'<span style="background:#1e3a5f;color:#60a5fa;padding:2px 8px;border-radius:8px;font-size:0.68rem;margin:2px">{i}</span>' for i in bn_info)

    ceo_safe_auto_gate_section_html = f"""<div class="section" id="ceo-safe-auto-gate" style="border:3px solid {bn_color}66;border-radius:14px;padding:18px 24px;background:linear-gradient(135deg,{bn_color}08,#080c14);margin-bottom:12px">
  <div class="section-title" style="border-bottom-color:{bn_color}44">
    <span class="section-title-icon">{'✅' if bn_ready else '🚫'}</span>
    <span style="color:{bn_color};font-weight:900">BN. SAFE_AUTO移行判定 — 今入ってよいか</span>
    <span style="margin-left:auto;background:{bn_color}22;color:{bn_color};border:1px solid {bn_color}55;padding:4px 14px;border-radius:20px;font-size:0.8rem;font-weight:900">{bn_label}</span>
  </div>
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin:12px 0">
    <div style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 16px;min-width:120px;text-align:center">
      <div style="font-size:0.65rem;color:#64748b">ブロック理由数</div>
      <div style="font-size:1.8rem;font-weight:900;color:{bn_color}">{len(bn_blocked)}</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 16px;min-width:120px;text-align:center">
      <div style="font-size:0.65rem;color:#64748b">confidence</div>
      <div style="font-size:1.1rem;font-weight:900;color:#fbbf24">{bn_conf}</div>
    </div>
    <div style="flex:1;min-width:200px;background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 14px">
      <div style="font-size:0.65rem;color:#64748b;margin-bottom:4px">ブロック理由</div>
      <ul style="margin:0;padding-left:16px">{bn_reason_html}</ul>
    </div>
  </div>
  {f'<div style="background:#fbbf2410;border:1px solid #fbbf2444;border-radius:8px;padding:10px;margin-bottom:10px"><b style="color:#fbbf24;font-size:0.75rem">▶ 次に打つコマンド:</b><br><code style="color:#a5f3fc;font-size:0.78rem">{bn_top_cmd[:160].replace("<","&lt;")}</code><br><span style="color:#94a3b8;font-size:0.65rem">対象: {bn_top_tgt}</span></div>' if bn_blocked else '<div style="background:#22c55e10;border:1px solid #22c55e44;border-radius:8px;padding:10px;margin-bottom:10px;color:#22c55e;font-size:0.78rem;font-weight:900">✅ 全条件クリア — SAFE_AUTOへの移行が可能です</div>'}
  {f'<div style="margin-top:8px">{bn_action_html}</div>' if bn_action_html else ''}
  {f'<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">{bn_info_html}</div>' if bn_info_html else ''}
</div>"""

    # ─── セクション BO: stale解消候補 ───
    bo_pending = [r for r in ceo_stale_resolution_queue if r.get("resolution_status") == "pending"]
    bo_high    = [r for r in bo_pending if r.get("resolve_priority") == "HIGH"]
    bo_top     = bo_high[0] if bo_high else (bo_pending[0] if bo_pending else {})
    by_action  = {}
    for r in bo_pending:
        act = r.get("resolve_action", "unknown")
        by_action[act] = by_action.get(act, 0) + 1

    bo_rows = ""
    for rr in list(reversed(bo_pending))[:10]:
        ta    = rr.get("target_agent", "—")
        stype = rr.get("stale_type", "—")
        action= rr.get("resolve_action", "—")
        prio  = rr.get("resolve_priority", "—")
        sm    = rr.get("stale_minutes", 0)
        cmd   = (rr.get("suggested_command") or "—")[:100].replace("<", "&lt;")
        pc    = "#ef4444" if prio == "HIGH" else ("#f59e0b" if prio == "MEDIUM" else "#64748b")
        bo_rows += f"""<tr>
          <td style="font-weight:800;color:#818cf8">{ta}</td>
          <td style="font-size:0.7rem;color:#94a3b8">{stype}</td>
          <td style="font-size:0.72rem;color:#fbbf24">{action}</td>
          <td><span style="color:{pc};font-weight:700;font-size:0.7rem">{prio}</span></td>
          <td style="font-size:0.65rem;color:#64748b;text-align:right">{sm:.1f}分</td>
          <td style="font-size:0.62rem;color:#a5f3fc;font-family:monospace">{cmd}</td>
        </tr>"""
    if not bo_rows:
        bo_rows = '<tr><td colspan="6" style="color:#22c55e;text-align:center;padding:14px">✅ stale解消候補なし</td></tr>'

    ceo_stale_resolver_section_html = f"""<div class="section" id="ceo-stale-resolver">
  <div class="section-title">
    <span class="section-title-icon">🧹</span>
    <span>BO. stale解消候補 — 何を先に片付けるか</span>
    <span style="margin-left:auto;background:#7f1d1d22;color:#f87171;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:900">HIGH:{len(bo_high)}件 全:{len(bo_pending)}件</span>
  </div>
  {f'<div style="background:#ef444410;border:1px solid #ef444444;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:0.75rem"><b style="color:#f87171">最優先stale:</b> {bo_top.get("target_agent","—")} ({bo_top.get("stale_type","—")})<br><code style="color:#a5f3fc;font-size:0.72rem">{(bo_top.get("suggested_command") or "—")[:120].replace("<","&lt;")}</code></div>' if bo_top else ''}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr><th>対象AI</th><th>stale種別</th><th>解消アクション</th><th>優先度</th><th>放置時間</th><th>推奨コマンド</th></tr></thead>
      <tbody>{bo_rows}</tbody>
    </table>
  </div>
</div>"""

    # ─── セクション BP: 今打つべき unlock 1件 ───
    bp_top1  = next((r for r in reversed(ceo_unlock_pick_queue)
                     if r.get("is_top") and r.get("pick_status") in ("active","pending")), {})
    bp_all   = [r for r in ceo_unlock_pick_queue if r.get("pick_status") in ("active","pending")]
    bp_color = "#818cf8" if bp_top1 else "#64748b"

    ceo_unlock_pick_section_html = f"""<div class="section" id="ceo-unlock-pick" style="border:2px solid {bp_color}44;border-radius:12px;padding:16px">
  <div class="section-title" style="border-bottom-color:{bp_color}44">
    <span class="section-title-icon">🎯</span>
    <span style="color:{bp_color}">BP. 今打つべき unlock 1件 — stale解消後のnext action</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">候補 {len(bp_all)}件</span>
  </div>
  {f'''<div style="background:#818cf810;border:1px solid #818cf844;border-radius:10px;padding:14px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <div>
        <div style="font-size:0.65rem;color:#64748b">対象AI</div>
        <div style="font-size:1.1rem;font-weight:900;color:#818cf8">{bp_top1.get("target_agent","—")}</div>
      </div>
      <div>
        <div style="font-size:0.65rem;color:#64748b">priority</div>
        <div style="font-size:0.9rem;font-weight:900;color:#fbbf24">{bp_top1.get("priority","—")}</div>
      </div>
      <div>
        <div style="font-size:0.65rem;color:#64748b">pick_score</div>
        <div style="font-size:0.9rem;color:#60a5fa">{bp_top1.get("pick_score",0):.2f}</div>
      </div>
      <div>
        <div style="font-size:0.65rem;color:#64748b">売上直結</div>
        <div style="font-size:0.9rem">{"✅" if bp_top1.get("is_revenue") else "—"}</div>
      </div>
    </div>
    <div style="margin-top:10px;background:#080c14;border-radius:6px;padding:10px;font-family:monospace;font-size:0.75rem;color:#a5f3fc;word-break:break-all">{(bp_top1.get("command") or "—")[:200].replace("<","&lt;")}</div>
    <div style="margin-top:8px;font-size:0.68rem;color:#94a3b8"><b style="color:#fbbf24">なぜ今:</b> {(bp_top1.get("why_now") or "—")[:120].replace("<","&lt;")}</div>
    <div style="margin-top:4px;font-size:0.68rem;color:#94a3b8"><b style="color:#6ee7b7">打つと:</b> {(bp_top1.get("expected_effect") or "—")[:120].replace("<","&lt;")}</div>
    <div style="margin-top:4px;font-size:0.65rem;color:#f87171;font-family:monospace"><b>rollback:</b> {(bp_top1.get("rollback_command") or "—")[:100].replace("<","&lt;")}</div>
  </div>''' if bp_top1 else '<div style="color:#64748b;padding:14px;text-align:center">unlock候補なし（stale解消後に再実行で候補が表示されます）</div>'}
</div>"""

    # ─── セクション BQ: モード移行チェックリスト ───
    bq_rec    = ceo_mode_transition_queue[-1] if ceo_mode_transition_queue else {}
    bq_items  = bq_rec.get("check_items", [])
    bq_green  = bq_rec.get("all_green", False)
    bq_status = bq_rec.get("transition_status", "blocked")
    bq_next   = bq_rec.get("next_command", "bash run_agent_monitor.sh")
    bq_reason = bq_rec.get("next_reason", "—")
    bq_failed = bq_rec.get("failed_count", 0)
    bq_color  = "#22c55e" if bq_green else "#f59e0b"

    bq_item_html = ""
    for item in bq_items:
        ok      = item.get("ok", False)
        name    = item.get("name", "—").replace("<", "&lt;")
        current = item.get("current", "—")
        fix     = (item.get("fix") or "")[:100].replace("<", "&lt;")
        icolor  = "#22c55e" if ok else "#ef4444"
        icon    = "✅" if ok else "❌"
        bq_item_html += f"""<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 12px;background:#111827;border-left:3px solid {icolor};border-radius:4px;margin:4px 0">
          <span style="font-size:1rem;flex-shrink:0">{icon}</span>
          <div style="flex:1">
            <div style="font-size:0.75rem;color:#f1f5f9;font-weight:600">{name}</div>
            <div style="font-size:0.65rem;color:#64748b">現在: {current}</div>
            {f'<div style="font-size:0.63rem;color:#fbbf24;font-family:monospace;margin-top:2px">fix: {fix}</div>' if fix else ''}
          </div>
        </div>"""
    if not bq_item_html:
        bq_item_html = '<div style="color:#64748b;padding:10px">チェックリスト未生成</div>'

    ceo_mode_transition_section_html = f"""<div class="section" id="ceo-mode-transition" style="border:2px solid {bq_color}55;border-radius:12px;padding:16px">
  <div class="section-title" style="border-bottom-color:{bq_color}44">
    <span class="section-title-icon">🚦</span>
    <span style="color:{bq_color}">BQ. MANUAL→SAFE_AUTO 移行チェックリスト</span>
    <span style="margin-left:auto;background:{bq_color}22;color:{bq_color};border:1px solid {bq_color}44;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:900">{'✅ 全クリア' if bq_green else f'❌ {bq_failed}項目未クリア'}</span>
  </div>
  {bq_item_html}
  <div style="background:#0d1117;border-radius:8px;padding:10px 14px;margin-top:10px">
    <div style="font-size:0.65rem;color:#64748b;margin-bottom:4px">{'SAFE_AUTO切替コマンド:' if bq_green else '次にやること:'}</div>
    <code style="color:#a5f3fc;font-size:0.73rem;word-break:break-all">{bq_next[:200].replace('<','&lt;')}</code>
    <div style="font-size:0.65rem;color:#94a3b8;margin-top:4px">{bq_reason[:100].replace('<','&lt;')}</div>
  </div>
</div>"""

    # ─── セクション BL: 実行モード ───
    import json as _rjson
    from pathlib import Path as _RPath
    _rmode_path = _RPath("config/runtime_mode.json")
    try:
        _rmode = _rjson.loads(_rmode_path.read_text(encoding="utf-8")) if _rmode_path.exists() else {}
    except Exception:
        _rmode = {}
    bl_mode    = _rmode.get("mode", "MANUAL")
    bl_unlock  = bool(_rmode.get("auto_unlock", False))
    bl_apply   = bool(_rmode.get("auto_apply", False))
    bl_rollback= bool(_rmode.get("auto_rollback", False))

    MODE_COLOR = {"MANUAL": "#64748b", "SAFE_AUTO": "#f59e0b", "FULL_AUTO": "#22c55e"}
    MODE_LABEL = {"MANUAL": "🔒 MANUAL（手動のみ）", "SAFE_AUTO": "🔑 SAFE_AUTO（条件付き自動）",
                  "FULL_AUTO": "🤖 FULL_AUTO（完全自動）"}
    bl_color   = MODE_COLOR.get(bl_mode, "#64748b")
    bl_label   = MODE_LABEL.get(bl_mode, bl_mode)

    def _flag(v: bool) -> str:
        return '<span style="color:#22c55e;font-weight:900">ON</span>' if v else '<span style="color:#ef4444;font-weight:900">OFF</span>'

    ceo_runtime_mode_section_html = f"""<div class="section" id="ceo-runtime-mode" style="border:3px solid {bl_color}66;border-radius:14px;padding:18px 24px;background:linear-gradient(135deg,{bl_color}10,#080c14);margin-bottom:12px">
  <div class="section-title" style="border-bottom-color:{bl_color}44">
    <span class="section-title-icon">⚙️</span>
    <span style="color:{bl_color};font-weight:900">BL. 実行モード — 自動実行スイッチ</span>
    <span style="margin-left:auto;background:{bl_color}33;color:{bl_color};border:1px solid {bl_color}66;padding:4px 16px;border-radius:20px;font-size:0.82rem;font-weight:900">{bl_label}</span>
  </div>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin:14px 0">
    <div style="flex:1;min-width:160px;background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px">auto_unlock</div>
      <div style="font-size:1.4rem">{_flag(bl_unlock)}</div>
      <div style="font-size:0.65rem;color:#64748b;margin-top:4px">{'HIGH以上のみ自動unlock' if bl_mode=='SAFE_AUTO' else ('全優先度自動unlock' if bl_mode=='FULL_AUTO' else '手動のみ')}</div>
    </div>
    <div style="flex:1;min-width:160px;background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px">auto_apply</div>
      <div style="font-size:1.4rem">{_flag(bl_apply)}</div>
      <div style="font-size:0.65rem;color:#64748b;margin-top:4px">{'SAFE_AUTO: 永久禁止' if bl_mode=='SAFE_AUTO' else ('全安全ガード通過後のみ' if bl_mode=='FULL_AUTO' else '手動のみ')}</div>
    </div>
    <div style="flex:1;min-width:160px;background:#111827;border:1px solid #1e293b;border-radius:10px;padding:14px;text-align:center">
      <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px">auto_rollback</div>
      <div style="font-size:1.4rem">{_flag(bl_rollback)}</div>
      <div style="font-size:0.65rem;color:#64748b;margin-top:4px">{'rollback_dispatch優先実行' if bl_rollback else '手動のみ'}</div>
    </div>
  </div>
  <div style="font-size:0.7rem;color:#374151;padding:8px 12px;background:#0d1117;border-radius:6px">
    🔄 モード変更: <code style="color:#a5f3fc">config/runtime_mode.json</code> の <code style="color:#fbbf24">mode</code> を <code>MANUAL</code> / <code>SAFE_AUTO</code> / <code>FULL_AUTO</code> に書き換えてから <code>bash run_agent_monitor.sh</code> を実行
  </div>
</div>"""

    # ─── セクション BM: 自動実行ログ ───
    bm_unlocks  = [r for r in ceo_auto_exec_log_queue if r.get("action_type") == "auto_unlock"
                   and "executed" in (r.get("exec_status") or "")]
    bm_applies  = [r for r in ceo_auto_exec_log_queue if r.get("action_type") == "auto_apply"
                   and "executed" in (r.get("exec_status") or "")]
    bm_rollbacks= [r for r in ceo_auto_rollback_result if r.get("rb_result_status") == "executed"]
    bm_all_logs = list(reversed(ceo_auto_exec_log_queue))[:15]

    bm_rows = ""
    for rr in bm_all_logs:
        ts     = rr.get("logged_at", "—")
        atype  = rr.get("action_type", "—")
        ta     = rr.get("target_agent", "—")
        status = rr.get("exec_status", "—")
        mode_r = rr.get("runtime_mode", "—")
        reason = (rr.get("exec_reason") or "—")[:80].replace("<", "&lt;")
        scolor = "#22c55e" if "executed" in status else ("#ef4444" if status in ("blocked","error") else "#64748b")
        bm_rows += f"""<tr>
          <td style="font-size:0.65rem;color:#374151">{ts}</td>
          <td style="font-size:0.72rem;color:#818cf8">{atype}</td>
          <td style="font-weight:800;color:#818cf8">{ta}</td>
          <td><span style="color:{scolor};font-size:0.72rem;font-weight:700">{status}</span></td>
          <td style="font-size:0.65rem;color:#64748b">{mode_r}</td>
          <td style="font-size:0.62rem;color:#94a3b8">{reason}</td>
        </tr>"""
    if not bm_rows:
        bm_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center;padding:14px">自動実行ログなし（MANUALモードでは生成されません）</td></tr>'

    ceo_auto_exec_log_section_html = f"""<div class="section" id="ceo-auto-exec-log">
  <div class="section-title">
    <span class="section-title-icon">🤖</span>
    <span>BM. 自動実行ログ — auto unlock / apply / rollback 実績</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">unlock:{len(bm_unlocks)} apply:{len(bm_applies)} rollback:{len(bm_rollbacks)}</span>
  </div>
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">
    <div style="background:#1e3a5f22;border:1px solid #3b82f644;border-radius:8px;padding:10px 18px;text-align:center;min-width:100px">
      <div style="font-size:1.4rem;font-weight:900;color:#60a5fa">{len(bm_unlocks)}</div>
      <div style="font-size:0.65rem;color:#64748b">auto_unlock実行</div>
    </div>
    <div style="background:#14532d22;border:1px solid #22c55e44;border-radius:8px;padding:10px 18px;text-align:center;min-width:100px">
      <div style="font-size:1.4rem;font-weight:900;color:#4ade80">{len(bm_applies)}</div>
      <div style="font-size:0.65rem;color:#64748b">auto_apply実行</div>
    </div>
    <div style="background:#7f1d1d22;border:1px solid #ef444444;border-radius:8px;padding:10px 18px;text-align:center;min-width:100px">
      <div style="font-size:1.4rem;font-weight:900;color:#f87171">{len(bm_rollbacks)}</div>
      <div style="font-size:0.65rem;color:#64748b">auto_rollback実行</div>
    </div>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr><th>実行時刻</th><th>種別</th><th>対象AI</th><th>結果</th><th>mode</th><th>理由</th></tr></thead>
      <tbody>{bm_rows}</tbody>
    </table>
  </div>
</div>"""

    # ─── セクション BH: 手動実行前 unlock 説明 ───
    bh_pending  = [r for r in ceo_unlock_explain_queue if r.get("explain_status") == "pending"]
    bh_latest   = bh_pending[-1] if bh_pending else {}
    bh_rows     = ""
    for rr in list(reversed(bh_pending))[:10]:
        ta      = rr.get("target_agent", "—")
        prio    = rr.get("priority", "—")
        cmd     = (rr.get("next_manual_command") or "—")[:120].replace("<", "&lt;")
        rb      = (rr.get("rollback_command") or "—")[:100].replace("<", "&lt;")
        why     = (rr.get("why_now") or "—")[:120].replace("<", "&lt;")
        changes = (rr.get("what_changes") or "—")[:120].replace("<", "&lt;")
        ns      = rr.get("expected_next_stage", "—")
        bh_rows += f"""<tr>
          <td style="font-weight:800;color:#818cf8">{ta}</td>
          <td><span style="background:#1e3a5f;color:#60a5fa;padding:2px 8px;border-radius:8px;font-size:0.7rem">{prio}</span></td>
          <td style="font-size:0.68rem;color:#a5f3fc;font-family:monospace">{cmd}</td>
          <td style="font-size:0.65rem;color:#94a3b8">{why}</td>
          <td style="font-size:0.65rem;color:#6ee7b7">{changes}</td>
          <td style="font-size:0.65rem;color:#fbbf24">{ns}</td>
          <td style="font-size:0.62rem;color:#f87171;font-family:monospace">{rb}</td>
        </tr>"""
    if not bh_rows:
        bh_rows = '<tr><td colspan="7" style="color:#64748b;text-align:center;padding:14px">unlock 実行前説明なし（unlock_execute pending なし）</td></tr>'

    ceo_unlock_explain_section_html = f"""<div class="section" id="ceo-unlock-explain">
  <div class="section-title">
    <span class="section-title-icon">🔓</span>
    <span>BH. unlock前最終説明 — 何を打ち、何が起こり、失敗時は何で戻すか</span>
    <span style="margin-left:auto;background:#1e3a5f;color:#60a5fa;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:900">pending {len(bh_pending)}件</span>
  </div>
  {f'<div style="background:#1e3a5f22;border:1px solid #3b82f644;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:0.75rem"><b style="color:#60a5fa">次に打つコマンド:</b><br><code style="color:#a5f3fc;font-size:0.78rem">{(bh_latest.get("next_manual_command") or "—")[:160].replace("<","&lt;")}</code><br><span style="color:#94a3b8;font-size:0.68rem;margin-top:4px;display:block">理由: {(bh_latest.get("why_now") or "—")[:100].replace("<","&lt;")}</span></div>' if bh_latest else ''}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr><th>対象AI</th><th>優先度</th><th>手動コマンド</th><th>なぜ今</th><th>打つと何が変わるか</th><th>次のstage</th><th>失敗時rollback</th></tr></thead>
      <tbody>{bh_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔐 unlock は自動実行されません。上記コマンドをオーナーが手動で打ってください。
  </div>
</div>"""

    # ─── セクション BI: 手動実行前 apply 説明 ───
    bi_pending  = [r for r in ceo_apply_explain_queue if r.get("explain_status") == "pending"]
    bi_latest   = bi_pending[-1] if bi_pending else {}
    bi_rows     = ""
    for rr in list(reversed(bi_pending))[:10]:
        ta      = rr.get("target_agent", "—")
        pp      = (rr.get("patch_path") or "—")[:60].replace("<", "&lt;")
        av      = (rr.get("after_value") or "—")[:80].replace("<", "&lt;")
        tc      = rr.get("target_config", "—")
        ws      = rr.get("write_scope", "—")
        br_val  = "✅" if rr.get("backup_required") else "❌"
        bp      = (rr.get("backup_path") or "—")[:60].replace("<", "&lt;")
        cmd     = (rr.get("next_manual_command") or "—")[:100].replace("<", "&lt;")
        bi_rows += f"""<tr>
          <td style="font-weight:800;color:#818cf8">{ta}</td>
          <td style="font-size:0.68rem;color:#fbbf24;font-family:monospace">{pp}</td>
          <td style="font-size:0.65rem;color:#6ee7b7;font-family:monospace">{av}</td>
          <td style="font-size:0.65rem;color:#94a3b8">{tc}</td>
          <td style="font-size:0.65rem;color:#64748b">{ws}</td>
          <td style="text-align:center">{br_val}</td>
          <td style="font-size:0.62rem;color:#94a3b8">{bp}</td>
          <td style="font-size:0.65rem;color:#a5f3fc;font-family:monospace">{cmd}</td>
        </tr>"""
    if not bi_rows:
        bi_rows = '<tr><td colspan="8" style="color:#64748b;text-align:center;padding:14px">apply 実行前説明なし（apply_execute pending なし）</td></tr>'

    ceo_apply_explain_section_html = f"""<div class="section" id="ceo-apply-explain">
  <div class="section-title">
    <span class="section-title-icon">📝</span>
    <span>BI. apply前最終説明 — どのキーに何を書き込む予定か</span>
    <span style="margin-left:auto;background:#14532d22;color:#4ade80;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:900">pending {len(bi_pending)}件</span>
  </div>
  {f'<div style="background:#14532d22;border:1px solid #22c55e44;border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:0.75rem"><b style="color:#4ade80">apply対象:</b> {bi_latest.get("target_agent","—")} — patch_path: <code style="color:#fbbf24">{(bi_latest.get("patch_path") or "—")[:60].replace("<","&lt;")}</code><br><code style="color:#6ee7b7;font-size:0.7rem">{(bi_latest.get("after_value") or "—")[:120].replace("<","&lt;")}</code></div>' if bi_latest else ''}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:900px">
      <thead><tr><th>対象AI</th><th>patch_path</th><th>after_value</th><th>target_config</th><th>write_scope</th><th>backup</th><th>backup_path</th><th>apply コマンド</th></tr></thead>
      <tbody>{bi_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    📝 apply は自動実行されません。unlock完了後にオーナーが手動で打ってください。
  </div>
</div>"""

    # ─── セクション BJ: 実行禁止条件一覧 ───
    bj_blocked = [r for r in ceo_final_block_queue if r.get("block_status") == "blocked"]
    bj_ready   = [r for r in ceo_final_block_queue if r.get("block_status") == "ready"]
    bj_rows    = ""
    for rr in list(ceo_final_block_queue)[-20:]:
        ta       = rr.get("target_agent", "—")
        ctype    = rr.get("check_type", "—")
        bstatus  = rr.get("block_status", "—")
        reasons  = rr.get("blocked_reason", [])
        reasons_str = " / ".join(reasons)[:120].replace("<", "&lt;") if reasons else "なし（実行可能）"
        color    = "#ef4444" if bstatus == "blocked" else "#22c55e"
        label    = "🚫 禁止" if bstatus == "blocked" else "✅ 実行可"
        bj_rows += f"""<tr>
          <td style="font-weight:800;color:#818cf8">{ta}</td>
          <td style="font-size:0.7rem;color:#64748b">{ctype}</td>
          <td><span style="color:{color};font-weight:900;font-size:0.75rem">{label}</span></td>
          <td style="font-size:0.65rem;color:{color}">{reasons_str}</td>
          <td style="font-size:0.65rem;color:#64748b;text-align:center">{len(reasons)}</td>
        </tr>"""
    if not bj_rows:
        bj_rows = '<tr><td colspan="5" style="color:#64748b;text-align:center;padding:14px">実行禁止条件チェック対象なし</td></tr>'

    bj_badge_color = "#ef4444" if bj_blocked else "#22c55e"
    bj_badge_text  = f"🚫 禁止 {len(bj_blocked)}件 / ✅ 可 {len(bj_ready)}件"

    ceo_final_block_section_html = f"""<div class="section" id="ceo-final-block" style="border:2px solid {bj_badge_color}44;border-radius:12px;padding:16px">
  <div class="section-title" style="border-bottom-color:{bj_badge_color}44">
    <span class="section-title-icon">🚫</span>
    <span style="color:{bj_badge_color}">BJ. 実行禁止条件一覧 — なぜ今 unlock/apply できないか</span>
    <span style="margin-left:auto;background:{bj_badge_color}22;color:{bj_badge_color};border:1px solid {bj_badge_color}55;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:900">{bj_badge_text}</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:700px">
      <thead><tr><th>対象AI</th><th>種別</th><th>状態</th><th>禁止理由</th><th>理由数</th></tr></thead>
      <tbody>{bj_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔐 監視項目: execution_blocked / write_scope / backup_required / target_config / patch_path / after_value / invariant / stale
  </div>
</div>"""

    # ─── セクション BK: 実行後確認チェックリスト ───
    bk_pending = [r for r in ceo_post_command_checklist if r.get("checklist_status") == "active"]
    bk_latest  = bk_pending[-1] if bk_pending else {}
    bk_items   = bk_latest.get("items", [])
    bk_rows    = ""
    for item in bk_items:
        order  = item.get("order", "—")
        desc   = (item.get("item") or "—").replace("<", "&lt;")
        fname  = (item.get("check_file") or "—")
        field  = (item.get("check_field") or "—")
        expect = (item.get("expected") or "—")
        bk_rows += f"""<tr>
          <td style="font-weight:900;color:#818cf8;text-align:center">{order}</td>
          <td style="font-size:0.72rem;color:#f1f5f9">{desc}</td>
          <td style="font-size:0.65rem;color:#fbbf24;font-family:monospace">{fname}</td>
          <td style="font-size:0.65rem;color:#94a3b8">{field}</td>
          <td style="font-size:0.65rem;color:#6ee7b7">{expect}</td>
        </tr>"""
    if not bk_rows:
        bk_rows = '<tr><td colspan="5" style="color:#64748b;text-align:center;padding:14px">確認チェックリストなし（unlock/apply pending がなければ生成されません）</td></tr>'

    bk_stage = bk_latest.get("stage", "—")
    bk_ta    = bk_latest.get("target_agent", "—")

    ceo_checklist_section_html = f"""<div class="section" id="ceo-post-checklist">
  <div class="section-title">
    <span class="section-title-icon">✅</span>
    <span>BK. 実行後確認チェックリスト — unlock/apply 後に見るべき項目</span>
    <span style="margin-left:auto;background:#1e3a5f;color:#60a5fa;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:900">対象: {bk_ta} / stage: {bk_stage}</span>
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:800px">
      <thead><tr><th style="width:40px">順</th><th>確認項目</th><th>確認ファイル</th><th>確認フィールド</th><th>期待値</th></tr></thead>
      <tbody>{bk_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    ✅ 実行後は上記を順番に確認し、全件クリアを確認してから次フェーズへ進んでください。
  </div>
</div>"""

    # ─── セクションAZ: 本番運用手順 ───
    _op_stage    = summary.get("current_operation_stage", "monitor_only")
    _op_cmd      = summary.get("next_required_command", "bash run_agent_monitor.sh")
    _op_target   = summary.get("next_required_target", "—") or "—"
    _op_rb_cmd   = summary.get("rollback_command", "") or "—"
    _op_reason   = summary.get("operation_block_reason", "—")
    _op_conf     = summary.get("operation_confidence", "LOW")
    _stage_color = {
        "rollback_ready":      "#ef4444",
        "unlock_ready":        "#22c55e",
        "apply_ready":         "#3b82f6",
        "observe_post_apply":  "#f59e0b",
        "monitor_only":        "#64748b",
    }.get(_op_stage, "#64748b")
    _conf_color = {"HIGH": "#22c55e", "MEDIUM": "#f59e0b", "LOW": "#64748b"}.get(_op_conf, "#64748b")
    _stage_icon = {
        "rollback_ready":      "↩️",
        "unlock_ready":        "🔓",
        "apply_ready":         "📝",
        "observe_post_apply":  "👁",
        "monitor_only":        "🧭",
    }.get(_op_stage, "🧭")

    ceo_operation_runbook_section_html = f"""<div class="section" id="ceo-operation-runbook" style="border:2px solid {_stage_color}44;border-radius:14px;padding:20px;background:linear-gradient(135deg,{_stage_color}08,#0d1117)">
  <div class="section-title" style="border-bottom-color:{_stage_color}44">
    <span class="section-title-icon">{_stage_icon}</span>
    <span style="color:{_stage_color}">AZ. 本番運用手順 — unlock/apply/観測/rollback</span>
    <span style="margin-left:auto;font-size:0.72rem;background:{_stage_color}22;color:{_stage_color};border:1px solid {_stage_color}55;padding:3px 12px;border-radius:20px;font-weight:800">{_op_stage}</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">
    <div style="background:#111827;border:1px solid {_stage_color}33;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">現在のステージ</div>
      <div style="font-size:1.4rem;font-weight:900;color:{_stage_color}">{_stage_icon} {_op_stage}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:6px">{_op_reason}</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">次に打つコマンド</div>
      <div style="font-family:monospace;font-size:0.78rem;color:#22c55e;background:#0d1117;padding:8px 10px;border-radius:6px;word-break:break-all">{_op_cmd}</div>
      <div style="font-size:0.70rem;color:#94a3b8;margin-top:6px">対象: <b style="color:#e2e8f0">{_op_target}</b></div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">rollbackコマンド</div>
      <div style="font-family:monospace;font-size:0.75rem;color:#f97316;background:#0d1117;padding:8px 10px;border-radius:6px;word-break:break-all">{_op_rb_cmd}</div>
      <div style="font-size:0.68rem;color:#374151;margin-top:6px">rollback候補ありの場合のみ使用</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">判断信頼度</div>
      <div style="font-size:1.6rem;font-weight:900;color:{_conf_color}">{_op_conf}</div>
      <div style="font-size:0.70rem;color:#94a3b8;margin-top:6px">{_op_reason}</div>
    </div>
  </div>
  <div style="margin-top:14px;padding:10px 14px;background:#0d1117;border-radius:6px;font-size:0.70rem;color:#374151">
    🧭 ステージ定義: unlock_ready → apply_ready → observe_post_apply → rollback_ready → monitor_only<br>
    rollback: <code style="color:#f97316">{_op_rb_cmd}</code>
  </div>
</div>"""

    # ─── セクションBA: Hardening最優先判断 ───
    _ha_issue   = summary.get("hardening_top_issue", "none")
    _ha_prio    = summary.get("hardening_top_priority", "NONE")
    _ha_target  = summary.get("hardening_top_target", "—")
    _ha_action  = summary.get("hardening_required_action", "異常なし")
    _ha_command = summary.get("hardening_required_command", "bash run_agent_monitor.sh")
    _ha_esc     = summary.get("hardening_is_escalated", False)
    _ha_reason  = summary.get("hardening_escalation_reason", "")
    _ha_block   = summary.get("hardening_block_count", 0)
    _ha_attn    = summary.get("hardening_attention_count", 0)
    _ha_color   = {
        "rollback_candidate":      "#ef4444",
        "unlock_expiry_expired":   "#f97316",
        "post_apply_lock":         "#eab308",
        "stale_operation":         "#64748b",
        "none":                    "#1e293b",
    }.get(_ha_issue, "#1e293b")
    _ha_prio_color = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#64748b", "NONE": "#374151"}.get(_ha_prio, "#374151")
    _ha_esc_badge = (
        f'<span style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;padding:3px 10px;border-radius:99px;font-size:0.72rem;font-weight:800">🚨 ESCALATED</span>'
        if _ha_esc else
        f'<span style="background:#1e293b;color:#374151;border:1px solid #374151;padding:3px 10px;border-radius:99px;font-size:0.72rem">通常</span>'
    )

    ceo_hardening_alert_section_html = f"""<div class="section" id="ceo-hardening-alert" style="border:2px solid {_ha_color}55;border-radius:14px;padding:20px;background:linear-gradient(135deg,{_ha_color}0a,#0d1117)">
  <div class="section-title" style="border-bottom-color:{_ha_color}44">
    <span class="section-title-icon">🚨</span>
    <span style="color:{_ha_color if _ha_issue != 'none' else '#64748b'}">BA. Hardening最優先判断</span>
    {_ha_esc_badge}
    <span style="margin-left:auto;font-size:0.72rem;background:{_ha_prio_color}22;color:{_ha_prio_color};border:1px solid {_ha_prio_color}55;padding:3px 10px;border-radius:20px;font-weight:800">{_ha_prio}</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">
    <div style="background:#111827;border:1px solid {_ha_color}33;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">Top Issue</div>
      <div style="font-size:1.2rem;font-weight:900;color:{_ha_color}">{_ha_issue}</div>
      <div style="font-size:0.72rem;color:#94a3b8;margin-top:6px">対象: <b style="color:#e2e8f0">{_ha_target}</b></div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">必要アクション</div>
      <div style="font-size:0.80rem;color:#e2e8f0;font-weight:700">{_ha_action}</div>
      <div style="font-size:0.68rem;color:#374151;margin-top:6px">{_ha_reason}</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">実行コマンド</div>
      <div style="font-family:monospace;font-size:0.75rem;color:{_ha_color if _ha_issue != 'none' else '#22c55e'};background:#0d1117;padding:8px 10px;border-radius:6px;word-break:break-all">{_ha_command}</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:10px;padding:16px">
      <div style="font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px">件数</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:4px">
        <div><span style="font-size:1.4rem;font-weight:900;color:#ef4444">{_ha_block}</span><div style="font-size:0.65rem;color:#64748b">block</div></div>
        <div><span style="font-size:1.4rem;font-weight:900;color:#f59e0b">{_ha_attn}</span><div style="font-size:0.65rem;color:#64748b">attention</div></div>
      </div>
    </div>
  </div>
</div>"""

    # ─── セクションAV: unlock期限管理 ───
    av_expired  = [r for r in ceo_unlock_expiry_queue if r.get("expiry_status") == "expired"]
    av_top      = av_expired[-1] if av_expired else {}
    av_top_agent  = av_top.get("target_agent", "—")
    av_top_key    = (av_top.get("duplicate_key", "") or "")[:60]
    av_top_exp    = av_top.get("unlock_expires_at", "—")
    av_top_at     = av_top.get("detected_at", "—")

    ceo_unlock_expiry_section_html = f"""<div class="section" id="ceo-unlock-expiry">
  <div class="section-title">
    <span class="section-title-icon">⏳</span>
    AV. unlock期限管理 — 有効期限切れ検出
    <span style="margin-left:auto;font-size:0.72rem;color:#f97316">expired {len(av_expired)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#f9731622;border:1px solid #f9731655;color:#f97316;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">⏰ expired {len(av_expired)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_unlock_expiry_queue)}件</span>
  </div>
  {"" if not av_top else f'<div style="background:#f9731610;border:1px solid #f9731644;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.75rem"><span style="color:#f97316;font-weight:700">最新 expired:</span> agent=<b>{av_top_agent}</b> expires_at={av_top_exp} detected={av_top_at}<br><span style="color:#94a3b8;font-size:0.68rem">{av_top_key}</span></div>'}
  <div style="font-size:0.68rem;color:#374151;padding:6px 10px;background:#0d1117;border-radius:4px">
    ⏳ unlock 有効期限 {30} 分。期限切れ後は apply_execute_queue がハードニングブロック。再 unlock が必要: python3 lib/ceo_unlock_executor.py unlock &lt;duplicate_key&gt;
  </div>
</div>"""

    # ─── セクションAW: post-apply再ロック候補 ───
    aw_pending  = [r for r in ceo_post_apply_lock_queue if r.get("status") == "pending"]
    aw_done     = [r for r in ceo_post_apply_lock_queue if r.get("status") == "done"]
    aw_top      = aw_pending[-1] if aw_pending else {}
    aw_top_agent = aw_top.get("target_agent", "—")
    aw_top_key   = (aw_top.get("duplicate_key", "") or "")[:60]
    aw_top_at    = aw_top.get("registered_at", "—")

    ceo_post_apply_lock_section_html = f"""<div class="section" id="ceo-post-apply-lock">
  <div class="section-title">
    <span class="section-title-icon">🔒</span>
    AW. post-apply再ロック候補 — apply後の再 execution_blocked 候補
    <span style="margin-left:auto;font-size:0.72rem;color:#a78bfa">pending {len(aw_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#a78bfa22;border:1px solid #a78bfa55;color:#a78bfa;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔒 pending {len(aw_pending)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ done {len(aw_done)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_post_apply_lock_queue)}件</span>
  </div>
  {"" if not aw_top else f'<div style="background:#a78bfa10;border:1px solid #a78bfa44;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.75rem"><span style="color:#a78bfa;font-weight:700">最新 pending:</span> agent=<b>{aw_top_agent}</b> registered={aw_top_at}<br><span style="color:#94a3b8;font-size:0.68rem">{aw_top_key}</span></div>'}
  <div style="font-size:0.68rem;color:#374151;padding:6px 10px;background:#0d1117;border-radius:4px">
    🔒 apply 完了後に自動登録される再ロック候補。lock_action=restore_execution_blocked_true。実行は手動専用。
  </div>
</div>"""

    # ─── セクションAX: rollback候補 ───
    ax_pending  = [r for r in ceo_rollback_request_queue if r.get("status") == "pending"]
    ax_done     = [r for r in ceo_rollback_request_queue if r.get("status") == "done"]
    ax_top      = ax_pending[-1] if ax_pending else {}
    ax_top_agent = ax_top.get("target_agent", "—")
    ax_reason    = (ax_top.get("reason", "") or "")[:60].replace("<", "&lt;")
    ax_backup    = ax_top.get("backup_path", "—")
    ax_top_at    = ax_top.get("requested_at", "—")

    ceo_rollback_request_section_html = f"""<div class="section" id="ceo-rollback-request">
  <div class="section-title">
    <span class="section-title-icon">↩️</span>
    AX. rollback候補 — apply失敗時の自動 rollback 登録
    <span style="margin-left:auto;font-size:0.72rem;color:#ef4444">pending {len(ax_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">↩️ pending {len(ax_pending)}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">✅ done {len(ax_done)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_rollback_request_queue)}件</span>
  </div>
  {"" if not ax_top else f'<div style="background:#ef444410;border:1px solid #ef444444;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.75rem"><span style="color:#ef4444;font-weight:700">最新 pending:</span> agent=<b>{ax_top_agent}</b> requested={ax_top_at}<br><span style="color:#94a3b8">reason: {ax_reason}</span><br><span style="color:#374151;font-size:0.68rem">backup: {ax_backup}</span></div>'}
  <div style="font-size:0.68rem;color:#374151;padding:6px 10px;background:#0d1117;border-radius:4px">
    ↩️ apply 失敗時に自動登録される rollback 候補。実行: python3 lib/ceo_config_executor.py rollback &lt;target_agent&gt;
  </div>
</div>"""

    # ─── セクションAY: stale operation ───
    ay_pending  = [r for r in ceo_stale_operation_queue if r.get("status") == "pending"]
    ay_by_type: dict = {}
    for r in ay_pending:
        ot = r.get("operation_type", "unknown")
        ay_by_type[ot] = ay_by_type.get(ot, 0) + 1
    ay_top      = ay_pending[-1] if ay_pending else {}
    ay_top_agent = ay_top.get("target_agent", "—")
    ay_top_op    = ay_top.get("operation_type", "—")
    ay_top_min   = ay_top.get("stale_minutes", "—")
    ay_top_at    = ay_top.get("detected_at", "—")
    ay_type_badges = "".join(
        f'<span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:2px 8px;border-radius:12px;font-size:0.68rem;margin:2px">{k}:{v}件</span>'
        for k, v in ay_by_type.items()
    ) or '<span style="color:#374151;font-size:0.68rem">なし</span>'

    ceo_stale_operation_section_html = f"""<div class="section" id="ceo-stale-operation">
  <div class="section-title">
    <span class="section-title-icon">🧹</span>
    AY. stale operation — 放置操作検出
    <span style="margin-left:auto;font-size:0.72rem;color:#f59e0b">pending {len(ay_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🧹 pending {len(ay_pending)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_stale_operation_queue)}件</span>
  </div>
  <div style="margin-bottom:10px;display:flex;flex-wrap:wrap;gap:4px">{ay_type_badges}</div>
  {"" if not ay_top else f'<div style="background:#f59e0b10;border:1px solid #f59e0b44;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:0.75rem"><span style="color:#f59e0b;font-weight:700">最新 stale:</span> agent=<b>{ay_top_agent}</b> op={ay_top_op} stale_min={ay_top_min} detected={ay_top_at}</div>'}
  <div style="font-size:0.68rem;color:#374151;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧹 unlock_pending_stale(60分) / unlock_expired / apply_stale(120分) / rollback_stale(60分) の4パターン検出。手動確認・処理が必要。
  </div>
</div>"""

    ceo_sim_section_html = f"""<div class="section" id="ceo-simulation">
  <div class="section-title">
    <span class="section-title-icon">🧪</span>
    S. 実行シミュレーション — 実行前確認
    <span style="margin-left:auto;font-size:0.72rem;color:#a78bfa">pending {len(sim_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(sim_pending)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🔴 high {sim_high_r}件</span>
    <span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟡 medium {sim_med_r}件</span>
    <span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟢 low {sim_low_r}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_sim_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterSim('all')" id="sim-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="sim-filter-btn">全件</button>
    <button onclick="filterSim('high')" id="sim-btn-high" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="sim-filter-btn">high</button>
    <button onclick="filterSim('medium')" id="sim-btn-medium" style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="sim-filter-btn">medium</button>
    <button onclick="filterSim('low')" id="sim-btn-low" style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e55;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="sim-filter-btn">low</button>
    <button onclick="filterSim('pending')" id="sim-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="sim-filter-btn">pending</button>
  </div>
  {sim_latest_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:1050px">
      <thead><tr>
        <th>シミュ日時</th><th>対象AI</th><th>改善タイプ</th><th>simulation_type</th><th>risk</th><th>target_files</th><th>target_logs</th><th>予測効果</th><th>write_scope</th><th>状態</th><th>順位</th>
      </tr></thead>
      <tbody id="sim-tbody">{sim_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🧪 実行はしない。write_scope=none / execution_blocked=true 固定。ミュウツーCEOの実行前確認専用レーン。
  </div>
</div>
<script>
function filterSim(mode) {{
  document.querySelectorAll('.sim-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('sim-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.sim-row').forEach(function(row) {{
    var risk   = row.getAttribute('data-risk') || '';
    var status = row.getAttribute('data-status') || '';
    var show = false;
    if (mode === 'all')     show = true;
    else if (mode === 'pending') show = status === 'pending';
    else show = risk === mode;
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    # ─── セクションQ: READYレーン（ミュウツーCEO判断済み） ───
    RQ_STATUS_COLOR = {
        "pending":  "#818cf8",
        "archived": "#374151",
        "blocked":  "#ef4444",
    }

    rq_q_recent   = list(reversed(ceo_ready_queue))[:30]
    rq_q_pending  = [r for r in ceo_ready_queue if r.get("status") == "pending"]
    rq_q_archived = [r for r in ceo_ready_queue if r.get("status") == "archived"]
    rq_q_blocked  = [r for r in ceo_ready_queue if r.get("status") == "blocked"]
    rq_q_latest   = rq_q_recent[0] if rq_q_recent else {}

    rq_q_rows = ""
    for rr in rq_q_recent:
        status   = rr.get("status", "pending")
        sc_q     = RQ_STATUS_COLOR.get(status, "#64748b")
        prio     = rr.get("priority", "LOW")
        pc_q     = PRIO_COLOR.get(prio, "#64748b")
        itype    = rr.get("improvement_type", "")
        itl      = IMP_TYPE_LABEL.get(itype, itype or "—")
        itc      = IMP_TYPE_COLOR.get(itype, "#64748b")
        ta       = rr.get("target_agent", "") or "—"
        reason   = rr.get("reason", "")
        proposed = rr.get("proposed_change", "")
        sc_cls   = rr.get("safety_class", "SAFE")
        exec_rec = rr.get("execute_recommended", True)
        promoted_at = rr.get("promoted_at", "")[:16].replace("T", " ")
        row_op_q = "opacity:1" if status == "pending" else "opacity:0.5"
        # EXECUTION_READY昇格済みか
        erq_key  = rr.get("duplicate_key", "")
        er_promoted = erq_key in exec_ready_promoted_keys
        er_badge = (
            '<span style="color:#f59e0b;font-size:0.72rem;font-weight:800">🚀 EXE_READY</span>'
            if er_promoted else
            '<span style="color:#374151;font-size:0.72rem">—</span>'
        )
        rq_q_rows += f"""<tr class="rqq-row" data-status="{status}" data-prio="{prio}" style="{row_op_q}">
          <td style="font-size:0.8rem;font-weight:700;color:#818cf8">{ta}</td>
          <td><span style="background:{itc}22;border:1px solid {itc}55;color:{itc};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700;white-space:nowrap">{itl}</span></td>
          <td><span style="background:{pc_q};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:800">{prio}</span></td>
          <td style="font-size:0.75rem;color:#94a3b8;max-width:160px">{reason[:55]}{'…' if len(reason)>55 else ''}</td>
          <td style="font-size:0.75rem;color:#e2e8f0;max-width:200px">{proposed[:60]}{'…' if len(proposed)>60 else ''}</td>
          <td style="text-align:center"><span style="background:#22c55e22;border:1px solid #22c55e55;color:#22c55e;padding:2px 7px;border-radius:4px;font-size:0.68rem;font-weight:800">{sc_cls}</span></td>
          <td style="text-align:center;font-size:0.8rem">{'✅' if exec_rec else '—'}</td>
          <td style="text-align:center"><span style="background:{sc_q}22;border:1px solid {sc_q}55;color:{sc_q};padding:2px 8px;border-radius:4px;font-size:0.72rem;font-weight:700">{status}</span></td>
          <td style="text-align:center">{er_badge}</td>
          <td style="font-size:0.68rem;color:#374151;white-space:nowrap">{promoted_at}</td>
        </tr>"""
    if not rq_q_rows:
        rq_q_rows = '<tr><td colspan="10" style="color:#64748b;text-align:center;padding:16px">READYキューなし（SAFE候補が積まれると表示されます）</td></tr>'

    rq_q_lc     = PRIO_COLOR.get(rq_q_latest.get("priority","—"), "#64748b")
    rq_q_latest_html = f"""<div style="background:#0d1117;border:1px solid #1e293b;border-left:4px solid #818cf8;border-radius:10px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <span style="background:{rq_q_lc};color:#fff;padding:3px 10px;border-radius:4px;font-size:0.75rem;font-weight:800">{rq_q_latest.get('priority','—')}</span>
    <span style="font-size:0.88rem;font-weight:800;color:#f1f5f9">{IMP_TYPE_LABEL.get(rq_q_latest.get('improvement_type',''), rq_q_latest.get('improvement_type','—'))}</span>
    <span style="font-size:0.82rem;font-weight:700;color:#818cf8">{rq_q_latest.get('target_agent','') or '—'}</span>
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:2px 10px;border-radius:4px;font-size:0.72rem;font-weight:800">{rq_q_latest.get('status','—')}</span>
    <span style="margin-left:auto;font-size:0.68rem;color:#22c55e;font-weight:700">ミュウツーCEO判断済み</span>
  </div>
  <div style="font-size:0.8rem;color:#e2e8f0;line-height:1.7">
    <span style="color:#475569;font-weight:700">🔨 改善案: </span>{(rq_q_latest.get('proposed_change','') or '—')[:150]}
  </div>
</div>""" if rq_q_latest else '<div style="color:#374151;padding:12px;font-size:0.78rem">READYキューなし</div>'

    ceo_review_section_html = f"""<div class="section" id="ceo-ready-lane">
  <div class="section-title">
    <span class="section-title-icon">🟢</span>
    Q. READYレーン — ミュウツーCEO判断済み
    <span style="margin-left:auto;font-size:0.72rem;color:#818cf8">pending {len(rq_q_pending)}件</span>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
    <span style="background:#818cf822;border:1px solid #818cf855;color:#818cf8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🟣 pending {len(rq_q_pending)}件</span>
    <span style="background:#37415122;border:1px solid #37415155;color:#94a3b8;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🗄 archived {len(rq_q_archived)}件</span>
    <span style="background:#ef444422;border:1px solid #ef444455;color:#ef4444;padding:3px 12px;border-radius:20px;font-size:0.72rem;font-weight:700">🚫 blocked {len(rq_q_blocked)}件</span>
    <span style="background:#0d1117;border:1px solid #1e293b;color:#374151;padding:3px 12px;border-radius:20px;font-size:0.72rem">全 {len(ceo_ready_queue)}件</span>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
    <button onclick="filterRQQ('all')" id="rqq-btn-all" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rqq-filter-btn">全件</button>
    <button onclick="filterRQQ('pending')" id="rqq-btn-pending" style="background:#818cf822;color:#818cf8;border:1px solid #818cf855;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rqq-filter-btn">pending</button>
    <button onclick="filterRQQ('archived')" id="rqq-btn-archived" style="background:#37415122;color:#94a3b8;border:1px solid #37415155;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rqq-filter-btn">archived</button>
    <button onclick="filterRQQ('blocked')" id="rqq-btn-blocked" style="background:#ef444422;color:#ef4444;border:1px solid #ef444455;border-radius:6px;padding:4px 12px;font-size:0.72rem;cursor:pointer;font-weight:700" class="rqq-filter-btn">blocked</button>
  </div>
  {rq_q_latest_html}
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
    <table class="data-table" style="min-width:980px">
      <thead><tr>
        <th>対象AI</th><th>改善タイプ</th><th>優先度</th><th>判定根拠</th><th>改善案</th><th>安全クラス</th><th>実行推奨</th><th>状態</th><th>EXE_READY</th><th>昇格日時</th>
      </tr></thead>
      <tbody id="rqq-tbody">{rq_q_rows}</tbody>
    </table>
  </div>
  <div style="font-size:0.68rem;color:#374151;margin-top:8px;padding:6px 10px;background:#0d1117;border-radius:4px">
    🟢 SAFEかつ実行推奨=trueの候補のみ。ミュウツーCEOが自律判断で選別。実行は次フェーズ（未実装）。
  </div>
</div>
<script>
function filterRQQ(mode) {{
  document.querySelectorAll('.rqq-filter-btn').forEach(b => b.style.opacity='0.55');
  var activeBtn = document.getElementById('rqq-btn-' + mode);
  if (activeBtn) activeBtn.style.opacity='1';
  document.querySelectorAll('.rqq-row').forEach(function(row) {{
    var status = row.getAttribute('data-status') || '';
    var show = (mode === 'all') || (status === mode);
    row.style.display = show ? '' : 'none';
  }});
}}
</script>"""

    notif_sections_html = f"""
<!-- ─── セクション G: 通知状況 ─── -->
<div class="section" id="notif">
  <div class="section-title">
    <span class="section-title-icon">🔔</span>
    G. Discord通知状況
    <span style="margin-left:auto;font-size:0.72rem;color:{'#ef4444' if unres_crit>0 else '#64748b'}">
      {'⚠️ CRITICAL未解決 ' + str(unres_crit) + '件' if unres_crit > 0 else '✅ CRITICAL正常'}
    </span>
  </div>
  <div class="kpi-grid">
    {notif_cards}
  </div>
  {fail_reason_card}

  <!-- H: 未解決アラート -->
  <div style="margin-top:20px">
    <div style="font-size:0.82rem;font-weight:700;color:#f59e0b;margin-bottom:10px">
      📬 H. 未解決アラート（pendingキュー）— {len(pending_items)}件
    </div>
    <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
      <table class="data-table" style="min-width:600px">
        <thead><tr>
          <th>重要度</th><th>event_key</th><th>タイトル</th><th>試行</th><th>キュー日時</th><th>最終エラー</th>
        </tr></thead>
        <tbody>{pending_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- I: 通知履歴（フィルタ付き） -->
  <div style="margin-top:20px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
      <span style="font-size:0.82rem;font-weight:700;color:#818cf8">📋 I. 最近の通知履歴（最新20件）</span>
      <button class="collapse-btn" style="margin-left:0" onclick="toggleCollapse('hist-body',this)">▼ 折りたたむ</button>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-left:auto" id="hist-filters">
        <button class="hfilter active" data-filter="all"     onclick="filterHist('all')">全件</button>
        <button class="hfilter" data-filter="CRITICAL"  onclick="filterHist('CRITICAL')">CRITICAL</button>
        <button class="hfilter" data-filter="WARNING"   onclick="filterHist('WARNING')">WARNING</button>
        <button class="hfilter" data-filter="sent"      onclick="filterHist('sent')">sent</button>
        <button class="hfilter" data-filter="fail"      onclick="filterHist('fail')">failed</button>
        <button class="hfilter" data-filter="suppressed" onclick="filterHist('suppressed')">suppressed</button>
      </div>
    </div>
    <div id="hist-body" class="collapsible" style="max-height:3000px">
    <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:10px">
      <table class="data-table" id="hist-table" style="min-width:600px">
        <thead><tr>
          <th>日時</th><th>重要度</th><th>ルール</th><th>タイトル</th><th>結果</th><th>チャンネル</th>
        </tr></thead>
        <tbody>{hist_rows_filtered}</tbody>
      </table>
    </div>
    </div>
  </div>
</div>

<!-- ─── セクション J: AI稼働異常ランキング ─── -->
<div class="section" id="alert-rank">
  <div class="section-title">
    <span class="section-title-icon">🚨</span>
    J. AI稼働異常ランキング — danger複合スコア TOP10
  </div>
  <div style="font-size:0.78rem;color:#64748b;margin-bottom:12px;padding:8px 12px;background:#0f172a;border-radius:6px">
    売上・投稿停止に近い順で並んでいます
  </div>
  <div style="overflow-x:auto;background:#111827;border:1px solid #1e293b;border-radius:12px">
    <table class="data-table" style="min-width:640px">
      <thead><tr>
        <th style="text-align:center">順位</th><th>エージェント名</th><th>役割</th><th>成功率</th><th>主要異常</th><th>状態</th><th>危険スコア</th>
      </tr></thead>
      <tbody>{rank_rows}</tbody>
    </table>
  </div>
</div>

<!-- ─── セクション K: 売上阻害ボトルネック ─── -->
<div class="section" id="revenue-blocker">
  <div class="section-title">
    <span class="section-title-icon">💸</span>
    K. 売上阻害ボトルネック — 優先排除対象
  </div>
  {blocker_html}
</div>

<!-- ─── セクション L: CEO実行命令キュー ─── -->
{ceo_queue_section_html}

<!-- ─── セクション M: CEO命令実行ログ ─── -->
{ceo_exec_section_html}

<!-- ─── セクション N: 安全実行アクション履歴 ─── -->
{ceo_safe_section_html}

<!-- ─── セクション O: CEO改善候補キュー ─── -->
{ceo_improvement_section_html}

<!-- ─── セクション P: 実行準備キュー (SAFEのみ) ─── -->
{ceo_ready_section_html}

<!-- ─── セクション Q: READYレーン ─── -->
{ceo_review_section_html}

<!-- ─── セクション R: 実行候補レーン — ミュウツーCEO判断済み ─── -->
{ceo_exec_ready_section_html}

<!-- ─── セクション S: 実行シミュレーション ─── -->
{ceo_sim_section_html}

<!-- ─── セクション T: 実行優先順位 ─── -->
{ceo_ranked_section_html}

<!-- ─── セクション U: CEO送信パケット ─── -->
{ceo_packet_section_html}

<!-- ─── セクション V: 実行要求パケット ─── -->
{ceo_dispatch_section_html}

<!-- ─── セクション W: CEO実行スタブ ─── -->
{ceo_stub_section_html}

<!-- ─── セクション X: CEOドライラン結果 ─── -->
{ceo_dry_run_section_html}

<!-- ─── セクション Y: CEO最終実行候補 ─── -->
{ceo_candidate_section_html}

<!-- ─── セクション Z: CEO限定実行候補 ─── -->
{ceo_limited_section_html}

<!-- ─── セクション AA: CEO実行ガード結果 ─── -->
{ceo_guard_section_html}

<!-- ─── セクション AB: CEO設定変更計画 ─── -->
{ceo_patch_plan_section_html}

<!-- ─── セクション AC: CEO設定適用待ち ─── -->
{ceo_apply_queue_section_html}

<!-- ─── セクション AD: CEO設定変更結果 ─── -->
{ceo_apply_result_section_html}

<!-- ─── セクション AE: CEO実行結果観測 ─── -->
{ceo_exec_result_section_html}

<!-- ─── セクション AF: CEOパフォーマンス評価 ─── -->
{ceo_perf_eval_section_html}

<!-- ─── セクション AG: CEOフィードバックループ ─── -->
{ceo_feedback_section_html}

<!-- ─── セクション AH: 再投入優先順位 ─── -->
{ceo_reinject_section_html}

<!-- ─── セクション AI: 再投入ディスパッチ ─── -->
{ceo_dispatch_section_html}

<!-- ─── セクション AJ: 限定再投入候補 ─── -->
{ceo_reinject_return_section_html}

<!-- ─── セクション AK: 再投入ゲート判定 ─── -->
{ceo_gate_section_html}

<!-- ─── セクション AL: 再投入パッチ接続候補 ─── -->
{ceo_patch_ready_section_html}

<!-- ─── セクション AM: 再接続予約レーン ─── -->
{ceo_reserve_section_html}

<!-- ─── セクション AN: patch_plan 再投入コミット ─── -->
{ceo_commit_section_html}

<!-- ─── セクション AO: apply解放ゲート ─── -->
{ceo_apply_gate_section_html}

<!-- ─── セクション AP: apply候補レーン ─── -->
{ceo_apply_ready_section_html}

<!-- ─── セクション AQ: 最終解放候補 ─── -->
{ceo_apply_unlock_section_html}

<!-- ─── セクション AR: 最終解放判定 ─── -->
{ceo_unlock_judge_section_html}

<!-- ─── セクション AS: 解放実行待ち ─── -->
{ceo_unlock_execute_section_html}

<!-- ─── セクション AT: apply実行待ち ─── -->
{ceo_apply_execute_section_html}

<!-- ─── セクション AU: apply実行結果 ─── -->
{ceo_apply_result_exec_section_html}

<!-- ─── セクション AV: unlock期限管理 ─── -->
{ceo_unlock_expiry_section_html}

<!-- ─── セクション AW: post-apply再ロック候補 ─── -->
{ceo_post_apply_lock_section_html}

<!-- ─── セクション AX: rollback候補 ─── -->
{ceo_rollback_request_section_html}

<!-- ─── セクション AY: stale operation ─── -->
{ceo_stale_operation_section_html}

<!-- ─── セクション BC: apply後判定 ─── -->
{ceo_post_apply_judge_section_html}

<!-- ─── セクション BD: rollback振り分け ─── -->
{ceo_rollback_router_section_html}

<!-- ─── セクション BE: stale cleanup計画 ─── -->
{ceo_stale_cleanup_section_html}

<!-- ─── セクション BF: ライフサイクルトレース ─── -->
{ceo_lifecycle_trace_section_html}"""

    # ─── セクション BR: 勝ちパターン学習 ───
    import json as _bj
    from pathlib import Path as _bp
    _wp_path = _bp("logs/winning_patterns.jsonl")
    _wp_records = []
    if _wp_path.exists():
        for _line in _wp_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line:
                try: _wp_records.append(_bj.loads(_line))
                except: pass
    _wp_win  = [r for r in _wp_records if r.get("rank") == "WIN"]
    _wp_hold = [r for r in _wp_records if r.get("rank") == "HOLD"]
    _wp_impr = [r for r in _wp_records if r.get("rank") == "IMPROVE"]
    _wp_rew  = [r for r in _wp_records if r.get("rank") == "REWRITE_NOW"]

    _wp_rows = ""
    for r in sorted(_wp_win, key=lambda x: (x.get("thumbnail_score",0) or 0) + (x.get("x_hook_score",0) or 0), reverse=True)[:10]:
        _pid   = r.get("post_id","")
        _ttl   = (r.get("title","") or "")[:30]
        _cat   = r.get("category","—")
        _ts    = r.get("thumbnail_score", 0) or 0
        _xs    = r.get("x_hook_score", 0) or 0
        _elems = "+".join(k.replace("has_","").replace("_word","") for k in ["has_number","has_proper_noun","has_emotion_word","has_contrast"] if r.get(k))
        _wp_rows += f'<tr><td style="color:#a5f3fc">{_pid}</td><td>{_ttl}</td><td style="color:#fbbf24">{_cat}</td><td style="color:#86efac">{_ts}</td><td style="color:#c4b5fd">{_xs}</td><td style="font-size:0.65rem;color:#94a3b8">{_elems}</td></tr>'
    if not _wp_rows:
        _wp_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center">データなし (winning_patterns.jsonl未生成)</td></tr>'

    br_section_html = f"""<div class="section" id="br-winning-patterns" style="border:2px solid #a78bfa55;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#a78bfa44">
    <span class="section-title-icon">🏆</span>
    <span style="color:#a78bfa">BR. 勝ちパターン学習</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">WIN:{len(_wp_win)} HOLD:{len(_wp_hold)} IMPROVE:{len(_wp_impr)} REWRITE:{len(_wp_rew)}</span>
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
    <div style="background:#1e1b4b;border:1px solid #a78bfa44;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#a5f3fc">{len(_wp_win)}</div><div style="font-size:0.65rem;color:#64748b">WIN</div></div>
    <div style="background:#1e1b4b;border:1px solid #fbbf2444;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#fbbf24">{len(_wp_hold)}</div><div style="font-size:0.65rem;color:#64748b">HOLD</div></div>
    <div style="background:#1e1b4b;border:1px solid #fb923c44;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#fb923c">{len(_wp_impr)}</div><div style="font-size:0.65rem;color:#64748b">IMPROVE</div></div>
    <div style="background:#1e1b4b;border:1px solid #ef444444;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#ef4444">{len(_wp_rew)}</div><div style="font-size:0.65rem;color:#64748b">REWRITE_NOW</div></div>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
    <thead><tr style="color:#64748b;border-bottom:1px solid #1e293b"><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">タイトル</th><th style="text-align:left;padding:4px 8px">カテゴリ</th><th style="text-align:center;padding:4px 8px">サムネ</th><th style="text-align:center;padding:4px 8px">Xフック</th><th style="text-align:left;padding:4px 8px">要素</th></tr></thead>
    <tbody>{_wp_rows}</tbody>
  </table>
</div>"""

    # ─── セクション BS: 公開後評価 ───
    _eval_path = _bp("logs/post_publish_evaluations.jsonl")
    _eval_records = []
    if _eval_path.exists():
        for _line in _eval_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line:
                try: _eval_records.append(_bj.loads(_line))
                except: pass
    # 各post_idの最新評価のみ
    _eval_latest = {}
    for r in _eval_records:
        pid = str(r.get("post_id",""))
        if pid not in _eval_latest or (r.get("hours_since_publish",0) or 0) > (_eval_latest[pid].get("hours_since_publish",0) or 0):
            _eval_latest[pid] = r
    _ev_win  = [r for r in _eval_latest.values() if r.get("rank") == "WIN"]
    _ev_hold = [r for r in _eval_latest.values() if r.get("rank") == "HOLD"]
    _ev_impr = [r for r in _eval_latest.values() if r.get("rank") == "IMPROVE"]
    _ev_rew  = [r for r in _eval_latest.values() if r.get("rank") == "REWRITE_NOW"]

    _ev_rows = ""
    _rank_colors = {"WIN":"#22c55e","HOLD":"#fbbf24","IMPROVE":"#fb923c","REWRITE_NOW":"#ef4444"}
    for r in sorted(_eval_latest.values(), key=lambda x: x.get("hours_since_publish",0) or 0, reverse=True)[:15]:
        _rank  = r.get("rank","—")
        _rc    = _rank_colors.get(_rank, "#64748b")
        _pid   = r.get("post_id","")
        _ttl   = (r.get("title","") or "")[:28]
        _hrs   = r.get("hours_since_publish","—")
        _idx   = "✅" if r.get("indexed") else "❌"
        _clk   = r.get("clicks_7d", 0) or 0
        _xok   = "✅" if r.get("x_success") else "—"
        _ev_rows += f'<tr><td style="color:{_rc};font-weight:700">{_rank}</td><td style="color:#a5f3fc">{_pid}</td><td>{_ttl}</td><td style="text-align:center">{_hrs}h</td><td style="text-align:center">{_idx}</td><td style="text-align:center;color:#86efac">{_clk}</td><td style="text-align:center">{_xok}</td></tr>'
    if not _ev_rows:
        _ev_rows = '<tr><td colspan="7" style="color:#64748b;text-align:center">データなし</td></tr>'

    bs_section_html = f"""<div class="section" id="bs-publish-eval" style="border:2px solid #0ea5e955;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#0ea5e944">
    <span class="section-title-icon">📊</span>
    <span style="color:#0ea5e9">BS. 公開後評価 (24h/48h/72h)</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">WIN:{len(_ev_win)} HOLD:{len(_ev_hold)} IMPROVE:{len(_ev_impr)} REWRITE:{len(_ev_rew)}</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
    <thead><tr style="color:#64748b;border-bottom:1px solid #1e293b"><th style="text-align:left;padding:4px 8px">ランク</th><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">タイトル</th><th style="text-align:center;padding:4px 8px">経過</th><th style="text-align:center;padding:4px 8px">索引</th><th style="text-align:center;padding:4px 8px">クリック</th><th style="text-align:center;padding:4px 8px">X</th></tr></thead>
    <tbody>{_ev_rows}</tbody>
  </table>
</div>"""

    # ─── セクション BT: 自動再生成候補 ───
    _rq_path = _bp("logs/regeneration_queue.jsonl")
    _rq_records = []
    if _rq_path.exists():
        for _line in _rq_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line:
                try: _rq_records.append(_bj.loads(_line))
                except: pass
    _rq_p0 = [r for r in _rq_records if r.get("priority") == "P0"]
    _rq_p1 = [r for r in _rq_records if r.get("priority") == "P1"]
    _rq_p2 = [r for r in _rq_records if r.get("priority") == "P2"]

    _rq_rows = ""
    _pri_colors = {"P0":"#ef4444","P1":"#fb923c","P2":"#fbbf24"}
    for r in sorted(_rq_records, key=lambda x: {"P0":0,"P1":1,"P2":2}.get(x.get("priority","P2"),2))[:10]:
        _pri  = r.get("priority","—")
        _pc   = _pri_colors.get(_pri,"#64748b")
        _pid  = r.get("post_id","")
        _ttl  = (r.get("title","") or "")[:25]
        _rank = r.get("rank","—")
        _hrs  = r.get("hours_since_publish","—")
        _ncand = len(r.get("candidates",[]))
        _rq_rows += f'<tr><td style="color:{_pc};font-weight:900">{_pri}</td><td style="color:#a5f3fc">{_pid}</td><td>{_ttl}</td><td style="color:#94a3b8">{_rank}</td><td style="text-align:center">{_hrs}h</td><td style="text-align:center;color:#86efac">{_ncand}案</td></tr>'
    if not _rq_rows:
        _rq_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center">再生成候補なし</td></tr>'

    bt_section_html = f"""<div class="section" id="bt-regen-queue" style="border:2px solid #ef444455;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#ef444444">
    <span class="section-title-icon">🔄</span>
    <span style="color:#ef4444">BT. 自動再生成候補</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">P0:{len(_rq_p0)} P1:{len(_rq_p1)} P2:{len(_rq_p2)}</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
    <thead><tr style="color:#64748b;border-bottom:1px solid #1e293b"><th style="text-align:left;padding:4px 8px">優先度</th><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">タイトル</th><th style="text-align:left;padding:4px 8px">ランク</th><th style="text-align:center;padding:4px 8px">経過</th><th style="text-align:center;padding:4px 8px">候補</th></tr></thead>
    <tbody>{_rq_rows}</tbody>
  </table>
</div>"""

    # ─── セクション BU: カテゴリ別勝ちテンプレ ───
    _tmpl_path = _bp("logs/template_recommendations.json")
    _tmpl_data = {}
    if _tmpl_path.exists():
        try: _tmpl_data = _bj.loads(_tmpl_path.read_text(encoding="utf-8"))
        except: pass
    _tmpl_cats = _tmpl_data.get("categories", {})
    _tmpl_total_win = _tmpl_data.get("total_win_patterns", 0)

    _tmpl_rows = ""
    for _cat, _cd in _tmpl_cats.items():
        _wc   = _cd.get("win_count", 0)
        _combo = _cd.get("best_combo_label", "—")
        _ats  = _cd.get("avg_thumb_score", 0)
        _axs  = _cd.get("avg_x_score", 0)
        if _wc == 0:
            continue
        _tmpl_rows += f'<tr><td style="color:#a5f3fc;font-weight:700">{_cat}</td><td style="text-align:center;color:#86efac">{_wc}</td><td style="color:#fbbf24">{_combo}</td><td style="text-align:center;color:#c4b5fd">{_ats}</td><td style="text-align:center;color:#67e8f9">{_axs}</td></tr>'
    if not _tmpl_rows:
        _tmpl_rows = '<tr><td colspan="5" style="color:#64748b;text-align:center">データなし (template_recommendations.json未生成)</td></tr>'

    bu_section_html = f"""<div class="section" id="bu-templates" style="border:2px solid #22c55e55;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#22c55e44">
    <span class="section-title-icon">📋</span>
    <span style="color:#22c55e">BU. カテゴリ別勝ちテンプレ</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">WIN合計: {_tmpl_total_win}件</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
    <thead><tr style="color:#64748b;border-bottom:1px solid #1e293b"><th style="text-align:left;padding:4px 8px">カテゴリ</th><th style="text-align:center;padding:4px 8px">WIN数</th><th style="text-align:left;padding:4px 8px">最頻出要素</th><th style="text-align:center;padding:4px 8px">平均サムネ</th><th style="text-align:center;padding:4px 8px">平均Xスコア</th></tr></thead>
    <tbody>{_tmpl_rows}</tbody>
  </table>
</div>"""

    # ─── セクション BV: 自動リライト実行ログ ───
    _act_path = _bp("logs/rewrite_actions.jsonl")
    _act_records = []
    if _act_path.exists():
        for _line in _act_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line:
                try: _act_records.append(_bj.loads(_line))
                except: pass
    _act_exec    = [r for r in _act_records if not r.get("skipped")]
    _act_skipped = [r for r in _act_records if r.get("skipped")]
    _act_wp_ok   = [r for r in _act_exec if r.get("wp_update_ok")]
    _act_x_ok    = [r for r in _act_exec if r.get("x_posted")]

    _act_rows = ""
    _pri_c2 = {"P0":"#ef4444","P1":"#fb923c","P2":"#fbbf24"}
    for r in sorted(_act_records, key=lambda x: x.get("executed_at",""), reverse=True)[:20]:
        _pri2  = r.get("priority","—")
        _pc2   = _pri_c2.get(_pri2,"#64748b")
        _pid2  = r.get("post_id","")
        _ttl2  = (r.get("original_title","") or "")[:22]
        _ttl_n = (r.get("new_title","") or "")[:15]
        _ts2   = (r.get("executed_at","") or "")[:16]
        _skp   = "⏭️" if r.get("skipped") else ""
        _wp2   = "✅" if r.get("wp_update_ok") else ("—" if r.get("skipped") else "❌")
        _x2    = "✅" if r.get("x_posted") else ("—" if r.get("skipped") else "❌")
        _skip_r = (r.get("skip_reason","") or "")[:30]
        _act_rows += f'<tr><td style="color:{_pc2};font-weight:700">{_pri2}{_skp}</td><td style="color:#a5f3fc">{_pid2}</td><td title="{_ttl2}">{_ttl2}</td><td style="color:#86efac;font-size:0.65rem">{_ttl_n or _skip_r}</td><td style="text-align:center">{_wp2}</td><td style="text-align:center">{_x2}</td><td style="color:#64748b;font-size:0.65rem">{_ts2}</td></tr>'
    if not _act_rows:
        _act_rows = '<tr><td colspan="7" style="color:#64748b;text-align:center">リライト実行なし</td></tr>'

    bv_section_html = f"""<div class="section" id="bv-rewrite-log" style="border:2px solid #f59e0b55;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#f59e0b44">
    <span class="section-title-icon">⚡</span>
    <span style="color:#f59e0b">BV. 自動リライト実行ログ</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">実行:{len(_act_exec)} SKIP:{len(_act_skipped)} WP更新:{len(_act_wp_ok)} X投稿:{len(_act_x_ok)}</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
    <thead><tr style="color:#64748b;border-bottom:1px solid #1e293b"><th style="text-align:left;padding:4px 8px">優先度</th><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">元タイトル</th><th style="text-align:left;padding:4px 8px">新タイトル/理由</th><th style="text-align:center;padding:4px 8px">WP</th><th style="text-align:center;padding:4px 8px">X</th><th style="text-align:left;padding:4px 8px">実行日時</th></tr></thead>
    <tbody>{_act_rows}</tbody>
  </table>
</div>"""

    # ─── セクション BW: リライト成功率 ───
    _total_act = len(_act_records)
    _exec_rate = round(len(_act_exec) / _total_act * 100, 1) if _total_act > 0 else 0
    _wp_rate   = round(len(_act_wp_ok) / len(_act_exec) * 100, 1) if _act_exec else 0
    _x_rate    = round(len(_act_x_ok) / len(_act_exec) * 100, 1) if _act_exec else 0

    # 改善できなかった記事 (実行済みだがWP失敗かつX失敗)
    _failed_both = [r for r in _act_exec if not r.get("wp_update_ok") and not r.get("x_posted")]
    _failed_rows = ""
    for r in _failed_both[:5]:
        _pid3 = r.get("post_id","")
        _ttl3 = (r.get("original_title","") or "")[:25]
        _we   = (r.get("wp_error","") or "")[:40]
        _failed_rows += f'<tr><td style="color:#ef4444">{_pid3}</td><td>{_ttl3}</td><td style="color:#f87171;font-size:0.65rem">{_we}</td></tr>'

    bw_section_html = f"""<div class="section" id="bw-rewrite-rate" style="border:2px solid #8b5cf655;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#8b5cf644">
    <span class="section-title-icon">📈</span>
    <span style="color:#8b5cf6">BW. リライト成功率</span>
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
    <div style="background:#1e1b4b;border:1px solid #8b5cf644;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#a78bfa">{_total_act}</div><div style="font-size:0.65rem;color:#64748b">総処理件数</div></div>
    <div style="background:#1e1b4b;border:1px solid #22c55e44;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#86efac">{_exec_rate}%</div><div style="font-size:0.65rem;color:#64748b">実行率</div></div>
    <div style="background:#1e1b4b;border:1px solid #0ea5e944;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#67e8f9">{_wp_rate}%</div><div style="font-size:0.65rem;color:#64748b">WP更新成功率</div></div>
    <div style="background:#1e1b4b;border:1px solid #a78bfa44;border-radius:8px;padding:10px 18px;text-align:center"><div style="font-size:1.4rem;font-weight:900;color:#c4b5fd">{_x_rate}%</div><div style="font-size:0.65rem;color:#64748b">X投稿成功率</div></div>
  </div>
  {'<div style="margin-top:8px"><div style="font-size:0.7rem;color:#f87171;margin-bottom:6px">⚠️ 改善失敗記事</div><table style="width:100%;border-collapse:collapse;font-size:0.7rem"><thead><tr style="color:#64748b"><th style="text-align:left;padding:4px">ID</th><th style="text-align:left;padding:4px">タイトル</th><th style="text-align:left;padding:4px">エラー</th></tr></thead><tbody>' + _failed_rows + '</tbody></table></div>' if _failed_rows else '<div style="color:#22c55e;font-size:0.72rem;padding:8px">改善失敗記事なし ✅</div>'}
</div>"""

    # ─── セクション BX: 改善率ランキング ───
    # リライト後の評価でimprovement_deltaが正の記事をランキング
    _ev_rewrite = [r for r in _eval_latest.values()
                   if r.get("is_post_rewrite") and r.get("improvement_delta") is not None]
    _ev_rewrite_sorted = sorted(_ev_rewrite, key=lambda x: x.get("improvement_delta", 0) or 0, reverse=True)

    _improv_rows = ""
    for r in _ev_rewrite_sorted[:10]:
        _pid4  = r.get("post_id","")
        _ttl4  = (r.get("title","") or "")[:22]
        _bef   = r.get("before_score", 0) or 0
        _aft   = r.get("after_score", 0) or 0
        _delta = r.get("improvement_delta", 0) or 0
        _rank4 = r.get("rank","—")
        _dc    = "#22c55e" if _delta > 0 else "#ef4444" if _delta < 0 else "#64748b"
        _dsign = "+" if _delta > 0 else ""
        _improv_rows += f'<tr><td style="color:#a5f3fc">{_pid4}</td><td>{_ttl4}</td><td style="text-align:center">{_bef}</td><td style="text-align:center">{_aft}</td><td style="text-align:center;color:{_dc};font-weight:700">{_dsign}{_delta}</td><td style="color:#94a3b8">{_rank4}</td></tr>'
    if not _improv_rows:
        _improv_rows = '<tr><td colspan="6" style="color:#64748b;text-align:center">改善データなし（リライト実行後に蓄積）</td></tr>'

    bx_section_html = f"""<div class="section" id="bx-improvement-rank" style="border:2px solid #06b6d455;border-radius:12px;padding:16px;margin-top:16px">
  <div class="section-title" style="border-bottom-color:#06b6d444">
    <span class="section-title-icon">🏅</span>
    <span style="color:#06b6d4">BX. 改善率ランキング</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">リライト後評価: {len(_ev_rewrite)}件</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:0.72rem">
    <thead><tr style="color:#64748b;border-bottom:1px solid #1e293b"><th style="text-align:left;padding:4px 8px">ID</th><th style="text-align:left;padding:4px 8px">タイトル</th><th style="text-align:center;padding:4px 8px">前クリック</th><th style="text-align:center;padding:4px 8px">後クリック</th><th style="text-align:center;padding:4px 8px">改善Δ</th><th style="text-align:left;padding:4px 8px">現ランク</th></tr></thead>
    <tbody>{_improv_rows}</tbody>
  </table>
</div>"""

    # ─── HTML生成 ───
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>K-POP Journal AI Company — オーナー経営ダッシュボード</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#080c14;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;line-height:1.5}}
a{{text-decoration:none}}

/* ヘッダー */
.header{{
  background:linear-gradient(135deg,#0f0c29,#1a0533,#0f172a);
  padding:18px 32px;
  border-bottom:1px solid #1e293b;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;
}}
.company-badge{{
  display:flex;align-items:center;gap:14px;
}}
.company-name{{
  font-size:1.15rem;font-weight:900;letter-spacing:0.04em;
  background:linear-gradient(90deg,#818cf8,#c084fc);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}}
.ceo-badge{{
  background:linear-gradient(135deg,#7c3aed,#2563eb);
  padding:4px 12px;border-radius:99px;font-size:0.75rem;font-weight:700;
  color:#fff;display:flex;align-items:center;gap:6px;
}}
.owner-badge{{
  background:#1e293b;border:1px solid #334155;
  padding:4px 12px;border-radius:99px;font-size:0.75rem;color:#94a3b8;
}}
.live{{display:flex;align-items:center;gap:8px;font-size:0.78rem;color:#64748b}}
.live-dot{{width:8px;height:8px;background:#22c55e;border-radius:50%;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1;box-shadow:0 0 0 0 #22c55e44}}50%{{opacity:0.6;box-shadow:0 0 0 6px transparent}}}}

/* ナビゲーション */
.nav{{
  background:#0d1117;border-bottom:1px solid #1e293b;
  display:flex;gap:0;padding:0 32px;overflow-x:auto;
}}
.nav-item{{
  padding:12px 18px;font-size:0.8rem;font-weight:600;color:#64748b;
  cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;
  transition:all 0.2s;
}}
.nav-item:hover,.nav-item.active{{color:#818cf8;border-bottom-color:#818cf8}}
/* サブナビボタン */
.nav-sub-btn{{
  background:#111827;border:1px solid #1e293b;color:#94a3b8;
  font-size:0.72rem;padding:5px 12px;border-radius:99px;margin:2px 3px;
  cursor:pointer;white-space:nowrap;transition:all 0.15s;
}}
.nav-sub-btn:hover{{background:#1e293b;color:#e2e8f0;border-color:#334155}}

/* メインレイアウト */
.main{{padding:16px 28px;max-width:1440px;margin:0 auto}}
.section{{margin-bottom:28px}}
.section-title{{
  font-size:0.85rem;font-weight:800;color:#64748b;
  text-transform:uppercase;letter-spacing:0.1em;
  margin-bottom:16px;padding-bottom:8px;
  border-bottom:1px solid #1e293b;
  display:flex;align-items:center;gap:8px;
}}
.section-title-icon{{font-size:1rem}}

/* KPIカード */
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.kpi-card{{
  background:#111827;border:1px solid #1e293b;border-radius:12px;
  padding:18px 16px;position:relative;overflow:hidden;
}}
.kpi-card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
}}
.kpi-card.green::before{{background:linear-gradient(90deg,#22c55e,#16a34a)}}
.kpi-card.yellow::before{{background:linear-gradient(90deg,#eab308,#ca8a04)}}
.kpi-card.red::before{{background:linear-gradient(90deg,#ef4444,#dc2626)}}
.kpi-card.blue::before{{background:linear-gradient(90deg,#3b82f6,#2563eb)}}
.kpi-card.purple::before{{background:linear-gradient(90deg,#8b5cf6,#7c3aed)}}
.kpi-label{{font-size:0.7rem;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px}}
.kpi-value{{font-size:1.9rem;font-weight:900;line-height:1}}
.kpi-sub{{font-size:0.72rem;color:#64748b;margin-top:6px}}

/* 2カラムグリッド */
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}}
.card{{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:18px}}
.card-title{{font-size:0.82rem;font-weight:700;color:#94a3b8;margin-bottom:12px}}

/* エージェントカード */
.agents-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}}
.agent-card{{
  border-radius:10px;padding:16px;
  transition:transform 0.15s;
}}
.agent-card:hover{{transform:translateY(-2px)}}

/* MVP/ワースト */
.mvp-row{{display:flex;gap:14px;flex-wrap:wrap}}

/* 異常検知 */
.anomaly-row{{
  display:flex;align-items:center;gap:12px;
  padding:10px 14px;background:#0f172a;border-radius:6px;
  margin-bottom:8px;border-left:3px solid;
}}
.anomaly-badge{{
  display:inline-block;padding:2px 8px;border-radius:99px;
  font-size:0.7rem;font-weight:700;white-space:nowrap;
}}

/* 改善アクション */
.action-card{{
  background:#0f172a;border:1px solid #1e293b;border-radius:8px;
  padding:14px 16px;margin-bottom:10px;
}}

/* テーブル */
.data-table{{width:100%;border-collapse:collapse}}
.data-table th{{
  padding:10px 12px;text-align:left;font-size:0.7rem;
  color:#64748b;text-transform:uppercase;border-bottom:1px solid #1e293b;
}}
.data-table td{{padding:10px 12px;font-size:0.83rem;border-bottom:1px solid #0d1117}}
.data-table tr:hover td{{background:#0f172a33}}

/* 組織マップ */
.org-dept{{
  background:#111827;border:1px solid #1e293b;border-radius:10px;
  padding:16px;margin-bottom:12px;
}}
.org-dept-title{{
  font-size:0.75rem;font-weight:700;color:#818cf8;
  text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px;
}}

/* フッター */
.footer{{
  text-align:center;padding:20px 32px;
  color:#374151;font-size:0.72rem;
  border-top:1px solid #1e293b;margin-top:24px;
}}

/* 履歴フィルタボタン */
.hfilter{{
  background:#0f172a;border:1px solid #1e293b;color:#64748b;
  padding:4px 10px;border-radius:6px;font-size:0.72rem;font-weight:600;
  cursor:pointer;transition:all 0.15s;
}}
.hfilter:hover{{background:#1e293b;color:#e2e8f0}}
.hfilter.active{{background:#818cf855;color:#818cf8;border-color:#818cf8}}

/* 折りたたみセクション */
.collapse-btn{{
  background:none;border:none;color:#475569;font-size:0.72rem;
  cursor:pointer;padding:2px 6px;border-radius:4px;margin-left:auto;
  transition:color 0.2s;
}}
.collapse-btn:hover{{color:#94a3b8}}
.collapsible{{overflow:hidden;transition:max-height 0.3s ease}}
.collapsible.collapsed{{max-height:0!important}}

/* レスポンシブ */
@media(max-width:900px){{
  .header{{flex-direction:column;gap:10px;padding:12px 14px}}
  .main{{padding:12px 10px}}
  .grid-2,.grid-3{{grid-template-columns:1fr}}
  .agents-grid{{grid-template-columns:1fr}}
  .kpi-grid{{grid-template-columns:repeat(2,1fr)}}
}}
@media(max-width:640px){{
  /* スマホ: 2列グリッドを1列に */
  [style*="grid-template-columns:1fr 1fr"]{{grid-template-columns:1fr!important}}
  [style*="grid-template-columns:repeat(auto-fill"]{{grid-template-columns:1fr!important}}
  [style*="display:grid"]{{grid-template-columns:1fr!important}}
  /* テーブルのスクロール */
  table{{font-size:0.7rem!important}}
  /* 余白縮小 */
  [style*="padding:20px"]{{padding:12px!important}}
  [style*="padding:18px"]{{padding:10px!important}}
}}
@media(max-width:480px){{
  .kpi-grid{{grid-template-columns:1fr 1fr}}
  .kpi-value{{font-size:1.4rem}}
  .kpi-card{{padding:10px 8px}}
  .section{{margin-bottom:18px}}
  .agent-card{{padding:10px}}
  .nav{{padding:0 8px}}
  .nav-item{{padding:10px 10px;font-size:0.72rem}}
  /* 技術詳細セクションはスマホでは折りたたみ */
  details:not([open])>summary~*{{display:none}}
}}
</style>
</head>
<body>

<!-- ヘッダー -->
<div class="header">
  <div class="company-badge">
    <div>
      <div class="company-name">🤖 K-POP Journal AI Company</div>
      <div style="font-size:0.72rem;color:#475569;margin-top:2px">完全自律AI企業 — オーナー経営ダッシュボード</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px">
      <div class="ceo-badge">👑 CEO: ミュウツー</div>
      <div class="owner-badge">👤 オーナー: 閲覧専用</div>
    </div>
  </div>
  <div class="live">
    <div class="live-dot"></div>
    <span>リアルタイム監視 | 更新: {gen_str}</span>
  </div>
</div>

<!-- ナビゲーション（カテゴリ別折りたたみ式） -->
<div style="background:#0d1117;border-bottom:1px solid #1e293b;padding:0 20px">
  <!-- 常時表示ナビ：最重要5項目 -->
  <div style="display:flex;gap:0;overflow-x:auto;border-bottom:1px solid #1e293b" id="nav-primary">
    <div class="nav-item active" onclick="scrollToId('cd-owner-summary')" style="color:#22d3ee;border-bottom:3px solid #22d3ee;font-weight:900">👑 経営判断</div>
    <div class="nav-item" onclick="scrollToId('cj-finance')" style="font-weight:800">💹 財務状況</div>
    <div class="nav-item" onclick="scrollToId('ca-daily-kpi')" style="font-weight:700">📊 今日の目標</div>
    <div class="nav-item" onclick="scrollToId('cb-monthly-kpi')">📅 今月の目標</div>
    <div class="nav-item" onclick="scrollToId('cf-departments')">🏗️ 部署一覧</div>
    <div class="nav-item" onclick="scrollToId('ck-cta-optimizer')" style="color:#f472b6;font-weight:700">🎨 UI/CTA</div>
    <div style="flex:1"></div>
    <!-- カテゴリ切替ボタン -->
    <button onclick="toggleNavGroup('nav-org')" style="background:none;border:none;color:#818cf8;font-size:0.78rem;padding:10px 12px;cursor:pointer;white-space:nowrap">🏢 組織 ▾</button>
    <button onclick="toggleNavGroup('nav-meeting')" style="background:none;border:none;color:#34d399;font-size:0.78rem;padding:10px 12px;cursor:pointer;white-space:nowrap">🏛️ 会議 ▾</button>
    <button onclick="toggleNavGroup('nav-ops')" style="background:none;border:none;color:#fb923c;font-size:0.78rem;padding:10px 12px;cursor:pointer;white-space:nowrap">⚙️ 現場 ▾</button>
    <button onclick="toggleNavGroup('nav-detail')" style="background:none;border:none;color:#475569;font-size:0.78rem;padding:10px 12px;cursor:pointer;white-space:nowrap">📁 詳細 ▾</button>
  </div>
  <!-- 組織ナビ（折りたたみ） -->
  <div id="nav-org" style="display:none;padding:8px 0;border-bottom:1px solid #1e293b">
    <span style="font-size:0.62rem;color:#818cf8;font-weight:800;margin-right:12px;text-transform:uppercase">▶ 組織</span>
    <button class="nav-sub-btn" onclick="scrollToId('ce-org-chart')">🏢 組織図</button>
    <button class="nav-sub-btn" onclick="scrollToId('cf-departments')">🏗️ 部署一覧</button>
    <button class="nav-sub-btn" onclick="scrollToId('agents')">🤖 AI社員カード</button>
    <button class="nav-sub-btn" onclick="scrollToId('mvp')">🏆 成果/問題ランキング</button>
    <button class="nav-sub-btn" onclick="scrollToId('org')">🗺️ 組織マップ</button>
  </div>
  <!-- 会議ナビ（折りたたみ） -->
  <div id="nav-meeting" style="display:none;padding:8px 0;border-bottom:1px solid #1e293b">
    <span style="font-size:0.62rem;color:#34d399;font-weight:800;margin-right:12px;text-transform:uppercase">▶ 会議・議事録</span>
    <button class="nav-sub-btn" onclick="scrollToId('cg-meetings')">🏛️ 会議体一覧</button>
    <button class="nav-sub-btn" onclick="scrollToId('ch-minutes')">📋 最新議事録</button>
    <button class="nav-sub-btn" onclick="scrollToId('summary')">📊 経営サマリー</button>
    <button class="nav-sub-btn" onclick="scrollToId('cc-intraday-timeline')">⏱️ 時間別進捗</button>
  </div>
  <!-- 現場ナビ（折りたたみ） -->
  <div id="nav-ops" style="display:none;padding:8px 0;border-bottom:1px solid #1e293b">
    <span style="font-size:0.62rem;color:#fb923c;font-weight:800;margin-right:12px;text-transform:uppercase">▶ 現場・運用</span>
    <button class="nav-sub-btn" onclick="scrollToId('anomaly')">⚠️ 問題検知</button>
    <button class="nav-sub-btn" onclick="scrollToId('alert-rank')">🚨 問題ランキング</button>
    <button class="nav-sub-btn" onclick="scrollToId('revenue-blocker')">💸 収益阻害</button>
    <button class="nav-sub-btn" onclick="scrollToId('revenue')">💰 収益最大化</button>
    <button class="nav-sub-btn" onclick="scrollToId('actions')">🔧 改善アクション</button>
    <button class="nav-sub-btn" onclick="scrollToId('notif')">🔔 通知状況</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-next-command')">⚡ 今打つ1手</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-runtime-mode')">⚙️ 実行モード</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-hardening-alert')">🚨 安全確認最優先</button>
  </div>
  <!-- 詳細ナビ（折りたたみ） -->
  <div id="nav-detail" style="display:none;padding:8px 0">
    <span style="font-size:0.62rem;color:#475569;font-weight:800;margin-right:12px;text-transform:uppercase">▶ 技術詳細（CEO専用）</span>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-auto-exec-log')">🤖 自動実行記録</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-safe-auto-gate')">🟢 安全自動判定</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-queue')">🧾 CEO命令待ち</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-exec')">⚡ 実行記録</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-safe')">🛡️ 安全実行</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-improvement')">🧩 改善待ちリスト</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-stale-resolver')">🧹 未処理解消</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-mode-transition')">🚦 モード移行</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-safety-invariants')">🔐 安全ルール</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-operation-runbook')">🧭 運用手順</button>
    <button class="nav-sub-btn" onclick="scrollToId('ceo-lifecycle-trace')">🗺️ 処理流れ</button>
  </div>
</div>

<div class="main">

<!-- ─── 経営最上段: CD オーナー総合判断 ─── -->
<div style="margin-bottom:8px;padding:8px 0 4px;border-bottom:2px solid #22d3ee33">
  <div style="font-size:0.72rem;color:#22d3ee;font-weight:900;letter-spacing:0.1em">
    ▼ 経営ダッシュボード — 今日の「働き」と「経営状態」を一目で
  </div>
</div>
{_kpi_cd_html}

<!-- ─── CX 復旧＆成長KPI (2026-04-16障害以降の回復指標) ─── -->
{_cx_recovery_html}

<!-- ─── CJ 財務状況 ─── -->
{_cj_section_html}

<!-- ─── CA 今日の目標 / CB 今月の目標 / CC 進捗タイムライン ─── -->
{_kpi_ca_cb_cc_html}

<!-- ─── CK CTA最適化（イルミーゼ） ─── -->
{_ck_section_html}

<!-- ─── CF 部署一覧 ─── -->
{_cf_section_html}

<!-- ─── CE 組織図 ─── -->
{_ce_section_html}

<!-- ─── 会議体 CG / 議事録 CH ─── -->
{_cg_section_html}
{_ch_section_html}

<div style="margin-bottom:8px;padding:4px 0;border-bottom:2px solid #1e293b">
  <div style="font-size:0.7rem;color:#334155;letter-spacing:0.08em">▼ 運用詳細セクション (CEO / エージェント)</div>
</div>

<!-- ─── オーナー判断バー ─── -->
{owner_bar_html}

<!-- ─── オーナー3行サマリー ─── -->
{owner_summary_html}

<!-- ─── CEO意思決定ボード ─── -->
{ceo_board_html}

<!-- 全体KPI（補足） -->
<div class="kpi-grid" style="margin-top:20px">
  <div class="kpi-card {'green' if overall_rate>=0.85 else 'yellow' if overall_rate>=0.6 else 'red'}">
    <div class="kpi-label">全体成功率</div>
    <div class="kpi-value" style="color:{'#22c55e' if overall_rate>=0.85 else '#eab308' if overall_rate>=0.6 else '#ef4444'}">{pct(overall_rate)}</div>
    <div class="kpi-sub">全AIエージェント平均</div>
  </div>
  <div class="kpi-card blue">
    <div class="kpi-label">稼働中AI</div>
    <div class="kpi-value" style="color:#60a5fa">{len(active)}</div>
    <div class="kpi-sub">🟢{excellent} 🟡{warning} 🔴{critical}</div>
  </div>
  <div class="kpi-card {'red' if high_actions>=5 else 'yellow'}">
    <div class="kpi-label">HIGH優先度アラート</div>
    <div class="kpi-value" style="color:{'#ef4444' if high_actions>=5 else '#eab308'}">{high_actions}</div>
    <div class="kpi-sub">即対応必要</div>
  </div>
  <div class="kpi-card {'red' if sabori>0 else 'green'}">
    <div class="kpi-label">サボり疑いAI</div>
    <div class="kpi-value" style="color:{'#ef4444' if sabori>0 else '#22c55e'}">{sabori}</div>
    <div class="kpi-sub">空出力・長期未実行</div>
  </div>
  <div class="kpi-card blue">
    <div class="kpi-label">今日の投稿数</div>
    <div class="kpi-value" style="color:#60a5fa">{today_posts}</div>
    <div class="kpi-sub">週計 {week_posts}件</div>
  </div>
  <div class="kpi-card {'green' if avg_rev_score>=0.75 else 'yellow'}">
    <div class="kpi-label">平均収益スコア</div>
    <div class="kpi-value" style="color:{'#22c55e' if avg_rev_score>=0.75 else '#eab308'}">{avg_rev_score:.2f}</div>
    <div class="kpi-sub">CTA設置率 {pct(cta_rate)}</div>
  </div>
  <div class="kpi-card {'red' if contaminated>0 else 'green'}">
    <div class="kpi-label">タイトル汚染</div>
    <div class="kpi-value" style="color:{'#ef4444' if contaminated>0 else '#22c55e'}">{contaminated}</div>
    <div class="kpi-sub">記事汚染件数</div>
  </div>
  <div class="kpi-card purple">
    <div class="kpi-label">エラーフラグAI</div>
    <div class="kpi-value" style="color:#a78bfa">{err_agents}</div>
    <div class="kpi-sub">要調査エージェント</div>
  </div>
</div>

<!-- ─── セクションA: 経営サマリー ─── -->
<div class="section" id="summary">
  <div class="section-title"><span class="section-title-icon">📊</span> A. 経営サマリー — CEO: ミュウツー 報告</div>
  <div class="grid-3">
    <div class="card">
      <div class="card-title">🏆 成果トップ3（今週）</div>
      {top3_html if top3_html else '<div style="color:#64748b">データなし</div>'}
    </div>
    <div class="card">
      <div class="card-title">⚠️ 問題トップ3（要対応）</div>
      {worst3_html if worst3_html else '<div style="color:#64748b">データなし</div>'}
    </div>
    <div class="card">
      <div class="card-title">🎯 売上改善 優先タスク</div>
      <ol style="padding-left:18px;color:#e2e8f0">{urgent_html}</ol>
    </div>
  </div>
  <!-- 今週の経営指標 -->
  <div class="grid-2" style="margin-top:16px">
    <div class="card">
      <div class="card-title">📈 今週の経営数値</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:0.72rem;color:#64748b">週間投稿数</div>
          <div style="font-size:1.6rem;font-weight:800;color:#60a5fa">{week_posts}</div>
          <div style="font-size:0.68rem;color:#64748b">目標: 35本/週</div>
        </div>
        <div style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:0.72rem;color:#64748b">平均文字数</div>
          <div style="font-size:1.6rem;font-weight:800;color:{'#22c55e' if avg_chars>=3000 else '#ef4444'}">{avg_chars:,}</div>
          <div style="font-size:0.68rem;color:#64748b">目標: 3,000字↑</div>
        </div>
        <div style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:0.72rem;color:#64748b">CTA設置率</div>
          <div style="font-size:1.6rem;font-weight:800;color:{'#22c55e' if cta_rate>=0.9 else '#eab308'}">{pct(cta_rate)}</div>
          <div style="font-size:0.68rem;color:#64748b">目標: 100%</div>
        </div>
        <div style="background:#0f172a;border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:0.72rem;color:#64748b">サムネ設置率</div>
          <div style="font-size:1.6rem;font-weight:800;color:{'#22c55e' if thumb_rate>=0.95 else '#eab308'}">{pct(thumb_rate)}</div>
          <div style="font-size:0.68rem;color:#64748b">目標: 100%</div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">💡 CEO戦略メモ（ミュウツーより）</div>
      <div style="background:#0f172a;border-radius:8px;padding:14px;font-size:0.83rem;line-height:1.7;color:#cbd5e1">
        <p style="margin-bottom:8px">📌 <strong>最優先改善テーマ:</strong> {insights.get('priority_theme','記事品質向上')}</p>
        <p style="margin-bottom:8px">🏅 <strong>最もROIが高いpipeline:</strong> {insights.get('best_roi_pipeline','—')}</p>
        <p style="margin-bottom:8px">⚡ <strong>無駄が多いpipeline:</strong> {insights.get('worst_pipeline','—')}</p>
        <p style="font-size:0.75rem;color:#475569;margin-top:8px">※ CEOミュウツーの判断に基づく自律改善提案。オーナー確認推奨。</p>
      </div>
    </div>
  </div>
</div>

<!-- ─── セクションB: AI社員一覧 ─── -->
<div class="section" id="agents">
  <div class="section-title"><span class="section-title-icon">🤖</span> B. AI社員一覧（{len(sorted_active)}名 稼働中）</div>
  <div class="agents-grid">
    {agent_cards}
  </div>
</div>

<!-- ─── セクションC: MVP / ワースト ─── -->
<div class="section" id="mvp">
  <div class="section-title"><span class="section-title-icon">🏆</span> C. MVP / ワースト AI社員</div>
  <div class="grid-2">
    <div class="card">
      <div class="card-title">🏆 今週のMVP — 最も成果を出したAI</div>
      <div class="mvp-row">
        {mvp_html}
      </div>
    </div>
    <div class="card">
      <div class="card-title">💀 今週のワースト — 最も問題が大きいAI</div>
      <div class="mvp-row">
        {worst_html}
      </div>
    </div>
  </div>
</div>

<!-- ─── 組織マップ ─── -->
<div class="section" id="org">
  <div class="section-title"><span class="section-title-icon">🏢</span> 組織マップ — AI会社構造</div>
  <!-- CEO -->
  <div style="text-align:center;margin-bottom:20px">
    <div style="display:inline-block;background:linear-gradient(135deg,#7c3aed,#2563eb);border-radius:14px;padding:16px 32px">
      <div style="font-size:1.2rem;font-weight:900">👑 CEO: ミュウツー</div>
      <div style="font-size:0.78rem;color:#c4b5fd;margin-top:4px">戦略統合・最終意思決定 | K-POP Journal AI Company</div>
    </div>
    <div style="color:#4b5563;margin:8px 0;font-size:1.2rem">↕</div>
    <div style="display:inline-block;background:#1e293b;border:1px solid #334155;border-radius:10px;padding:10px 24px">
      <div style="font-size:0.88rem;font-weight:700;color:#94a3b8">👤 オーナー（人間）— 閲覧専用</div>
    </div>
  </div>
  <!-- 部門別 -->
  <div class="grid-2">
    <div class="org-dept">
      <div class="org-dept-title">⚡ コア部隊 — 記事生成・品質管理</div>
      {dept_html(core_list)}
    </div>
    <div class="org-dept">
      <div class="org-dept-title">🔬 サポート部隊 — 分析・最適化</div>
      {dept_html(support_list)}
    </div>
    <div class="org-dept">
      <div class="org-dept-title">🚀 インフラ部隊 — 投稿・配信</div>
      {dept_html(infra_list)}
    </div>
    <div class="org-dept">
      <div class="org-dept-title">📝 手動発注専門 — オーナー指示待ち</div>
      {dept_html(manual_list)}
    </div>
  </div>
</div>

<!-- ─── セクションD: 異常検知 ─── -->
<div class="section" id="anomaly">
  <div class="section-title">
    <span class="section-title-icon">🚨</span> D. 異常検知ログ
    <span style="font-size:0.72rem;color:#64748b;margin-left:8px">崩壊:{contaminated} HARD_FAIL:{gdv.get('gardevoir_fail',0) if gdv else 0} サボり:{sabori}</span>
    <button class="collapse-btn" onclick="toggleCollapse('anomaly-body',this)">▼ 折りたたむ</button>
  </div>
  <div id="anomaly-body" class="collapsible" style="max-height:2000px">
    <div class="card">
      {anomalies_html}
    </div>
  </div>
</div>

<!-- ─── セクションE: 売上最大化 ─── -->
<div class="section" id="revenue">
  <div class="section-title"><span class="section-title-icon">💰</span> E. 売上最大化アルゴリズム</div>

  <!-- パイプライン別 収益スコア -->
  <div class="card" style="margin-bottom:16px">
    <div class="card-title">📊 パイプライン別 平均 revenue_score</div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:8px">
      {pl_html}
    </div>
  </div>

  <!-- 勝ち/負けパターン -->
  <div class="grid-2" style="margin-bottom:16px">
    <div class="card">
      <div class="card-title">🏆 勝ちパターン（TOP25%記事の共通点）</div>
      <div style="font-size:0.83rem;color:#e2e8f0;line-height:2">
        <div>📝 平均文字数: <strong style="color:#22c55e">{win.get('avg_chars',0):,}字</strong></div>
        <div>📌 平均H2数: <strong style="color:#22c55e">{win.get('avg_h2',0):.1f}本</strong></div>
        <div>🎯 CTA設置率: <strong style="color:#22c55e">{win.get('cta_rate',0):.0%}</strong></div>
        <div>🖼 サムネ設置率: <strong style="color:#22c55e">{win.get('thumb_rate',0):.0%}</strong></div>
        <div>📈 平均CTRスコア: <strong style="color:#22c55e">{win.get('avg_ctr_score',0):.3f}</strong></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">💀 負けパターン（WORST25%記事の共通点）</div>
      <div style="font-size:0.83rem;color:#e2e8f0;line-height:2">
        <div>📝 平均文字数: <strong style="color:#ef4444">{lose.get('avg_chars',0):,}字</strong></div>
        <div>📌 平均H2数: <strong style="color:#ef4444">{lose.get('avg_h2',0):.1f}本</strong></div>
        <div>🎯 CTA設置率: <strong style="color:#ef4444">{lose.get('cta_rate',0):.0%}</strong></div>
        <div>🖼 サムネ設置率: <strong style="color:#ef4444">{lose.get('thumb_rate',0):.0%}</strong></div>
        <div>📈 平均CTRスコア: <strong style="color:#ef4444">{lose.get('avg_ctr_score',0):.3f}</strong></div>
      </div>
    </div>
  </div>

  <!-- TOP記事 -->
  <div class="card" style="margin-bottom:16px">
    <div class="card-title">🚀 revenue_score 上位記事（伸ばすべき記事群）</div>
    <table class="data-table">
      <thead><tr>
        <th>タイトル</th><th>スコア</th><th>文字数</th><th>CTA</th><th>サムネ</th><th>スコアバー</th>
      </tr></thead>
      <tbody>{top_art_html if top_art_html else '<tr><td colspan="6" style="color:#64748b;text-align:center">データなし</td></tr>'}</tbody>
    </table>
  </div>

  <!-- BOTTOM記事 -->
  <div class="card">
    <div class="card-title">⚠️ revenue_score 低位記事（止めるか改善すべき記事群）</div>
    <table class="data-table">
      <thead><tr><th>タイトル</th><th>スコア</th><th>改善理由</th></tr></thead>
      <tbody>{bot_art_html if bot_art_html else '<tr><td colspan="3" style="color:#64748b;text-align:center">データなし</td></tr>'}</tbody>
    </table>
  </div>
</div>

<!-- ─── セクション: 改善アクション ─── -->
<div class="section" id="actions">
  <div class="section-title">
    <span class="section-title-icon">🔧</span>
    F. 自律改善アクション — {opt.get('total_actions',0)}件
    <span style="font-size:0.72rem;color:#64748b;margin-left:6px">HIGH:{opt.get('high_count',0)} MED:{opt.get('medium_count',0)} LOW:{opt.get('low_count',0)}</span>
    <button class="collapse-btn" onclick="toggleCollapse('actions-body',this)">▼ 折りたたむ</button>
  </div>
  <div id="actions-body" class="collapsible" style="max-height:4000px">
    <div style="background:#111827;border:1px solid #1e293b;border-radius:12px;padding:16px">
      <div style="font-size:0.75rem;color:#374151;margin-bottom:12px;padding:8px;background:#0f172a;border-radius:6px">
        ⚠️ 改善提案のみ — 既存pipeline・WordPress記事への自動変更は行いません
      </div>
      {action_html if action_html else '<div style="color:#22c55e;padding:12px">✅ 改善アクションなし</div>'}
    </div>
  </div>
</div>

{notif_sections_html}

</div><!-- /main -->

<div class="footer">
  K-POP Journal AI Company — オーナー経営ダッシュボード v2.0 |
  CEO: ミュウツー | オーナー: 閲覧専用 |
  生成: {now_str} |
  既存pipeline・記事への変更なし（読み取り専用分析）
</div>

<script>
// ナビゲーションスクロール
function scrollTo(id) {{
  document.querySelector(id)?.scrollIntoView({{behavior:'smooth', block:'start'}});
}}
// アクティブナビ更新
const navItems = document.querySelectorAll('.nav-item');
navItems.forEach(item => {{
  item.addEventListener('click', () => {{
    navItems.forEach(n => n.classList.remove('active'));
    item.classList.add('active');
  }});
}});
// 最終更新時刻を動的表示
const generatedAt = new Date('{am.get("generated_at","")}');
if (!isNaN(generatedAt)) {{
  const diff = Math.floor((new Date() - generatedAt) / 60000);
  document.querySelectorAll('.live').forEach(el => {{
    const span = el.querySelector('span');
    if (span && diff < 60) span.textContent += ` (` + diff + `分前)`;
  }});
}}
// セクション折りたたみ
function toggleCollapse(id, btn) {{
  const el = document.getElementById(id);
  if (!el) return;
  const collapsed = el.classList.toggle('collapsed');
  btn.textContent = collapsed ? '▶ 展開' : '▼ 折りたたむ';
}}
// 通知履歴フィルタ
function filterHist(f) {{
  const rows = document.querySelectorAll('#hist-table tbody tr.hrow');
  rows.forEach(tr => {{
    const sev = tr.dataset.sev || '';
    const res = tr.dataset.res || '';
    let show = false;
    if (f === 'all') show = true;
    else if (f === 'CRITICAL') show = sev === 'CRITICAL';
    else if (f === 'WARNING') show = sev === 'WARNING';
    else if (f === 'sent') show = res === 'sent';
    else if (f === 'fail') show = !['sent','suppressed','skipped','webhook_not_set',''].includes(res);
    else if (f === 'suppressed') show = res === 'suppressed';
    tr.style.display = show ? '' : 'none';
  }});
  document.querySelectorAll('.hfilter').forEach(b => {{
    b.classList.toggle('active', b.dataset.filter === f);
  }});
}}
function filterSafe(f) {{
  const rows = document.querySelectorAll('#safe-table tbody tr');
  rows.forEach(tr => {{
    const res = tr.dataset.saferes || '';
    tr.style.display = (f === 'all' || res === f) ? '' : 'none';
  }});
  document.querySelectorAll('[data-safefilter]').forEach(b => {{
    b.classList.toggle('active', b.dataset.safefilter === f);
  }});
}}
function filterExec(f) {{
  const rows = document.querySelectorAll('#exec-table tbody tr');
  rows.forEach(tr => {{
    const res = tr.dataset.exres || '';
    tr.style.display = (f === 'all' || res === f) ? '' : 'none';
  }});
  document.querySelectorAll('[data-exfilter]').forEach(b => {{
    b.classList.toggle('active', b.dataset.exfilter === f);
  }});
}}
function scrollToId(id) {{
  const el = document.getElementById(id);
  if (el) {{ el.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}
}}
function toggleNavGroup(groupId) {{
  const el = document.getElementById(groupId);
  if (!el) return;
  const isHidden = el.style.display === 'none' || el.style.display === '';
  document.querySelectorAll('.nav-group').forEach(g => {{ g.style.display = 'none'; }});
  el.style.display = isHidden ? 'flex' : 'none';
}}
</script>
</body>
</html>"""

    # ─── 後処理: 機械名をポケモン名に一括置換 ───
    # CEOログ・実行記録内に残る生の機械名を表示名に差し替える
    _name_replace_map = {
        "X投稿B":     "ゾロアーク",
        "X投稿":      "ジュペッタ",
        "WP投稿":     "カメックス",
        "コスメライター": "ニンフィア",
        "ポップアップライター": "ハピナス",
        "ミュウツー（コスメ）": "ミュウツーX",
        "ミュウツー（POP）":  "ミュウツーY",
        "カイリュー（旧）":   "カイリュー（旧）",
    }
    for old_name, new_name in _name_replace_map.items():
        html = html.replace(old_name, new_name)

    # ─── 後処理: IT用語 → 平易な日本語 ───
    _term_replace_map = {
        "pending":    "対応待ち",
        "blocked":    "停止中",
        "stale":      "古くなった未処理",
        "queue":      "待ちリスト",
        "duplicate":  "重複",
        "archive":    "保管庫",
        "deploy":     "公開反映",
        "runtime":    "実行環境",
        "monitor":    "監視",
        "alert":      "通知・警報",
        "tracking":   "追跡",
        "ON_TRACK":   "順調",
        "AT_RISK":    "注意",
        "BEHIND":     "遅れ",
    }
    for old_term, new_term in _term_replace_map.items():
        html = html.replace(old_term, new_term)

    return html


def main():
    html = generate()
    OUT.write_text(html)
    size = OUT.stat().st_size
    print(f"[generate_dashboard v2.0] ✅ dashboard.html 生成完了: {size:,} bytes")


if __name__ == "__main__":
    main()
