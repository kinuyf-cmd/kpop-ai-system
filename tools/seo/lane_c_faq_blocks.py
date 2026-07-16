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
    # mama-awards-2026-osaka-guide (post 4826)。「mama 2026 投票」クエリ獲得用(2026-06-17)。
    # 投票方法/開始時期は2026年6月時点で公式未発表のため断定しない(ハルシネ防止)。
    # 開催日程・会場(11/20-21 京セラドーム大阪)は公式確定(PRTIMES/Mnet)なので断定可。
    # 「例年は〜」の記述は本文の投票セクションの記述に一致させる。
    4826: [
        ("MAMA 2026の投票はいつから始まりますか?",
         "2026年6月時点で、2026 MAMA AWARDSの投票期間は公式に発表されていません。例年は授賞式本番(2026年は11月)の数週間前に投票期間が告知されます。発表があり次第このページを更新します。"),
        ("MAMA 2026の投票方法は?",
         "例年の投票は公式アプリ「Mnet Plus」を通じたファン投票が中心です。2026年の具体的な投票方法・対象部門は未発表のため、公式の告知をご確認ください。"),
        ("MAMAの投票は無料でできますか?",
         "例年はMnet Plusアプリ上で無料の投票が可能で、アプリ内のアクションを通じて投票数を増やせる仕組みでした。2026年の投票方式は未確定です。"),
        ("MAMAの受賞はファン投票だけで決まりますか?",
         "いいえ。例年はグローバルの音源・再生などのデータと、ファン投票を組み合わせて受賞者を決定しています。部門ごとに配分は異なります。"),
        ("MAMA 2026はいつ・どこで開催されますか?",
         "2026年11月20日(金)・21日(土)の2日間、京セラドーム大阪で開催されます。配信はMnet Plusなどで予定されています。"),
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
    # tettsui-kyoshi-cast-chart(post 9189)。「鉄槌教師 相関図」クエリ(pos6.6/CTR0.6%・
    # 直近7d +459imp 急上昇)獲得用(2026-07-07)。回答は本文の相関図記述に厳密一致(ハルシネ防止)。
    9189: [
        ("『鉄槌教師』の相関図はどういう構造になっていますか?",
         "「教権保護局」という架空の政府機関を中心に、〈組織 → 現場 → 情報〉という縦のチームで組み立てられています。教育部長官チェ・ガンソクが組織を作り、監督官ナ・ファジンとイム・ハンリムが現場で実行し、ボン・グンデが情報・技術で支える関係です。"),
        ("『鉄槌教師』の相関図の中心人物は誰ですか?",
         "監督官ナ・ファジン(演:キム・ムヨル)です。教権保護局の最強監督官で、相関図のすべての関係線がこの人物から伸びていく物語の起点です。組織を創設した教育部長官チェ・ガンソク(演:イ・ソンミン)とは、単なる上司と部下を超えた絆で結ばれています。"),
        ("『鉄槌教師』のチョ・ギュチョルとはどんな人物ですか?",
         "チョ・ギュチョル(演:イ・ボンジュン)は、ジンウォン高校に通う生徒で、ある衝撃的な事件を起こして少年刑務所に収監されている人物です。この事件こそが教権保護局が創設される直接のきっかけとなり、相関図の上ではチームと真っ向から対立する「物語の起点」に位置します。"),
        ("『鉄槌教師』のボン・グンデ(P.O)はオリジナルキャラクターですか?",
         "はい。ボン・グンデ(演:ピョ・ジフン=Block BのP.O)は、情報収集・技術を担うブレインで、ドラマ版で追加されたオリジナルキャラクターです。"),
    ],
    # tettsui-kyoshi-dub-episodes(post 9190)。imp 7,956(サイト最大)/pos 9.1/CTR 1.6%、
    # 「鉄槌教師 声優」が直近7d +239imp 急上昇(2026-07-16 GSC実測)。pos9-10は1ページ目の底で
    # クリックが出ない帯のため、CTR改善より順位押し上げが要る → FAQPage schema で強化。
    # この記事は可視FAQ(<div class="wp-block-group kpop-faq">)が本文に既存のため、
    # JSONLD_ONLY に登録し JSON-LD のみ出力する(可視FAQを足すと重複になる)。
    # 回答は本文の既存FAQ 4問の文言をそのまま転記(ハルシネ防止)。
    9190: [
        ("『鉄槌教師』の主人公イム・ハンリムの声優は誰ですか?",
         "主人公イム・ハンリムの日本語吹き替えは、声優・歌手として活躍する北原沙弥香が担当しています。"),
        ("ジュンヒョン役の吹き替え声優は?",
         "ジュンヒョン役は鈴木崚汰が担当しています。"),
        ("『鉄槌教師』に日本語吹き替え版はありますか?",
         "あります。Netflixで日本語吹き替え版が配信されており、再生中に字幕・音声をワンタップで切り替えられます。"),
        ("吹き替えのスタッフは誰ですか?",
         "吹替翻訳を村富梨絵、日本語版演出を三井瑠美が担当しています。"),
    ],
}

# 可視FAQが本文に既存の記事。JSON-LD のみ出力し、可視HTMLの二重掲載を防ぐ。
JSONLD_ONLY = {9190}

CSS_NOTE = ("<!-- Lane C push: FAQ block。可視FAQ + FAQPage JSON-LD。"
            "本文「関連記事」見出しの直前に挿入する。回答は本文記述に一致。 -->")

JSONLD_ONLY_NOTE = ("<!-- Lane C push: FAQPage JSON-LD のみ。"
                    "可視FAQは本文に既存のため追加しない(重複防止)。"
                    "本文「関連記事」見出しの直前に挿入する。回答は本文の既存FAQに一致。 -->")


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
    if pid in JSONLD_ONLY:
        block = f"{JSONLD_ONLY_NOTE}\n{faq_jsonld(qas)}\n"
        kind = "JSON-LD only"
    else:
        block = f"{CSS_NOTE}\n{visible_faq(qas)}\n{faq_jsonld(qas)}\n"
        kind = "visible + JSON-LD"
    path = OUT / f"post_{pid}_faq.html"
    path.write_text(block, encoding="utf-8")
    print(f"wrote {path} ({len(qas)} Q&A, {len(block)} bytes, {kind})")

print("\n挿入位置: 各記事の「関連記事 / あわせて読みたい」見出しの直前。")
print("反映: owner が kpop-wp-rw.sh post update <id> で本文に追記(直接渡し・stdin禁止)。")
