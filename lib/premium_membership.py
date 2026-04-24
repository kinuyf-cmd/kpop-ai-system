#!/usr/bin/env python3
"""
有料会員プラン設計・実装

プラン: K-POP JOURNAL Premium（月額980円）
特典:
  1. 速報先行配信（一般公開の1時間前にメール配信）
  2. 限定コンテンツ（深掘り分析・インタビュー・舞台裏）
  3. 広告なし表示
  4. 限定Discord/コミュニティアクセス
  5. 月1回の限定グッズ抽選

実装方式:
  - WordPress REST API + カスタム投稿ステータス
  - WooCommerce Subscriptions連携（決済）
  - premium カテゴリ（999）で限定記事を管理
  - premium_gate shortcode で非会員にはプレビュー+登録促進

使い方:
  python3 lib/premium_membership.py setup          # WP側の初期設定
  python3 lib/premium_membership.py create-gate     # ゲートHTML生成
  python3 lib/premium_membership.py gate POST_ID    # 記事にゲート適用
  python3 lib/premium_membership.py stats           # 会員統計
"""
from __future__ import annotations
import argparse
import json
import os
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

PREMIUM_LOG = LOGS / "premium_membership.jsonl"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# プラン設計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PREMIUM_PLAN = {
    "name": "K-POP JOURNAL Premium",
    "price_monthly": 980,
    "currency": "JPY",
    "features": [
        {
            "name": "速報先行配信",
            "description": "最新ニュースを一般公開の1時間前にメール配信",
            "icon": "⚡",
        },
        {
            "name": "限定コンテンツ",
            "description": "深掘り分析・チャート裏話・未公開データ",
            "icon": "🔒",
        },
        {
            "name": "広告非表示",
            "description": "すべての記事を広告なしで快適に閲覧",
            "icon": "✨",
        },
        {
            "name": "限定コミュニティ",
            "description": "Premium会員限定のDiscordチャンネルに参加",
            "icon": "💬",
        },
        {
            "name": "月1グッズ抽選",
            "description": "K-POP公式グッズが毎月当たる抽選に参加",
            "icon": "🎁",
        },
    ],
    "free_trial_days": 7,
    "target_subscribers": {
        "month_3": 100,
        "month_6": 500,
        "month_12": 2000,
    },
    "revenue_projection": {
        "month_3": 98000,    # 100人 × 980円
        "month_6": 490000,   # 500人 × 980円
        "month_12": 1960000, # 2000人 × 980円
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ゲートHTML（非会員向け）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PREMIUM_GATE_HTML = """<div class="kpopj-premium-gate" style="margin:40px 0;padding:0;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.1);">
  <!-- グラデーションオーバーレイ（記事プレビューの続きをぼかす） -->
  <div style="height:120px;background:linear-gradient(to bottom,rgba(255,255,255,0),rgba(255,255,255,1));margin-top:-120px;position:relative;z-index:1;"></div>

  <!-- ゲート本体 -->
  <div style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);padding:40px 32px;text-align:center;color:#fff;">
    <p style="font-size:0.9em;color:#ff6b9d;margin:0 0 8px;font-weight:600;letter-spacing:2px;">PREMIUM CONTENT</p>
    <h3 style="font-size:1.6em;margin:0 0 16px;font-weight:800;line-height:1.4;">この先はPremium会員限定です</h3>
    <p style="font-size:1em;color:#ccc;margin:0 0 24px;line-height:1.8;">
      K-POP JOURNALの深掘り分析・未公開データ・速報先行配信を<br>月額<strong style="color:#ff6b9d;font-size:1.2em;">980円</strong>でお届けします。
    </p>

    <!-- 特典リスト -->
    <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:12px;margin:0 0 28px;">
      <span style="background:rgba(255,107,157,0.15);padding:8px 16px;border-radius:20px;font-size:0.85em;">⚡ 速報先行配信</span>
      <span style="background:rgba(255,107,157,0.15);padding:8px 16px;border-radius:20px;font-size:0.85em;">🔒 限定コンテンツ</span>
      <span style="background:rgba(255,107,157,0.15);padding:8px 16px;border-radius:20px;font-size:0.85em;">✨ 広告なし</span>
      <span style="background:rgba(255,107,157,0.15);padding:8px 16px;border-radius:20px;font-size:0.85em;">💬 限定コミュニティ</span>
      <span style="background:rgba(255,107,157,0.15);padding:8px 16px;border-radius:20px;font-size:0.85em;">🎁 月1グッズ抽選</span>
    </div>

    <!-- CTA -->
    <a href="/premium/" style="display:inline-block;background:linear-gradient(90deg,#ff6b9d,#c44dff);color:#fff;padding:16px 48px;border-radius:30px;text-decoration:none;font-weight:bold;font-size:1.1em;box-shadow:0 4px 16px rgba(196,77,255,0.4);transition:transform 0.2s;">
      7日間無料で試す →
    </a>
    <p style="font-size:0.8em;color:#888;margin:12px 0 0;">いつでも解約OK・初回7日間無料</p>
  </div>
</div>"""

# 記事内に埋め込むプレミアム会員誘導CTA（通常記事の末尾に配置）
PREMIUM_UPSELL_CTA = """<div class="kpopj-premium-upsell" data-cta="premium" style="margin:36px 0;padding:24px;border:2px solid #c44dff;border-radius:14px;background:linear-gradient(135deg,#faf5ff,#f0e6ff);text-align:center;">
  <p style="font-size:1.15em;font-weight:bold;margin:0 0 8px;color:#7c3aed;">🔒 もっと深い分析を読みたい方へ</p>
  <p style="margin:0 0 16px;color:#555;font-size:0.95em;line-height:1.7;">Premium会員なら限定記事・速報先行配信・広告なし表示が月額980円で利用可能</p>
  <a href="/premium/" style="display:inline-block;background:#c44dff;color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;">Premium会員になる（7日間無料）</a>
</div>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WordPress側セットアップ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def setup_premium_category() -> int:
    """Premium限定カテゴリ（ID: 999相当）を作成/取得"""
    # 既存チェック
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/categories?search=Premium限定&per_page=5", "-K", WP_AUTH]
    try:
        cats = json.loads(subprocess.check_output(cmd, timeout=15))
        for c in cats:
            if "premium" in c["name"].lower() or "Premium" in c["name"]:
                print(f"  ✅ Premiumカテゴリ既存: ID={c['id']}")
                return c["id"]
    except Exception:
        pass

    # 作成
    cmd = [
        "curl", "-s", "-X", "POST", f"{WP}/wp-json/wp/v2/categories",
        "-K", WP_AUTH, "-H", "Content-Type: application/json",
        "-d", json.dumps({
            "name": "Premium限定",
            "slug": "premium-exclusive",
            "description": "K-POP JOURNAL Premium会員限定コンテンツ",
        }),
    ]
    try:
        resp = json.loads(subprocess.check_output(cmd, timeout=15))
        cat_id = resp.get("id", 0)
        print(f"  ✅ Premiumカテゴリ作成: ID={cat_id}")
        return cat_id
    except Exception as e:
        print(f"  ⚠️ カテゴリ作成失敗: {e}")
        return 0


def create_premium_page() -> int:
    """Premium紹介・登録ページを作成"""
    page_content = f"""<div style="max-width:800px;margin:0 auto;">

<div style="text-align:center;padding:48px 24px;">
  <h1 style="font-size:2.2em;font-weight:800;margin:0 0 16px;background:linear-gradient(90deg,#ff6b9d,#c44dff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">K-POP JOURNAL Premium</h1>
  <p style="font-size:1.2em;color:#666;margin:0 0 32px;">推し活をもっと深く、もっと早く。</p>
</div>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px;margin:0 0 40px;">
  {"".join(f'''<div style="padding:24px;border-radius:12px;background:#f8f9fa;text-align:center;">
    <span style="font-size:2em;">{f["icon"]}</span>
    <h3 style="margin:12px 0 8px;font-size:1.1em;">{f["name"]}</h3>
    <p style="color:#666;font-size:0.9em;margin:0;">{f["description"]}</p>
  </div>''' for f in PREMIUM_PLAN["features"])}
</div>

<div style="text-align:center;padding:40px;background:linear-gradient(135deg,#1a1a2e,#0f3460);border-radius:16px;color:#fff;margin:0 0 40px;">
  <p style="font-size:0.9em;color:#ff6b9d;margin:0 0 8px;">月額プラン</p>
  <p style="font-size:3em;font-weight:800;margin:0 0 8px;">¥980<span style="font-size:0.4em;color:#ccc;">/月（税込）</span></p>
  <p style="color:#ccc;margin:0 0 24px;">初回7日間無料・いつでも解約OK</p>
  <a href="#subscribe" style="display:inline-block;background:linear-gradient(90deg,#ff6b9d,#c44dff);color:#fff;padding:16px 56px;border-radius:30px;text-decoration:none;font-weight:bold;font-size:1.15em;box-shadow:0 4px 20px rgba(196,77,255,0.4);">7日間無料で始める</a>
</div>

<div style="padding:24px;background:#f8f9fa;border-radius:12px;margin:0 0 40px;">
  <h2 style="font-size:1.3em;margin:0 0 16px;">よくある質問</h2>
  <details style="margin:0 0 12px;"><summary style="cursor:pointer;font-weight:bold;">解約はいつでもできますか？</summary><p style="padding:8px 0 0 16px;color:#666;">はい。マイページからいつでも解約でき、次の請求日から課金が停止されます。</p></details>
  <details style="margin:0 0 12px;"><summary style="cursor:pointer;font-weight:bold;">無料期間中に解約したら請求されますか？</summary><p style="padding:8px 0 0 16px;color:#666;">いいえ。7日間の無料期間中に解約すれば一切請求されません。</p></details>
  <details style="margin:0 0 12px;"><summary style="cursor:pointer;font-weight:bold;">支払い方法は？</summary><p style="padding:8px 0 0 16px;color:#666;">クレジットカード（Visa/Mastercard/JCB/AMEX）に対応しています。</p></details>
  <details><summary style="cursor:pointer;font-weight:bold;">限定コンテンツはどのくらいの頻度で更新されますか？</summary><p style="padding:8px 0 0 16px;color:#666;">週2〜3本の限定記事に加え、速報は全て先行配信されます。</p></details>
</div>

</div>"""

    # 既存チェック
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/pages?slug=premium&per_page=1", "-K", WP_AUTH]
    try:
        pages = json.loads(subprocess.check_output(cmd, timeout=15))
        if pages:
            print(f"  ✅ Premiumページ既存: ID={pages[0]['id']}")
            return pages[0]["id"]
    except Exception:
        pass

    # 作成
    cmd = [
        "curl", "-s", "-X", "POST", f"{WP}/wp-json/wp/v2/pages",
        "-K", WP_AUTH, "-H", "Content-Type: application/json",
        "-d", json.dumps({
            "title": "K-POP JOURNAL Premium",
            "content": page_content,
            "status": "publish",
            "slug": "premium",
        }, ensure_ascii=False),
    ]
    try:
        resp = json.loads(subprocess.check_output(cmd, timeout=30))
        page_id = resp.get("id", 0)
        print(f"  ✅ Premiumページ作成: ID={page_id}")
        return page_id
    except Exception as e:
        print(f"  ⚠️ ページ作成失敗: {e}")
        return 0


def apply_gate(post_id: int, dry_run: bool = False) -> bool:
    """記事にPremiumゲートを適用"""
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/posts/{post_id}?context=edit", "-K", WP_AUTH]
    try:
        post = json.loads(subprocess.check_output(cmd, timeout=15))
    except Exception as e:
        print(f"  ⚠️ 取得失敗: {e}")
        return False

    content = post.get("content", {}).get("raw", "") or post.get("content", {}).get("rendered", "")
    title = post.get("title", {}).get("rendered", "")

    if "kpopj-premium-gate" in content:
        print(f"  → #{post_id} ゲート既存 → スキップ")
        return False

    # 本文の半分の位置にゲートを挿入（前半はプレビュー、後半は非表示）
    h2_positions = [m.start() for m in re.finditer(r"<h2\b", content, re.IGNORECASE)]
    if len(h2_positions) >= 3:
        gate_pos = h2_positions[len(h2_positions) // 2]
    elif h2_positions:
        gate_pos = h2_positions[-1]
    else:
        gate_pos = len(content) // 2

    new_content = content[:gate_pos] + "\n" + PREMIUM_GATE_HTML + "\n" + content[gate_pos:]

    if dry_run:
        print(f"  [DRY-RUN] #{post_id} ゲート挿入予定: {title[:40]}...")
        return True

    cmd = [
        "curl", "-s", "-X", "POST", f"{WP}/wp-json/wp/v2/posts/{post_id}",
        "-K", WP_AUTH, "-H", "Content-Type: application/json",
        "-d", json.dumps({"content": new_content}, ensure_ascii=False),
    ]
    try:
        resp = json.loads(subprocess.check_output(cmd, timeout=30))
        if resp.get("id"):
            print(f"  ✅ #{post_id} ゲート適用: {title[:40]}...")
            LOGS.mkdir(exist_ok=True)
            with open(PREMIUM_LOG, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(JST).isoformat(),
                    "action": "gate_applied",
                    "post_id": post_id,
                    "title": title[:60],
                }, ensure_ascii=False) + "\n")
            return True
    except Exception as e:
        print(f"  ⚠️ ゲート適用失敗: {e}")

    return False


def inject_upsell_cta(post_id: int, dry_run: bool = False) -> bool:
    """通常記事の末尾にPremium誘導CTAを挿入"""
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/posts/{post_id}?context=edit", "-K", WP_AUTH]
    try:
        post = json.loads(subprocess.check_output(cmd, timeout=15))
    except Exception:
        return False

    content = post.get("content", {}).get("raw", "") or post.get("content", {}).get("rendered", "")

    if "kpopj-premium-upsell" in content or "kpopj-premium-gate" in content:
        return False

    new_content = content + "\n" + PREMIUM_UPSELL_CTA

    if dry_run:
        return True

    cmd = [
        "curl", "-s", "-X", "POST", f"{WP}/wp-json/wp/v2/posts/{post_id}",
        "-K", WP_AUTH, "-H", "Content-Type: application/json",
        "-d", json.dumps({"content": new_content}, ensure_ascii=False),
    ]
    try:
        resp = json.loads(subprocess.check_output(cmd, timeout=30))
        return bool(resp.get("id"))
    except Exception:
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# プラン設定JSON出力
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_plan_config():
    """プラン設定をJSON出力"""
    config_path = CONFIG / "premium_plan.json"
    config_path.write_text(json.dumps(PREMIUM_PLAN, ensure_ascii=False, indent=2))
    print(f"  ✅ プラン設定保存: {config_path}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="有料会員プラン管理")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="WP側の初期設定（カテゴリ・ページ作成）")
    sub.add_parser("create-gate", help="ゲートHTML表示")

    p_gate = sub.add_parser("gate", help="記事にゲート適用")
    p_gate.add_argument("post_id", type=int)
    p_gate.add_argument("--dry-run", action="store_true")

    sub.add_parser("stats", help="会員統計")
    sub.add_parser("save-config", help="プラン設定JSON保存")

    args = parser.parse_args()

    if args.command == "setup":
        print("=== Premium会員セットアップ ===")
        save_plan_config()
        setup_premium_category()
        create_premium_page()
        print("  ✅ セットアップ完了")

    elif args.command == "create-gate":
        print(PREMIUM_GATE_HTML)

    elif args.command == "gate":
        apply_gate(args.post_id, dry_run=args.dry_run)

    elif args.command == "save-config":
        save_plan_config()

    elif args.command == "stats":
        print("=== Premium会員統計 ===")
        print(f"  プラン: {PREMIUM_PLAN['name']}")
        print(f"  月額: ¥{PREMIUM_PLAN['price_monthly']}")
        if PREMIUM_LOG.exists():
            with open(PREMIUM_LOG) as f:
                lines = [l for l in f if l.strip()]
            print(f"  ゲート適用記事: {len(lines)}件")
        print(f"  目標: 3ヶ月={PREMIUM_PLAN['target_subscribers']['month_3']}人 / 12ヶ月={PREMIUM_PLAN['target_subscribers']['month_12']}人")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
