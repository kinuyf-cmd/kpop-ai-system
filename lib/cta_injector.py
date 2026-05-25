#!/usr/bin/env python3
"""cta_injector.py — CTA未設置記事に冒頭・中盤・終盤CTAを自動挿入

Phase 14 統合版: アフィリエイト連動ジャンル別CTA + 既存static CTA

判定:
  - data-cta="top|mid|bottom" 属性マーカで既存CTAを検出
  - kpj-cta-block でアフィリCTA検出
  - 3箇所のいずれかが欠けていれば挿入

使い方:
  python3 lib/cta_injector.py [--limit 100] [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT_LOG = LOGS / "cta_updates.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

# === 地域判定ロジック (海外ツアー記事のCTA最適化) ===
_OVERSEAS_KW = ['台北', '高雄', '台湾', 'タイ', 'バンコク', 'インドネシア', 'ジャカルタ',
    'フィリピン', 'マニラ', 'アメリカ', 'ロサンゼルス', 'ニューヨーク', 'コーチェラ',
    'ロンドン', 'ベルリン', 'パリ', 'ヨーロッパ', 'アジアツアー', 'ワールドツアー',
    '海外公演', '北米ツアー', 'シンガポール', 'マレーシア', 'ベトナム']
_KOREA_KW = ['ソウル', '釜山', '明洞', '東大門', '江南', '弘大', '韓国旅行', '韓国コンサート']
_JAPAN_KW = ['KCON JAPAN', '幕張', '来日公演', '日本ツアー', '国立競技場', '東京ドーム']

def detect_region(title: str, content: str) -> str:
    """記事の地域を判定: 'overseas' / 'korea' / 'japan' / 'general'"""
    text = title + ' ' + content[:3000]
    has_overseas = any(k in text for k in _OVERSEAS_KW)
    has_korea = any(k in text for k in _KOREA_KW)
    has_japan = any(k in text for k in _JAPAN_KW)
    if has_overseas and not has_japan and not has_korea:
        return 'overseas'
    if has_korea and not has_japan:
        return 'korea'
    if has_japan:
        return 'japan'
    return 'general'

# --- Phase 14: アフィリエイト連動 ---
try:
    from lib.affiliate_manager import (
        build_a8_link_with_html, get_program_metadata
    )
    from lib.genre_classifier import get_cta_programs_for_article
    HAS_AFFILIATE = True
except ImportError:
    HAS_AFFILIATE = False

# ステマ規制対応
PR_DISCLOSURE = '''
<div class="kpj-disclosure" style="background:#fff5f7;border-radius:8px;padding:12px;margin:30px 0 20px;font-size:12px;color:#666;border-left:3px solid #FF4E6B">
※当サイトはアフィリエイトプログラムに参加しており、リンク経由の商品購入により当サイトに収益が発生する場合があります。
</div>
'''

# --- 既存 static CTA (Phase <14 互換) ---
CTA_TOP = """<div data-cta="top" class="kpopj-cta-top" style="margin:20px 0;padding:14px 16px;border-left:4px solid #ff4d6d;background:#fff5f7;border-radius:0 8px 8px 0;">
<p style="margin:0;font-size:0.95em;"><strong>最新の推し活ニュースを毎日チェック</strong> → <a href="https://www.kpopjournal.tokyo/category/kpop%e3%83%8b%e3%83%a5%e3%83%bc%e3%82%b9/" style="color:#ff4d6d;font-weight:700;">K-POP速報カテゴリ</a></p>
</div>"""

CTA_MID = """<div data-cta="mid" class="kpopj-cta-mid" style="margin:28px 0;padding:16px 18px;border:2px solid #7b61ff;background:#faf9ff;border-radius:10px;">
<p style="margin:0 0 6px 0;font-weight:700;color:#7b61ff;">配信・ライブ視聴はABEMAが最速</p>
<p style="margin:0;font-size:0.92em;">K-POPのMVプレミア公開・カムバショー・音楽番組を日本からリアルタイムで視聴 → <a href="https://abema.tv/" rel="sponsored nofollow">ABEMA公式で見る</a></p>
</div>"""

CTA_BOTTOM = """<div data-cta="bottom" class="kpopj-cta-bottom" style="margin:36px 0 10px 0;padding:18px 20px;border:2px dashed #ff4d6d;background:#fff8f9;border-radius:12px;text-align:center;">
<p style="margin:0 0 8px 0;font-weight:700;font-size:1.05em;">この記事が役立ったら保存してください</p>
<p style="margin:0;font-size:0.92em;"><a href="https://www.kpopjournal.tokyo/">K-POP JOURNAL トップへ戻る</a> &nbsp;/&nbsp; <a href="https://www.kpopjournal.tokyo/kpop-beginner-hub-2026/">K-POP初心者ガイド</a></p>
</div>"""


# --- アフィリCTA HTML生成 ---

def _get_icon(meta):
    cats = meta.get('categories', [])
    if 'vod' in cats: return '&#127916;'
    if 'korean_language' in cats: return '&#128483;'
    if 'korean_cosme' in cats or 'skincare' in cats: return '&#129524;'
    if 'beauty_device' in cats: return '&#128134;'
    if 'color_contact' in cats: return '&#128065;'
    if 'korean_fashion' in cats or 'sportswear' in cats: return '&#128087;'
    if 'kpop_goods' in cats or 'accessory' in cats: return '&#10024;'
    if 'shopping_mall' in cats: return '&#128722;'
    if 'travel_korea' in cats: return '&#127472;&#127479;'
    if 'travel_domestic' in cats or 'hotel' in cats: return '&#127976;'
    if 'travel' in cats or 'esim' in cats or 'wifi' in cats: return '&#9992;'
    if 'anime_goods' in cats: return '&#127873;'
    return '&#11088;'


def _get_desc(meta):
    best_for = meta.get('best_for', [])
    if best_for:
        return f"こんな方におすすめ: {best_for[0]}"
    return meta.get('advertiser', '')


def generate_cta_block(programs_keys, article_title=''):
    """指定された案件リストからCTAブロックHTML生成"""
    if not programs_keys or not HAS_AFFILIATE:
        return ''

    items_html = []
    for prog_key in programs_keys[:3]:
        meta = get_program_metadata(prog_key)
        if not meta:
            continue

        link_html = build_a8_link_with_html(prog_key, f"▶ {meta['name']}")
        if not link_html:
            continue

        # 2026-05-11: link_html を <p class="kpj-cta-link"> で明示的に包む。
        # 包まないと wpautop が <a>...</a>\n<img/> を自動<p>化する際に
        # </p> 閉じが落ちて pre_publish_gate (open=N close=N-3) で BLOCK される事故が頻発。
        items_html.append(f'''<div class="kpj-cta-item">
  <div class="kpj-cta-icon">{_get_icon(meta)}</div>
  <div class="kpj-cta-content">
    <div class="kpj-cta-title">{meta['name']}</div>
    <div class="kpj-cta-desc">{_get_desc(meta)}</div>
    <p class="kpj-cta-link">{link_html}</p>
  </div>
</div>''')

    if not items_html:
        return ''

    block = f'''
<div class="kpj-cta-block">
  <h3 class="kpj-cta-heading">関連おすすめ</h3>
  <div class="kpj-cta-grid">
    {"".join(items_html)}
  </div>
</div>
'''
    # 2026-05-11: A8素材HTMLが <p>未閉じを含むため BeautifulSoupで正規化
    # (24h記事14件すべてで unclosed_p 検出されたバグの根本対策)
    try:
        from bs4 import BeautifulSoup
        block = str(BeautifulSoup(block, 'html.parser'))
    except Exception:
        pass
    return block


def inject_cta_into_content(title, content, force_genre=None):
    """記事本文に最適なアフィリCTAブロックを挿入 (Phase 14)"""
    if not HAS_AFFILIATE:
        return content

    # 既にアフィリCTAブロック挿入済みなら何もしない
    if 'kpj-cta-block' in content or 'class="kpj-cta-' in content:
        return content

    # 短すぎる記事はスキップ
    plain = re.sub(r'<[^>]+>', '', content)
    if len(plain) < 400:
        return content

    # ジャンル判定
    cta_info = get_cta_programs_for_article(title, content)
    if not cta_info['programs']:
        return content

    cta_block = generate_cta_block(cta_info['programs'], title)
    if not cta_block:
        return content

    # 挿入位置: 2つ目のh2の直前、なければ1つ目のh2後の段落後、なければ中間
    h2_matches = list(re.finditer(r'</h2>\s*(<p[^>]*>.*?</p>\s*){2,}', content, re.DOTALL))

    if len(h2_matches) >= 2:
        insert_pos = h2_matches[1].start()
        new_content = content[:insert_pos] + cta_block + content[insert_pos:]
    elif h2_matches:
        insert_pos = h2_matches[0].end()
        new_content = content[:insert_pos] + cta_block + content[insert_pos:]
    else:
        paragraphs = content.split('</p>')
        if len(paragraphs) >= 4:
            mid = len(paragraphs) // 2
            paragraphs[mid] += '</p>' + cta_block
            new_content = '</p>'.join(paragraphs).replace('</p></p>', '</p>')
        else:
            new_content = content + cta_block

    # PR表記を末尾に追加
    if 'kpj-disclosure' not in new_content:
        new_content = new_content + PR_DISCLOSURE

    return new_content


# --- 既存 static CTA 挿入 ---

def curl_get(path: str):
    cmd = ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH]
    return json.loads(subprocess.check_output(cmd, timeout=30).decode())


def curl_post(path: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def has_cta(content: str, slot: str) -> bool:
    return f'data-cta="{slot}"' in content


def insert_top(content: str) -> str:
    m = re.search(r"<h2\b", content)
    if not m:
        return CTA_TOP + content
    i = m.start()
    return content[:i] + CTA_TOP + "\n" + content[i:]


def insert_mid(content: str) -> str:
    ps = [m.start() for m in re.finditer(r"</p>", content)]
    if not ps:
        return content + "\n" + CTA_MID
    mid = ps[len(ps) // 2]
    insert_at = mid + 4
    return content[:insert_at] + "\n" + CTA_MID + content[insert_at:]


def insert_bottom(content: str) -> str:
    return content.rstrip() + "\n" + CTA_BOTTOM


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # WP REST の per_page 上限は 100。超えるとJSONでなくエラーを返し処理が落ちるためクランプ。
    per_page = min(max(args.limit, 1), 100)

    posts = curl_get(
        f"/wp-json/wp/v2/posts?per_page={per_page}&orderby=date&order=desc"
        "&_fields=id,title,slug,link,categories,content"
    )
    ts = datetime.now(tz=JST).isoformat()
    top_added = mid_added = bot_added = aff_added = 0
    posts_updated = 0
    failed = 0

    with OUT_LOG.open("a") as fp:
        for p in posts:
            try:
                content = p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")
                title_text = p.get("title", {}).get("rendered", "") if isinstance(p.get("title"), dict) else ""
                updates = []
                new_content = content

                # Phase 14: アフィリCTA挿入
                if HAS_AFFILIATE and 'kpj-cta-block' not in new_content:
                    injected = inject_cta_into_content(title_text, new_content)
                    if injected != new_content:
                        new_content = injected
                        updates.append("affiliate_cta")
                        aff_added += 1

                # 既存 static CTA
                if not has_cta(new_content, "top"):
                    new_content = insert_top(new_content); updates.append("top"); top_added += 1
                if not has_cta(new_content, "mid"):
                    new_content = insert_mid(new_content); updates.append("mid"); mid_added += 1
                if not has_cta(new_content, "bottom"):
                    new_content = insert_bottom(new_content); updates.append("bottom"); bot_added += 1

                if not updates:
                    continue
                if args.dry_run:
                    posts_updated += 1
                    print(f"  [dry] [{p['id']}] would add: {updates}")
                    continue
                curl_post(f"/wp-json/wp/v2/posts/{p['id']}", {"content": new_content})
                posts_updated += 1
                fp.write(json.dumps({
                    "ts": ts, "post_id": p["id"], "slug": p["slug"],
                    "added": updates,
                }, ensure_ascii=False) + "\n")
                print(f"  OK [{p['id']}] +CTA: {updates}")
            except Exception as e:
                failed += 1
                print(f"  NG [{p['id']}] {e}")

    print()
    print(f"[cta_injector] 更新記事={posts_updated} / top+={top_added} mid+={mid_added} "
          f"bot+={bot_added} aff+={aff_added} / failed={failed}")
    print(f"  ログ: {OUT_LOG}")


if __name__ == "__main__":
    main()
