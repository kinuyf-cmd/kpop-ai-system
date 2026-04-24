#!/usr/bin/env python3
"""
lib/ui_optimizer.py
イルミーゼ — UI/UXデザイン最適化エージェント本体 v2

CTR・滞在時間・CTAクリック率の3指標を同時評価し、
A/Bテスト（1変数1週間）で継続的に勝ちパターンへ収束させる。

Usage:
  python3 lib/ui_optimizer.py apply        # ベースCSS適用（初回・リセット用）
  python3 lib/ui_optimizer.py generate     # 学習CSSを生成して表示（適用しない）
  python3 lib/ui_optimizer.py analyze      # KPI3指標評価→CSS改善→WP適用（フルループ）
  python3 lib/ui_optimizer.py record       # 実験開始を記録
  python3 lib/ui_optimizer.py update       # 実験結果を手動確定
  python3 lib/ui_optimizer.py report       # レポート表示
  python3 lib/ui_optimizer.py rollback     # 直前バージョンに戻す
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

BASE_DIR     = Path(__file__).parent.parent
LOGS         = BASE_DIR / "logs"
GMETRICS     = BASE_DIR / "google_metrics"
WP_BASE      = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH_FILE = Path.home() / ".wp_auth"

UI_EXP_LOG   = LOGS / "ui_experiments.jsonl"
UI_CSS_HIST  = LOGS / "ui_css_history.jsonl"
UI_KPI_LOG   = LOGS / "ui_kpi_snapshots.jsonl"   # 3指標スナップショット
UI_CTA_LOG   = LOGS / "ui_cta_events.jsonl"       # CTA実測ログ
WIN_PATTERNS = LOGS / "winning_patterns.jsonl"
KPI_POSTS    = LOGS / "kpi_posts.jsonl"
METRICS_FILE = GMETRICS / "metrics_yesterday.json"

JST = timezone(timedelta(hours=9))

# ─── 勝ち/負け閾値 ────────────────────────────────────────────
# 3指標すべてで評価する
CTR_WIN       = 0.005    # CTR +0.5%以上
CTR_LOSE      = -0.003   # CTR -0.3%以下
DWELL_LOSE    = -2.0     # 滞在時間 -2秒以下
CTA_LOSE      = -0.01    # CTAクリック率 -1pt以下
MIN_SAMPLES   = 10       # 判定に必要な最低記事数

# ─── 記事タイプマッピング ──────────────────────────────────────
# winning_patterns.jsonl の category → UI管理上のタイプ名
ARTICLE_TYPE_MAP = {
    "breaking":  "速報",
    "chart":     "ランキング",
    "profile":   "プロフィール",
    "guide":     "解説",
    "review":    "解説",
    "rumor":     "速報",
    "live":      "解説",
    "comeback":  "速報",
    "other":     "解説",
}

# ─── CSS変数と学習候補値 ──────────────────────────────────────
# key: (ラベル, 候補リスト)  先頭がデフォルト値
CSS_PARAMS = {
    "font_size_body":    ("フォントサイズ",    ["16px", "17px", "18px"]),
    "line_height":       ("行間",             ["1.8", "1.9", "2.0", "1.7"]),
    "cta_border_radius": ("CTAボタン角丸",     ["8px", "12px", "16px", "4px"]),
    "cta_padding":       ("CTAボタン余白",     ["14px 28px", "16px 32px", "12px 24px"]),
    "h2_margin_top":     ("見出し上余白",      ["32px", "40px", "28px"]),
    "card_border_radius":("カード角丸",        ["12px", "10px", "16px"]),
    "body_padding_x":    ("本文左右余白",      ["14px", "16px", "12px"]),
    "cta_text":          ("CTA文言",          ["最新K-POPニュースをチェック", "いち早くチェック！", "今すぐ読む"]),
}

# ─── ベースCSS ─────────────────────────────────────────────────
BASE_CSS_TEMPLATE = """\
/* ============================================================
   イルミーゼ管理CSS v{version}  ({date})
   K-POP Journal UI最適化 — スマホ優先設計
   3KPI同時最適化モード (CTR / 滞在時間 / CTAクリック率)
   ============================================================ */

/* ─── 基本フォント・余白 ─── */
.entry-content {{
  font-size: {font_size_body} !important;
  line-height: {line_height} !important;
  padding: 0 {body_padding_x} !important;
  max-width: 100% !important;
  word-break: break-word;
}}
.entry-content p {{
  margin-bottom: 20px;
  font-size: {font_size_body};
  line-height: {line_height};
}}

/* ─── 見出し ─── */
.entry-content h2 {{
  font-size: 22px;
  font-weight: 800;
  margin-top: {h2_margin_top};
  margin-bottom: 14px;
  padding-bottom: 6px;
  border-bottom: 2px solid #FF2D55;
  line-height: 1.5;
}}
.entry-content h3 {{
  font-size: 18px;
  font-weight: 700;
  margin-top: 24px;
  margin-bottom: 10px;
  line-height: 1.5;
}}

/* ─── 画像レスポンシブ ─── */
.entry-content img {{
  max-width: 100% !important;
  height: auto !important;
  border-radius: 8px;
  display: block;
  margin: 0 auto;
}}

/* ─── 記事一覧カード型UI ─── */
.post-card, article.post {{
  border-radius: {card_border_radius};
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  margin-bottom: 16px;
  overflow: hidden;
  background: #fff;
  transition: transform 0.15s, box-shadow 0.15s;
}}
.post-card:hover, article.post:hover {{
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,0.13);
}}

/* ─── サムネイル 16:9固定 ─── */
.post-card .thumbnail, .post-thumbnail, .entry-thumbnail {{
  position: relative;
  width: 100%;
  padding-top: 56.25%;
  overflow: hidden;
}}
.post-card .thumbnail img, .post-thumbnail img, .entry-thumbnail img {{
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  object-fit: cover;
  border-radius: 0;
}}

/* ─── タイトル（最大2行） ─── */
.entry-title a, .post-card .post-title {{
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.5;
  color: #111;
  text-decoration: none;
}}
.entry-title a:hover {{ color: #FF2D55; }}

/* ─── カテゴリタグ ─── */
.category-tag, .cat-links a {{
  display: inline-block;
  background: #FF2D55;
  color: #fff !important;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  text-decoration: none;
  margin-right: 4px;
  margin-bottom: 4px;
}}

/* ─── 投稿日 ─── */
.entry-date, .post-date, time.published {{
  font-size: 11px;
  color: #888;
  display: block;
  margin-top: 4px;
}}

/* ─── CTAボックス ─── */
.cta-box, .revenue-cta {{
  border-radius: {cta_border_radius};
  margin: 28px 0;
}}
.cta-box a, .revenue-cta a {{
  display: inline-block;
  padding: {cta_padding};
  border-radius: {cta_border_radius};
  font-weight: 700;
  font-size: 15px;
  text-decoration: none;
  min-height: 44px;
  line-height: 1.4;
}}
/* 独自CTAボタン */
.kpj-cta-btn {{
  display: block;
  width: 100%;
  padding: 0 24px;
  border-radius: {cta_border_radius};
  background: #FF2D55;
  color: #fff !important;
  font-size: 16px;
  font-weight: 800;
  text-align: center;
  text-decoration: none;
  border: none;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(255,45,85,0.35);
  transition: opacity 0.15s;
  min-height: 52px;
  line-height: 52px;
}}
.kpj-cta-btn:hover {{ opacity: 0.88; color: #fff !important; }}

/* ─── 記事タイプバッジ ─── */
.article-type {{
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
  margin-bottom: 12px;
}}
.article-type.speed     {{ background: #FF2D55; color: #fff; }}
.article-type.guide     {{ background: #007AFF; color: #fff; }}
.article-type.explanation {{ background: #555; color: #fff; }}

/* ─── 関連記事 ─── */
.related-articles {{
  background: #fff8f9;
  border-left: 4px solid #FF2D55;
  border-radius: 0 8px 8px 0;
  padding: 16px 18px;
  margin: 28px 0;
}}
.related-articles h3 {{ font-size: 14px; font-weight: 700; margin: 0 0 10px; color: #FF2D55; }}
.related-articles ul  {{ list-style: none; margin: 0; padding: 0; }}
.related-articles li  {{ font-size: 14px; line-height: 1.8; color: #333; }}
.related-articles li a {{ color: #FF2D55; text-decoration: none; }}

/* ─── SNSシェアボタン（記事上部＋記事下部＋フローティング） ─── */
.kpj-share {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 18px 0 24px;
  padding: 12px 0;
}}
.kpj-share-label {{
  font-size: 13px;
  font-weight: 700;
  color: #555;
  margin-right: 4px;
  white-space: nowrap;
}}
.kpj-share a {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  text-decoration: none;
  color: #fff !important;
  font-size: 16px;
  font-weight: 700;
  transition: opacity 0.15s, transform 0.15s;
  line-height: 1;
}}
.kpj-share a:hover {{
  opacity: 0.85;
  transform: scale(1.1);
}}
.kpj-share .share-x     {{ background: #000; }}
.kpj-share .share-line   {{ background: #06C755; }}
.kpj-share .share-fb     {{ background: #1877F2; }}
.kpj-share .share-copy   {{ background: #666; cursor: pointer; }}

/* 記事上部のシェアバー（目立つ配色） */
.kpj-share-top {{
  background: linear-gradient(135deg, #fff0f3 0%, #fff 100%);
  border: 1px solid #ffe0e6;
  border-radius: 10px;
  padding: 10px 16px;
  margin: 12px 0 20px;
}}
.kpj-share-top .kpj-share-label {{
  color: #FF2D55;
}}

/* 記事下部のシェアバー */
.kpj-share-bottom {{
  background: #f8f8fa;
  border-top: 2px solid #FF2D55;
  border-radius: 0 0 10px 10px;
  padding: 14px 16px;
  margin: 32px 0 16px;
}}

/* フローティングサイドシェア（PC: 左サイド固定） */
.kpj-share-float {{
  display: none;
  position: fixed;
  left: max(calc(50% - 440px), 12px);
  top: 50%;
  transform: translateY(-50%);
  flex-direction: column;
  gap: 8px;
  z-index: 9990;
  background: rgba(255,255,255,0.95);
  border-radius: 12px;
  padding: 10px 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.1);
}}
.kpj-share-float a {{
  width: 36px;
  height: 36px;
  font-size: 14px;
}}
@media (min-width: 1100px) {{
  .kpj-share-float {{ display: flex; }}
}}

/* 旧.share-prompt との互換 */
.share-prompt {{
  background: #f5f5f5;
  border-radius: 8px;
  padding: 14px 16px;
  margin: 24px 0;
  text-align: center;
  font-size: 13px;
  color: #555;
}}

/* ─── lazyload フェードイン ─── */
img[loading="lazy"] {{ opacity: 0; transition: opacity 0.3s; }}
img[loading="lazy"].loaded {{ opacity: 1; }}

/* ─── モバイル固定CTAバー ─── */
#kpj-fixed-cta {{
  display: none;
  position: fixed;
  bottom: 0; left: 0;
  width: 100%;
  height: 56px;
  background: #FF2D55;
  z-index: 9999;
  align-items: center;
  justify-content: center;
}}
#kpj-fixed-cta a {{
  color: #fff !important;
  font-weight: 800;
  font-size: 15px;
  text-decoration: none;
  letter-spacing: 0.04em;
}}

@media (max-width: 768px) {{
  #kpj-fixed-cta {{ display: flex; }}
  body {{ padding-bottom: 56px; }}
  .entry-content {{
    padding: 0 {body_padding_x} !important;
  }}
  .entry-content p, .entry-content li {{
    font-size: {font_size_body};
    line-height: {line_height};
  }}
}}
@media (min-width: 769px) {{
  .entry-content {{
    max-width: 780px;
    margin: 0 auto;
    padding: 0 20px !important;
  }}
  .post-card, article.post {{ margin-bottom: 24px; }}
}}

/* ============================================================
   Phase1 UI刷新 — トップページ専用デザイン
   ============================================================ */

/* ─── トップページ: 不要タイトル・日付非表示 ─── */
.front-top-page .entry-title {{ display: none !important; }}
.front-top-page .eye-catch-wrap {{ display: none !important; }}
.front-top-page .date-tags {{ display: none !important; }}
.front-top-page .article-header {{ padding: 0 !important; margin: 0 !important; min-height: 0 !important; }}
.front-top-page .article-footer {{ padding-top: 0 !important; }}

/* ─── ヒーローセクション（最新記事1件目をハイライト） ─── */
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child {{
  flex: 0 0 100% !important;
  max-width: 100% !important;
  margin-bottom: 8px;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-thumb {{
  padding-top: 0;
  height: auto;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-thumb img {{
  position: relative;
  width: 100%;
  height: auto;
  max-height: 400px;
  object-fit: cover;
  border-radius: 16px 16px 0 0;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-content {{
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  padding: 20px 18px;
  border-radius: 0 0 16px 16px;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-title {{
  color: #fff !important;
  font-size: 20px !important;
  font-weight: 800;
  line-height: 1.45;
  -webkit-line-clamp: 3;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .entry-date {{
  color: rgba(255,255,255,0.7) !important;
}}

/* ─── カード型グリッドレイアウト ─── */
.front-top-page .new-entry-cards .swiper-wrapper {{
  display: flex !important;
  flex-wrap: wrap !important;
  gap: 14px;
  transform: none !important;
}}
.front-top-page .new-entry-cards .swiper-slide {{
  flex: 0 0 calc(50% - 7px);
  max-width: calc(50% - 7px);
  margin: 0 !important;
}}
.front-top-page .new-entry-card-link {{
  display: block;
  border-radius: 14px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 2px 12px rgba(0,0,0,0.07);
  transition: transform 0.2s, box-shadow 0.2s;
  text-decoration: none;
}}
.front-top-page .new-entry-card-link:hover {{
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(0,0,0,0.12);
}}
.front-top-page .new-entry-card .card-thumb {{
  position: relative;
  padding-top: 56.25%;
  overflow: hidden;
}}
.front-top-page .new-entry-card .card-thumb img {{
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}}
.front-top-page .new-entry-card-link:hover .card-thumb img {{
  transform: scale(1.04);
}}
.front-top-page .new-entry-card .card-content {{
  padding: 12px 14px 14px;
}}
.front-top-page .new-entry-card .card-title {{
  font-size: 14px;
  font-weight: 700;
  line-height: 1.5;
  color: #1a1a2e;
  -webkit-line-clamp: 2;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}

/* ─── 新着記事セクションタイトル ─── */
.front-top-page .widget-page-content-bottom-title {{
  font-size: 20px;
  font-weight: 800;
  color: #1a1a2e;
  padding: 0 0 10px;
  margin: 8px 0 16px;
  border-bottom: 3px solid #FF2D55;
  position: relative;
}}
.front-top-page .widget-page-content-bottom-title::before {{
  content: "\\1F525";
  margin-right: 6px;
}}

/* ─── サイドバー人気記事の強化 ─── */
.front-top-page .widget_popular_entries .widget-sidebar-title {{
  font-size: 16px;
  font-weight: 800;
  color: #1a1a2e;
  border-bottom: 3px solid #FF2D55;
  padding-bottom: 8px;
  margin-bottom: 12px;
}}
.front-top-page .popular-entry-card-link {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
  text-decoration: none;
  transition: background 0.15s;
}}
.front-top-page .popular-entry-card-link:hover {{
  background: #fff8f9;
}}
/* ランキング番号バッジ */
.front-top-page .popular-entry-card-link.no-1::before,
.front-top-page .popular-entry-card-link.no-2::before,
.front-top-page .popular-entry-card-link.no-3::before,
.front-top-page .popular-entry-card-link.no-4::before,
.front-top-page .popular-entry-card-link.no-5::before {{
  font-weight: 900;
  font-size: 14px;
  width: 28px;
  height: 28px;
  line-height: 28px;
  text-align: center;
  border-radius: 50%;
  color: #fff;
  flex-shrink: 0;
}}
.front-top-page .popular-entry-card-link.no-1::before {{ content: "1"; background: #FF2D55; }}
.front-top-page .popular-entry-card-link.no-2::before {{ content: "2"; background: #FF6B81; }}
.front-top-page .popular-entry-card-link.no-3::before {{ content: "3"; background: #FFA07A; }}
.front-top-page .popular-entry-card-link.no-4::before {{ content: "4"; background: #bbb; }}
.front-top-page .popular-entry-card-link.no-5::before {{ content: "5"; background: #bbb; }}

/* ─── 急上昇ランキングウィジェット（JS注入） ─── */
#kpj-trending {{
  background: linear-gradient(135deg, #fff0f3 0%, #fff5f7 50%, #fff 100%);
  border-radius: 16px;
  padding: 20px 16px;
  margin: 0 0 24px;
  border: 1px solid #ffe0e6;
}}
#kpj-trending h2 {{
  font-size: 18px;
  font-weight: 800;
  color: #1a1a2e;
  margin: 0 0 14px;
  padding: 0;
  border: none;
  display: flex;
  align-items: center;
  gap: 6px;
}}
#kpj-trending .kpj-trend-list {{
  list-style: none;
  margin: 0;
  padding: 0;
}}
#kpj-trending .kpj-trend-item {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  border-radius: 10px;
  transition: background 0.15s;
  text-decoration: none;
  color: #1a1a2e;
}}
#kpj-trending .kpj-trend-item:hover {{
  background: rgba(255,45,85,0.06);
}}
#kpj-trending .kpj-trend-rank {{
  font-size: 16px;
  font-weight: 900;
  width: 30px;
  height: 30px;
  line-height: 30px;
  text-align: center;
  border-radius: 8px;
  flex-shrink: 0;
}}
#kpj-trending .kpj-trend-rank.r1 {{ background: #FF2D55; color: #fff; }}
#kpj-trending .kpj-trend-rank.r2 {{ background: #FF6B81; color: #fff; }}
#kpj-trending .kpj-trend-rank.r3 {{ background: #FFA07A; color: #fff; }}
#kpj-trending .kpj-trend-rank.r4,
#kpj-trending .kpj-trend-rank.r5 {{ background: #f0f0f0; color: #555; }}
#kpj-trending .kpj-trend-title {{
  font-size: 14px;
  font-weight: 600;
  line-height: 1.45;
  -webkit-line-clamp: 2;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}}
#kpj-trending .kpj-trend-badge {{
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  background: #FF2D55;
  color: #fff;
  flex-shrink: 0;
  white-space: nowrap;
}}

/* ─── ヘッダー強化 ─── */
.front-top-page .header {{
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%) !important;
}}
.front-top-page .site-name-text {{
  color: #fff !important;
  font-size: 26px !important;
  font-weight: 900 !important;
  letter-spacing: 0.06em;
}}

/* ─── モバイル最適化 (トップページ) ─── */
@media (max-width: 768px) {{
  .front-top-page .new-entry-cards .swiper-slide {{
    flex: 0 0 100%;
    max-width: 100%;
  }}
  .front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-thumb img {{
    max-height: 220px;
  }}
  .front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-title {{
    font-size: 17px !important;
  }}
  .front-top-page .new-entry-card .card-content {{
    padding: 10px 12px 12px;
  }}
  .front-top-page .new-entry-card .card-title {{
    font-size: 14px;
  }}
  #kpj-trending {{
    padding: 16px 12px;
    margin: 0 0 18px;
    border-radius: 12px;
  }}
  #kpj-trending h2 {{
    font-size: 16px;
  }}
  #kpj-trending .kpj-trend-item {{
    padding: 8px 6px;
    gap: 8px;
  }}
  #kpj-trending .kpj-trend-title {{
    font-size: 13px;
  }}
  .front-top-page .site-name-text {{
    font-size: 22px !important;
  }}
  /* タップターゲット44px確保 */
  .front-top-page .new-entry-card-link {{
    min-height: 44px;
  }}
  .front-top-page .popular-entry-card-link {{
    min-height: 44px;
    padding: 12px 0;
  }}
}}
@media (min-width: 769px) {{
  .front-top-page .new-entry-cards .swiper-slide {{
    flex: 0 0 calc(33.333% - 10px);
    max-width: calc(33.333% - 10px);
  }}
  #kpj-trending {{
    padding: 24px 20px;
  }}
}}

/* ─── ページ速度改善 ─── */
/* コンテンツ外の画像はlazy + 非表示で初期描画を高速化 */
.front-top-page .new-entry-card .card-thumb img {{
  content-visibility: auto;
  contain-intrinsic-size: 320px 180px;
}}
/* アニメーション軽量化 — will-change指定 */
.front-top-page .new-entry-card-link {{
  will-change: transform;
}}
/* フォント読み込み最適化 */
.front-top-page {{
  text-rendering: optimizeSpeed;
}}
/* 広告エリアの高さ確保 (CLS防止) */
.front-top-page .ad-area {{
  min-height: 90px;
  contain: layout style;
}}
.front-top-page .ad-responsive {{
  min-height: 250px;
}}
"""

# CSSに追記する固定CTAバーHTML + CTA計測JSテンプレート
# WordPress の custom_css フィールドはCSS専用だが、
# Cocoonテーマは wp_footer フックでカスタムHTMLを出力する機能がある。
# ここでは CSS の末尾に HTML+script を含めることで注入する
# （WP は custom_css を <style> タグで出力するため、その直後にスクリプトが来る構造になる）
CTA_JS_APPEND = """
</style>
<!-- イルミーゼ管理: モバイル固定CTAバー + SNSシェア + CTA計測 v4 -->
<div id="kpj-fixed-cta" style="display:none;position:fixed;bottom:0;left:0;width:100%;height:56px;background:#FF2D55;z-index:9999;align-items:center;justify-content:center">
  <a href="https://www.kpopjournal.tokyo/" rel="noopener" style="color:#fff!important;font-weight:800;font-size:15px;text-decoration:none;letter-spacing:.04em;flex:1;text-align:center;line-height:56px">📰 {cta_text}</a>
  <button id="kpj-fixed-close" style="background:none;border:none;color:#fff;font-size:18px;padding:0 14px;cursor:pointer;opacity:.75;line-height:56px" aria-label="閉じる">✕</button>
</div>
<!-- SNSシェアフローティング（PC左サイド） -->
<div class="kpj-share-float" id="kpj-share-float">
  <a class="share-x" id="kpj-float-x" href="#" target="_blank" rel="noopener" aria-label="Xでシェア">X</a>
  <a class="share-line" id="kpj-float-line" href="#" target="_blank" rel="noopener" aria-label="LINEでシェア">L</a>
  <a class="share-fb" id="kpj-float-fb" href="#" target="_blank" rel="noopener" aria-label="Facebookでシェア">f</a>
  <a class="share-copy" id="kpj-float-copy" href="javascript:void(0)" aria-label="URLコピー">&#128279;</a>
</div>
<script>
(function(){{
  'use strict';
  if(typeof gtag!=='function'&&typeof dataLayer==='undefined')return;
  var _g=typeof gtag==='function'?gtag:function(){{(window.dataLayer=window.dataLayer||[]).push(arguments);}};
  var pp=window.location.pathname;
  var pu=window.location.href;
  var pt=document.title;
  var at='解説';
  var ab=document.querySelector('.article-type');
  if(ab){{if(ab.classList.contains('speed'))at='速報';else if(ab.classList.contains('guide'))at='解説';}}
  function pos(el){{
    var c=document.querySelector('.entry-content');
    if(!c)return'middle';
    var r=(el.getBoundingClientRect().top-c.getBoundingClientRect().top)/(c.offsetHeight||1);
    return r<0.3?'top':r<0.65?'middle':'bottom';
  }}

  /* ─ SNSシェアボタン動的生成（記事上部・下部） ─ */
  var isSingle=document.body.className.indexOf('single')!==-1;
  if(isSingle){{
    var shareHTML='<div class="kpj-share kpj-share-__POS__"><span class="kpj-share-label">__LABEL__</span>'
      +'<a class="share-x" href="https://x.com/intent/tweet?text='+encodeURIComponent(pt)+'&url='+encodeURIComponent(pu)+'" target="_blank" rel="noopener" aria-label="Xでシェア">X</a>'
      +'<a class="share-line" href="https://social-plugins.line.me/lineit/share?url='+encodeURIComponent(pu)+'" target="_blank" rel="noopener" aria-label="LINEでシェア">L</a>'
      +'<a class="share-fb" href="https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(pu)+'" target="_blank" rel="noopener" aria-label="Facebookでシェア">f</a>'
      +'<a class="share-copy kpj-copy-btn" href="javascript:void(0)" aria-label="URLコピー">&#128279;</a></div>';

    /* 記事上部に挿入 */
    var entry=document.querySelector('.entry-content');
    if(entry){{
      var topDiv=document.createElement('div');
      topDiv.innerHTML=shareHTML.replace(/__POS__/g,'top').replace(/__LABEL__/g,'Share');
      entry.insertBefore(topDiv.firstChild,entry.firstChild);
    }}

    /* 記事下部に挿入 */
    if(entry){{
      var botDiv=document.createElement('div');
      botDiv.innerHTML=shareHTML.replace(/__POS__/g,'bottom').replace(/__LABEL__/g,'この記事をシェア');
      entry.appendChild(botDiv.firstChild);
    }}

    /* フローティングのURL設定 */
    var fl=document.getElementById('kpj-share-float');
    if(fl){{
      var fx=document.getElementById('kpj-float-x');
      if(fx)fx.href='https://x.com/intent/tweet?text='+encodeURIComponent(pt)+'&url='+encodeURIComponent(pu);
      var fln=document.getElementById('kpj-float-line');
      if(fln)fln.href='https://social-plugins.line.me/lineit/share?url='+encodeURIComponent(pu);
      var ffb=document.getElementById('kpj-float-fb');
      if(ffb)ffb.href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(pu);
    }}

    /* URLコピー機能 */
    document.querySelectorAll('.kpj-copy-btn,#kpj-float-copy').forEach(function(btn){{
      btn.addEventListener('click',function(e){{
        e.preventDefault();
        navigator.clipboard.writeText(pu).then(function(){{
          var orig=btn.innerHTML;btn.innerHTML='&#10003;';
          setTimeout(function(){{btn.innerHTML=orig;}},1500);
        }});
        _g('event','share_click',{{share_method:'copy',article_type:at,page_path:pp}});
      }});
    }});

    /* シェアボタンクリック計測 */
    document.querySelectorAll('.kpj-share a,.kpj-share-float a').forEach(function(l){{
      if(l.classList.contains('kpj-copy-btn')||l.id==='kpj-float-copy')return;
      l.addEventListener('click',function(){{
        var m='unknown';
        if(l.classList.contains('share-x'))m='x';
        else if(l.classList.contains('share-line'))m='line';
        else if(l.classList.contains('share-fb'))m='facebook';
        var p2=l.closest('.kpj-share-top')?'top':l.closest('.kpj-share-bottom')?'bottom':'float';
        _g('event','share_click',{{share_method:m,share_position:p2,article_type:at,page_path:pp}});
      }});
    }});
  }}

  /* ─ CTA計測 ─ */
  document.querySelectorAll('.cta-box a,.revenue-cta a,.kpj-cta-btn').forEach(function(l){{
    l.addEventListener('click',function(){{
      var p=pos(l);
      _g('event','cta_click_'+p,{{cta_position:p,article_type:at,page_path:pp,cta_label:l.textContent.trim().substring(0,50)}});
    }});
  }});
  document.querySelectorAll('img[loading="lazy"]').forEach(function(i){{
    if(i.complete)i.classList.add('loaded');
    else i.addEventListener('load',function(){{i.classList.add('loaded');}});
  }});

  /* ─ 固定CTAバー ─ */
  if(isSingle){{
    var bar=document.getElementById('kpj-fixed-cta');
    if(bar){{
      bar.style.display='flex';
      document.body.style.paddingBottom='56px';
      _g('event','fixed_cta_impression',{{article_type:at,page_path:pp}});
      var bl=bar.querySelector('a');
      if(bl)bl.addEventListener('click',function(){{
        _g('event','cta_click_fixed_bar',{{cta_position:'fixed_bar',article_type:at,page_path:pp,cta_label:bl.textContent.trim().substring(0,50)}});
      }});
      var bc=document.getElementById('kpj-fixed-close');
      if(bc)bc.addEventListener('click',function(){{
        bar.style.display='none';
        document.body.style.paddingBottom='0';
        _g('event','fixed_cta_close',{{article_type:at,page_path:pp}});
      }});
    }}
  }}

  /* ─ 急上昇ランキングウィジェット動的注入 ─ */
  if(document.body.className.indexOf('front-top-page')!==-1){{
    try{{
      var trendSrc='{trending_json_escaped}';
      if(trendSrc && trendSrc!==''){{
        var trendData=JSON.parse(trendSrc);
        if(trendData.length>0){{
          var rankColors=['r1','r2','r3','r4','r5'];
          var h='<div id="kpj-trending"><h2>\\ud83d\\udcc8 \\u6025\\u4e0a\\u6607\\u30e9\\u30f3\\u30ad\\u30f3\\u30b0</h2><div class="kpj-trend-list">';
          trendData.forEach(function(item,i){{
            var badge='';
            if(item.b)badge='<span class="kpj-trend-badge">'+item.b+'</span>';
            h+='<a class="kpj-trend-item" href="'+item.u+'">'
              +'<span class="kpj-trend-rank '+rankColors[i]+'">'+(i+1)+'</span>'
              +'<span class="kpj-trend-title">'+item.t+'</span>'
              +badge+'</a>';
          }});
          h+='</div></div>';
          var ec=document.querySelector('.entry-content');
          if(ec){{ec.innerHTML=h+ec.innerHTML;}}
        }}
      }}
    }}catch(e){{}}
  }}

  /* ─ トップページ: カード表示数制限（速度改善） ─ */
  if(document.body.className.indexOf('front-top-page')!==-1){{
    var allCards=document.querySelectorAll('.new-entry-cards .swiper-slide');
    var maxCards=window.innerWidth<769?12:18;
    for(var ci=maxCards;ci<allCards.length;ci++){{
      allCards[ci].style.display='none';
    }}
    if(allCards.length>maxCards){{
      var moreBtn=document.createElement('div');
      moreBtn.style.cssText='text-align:center;padding:20px 0;';
      moreBtn.innerHTML='<a href="/page/2/" style="display:inline-block;padding:12px 32px;background:#FF2D55;color:#fff;border-radius:8px;font-weight:700;font-size:14px;text-decoration:none;min-height:44px;line-height:20px;">\\u3082\\u3063\\u3068\\u898b\\u308b</a>';
      var cardContainer=document.querySelector('.new-entry-cards');
      if(cardContainer)cardContainer.parentNode.insertBefore(moreBtn,cardContainer.nextSibling);
    }}
  }}

  /* ─ 画像遅延読み込み強化（IntersectionObserver） ─ */
  if('IntersectionObserver' in window){{
    var imgObs=new IntersectionObserver(function(entries){{
      entries.forEach(function(entry){{
        if(entry.isIntersecting){{
          var img=entry.target;
          if(img.dataset.src){{img.src=img.dataset.src;img.removeAttribute('data-src');}}
          img.classList.add('loaded');
          imgObs.unobserve(img);
        }}
      }});
    }},{{rootMargin:'200px'}});
    document.querySelectorAll('img[loading="lazy"]').forEach(function(img){{imgObs.observe(img);}});
  }}
}})();
</script>
<style>"""


# ─── ユーティリティ ────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).isoformat()

def _now_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")

def _css_defaults() -> dict:
    return {k: v[1][0] for k, v in CSS_PARAMS.items()}

def _get_auth_header():
    if not WP_AUTH_FILE.exists():
        return None, "AUTH_FAIL: ~/.wp_auth が存在しない"
    try:
        content = WP_AUTH_FILE.read_text()
        m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
        if m:
            return m.group(1), None
        token = content.strip().split()[-1]
        return f"Basic {token}", None
    except Exception as e:
        return None, f"AUTH_FAIL: {e}"

def _wp_request(method, path, data=None):
    auth, err = _get_auth_header()
    if err:
        return None, err
    url = f"{WP_BASE}{path}"
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "kpop-illumise-ui/2.0",
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:400]
        return None, f"HTTP {e.code}: {body_text}"
    except Exception as e:
        return None, str(e)

def _load_jsonl(path: Path, max_lines: int = 0) -> list:
    if not path.exists():
        return []
    records = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if max_lines:
            lines = lines[-max_lines:]
        for line in lines:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records

def _append_jsonl(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _get_version() -> int:
    records = _load_jsonl(UI_CSS_HIST)
    if not records:
        return 1
    return max(r.get("version", 0) for r in records) + 1


# ─── KPI3指標データ収集 ───────────────────────────────────────

def _get_real_cta_avg(days_back: int = 7) -> Optional[float]:
    """
    ui_cta_events.jsonlから直近N日の実CTA率平均を返す。
    データが存在しない場合は None を返す（フォールバック判定用）。
    """
    if not UI_CTA_LOG.exists():
        return None
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    vals = []
    try:
        for line in UI_CTA_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("date", "") >= cutoff and r.get("source") == "ga4_real":
                    v = r.get("cta_ctr_real")
                    if v is not None:
                        vals.append(float(v))
            except Exception:
                pass
    except Exception:
        pass
    return round(sum(vals) / len(vals), 4) if vals else None


def _collect_kpi_snapshot(days_back: int = 7) -> dict:
    """
    CTR / 滞在時間 / CTAクリック率 を収集してスナップショットを返す。

    CTR:      winning_patterns.jsonl の eval_72h（GSCスコア）平均
    滞在時間: metrics_yesterday.json の ga4.summary.avg_session_duration
    CTA率:    [優先] ui_cta_events.jsonl の cta_ctr_real（GA4実測）
              [代替] kpi_posts.jsonl の has_cta記事 × eval_72h 平均
    """
    from datetime import date as _date
    cutoff_iso = (datetime.now(JST) - timedelta(days=days_back)).isoformat()

    # ─ CTR (winning_patterns) ─
    patterns = _load_jsonl(WIN_PATTERNS, max_lines=500)
    ctr_scores = []
    type_ctr: dict[str, list] = defaultdict(list)
    for p in patterns:
        ts = p.get("recorded_at", "")
        if ts < cutoff_iso:
            continue
        score = p.get("eval_72h") or p.get("eval_48h") or p.get("eval_24h")
        if score and isinstance(score, (int, float)) and score > 0:
            ctr_scores.append(float(score))
            raw_cat = p.get("category", "other")
            ui_type = ARTICLE_TYPE_MAP.get(raw_cat, "解説")
            type_ctr[ui_type].append(float(score))

    avg_ctr      = round(sum(ctr_scores) / len(ctr_scores), 3) if ctr_scores else 0.0
    type_avg_ctr = {t: round(sum(v)/len(v), 3) for t, v in type_ctr.items() if v}

    # ─ 滞在時間 (GA4) ─
    avg_dwell = 0.0
    try:
        metrics  = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        raw_dwell = metrics.get("ga4", {}).get("summary", {}).get("avg_session_duration", 0)
        avg_dwell = round(float(raw_dwell), 1)
    except Exception:
        pass

    # ─ CTA率: 実測を優先、なければ代替 ─
    real_cta = _get_real_cta_avg(days_back=days_back)
    if real_cta is not None:
        avg_cta      = real_cta
        cta_source   = "ga4_real"
        cta_sample_n = days_back  # 実測日数（概算）
    else:
        # 代替: CTA設置済み記事のCTRスコア平均
        posts = _load_jsonl(KPI_POSTS, max_lines=300)
        cta_scores = []
        for p in posts:
            ts = p.get("timestamp", "")
            if ts < cutoff_iso or not p.get("has_cta"):
                continue
            for pat in patterns:
                if str(pat.get("post_id")) == str(p.get("post_id")):
                    s = pat.get("eval_72h") or pat.get("eval_48h")
                    if s and isinstance(s, (int, float)) and s > 0:
                        cta_scores.append(float(s))
                    break
        avg_cta      = round(sum(cta_scores) / len(cta_scores), 3) if cta_scores else 0.0
        cta_source   = "proxy"
        cta_sample_n = len(cta_scores)

    return {
        "timestamp":    _now_jst(),
        "days_back":    days_back,
        "avg_ctr":      avg_ctr,
        "avg_dwell_sec": avg_dwell,
        "avg_cta_score": avg_cta,
        "cta_source":   cta_source,     # "ga4_real" or "proxy"
        "ctr_sample_n": len(ctr_scores),
        "cta_sample_n": cta_sample_n,
        "type_avg_ctr": type_avg_ctr,
    }


def _get_baseline_kpi(exp: dict) -> dict:
    return {
        "avg_ctr":       exp.get("baseline_avg_ctr", 0.0),
        "avg_dwell_sec": exp.get("baseline_avg_dwell_sec", 0.0),
        "avg_cta_score": exp.get("baseline_avg_cta_score", 0.0),
        "cta_source":    exp.get("baseline_cta_source", "proxy"),
    }


# ─── 3指標勝ち/負け判定 ───────────────────────────────────────

def _judge_experiment(baseline: dict, result: dict) -> tuple[str, dict]:
    """
    3指標を同時評価して status を返す。

    優先順位:
      1. CTR  (+0.5%以上で勝ち、-0.3%以下で負け)
      2. 滞在時間 (-2秒以下で負け)
      3. CTA率 (-1pt以下で負け)

    provisional判定:
      CTA率が代替指標(proxy)の場合は "provisional_win/lose" として記録する。
      実測データが揃った時点で再評価を推奨する。

    勝ち: CTR +0.5%以上 AND 滞在 維持/改善 AND CTA 維持/改善
    負け: CTR -0.3%以下 OR 滞在 -2秒以下 OR CTA -1pt以下
    中立: それ以外
    """
    delta_ctr   = result["avg_ctr"]       - baseline["avg_ctr"]
    delta_dwell = result["avg_dwell_sec"] - baseline["avg_dwell_sec"]
    delta_cta   = result["avg_cta_score"] - baseline["avg_cta_score"]

    # CTAが実測かどうか判定（ベースラインと結果の両方が実測なら final）
    cta_is_real = (
        result.get("cta_source") == "ga4_real"
        and baseline.get("cta_source") == "ga4_real"
    )
    judgment_mode = "final" if cta_is_real else "provisional"

    verdict = {
        "delta_ctr":     round(delta_ctr, 4),
        "delta_dwell":   round(delta_dwell, 2),
        "delta_cta":     round(delta_cta, 4),
        "judgment_mode": judgment_mode,
        "cta_is_real":   cta_is_real,
    }

    # 負け判定
    if delta_ctr <= CTR_LOSE or delta_dwell <= DWELL_LOSE or delta_cta <= CTA_LOSE:
        verdict["reason"] = _lose_reason(delta_ctr, delta_dwell, delta_cta)
        status = "lose" if cta_is_real else "provisional_lose"
        return status, verdict

    # 勝ち判定
    if delta_ctr >= CTR_WIN and delta_dwell >= 0 and delta_cta >= 0:
        verdict["reason"] = (
            f"CTR+{delta_ctr:.4f} 滞在+{delta_dwell:.1f}s CTA+{delta_cta:.4f}"
        )
        status = "win" if cta_is_real else "provisional_win"
        return status, verdict

    return "neutral", verdict


def _lose_reason(delta_ctr, delta_dwell, delta_cta) -> str:
    reasons = []
    if delta_ctr <= CTR_LOSE:
        reasons.append(f"CTR低下({delta_ctr:+.4f})")
    if delta_dwell <= DWELL_LOSE:
        reasons.append(f"滞在悪化({delta_dwell:+.1f}s)")
    if delta_cta <= CTA_LOSE:
        reasons.append(f"CTA低下({delta_cta:+.4f})")
    return " / ".join(reasons)


# ─── CSS生成 ─────────────────────────────────────────────────

def _get_best_params() -> dict:
    """wins履歴から最良パラメータを選ぶ。不足時はデフォルト。"""
    params = _css_defaults()
    experiments = _load_jsonl(UI_EXP_LOG)
    wins = [e for e in experiments if e.get("status") == "win" and e.get("css_params")]
    if len(wins) < 3:
        return params
    param_wins: dict[str, Counter] = defaultdict(Counter)
    for exp in wins:
        for key, val in exp.get("css_params", {}).items():
            if key in CSS_PARAMS:
                param_wins[key][val] += 1
    for key, counter in param_wins.items():
        if counter:
            best_val = counter.most_common(1)[0][0]
            if best_val in CSS_PARAMS[key][1]:
                params[key] = best_val
    return params


def _build_trending_json() -> str:
    """急上昇ランキングデータをJS埋め込み用JSON文字列で返す"""
    trending_cache = LOGS / "trending_ranking.json"
    if not trending_cache.exists():
        # trending_widget が未実行なら空
        return ""
    try:
        cache = json.loads(trending_cache.read_text(encoding="utf-8"))
        ranking = cache.get("ranking", [])
        if not ranking:
            return ""
        # コンパクトなJSONに変換 (u=url, t=title, b=badge)
        compact = []
        site = "https://www.kpopjournal.tokyo"
        for item in ranking[:5]:
            path = item.get("path", f"/{item.get('slug', '')}/")
            badge = ""
            if item.get("gsc_clicks", 0) >= 3:
                badge = "検索急上昇"
            elif item.get("engaged_sessions", 0) >= 2:
                badge = "注目"
            elif len(compact) == 0:
                badge = "HOT"
            compact.append({"u": f"{site}{path}", "t": item.get("title", ""), "b": badge})
        return json.dumps(compact, ensure_ascii=False).replace("'", "\\'")
    except Exception:
        return ""


def generate_css(params: dict = None) -> str:
    if params is None:
        params = _get_best_params()
    version = _get_version()
    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    css = BASE_CSS_TEMPLATE.format(version=version, date=date_str, **{
        k: params.get(k, v[1][0]) for k, v in CSS_PARAMS.items()
    })
    # CTAクリック計測JSをCSSに埋め込む
    # WPはcustom_cssを<style>タグで出力するため、閉じタグを挟んでHTMLを注入する
    cta_text = params.get("cta_text", CSS_PARAMS["cta_text"][1][0])
    trending_json = _build_trending_json()
    js_block = CTA_JS_APPEND.format(
        cta_text=cta_text,
        trending_json_escaped=trending_json,
    )
    return css + js_block


# ─── WP CSS適用 ──────────────────────────────────────────────

def apply_css_to_wp(css: str) -> tuple[bool, str]:
    version = _get_version()
    resp, err = _wp_request("POST", "/settings", {"custom_css": css})
    if not err:
        _append_jsonl(UI_CSS_HIST, {
            "timestamp": _now_jst(), "version": version,
            "css": css, "method": "settings_api", "reason": "auto_apply",
        })
        return True, f"✅ settings API 適用成功 (v{version})"

    # フォールバック: global-styles
    gs_list, _ = _wp_request("GET", "/global-styles/themes/current-theme")
    if gs_list:
        gs_id = gs_list[0].get("id") if isinstance(gs_list, list) else gs_list.get("id")
        if gs_id:
            gs_resp, gs_err = _wp_request("PUT", f"/global-styles/{gs_id}",
                                          {"settings": {"custom": {"css": css}}})
            if not gs_err:
                _append_jsonl(UI_CSS_HIST, {
                    "timestamp": _now_jst(), "version": version,
                    "css": css, "method": "global_styles_api", "reason": "auto_apply",
                })
                return True, f"✅ global-styles API 適用成功 (v{version})"

    return False, f"❌ CSS適用失敗: {err}"


# ─── 保留実験の解決 ──────────────────────────────────────────

def _resolve_pending_experiments() -> int:
    """計測期間が終わったpending実験を win/lose/neutral に確定する"""
    experiments = _load_jsonl(UI_EXP_LOG)
    now = datetime.now(JST)
    updated_count = 0
    new_records = []

    for exp in experiments:
        if exp.get("status") != "pending":
            new_records.append(exp)
            continue

        applied_at_str = exp.get("applied_at", "")
        measurement_days = exp.get("measurement_days", 7)
        if not applied_at_str:
            new_records.append(exp)
            continue
        try:
            applied_at = datetime.fromisoformat(applied_at_str)
        except Exception:
            new_records.append(exp)
            continue

        if (now - applied_at).days < measurement_days:
            new_records.append(exp)
            continue

        # 期間終了 → KPI計測
        baseline = _get_baseline_kpi(exp)
        if baseline["avg_ctr"] == 0.0:
            exp["status"] = "insufficient_data"
            exp["note"] = "ベースラインデータ不足"
            new_records.append(exp)
            updated_count += 1
            continue

        result_snap = _collect_kpi_snapshot(days_back=measurement_days)
        if result_snap["ctr_sample_n"] < MIN_SAMPLES:
            exp["status"] = "insufficient_data"
            exp["note"] = f"サンプル不足 n={result_snap['ctr_sample_n']}"
            new_records.append(exp)
            updated_count += 1
            continue

        result = {
            "avg_ctr":       result_snap["avg_ctr"],
            "avg_dwell_sec": result_snap["avg_dwell_sec"],
            "avg_cta_score": result_snap["avg_cta_score"],
            "cta_source":    result_snap["cta_source"],
        }
        status, verdict = _judge_experiment(baseline, result)

        exp["status"]             = status
        exp["result_avg_ctr"]     = result["avg_ctr"]
        exp["result_avg_dwell"]   = result["avg_dwell_sec"]
        exp["result_avg_cta"]     = result["avg_cta_score"]
        exp["delta_ctr"]          = verdict["delta_ctr"]
        exp["delta_dwell"]        = verdict["delta_dwell"]
        exp["delta_cta"]          = verdict["delta_cta"]
        exp["verdict_reason"]     = verdict.get("reason", "")
        exp["judgment_mode"]      = verdict.get("judgment_mode", "provisional")
        exp["cta_is_real"]        = verdict.get("cta_is_real", False)

        new_records.append(exp)
        updated_count += 1
        prov = " [provisional]" if verdict.get("judgment_mode") == "provisional" else ""
        icon = {"win":"✅","provisional_win":"🔶","lose":"❌","provisional_lose":"🔸","neutral":"➡️"}.get(status,"?")
        print(f"  {icon} {exp.get('experiment_id')} → {status}{prov}  "
              f"CTR{verdict['delta_ctr']:+.4f} 滞在{verdict['delta_dwell']:+.1f}s "
              f"CTA{verdict['delta_cta']:+.4f}")

    if updated_count:
        with open(UI_EXP_LOG, "w", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return updated_count


# ─── 次の実験変数選択 ────────────────────────────────────────

def _pick_next_experiment(current_params: dict) -> Optional[dict]:
    """
    まだ十分に試されていない変数を1つ選んで次の実験パラメータを返す。
    全変数が3回以上試験済みなら None を返す。
    lose が多い変数は後回しにする。
    """
    experiments = _load_jsonl(UI_EXP_LOG)
    trial_counts: dict[str, Counter]  = {k: Counter() for k in CSS_PARAMS}
    lose_counts:  dict[str, Counter]  = {k: Counter() for k in CSS_PARAMS}

    for exp in experiments:
        exp_params = exp.get("css_params", {})
        for key, val in exp_params.items():
            if key not in CSS_PARAMS:
                continue
            trial_counts[key][val] += 1
            if exp.get("status") == "lose":
                lose_counts[key][val] += 1

    best_key = None
    best_val = None
    min_trials = float("inf")

    for key, (label, candidates) in CSS_PARAMS.items():
        for val in candidates:
            if val == current_params.get(key):
                continue  # 現在値はスキップ
            n_trials = trial_counts[key].get(val, 0)
            n_loses  = lose_counts[key].get(val, 0)
            # 2回負けた値は候補から除外
            if n_loses >= 2:
                continue
            if n_trials < min_trials:
                min_trials = n_trials
                best_key = key
                best_val = val

    if best_key is None or min_trials >= 3:
        return None  # 全パラメータ試験完了

    new_params = dict(current_params)
    new_params[best_key] = best_val
    return new_params


# ─── 改善候補生成 ────────────────────────────────────────────

def _generate_improvement_candidates(current_params: dict) -> list[dict]:
    """
    未試験または試験回数の少ない変数について最大3案の改善候補を生成する。
    """
    experiments = _load_jsonl(UI_EXP_LOG)
    trial_counts: dict[str, Counter] = {k: Counter() for k in CSS_PARAMS}
    win_counts:   dict[str, Counter] = {k: Counter() for k in CSS_PARAMS}
    lose_counts:  dict[str, Counter] = {k: Counter() for k in CSS_PARAMS}

    for exp in experiments:
        for key, val in exp.get("css_params", {}).items():
            if key not in CSS_PARAMS:
                continue
            trial_counts[key][val] += 1
            if exp.get("status") == "win":
                win_counts[key][val] += 1
            elif exp.get("status") == "lose":
                lose_counts[key][val] += 1

    candidates = []
    for key, (label, values) in CSS_PARAMS.items():
        for val in values:
            if val == current_params.get(key):
                continue
            if lose_counts[key].get(val, 0) >= 2:
                continue
            trials = trial_counts[key].get(val, 0)
            wins   = win_counts[key].get(val, 0)
            priority = wins * 3 - trials  # 勝ち実績があれば優先
            candidates.append({
                "key": key,
                "label": label,
                "value": val,
                "current": current_params.get(key),
                "trials": trials,
                "wins": wins,
                "priority": priority,
            })

    candidates.sort(key=lambda x: (-x["priority"], x["trials"]))
    return candidates[:3]


# ─── CLIコマンド ──────────────────────────────────────────────

def cmd_apply(args):
    print("🎨 ベースCSSを生成・適用します...")
    params = _css_defaults()
    css = generate_css(params)
    print(f"  CSSサイズ: {len(css):,} bytes")
    ok, msg = apply_css_to_wp(css)
    print(f"  {msg}")
    if ok:
        snap = _collect_kpi_snapshot()
        exp_id = f"ui_exp_{datetime.now(JST).strftime('%Y%m%d_%H%M')}_base"
        _append_jsonl(UI_EXP_LOG, {
            "experiment_id": exp_id,
            "timestamp": _now_jst(),
            "css_params": params,
            "applied_at": _now_jst(),
            "baseline_avg_ctr":        snap["avg_ctr"],
            "baseline_avg_dwell_sec":  snap["avg_dwell_sec"],
            "baseline_avg_cta_score":  snap["avg_cta_score"],
            "baseline_cta_source":     snap["cta_source"],
            "result_avg_ctr": 0.0, "result_avg_dwell": 0.0, "result_avg_cta": 0.0,
            "delta_ctr": 0.0, "delta_dwell": 0.0, "delta_cta": 0.0,
            "status": "pending",
            "judgment_mode": "pending",
            "measurement_days": 7,
            "article_types_tracked": list(snap["type_avg_ctr"].keys()),
            "note": "ベースCSS初回適用",
        })
        _append_jsonl(UI_KPI_LOG, {**snap, "trigger": "apply_base"})
        print(f"  実験記録: {exp_id}")
        cta_label = "🔬 実測" if snap['cta_source'] == 'ga4_real' else "📊 代替"
        print(f"  ベースラインKPI: CTR={snap['avg_ctr']} 滞在={snap['avg_dwell_sec']}s CTA={snap['avg_cta_score']} {cta_label}")


def cmd_generate(args):
    params = _get_best_params()
    css = generate_css(params)
    print("─── 生成されたCSS ───")
    print(css[:2000], "...(省略)" if len(css) > 2000 else "")
    print(f"─── パラメータ ───")
    for k, v in params.items():
        label = CSS_PARAMS[k][0]
        print(f"  {label}({k}): {v}")
    print(f"サイズ: {len(css):,} bytes")


def cmd_analyze(args):
    """フルループ: KPI3指標評価 → CSS改善 → WP適用"""
    print(f"[{_now_str()}] ╔══ イルミーゼ UIフルループ開始 ══╗")

    # Step1: KPIスナップショット取得
    print("\n[1/5] 現在のKPI3指標を収集...")
    snap = _collect_kpi_snapshot(days_back=7)
    _append_jsonl(UI_KPI_LOG, {**snap, "trigger": "analyze"})
    cta_label = "🔬 実測" if snap['cta_source'] == 'ga4_real' else "📊 代替指標"
    print(f"  CTR={snap['avg_ctr']} (n={snap['ctr_sample_n']})")
    print(f"  滞在時間={snap['avg_dwell_sec']}s")
    print(f"  CTA率={snap['avg_cta_score']} {cta_label} (n={snap['cta_sample_n']})")
    if snap["type_avg_ctr"]:
        print(f"  タイプ別CTR: {snap['type_avg_ctr']}")

    # Step2: 保留実験を解決
    print("\n[2/5] 保留実験を評価...")
    resolved = _resolve_pending_experiments()
    print(f"  確定: {resolved}件")

    # Step3: 現在ベストパラメータ
    current_params = _get_best_params()
    print(f"\n[3/5] 現在のベストパラメータ:")
    for k, v in current_params.items():
        print(f"  {CSS_PARAMS[k][0]}: {v}")

    # Step4: 次の実験変数を選択
    print("\n[4/5] 次の実験変数を選択...")
    next_params = _pick_next_experiment(current_params)

    if next_params is None:
        print("  → 全変数試験完了。ベストCSSを再適用します。")
        target_params = current_params
        note = "全変数試験完了: ベストパラメータ再確認"
    else:
        diff = {k: v for k, v in next_params.items() if v != current_params.get(k)}
        for k, v in diff.items():
            print(f"  → 実験: {CSS_PARAMS[k][0]} {current_params.get(k)} → {v}")
        target_params = next_params
        note = f"実験: {'; '.join(f'{CSS_PARAMS[k][0]} → {v}' for k,v in diff.items())}"

    # Step5: CSS生成・適用・実験記録
    print("\n[5/5] CSS生成・WP適用...")
    css = generate_css(target_params)
    ok, msg = apply_css_to_wp(css)
    print(f"  {msg}")

    if ok:
        exp_id = f"ui_exp_{datetime.now(JST).strftime('%Y%m%d_%H%M')}"
        _append_jsonl(UI_EXP_LOG, {
            "experiment_id": exp_id,
            "timestamp": _now_jst(),
            "css_params": target_params,
            "applied_at": _now_jst(),
            "baseline_avg_ctr":       snap["avg_ctr"],
            "baseline_avg_dwell_sec": snap["avg_dwell_sec"],
            "baseline_avg_cta_score": snap["avg_cta_score"],
            "result_avg_ctr": 0.0, "result_avg_dwell": 0.0, "result_avg_cta": 0.0,
            "delta_ctr": 0.0, "delta_dwell": 0.0, "delta_cta": 0.0,
            "status": "pending",
            "judgment_mode": "pending",
            "baseline_cta_source": snap.get("cta_source", "proxy"),
            "measurement_days": 7,
            "article_types_tracked": list(snap["type_avg_ctr"].keys()),
            "note": note,
        })

        # 改善候補3案を出力
        print("\n  ─ 改善候補（次回以降）─")
        for i, cand in enumerate(_generate_improvement_candidates(target_params), 1):
            print(f"  案{i}: {cand['label']} {cand['current']} → {cand['value']}"
                  f"  (試験{cand['trials']}回 勝ち{cand['wins']}回)")

        print(f"\n✅ 実験 {exp_id} 開始。7日後に3指標で評価します。")

    print(f"\n[{_now_str()}] ╚══ イルミーゼ UIフルループ完了 ══╝")


def cmd_record(args):
    snap = _collect_kpi_snapshot()
    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except Exception:
            print("--params は JSON形式で指定してください")
            sys.exit(1)
    exp_id = args.id or f"ui_exp_{datetime.now(JST).strftime('%Y%m%d_%H%M')}_manual"
    _append_jsonl(UI_EXP_LOG, {
        "experiment_id": exp_id,
        "timestamp": _now_jst(),
        "css_params": params,
        "applied_at": _now_jst(),
        "baseline_avg_ctr":       snap["avg_ctr"],
        "baseline_avg_dwell_sec": snap["avg_dwell_sec"],
        "baseline_avg_cta_score": snap["avg_cta_score"],
        "result_avg_ctr": 0.0, "result_avg_dwell": 0.0, "result_avg_cta": 0.0,
        "delta_ctr": 0.0, "delta_dwell": 0.0, "delta_cta": 0.0,
        "status": "pending",
        "measurement_days": args.days or 7,
        "article_types_tracked": [],
        "note": args.note or "手動記録",
    })
    print(f"✅ 記録: {exp_id}  CTR={snap['avg_ctr']} 滞在={snap['avg_dwell_sec']}s")


def cmd_update(args):
    experiments = _load_jsonl(UI_EXP_LOG)
    updated = 0
    new_records = []
    for exp in experiments:
        if exp.get("experiment_id") == args.id:
            exp["status"] = args.status
            if args.ctr is not None:
                exp["result_avg_ctr"] = args.ctr
                exp["delta_ctr"] = round(args.ctr - exp.get("baseline_avg_ctr", 0.0), 4)
            if args.dwell is not None:
                exp["result_avg_dwell"] = args.dwell
                exp["delta_dwell"] = round(args.dwell - exp.get("baseline_avg_dwell_sec", 0.0), 2)
            updated += 1
        new_records.append(exp)
    if updated == 0:
        print(f"❌ 実験ID '{args.id}' が見つかりません")
        sys.exit(1)
    with open(UI_EXP_LOG, "w", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ {args.id} → {args.status}")


def cmd_report(args):
    """強化レポート: 3KPI + タイプ別 + 変数ランキング + 次週推奨"""
    experiments = _load_jsonl(UI_EXP_LOG)
    kpi_snaps   = _load_jsonl(UI_KPI_LOG, max_lines=30)

    wins    = [e for e in experiments if e.get("status") == "win"]
    loses   = [e for e in experiments if e.get("status") == "lose"]
    pending = [e for e in experiments if e.get("status") == "pending"]
    neutral = [e for e in experiments if e.get("status") == "neutral"]

    # 現在のUI状態判定
    recent = [e for e in experiments if e.get("status") not in ("pending",)][-5:]
    recent_loses = sum(1 for e in recent if e.get("status") == "lose")
    if recent_loses >= 3:
        ui_state = "🔴 DANGER"
    elif recent_loses >= 1:
        ui_state = "🟡 WATCH"
    else:
        ui_state = "🟢 GOOD"

    print("=" * 64)
    print(f"  イルミーゼ UI最適化レポート  {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}")
    print("=" * 64)
    print(f"  UI状態: {ui_state}")
    print(f"  総実験: {len(experiments)}件  ✅WIN: {len(wins)}  ❌LOSE: {len(loses)}  ➡️中立: {len(neutral)}  ⏳計測中: {len(pending)}")
    print()

    # 現在のKPIスナップ
    if kpi_snaps:
        latest = kpi_snaps[-1]
        print("── 現在のKPI3指標 ──")
        print(f"  CTR スコア    : {latest.get('avg_ctr', 0):.3f}  (n={latest.get('ctr_sample_n', 0)})")
        print(f"  平均滞在時間  : {latest.get('avg_dwell_sec', 0):.1f}秒")
        print(f"  CTA スコア    : {latest.get('avg_cta_score', 0):.3f}  (n={latest.get('cta_sample_n', 0)})")
        if latest.get("type_avg_ctr"):
            print("  記事タイプ別CTR:")
            for t, v in latest["type_avg_ctr"].items():
                print(f"    {t}: {v:.3f}")
        cta_src = latest.get("cta_source", "proxy")
        cta_label = "🔬 実測(GA4)" if cta_src == "ga4_real" else "📊 代替指標"
        print(f"  CTA計測モード : {cta_label}")
        print()

    # CTA実測データ
    cta_records = _load_jsonl(UI_CTA_LOG, max_lines=7) if UI_CTA_LOG.exists() else []
    if cta_records:
        latest_cta = cta_records[-1]
        prov_count = sum(
            1 for e in experiments
            if e.get("judgment_mode") in ("provisional_win", "provisional_lose", "pending")
            and e.get("baseline_cta_source") == "proxy"
        )
        final_count = sum(1 for e in experiments if e.get("judgment_mode") == "final")
        print("── CTAクリック実測（直近） ──")
        print(f"  総クリック数      : {latest_cta.get('total_cta_clicks', 0)}")
        print(f"  CTA率 (PV比)      : {latest_cta.get('cta_ctr_real', 0) or 0:.2%}")
        if "cta_click_top" in latest_cta:
            top  = latest_cta.get("cta_click_top", 0)
            mid  = latest_cta.get("cta_click_middle", 0)
            bot  = latest_cta.get("cta_click_bottom", 0)
            fbar = latest_cta.get("cta_click_fixed_bar", 0)
            total = latest_cta.get("total_cta_clicks", 1) or 1
            print(f"  位置別クリック:")
            print(f"    TOP    : {top}  ({top/total:.1%})")
            print(f"    MIDDLE : {mid}  ({mid/total:.1%})")
            print(f"    BOTTOM : {bot}  ({bot/total:.1%})")
            print(f"    固定バー: {fbar}  ({fbar/total:.1%})")
        imp  = latest_cta.get("fixed_cta_impression", 0) or 0
        fcls = latest_cta.get("fixed_cta_close", 0) or 0
        fclk = latest_cta.get("cta_click_fixed_bar", 0) or 0
        if imp > 0:
            print(f"  固定CTAバー表示数 : {imp}")
            print(f"  固定CTAクリック率 : {fclk/imp:.2%}")
            print(f"  固定CTA閉じる率   : {fcls/imp:.2%}")
        if latest_cta.get("type_breakdown"):
            print("  記事タイプ×位置 クリック数:")
            for art_type, pos_map in sorted(latest_cta["type_breakdown"].items()):
                pos_str = "  ".join(f"{p}:{c}" for p, c in sorted(pos_map.items()))
                print(f"    {art_type}: {pos_str}")
        print(f"  判定モード: provisional={prov_count}件  final={final_count}件")
        print()
    elif UI_CTA_LOG.exists():
        print("── CTAクリック実測 ──")
        print("  データなし（GA4イベント計測開始前）")
        print()

    # 勝ち変数ランキング
    win_var_counts: Counter = Counter()
    lose_var_counts: Counter = Counter()
    for exp in wins:
        for k in exp.get("css_params", {}):
            if k in CSS_PARAMS:
                win_var_counts[CSS_PARAMS[k][0]] += 1
    for exp in loses:
        for k in exp.get("css_params", {}):
            if k in CSS_PARAMS:
                lose_var_counts[CSS_PARAMS[k][0]] += 1

    if win_var_counts:
        print("── 勝ち変数ランキング ──")
        for label, cnt in win_var_counts.most_common(5):
            print(f"  {'★' * min(cnt,3)} {label} ({cnt}回勝ち)")
        print()

    if lose_var_counts:
        print("── 負け変数ランキング ──")
        for label, cnt in lose_var_counts.most_common(3):
            print(f"  ⚠️  {label} ({cnt}回負け)")
        print()

    # 現在のベストパラメータ
    current_params = _get_best_params()
    print("── 現在のベストパラメータ ──")
    for k, v in current_params.items():
        print(f"  {CSS_PARAMS[k][0]:<14}: {v}")
    print()

    # 次週テスト変数
    next_params = _pick_next_experiment(current_params)
    if next_params:
        diff = {k: v for k, v in next_params.items() if v != current_params.get(k)}
        print("── 次週テスト推奨（1変数のみ） ──")
        for k, v in diff.items():
            print(f"  変数 : {CSS_PARAMS[k][0]}")
            print(f"  現在値: {current_params.get(k)}")
            print(f"  試験値: {v}")
    else:
        print("── 次週テスト ──")
        print("  全変数試験完了。ベストパラメータを継続維持します。")

    print()

    # 最新5件実験
    print("── 最新5件の実験 ──")
    for exp in experiments[-5:]:
        icon = {"win":"✅","lose":"❌","pending":"⏳","neutral":"➡️",
                "insufficient_data":"⚠️","rollback":"🔄"}.get(exp.get("status"),"?")
        d_ctr   = exp.get("delta_ctr", 0)
        d_dwell = exp.get("delta_dwell", 0)
        d_cta   = exp.get("delta_cta", 0)
        delta_str = f"CTR{d_ctr:+.4f} 滞在{d_dwell:+.1f}s CTA{d_cta:+.4f}" if d_ctr else ""
        print(f"  {icon} {exp.get('experiment_id','?')[:30]}")
        if delta_str:
            print(f"     {delta_str}")
        if exp.get("verdict_reason"):
            print(f"     → {exp['verdict_reason']}")
    print("=" * 64)


def cmd_rollback(args):
    history = _load_jsonl(UI_CSS_HIST)
    if len(history) < 2:
        print("❌ ロールバック先がありません")
        sys.exit(1)
    target = history[-2]
    css = target.get("css", "")
    if not css:
        print("❌ ロールバック先のCSSが空です")
        sys.exit(1)
    version = target.get("version")
    print(f"🔄 v{version} にロールバックします...")
    ok, msg = apply_css_to_wp(css)
    print(f"  {msg}")
    if ok:
        _append_jsonl(UI_EXP_LOG, {
            "experiment_id": f"rollback_{datetime.now(JST).strftime('%Y%m%d_%H%M')}",
            "timestamp": _now_jst(),
            "css_params": {},
            "applied_at": _now_jst(),
            "baseline_avg_ctr": 0.0, "baseline_avg_dwell_sec": 0.0, "baseline_avg_cta_score": 0.0,
            "result_avg_ctr": 0.0, "result_avg_dwell": 0.0, "result_avg_cta": 0.0,
            "delta_ctr": 0.0, "delta_dwell": 0.0, "delta_cta": 0.0,
            "status": "rollback",
            "measurement_days": 0,
            "article_types_tracked": [],
            "note": f"v{version}へロールバック",
        })


# ─── main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="イルミーゼ UI最適化エージェント v2")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("apply",    help="ベースCSS適用")
    sub.add_parser("generate", help="学習CSSを生成して表示")
    sub.add_parser("analyze",  help="KPI3指標評価→CSS改善→WP適用（フルループ）")
    sub.add_parser("rollback", help="直前バージョンに戻す")
    sub.add_parser("report",   help="レポート表示")

    p_rec = sub.add_parser("record", help="実験を記録")
    p_rec.add_argument("--id",     help="実験ID")
    p_rec.add_argument("--params", help='CSS変数JSON')
    p_rec.add_argument("--days",   type=int, default=7)
    p_rec.add_argument("--note",   help="メモ")

    p_upd = sub.add_parser("update", help="実験結果を手動確定")
    p_upd.add_argument("--id",     required=True)
    p_upd.add_argument("--status", required=True,
                       choices=["win","lose","neutral","insufficient_data"])
    p_upd.add_argument("--ctr",   type=float, help="結果CTRスコア")
    p_upd.add_argument("--dwell", type=float, help="結果滞在時間(秒)")

    args = parser.parse_args()
    dispatch = {
        "apply": cmd_apply, "generate": cmd_generate, "analyze": cmd_analyze,
        "record": cmd_record, "update": cmd_update, "report": cmd_report,
        "rollback": cmd_rollback,
    }
    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
