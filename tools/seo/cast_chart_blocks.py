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
    # post 1317 = kpop-demon-hunters-cast-characters
    # 28d clk419/CTR8.40% と既に好調だが「デーモンハンターズ キャラクター」だけ pos7.9/CTR3.62%。
    # pos7-10帯平均1.81%の2倍なので記事固有の問題ではなく純粋に順位の問題。FAQPage は既にある。
    # 本文に「登場キャラクター一覧と相関図」H2 があり「まずは関係性(相関図)を**言葉で**押さえましょう」
    # と書かれている = 図が0枚。「デーモンハンターズ 相関図」は pos1.2/CTR37.6% と最強クエリなので
    # 図の実体を与えて強化する(鉄槌教師 9189 と同じ打ち手)。
    # 内容は本文の三層構造の記述と、メンバー表(声優・歌唱担当)に厳密一致。
    1317: {
        "layout": "factions",
        "title": "『K-POPデーモンハンターズ』キャラクター相関図",
        "org": "HUNTR/X(正義) ─ 対立 ─ Saja Boys(悪魔) ← 操る ← グィマ(王) の三層構造",
        "factions": [
            {
                "label": "◆ HUNTR/X(ハントリックス) — 主人公の女性3人組。人気アイドルでありながら悪魔ハンター",
                "lead": True,
                "arrow": "↕ 対立 — その中心に ルミ ⇔ ジヌ の関係が置かれている",
                "nodes": [
                    {"tag": "リーダー / メインボーカル", "role": "ルミ(Rumi)", "head": True,
                     "actor": "アーデン・チョー / 歌唱: EJAE",
                     "desc": "HUNTR/Xのリーダー。ジヌとは敵同士でありながら惹かれ合う、本作の感情の中心"},
                    {"tag": "メインダンサー", "role": "ミラ(Mira)",
                     "actor": "メイ・ホン / 歌唱: Audrey Nuna", "desc": "HUNTR/Xのメインダンサー"},
                    {"tag": "ラッパー / 作詞 / マンネ", "role": "ゾーイ(Zoey)",
                     "actor": "ジヨン・ユー / 歌唱: Rei Ami", "desc": "ラップと作詞を担当する末っ子"},
                ],
            },
            {
                "label": "◆ Saja Boys(サジャボーイズ) — 人間に化けた悪魔の男性5人組。悪魔の王の命令でHUNTR/Xのファンを奪いに来る",
                "rival": True,
                "arrow": "↑ 操る",
                "nodes": [
                    {"tag": "リーダー", "role": "ジヌ(Jinu)", "head": True,
                     "actor": "アン・ヒョソプ / 歌唱: Andrew Choi",
                     "desc": "Saja Boysのリーダー。ルミと惹かれ合う"},
                    {"tag": "メンバー", "role": "ロマンス・サジャ",
                     "actor": "ジョエル・キム・ブースター / 歌唱: Samuil Lee", "desc": "Saja Boysのメンバー"},
                    {"tag": "メンバー", "role": "ミステリー・サジャ",
                     "actor": "アラン・リー / 歌唱: Kevin Woo", "desc": "Saja Boysのメンバー"},
                    {"tag": "メンバー", "role": "アビー・サジャ",
                     "actor": "ソンウォン・チョー / 歌唱: Neckwav", "desc": "Saja Boysのメンバー"},
                    {"tag": "メンバー", "role": "ベイビー・サジャ",
                     "actor": "ダニー・チョン", "desc": "Saja Boysのメンバー"},
                ],
            },
            {
                "label": "◆ 黒幕",
                "boss": True,
                "nodes": [
                    {"tag": "悪魔の王 / 黒幕", "role": "グィマ(Gwi-Ma)", "head": True,
                     "actor": "—", "desc": "サジャボーイズを操る悪魔の王。物語全体の黒幕"},
                ],
            },
        ],
        "bond": "ルミ ⇔ ジヌ — HUNTR/Xのリーダーとサジャボーイズのリーダー。"
                "敵同士でありながら惹かれ合う、本作の感情の中心",
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
    ".is-boss{border:2px solid #2c3e50;background:#f4f6f8}"
    ".is-boss .kpj-tag{background:#2c3e50;color:#fff}"
    ".kpj-tag{display:inline-block;font-size:11px;background:#eef1f5;color:#444;border-radius:3px;"
    "padding:1px 7px;margin-bottom:5px}"
    ".is-lead .kpj-tag{background:#c0392b;color:#fff}.is-rival .kpj-tag{background:#8e44ad;color:#fff}"
    ".kpj-role{font-weight:700;font-size:15px;display:block}"
    ".kpj-actor{font-size:12.5px;color:#555;display:block;margin-bottom:5px}"
    ".kpj-desc{font-size:12.5px;color:#333;margin:0}"
    ".kpj-arrow{text-align:center;color:#888;font-size:12px;margin:9px 0}"
    ".kpj-bond{border-left:3px solid #c0392b;background:#fff5f4;padding:9px 12px;margin:16px auto 0;"
    "max-width:560px;font-size:12.5px;border-radius:0 5px 5px 0}"
    ".kpj-faction{text-align:center;font-weight:700;font-size:13px;color:#444;margin:14px 0 7px}"
    "@media(max-width:600px){.kpj-node{max-width:100%;flex:1 1 100%}}"
    "</style>"
)


def esc(s):
    return html.escape(s, quote=True)


def node_html(n, cls=""):
    # actor が "—"(本文に記載なし)のときは「演:」行ごと出さない。
    # 空の「演: —」は図の情報として無意味で、むしろ欠落に見える。
    actor = n.get("actor", "").strip()
    actor_html = (f'<span class="kpj-actor">演: {esc(actor)}</span>'
                  if actor and actor != "—" else "")
    return (
        f'<div class="kpj-node{cls}">'
        f'<span class="kpj-tag">{esc(n["tag"])}</span>'
        f'<span class="kpj-role">{esc(n["role"])}</span>'
        f'{actor_html}'
        f'<p class="kpj-desc">{esc(n["desc"])}</p>'
        f"</div>"
    )


def build_hierarchy(c):
    """階層型(組織トップ → 中心 → 現場/情報 → 対立)。作品: 鉄槌教師。"""
    by = {n["key"]: n for n in c["nodes"]}
    return "\n".join([
        CSS,
        '<figure class="kpj-chart">',
        f'<h4>{esc(c["title"])}</h4>',
        f'<div class="kpj-org">中心となる組織: {esc(c["org"])}</div>',
        '<div class="kpj-row">' + node_html(by["boss"]) + "</div>",
        '<div class="kpj-arrow">↓ 組織を創設し、監督官を現場へ送り出す</div>',
        '<div class="kpj-row">' + node_html(by["lead"], " is-lead") + "</div>",
        '<div class="kpj-arrow">↓ 現場で組む &nbsp;/&nbsp; ↘ 情報・技術で支える</div>',
        '<div class="kpj-row">' + node_html(by["partner"]) + node_html(by["brain"]) + "</div>",
        '<div class="kpj-arrow">↕ 真っ向から対立</div>',
        '<div class="kpj-row">' + node_html(c["rival"], " is-rival") + "</div>",
        f'<figcaption class="kpj-bond"><strong>相関図の鍵:</strong> '
        f'チェ・ガンソク × ナ・ファジン — {esc(c["bond"])}</figcaption>',
        "</figure>",
    ])


def build_factions(c):
    """陣営対立型(陣営A ─対立─ 陣営B ← 操る ← 黒幕)。作品: K-POPデーモンハンターズ。

    本文の「HUNTR/X(正義) ─ 対立 ─ Saja Boys(悪魔) ← 操る ← グィマ(王)」という
    三層構造の記述をそのまま図にする。
    """
    parts = [
        CSS,
        '<figure class="kpj-chart">',
        f'<h4>{esc(c["title"])}</h4>',
        f'<div class="kpj-org">{esc(c["org"])}</div>',
    ]
    for fac in c["factions"]:
        parts.append(f'<div class="kpj-faction">{esc(fac["label"])}</div>')
        cls = (" is-lead" if fac.get("lead")
               else " is-rival" if fac.get("rival")
               else " is-boss" if fac.get("boss") else "")
        parts.append('<div class="kpj-row">'
                     + "".join(node_html(n, cls if n.get("head") else "") for n in fac["nodes"])
                     + "</div>")
        if fac.get("arrow"):
            parts.append(f'<div class="kpj-arrow">{esc(fac["arrow"])}</div>')
    parts.append(f'<figcaption class="kpj-bond"><strong>相関図の鍵:</strong> {esc(c["bond"])}</figcaption>')
    parts.append("</figure>")
    return "\n".join(parts)


def build(c):
    return build_factions(c) if c.get("layout") == "factions" else build_hierarchy(c)


NOTE = ("<!-- cast chart: 相関図の可視ブロック(HTML+CSS)。図が無いことがCTR低迷の真因だったため追加。"
        "内容は本文記述に厳密一致(ハルシネ防止)。挿入位置: 「相関図とは」H2 の直後 -->")

def node_count(c):
    if c.get("layout") == "factions":
        return sum(len(f["nodes"]) for f in c["factions"])
    return len(c["nodes"]) + 1  # nodes + rival


if __name__ == "__main__":
    for pid, c in CHARTS.items():
        block = f"{NOTE}\n{build(c)}\n"
        path = OUT / f"post_{pid}_chart.html"
        path.write_text(block, encoding="utf-8")
        print(f"wrote {path} ({node_count(c)} nodes, {len(block)} bytes, "
              f"{c.get('layout','hierarchy')})")
    print("\n挿入位置: 「『鉄槌教師』の相関図とは — まず全体構造を押さえる」H2 の直後(図を最初に見せる)。")
    print("反映: tools/wp/safe_post_edit.sh apply <post_id> <new_body.html>")
