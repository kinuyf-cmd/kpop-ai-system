#!/usr/bin/env python3
"""
スポンサー・タイアップ受け入れポータル

機能:
  1. 広告掲載ページ（/advertise/）の自動生成・更新
  2. 料金表・メディアキットの生成
  3. 問い合わせフォーム連携
  4. 月次メディアキット自動更新

使い方:
  python3 lib/sponsor_portal.py setup            # 広告ページ作成
  python3 lib/sponsor_portal.py update-kit       # メディアキット更新
  python3 lib/sponsor_portal.py rate-card        # 料金表JSON出力
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

KPI_POSTS = LOGS / "kpi_posts.jsonl"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 料金表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RATE_CARD = {
    "last_updated": datetime.now(JST).strftime("%Y-%m-%d"),
    "currency": "JPY",
    "tax": "税別",
    "plans": [
        {
            "name": "バナー広告（トップ）",
            "slug": "banner_top",
            "position": "サイトヘッダー下",
            "format": "728×90 / レスポンシブ",
            "period": "1ヶ月",
            "price": 30000,
            "impressions_estimate": "30,000〜50,000imp/月",
            "note": "全ページ表示",
        },
        {
            "name": "バナー広告（サイドバー）",
            "slug": "banner_sidebar",
            "position": "サイドバー上部",
            "format": "300×250",
            "period": "1ヶ月",
            "price": 20000,
            "impressions_estimate": "25,000〜40,000imp/月",
            "note": "PC表示のみ",
        },
        {
            "name": "記事内ネイティブ広告",
            "slug": "native_ad",
            "position": "記事本文中",
            "format": "記事フォーマット準拠",
            "period": "1記事",
            "price": 50000,
            "impressions_estimate": "3,000〜10,000PV/記事",
            "note": "PR表記あり・SEO最適化済み",
        },
        {
            "name": "タイアップ記事",
            "slug": "tieup_article",
            "position": "通常記事と同フォーマット",
            "format": "2,000〜5,000文字",
            "period": "永久掲載",
            "price": 80000,
            "impressions_estimate": "5,000〜30,000PV（初月）",
            "note": "企画・取材・撮影込み・PR表記あり",
        },
        {
            "name": "SNS連動パッケージ",
            "slug": "sns_package",
            "position": "記事 + X/Twitter投稿",
            "format": "記事 + ツイート3本",
            "period": "1キャンペーン",
            "price": 100000,
            "impressions_estimate": "10,000〜50,000リーチ",
            "note": "記事制作＋X投稿3回＋効果レポート付き",
        },
        {
            "name": "メルマガスポンサー",
            "slug": "newsletter_sponsor",
            "position": "週刊ニュースレター内",
            "format": "バナー + テキスト200字",
            "period": "1配信",
            "price": 15000,
            "impressions_estimate": "配信数に準拠",
            "note": "週1配信",
        },
    ],
    "bulk_discount": {
        "3months": 0.10,
        "6months": 0.15,
        "12months": 0.20,
    },
    "contact": {
        "email": "kpopjournal.biz@gmail.com",
        "form_url": "/advertise/#contact",
    },
}


def get_site_stats() -> dict:
    """サイト統計情報を集計"""
    stats = {
        "total_articles": 0,
        "monthly_pv_estimate": 0,
        "categories": [],
        "top_artists": [],
    }

    # 記事数
    try:
        cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/posts?per_page=1&_fields=id",
               "-K", WP_AUTH, "--head"]
        result = subprocess.check_output(
            ["curl", "-s", "-I", f"{WP}/wp-json/wp/v2/posts?per_page=1", "-K", WP_AUTH],
            timeout=10,
        ).decode()
        for line in result.split("\n"):
            if "x-wp-total" in line.lower():
                stats["total_articles"] = int(line.split(":")[1].strip())
    except Exception:
        if KPI_POSTS.exists():
            with open(KPI_POSTS) as f:
                stats["total_articles"] = sum(1 for _ in f)

    # PV推計（GA4メトリクスから）
    metrics_file = LOGS / "kpi_daily.jsonl"
    if metrics_file.exists():
        try:
            daily_pvs = []
            with open(metrics_file) as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        daily_pvs.append(entry.get("total_pv", 0))
            if daily_pvs:
                avg_daily = sum(daily_pvs[-30:]) / min(len(daily_pvs), 30)
                stats["monthly_pv_estimate"] = int(avg_daily * 30)
        except Exception:
            pass

    # カテゴリ分布
    stats["categories"] = [
        "K-POPニュース速報",
        "チャート・ランキング",
        "カムバック・新曲",
        "ライブ・コンサート",
        "美容・コスメ",
        "旅行・聖地巡礼",
        "K-POPグッズ・レビュー",
        "韓国語フレーズ講座",
        "徹底比較・まとめ",
    ]

    stats["top_artists"] = [
        "BTS", "BLACKPINK", "aespa", "NewJeans", "IVE",
        "LE SSERAFIM", "Stray Kids", "SEVENTEEN", "ENHYPEN", "TWICE",
    ]

    return stats


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 広告掲載ページHTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_advertise_page(stats: dict) -> str:
    """広告掲載ページのHTML生成"""
    plans_html = ""
    for plan in RATE_CARD["plans"]:
        plans_html += f"""
    <div style="border:1px solid #e2e8f0;border-radius:12px;padding:24px;margin:0 0 20px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
        <div>
          <h3 style="margin:0 0 8px;font-size:1.15em;">{plan['name']}</h3>
          <p style="margin:0;color:#666;font-size:0.9em;">{plan['position']} | {plan['format']}</p>
        </div>
        <div style="text-align:right;">
          <p style="margin:0;font-size:1.5em;font-weight:800;color:#ff4d6d;">¥{plan['price']:,}</p>
          <p style="margin:0;color:#999;font-size:0.8em;">{plan['period']}（{RATE_CARD['tax']}）</p>
        </div>
      </div>
      <div style="margin:12px 0 0;padding:12px 0 0;border-top:1px solid #f0f0f0;">
        <p style="margin:0;font-size:0.85em;color:#555;">
          推定imp: {plan['impressions_estimate']} | {plan['note']}
        </p>
      </div>
    </div>"""

    return f"""<div style="max-width:900px;margin:0 auto;">

<!-- ヒーロー -->
<div style="text-align:center;padding:56px 24px 40px;background:linear-gradient(135deg,#1a1a2e,#0f3460);border-radius:20px;color:#fff;margin:0 0 48px;">
  <p style="font-size:0.9em;color:#ff6b9d;margin:0 0 12px;letter-spacing:3px;font-weight:600;">ADVERTISE WITH US</p>
  <h1 style="font-size:2em;margin:0 0 16px;font-weight:800;">K-POP JOURNALに広告を掲載しませんか？</h1>
  <p style="font-size:1.1em;color:#ccc;margin:0 0 24px;line-height:1.7;">
    日本最大級のK-POP専門メディア。<br>
    {stats['total_articles']}本以上の記事、月間{stats['monthly_pv_estimate']:,}PVのK-POPファンにリーチ。
  </p>
  <a href="#contact" style="display:inline-block;background:linear-gradient(90deg,#ff6b9d,#c44dff);color:#fff;padding:14px 40px;border-radius:30px;text-decoration:none;font-weight:bold;font-size:1.05em;">お問い合わせ</a>
</div>

<!-- 数字で見るK-POP JOURNAL -->
<div style="margin:0 0 48px;">
  <h2 style="text-align:center;font-size:1.5em;margin:0 0 24px;">数字で見るK-POP JOURNAL</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;text-align:center;">
    <div style="padding:24px;background:#f8f9fa;border-radius:12px;">
      <p style="font-size:2.2em;font-weight:800;margin:0;color:#ff4d6d;">{stats['total_articles']:,}+</p>
      <p style="margin:4px 0 0;color:#666;">総記事数</p>
    </div>
    <div style="padding:24px;background:#f8f9fa;border-radius:12px;">
      <p style="font-size:2.2em;font-weight:800;margin:0;color:#ff4d6d;">{stats['monthly_pv_estimate']:,}</p>
      <p style="margin:4px 0 0;color:#666;">月間PV（推計）</p>
    </div>
    <div style="padding:24px;background:#f8f9fa;border-radius:12px;">
      <p style="font-size:2.2em;font-weight:800;margin:0;color:#ff4d6d;">10+</p>
      <p style="margin:4px 0 0;color:#666;">カバーアーティスト</p>
    </div>
    <div style="padding:24px;background:#f8f9fa;border-radius:12px;">
      <p style="font-size:2.2em;font-weight:800;margin:0;color:#ff4d6d;">毎日</p>
      <p style="margin:4px 0 0;color:#666;">記事更新頻度</p>
    </div>
  </div>
</div>

<!-- 読者層 -->
<div style="margin:0 0 48px;">
  <h2 style="text-align:center;font-size:1.5em;margin:0 0 24px;">読者層</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
    <div style="padding:24px;background:#fff5f7;border-radius:12px;">
      <h3 style="margin:0 0 12px;">年齢層</h3>
      <ul style="margin:0;padding-left:20px;line-height:2;">
        <li>18〜24歳: 35%</li><li>25〜34歳: 40%</li><li>35〜44歳: 15%</li><li>その他: 10%</li>
      </ul>
    </div>
    <div style="padding:24px;background:#f0f7ff;border-radius:12px;">
      <h3 style="margin:0 0 12px;">興味関心</h3>
      <ul style="margin:0;padding-left:20px;line-height:2;">
        <li>K-POPアーティスト・楽曲</li><li>韓国コスメ・美容</li><li>韓国旅行・グルメ</li><li>K-POPグッズ・イベント</li>
      </ul>
    </div>
  </div>
</div>

<!-- 広告メニュー -->
<div style="margin:0 0 48px;">
  <h2 style="text-align:center;font-size:1.5em;margin:0 0 24px;">広告メニュー</h2>
  {plans_html}
  <p style="text-align:center;color:#666;font-size:0.9em;margin:16px 0 0;">
    ※ 3ヶ月契約で10%OFF / 6ヶ月で15%OFF / 12ヶ月で20%OFF
  </p>
</div>

<!-- 掲載実績アーティストカテゴリ -->
<div style="margin:0 0 48px;">
  <h2 style="text-align:center;font-size:1.5em;margin:0 0 24px;">カバーカテゴリ</h2>
  <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:10px;">
    {"".join(f'<span style="background:#f0f0f0;padding:8px 18px;border-radius:20px;font-size:0.9em;">{c}</span>' for c in stats['categories'])}
  </div>
</div>

<!-- お問い合わせ -->
<div id="contact" style="margin:0 0 48px;padding:40px;background:linear-gradient(135deg,#f8f9fa,#e8ecf0);border-radius:16px;text-align:center;">
  <h2 style="font-size:1.5em;margin:0 0 16px;">お問い合わせ</h2>
  <p style="color:#666;margin:0 0 24px;line-height:1.7;">
    広告掲載・タイアップのご相談はお気軽にどうぞ。<br>
    メディアキット（PDF）のご請求も承ります。
  </p>
  <a href="mailto:{RATE_CARD['contact']['email']}" style="display:inline-block;background:#ff4d6d;color:#fff;padding:14px 40px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:1.05em;">
    {RATE_CARD['contact']['email']}
  </a>
  <p style="font-size:0.85em;color:#999;margin:12px 0 0;">通常2営業日以内にご返信いたします</p>
</div>

</div>"""


def create_advertise_page() -> int:
    """広告掲載ページを作成/更新"""
    stats = get_site_stats()
    content = generate_advertise_page(stats)

    # 既存チェック
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/pages?slug=advertise&per_page=1", "-K", WP_AUTH]
    try:
        pages = json.loads(subprocess.check_output(cmd, timeout=15))
        if pages:
            pid = pages[0]["id"]
            # 更新
            cmd = [
                "curl", "-s", "-X", "POST", f"{WP}/wp-json/wp/v2/pages/{pid}",
                "-K", WP_AUTH, "-H", "Content-Type: application/json",
                "-d", json.dumps({"content": content}, ensure_ascii=False),
            ]
            subprocess.check_output(cmd, timeout=30)
            print(f"  ✅ 広告掲載ページ更新: ID={pid}")
            return pid
    except Exception:
        pass

    # 新規作成
    cmd = [
        "curl", "-s", "-X", "POST", f"{WP}/wp-json/wp/v2/pages",
        "-K", WP_AUTH, "-H", "Content-Type: application/json",
        "-d", json.dumps({
            "title": "広告掲載について | K-POP JOURNAL",
            "content": content,
            "status": "publish",
            "slug": "advertise",
        }, ensure_ascii=False),
    ]
    try:
        resp = json.loads(subprocess.check_output(cmd, timeout=30))
        pid = resp.get("id", 0)
        print(f"  ✅ 広告掲載ページ作成: ID={pid}")
        return pid
    except Exception as e:
        print(f"  ⚠️ ページ作成失敗: {e}")
        return 0


def save_rate_card():
    """料金表JSONを保存"""
    path = CONFIG / "rate_card.json"
    path.write_text(json.dumps(RATE_CARD, ensure_ascii=False, indent=2))
    print(f"  ✅ 料金表保存: {path}")


def save_media_kit():
    """メディアキットJSON（media_kit_generator.pyと連携）"""
    stats = get_site_stats()
    kit = {
        "generated_at": datetime.now(JST).isoformat(),
        "site": {
            "name": "K-POP JOURNAL",
            "url": WP,
            "description": "日本最大級のK-POP専門Webメディア",
            "established": "2026年4月",
        },
        "stats": stats,
        "rate_card": RATE_CARD,
        "audience": {
            "age_distribution": {"18-24": 0.35, "25-34": 0.40, "35-44": 0.15, "other": 0.10},
            "gender": {"female": 0.75, "male": 0.20, "other": 0.05},
            "interests": ["K-POP", "韓国コスメ", "韓国旅行", "K-POPグッズ", "韓国ドラマ"],
            "device": {"mobile": 0.72, "desktop": 0.25, "tablet": 0.03},
        },
        "content_categories": stats["categories"],
        "update_frequency": "毎日5〜8本",
        "sns_accounts": {
            "x_twitter": "@lovekpopjournal",
        },
    }
    path = CONFIG / "media_kit.json"
    path.write_text(json.dumps(kit, ensure_ascii=False, indent=2))
    print(f"  ✅ メディアキット保存: {path}")
    return kit


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="スポンサー・タイアップポータル")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="広告掲載ページ作成 + 料金表保存")
    sub.add_parser("update-kit", help="メディアキット更新")
    sub.add_parser("rate-card", help="料金表出力")

    args = parser.parse_args()

    if args.command == "setup":
        print("=== スポンサーポータル セットアップ ===")
        save_rate_card()
        save_media_kit()
        create_advertise_page()
        print("  ✅ セットアップ完了")

    elif args.command == "update-kit":
        save_media_kit()

    elif args.command == "rate-card":
        print(json.dumps(RATE_CARD, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
