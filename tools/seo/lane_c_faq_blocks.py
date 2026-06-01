#!/usr/bin/env python3
"""Lane C 押し上げ: 対象3記事に挿入する FAQ(可視HTML + FAQPage JSON-LD)を生成。

各 FAQ の回答は対象記事の本文記述に厳密一致させてある(ハルシネ防止)。
出力は reports/lane_c_faq_patches/post_<id>.html に保存し、本番反映は
owner が /usr/local/sbin/kpop/kpop-wp-rw.sh で実施する(本文末尾「関連記事」直前に挿入)。
"""
import json, html, os, pathlib

OUT = pathlib.Path("reports/lane_c_faq_patches")
OUT.mkdir(parents=True, exist_ok=True)

# (post_id, [(question, answer), ...]) — answer は各記事本文の記述に一致
ARTICLES = {
    1317: [
        ("K-POPデーモンハンターズの登場キャラクターは何人ですか?",
         "主人公グループ「HUNTR/X(ハントリックス)」の3人と、敵対する「Saja Boys(サジャボーイズ)」の5人を中心に構成されています。"),
        ("HUNTR/X(ハントリックス)のメンバーの名前は?",
         "ルミ・ミラ・ゾーイの3人です。"),
        ("声優と歌手が異なるのはなぜですか?",
         "セリフを担当する声優と、楽曲を歌う歌唱担当が別々にキャスティングされているためです。本編では役の声と歌声で担当者が分かれています。"),
    ],
    1318: [
        ("OSAKA Ojo Gang のメンバーは何人ですか?",
         "7人です。それぞれが異なる担当ジャンルを持つ編成になっています。"),
        ("OSAKA Ojo Gang はスウパ3で優勝しましたか?",
         "はい。『WORLD OF STREET WOMAN FIGHTER(通称スウパ3)』で、日本代表チームとして見事に優勝しました。"),
        ("OSAKA Ojo Gang にはどんなメンバーがいますか?",
         "TWICE・MOMOの姉であるHANAをはじめ、ジャンルの異なるトップダンサーが集まったクルーです。各メンバーの名前・年齢・担当ジャンルは本文の一覧表で確認できます。"),
    ],
    1338: [
        ("劇中歌「Golden」を歌っているのは誰ですか?",
         "劇中ではHUNTR/X(ルミ・ミラ・ゾーイ)が歌う設定ですが、実際の歌唱を担当しているのはEJAE・Audrey Nuna・Rei Amiの3人です。"),
        ("「Golden」の作詞・作曲は誰ですか?",
         "EJAE と Mark Sonnenblick らが手がけています。"),
        ("EJAE(イジェ)とはどんな人ですか?",
         "「Golden」の歌唱と作詞作曲に関わったアーティストです。詳細は本文の解説セクションで紹介しています。"),
    ],
    # confidence-man-kr-guide。吹き替え声優は本文が「断定できない」としているため
    # FAQ も断定しない(ハルシネ防止)。配信情報は本文で確定しているので断定可。
    1319: [
        ("『コンフィデンスマンKR』はどこで配信されていますか?",
         "Amazon Prime Video の独占配信です。2025年9月6日から配信が始まり、全12話構成で、新エピソードが毎週順次追加されました。"),
        ("『コンフィデンスマンKR』に日本語吹き替えはありますか?声優は誰ですか?",
         "日本語吹き替えの有無や担当声優は配信時期・地域によって異なる場合があります。視聴の際に Prime Video の音声・字幕の言語設定で最新の対応をご確認ください。"),
        ("『コンフィデンスマンKR』は何話ありますか?原作は?",
         "全12話で、日本のドラマ「コンフィデンスマンJP」を原作とする韓国版リメイク作品です。"),
    ],
}

CSS_NOTE = ("<!-- Lane C push: FAQ block。可視FAQ + FAQPage JSON-LD。"
            "本文「関連記事」見出しの直前に挿入する。回答は本文記述に一致。 -->")


def visible_faq(qas):
    rows = []
    for q, a in qas:
        rows.append(
            f'<div class="kpop-faq-item">'
            f'<h3 class="kpop-faq-q">{html.escape(q)}</h3>'
            f'<p class="kpop-faq-a">{html.escape(a)}</p>'
            f'</div>'
        )
    return ('<section class="kpop-faq" aria-label="よくある質問">\n'
            '<h2>よくある質問(FAQ)</h2>\n' + "\n".join(rows) + "\n</section>")


def faq_jsonld(qas):
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in qas
        ],
    }
    return ('<script type="application/ld+json">\n'
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n</script>")


for pid, qas in ARTICLES.items():
    block = f"{CSS_NOTE}\n{visible_faq(qas)}\n{faq_jsonld(qas)}\n"
    path = OUT / f"post_{pid}_faq.html"
    path.write_text(block, encoding="utf-8")
    print(f"wrote {path} ({len(qas)} Q&A, {len(block)} bytes)")

print("\n挿入位置: 各記事の「関連記事 / あわせて読みたい」見出しの直前。")
print("反映: owner が kpop-wp-rw.sh post update <id> で本文に追記(直接渡し・stdin禁止)。")
