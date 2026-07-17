#!/usr/bin/env python3
"""相関図クエリ向け: 記事本文に埋め込む可視の相関図(HTML+CSS)を生成。

背景(2026-07-16 GSC実測):
  「鉄槌教師 相関図」は 28d imp1,111 / pos6.2 だが CTR0.90%。当サイトの pos5-7 帯平均は
  5.20% なので約6分の1に沈んでいる。意図不一致ではない(同じ相関図系の
  「デーモンハンターズ 相関図」は pos1.2/CTR37.6%、「bts 仲良し 相関 図 2026」は pos2.0/CTR37.8%)。
  真因は **相関図記事なのに図が1枚もない**(本文画像0枚)こと。「相関図」で検索する人は
  図を見たいのに、記事は全部テキストだった。

方針:
  - 画像でなく HTML+CSS で組む。著作権リスクゼロ / テキストなのでSEOにも効く /
    レスポンシブ対応 / 生成コストなし。俳優の顔写真は使わず、役名・俳優名・関係性で構成。
  - 図の内容は **記事本文の記述に厳密一致**させる(ハルシネ防止。lane_c_faq_blocks.py と同方針)。
  - 出力は reports/cast_chart_patches/post_<id>_chart.html。
    反映は tools/wp/safe_post_edit.sh apply <id> <body.html> 経由(バックアップ/検証/GSC申請つき)。

使い方:
  venv_kpi/bin/python3 tools/seo/cast_chart_blocks.py
"""
import html
import pathlib

OUT = pathlib.Path("reports/cast_chart_patches")
OUT.mkdir(parents=True, exist_ok=True)

# post 9189 = tettsui-kyoshi-cast-chart
# 各要素は記事本文の記述に一致させてある:
#   - 「教権保護局」という架空の政府機関が中心
#   - 〈チェ・ガンソク(組織) → ナ・ファジン&イム・ハンリム(現場) → ボン・グンデ(情報)〉
#   - ナ・ファジンが相関図の中心、チェ・ガンソクとは「2年前の生徒による教師殺害事件の遺族同士」
#   - チョ・ギュチョルはジンウォン高校の生徒で、チームと真っ向から対立する「物語の起点」
#   - ボン・グンデはドラマ版で追加されたオリジナルキャラ(演:ピョ・ジフン=Block BのP.O)
CHARTS = {
    9189: {
        "title": "『鉄槌教師』キャスト相関図",
        "org": "教権保護局(架空の政府機関)",
        "nodes": [
            {"key": "boss", "role": "チェ・ガンソク", "actor": "イ・ソンミン",
             "desc": "教育部長官。教権保護局を創設した組織のトップ", "tag": "組織"},
            {"key": "lead", "role": "ナ・ファジン", "actor": "キム・ムヨル",
             "desc": "最強監督官。相関図の中心。特戦司出身で現場に潜入し悪に一撃を下す",
             "tag": "現場・中心"},
            {"key": "partner", "role": "イム・ハンリム", "actor": "チン・ギジュ",
             "desc": "2人目の監督官。ナ・ファジンと組んで現場に立つ相棒", "tag": "現場"},
            {"key": "brain", "role": "ボン・グンデ", "actor": "ピョ・ジフン(P.O / Block B)",
             "desc": "情報収集・技術を担うブレイン。ドラマ版オリジナルキャラ", "tag": "情報・技術"},
        ],
        "rival": {"role": "チョ・ギュチョル", "actor": "イ・ボンジュン",
                  "desc": "ジンウォン高校の生徒。ある事件を起こし少年刑務所に収監。チームと対立する物語の起点",
                  "tag": "対立・物語の起点"},
        # 関係線(本文の記述に一致)
        "bond": "2年前の「生徒による教師殺害事件」の遺族同士 — 共通の喪失が二人を結ぶ",
    },
}

# CSS は圧縮して持つ。safe_post_edit の肥大ガード(追記後が1.5倍超で更新ブロック)は
# 「本文が意図せず膨らんでいないか」を見る安全装置で、緩めるべきではない。
# 一方この図は読者に届くテキストが390字(本文比1.08倍)で、バイト比1.51倍の正体はCSS。
# → ガードを緩めるのではなく CSS 側を削ってガード内に収める(ページ速度にも有利)。
CSS = (
    "<style>"
    ".kpj-chart{border:1px solid #e3e6ea;border-radius:10px;padding:20px 16px;margin:28px 0;"
    "background:#fafbfc;font-size:15px;line-height:1.6;color:#1a1a1a}"
    ".kpj-chart h4{margin:0 0 4px;font-size:17px;text-align:center}"
    ".kpj-org{text-align:center;font-size:13px;color:#666;margin-bottom:18px}"
    ".kpj-row{display:flex;justify-content:center;gap:14px;flex-wrap:wrap}"
    ".kpj-node{background:#fff;border:1px solid #c8ccd4;border-radius:8px;padding:11px 13px;"
    "max-width:230px;flex:1 1 190px}"
    ".is-lead{border:2px solid #c0392b}.is-rival{border:2px solid #8e44ad}"
    ".kpj-tag{display:inline-block;font-size:11px;background:#eef1f5;color:#444;border-radius:3px;"
    "padding:1px 7px;margin-bottom:5px}"
    ".is-lead .kpj-tag{background:#c0392b;color:#fff}.is-rival .kpj-tag{background:#8e44ad;color:#fff}"
    ".kpj-role{font-weight:700;font-size:15px;display:block}"
    ".kpj-actor{font-size:12.5px;color:#555;display:block;margin-bottom:5px}"
    ".kpj-desc{font-size:12.5px;color:#333;margin:0}"
    ".kpj-arrow{text-align:center;color:#888;font-size:12px;margin:9px 0}"
    ".kpj-bond{border-left:3px solid #c0392b;background:#fff5f4;padding:9px 12px;margin:16px auto 0;"
    "max-width:560px;font-size:12.5px;border-radius:0 5px 5px 0}"
    "@media(max-width:600px){.kpj-node{max-width:100%;flex:1 1 100%}}"
    "</style>"
)


def esc(s):
    return html.escape(s, quote=True)


def node_html(n, cls=""):
    return (
        f'<div class="kpj-node{cls}">'
        f'<span class="kpj-tag">{esc(n["tag"])}</span>'
        f'<span class="kpj-role">{esc(n["role"])}</span>'
        f'<span class="kpj-actor">演: {esc(n["actor"])}</span>'
        f'<p class="kpj-desc">{esc(n["desc"])}</p>'
        f"</div>"
    )


def build(c):
    by = {n["key"]: n for n in c["nodes"]}
    parts = [
        CSS,
        '<figure class="kpj-chart">',
        f'<h4>{esc(c["title"])}</h4>',
        f'<div class="kpj-org">中心となる組織: {esc(c["org"])}</div>',
        # 組織トップ
        '<div class="kpj-row">' + node_html(by["boss"]) + "</div>",
        '<div class="kpj-arrow">↓ 組織を創設し、監督官を現場へ送り出す</div>',
        # 中心
        '<div class="kpj-row">' + node_html(by["lead"], " is-lead") + "</div>",
        '<div class="kpj-arrow">↓ 現場で組む &nbsp;/&nbsp; ↘ 情報・技術で支える</div>',
        # 現場+情報
        '<div class="kpj-row">' + node_html(by["partner"]) + node_html(by["brain"]) + "</div>",
        '<div class="kpj-arrow">↕ 真っ向から対立</div>',
        # 対立
        '<div class="kpj-row">' + node_html(c["rival"], " is-rival") + "</div>",
        f'<figcaption class="kpj-bond"><strong>相関図の鍵:</strong> '
        f'チェ・ガンソク × ナ・ファジン — {esc(c["bond"])}</figcaption>',
        "</figure>",
    ]
    return "\n".join(parts)


NOTE = ("<!-- cast chart: 相関図の可視ブロック(HTML+CSS)。図が無いことがCTR低迷の真因だったため追加。"
        "内容は本文記述に厳密一致(ハルシネ防止)。挿入位置: 「相関図とは」H2 の直後 -->")

if __name__ == "__main__":
    for pid, c in CHARTS.items():
        block = f"{NOTE}\n{build(c)}\n"
        path = OUT / f"post_{pid}_chart.html"
        path.write_text(block, encoding="utf-8")
        print(f"wrote {path} ({len(c['nodes'])+1} nodes, {len(block)} bytes)")
    print("\n挿入位置: 「『鉄槌教師』の相関図とは — まず全体構造を押さえる」H2 の直後(図を最初に見せる)。")
    print("反映: tools/wp/safe_post_edit.sh apply <post_id> <new_body.html>")
