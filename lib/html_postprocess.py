#!/usr/bin/env python3
"""
html_postprocess.py — UI/UX後処理保証スクリプト
kpop_strategy_pipeline.sh の final_post.md 生成後に実行する。
LLMが指示を一部守らなくても最低限の構造を補正する。

保証項目:
  1. conclusion-lead (冒頭結論1行)
  2. rehook (中盤再フック文)
  3. related-mid (本文中盤の関連記事)
  4. 末尾関連記事ブロック
  5. 中盤CTA (revenue-cta)
  6. 段落長の分割 (句点ベース)
  7. 冒頭付近の数字・記録語への <strong> 最低保証
  8. 主要 <h2> 前の section-hook (2箇所以上)
  9. 画像→説明文の順序保証
 10. SEO構造化データ自動挿入 (Article/FAQ/Breadcrumb JSON-LD)
"""

import re
import sys
from pathlib import Path

try:
    from lib.seo_structured_data import inject_structured_data, guess_category_from_title
except ImportError:
    # lib/ が sys.path にある時のフォールバック
    from seo_structured_data import inject_structured_data, guess_category_from_title

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
REHOOK_TEXT = "ここまで読んでくれたあなたへ——本当に大事な話はここから。"
RELATED_MID_HTML = """<div class="related-mid" style="border-left:4px solid #ff4d6d;padding:12px 16px;margin:24px 0;background:#fff5f7;">
<p style="font-weight:bold;margin:0 0 8px;">📌 あわせて読みたい</p>
<ul style="margin:0;padding-left:20px;line-height:2.2;">
<li><a href="https://www.kpopjournal.tokyo/kpop-chart-weekly/">K-POPチャート週間ランキング</a></li>
<li><a href="https://www.kpopjournal.tokyo/kpop-comeback-schedule-2026/">K-POPカムバックスケジュール</a></li>
<li><a href="https://www.kpopjournal.tokyo/kpop-events-japan-2025-list/">K-POPライブ・イベントまとめ</a></li>
</ul>
</div>"""
RELATED_FOOTER_HTML = """<div class="related-footer" style="border:2px solid #ff4d6d;padding:20px;margin:32px 0;border-radius:8px;">
<p style="font-weight:bold;margin:0 0 12px;">📌 関連記事</p>
<ul style="margin:0;padding-left:20px;line-height:2.2;">
<li><a href="https://www.kpopjournal.tokyo/kpop-chart-weekly/">K-POPチャート週間ランキング</a></li>
<li><a href="https://www.kpopjournal.tokyo/kpop-comeback-schedule-2026/">K-POPカムバックスケジュール2026</a></li>
<li><a href="https://www.kpopjournal.tokyo/kpop-events-japan-2025-list/">K-POPライブ・イベントまとめ</a></li>
</ul>
</div>"""
CTA_MID_HTML = """<div class="revenue-cta cta-internal" style="border:2px solid #ff4d6d;padding:20px;margin:32px 0;border-radius:12px;background:#fff5f7;">
<p style="font-size:1.1em;font-weight:bold;margin:0 0 12px;">📌 あわせて読みたい</p>
<ul style="margin:0;padding-left:20px;line-height:2.2;">
<li><a href="https://www.kpopjournal.tokyo/kpop-chart-weekly/" style="color:#ff4d6d;font-weight:bold;">K-POPチャート週間ランキング</a></li>
</ul>
</div>"""

# 冒頭付近で強調する記録語パターン（数字前後に出現するもの）
RECORD_PATTERNS = [
    r'(\d+(?:,\d+)?(?:\.\d+)?)\s*(位|冠|週連続|週連|枚|万枚|億回|万回)',
    r'(初週|史上初|歴代最多|歴代最高|過去最多|過去最高)',
]

# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def split_title_body(text: str):
    """1行目=タイトル、2行目以降=本文として分割"""
    lines = text.splitlines(keepends=True)
    if not lines:
        return "", ""
    title = lines[0].rstrip("\n")
    body = "".join(lines[1:])
    return title, body


def find_h2_positions(body: str) -> list[int]:
    """<h2>タグの開始位置リストを返す"""
    return [m.start() for m in re.finditer(r'<h2[^>]*>', body)]


def insert_after_nth_h2_end(body: str, n: int, html: str) -> str:
    """n番目(0-indexed)の</h2>の後にhtmlを挿入する"""
    matches = list(re.finditer(r'</h2>', body))
    if len(matches) <= n:
        return body
    pos = matches[n].end()
    return body[:pos] + "\n" + html + body[pos:]


def get_midpoint_h2_index(body: str) -> int:
    """中盤に最も近い<h2>のインデックスを返す（全体の40〜60%付近）"""
    h2_positions = find_h2_positions(body)
    if not h2_positions:
        return -1
    mid = len(body) // 2
    best = min(range(len(h2_positions)), key=lambda i: abs(h2_positions[i] - mid))
    # 先頭と末尾は避ける
    if best == 0 and len(h2_positions) > 1:
        best = 1
    if best == len(h2_positions) - 1 and len(h2_positions) > 2:
        best = len(h2_positions) - 2
    return best


# ─────────────────────────────────────────────
# 各補正処理
# ─────────────────────────────────────────────

def ensure_conclusion_lead(body: str, title: str) -> tuple[str, bool]:
    """
    article-type ラベルの直後に conclusion-lead がなければ自動挿入。
    冒頭100文字以内の数字/記録語から要約を生成する。
    """
    if 'class="conclusion-lead"' in body or "conclusion-lead" in body:
        return body, False

    # 冒頭テキストから数字・記録語を抽出して結論文を組み立てる
    plain_head = re.sub(r'<[^>]+>', '', body[:400])
    conclusion = ""
    for pat in RECORD_PATTERNS:
        m = re.search(pat, plain_head)
        if m:
            conclusion = f"結論：{title}——{m.group(0)}の記録とその背景を、この記事で全て解説する。"
            break
    if not conclusion:
        conclusion = f"結論：{title}——この記事で全て解説する。"

    lead = f'<p class="conclusion-lead"><strong>{conclusion}</strong></p>\n'

    # article-type の直後に挿入
    m = re.search(r'(<p[^>]*class="article-type[^"]*"[^>]*>.*?</p>)', body, re.DOTALL)
    if m:
        pos = m.end()
        body = body[:pos] + "\n" + lead + body[pos:]
    else:
        # article-type がなければ先頭に挿入
        body = lead + body
    return body, True


def ensure_rehook(body: str) -> tuple[str, bool]:
    """中盤に rehook が無ければ自動挿入"""
    if 'class="rehook"' in body or "rehook" in body:
        return body, False

    rehook_html = f'<p class="rehook"><strong>{REHOOK_TEXT}</strong></p>\n'
    mid_idx = get_midpoint_h2_index(body)
    if mid_idx < 0:
        # h2がない場合は本文の中間付近に挿入
        mid = len(body) // 2
        body = body[:mid] + "\n" + rehook_html + body[mid:]
    else:
        body = insert_after_nth_h2_end(body, mid_idx, rehook_html)
    return body, True


def ensure_related_mid(body: str) -> tuple[str, bool]:
    """本文中盤の related-mid が無ければ自動挿入"""
    if 'class="related-mid"' in body or "related-mid" in body:
        return body, False

    mid_idx = get_midpoint_h2_index(body)
    if mid_idx < 0:
        return body, False
    body = insert_after_nth_h2_end(body, mid_idx, RELATED_MID_HTML)
    return body, True


def ensure_related_footer(body: str) -> tuple[str, bool]:
    """末尾関連記事ブロックが無ければ自動挿入"""
    if 'class="related-footer"' in body or "related-footer" in body:
        return body, False
    # 既存の「関連記事」h2があればスキップ
    if re.search(r'<h2[^>]*>関連記事', body):
        return body, False
    body = body.rstrip() + "\n" + RELATED_FOOTER_HTML + "\n"
    return body, True


def ensure_cta_mid(body: str) -> tuple[str, bool]:
    """中盤にCTAが無ければ自動挿入（既存CTAがあればスキップ）"""
    # 既存CTAが2箇所以上あればスキップ
    cta_count = len(re.findall(r'revenue-cta', body))
    if cta_count >= 2:
        return body, False

    # 1箇所のみなら中盤に追加
    mid_idx = get_midpoint_h2_index(body)
    if mid_idx < 0:
        return body, False
    # related-mid の直後に挿入しないよう前のh2を使う
    insert_idx = max(0, mid_idx - 1)
    body = insert_after_nth_h2_end(body, insert_idx, CTA_MID_HTML)
    return body, True


def split_long_paragraphs(body: str) -> tuple[str, int]:
    """
    <p>〜</p> が長すぎる場合、句点（。）で2〜3分割する。
    クラス付きp（conclusion-lead, rehook等）は触らない。
    60文字×3行≒180文字を目安とする。
    """
    MAX_LEN = 200  # これ以上なら分割対象
    MIN_SPLIT_LEN = 60  # 分割後の最小長
    count = 0

    def split_p(m):
        nonlocal count
        tag_open = m.group(1)   # <p...>
        content = m.group(2)    # 中身テキスト
        tag_close = m.group(3)  # </p>

        # クラス付きpは触らない
        if re.search(r'class=', tag_open):
            return m.group(0)

        plain = re.sub(r'<[^>]+>', '', content)
        if len(plain) <= MAX_LEN:
            return m.group(0)

        # 句点で分割
        sentences = re.split(r'(?<=。)', content)
        if len(sentences) < 2:
            return m.group(0)

        # 60文字以上になるようにグループ化
        groups = []
        current = ""
        for s in sentences:
            if len(re.sub(r'<[^>]+>', '', current + s)) > MAX_LEN and current:
                groups.append(current)
                current = s
            else:
                current += s
        if current:
            groups.append(current)

        if len(groups) < 2:
            return m.group(0)

        count += len(groups) - 1
        return "\n".join(f"{tag_open}{g}{tag_close}" for g in groups if g.strip())

    result = re.sub(
        r'(<p(?:\s[^>]*)?>)(.*?)(</p>)',
        split_p,
        body,
        flags=re.DOTALL
    )
    return result, count


def add_strong_to_records(body: str) -> tuple[str, int]:
    """
    本文の先頭1/3部分のみを対象に、未強調の数字+記録語に<strong>を付与する。
    既に<strong>内にある場合はスキップ。強調しすぎを防ぐため最大3箇所。
    """
    boundary = len(body) // 3
    head = body[:boundary]
    tail = body[boundary:]

    count = 0
    MAX_STRONG = 3

    def wrap_strong(m):
        nonlocal count
        if count >= MAX_STRONG:
            return m.group(0)
        # 既に<strong>の中にあるかチェック（簡易）
        start = m.start()
        preceding = head[:start]
        open_count = preceding.count('<strong>') + preceding.count('<strong ')
        close_count = preceding.count('</strong>')
        if open_count > close_count:
            return m.group(0)
        count += 1
        return f'<strong>{m.group(0)}</strong>'

    for pat in RECORD_PATTERNS:
        if count >= MAX_STRONG:
            break
        # <h2>〜</h2> 内は触らない
        def safe_sub(m):
            s = m.start()
            preceding = head[:s]
            # h2内かどうか判定
            h2_opens = preceding.count('<h2') - preceding.count('</h2>')
            if h2_opens > 0:
                return m.group(0)
            return wrap_strong(m)
        head = re.sub(pat, safe_sub, head)

    return head + tail, count


def ensure_section_hooks(body: str) -> tuple[str, int]:
    """
    <h2>の前に section-hook が無い場合、主要h2(2〜3箇所)に短いフック文を追加する。
    既に section-hook が2箇所以上あればスキップ。
    """
    existing = len(re.findall(r'section-hook', body))
    if existing >= 2:
        return body, 0

    needed = 2 - existing
    h2_matches = list(re.finditer(r'<h2[^>]*>', body))
    if not h2_matches:
        return body, 0

    # 中盤付近のh2を優先（先頭と末尾を避ける）
    candidates = h2_matches[1:-1] if len(h2_matches) > 2 else h2_matches
    if not candidates:
        candidates = h2_matches

    # hookテキストのバリエーション
    hook_texts = [
        "ここが一番重要なポイントです。",
        "実は、ここからが本題です。",
    ]

    added = 0
    offset = 0
    for i, m in enumerate(candidates[:needed]):
        # 直前に既にsection-hookがあればスキップ
        pre = body[max(0, m.start() + offset - 100):m.start() + offset]
        if 'section-hook' in pre:
            continue
        hook_html = f'<p class="section-hook">{hook_texts[i % len(hook_texts)]}</p>\n'
        pos = m.start() + offset
        body = body[:pos] + hook_html + body[pos:]
        offset += len(hook_html)
        added += 1

    return body, added


def ensure_image_before_text(body: str) -> tuple[str, bool]:
    """
    <figure>や<img>の直後に<p>が来ていなければ何もしない。
    <p>が<figure>/<img>より先に来ている場合は入れ替える（簡易版）。
    画像が存在しない記事では何もしない。
    """
    if not re.search(r'<(figure|img)', body):
        return body, False

    # <p>...</p> が <figure>...</figure> より前にある最初のケースを検出
    p_match = re.search(r'(<p[^>]*>.*?</p>)\s*(<figure[^>]*>.*?</figure>)', body, re.DOTALL)
    if not p_match:
        return body, False

    p_block = p_match.group(1)
    fig_block = p_match.group(2)
    # 入れ替え（figureを先、pを後に）
    body = body[:p_match.start()] + fig_block + "\n" + p_block + body[p_match.end():]
    return body, True


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: html_postprocess.py <file>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"  ⚠️ html_postprocess: {path} が存在しない → スキップ", file=sys.stderr)
        sys.exit(0)

    text = path.read_text(encoding="utf-8")
    title, body = split_title_body(text)

    log = []

    # 1. conclusion-lead
    body, changed = ensure_conclusion_lead(body, title)
    if changed:
        log.append("✅ conclusion-lead 自動挿入")

    # 2. rehook
    body, changed = ensure_rehook(body)
    if changed:
        log.append("✅ rehook 自動挿入")

    # 3. related-mid
    body, changed = ensure_related_mid(body)
    if changed:
        log.append("✅ related-mid 自動挿入")

    # 4. 末尾関連記事
    body, changed = ensure_related_footer(body)
    if changed:
        log.append("✅ related-footer 自動挿入")

    # 5. 中盤CTA
    body, changed = ensure_cta_mid(body)
    if changed:
        log.append("✅ CTA中盤 自動挿入")

    # 6. 段落分割
    body, n = split_long_paragraphs(body)
    if n > 0:
        log.append(f"✅ 長段落を {n} 箇所分割")

    # 7. strong強調（冒頭1/3のみ）
    body, n = add_strong_to_records(body)
    if n > 0:
        log.append(f"✅ 記録語 {n} 箇所に <strong> 付与")

    # 8. section-hook
    body, n = ensure_section_hooks(body)
    if n > 0:
        log.append(f"✅ section-hook {n} 箇所追加")

    # 9. 画像先行配置
    body, changed = ensure_image_before_text(body)
    if changed:
        log.append("✅ 画像→テキスト順序を補正")

    # 10. SEO構造化データ自動挿入 (Article/FAQ/BreadcrumbList JSON-LD)
    cat_name, cat_slug = guess_category_from_title(title)
    body, seo_log = inject_structured_data(
        body=body,
        title=title,
        category_name=cat_name,
        category_slug=cat_slug,
    )
    log.extend(f"  [SEO] {m}" for m in seo_log)

    # 書き戻し
    path.write_text(title + "\n" + body, encoding="utf-8")

    if log:
        for line in log:
            print(f"  [html_postprocess] {line}")
    else:
        print("  [html_postprocess] 補正なし（すべて既に満たされている）")


if __name__ == "__main__":
    main()
