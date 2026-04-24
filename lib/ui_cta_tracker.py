#!/usr/bin/env python3
"""
lib/ui_cta_tracker.py
イルミーゼ — CTAクリック実測モジュール

役割:
  1. CTAクリック計測用 JavaScript スニペットを生成
     → WP カスタムCSS API 経由で <style>+<script> として注入
  2. GA4 Data API から CTAイベントを日次集計して取得
  3. logs/ui_cta_events.jsonl に日次スナップを記録

GA4 イベント定義:
  cta_click_top        記事冒頭CTA クリック
  cta_click_middle     記事中盤CTA クリック
  cta_click_bottom     記事末尾CTA クリック
  cta_click_fixed_bar  固定CTAバー クリック
  fixed_cta_impression 固定CTAバー 表示（ページロード時）
  fixed_cta_close      固定CTAバー 閉じる

イベントパラメータ (各クリックに付与):
  cta_position   : top / middle / bottom / fixed_bar
  article_type   : 速報 / ランキング / プロフィール / 解説
  page_path      : /slug/

Usage:
  python3 lib/ui_cta_tracker.py fetch          # GA4からCTAイベント取得→ログ記録
  python3 lib/ui_cta_tracker.py report         # 直近7日のCTAレポート
  python3 lib/ui_cta_tracker.py js             # 注入JSスニペットを表示
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent
LOGS       = BASE_DIR / "logs"
GMETRICS   = BASE_DIR / "google_metrics"

UI_CTA_LOG     = LOGS / "ui_cta_events.jsonl"
METRICS_FILE   = GMETRICS / "metrics_yesterday.json"
SERVICE_ACCT   = GMETRICS / "service_account.json"

GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "493983919")
JST = timezone(timedelta(hours=9))

# CTA位置の定義
CTA_POSITIONS = ["top", "middle", "bottom", "fixed_bar"]

# GA4イベント名 → 内部ラベル
GA4_EVENT_MAP = {
    "cta_click_top":        "冒頭CTA",
    "cta_click_middle":     "中盤CTA",
    "cta_click_bottom":     "末尾CTA",
    "cta_click_fixed_bar":  "固定CTAバー",
    "fixed_cta_impression": "固定CTAバー表示",
    "fixed_cta_close":      "固定CTAバー閉じる",
}

# 記事タイプ→article_typeパラメータ値のマッピング（JSと同期）
ARTICLE_TYPE_JS_MAP = {
    "speed":       "速報",
    "guide":       "解説",
    "explanation": "解説",
}


# ─── JS スニペット生成 ─────────────────────────────────────────

def build_cta_tracking_js(cta_label: str = "最新K-POPニュースをチェック") -> str:
    """
    CTAクリック追跡JSを生成する。
    Cocoonテーマが読み込む gtag() を前提にしているため、
    gtag.js の追加読み込みは不要。

    CTA要素への紐付け:
      - .cta-box a, .revenue-cta a → 記事内CTA (position: top/middle/bottom は
        DOM上のH2見出し数で判定)
      - #kpj-fixed-cta a           → 固定CTAバー
      - button#kpj-fixed-close     → 固定CTAバー閉じるボタン
    """
    return f"""
<!-- イルミーゼ CTA計測スクリプト v3 -->
<script>
(function() {{
  'use strict';

  // gtag が使えない環境では何もしない（フェイルセーフ）
  if (typeof gtag !== 'function' && typeof dataLayer === 'undefined') return;

  var _gtag = typeof gtag === 'function' ? gtag : function(cmd, event, params) {{
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(arguments);
  }};

  // ─ ページ情報の取得 ─
  var pagePath = window.location.pathname;
  var bodyClasses = document.body.className || '';
  var articleType = '解説';
  var articleTypeBadge = document.querySelector('.article-type');
  if (articleTypeBadge) {{
    if (articleTypeBadge.classList.contains('speed')) articleType = '速報';
    else if (articleTypeBadge.classList.contains('guide')) articleType = '解説';
  }}

  // ─ CTA位置判定（記事内の相対位置から top/middle/bottom を判定） ─
  function getCtaPosition(el) {{
    var content = document.querySelector('.entry-content');
    if (!content) return 'middle';
    var contentH  = content.offsetHeight || 1;
    var elTop     = el.getBoundingClientRect().top - content.getBoundingClientRect().top;
    var ratio     = elTop / contentH;
    if (ratio < 0.3)  return 'top';
    if (ratio < 0.65) return 'middle';
    return 'bottom';
  }}

  // ─ 記事内CTAボタン計測 ─
  function attachCtaClicks() {{
    var ctaLinks = document.querySelectorAll('.cta-box a, .revenue-cta a, .kpj-cta-btn');
    ctaLinks.forEach(function(link) {{
      link.addEventListener('click', function(e) {{
        var pos = getCtaPosition(link);
        var eventName = 'cta_click_' + pos;
        _gtag('event', eventName, {{
          cta_position:  pos,
          article_type:  articleType,
          page_path:     pagePath,
          cta_label:     link.textContent.trim().substring(0, 50),
        }});
      }});
    }});
  }}

  // ─ 固定CTAバー計測 ─
  function attachFixedCtaEvents() {{
    var bar = document.getElementById('kpj-fixed-cta');
    if (!bar) return;

    // 表示イベント（ページロード直後）
    _gtag('event', 'fixed_cta_impression', {{
      article_type: articleType,
      page_path:    pagePath,
    }});

    // クリックイベント
    var barLink = bar.querySelector('a');
    if (barLink) {{
      barLink.addEventListener('click', function() {{
        _gtag('event', 'cta_click_fixed_bar', {{
          cta_position: 'fixed_bar',
          article_type: articleType,
          page_path:    pagePath,
          cta_label:    barLink.textContent.trim().substring(0, 50),
        }});
      }});
    }}

    // 閉じるボタン（存在すれば）
    var closeBtn = document.getElementById('kpj-fixed-close');
    if (closeBtn) {{
      closeBtn.addEventListener('click', function() {{
        bar.style.display = 'none';
        document.body.style.paddingBottom = '0';
        _gtag('event', 'fixed_cta_close', {{
          article_type: articleType,
          page_path:    pagePath,
        }});
      }});
    }}
  }}

  // lazyload フェードイン
  document.querySelectorAll('img[loading="lazy"]').forEach(function(img) {{
    if (img.complete) {{ img.classList.add('loaded'); }}
    else {{ img.addEventListener('load', function() {{ img.classList.add('loaded'); }}); }}
  }});

  // 記事ページのみ固定CTAバーを表示 & 計測
  var isSingle = bodyClasses.indexOf('single') !== -1;
  if (isSingle) {{
    var bar = document.getElementById('kpj-fixed-cta');
    if (bar) bar.style.display = 'flex';
    attachFixedCtaEvents();
    attachCtaClicks();
  }}

}})();
</script>
"""


def build_fixed_cta_html(cta_label: str = "最新K-POPニュースをチェック") -> str:
    """固定CTAバーHTML（閉じるボタン付き）"""
    return f"""
<!-- イルミーゼ管理: モバイル固定CTAバー -->
<div id="kpj-fixed-cta" style="display:none">
  <a href="https://www.kpopjournal.tokyo/" rel="noopener">📰 {cta_label}</a>
  <button id="kpj-fixed-close" style="background:none;border:none;color:#fff;font-size:18px;padding:0 12px;cursor:pointer;opacity:0.7;line-height:56px" aria-label="閉じる">✕</button>
</div>
"""


# ─── GA4 CTAイベント取得 ──────────────────────────────────────

def fetch_cta_events(target_date: date = None) -> dict:
    """
    GA4 Data API から CTAイベント数を取得する。
    サービスアカウント認証を使用（fetch_yesterday_metrics.py と同じ方式）。

    戻り値:
    {
      "date": "2026-04-14",
      "cta_click_top": 12,
      "cta_click_middle": 8,
      "cta_click_bottom": 15,
      "cta_click_fixed_bar": 45,
      "fixed_cta_impression": 320,
      "fixed_cta_close": 28,
      "total_cta_clicks": 80,
      "fixed_cta_click_rate": 0.141,   # クリック÷表示
      "fixed_cta_close_rate": 0.088,   # 閉じる÷表示
      "cta_ctr_real": null,            # クリック÷PV (PVはGA4summaryから)
      "type_breakdown": { "速報": {...}, ... },
    }
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    date_str = target_date.isoformat()

    try:
        from google.oauth2 import service_account
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest, FilterExpression,
            Filter, FilterExpressionList
        )
    except ImportError:
        return {"error": "google-analytics-data 未インストール", "date": date_str}

    if not SERVICE_ACCT.exists():
        return {"error": "service_account.json が見つかりません", "date": date_str}

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(SERVICE_ACCT),
            scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
        client = BetaAnalyticsDataClient(credentials=creds)

        # ─ イベント名別の合計取得 ─
        req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            dimensions=[
                Dimension(name="eventName"),
            ],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
        )
        res = client.run_report(req)

        event_counts = {}
        for row in res.rows:
            ev   = row.dimension_values[0].value
            cnt  = int(row.metric_values[0].value)
            if ev in GA4_EVENT_MAP:
                event_counts[ev] = cnt

        # ─ 記事タイプ別CTA内訳 (article_typeカスタムパラメータで分解) ─
        type_req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            dimensions=[
                Dimension(name="eventName"),
                Dimension(name="customEvent:article_type"),
            ],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
        )
        type_res = client.run_report(type_req)

        type_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in type_res.rows:
            ev        = row.dimension_values[0].value
            art_type  = row.dimension_values[1].value or "不明"
            cnt       = int(row.metric_values[0].value)
            if ev in GA4_EVENT_MAP and "cta_click" in ev:
                pos = ev.replace("cta_click_", "")
                type_breakdown[art_type][pos] += cnt

        # ─ PV取得（CTR計算用） ─
        pv = 0
        try:
            metrics_data = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
            pv = int(metrics_data.get("ga4", {}).get("summary", {}).get("pageviews", 0))
        except Exception:
            pass

        # ─ 集計 ─
        clicks_top    = event_counts.get("cta_click_top", 0)
        clicks_mid    = event_counts.get("cta_click_middle", 0)
        clicks_bot    = event_counts.get("cta_click_bottom", 0)
        clicks_fixed  = event_counts.get("cta_click_fixed_bar", 0)
        impressions   = event_counts.get("fixed_cta_impression", 0)
        closes        = event_counts.get("fixed_cta_close", 0)
        total_clicks  = clicks_top + clicks_mid + clicks_bot + clicks_fixed

        fixed_click_rate = round(clicks_fixed / impressions, 4) if impressions > 0 else 0.0
        fixed_close_rate = round(closes / impressions, 4) if impressions > 0 else 0.0
        cta_ctr_real     = round(total_clicks / pv, 4) if pv > 0 else None

        return {
            "date":                    date_str,
            "cta_click_top":           clicks_top,
            "cta_click_middle":        clicks_mid,
            "cta_click_bottom":        clicks_bot,
            "cta_click_fixed_bar":     clicks_fixed,
            "fixed_cta_impression":    impressions,
            "fixed_cta_close":         closes,
            "total_cta_clicks":        total_clicks,
            "fixed_cta_click_rate":    fixed_click_rate,
            "fixed_cta_close_rate":    fixed_close_rate,
            "cta_ctr_real":            cta_ctr_real,
            "pageviews":               pv,
            "type_breakdown":          {k: dict(v) for k, v in type_breakdown.items()},
            "source": "ga4_real",
        }

    except Exception as e:
        return {"error": str(e), "date": date_str, "source": "ga4_error"}


def fetch_and_save(target_date: date = None) -> dict:
    """CTAイベントを取得してlogs/ui_cta_events.jsonlに追記する"""
    result = fetch_cta_events(target_date)
    result["fetched_at"] = datetime.now(JST).isoformat()

    UI_CTA_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(UI_CTA_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    return result


def get_avg_cta_real(days_back: int = 7) -> dict:
    """
    直近N日間の実CTA指標平均を返す。
    データがなければ None を返す（フォールバック判定用）。
    """
    if not UI_CTA_LOG.exists():
        return {"available": False, "reason": "ログファイルなし"}

    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    records = []
    for line in UI_CTA_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("date", "") >= cutoff and "error" not in r and r.get("source") == "ga4_real":
                records.append(r)
        except Exception:
            pass

    if not records:
        return {"available": False, "reason": f"直近{days_back}日に実測データなし"}

    def _avg(key):
        vals = [r[key] for r in records if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    # 記事タイプ×CTA位置 クロス集計
    type_pos_totals: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        for art_type, pos_dict in r.get("type_breakdown", {}).items():
            for pos, cnt in pos_dict.items():
                type_pos_totals[art_type][pos].append(cnt)
    type_pos_avg = {
        art: {pos: round(sum(vals)/len(vals), 2) for pos, vals in pos_d.items()}
        for art, pos_d in type_pos_totals.items()
    }

    # 記事タイプ別の最優勝CTA位置
    best_cta_by_type = {}
    for art, pos_d in type_pos_avg.items():
        if pos_d:
            best_cta_by_type[art] = max(pos_d, key=lambda k: pos_d[k])

    return {
        "available":             True,
        "days_back":             days_back,
        "sample_days":           len(records),
        "avg_total_cta_clicks":  _avg("total_cta_clicks"),
        "avg_cta_ctr_real":      _avg("cta_ctr_real"),
        "avg_fixed_click_rate":  _avg("fixed_cta_click_rate"),
        "avg_fixed_close_rate":  _avg("fixed_cta_close_rate"),
        "avg_cta_click_top":     _avg("cta_click_top"),
        "avg_cta_click_middle":  _avg("cta_click_middle"),
        "avg_cta_click_bottom":  _avg("cta_click_bottom"),
        "avg_cta_click_fixed":   _avg("cta_click_fixed_bar"),
        "type_pos_avg":          type_pos_avg,
        "best_cta_by_type":      best_cta_by_type,
    }


# ─── CLI ──────────────────────────────────────────────────────

def cmd_fetch(args):
    target = date.fromisoformat(args.date) if args.date else None
    print(f"🔍 GA4からCTAイベントを取得中... ({(target or date.today() - timedelta(days=1)).isoformat()})")
    result = fetch_and_save(target)
    if "error" in result:
        print(f"❌ 取得失敗: {result['error']}")
        if "未インストール" in result.get("error", ""):
            print("   → pip install google-analytics-data")
        sys.exit(1)
    print(f"✅ 取得完了")
    print(f"  CTAクリック合計: {result['total_cta_clicks']}")
    print(f"  冒頭: {result['cta_click_top']}  中盤: {result['cta_click_middle']}  末尾: {result['cta_click_bottom']}  固定バー: {result['cta_click_fixed_bar']}")
    print(f"  固定バー表示: {result['fixed_cta_impression']}  クリック率: {result['fixed_cta_click_rate']:.1%}  閉じる率: {result['fixed_cta_close_rate']:.1%}")
    if result.get("cta_ctr_real") is not None:
        print(f"  CTA実CTR: {result['cta_ctr_real']:.4f} (PV={result['pageviews']})")
    if result.get("type_breakdown"):
        print(f"  記事タイプ別: {json.dumps(result['type_breakdown'], ensure_ascii=False)}")


def cmd_report(args):
    days = args.days or 7
    avg = get_avg_cta_real(days_back=days)
    print(f"{'='*56}")
    print(f"  イルミーゼ CTAクリック実測レポート (直近{days}日)")
    print(f"{'='*56}")

    if not avg["available"]:
        print(f"  ⚠️  {avg['reason']}")
        print("  → まず `python3 lib/ui_cta_tracker.py fetch` を実行してください")
        print("  → GA4でCTAイベントが計測されていない場合はJSスニペット注入が必要です")
        print(f"{'='*56}")
        return

    print(f"  データ期間: {days}日 (実測: {avg['sample_days']}日分)")
    print()
    print("── CTA実クリック ──")
    print(f"  合計クリック/日: {avg['avg_total_cta_clicks']}")
    print(f"  実CTA率 (clicks/PV): {avg['avg_cta_ctr_real']:.4f}" if avg['avg_cta_ctr_real'] else "  実CTA率: データなし")
    print(f"  冒頭CTA:  {avg['avg_cta_click_top']}/日")
    print(f"  中盤CTA:  {avg['avg_cta_click_middle']}/日")
    print(f"  末尾CTA:  {avg['avg_cta_click_bottom']}/日")
    print(f"  固定バー: {avg['avg_cta_click_fixed']}/日")
    print()
    print("── 固定CTAバー効果 ──")
    print(f"  表示/日:   {avg.get('avg_fixed_impressions', '—')}")
    print(f"  クリック率: {avg['avg_fixed_click_rate']:.1%}")
    print(f"  閉じる率:   {avg['avg_fixed_close_rate']:.1%}")
    # 閉じる率が高い場合は警告
    if avg['avg_fixed_close_rate'] and avg['avg_fixed_close_rate'] > 0.15:
        print(f"  ⚠️  閉じる率が高い({avg['avg_fixed_close_rate']:.1%}) → バーが邪魔と判断されている可能性")
    print()
    if avg.get("type_pos_avg"):
        print("── 記事タイプ×CTA位置 クロス集計 (日平均クリック) ──")
        for art_type, pos_d in avg["type_pos_avg"].items():
            best = avg["best_cta_by_type"].get(art_type, "—")
            pos_str = "  ".join(f"{p}:{v:.1f}" for p, v in sorted(pos_d.items()))
            print(f"  {art_type:<10} {pos_str}  ★最強: {best}")
    print(f"{'='*56}")


def cmd_js(args):
    """JSスニペットを標準出力に表示（確認・手動注入用）"""
    print(build_cta_tracking_js())
    print()
    print(build_fixed_cta_html())


def main():
    parser = argparse.ArgumentParser(description="イルミーゼ CTAクリック実測モジュール")
    sub = parser.add_subparsers(dest="command")
    p_fetch = sub.add_parser("fetch", help="GA4からCTAイベントを取得・記録")
    p_fetch.add_argument("--date", help="取得日 YYYY-MM-DD (省略: 昨日)")
    p_report = sub.add_parser("report", help="CTAレポート表示")
    p_report.add_argument("--days", type=int, default=7)
    sub.add_parser("js", help="JSスニペット表示")

    args = parser.parse_args()
    dispatch = {"fetch": cmd_fetch, "report": cmd_report, "js": cmd_js}
    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
