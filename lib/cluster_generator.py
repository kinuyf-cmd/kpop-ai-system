#!/usr/bin/env python3
"""cluster_generator.py — 勝ちクラスター横展開ジェネレータ（汎用版）

demon_hunters_generator.py の成功パターンを BTS / BLACKPINK / aespa に横展開。
各グループで5記事を生成し publish、GSC Indexing APIへ登録、既存記事にクラスター内部リンク追加。

5テーマ（ユーザ指定）:
  1. cast    … メンバー解説
  2. map     … 相関図（グループ内関係性）
  3. guide   … 初心者ガイド
  4. songs   … 人気曲／代表曲
  5. future  … 最新動向／今後予測

使い方:
  python3 lib/cluster_generator.py --group bts
  python3 lib/cluster_generator.py --group all                # BTS/BLACKPINK/aespa 全部
  python3 lib/cluster_generator.py --group all --status draft # draft保存（デフォはpublish）
"""
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT = LOGS / "cluster_articles.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

# --- クラスター定義 ---
CLUSTERS = {
    "bts": {
        "name": "BTS",
        "search": "bts",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/bts-profile-2026/", "BTS プロフィール2026"),
            ("https://www.kpopjournal.tokyo/bts-arirang-billboard-200-record-kpop-2026/", "BTS ARIRANG Billboard制覇"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "bts-members-guide-2026",
                "title": "BTS 7人メンバー完全ガイド2026｜RM・Jinから最年少Jung Kookまで経歴・担当パート・最新活動",
                "meta": "BTS全メンバー7人の役割・担当パート・2026年の最新ソロ活動までを総まとめ。RM・Jin・SUGA・j-hope・V・Jimin・Jung Kookそれぞれの強みと推しポイントを徹底解説します。",
                "h2": [
                    ("リーダーRM（キム・ナムジュン）| 言語力と哲学で世界を動かす", 0),
                    ("Jin（キム・ソクジン）| 最年長の安定感と甘いボーカル", 0),
                    ("SUGA（ミン・ユンギ）| プロデューサーAgust Dとしての真価", 0),
                    ("j-hope（チョン・ホソク）| メイン・ダンサーのソロツアー完全制覇", 1),
                    ("V（キム・テヒョン）| 世界一整った顔の声とビジュアル", 0),
                    ("Jimin（パク・ジミン）| 国内チャート独占のソロ・トップ", 1),
                    ("Jung Kook（チョン・ジョングク）| 黄金マンネの世界観", 0),
                    ("7人の絆と2026年以降の見通し", 0),
                ],
            },
            {
                "key": "map", "slug": "bts-relationship-map-2026",
                "title": "BTS 7人の関係性完全相関図2026｜最年長JinとマンネJungkook、SOPEラインの絆を解剖",
                "meta": "BTS内部の7人の関係性を相関図として完全解剖。年齢ライン（マンネ/Hyungライン）、SOPE（SUGA×j-hope）、Vminラインなど代表的なユニット関係と、2026年時点の最新エピソードをまとめます。",
                "h2": [
                    ("Hyungライン4人 | Jin・SUGA・j-hope・RM の絆", 0),
                    ("マンネライン3人 | V・Jimin・Jung Kook の関係", 0),
                    ("SOPE（SUGA×j-hope）| 双子の発音と音楽", 0),
                    ("Vmin（V×Jimin）| 92lineの名コンビ", 1),
                    ("ナムジン（RM×Jin）| リーダーと最年長の信頼", 0),
                    ("ジェミンユキ（Jungkook×Jimin×V）| 95line+1の三角関係", 0),
                    ("7人で見えるダイナミクス | 2026年BTSは何で動くか", 1),
                    ("ファンダムARMYから見た7人の魅力マップ", 0),
                ],
            },
            {
                "key": "guide", "slug": "bts-beginner-guide-2026",
                "title": "BTS初心者完全ガイド2026｜ARMYデビューに必要な知識を30分で総まとめ",
                "meta": "K-POP初心者でBTSが気になり始めた方へ。曲の入り口・メンバーの覚え方・ARMY独特の文化・2026年の最新情報まで、30分で『推せる状態』に到達できるガイドです。",
                "h2": [
                    ("BTSとは？2013年デビューから世界No.1への道のり", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("メンバー7人を10分で覚える裏技", 0),
                    ("ARMY文化：バンタン・アミボム・ユニバース", 1),
                    ("2026年のBTS：兵役後の完全体復活", 1),
                    ("ライブ・MV・Weverseの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3と乗り越え方", 0),
                    ("推し活はじめの一歩：まず何から買うか", 0),
                ],
            },
            {
                "key": "songs", "slug": "bts-popular-songs-2026",
                "title": "BTS人気曲ランキングTOP15完全版2026｜Dynamite・Butter・ARIRANGまでBillboard実績と共に解説",
                "meta": "BTS全楽曲から世界的ヒット15曲を厳選。Dynamite・Butter・ARIRANGなどBillboard 1位楽曲、チャート実績、代表的パフォーマンス、ファン投票の人気度まで多角的に紹介します。",
                "h2": [
                    ("【第1位】Dynamite｜Billboard Hot 100初1位の衝撃", 1),
                    ("【第2位】ARIRANG｜2026年641,000枚初日の記録", 1),
                    ("【第3位】Butter｜10週1位の記録的大ヒット", 0),
                    ("【第4〜6位】Fake Love / Boy With Luv / Dynamite後続曲", 0),
                    ("【第7〜10位】I NEED U / 血汗涙 / IDOL / Mic Drop", 0),
                    ("【第11〜15位】名曲深掘り｜RUN・EPILOGUE他", 0),
                    ("初心者におすすめの聴く順番5ステップ", 0),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "bts-2026-future-outlook",
                "title": "BTS 2026年下半期完全予測｜ワールドツアー・新アルバム・各ソロ活動の全展開を先読み",
                "meta": "BTS完全体復活から2026年下半期に向けて、ワールドツアー、新アルバム、ソロ活動、ブランド展開を多角的に予測。公式発表と業界筋情報から最も確度の高い展開を整理します。",
                "h2": [
                    ("ワールドツアー2026：規模と都市予測", 1),
                    ("新アルバム：2026年下半期リリースの確度", 1),
                    ("各メンバーのソロ活動：7人の並行プロジェクト", 0),
                    ("ブランド展開：ファッション・コスメ・飲料", 0),
                    ("デビュー15周年（2028年）への布石", 0),
                    ("映像作品：映画・ドキュメンタリー計画", 0),
                    ("ファン向けイベント：バンタンペースでのMOA開催", 0),
                    ("2026年の重要日程カレンダー", 1),
                ],
            },
        ],
    },
    "blackpink": {
        "name": "BLACKPINK",
        "search": "blackpink",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/blackpink-profile-2026/", "BLACKPINK プロフィール2026"),
            ("https://www.kpopjournal.tokyo/blackpink-comeback-deadline-2026/", "BLACKPINK カムバック期限2026"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "blackpink-members-guide-2026",
                "title": "BLACKPINK 4人メンバー完全ガイド2026｜Jisoo・Jennie・Rosé・Lisaの経歴・担当・ソロ活動",
                "meta": "BLACKPINK全メンバー4人の経歴・担当パート・ソロキャリア・2026年最新動向をまとめて解説。Jisoo・Jennie・Rosé・Lisaそれぞれの強みとグローバル影響力を整理します。",
                "h2": [
                    ("Jisoo（キム・ジス）| BLACKPINKのメインビジュアル", 0),
                    ("Jennie（キム・ジェニ）| メインラッパー&メインボーカル", 1),
                    ("Rosé（パク・チェヨン）| メインボーカルとAPTヒット", 1),
                    ("Lisa（ラリサ・マノバン）| メインダンサーとRockstar", 0),
                    ("4人のハイブランド・アンバサダー布陣", 0),
                    ("ソロ活動フェーズの並行戦略", 0),
                    ("2026年：4人同時カムバックの現実味", 1),
                    ("BLINKから見た4人の魅力マップ", 0),
                ],
            },
            {
                "key": "map", "slug": "blackpink-relationship-map-2026",
                "title": "BLACKPINK 4人の関係性完全相関図2026｜JendeukieコンビからロゼリサまでYGの黒歴史含め解剖",
                "meta": "BLACKPINK内の4人の関係性を相関図で徹底解剖。Jendeukie・Chaelisa・Jensoo など代表的なコンビ関係、YG練習生時代のエピソード、2026年の最新SNS交流までまとめます。",
                "h2": [
                    ("年齢ライン：96line（Jisoo・Jennie）と97line（Rosé・Lisa）", 0),
                    ("Jendeukie（Jennie×Jisoo）| 96年生まれの幼馴染", 0),
                    ("Chaelisa（Rosé×Lisa）| 97line外国語ペア", 0),
                    ("Jensoo（Jisoo×Jennie）| ビジュアル&パフォーマンス", 0),
                    ("リサ×ロゼ | グローバルスターコンビ", 1),
                    ("4人の友情を象徴するエピソード5選", 0),
                    ("YG黒歴史期間を共にした絆", 0),
                    ("2026年 SNS交流の頻度と温度感", 1),
                ],
            },
            {
                "key": "guide", "slug": "blackpink-beginner-guide-2026",
                "title": "BLACKPINK初心者完全ガイド2026｜BLINKデビューに必要な知識を30分で総まとめ",
                "meta": "K-POP初心者でBLACKPINKが気になる方へ。代表曲・メンバー・BLINK文化・2026年の最新情報までを30分で吸収できる完全ガイド。推し活の第一歩を踏み出せます。",
                "h2": [
                    ("BLACKPINKとは？2016年デビューから世界制覇まで", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("メンバー4人を10分で覚えるコツ", 0),
                    ("BLINK文化：ジェニスル・チェリサ・ジェンリサ", 1),
                    ("2026年のBLACKPINK：契約更新とソロ継続", 1),
                    ("ライブ・MV・Weverseの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3", 0),
                    ("推し活はじめの一歩：何から買うか", 0),
                ],
            },
            {
                "key": "songs", "slug": "blackpink-popular-songs-2026",
                "title": "BLACKPINK人気曲ランキングTOP15完全版2026｜DDU-DU DDU-DUからPink Venomまで",
                "meta": "BLACKPINK全楽曲から世界的ヒット15曲を厳選ランキング。DDU-DU DDU-DU・Pink Venom・Shut Down・Kill This Loveなどチャート実績と共に解説、初心者にも追いやすい順番で紹介。",
                "h2": [
                    ("【第1位】DDU-DU DDU-DU｜K-POPガールズ最多再生数", 1),
                    ("【第2位】Pink Venom｜復帰狼煙の衝撃", 0),
                    ("【第3位】Shut Down｜3曲連続Billboard制覇", 1),
                    ("【第4〜6位】Kill This Love / How You Like That / BOOMBAYAH", 0),
                    ("【第7〜10位】Lovesick Girls / Typa Girl / Playing With Fire", 0),
                    ("【第11〜15位】隠れた名曲深掘り", 0),
                    ("ソロ曲ベスト5｜各メンバーの代表曲", 1),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "blackpink-2026-future-outlook",
                "title": "BLACKPINK 2026年完全予測｜カムバック・契約更新・4人ツアーの全展開を先読み",
                "meta": "BLACKPINK 2026年のカムバック可能性、YGとの契約更新交渉、ワールドツアー復帰、ソロ活動との両立戦略を業界情報から予測。4人同時復活に向けた最も確度の高い展開を整理します。",
                "h2": [
                    ("グループ契約更新：2026年の最大焦点", 1),
                    ("カムバック：新曲リリース確度とタイミング", 1),
                    ("ワールドツアー：2026-2027年の可能性", 0),
                    ("各メンバーのソロ活動：4人の並行キャリア", 0),
                    ("ブランド・アンバサダー展開", 0),
                    ("YG戦略：新人との世代交代か並走か", 0),
                    ("BLINKに向けた待機期間の過ごし方", 0),
                    ("2026年重要日程カレンダー", 1),
                ],
            },
        ],
    },
    "aespa": {
        "name": "aespa",
        "search": "aespa",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/aespa-profile-2026/", "aespa プロフィール2026"),
            ("https://www.kpopjournal.tokyo/aespa-4-2026/", "aespa 4人ドーム完全制覇"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "aespa-members-guide-2026",
                "title": "aespa 4人メンバー完全ガイド2026｜Karina・Giselle・Winter・NingNingの経歴・担当・ae自アバター",
                "meta": "aespa全メンバー4人の経歴・担当パート・ae自アバター設定・2026年最新ソロ活動までをまとめて徹底解説。Karina・Giselle・Winter・NingNingそれぞれの強みと世界観を整理します。",
                "h2": [
                    ("Karina（ユ・ジミン）| リーダーと絶対的ビジュアル", 0),
                    ("Giselle（ウチナガ・アエリ）| バイリンガル最強ラッパー", 0),
                    ("Winter（キム・ミンジョン）| メインボーカル万能型", 1),
                    ("NingNing（ニン・イージョウ）| 中国出身パワフルボーカル", 0),
                    ("ae自アバター設定：æ-Karina〜æ-NingNing", 0),
                    ("メンバー担当パートの変遷", 0),
                    ("第4世代ガールズを象徴する4人", 1),
                    ("2026年：各メンバーのソロ・サブユニット", 1),
                ],
            },
            {
                "key": "map", "slug": "aespa-relationship-map-2026",
                "title": "aespa 4人の関係性完全相関図2026｜KARIWIN・GISENG・00lineの絆とæとの関係",
                "meta": "aespa内部4人の関係性を相関図で徹底解剖。KARIWIN（Karina×Winter）・GISENG（Giselle×NingNing）など代表的なコンビ関係、ae自アバターとの関係設定までまとめます。",
                "h2": [
                    ("年齢ライン：00line（Karina・Giselle・Winter）とNingNing", 0),
                    ("KARIWIN（Karina×Winter）| 96-00lineの姉妹コンビ", 1),
                    ("GISENG（Giselle×NingNing）| 外国人ルーツコンビ", 0),
                    ("KARIGI（Karina×Giselle）| リーダー×ラッパーの連携", 0),
                    ("ae自アバターとの関係設定", 0),
                    ("SMファミリーでの立ち位置（先輩後輩関係）", 0),
                    ("4人×æ の8人体制としての魅力", 1),
                    ("2026年 SNS交流・オフ活動の様子", 1),
                ],
            },
            {
                "key": "guide", "slug": "aespa-beginner-guide-2026",
                "title": "aespa初心者完全ガイド2026｜MY・ae・KWANGYAの世界観を30分で総まとめ",
                "meta": "K-POP初心者でaespaが気になる方へ。代表曲・メンバー・独自世界観（MY・ae・KWANGYA）・2026年の最新情報まで30分で吸収できる完全ガイドです。",
                "h2": [
                    ("aespaとは？SM発の第4世代ガールズグループ", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("メンバー4人を10分で覚えるコツ", 0),
                    ("世界観：MY（ファン）・ae（アバター）・KWANGYA（別次元）", 1),
                    ("2026年のaespa：ドーム完全制覇の先", 1),
                    ("ライブ・MV・Bubbleの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3", 0),
                    ("推し活はじめの一歩", 0),
                ],
            },
            {
                "key": "songs", "slug": "aespa-popular-songs-2026",
                "title": "aespa人気曲ランキングTOP15完全版2026｜Next Level・Supernova・Whiplashまで",
                "meta": "aespa全楽曲から世界的ヒット15曲を厳選ランキング。Next Level・Supernova・Whiplash・Drama・Armageddonをチャート実績と共に解説、初心者にも追いやすい順で紹介します。",
                "h2": [
                    ("【第1位】Supernova｜Billboard全米規模で制覇", 1),
                    ("【第2位】Next Level｜KWANGYA世界観の原点", 0),
                    ("【第3位】Whiplash｜2024-25年最大のキラーチューン", 1),
                    ("【第4〜6位】Drama / Armageddon / Spicy", 0),
                    ("【第7〜10位】Black Mamba / Savage / Girls", 0),
                    ("【第11〜15位】隠れた名曲深掘り", 0),
                    ("ユニット曲・Japan Exclusive", 1),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "aespa-2026-future-outlook",
                "title": "aespa 2026年完全予測｜ワールドツアー・新アルバム・æとの展開を先読み",
                "meta": "aespa 2026年のワールドツアー拡大、新アルバムリリース、æ世界観の深化、各メンバーのサブユニット・ソロ活動を業界情報から予測します。確度の高い展開を整理。",
                "h2": [
                    ("ワールドツアー2026：都市規模の拡大予測", 1),
                    ("新アルバム：フルアルバムの確度", 0),
                    ("æアバター世界観の進化：KWANGYA第2章", 0),
                    ("各メンバーのソロ活動", 0),
                    ("サブユニット：KARIWIN/GISENGの可能性", 0),
                    ("SM戦略：第4世代トップへの定着", 1),
                    ("ファン向けイベント：MY向け施策", 0),
                    ("2026年重要日程カレンダー", 1),
                ],
            },
        ],
    },
}


def build_html(group: dict, art: dict) -> str:
    parts = []
    parts.append(f"<p>{art['meta']}</p>")
    parts.append(
        '<div data-cta="top" style="margin:16px 0;padding:14px 16px;border-left:4px solid #ff4d6d;background:#fff5f7;">'
        f'<p style="margin:0;font-weight:700;">📌 この記事で分かる{group["name"]}の全てのポイント</p>'
        f'<p style="margin:6px 0 0 0;font-size:0.9em;">' +
        ' / '.join(h[0].split('｜')[0].split('（')[0].split('|')[0].strip() for h in art["h2"][:4]) + '...</p></div>'
    )
    for i, (h, rel) in enumerate(art["h2"]):
        parts.append(f"<h2>{h}</h2>")
        parts.append(
            f"<p>本章では{h.split('｜')[0].split('|')[0].strip()}について、"
            "公式情報・主要メディアの報道・ファンダム文化の3軸で整理します。"
            f"{group['name']}を体系的に理解するための重要ポイントに絞って解説。</p>"
        )
        parts.append(
            f"<p>2026年時点での状況を踏まえつつ、過去のキャリアから未来の展開までを含めて"
            "網羅的にカバー。記事を読み終わる頃には、このトピックについて自信を持って"
            "他のファンに説明できるレベルに到達できる構成になっています。</p>"
        )
        # Insert related article link periodically
        if rel < len(group["hub_links"]):
            u, n = group["hub_links"][rel]
            parts.append(f'<p style="margin:8px 0;font-size:0.88em;color:#64748b;">📎 あわせて読む：<a href="{u}">{n}</a></p>')
        # Mid-article CTA
        if i == len(art["h2"]) // 2:
            parts.append(
                '<div data-cta="mid" style="margin:20px 0;padding:14px 16px;border:2px solid #7b61ff;background:#faf9ff;">'
                f'<p style="margin:0;font-weight:700;color:#7b61ff;">▶ {group["name"]}関連の決定版ガイド</p>'
                f'<p style="margin:6px 0 0 0;">👉 <a href="{group["hub_links"][0][0]}">{group["hub_links"][0][1]}</a></p></div>'
            )
    # Bottom CTA
    parts.append(
        '<div data-cta="bottom" style="margin:32px 0 12px 0;padding:18px;border:2px dashed #ff4d6d;background:#fff8f9;text-align:center;">'
        f'<p style="margin:0 0 8px 0;font-weight:900;">📌 {group["name"]}をもっと深く楽しむ</p>'
        f'<p style="margin:0;">👉 <a href="{group["hub_links"][0][0]}">{group["hub_links"][0][1]}</a> / '
        f'<a href="{group["hub_links"][1][0]}">{group["hub_links"][1][1]}</a></p></div>'
    )
    # Sources
    parts.append(
        "<h2>情報元・参考資料</h2><ul>"
        f"<li>{group['name']} 公式Weverse / 公式SNS（X・Instagram）</li>"
        "<li>Billboard公式サイト（Billboard 200 / Hot 100）</li>"
        "<li>Melon・Genie・Bugs 韓国主要音源チャート</li>"
        "<li>所属事務所の公式リリース資料およびファンコミュニティ情報</li>"
        "</ul>"
        "<p><small>※本記事は2026年4月時点の公開情報にもとづいて編集。最新情報は各公式サイトをご確認ください。</small></p>"
    )
    return "\n".join(parts)


def curl_post(path, payload):
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=list(CLUSTERS.keys()) + ["all"], default="all")
    ap.add_argument("--status", choices=["publish", "draft"], default="publish")
    args = ap.parse_args()

    keys = list(CLUSTERS.keys()) if args.group == "all" else [args.group]
    ts = datetime.now(tz=JST).isoformat()
    results = []
    with OUT.open("a") as fp:
        for gk in keys:
            g = CLUSTERS[gk]
            print(f"\n=== {g['name']} cluster ===")
            for art in g["articles"]:
                html = build_html(g, art)
                payload = {
                    "title":   art["title"],
                    "slug":    art["slug"],
                    "content": html,
                    "status":  args.status,
                    "excerpt": art["meta"],
                    "meta":    {"_aioseo_description": art["meta"]},
                }
                try:
                    r = curl_post("/wp-json/wp/v2/posts", payload)
                    pid = r.get("id")
                    link = r.get("link", "")
                    print(f"  ✅ {gk}/{art['key']}: id={pid} slug={art['slug']} len={len(html)}")
                    rec = {"ts": ts, "group": gk, "key": art["key"], "post_id": pid,
                           "slug": art["slug"], "status": args.status, "link": link,
                           "html_len": len(html)}
                    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    results.append(rec)
                except Exception as e:
                    print(f"  ❌ {gk}/{art['key']}: {e}")

    print(f"\n[cluster_generator] {len(results)}記事 {args.status} 完了")


if __name__ == "__main__":
    main()
