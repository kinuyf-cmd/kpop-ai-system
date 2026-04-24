#!/usr/bin/env python3
"""
site_redesign.py — K-POP Journal サイト全面リニューアル v5.0

kstyle・daebak・Soompiを超えるビジュアルデザインを実装。
ui_optimizer.py の apply_css_to_wp() と同じ仕組みでWPに適用する。

ブランドコンセプト:
  - Premium K-POP Media — ファン必携のハイエンドメディア感
  - 韓国デザインの洗練さ + 日本メディアの信頼感
  - ダークモード対応（CSS変数ベース）

Usage:
  python3 lib/site_redesign.py preview   # CSS/JSプレビュー（適用しない）
  python3 lib/site_redesign.py apply     # WPに適用
  python3 lib/site_redesign.py rollback  # 直前バージョンに戻す
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE     = Path(__file__).parent.parent
LOGS     = BASE / "logs"
WP_BASE  = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH  = Path.home() / ".wp_auth"
CSS_HIST = LOGS / "site_redesign_history.jsonl"
JST = timezone(timedelta(hours=9))

# ─── ブランドカラーシステム ────────────────────────────────────
BRAND = {
    "primary":       "#FF2D55",   # K-POP Pink
    "primary_dark":  "#E0264B",
    "primary_light": "#FF6B8A",
    "secondary":     "#7B61FF",   # Creative Purple
    "accent":        "#00D4AA",   # Fresh Mint
    "gold":          "#FFB800",   # Premium Gold
    "dark_bg":       "#0A0A0F",   # Rich Black
    "dark_surface":  "#14141F",   # Card BG Dark
    "dark_elevated": "#1E1E2E",   # Elevated surface
    "light_bg":      "#FAFAFA",   # Light mode BG
    "light_surface": "#FFFFFF",
    "text_primary":  "#1A1A2E",   # Dark text
    "text_secondary":"#6B7280",
    "text_on_dark":  "#F1F5F9",
    "gradient_start":"#FF2D55",
    "gradient_end":  "#7B61FF",
}


def _get_redesign_css() -> str:
    """v5.0 完全リデザインCSS"""
    return f"""
/* ============================================================
   K-POP JOURNAL — Site Redesign v5.0 (Phase5 UI/UX完全刷新)
   Generated: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}

   Design: Premium K-POP Media (kstyle/daebak/Soompi超え)
   Features: CSS変数 / ダークモード / レスポンシブ / アニメーション
   ============================================================ */

/* ─── CSS変数（テーマ切替対応） ─── */
:root {{
  --kpj-primary: {BRAND['primary']};
  --kpj-primary-dark: {BRAND['primary_dark']};
  --kpj-primary-light: {BRAND['primary_light']};
  --kpj-secondary: {BRAND['secondary']};
  --kpj-accent: {BRAND['accent']};
  --kpj-gold: {BRAND['gold']};
  --kpj-bg: {BRAND['light_bg']};
  --kpj-surface: {BRAND['light_surface']};
  --kpj-surface-elevated: #F8F8FC;
  --kpj-text: {BRAND['text_primary']};
  --kpj-text-secondary: {BRAND['text_secondary']};
  --kpj-text-muted: #9CA3AF;
  --kpj-border: #E5E7EB;
  --kpj-shadow: 0 4px 20px rgba(0,0,0,0.06);
  --kpj-shadow-hover: 0 8px 32px rgba(0,0,0,0.12);
  --kpj-gradient: linear-gradient(135deg, {BRAND['gradient_start']}, {BRAND['gradient_end']});
  --kpj-radius: 16px;
  --kpj-radius-sm: 10px;
  --kpj-transition: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  --kpj-font: 'Noto Sans JP', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}

/* ─── ダークモード ─── */
[data-theme="dark"] {{
  --kpj-bg: {BRAND['dark_bg']};
  --kpj-surface: {BRAND['dark_surface']};
  --kpj-surface-elevated: {BRAND['dark_elevated']};
  --kpj-text: {BRAND['text_on_dark']};
  --kpj-text-secondary: #94A3B8;
  --kpj-text-muted: #64748B;
  --kpj-border: #2D2D3F;
  --kpj-shadow: 0 4px 20px rgba(0,0,0,0.3);
  --kpj-shadow-hover: 0 8px 32px rgba(0,0,0,0.5);
}}

/* ─── グローバルリセット ─── */
body {{
  font-family: var(--kpj-font) !important;
  background: var(--kpj-bg) !important;
  color: var(--kpj-text) !important;
  transition: background var(--kpj-transition), color var(--kpj-transition);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}}
* {{ box-sizing: border-box; }}

/* ─── ヘッダー（グラデーション + グラスモーフィズム） ─── */
#header, .site-header {{
  background: linear-gradient(135deg, #0F0F1A 0%, #1A1A2E 50%, #16213E 100%) !important;
  border-bottom: 1px solid rgba(255,45,85,0.15) !important;
  backdrop-filter: blur(20px);
  position: sticky !important;
  top: 0;
  z-index: 999;
}}
.site-name-text, .site-name-text a {{
  color: #fff !important;
  font-size: 28px !important;
  font-weight: 900 !important;
  letter-spacing: 0.06em;
  background: var(--kpj-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
.tagline {{
  color: rgba(255,255,255,0.6) !important;
  font-size: 12px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}

/* ─── ナビゲーション ─── */
.navi, .navi-in {{
  background: transparent !important;
}}
.navi-in a {{
  color: rgba(255,255,255,0.85) !important;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: 0.03em;
  padding: 14px 18px !important;
  transition: color var(--kpj-transition);
  position: relative;
}}
.navi-in a:hover {{
  color: var(--kpj-primary) !important;
}}
.navi-in a::after {{
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  width: 0;
  height: 2px;
  background: var(--kpj-gradient);
  transition: all var(--kpj-transition);
  transform: translateX(-50%);
}}
.navi-in a:hover::after {{
  width: 60%;
}}

/* ─── 速報帯（Breaking News Ticker） ─── */
#kpj-ticker {{
  background: linear-gradient(90deg, var(--kpj-primary), var(--kpj-secondary));
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  padding: 8px 0;
  overflow: hidden;
  white-space: nowrap;
  position: relative;
}}
#kpj-ticker .ticker-label {{
  background: rgba(0,0,0,0.3);
  padding: 3px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 800;
  margin-right: 16px;
  letter-spacing: 0.08em;
  display: inline-block;
  vertical-align: middle;
}}
#kpj-ticker .ticker-content {{
  display: inline-block;
  animation: kpjTickerScroll 30s linear infinite;
  vertical-align: middle;
}}
@keyframes kpjTickerScroll {{
  0% {{ transform: translateX(0); }}
  100% {{ transform: translateX(-50%); }}
}}

/* ─── ヒーローセクション（トップページ最新記事） ─── */
.front-top-page .entry-title {{ display: none !important; }}
.front-top-page .eye-catch-wrap {{ display: none !important; }}
.front-top-page .date-tags {{ display: none !important; }}
.front-top-page .article-header {{ padding: 0 !important; margin: 0 !important; min-height: 0 !important; }}

/* ヒーロー: 最新記事1件目 */
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child {{
  flex: 0 0 100% !important;
  max-width: 100% !important;
  margin-bottom: 20px;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-thumb {{
  padding-top: 0;
  height: auto;
  position: relative;
  overflow: hidden;
  border-radius: var(--kpj-radius);
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-thumb img {{
  position: relative;
  width: 100%;
  height: auto;
  max-height: 460px;
  object-fit: cover;
  border-radius: var(--kpj-radius) var(--kpj-radius) 0 0;
  transition: transform 0.5s ease;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child:hover .card-thumb img {{
  transform: scale(1.03);
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-content {{
  background: linear-gradient(135deg, #0F0F1A 0%, #1A1A2E 100%);
  padding: 24px 22px;
  border-radius: 0 0 var(--kpj-radius) var(--kpj-radius);
  position: relative;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-content::before {{
  content: 'LATEST';
  position: absolute;
  top: -14px;
  left: 22px;
  background: var(--kpj-gradient);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  padding: 4px 14px;
  border-radius: 6px;
  letter-spacing: 0.1em;
}}
.front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-title {{
  color: #fff !important;
  font-size: 22px !important;
  font-weight: 800;
  line-height: 1.45;
  -webkit-line-clamp: 3;
}}

/* ─── カードグリッド（kstyle超えデザイン） ─── */
.front-top-page .new-entry-cards .swiper-wrapper {{
  display: flex !important;
  flex-wrap: wrap !important;
  gap: 18px;
  transform: none !important;
}}
.front-top-page .new-entry-cards .swiper-slide {{
  flex: 0 0 calc(50% - 9px);
  max-width: calc(50% - 9px);
  margin: 0 !important;
}}
.front-top-page .new-entry-card-link {{
  display: block;
  border-radius: var(--kpj-radius);
  overflow: hidden;
  background: var(--kpj-surface);
  box-shadow: var(--kpj-shadow);
  transition: all var(--kpj-transition);
  text-decoration: none;
  border: 1px solid var(--kpj-border);
}}
.front-top-page .new-entry-card-link:hover {{
  transform: translateY(-4px);
  box-shadow: var(--kpj-shadow-hover);
  border-color: var(--kpj-primary);
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
  transition: transform 0.4s ease;
}}
.front-top-page .new-entry-card-link:hover .card-thumb img {{
  transform: scale(1.06);
}}
.front-top-page .new-entry-card .card-content {{
  padding: 14px 16px 16px;
}}
.front-top-page .new-entry-card .card-title {{
  font-size: 14.5px;
  font-weight: 700;
  line-height: 1.55;
  color: var(--kpj-text);
  -webkit-line-clamp: 2;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
.front-top-page .entry-date, .post-date, time.published {{
  font-size: 11px;
  color: var(--kpj-text-muted);
  margin-top: 6px;
}}

/* ─── 記事本文（プレミアムリーディング体験） ─── */
.entry-content {{
  font-size: 17px !important;
  line-height: 1.9 !important;
  color: var(--kpj-text) !important;
  padding: 0 16px !important;
  max-width: 100% !important;
  word-break: break-word;
}}
.entry-content p {{
  margin-bottom: 22px;
  font-size: 17px;
  line-height: 1.9;
}}

/* 見出し — アクセントライン付き */
.entry-content h2 {{
  font-size: 23px;
  font-weight: 800;
  margin-top: 40px;
  margin-bottom: 16px;
  padding: 14px 18px;
  background: var(--kpj-surface-elevated);
  border-left: 4px solid var(--kpj-primary);
  border-radius: 0 var(--kpj-radius-sm) var(--kpj-radius-sm) 0;
  line-height: 1.45;
  color: var(--kpj-text);
  position: relative;
}}
.entry-content h3 {{
  font-size: 19px;
  font-weight: 700;
  margin-top: 28px;
  margin-bottom: 12px;
  color: var(--kpj-text);
  padding-left: 14px;
  border-left: 3px solid var(--kpj-secondary);
  line-height: 1.5;
}}

/* 画像 */
.entry-content img {{
  max-width: 100% !important;
  height: auto !important;
  border-radius: var(--kpj-radius-sm);
  display: block;
  margin: 8px auto;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
}}

/* ─── カテゴリ・タグ ─── */
.category-tag, .cat-links a {{
  display: inline-block;
  background: var(--kpj-gradient);
  color: #fff !important;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
  text-decoration: none;
  margin-right: 4px;
  letter-spacing: 0.02em;
}}

/* ─── 記事タイプバッジ ─── */
.article-type {{
  display: inline-block;
  font-size: 11px;
  font-weight: 800;
  padding: 4px 12px;
  border-radius: 6px;
  margin-bottom: 14px;
  letter-spacing: 0.05em;
}}
.article-type.speed     {{ background: var(--kpj-primary); color: #fff; }}
.article-type.guide     {{ background: var(--kpj-secondary); color: #fff; }}
.article-type.explanation {{ background: #374151; color: #fff; }}

/* ─── CTAボックス（プレミアムデザイン） ─── */
.cta-box, .revenue-cta {{
  border-radius: var(--kpj-radius);
  margin: 32px 0;
  background: linear-gradient(135deg, rgba(255,45,85,0.05), rgba(123,97,255,0.05));
  border: 1px solid rgba(255,45,85,0.15);
  padding: 20px;
}}
.cta-box a, .revenue-cta a {{
  display: inline-block;
  padding: 14px 32px;
  border-radius: var(--kpj-radius-sm);
  font-weight: 700;
  font-size: 15px;
  text-decoration: none;
  min-height: 44px;
}}
.kpj-cta-btn {{
  display: block;
  width: 100%;
  padding: 0 24px;
  border-radius: var(--kpj-radius-sm);
  background: var(--kpj-gradient) !important;
  color: #fff !important;
  font-size: 16px;
  font-weight: 800;
  text-align: center;
  text-decoration: none;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(255,45,85,0.3);
  transition: all var(--kpj-transition);
  min-height: 52px;
  line-height: 52px;
}}
.kpj-cta-btn:hover {{
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(255,45,85,0.45);
  color: #fff !important;
}}

/* ─── 関連記事（カード型） ─── */
.related-articles {{
  background: var(--kpj-surface-elevated);
  border: 1px solid var(--kpj-border);
  border-radius: var(--kpj-radius);
  padding: 20px;
  margin: 32px 0;
}}
.related-articles h3 {{
  font-size: 15px;
  font-weight: 800;
  margin: 0 0 12px;
  color: var(--kpj-primary);
  border: none;
  padding: 0;
}}
.related-articles ul  {{ list-style: none; margin: 0; padding: 0; }}
.related-articles li  {{
  font-size: 14px;
  line-height: 1.8;
  color: var(--kpj-text-secondary);
  padding: 6px 0;
  border-bottom: 1px solid var(--kpj-border);
}}
.related-articles li:last-child {{ border-bottom: none; }}
.related-articles li a {{ color: var(--kpj-primary); text-decoration: none; font-weight: 600; }}
.related-articles li a:hover {{ text-decoration: underline; }}

/* ─── SNSシェアボタン ─── */
.kpj-share {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 20px 0 28px;
  padding: 14px 0;
}}
.kpj-share a {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  text-decoration: none;
  color: #fff !important;
  font-size: 16px;
  font-weight: 700;
  transition: all var(--kpj-transition);
}}
.kpj-share a:hover {{
  transform: scale(1.15);
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}}
.kpj-share .share-x     {{ background: #000; }}
.kpj-share .share-line   {{ background: #06C755; }}
.kpj-share .share-fb     {{ background: #1877F2; }}
.kpj-share .share-copy   {{ background: var(--kpj-text-muted); cursor: pointer; }}

.kpj-share-top {{
  background: var(--kpj-surface-elevated);
  border: 1px solid var(--kpj-border);
  border-radius: var(--kpj-radius-sm);
  padding: 12px 16px;
  margin: 14px 0 22px;
}}
.kpj-share-bottom {{
  background: var(--kpj-surface-elevated);
  border-top: 2px solid var(--kpj-primary);
  border-radius: 0 0 var(--kpj-radius-sm) var(--kpj-radius-sm);
  padding: 16px;
  margin: 36px 0 16px;
}}

/* フローティングシェア（PC左サイド） */
.kpj-share-float {{
  display: none;
  position: fixed;
  left: max(calc(50% - 440px), 12px);
  top: 50%;
  transform: translateY(-50%);
  flex-direction: column;
  gap: 8px;
  z-index: 9990;
  background: var(--kpj-surface);
  border-radius: 14px;
  padding: 10px 8px;
  box-shadow: var(--kpj-shadow);
  border: 1px solid var(--kpj-border);
}}
@media (min-width: 1100px) {{
  .kpj-share-float {{ display: flex; }}
}}

/* ─── 急上昇ランキング ─── */
#kpj-trending {{
  background: var(--kpj-surface-elevated);
  border-radius: var(--kpj-radius);
  padding: 22px 18px;
  margin: 0 0 24px;
  border: 1px solid var(--kpj-border);
}}
#kpj-trending h2 {{
  font-size: 18px;
  font-weight: 800;
  color: var(--kpj-text);
  margin: 0 0 16px;
  padding: 0;
  border: none;
  background: none;
}}
#kpj-trending .kpj-trend-item {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  border-radius: var(--kpj-radius-sm);
  transition: background var(--kpj-transition);
  text-decoration: none;
  color: var(--kpj-text);
}}
#kpj-trending .kpj-trend-item:hover {{
  background: rgba(255,45,85,0.06);
}}
#kpj-trending .kpj-trend-rank {{
  font-size: 16px;
  font-weight: 900;
  width: 32px;
  height: 32px;
  line-height: 32px;
  text-align: center;
  border-radius: 8px;
  flex-shrink: 0;
}}
#kpj-trending .kpj-trend-rank.r1 {{ background: var(--kpj-primary); color: #fff; }}
#kpj-trending .kpj-trend-rank.r2 {{ background: var(--kpj-primary-light); color: #fff; }}
#kpj-trending .kpj-trend-rank.r3 {{ background: var(--kpj-gold); color: #1a1a2e; }}
#kpj-trending .kpj-trend-title {{
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
  flex: 1;
}}
#kpj-trending .kpj-trend-badge {{
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--kpj-primary);
  color: #fff;
}}

/* ─── モバイル固定CTAバー ─── */
#kpj-fixed-cta {{
  display: none;
  position: fixed;
  bottom: 0; left: 0;
  width: 100%;
  height: 58px;
  background: var(--kpj-gradient) !important;
  z-index: 9999;
  align-items: center;
  justify-content: center;
  box-shadow: 0 -4px 20px rgba(255,45,85,0.3);
}}

/* ─── ダークモードトグル ─── */
#kpj-theme-toggle {{
  position: fixed;
  bottom: 76px;
  right: 16px;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--kpj-surface);
  border: 1px solid var(--kpj-border);
  box-shadow: var(--kpj-shadow);
  cursor: pointer;
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  transition: all var(--kpj-transition);
}}
#kpj-theme-toggle:hover {{
  transform: scale(1.1);
  box-shadow: var(--kpj-shadow-hover);
}}

/* ─── サイドバー ─── */
.widget-sidebar-title {{
  font-size: 16px;
  font-weight: 800;
  color: var(--kpj-text);
  border-bottom: 3px solid var(--kpj-primary);
  padding-bottom: 8px;
  margin-bottom: 14px;
}}

/* ─── 記事一覧カード ─── */
.post-card, article.post {{
  border-radius: var(--kpj-radius);
  box-shadow: var(--kpj-shadow);
  margin-bottom: 18px;
  overflow: hidden;
  background: var(--kpj-surface);
  transition: all var(--kpj-transition);
  border: 1px solid var(--kpj-border);
}}
.post-card:hover, article.post:hover {{
  transform: translateY(-3px);
  box-shadow: var(--kpj-shadow-hover);
}}

/* タイトルリンク */
.entry-title a, .post-card .post-title {{
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.55;
  color: var(--kpj-text);
  text-decoration: none;
  transition: color var(--kpj-transition);
}}
.entry-title a:hover {{ color: var(--kpj-primary); }}

/* ─── lazyload ─── */
img[loading="lazy"] {{ opacity: 0; transition: opacity 0.4s ease; }}
img[loading="lazy"].loaded {{ opacity: 1; }}

/* ─── レスポンシブ ─── */
@media (max-width: 768px) {{
  #kpj-fixed-cta {{ display: flex; }}
  body {{ padding-bottom: 58px; }}
  .entry-content {{
    padding: 0 14px !important;
  }}
  .entry-content h2 {{
    font-size: 20px;
    padding: 12px 14px;
    margin-top: 32px;
  }}
  .front-top-page .new-entry-cards .swiper-slide {{
    flex: 0 0 100%;
    max-width: 100%;
  }}
  .front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-thumb img {{
    max-height: 240px;
  }}
  .front-top-page .new-entry-cards.is-list-horizontal .swiper-slide:first-child .card-title {{
    font-size: 18px !important;
  }}
  #kpj-trending {{
    padding: 16px 14px;
    border-radius: var(--kpj-radius-sm);
  }}
  .site-name-text, .site-name-text a {{
    font-size: 22px !important;
  }}
  /* タップターゲット44px */
  .front-top-page .new-entry-card-link {{ min-height: 44px; }}
}}
@media (min-width: 769px) {{
  .entry-content {{
    max-width: 780px;
    margin: 0 auto;
    padding: 0 20px !important;
  }}
  .front-top-page .new-entry-cards .swiper-slide {{
    flex: 0 0 calc(33.333% - 12px);
    max-width: calc(33.333% - 12px);
  }}
}}

/* ─── フッター強化 ─── */
#footer, .site-footer {{
  background: linear-gradient(135deg, #0F0F1A 0%, #1A1A2E 100%) !important;
  color: rgba(255,255,255,0.7) !important;
  border-top: 1px solid rgba(255,45,85,0.15);
}}
#footer a {{ color: var(--kpj-primary) !important; }}

/* ─── アニメーション ─── */
@keyframes kpjFadeInUp {{
  from {{ opacity: 0; transform: translateY(20px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.entry-content, .new-entry-card {{
  animation: kpjFadeInUp 0.5s ease-out;
}}

/* ─── スクロールバー ─── */
::-webkit-scrollbar {{ width: 8px; }}
::-webkit-scrollbar-track {{ background: var(--kpj-bg); }}
::-webkit-scrollbar-thumb {{
  background: linear-gradient(var(--kpj-primary), var(--kpj-secondary));
  border-radius: 4px;
}}

/* ─── 選択色 ─── */
::selection {{
  background: rgba(255,45,85,0.2);
  color: var(--kpj-text);
}}

/* ─── ページ速度 ─── */
.front-top-page .new-entry-card .card-thumb img {{
  content-visibility: auto;
  contain-intrinsic-size: 320px 180px;
}}
.front-top-page {{ text-rendering: optimizeSpeed; }}
.front-top-page .ad-area {{ min-height: 90px; contain: layout style; }}

/* ============================================================
   Phase6 UI/UX全面改善 — 広告制御・サイドバー・トップ・記事改善
   ============================================================ */

/* ─── 広告制御: 不要広告の非表示 + 配置最適化 ─── */
/* 自動広告の過剰表示を抑制 */
.adsbygoogle[data-ad-status="unfilled"] {{ display: none !important; }}
ins.adsbygoogle[data-ad-format="auto"]:not(.kpopj-ad ins) {{
  max-height: 280px !important;
}}
/* サイドバー広告を最大2つに制限 */
.sidebar .adsbygoogle:nth-of-type(n+3) {{ display: none !important; }}
.sidebar ins.adsbygoogle:nth-of-type(n+3) {{ display: none !important; }}
/* 記事内の自動挿入広告を抑制（手動配置のみ許可） */
.entry-content > ins.adsbygoogle:not([data-ad-slot]) {{ display: none !important; }}
.entry-content > div[id^="google_ads"]:not(.kpopj-ad) {{ display: none !important; }}
/* 「続きへ進むにはこちらをクリック」ゲートを非表示 */
.entry-content .kpj-gate-overlay,
.entry-content .continue-reading-gate,
.entry-content [class*="click-to-continue"],
.entry-content [class*="gate-overlay"],
.entry-content [id*="content-gate"] {{
  display: none !important;
}}
/* 広告の見た目を改善（ラベル付き・余白調整） */
.kpopj-ad {{
  position: relative;
  margin: 28px auto;
  max-width: 728px;
  text-align: center;
}}
.kpopj-ad::before {{
  content: 'AD';
  display: block;
  font-size: 10px;
  font-weight: 700;
  color: var(--kpj-text-muted);
  letter-spacing: 0.12em;
  margin-bottom: 6px;
  opacity: 0.5;
}}

/* ─── サイドバー刷新 ─── */
#sidebar, .sidebar {{
  display: flex;
  flex-direction: column;
  gap: 20px;
}}
/* 不要なサイドバーウィジェットを非表示 */
.sidebar .widget_text:has(ins.adsbygoogle):nth-of-type(n+3),
.sidebar .widget_custom_html:has(ins.adsbygoogle):nth-of-type(n+3) {{
  display: none !important;
}}

/* 人気記事TOP5 ウィジェット */
#kpj-popular-posts {{
  background: var(--kpj-surface);
  border-radius: var(--kpj-radius);
  padding: 20px 18px;
  border: 1px solid var(--kpj-border);
}}
#kpj-popular-posts h3 {{
  font-size: 16px;
  font-weight: 800;
  margin: 0 0 14px;
  padding-bottom: 8px;
  border-bottom: 3px solid var(--kpj-primary);
  color: var(--kpj-text);
  background: none;
  border-left: none;
}}
#kpj-popular-posts .kpj-pop-item {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--kpj-border);
  text-decoration: none;
  transition: all var(--kpj-transition);
}}
#kpj-popular-posts .kpj-pop-item:last-child {{
  border-bottom: none;
}}
#kpj-popular-posts .kpj-pop-item:hover {{
  transform: translateX(4px);
}}
#kpj-popular-posts .kpj-pop-rank {{
  font-size: 18px;
  font-weight: 900;
  min-width: 28px;
  text-align: center;
  color: var(--kpj-text-muted);
}}
#kpj-popular-posts .kpj-pop-rank.top3 {{
  color: var(--kpj-primary);
}}
#kpj-popular-posts .kpj-pop-thumb {{
  width: 64px;
  height: 48px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}}
#kpj-popular-posts .kpj-pop-title {{
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--kpj-text);
  flex: 1;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}}
#kpj-popular-posts .kpj-pop-views {{
  font-size: 10px;
  color: var(--kpj-text-muted);
  white-space: nowrap;
}}

/* アーティスト別カテゴリ（コンパクト表示） */
#kpj-artist-cats {{
  background: var(--kpj-surface);
  border-radius: var(--kpj-radius);
  padding: 20px 18px;
  border: 1px solid var(--kpj-border);
}}
#kpj-artist-cats h3 {{
  font-size: 16px;
  font-weight: 800;
  margin: 0 0 14px;
  padding-bottom: 8px;
  border-bottom: 3px solid var(--kpj-secondary);
  color: var(--kpj-text);
  background: none;
  border-left: none;
}}
#kpj-artist-cats .kpj-cat-grid {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}
#kpj-artist-cats .kpj-cat-chip {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 20px;
  background: var(--kpj-surface-elevated);
  border: 1px solid var(--kpj-border);
  font-size: 12px;
  font-weight: 600;
  color: var(--kpj-text);
  text-decoration: none;
  transition: all var(--kpj-transition);
  white-space: nowrap;
}}
#kpj-artist-cats .kpj-cat-chip:hover {{
  border-color: var(--kpj-primary);
  background: rgba(255,45,85,0.06);
  color: var(--kpj-primary);
  transform: translateY(-1px);
}}
#kpj-artist-cats .kpj-cat-count {{
  font-size: 10px;
  color: var(--kpj-text-muted);
  font-weight: 400;
}}

/* ─── トップページ: 特集セクション（アーティスト別） ─── */
#kpj-featured-artists {{
  margin: 32px 0;
  padding: 28px 0;
}}
#kpj-featured-artists h2 {{
  font-size: 20px;
  font-weight: 800;
  margin: 0 0 20px;
  padding: 0 16px;
  color: var(--kpj-text);
  background: none;
  border: none;
}}
#kpj-featured-artists h2::before {{
  content: '';
  display: inline-block;
  width: 4px;
  height: 20px;
  background: var(--kpj-gradient);
  border-radius: 2px;
  margin-right: 10px;
  vertical-align: middle;
}}
.kpj-artist-section {{
  margin-bottom: 28px;
  padding: 0 16px;
}}
.kpj-artist-section-title {{
  font-size: 16px;
  font-weight: 800;
  color: var(--kpj-text);
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.kpj-artist-section-title .kpj-artist-badge {{
  font-size: 11px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 12px;
  background: var(--kpj-gradient);
  color: #fff;
}}
.kpj-artist-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}}
.kpj-artist-card {{
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--kpj-surface);
  border: 1px solid var(--kpj-border);
  border-radius: var(--kpj-radius-sm);
  text-decoration: none;
  transition: all var(--kpj-transition);
}}
.kpj-artist-card:hover {{
  border-color: var(--kpj-primary);
  box-shadow: var(--kpj-shadow-hover);
  transform: translateY(-2px);
}}
.kpj-artist-card-thumb {{
  width: 80px;
  height: 60px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}}
.kpj-artist-card-title {{
  font-size: 13px;
  font-weight: 700;
  color: var(--kpj-text);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  flex: 1;
}}
.kpj-artist-card-date {{
  font-size: 10px;
  color: var(--kpj-text-muted);
  margin-top: 4px;
}}

/* ─── 記事ページ: コメントセクション ─── */
#comments, .comment-area {{
  margin-top: 40px;
  padding: 24px 20px;
  background: var(--kpj-surface);
  border-radius: var(--kpj-radius);
  border: 1px solid var(--kpj-border);
}}
#comments h3, .comment-area h3 {{
  font-size: 18px;
  font-weight: 800;
  color: var(--kpj-text);
  margin: 0 0 16px;
  background: none;
  border: none;
  padding: 0;
}}
#comments .comment-form textarea {{
  width: 100%;
  min-height: 120px;
  border: 2px solid var(--kpj-border);
  border-radius: var(--kpj-radius-sm);
  background: var(--kpj-surface-elevated);
  color: var(--kpj-text);
  padding: 14px;
  font-size: 15px;
  font-family: var(--kpj-font);
  resize: vertical;
  transition: border-color var(--kpj-transition);
}}
#comments .comment-form textarea:focus {{
  border-color: var(--kpj-primary);
  outline: none;
}}
#comments .comment-form input[type="submit"] {{
  display: inline-block;
  padding: 12px 28px;
  border-radius: var(--kpj-radius-sm);
  background: var(--kpj-gradient);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  border: none;
  cursor: pointer;
  margin-top: 10px;
  transition: all var(--kpj-transition);
}}
#comments .comment-form input[type="submit"]:hover {{
  transform: translateY(-2px);
  box-shadow: 0 4px 14px rgba(255,45,85,0.3);
}}
.comment-list .comment {{
  padding: 16px 0;
  border-bottom: 1px solid var(--kpj-border);
}}
.comment-list .comment:last-child {{ border-bottom: none; }}
.comment-author {{
  font-weight: 700;
  font-size: 14px;
  color: var(--kpj-text);
}}
.comment-date {{
  font-size: 11px;
  color: var(--kpj-text-muted);
}}
.comment-body p {{
  font-size: 14px;
  line-height: 1.7;
  color: var(--kpj-text-secondary);
}}

/* ─── PC 3列グリッド強化 ─── */
@media (min-width: 769px) {{
  .kpj-artist-cards {{
    grid-template-columns: repeat(3, 1fr);
  }}
}}
@media (max-width: 768px) {{
  .kpj-artist-cards {{
    grid-template-columns: 1fr;
  }}
  #kpj-artist-cats .kpj-cat-grid {{
    gap: 6px;
  }}
  #kpj-artist-cats .kpj-cat-chip {{
    padding: 5px 10px;
    font-size: 11px;
  }}
}}
"""


def _get_redesign_js() -> str:
    """v5.0 サイトリニューアルJS（ダークモード・速報帯・SNSシェア・CTA計測）"""
    return """
</style>
<!-- K-POP JOURNAL v5.0 — Site Redesign JS -->

<!-- 速報帯 -->
<div id="kpj-ticker" style="display:none">
  <div style="max-width:1200px;margin:0 auto;padding:0 16px;overflow:hidden;white-space:nowrap">
    <span class="ticker-label">BREAKING</span>
    <span class="ticker-content" id="kpj-ticker-text"></span>
  </div>
</div>

<!-- ダークモードトグル -->
<div id="kpj-theme-toggle" title="ダークモード切替">🌙</div>

<!-- モバイル固定CTAバー -->
<div id="kpj-fixed-cta" style="display:none;position:fixed;bottom:0;left:0;width:100%;height:58px;z-index:9999;align-items:center;justify-content:center">
  <a href="https://www.kpopjournal.tokyo/" rel="noopener" style="color:#fff!important;font-weight:800;font-size:15px;text-decoration:none;letter-spacing:.04em;flex:1;text-align:center;line-height:58px">K-POP Journal</a>
  <button id="kpj-fixed-close" style="background:none;border:none;color:#fff;font-size:18px;padding:0 14px;cursor:pointer;opacity:.75;line-height:58px" aria-label="Close">&#10005;</button>
</div>

<!-- SNSシェアフローティング（PC） -->
<div class="kpj-share-float" id="kpj-share-float">
  <a class="share-x" id="kpj-float-x" href="#" target="_blank" rel="noopener" aria-label="X">X</a>
  <a class="share-line" id="kpj-float-line" href="#" target="_blank" rel="noopener" aria-label="LINE">L</a>
  <a class="share-fb" id="kpj-float-fb" href="#" target="_blank" rel="noopener" aria-label="Facebook">f</a>
  <a class="share-copy" id="kpj-float-copy" href="javascript:void(0)" aria-label="Copy">&#128279;</a>
</div>

<script>
(function(){
  'use strict';
  var _g=typeof gtag==='function'?gtag:function(){(window.dataLayer=window.dataLayer||[]).push(arguments);};
  var pp=window.location.pathname;
  var pu=window.location.href;
  var pt=document.title;
  var isSingle=document.body.className.indexOf('single')!==-1;

  /* ─ ダークモード ─ */
  var toggle=document.getElementById('kpj-theme-toggle');
  var saved=localStorage.getItem('kpj-theme');
  if(saved==='dark'||(saved===null&&window.matchMedia('(prefers-color-scheme:dark)').matches)){
    document.documentElement.setAttribute('data-theme','dark');
    if(toggle)toggle.textContent='☀️';
  }
  if(toggle){
    toggle.addEventListener('click',function(){
      var isDark=document.documentElement.getAttribute('data-theme')==='dark';
      if(isDark){
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('kpj-theme','light');
        toggle.textContent='🌙';
      }else{
        document.documentElement.setAttribute('data-theme','dark');
        localStorage.setItem('kpj-theme','dark');
        toggle.textContent='☀️';
      }
      _g('event','theme_toggle',{theme:isDark?'light':'dark',page_path:pp});
    });
  }

  /* ─ 速報帯（トップページ最新5記事タイトル） ─ */
  if(document.body.className.indexOf('front-top-page')!==-1){
    var ticker=document.getElementById('kpj-ticker');
    var tickerText=document.getElementById('kpj-ticker-text');
    if(ticker&&tickerText){
      var titles=[];
      document.querySelectorAll('.new-entry-card .card-title').forEach(function(el,i){
        if(i<5&&el.textContent.trim())titles.push(el.textContent.trim());
      });
      if(titles.length>0){
        var txt=titles.join('　　|　　')+'　　|　　'+titles.join('　　|　　');
        tickerText.textContent=txt;
        ticker.style.display='block';
      }
    }
  }

  /* ─ SNSシェアボタン動的生成 ─ */
  if(isSingle){
    var shareHTML='<div class="kpj-share kpj-share-__POS__"><span class="kpj-share-label" style="font-size:13px;font-weight:700;color:var(--kpj-text-secondary);margin-right:6px">__LABEL__</span>'
      +'<a class="share-x" href="https://x.com/intent/tweet?text='+encodeURIComponent(pt)+'&url='+encodeURIComponent(pu)+'" target="_blank" rel="noopener">X</a>'
      +'<a class="share-line" href="https://social-plugins.line.me/lineit/share?url='+encodeURIComponent(pu)+'" target="_blank" rel="noopener">L</a>'
      +'<a class="share-fb" href="https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(pu)+'" target="_blank" rel="noopener">f</a>'
      +'<a class="share-copy kpj-copy-btn" href="javascript:void(0)">&#128279;</a></div>';
    var entry=document.querySelector('.entry-content');
    if(entry){
      var topDiv=document.createElement('div');
      topDiv.innerHTML=shareHTML.replace(/__POS__/g,'top').replace(/__LABEL__/g,'Share');
      entry.insertBefore(topDiv.firstChild,entry.firstChild);
      var botDiv=document.createElement('div');
      botDiv.innerHTML=shareHTML.replace(/__POS__/g,'bottom').replace(/__LABEL__/g,'Share');
      entry.appendChild(botDiv.firstChild);
    }
    var fl=document.getElementById('kpj-share-float');
    if(fl){
      var fx=document.getElementById('kpj-float-x');
      if(fx)fx.href='https://x.com/intent/tweet?text='+encodeURIComponent(pt)+'&url='+encodeURIComponent(pu);
      var fln=document.getElementById('kpj-float-line');
      if(fln)fln.href='https://social-plugins.line.me/lineit/share?url='+encodeURIComponent(pu);
      var ffb=document.getElementById('kpj-float-fb');
      if(ffb)ffb.href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(pu);
    }
    document.querySelectorAll('.kpj-copy-btn,#kpj-float-copy').forEach(function(btn){
      btn.addEventListener('click',function(e){
        e.preventDefault();
        navigator.clipboard.writeText(pu).then(function(){
          var orig=btn.innerHTML;btn.innerHTML='&#10003;';
          setTimeout(function(){btn.innerHTML=orig;},1500);
        });
        _g('event','share_click',{share_method:'copy',page_path:pp});
      });
    });
    document.querySelectorAll('.kpj-share a,.kpj-share-float a').forEach(function(l){
      if(l.classList.contains('kpj-copy-btn')||l.id==='kpj-float-copy')return;
      l.addEventListener('click',function(){
        var m='unknown';
        if(l.classList.contains('share-x'))m='x';
        else if(l.classList.contains('share-line'))m='line';
        else if(l.classList.contains('share-fb'))m='facebook';
        _g('event','share_click',{share_method:m,page_path:pp});
      });
    });
  }

  /* ─ CTA計測 ─ */
  document.querySelectorAll('.cta-box a,.revenue-cta a,.kpj-cta-btn').forEach(function(l){
    l.addEventListener('click',function(){
      _g('event','cta_click',{cta_label:l.textContent.trim().substring(0,50),page_path:pp});
    });
  });
  document.querySelectorAll('img[loading="lazy"]').forEach(function(i){
    if(i.complete)i.classList.add('loaded');
    else i.addEventListener('load',function(){i.classList.add('loaded');});
  });

  /* ─ 固定CTAバー ─ */
  if(isSingle){
    var bar=document.getElementById('kpj-fixed-cta');
    if(bar){
      bar.style.display='flex';
      document.body.style.paddingBottom='58px';
      var bc=document.getElementById('kpj-fixed-close');
      if(bc)bc.addEventListener('click',function(){
        bar.style.display='none';
        document.body.style.paddingBottom='0';
      });
    }
  }

  /* ─ 急上昇ランキング ─ */
  if(document.body.className.indexOf('front-top-page')!==-1){
    try{
      var trendSrc='{trending_json_escaped}';
      if(trendSrc&&trendSrc!==''){
        var trendData=JSON.parse(trendSrc);
        if(trendData.length>0){
          var rankColors=['r1','r2','r3','r4','r5'];
          var h='<div id="kpj-trending"><h2>\\ud83d\\udcc8 \\u6025\\u4e0a\\u6607\\u30e9\\u30f3\\u30ad\\u30f3\\u30b0</h2><div class="kpj-trend-list">';
          trendData.forEach(function(item,i){
            var badge='';
            if(item.b)badge='<span class="kpj-trend-badge">'+item.b+'</span>';
            h+='<a class="kpj-trend-item" href="'+item.u+'"><span class="kpj-trend-rank '+rankColors[i]+'">'+(i+1)+'</span><span class="kpj-trend-title">'+item.t+'</span>'+badge+'</a>';
          });
          h+='</div></div>';
          var ec=document.querySelector('.entry-content');
          if(ec)ec.innerHTML=h+ec.innerHTML;
        }
      }
    }catch(e){}
  }

  /* ─ IntersectionObserver ─ */
  if('IntersectionObserver' in window){
    var obs=new IntersectionObserver(function(entries){
      entries.forEach(function(entry){
        if(entry.isIntersecting){
          var img=entry.target;
          if(img.dataset.src){img.src=img.dataset.src;img.removeAttribute('data-src');}
          img.classList.add('loaded');
          obs.unobserve(img);
        }
      });
    },{rootMargin:'200px'});
    document.querySelectorAll('img[loading="lazy"]').forEach(function(img){obs.observe(img);});
  }

  /* ─ Phase6: 不要広告ブロック（ギャンブル・ゲーム・IQテスト・出会い系） ─ */
  (function blockUnwantedAds(){
    var blockedKeywords=['iq test','iq テスト','知能テスト','iot','ゲーム','gambling',
      'casino','カジノ','パチンコ','slot','betting','出会い','マッチング','dating',
      'loan','キャッシング','消費者金融','副業','稼げる'];
    function hideUnwanted(){
      document.querySelectorAll('ins.adsbygoogle,iframe[id^="google_ads"],div[id^="google_ads"]').forEach(function(ad){
        var container=ad.closest('div')||ad;
        var txt=(container.textContent||'').toLowerCase()+(container.innerHTML||'').toLowerCase().substring(0,500);
        var src=(ad.getAttribute('src')||'')+(ad.getAttribute('data-ad-client')||'');
        for(var i=0;i<blockedKeywords.length;i++){
          if(txt.indexOf(blockedKeywords[i].toLowerCase())!==-1){
            container.style.display='none';
            break;
          }
        }
      });
    }
    hideUnwanted();
    var adObs=new MutationObserver(function(){hideUnwanted();});
    adObs.observe(document.body,{childList:true,subtree:true});
    setTimeout(hideUnwanted,3000);
    setTimeout(hideUnwanted,8000);
  })();

  /* ─ Phase6: 記事ページ広告を3箇所に制限 ─ */
  if(isSingle){
    setTimeout(function(){
      var manualAds=document.querySelectorAll('.kpopj-ad');
      var autoAds=document.querySelectorAll('.entry-content ins.adsbygoogle:not(.kpopj-ad ins),.entry-content div[id^="google_ads"]:not(.kpopj-ad div)');
      autoAds.forEach(function(ad){
        var p=ad.closest('div')||ad;
        if(!p.classList.contains('kpopj-ad'))p.style.display='none';
      });
    },2000);
  }

  /* ─ Phase6: サイドバー動的生成（人気記事TOP5 + アーティスト別カテゴリ） ─ */
  (function buildSidebar(){
    var sidebar=document.querySelector('#sidebar,.sidebar');
    if(!sidebar)return;

    /* 人気記事TOP5 */
    try{
      var xhr=new XMLHttpRequest();
      xhr.open('GET','""" + WP_BASE + """/posts?per_page=5&orderby=date&order=desc&_fields=id,title,link,featured_media,date&_embed',true);
      xhr.onload=function(){
        if(xhr.status!==200)return;
        var posts=JSON.parse(xhr.responseText);
        var h='<div id="kpj-popular-posts"><h3>\\ud83d\\udcf0 \\u4eba\\u6c17\\u8a18\\u4e8bTOP5</h3>';
        posts.forEach(function(p,i){
          var title=p.title.rendered.replace(/<[^>]+>/g,'');
          var thumb='';
          try{thumb=p._embedded['wp:featuredmedia'][0].media_details.sizes.thumbnail.source_url;}catch(e){}
          var thumbHtml=thumb?'<img class="kpj-pop-thumb" src="'+thumb+'" alt="" loading="lazy">':'';
          var rankClass=i<3?'top3':'';
          h+='<a class="kpj-pop-item" href="'+p.link+'">'
            +'<span class="kpj-pop-rank '+rankClass+'">'+(i+1)+'</span>'
            +thumbHtml
            +'<span class="kpj-pop-title">'+title+'</span></a>';
        });
        h+='</div>';
        var trendEl=document.getElementById('kpj-trending');
        var insertRef=trendEl?trendEl.nextSibling:sidebar.firstChild;
        var div=document.createElement('div');div.innerHTML=h;
        sidebar.insertBefore(div.firstChild,insertRef);
      };
      xhr.send();
    }catch(e){}

    /* アーティスト別カテゴリ */
    var artistCats=[
      {name:'BTS',slug:'bts',emoji:'\\ud83d\\udc9c'},
      {name:'BLACKPINK',slug:'blackpink',emoji:'\\ud83d\\udc96'},
      {name:'SEVENTEEN',slug:'seventeen',emoji:'\\ud83d\\udc8e'},
      {name:'aespa',slug:'aespa',emoji:'\\u2728'},
      {name:'Stray Kids',slug:'stray-kids',emoji:'\\ud83c\\udfb5'},
      {name:'NewJeans',slug:'newjeans',emoji:'\\ud83d\\udc30'},
      {name:'IVE',slug:'ive',emoji:'\\ud83c\\udf1f'},
      {name:'TWICE',slug:'twice',emoji:'\\ud83c\\udf38'},
      {name:'TXT',slug:'txt',emoji:'\\ud83d\\udc99'},
      {name:'LE SSERAFIM',slug:'le-sserafim',emoji:'\\ud83e\\udda5'},
      {name:'ENHYPEN',slug:'enhypen',emoji:'\\ud83e\\uddca'},
      {name:'(G)I-DLE',slug:'gi-dle',emoji:'\\ud83d\\udd25'},
      {name:'ATEEZ',slug:'ateez',emoji:'\\u2693'},
      {name:'ITZY',slug:'itzy',emoji:'\\ud83c\\udf08'}
    ];
    var catHtml='<div id="kpj-artist-cats"><h3>\\ud83c\\udfa4 \\u30a2\\u30fc\\u30c6\\u30a3\\u30b9\\u30c8\\u5225</h3><div class="kpj-cat-grid">';
    var siteBase='""" + "https://www.kpopjournal.tokyo" + """';
    artistCats.forEach(function(c){
      catHtml+='<a class="kpj-cat-chip" href="'+siteBase+'/tag/'+c.slug+'/">'+c.emoji+' '+c.name+'</a>';
    });
    catHtml+='</div></div>';
    var catDiv=document.createElement('div');catDiv.innerHTML=catHtml;
    sidebar.appendChild(catDiv.firstChild);

    /* サイドバー内の3つ目以降の広告ウィジェットを非表示 */
    var sidebarAds=sidebar.querySelectorAll('.widget_text,.widget_custom_html');
    var adCount=0;
    sidebarAds.forEach(function(w){
      if(w.querySelector('ins.adsbygoogle,iframe[id^="aswift"]')){
        adCount++;
        if(adCount>2)w.style.display='none';
      }
    });
  })();

  /* ─ Phase6: トップページ特集セクション（アーティスト別） ─ */
  if(document.body.className.indexOf('front-top-page')!==-1){
    var featuredArtists=['bts','blackpink','aespa','seventeen','stray-kids'];
    var artistNames={bts:'BTS',blackpink:'BLACKPINK',aespa:'aespa',seventeen:'SEVENTEEN','stray-kids':'Stray Kids'};
    var featuredContainer=document.createElement('div');
    featuredContainer.id='kpj-featured-artists';
    featuredContainer.innerHTML='<h2>\\u7279\\u96c6</h2>';
    var entry=document.querySelector('.entry-content,.main');
    if(entry){
      entry.appendChild(featuredContainer);
      featuredArtists.forEach(function(tag){
        try{
          var xh=new XMLHttpRequest();
          var apiUrl='""" + WP_BASE + """/posts?per_page=3&orderby=date&order=desc&_fields=id,title,link,featured_media,date&search='+encodeURIComponent(artistNames[tag]||tag);
          xh.open('GET',apiUrl,true);
          xh.onload=function(){
            if(xh.status!==200)return;
            var posts=JSON.parse(xh.responseText);
            if(posts.length===0)return;
            var sec=document.createElement('div');sec.className='kpj-artist-section';
            var h='<div class="kpj-artist-section-title">'+(artistNames[tag]||tag)+' <span class="kpj-artist-badge">'+posts.length+'\\u4ef6</span></div>';
            h+='<div class="kpj-artist-cards">';
            posts.forEach(function(p){
              var title=p.title.rendered.replace(/<[^>]+>/g,'');
              var d=new Date(p.date);
              var dateStr=(d.getMonth()+1)+'/'+d.getDate();
              h+='<a class="kpj-artist-card" href="'+p.link+'">'
                +'<div><div class="kpj-artist-card-title">'+title+'</div>'
                +'<div class="kpj-artist-card-date">'+dateStr+'</div></div></a>';
            });
            h+='</div>';
            sec.innerHTML=h;
            featuredContainer.appendChild(sec);
          };
          xh.send();
        }catch(e){}
      });
    }
  }

  /* ─ Phase6: コメント機能有効化 ─ */
  if(isSingle){
    var commentArea=document.getElementById('comments')||document.querySelector('.comment-area');
    if(commentArea){
      commentArea.style.display='block';
    }
  }

  /* ─ PWA register ─ */
  if('serviceWorker' in navigator){
    navigator.serviceWorker.register('/sw.js').catch(function(){});
  }
})();
</script>
<style>"""
    # Note: the </style>...<style> trick is inherited from ui_optimizer.py


def generate_full_css_js() -> str:
    """CSSとJSを結合して返す"""
    css = _get_redesign_css()
    js = _get_redesign_js()
    # trending JSON placeholder
    from pathlib import Path as _P
    trending_cache = _P(__file__).parent.parent / "logs" / "trending_ranking.json"
    trending_json = ""
    if trending_cache.exists():
        try:
            import json as _j
            cache = _j.loads(trending_cache.read_text(encoding="utf-8"))
            ranking = cache.get("ranking", [])
            if ranking:
                site = "https://www.kpopjournal.tokyo"
                compact = []
                for item in ranking[:5]:
                    path = item.get("path", f"/{item.get('slug', '')}/")
                    badge = ""
                    if item.get("gsc_clicks", 0) >= 3:
                        badge = "\\u691c\\u7d22\\u6025\\u4e0a\\u6607"
                    elif len(compact) == 0:
                        badge = "HOT"
                    compact.append({"u": f"{site}{path}", "t": item.get("title", ""), "b": badge})
                trending_json = _j.dumps(compact, ensure_ascii=False).replace("'", "\\'")
        except Exception:
            pass
    js = js.replace("{trending_json_escaped}", trending_json)
    return css + js


def _wp_request(method, path, data=None):
    if not WP_AUTH.exists():
        return None, "AUTH_FAIL"
    try:
        content = WP_AUTH.read_text()
        m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
        auth = m.group(1) if m else f"Basic {content.strip().split()[-1]}"
    except Exception as e:
        return None, str(e)
    url = f"{WP_BASE}{path}"
    headers = {"Authorization": auth, "Content-Type": "application/json",
               "User-Agent": "kpop-site-redesign/5.0"}
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        return None, str(e)


def _append_jsonl(record: dict):
    CSS_HIST.parent.mkdir(parents=True, exist_ok=True)
    with open(CSS_HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def cmd_preview(args):
    css_js = generate_full_css_js()
    print(f"CSS+JS total size: {len(css_js):,} bytes")
    print(css_js[:3000])
    print("... (truncated)")


def cmd_apply(args):
    print(f"[{datetime.now(JST).strftime('%H:%M')}] K-POP Journal v5.0 サイトリニューアル適用...")
    css_js = generate_full_css_js()
    print(f"  CSS+JS size: {len(css_js):,} bytes")

    resp, err = _wp_request("POST", "/settings", {"custom_css": css_js})
    if not err:
        _append_jsonl({"timestamp": datetime.now(JST).isoformat(), "version": "5.0",
                       "size": len(css_js), "method": "settings_api", "status": "ok"})
        print(f"  ✅ Settings API 適用成功")
        return

    # Fallback: global-styles
    gs_list, _ = _wp_request("GET", "/global-styles/themes/current-theme")
    if gs_list:
        gs_id = gs_list[0].get("id") if isinstance(gs_list, list) else gs_list.get("id")
        if gs_id:
            gs_resp, gs_err = _wp_request("PUT", f"/global-styles/{gs_id}",
                                          {"settings": {"custom": {"css": css_js}}})
            if not gs_err:
                _append_jsonl({"timestamp": datetime.now(JST).isoformat(), "version": "5.0",
                               "size": len(css_js), "method": "global_styles", "status": "ok"})
                print(f"  ✅ Global Styles API 適用成功")
                return

    print(f"  ❌ 適用失敗: {err}")


def cmd_rollback(args):
    if not CSS_HIST.exists():
        print("❌ 履歴なし")
        return
    recs = []
    for line in CSS_HIST.read_text().splitlines():
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    if len(recs) < 2:
        print("❌ ロールバック先なし")
        return
    print("ロールバック: ui_optimizer.py rollback を使用してください")


def main():
    parser = argparse.ArgumentParser(description="K-POP Journal サイトリニューアル v5.0")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("preview", help="CSS/JSプレビュー")
    sub.add_parser("apply", help="WPに適用")
    sub.add_parser("rollback", help="ロールバック")
    args = parser.parse_args()
    dispatch = {"preview": cmd_preview, "apply": cmd_apply, "rollback": cmd_rollback}
    if args.command not in dispatch:
        parser.print_help()
        sys.exit(1)
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
