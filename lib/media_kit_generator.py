"""
媒体資料（Media Kit）自動生成

Usage:
  python3 lib/media_kit_generator.py              # 前月データで生成
  python3 lib/media_kit_generator.py 2026-03      # 指定月
  python3 lib/media_kit_generator.py 2026-03 --json

毎月1日 11:00 JST に cron で実行推奨（月次レポートの後）
"""
import json, sys, os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REVENUE_CONFIG = BASE_DIR / "config" / "revenue_config.json"
SITE_CONFIG = BASE_DIR / "config" / "site_config.json"
KPI_POSTS = BASE_DIR / "logs" / "kpi_posts.jsonl"
KPI_DAILY = BASE_DIR / "logs" / "kpi_daily.jsonl"
OUTPUT_DIR = Path.home() / "monthly_reports"


def load_site_config():
    if SITE_CONFIG.exists():
        return json.loads(SITE_CONFIG.read_text())
    return {}


def load_monthly_stats(month_str):
    """月次統計を集計"""
    from monthly_metrics_aggregator import get_month_range, load_posts, load_daily_kpi
    start, end = get_month_range(month_str)
    posts = load_posts(start, end)
    daily = load_daily_kpi(start, end)

    total_pv = sum(d.get("total_pv", 0) for d in daily)
    total_sessions = sum(d.get("sessions", 0) for d in daily)
    total_users = sum(d.get("users", 0) for d in daily)

    return {
        "month": month_str,
        "total_posts": len(posts),
        "total_pv": total_pv,
        "total_sessions": total_sessions,
        "total_users": total_users,
        "avg_daily_pv": total_pv // max(len(daily), 1),
        "active_days": len(daily),
    }


def load_category_distribution(month_str):
    """カテゴリ別投稿比率"""
    try:
        from monthly_metrics_aggregator import get_month_range, load_posts
        start, end = get_month_range(month_str)
        posts = load_posts(start, end)
    except Exception:
        return {}

    from collections import defaultdict
    cats = defaultdict(int)
    for p in posts:
        for c in p.get("categories", []):
            cats[str(c)] += 1
    return dict(sorted(cats.items(), key=lambda x: -x[1])[:10])


def generate_media_kit(month_str):
    """媒体資料を生成"""
    site = load_site_config()
    domain = site.get("domain", "https://www.kpopjournal.tokyo")
    genre = site.get("genre", "K-POP")

    try:
        stats = load_monthly_stats(month_str)
    except Exception:
        stats = {"month": month_str, "total_posts": 0, "total_pv": 0,
                 "total_sessions": 0, "total_users": 0, "avg_daily_pv": 0, "active_days": 0}

    # 広告メニュー（revenue_config.jsonから）
    rev_config = {}
    if REVENUE_CONFIG.exists():
        try:
            rev_config = json.loads(REVENUE_CONFIG.read_text())
        except Exception:
            pass

    kit = {
        "generated_at": datetime.now().isoformat(),
        "target_month": month_str,
        "site_info": {
            "name": "K-POP JOURNAL",
            "url": domain,
            "genre": genre,
            "language": "日本語",
            "target_audience": "K-POPファン（10代後半〜30代女性中心）",
            "content_types": ["速報ニュース", "解説・考察", "ライブ・イベント情報",
                             "チャートランキング", "カムバック情報", "美容・コスメ", "韓国旅行"],
        },
        "monthly_metrics": stats,
        "features": [
            "AI活用による速報性の高いニュース配信（検知から30分以内）",
            "SEO最適化された高品質記事（検索流入60%以上）",
            "X/Twitter連携によるSNS拡散",
            "毎日安定した更新頻度（4〜8本/日）",
        ],
        "ad_menu": {
            "banner_top": {"name": "トップバナー", "size": "728x90", "position": "記事上部", "price": "応相談"},
            "banner_sidebar": {"name": "サイドバナー", "size": "300x250", "position": "サイドバー", "price": "応相談"},
            "native_ad": {"name": "記事広告", "format": "記事形式", "min_chars": 2000, "price": "応相談"},
            "tieup": {"name": "タイアップ記事", "format": "取材+記事作成", "price": "応相談"},
        },
        "contact": {
            "method": "お問い合わせフォーム or メール",
            "response_time": "2営業日以内",
        },
    }
    return kit


def format_media_kit(kit):
    """Markdown形式で媒体資料を出力"""
    site = kit["site_info"]
    metrics = kit["monthly_metrics"]

    lines = []
    lines.append(f"# {site['name']} 媒体資料")
    lines.append(f"*{kit['target_month']} 実績ベース | 生成日: {kit['generated_at'][:10]}*")
    lines.append("")

    lines.append("## サイト概要")
    lines.append(f"- **サイト名**: {site['name']}")
    lines.append(f"- **URL**: {site['url']}")
    lines.append(f"- **ジャンル**: {site['genre']}")
    lines.append(f"- **言語**: {site['language']}")
    lines.append(f"- **ターゲット**: {site['target_audience']}")
    lines.append("")

    lines.append("## コンテンツカテゴリ")
    for ct in site["content_types"]:
        lines.append(f"- {ct}")
    lines.append("")

    lines.append("## 月間実績")
    lines.append(f"| 指標 | 数値 |")
    lines.append(f"|------|------|")
    lines.append(f"| 月間PV | {metrics['total_pv']:,} |")
    lines.append(f"| 月間投稿数 | {metrics['total_posts']} 本 |")
    lines.append(f"| 日平均PV | {metrics['avg_daily_pv']:,} |")
    lines.append(f"| 稼働日数 | {metrics['active_days']} 日 |")
    lines.append("")

    lines.append("## 特長")
    for f in kit["features"]:
        lines.append(f"- {f}")
    lines.append("")

    lines.append("## 広告メニュー")
    lines.append(f"| メニュー | 仕様 | 掲載位置 | 料金 |")
    lines.append(f"|---------|------|---------|------|")
    for key, ad in kit["ad_menu"].items():
        spec = ad.get("size", ad.get("format", ""))
        lines.append(f"| {ad['name']} | {spec} | {ad.get('position', '')} | {ad['price']} |")
    lines.append("")

    lines.append("## お問い合わせ")
    lines.append(f"- {kit['contact']['method']}")
    lines.append(f"- 返信: {kit['contact']['response_time']}")
    lines.append("")
    lines.append("---")
    lines.append(f"*本資料は自動生成されています。最新データは直接お問い合わせください。*")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--json":
        month = sys.argv[1]
    else:
        now = datetime.now()
        if now.month == 1:
            month = f"{now.year - 1}-12"
        else:
            month = f"{now.year}-{now.month - 1:02d}"

    kit = generate_media_kit(month)

    if "--json" in sys.argv:
        print(json.dumps(kit, ensure_ascii=False, indent=2))
    else:
        md = format_media_kit(kit)
        print(md)

        # ファイル保存
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"media_kit_{month}.md"
        output_path.write_text(md)
        print(f"\n保存先: {output_path}")
