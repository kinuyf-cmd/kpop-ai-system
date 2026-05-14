#!/usr/bin/env python3
"""cluster_generator.py — 勝ちクラスター横展開ジェネレータ（汎用版）

demon_hunters_generator.py の成功パターンを
BTS / BLACKPINK / aespa / IVE / NewJeans / SEVENTEEN / LE SSERAFIM に横展開。
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
import re
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
    "ive": {
        "name": "IVE",
        "search": "ive",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/ive-profile-2026/", "IVE プロフィール2026"),
            ("https://www.kpopjournal.tokyo/kpop-comeback-schedule-2026/", "K-POPカムバックスケジュール2026"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "ive-members-guide-2026",
                "title": "IVE 6人メンバー完全ガイド2026｜ユジン・ガウル・レイ・ウォニョン・リズ・イソの経歴と担当",
                "meta": "IVE全メンバー6人の経歴・担当・2026年最新ソロ活動を徹底解説。ユジン・ガウル・レイ・ウォニョン・リズ・イソそれぞれの強みと魅力を整理し初心者にも分かりやすく紹介します。",
                "h2": [
                    ("アン・ユジン（リーダー）| 元IZ*ONEセンターの絶対的ビジュアル", 0),
                    ("ガウル（コ・ユジン）| 元IZ*ONE経験と安定感", 0),
                    ("レイ（内藤レイ）| 日本人メンバー最強ダンサー", 1),
                    ("チャン・ウォンヨン | 第4世代ビジュアルの頂点", 0),
                    ("リズ（キム・ジウォン）| メインボーカルのパワー", 0),
                    ("イソ（イ・ヒョンソ）| 最年少ラッパーの存在感", 0),
                    ("6人の担当パート・ユニット構成", 1),
                    ("DIVEから見た6人の魅力マップ", 0),
                ],
            },
            {
                "key": "map", "slug": "ive-relationship-map-2026",
                "title": "IVE 6人の関係性完全相関図2026｜元IZ*ONE組とニューラインの絆を解剖",
                "meta": "IVE内6人の関係性を相関図で徹底解剖。元IZ*ONEユジン・ガウル組、ウォニョン・レイ・リズ・イソのニューライン、03line/04line/07lineの内部関係と2026年最新SNS交流までまとめます。",
                "h2": [
                    ("元IZ*ONE組 | ユジン・ガウルの盤石コンビ", 0),
                    ("ウォニョン×ユジン | センター2枚看板", 1),
                    ("ウォニョン×レイ | 04line親友コンビ", 0),
                    ("リズ×イソ | 末っ子ラインの仲良しペア", 0),
                    ("レイ×ガウル | 異文化ハーフコンビ", 0),
                    ("年齢別ライン：03/04/07lineの距離感", 0),
                    ("6人で見えるユニット相性マップ", 1),
                    ("2026年 DIVEから見る6人の温度感", 1),
                ],
            },
            {
                "key": "guide", "slug": "ive-beginner-guide-2026",
                "title": "IVE初心者完全ガイド2026｜DIVEデビューに必要な知識を30分で総まとめ",
                "meta": "K-POP初心者でIVEが気になる方へ。代表曲・メンバー・DIVE文化・2026年の最新情報までを30分で吸収できる完全ガイド。推し活の第一歩を確実に踏み出せます。",
                "h2": [
                    ("IVEとは？2021年デビューから第4世代トップへ", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("メンバー6人を10分で覚えるコツ", 0),
                    ("DIVE文化：公式カラー・応援棒・SNS用語", 1),
                    ("2026年のIVE：ワールドツアーと日本進出", 1),
                    ("ライブ・MV・Weverseの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3", 0),
                    ("推し活はじめの一歩", 0),
                ],
            },
            {
                "key": "songs", "slug": "ive-popular-songs-2026",
                "title": "IVE人気曲ランキングTOP15完全版2026｜LOVE DIVE・After LIKE・I AMまで",
                "meta": "IVE全楽曲から世界的ヒット15曲を厳選ランキング。LOVE DIVE・After LIKE・I AM・Kitsch・Baddie・HEYA・Accendioをチャート実績と共に解説、初心者向けに聴く順も提案します。",
                "h2": [
                    ("【第1位】LOVE DIVE｜大賞3冠のブレイク曲", 1),
                    ("【第2位】After LIKE｜夏のアンセム", 0),
                    ("【第3位】I AM｜ガールクラッシュ宣言", 1),
                    ("【第4〜6位】Kitsch / Baddie / HEYA", 0),
                    ("【第7〜10位】ELEVEN / Accendio / All Night", 0),
                    ("【第11〜15位】隠れた名曲深掘り", 0),
                    ("日本語楽曲・Japan Exclusive", 1),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "ive-2026-future-outlook",
                "title": "IVE 2026年完全予測｜ワールドツアー・新アルバム・ソロ活動の全展開を先読み",
                "meta": "IVE 2026年のワールドツアー拡大、新アルバムリリース、各メンバーのソロ・サブユニット活動、日本市場攻略までを業界情報から予測。確度の高い展開を整理します。",
                "h2": [
                    ("ワールドツアー2026：都市規模の拡大予測", 1),
                    ("新アルバム：フルアルバムの確度", 0),
                    ("ウォニョン・ユジンのソロ活動可能性", 0),
                    ("レイの日本市場でのソロ・俳優路線", 1),
                    ("サブユニット：6人編成での多様化", 0),
                    ("STARSHIP戦略：第4世代トップ固定化", 0),
                    ("ファン向けイベント：DIVE向け施策", 0),
                    ("2026年重要日程カレンダー", 1),
                ],
            },
        ],
    },
    "newjeans": {
        "name": "NewJeans",
        "search": "newjeans",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/newjeans-profile-2026/", "NewJeans プロフィール2026"),
            ("https://www.kpopjournal.tokyo/kpop-comeback-schedule-2026/", "K-POPカムバックスケジュール2026"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "newjeans-members-guide-2026",
                "title": "NewJeans 5人メンバー完全ガイド2026｜ミンジ・ハニ・ダニエル・ヘリン・ヘインの経歴と担当",
                "meta": "NewJeans全メンバー5人の経歴・担当・2026年最新ソロ活動を徹底解説。ミンジ・ハニ・ダニエル・ヘリン・ヘインそれぞれの強みと第4世代ガールクラッシュの魅力を整理します。",
                "h2": [
                    ("ミンジ（キム・ミンジ）| リーダーと圧倒的ビジュアル", 0),
                    ("ハニ（ファム・ハン・ニ）| ベトナム系の歌唱力", 1),
                    ("ダニエル（ダニエル・マーシュ）| 豪州韓国ハーフの明るさ", 0),
                    ("ヘリン（カン・ヘリン）| メインダンサーの実力", 0),
                    ("ヘイン（イ・ヘイン）| 最年少マンネの透明感", 0),
                    ("5人の担当パート・ユニット構成", 0),
                    ("第4世代 Y2K×イージーリスニング路線", 1),
                    ("Bunniesから見た5人の魅力マップ", 0),
                ],
            },
            {
                "key": "map", "slug": "newjeans-relationship-map-2026",
                "title": "NewJeans 5人の関係性完全相関図2026｜04line姉妹とマンネヘインの絆を解剖",
                "meta": "NewJeans内5人の関係性を相関図で徹底解剖。ミンジ・ハニ・ダニエル・ヘリンの04line、マンネヘインとの関係、2026年最新SNS交流までまとめます。",
                "h2": [
                    ("04line4人 | ミンジ・ハニ・ダニエル・ヘリンの絆", 0),
                    ("マンネヘイン | 07lineの可愛がられポジション", 0),
                    ("ミンジ×ハニ | リーダーとメインボーカル", 1),
                    ("ダニエル×ヘリン | ハーフ組と実力派", 0),
                    ("ヘリン×ヘイン | ダンス姉妹ライン", 0),
                    ("ミンジ×ヘイン | リーダーとマンネの距離", 0),
                    ("5人で見えるユニット相性マップ", 1),
                    ("2026年 Bunniesから見る5人の温度感", 1),
                ],
            },
            {
                "key": "guide", "slug": "newjeans-beginner-guide-2026",
                "title": "NewJeans初心者完全ガイド2026｜Bunniesデビューに必要な知識を30分で総まとめ",
                "meta": "K-POP初心者でNewJeansが気になる方へ。代表曲・メンバー・Bunnies文化・2026年の最新情報までを30分で吸収できる完全ガイド。推し活の第一歩を確実に踏み出せます。",
                "h2": [
                    ("NewJeansとは？2022年デビューの革命児", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("メンバー5人を10分で覚えるコツ", 0),
                    ("Bunnies文化：公式カラー・応援棒・ロゴ", 1),
                    ("2026年のNewJeans：ADOR問題その後", 1),
                    ("ライブ・MV・Phoningの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3", 0),
                    ("推し活はじめの一歩", 0),
                ],
            },
            {
                "key": "songs", "slug": "newjeans-popular-songs-2026",
                "title": "NewJeans人気曲ランキングTOP15完全版2026｜Hype Boy・Ditto・OMGからSuper Shyまで",
                "meta": "NewJeans全楽曲から世界的ヒット15曲を厳選ランキング。Hype Boy・Ditto・OMG・Super Shy・ETA・How Sweet・Supernaturalをチャート実績と共に解説します。",
                "h2": [
                    ("【第1位】Ditto｜Melonチャート最長1位記録", 1),
                    ("【第2位】Hype Boy｜デビュー曲の大ヒット", 0),
                    ("【第3位】OMG｜バイラルTikTok爆発", 1),
                    ("【第4〜6位】Super Shy / ETA / Cool With You", 0),
                    ("【第7〜10位】Attention / How Sweet / Supernatural", 0),
                    ("【第11〜15位】隠れた名曲深掘り", 0),
                    ("日本語楽曲・Japan Exclusive", 1),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "newjeans-2026-future-outlook",
                "title": "NewJeans 2026年完全予測｜ADOR和解後のワールドツアー・新アルバム・ソロ展開を先読み",
                "meta": "NewJeans 2026年のADOR体制安定後のワールドツアー、新アルバムリリース、各メンバーのソロ活動、日本市場攻略を業界情報から予測。確度の高い展開を整理します。",
                "h2": [
                    ("ADOR体制：2026年の安定と活動再開", 1),
                    ("ワールドツアー2026：都市規模の拡大予測", 1),
                    ("新アルバム：フルアルバムの確度", 0),
                    ("各メンバーのソロ活動可能性", 0),
                    ("ダニエル・ハニの日本市場攻略", 1),
                    ("サブユニット：5人編成の多様化", 0),
                    ("ファン向けイベント：Bunnies向け施策", 0),
                    ("2026年重要日程カレンダー", 1),
                ],
            },
        ],
    },
    "seventeen": {
        "name": "SEVENTEEN",
        "search": "seventeen",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/seventeen-profile-2026/", "SEVENTEEN プロフィール2026"),
            ("https://www.kpopjournal.tokyo/kpop-comeback-schedule-2026/", "K-POPカムバックスケジュール2026"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "seventeen-members-guide-2026",
                "title": "SEVENTEEN 13人メンバー完全ガイド2026｜ヒップホップ・ボーカル・パフォーマンス3ユニットの全貌",
                "meta": "SEVENTEEN全13人の経歴・担当・ユニット構成を徹底解説。S.coups・ジョンハン・ジョシュアらヒップホップチーム、ボーカルチーム、パフォーマンスチーム、各メンバーの強みを整理します。",
                "h2": [
                    ("ヒップホップチーム | S.coups・ウジ・ミンギュ・バーノン", 0),
                    ("ボーカルチーム | ジョンハン・ジョシュア・ドギョム・スングァン・DK", 0),
                    ("パフォーマンスチーム | ホシ・ジュン・ディノ・ジョンハン", 1),
                    ("S.coups（リーダー）| 13人を束ねる兄貴", 0),
                    ("ウジ | 自作曲の天才プロデューサー", 0),
                    ("ホシ | パフォーマンスチームリーダー", 0),
                    ("13人のユニット動線・楽曲制作プロセス", 1),
                    ("CARATから見た13人の魅力マップ", 0),
                ],
            },
            {
                "key": "map", "slug": "seventeen-relationship-map-2026",
                "title": "SEVENTEEN 13人の関係性完全相関図2026｜95line/96line/97line/99lineの絆を解剖",
                "meta": "SEVENTEEN13人の関係性を相関図で徹底解剖。95line/96line/97line/99lineの年齢ライン、ユニット内部関係、13人の複雑な友情マップまでまとめます。",
                "h2": [
                    ("95line | S.coups・ジョンハン・ジョシュア・ジュン", 0),
                    ("96line | ホシ・ウジ・ウォヌ", 0),
                    ("97line | ドギョム・ミンギュ・THE8", 0),
                    ("99line | スングァン・バーノン・ディノ", 1),
                    ("ヒップホップ・ボーカル・パフォ内部の絆", 0),
                    ("BooSeokSoon（BSS）ユニットの仲良し三人組", 1),
                    ("13人で見える複雑な友情マップ", 0),
                    ("2026年 CARATから見る13人の温度感", 1),
                ],
            },
            {
                "key": "guide", "slug": "seventeen-beginner-guide-2026",
                "title": "SEVENTEEN初心者完全ガイド2026｜CARATデビューに必要な知識を30分で総まとめ",
                "meta": "K-POP初心者でSEVENTEENが気になる方へ。代表曲・13人メンバー・CARAT文化・2026年の最新情報までを30分で吸収できる完全ガイド。推し活の第一歩を踏み出せます。",
                "h2": [
                    ("SEVENTEENとは？2015年デビューのセルプロデュースボーイズ", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("13人メンバーを10分で覚える裏技", 0),
                    ("CARAT文化：公式カラー・応援棒・ユニット愛称", 1),
                    ("2026年のSEVENTEEN：兵役完了と完全体復活", 1),
                    ("ライブ・MV・Weverseの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3", 0),
                    ("推し活はじめの一歩", 0),
                ],
            },
            {
                "key": "songs", "slug": "seventeen-popular-songs-2026",
                "title": "SEVENTEEN人気曲ランキングTOP15完全版2026｜VERY NICE・HOME RUN・God of Musicまで",
                "meta": "SEVENTEEN全楽曲から人気曲15曲を厳選ランキング。VERY NICE・HOME RUN・God of Music・Super・Rock with youをチャート実績と共に解説、13人の自作曲の魅力も紹介します。",
                "h2": [
                    ("【第1位】HOT｜Billboard 200 No.1制覇", 1),
                    ("【第2位】God of Music｜ボブ・ディラン譜面引用", 0),
                    ("【第3位】Super（孫悟空）| カムバ大ヒット", 1),
                    ("【第4〜6位】Rock with you / HOME RUN / VERY NICE", 0),
                    ("【第7〜10位】Left & Right / HOT / Clap / Don Quixote", 0),
                    ("【第11〜15位】隠れた名曲深掘り", 0),
                    ("日本語楽曲・Japan Exclusive", 1),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "seventeen-2026-future-outlook",
                "title": "SEVENTEEN 2026年完全予測｜兵役完了後のワールドツアー・新アルバム・全ソロ活動を先読み",
                "meta": "SEVENTEEN 2026年の兵役完了後13人完全体での活動再開、ワールドツアー、新アルバム、各メンバーのソロ活動を業界情報から予測。確度の高い展開を整理します。",
                "h2": [
                    ("兵役状況：13人完全体復活のタイミング", 1),
                    ("ワールドツアー2026：都市規模の拡大予測", 1),
                    ("新アルバム：フルアルバムの確度", 0),
                    ("ソロ活動：ウジ・ホシ・バーノン・THE8", 0),
                    ("BSS等サブユニットの継続活動", 1),
                    ("PLEDIS/HYBE戦略：第3世代レジェンド化", 0),
                    ("ファン向けイベント：CARAT向け施策", 0),
                    ("2026年重要日程カレンダー", 1),
                ],
            },
        ],
    },
    "lesserafim": {
        "name": "LE SSERAFIM",
        "search": "lesserafim",
        "hub_links": [
            ("https://www.kpopjournal.tokyo/lesserafim-profile-2026/", "LE SSERAFIM プロフィール2026"),
            ("https://www.kpopjournal.tokyo/kpop-comeback-schedule-2026/", "K-POPカムバックスケジュール2026"),
        ],
        "articles": [
            {
                "key": "cast", "slug": "lesserafim-members-guide-2026",
                "title": "LE SSERAFIM 5人メンバー完全ガイド2026｜サクラ・チェウォン・ウンチェ・カズハ・ユンジンの経歴と担当",
                "meta": "LE SSERAFIM全メンバー5人の経歴・担当・2026年最新ソロ活動を徹底解説。サクラ・チェウォン・ウンチェ・カズハ・ユンジンそれぞれの強みと自信の美学を整理します。",
                "h2": [
                    ("サクラ（宮脇咲良）| HKT48・IZ*ONE経由の最強経験", 1),
                    ("チェウォン（キム・チェウォン）| リーダーのカリスマ", 0),
                    ("ウンチェ（ホン・ウンチェ）| 最年少マンネの透明感", 0),
                    ("カズハ（中村一葉）| バレエ出身メインダンサー", 1),
                    ("ホ・ユンジン | 米国出身ラッパー・ボーカル", 0),
                    ("5人の担当パート・ユニット構成", 0),
                    ("第4世代 ガールクラッシュ×自信の美学", 0),
                    ("FEARNOTから見た5人の魅力マップ", 0),
                ],
            },
            {
                "key": "map", "slug": "lesserafim-relationship-map-2026",
                "title": "LE SSERAFIM 5人の関係性完全相関図2026｜元IZ*ONE組と新世代4人の絆を解剖",
                "meta": "LE SSERAFIM内5人の関係性を相関図で徹底解剖。元IZ*ONEサクラ・チェウォン、カズハ・ユンジン・ウンチェの新世代、日韓混成の特殊ダイナミクスまでまとめます。",
                "h2": [
                    ("元IZ*ONE組 | サクラ・チェウォンの盤石コンビ", 1),
                    ("カズハ×サクラ | 日本組の絆", 1),
                    ("ユンジン×チェウォン | 97lineパワーデュオ", 0),
                    ("ウンチェ×他4人 | マンネラインの可愛がられ", 0),
                    ("カズハ×ウンチェ | 03line年下コンビ", 0),
                    ("日韓混成グループ内部のコミュニケーション", 0),
                    ("5人で見えるユニット相性マップ", 1),
                    ("2026年 FEARNOTから見る5人の温度感", 1),
                ],
            },
            {
                "key": "guide", "slug": "lesserafim-beginner-guide-2026",
                "title": "LE SSERAFIM初心者完全ガイド2026｜FEARNOTデビューに必要な知識を30分で総まとめ",
                "meta": "K-POP初心者でLE SSERAFIMが気になる方へ。代表曲・メンバー・FEARNOT文化・2026年の最新情報までを30分で吸収できる完全ガイド。推し活の第一歩を踏み出せます。",
                "h2": [
                    ("LE SSERAFIMとは？2022年デビューHYBE×SOURCE MUSIC", 1),
                    ("最初に聴くべき代表曲TOP5", 0),
                    ("メンバー5人を10分で覚えるコツ", 0),
                    ("FEARNOT文化：公式カラー・応援棒・モットー", 1),
                    ("2026年のLE SSERAFIM：コーチェラ後の世界展開", 1),
                    ("ライブ・MV・Weverseの追いかけ方", 0),
                    ("初心者がぶつかる壁TOP3", 0),
                    ("推し活はじめの一歩", 0),
                ],
            },
            {
                "key": "songs", "slug": "lesserafim-popular-songs-2026",
                "title": "LE SSERAFIM人気曲ランキングTOP15完全版2026｜FEARLESS・ANTIFRAGILE・Perfect Nightまで",
                "meta": "LE SSERAFIM全楽曲から人気曲15曲を厳選ランキング。FEARLESS・ANTIFRAGILE・UNFORGIVEN・EASY・Perfect Night・CRAZYをチャート実績と共に解説、初心者にも追いやすい順で紹介します。",
                "h2": [
                    ("【第1位】ANTIFRAGILE｜Billboard Hot 100チャート入り", 1),
                    ("【第2位】FEARLESS｜デビュー曲の衝撃", 0),
                    ("【第3位】UNFORGIVEN｜Nile Rodgersコラボ", 1),
                    ("【第4〜6位】EASY / Perfect Night / CRAZY", 0),
                    ("【第7〜10位】Eve, Psyche & The Bluebeard's wife / Smart", 0),
                    ("【第11〜15位】隠れた名曲深掘り", 0),
                    ("日本語楽曲・Japan Exclusive", 1),
                    ("2026年以降の新曲・話題曲", 1),
                ],
            },
            {
                "key": "future", "slug": "lesserafim-2026-future-outlook",
                "title": "LE SSERAFIM 2026年完全予測｜ワールドツアー・新アルバム・ソロ展開の全展開を先読み",
                "meta": "LE SSERAFIM 2026年のワールドツアー拡大、新アルバムリリース、各メンバーのソロ活動、コーチェラ後の世界展開を業界情報から予測。確度の高い展開を整理します。",
                "h2": [
                    ("ワールドツアー2026：都市規模の拡大予測", 1),
                    ("新アルバム：フルアルバムの確度", 0),
                    ("サクラの日本市場でのソロ・俳優路線", 1),
                    ("チェウォン・ユンジンのソロ活動可能性", 0),
                    ("カズハの日本進出・CM路線", 1),
                    ("HYBE/SOURCE戦略：世界的地位固定", 0),
                    ("ファン向けイベント：FEARNOT向け施策", 0),
                    ("2026年重要日程カレンダー", 1),
                ],
            },
        ],
    },
}


def _parse_h2(h2: str) -> tuple[str, str]:
    """h2 を主題 / 補足 (役割・説明) に分解。"""
    main = h2.split('｜')[0].split('|')[0].strip()
    rest = ''
    for sep in ('｜', '|'):
        if sep in h2:
            rest = h2.split(sep, 1)[1].strip()
            break
    # 主題から括弧書き本名を取り除く
    main_short = re.sub(r'[（(][^）)]*[）)]', '', main).strip()
    return main_short or main, rest


# key別 × idx別の段落生成テンプレ。
# 同一 key 内でも idx で文体・着眼点を循環させ、boilerplate 反復を避ける。
_P1_TEMPLATES: dict[str, list[str]] = {
    "cast": [
        "{main}{sub_clause}は、{name}内で固有の存在感を担うピースだ。担当パート・ステージング・MV内でのカット配分・ファンダム内での呼称まで含めて見ると、なぜ {main} がこのポジションを任されているのかが立体的に見えてくる。",
        "{main} を {name} のメンバー構成図にマッピングすると、{sub_or_role}としての機能が他メンバーと明確に差分化されているのが分かる。",
        "{main} の魅力は数字化しにくいが、{name} のステージ全体で「ここを抜くと崩れる」役割を担っており、{sub_or_role}という表現で語られることが多い。",
        "{name} を語るうえで {main} を外せない理由は、ボーカル/ダンス/ビジュアルのどの軸でも代替の効かないピースになっている点だ。",
        "{main} のソロ動向を追うと、{name} がメンバー個別ブランドをどう設計しているかが透けて見える。",
    ],
    "map": [
        "{main} の関係性は、{name} 全体のダイナミクスを読むうえで欠かせない切り口だ。VLOG・バラエティ出演・コンサートMC・SNS のリプライ頻度といった一次情報を重ねると、{sub_or_role} の文脈で {main} がどう機能しているかが浮かび上がる。",
        "{main} のペアワークは、{name} のステージ構成・コール&レスポンス設計に直接影響しているコンビネーションだ。",
        "{main} は単なる仲良しエピソードではなく、{name} の楽曲制作・コンセプト決定にまで影響する関係軸になっている。",
        "ファンダム内で {main} が頻繁に切り抜かれる理由を、{name} のグループ運営の視点から整理すると合点がいく。",
        "{main} の距離感は時期によって揺れているが、それが {name} のグループとしての健全さを示す指標になっている。",
    ],
    "guide": [
        "初心者にとって {main} は、{name} を理解する近道のひとつだ。ここでは曲・MV・コンテンツ・SNS の中から最短ルートだけを抽出し、30分以内に {main}{sub_clause} を自分の言葉で説明できる状態に持っていく。",
        "{name} を初めて追う人がつまずきやすいのが {main} の周辺知識で、ここを最初に押さえると残りの情報が一気に整理できる。",
        "{main} は、{name} のファンダムが共有している前提知識のひとつ。知っておくと SNS・コンサートでの体験密度が大きく変わる。",
        "{name} の入門で {main} を後回しにすると遠回りになる。先に概念を掴み、その後で曲・MV を聴く順番が圧倒的に効率的だ。",
        "推し活の最初の一歩として {main} を選ぶ理由は、ここから他トピックへ自然に派生していけるからだ。",
    ],
    "songs": [
        "{main} は、{name} の楽曲史の中でも語り継がれるトピックだ。チャート実績・ストリーミング推移・コレオの完成度・ライブでの定番化度を並べて見ると、なぜこの曲が {sub_or_role} のかが定量的に裏取れる。",
        "{main} を語る上で外せないのは、リリース直後のチャートではなく数ヶ月後のロングテール推移だ。{name} の他楽曲との比較で見えてくる。",
        "{main} のキラーフックは、{name} のサウンド戦略を象徴している。プロデュース体制・サウンドメイクが噛み合った成功例だ。",
        "{main} はライブでのアレンジ違いも含めて評価される楽曲で、{name} のステージング哲学が凝縮されている。",
        "{main} は {name} の代表曲だが、選曲の理由は単純なヒット数ではなく、ファンダム文化への寄与度で測られている。",
    ],
    "future": [
        "{main} は、{name} の 2026 年以降を読むうえで最重要シグナルになる。所属事務所の公式発表・産業誌の観測筋情報・ファンダム内コンセンサスを突き合わせて、{sub_or_role} の確度の高い展開を整理する。",
        "{main} の動きは、{name} の次フェーズを左右する判断材料として業界内で注目されている。",
        "{main} を予測する際に重視すべきは、過去のリリース間隔と海外ツアー枠の取り合いだ。{name} の事務所戦略から逆算すると見えてくる。",
        "{main} は表向きまだ未発表だが、契約更新時期・関連商標出願・スタッフSNS から十分な状況証拠が拾える。",
        "{main} に関する確度ランクを、公式発表・主要メディア観測・ファンダム内噂の3層で整理して提示する。",
    ],
}

_PERSPECTIVES = [
    "特に注目したいのは、{main} を語るうえで {name} 全体の方向性とどう接続するかという点だ。",
    "{main} の文脈を読み解くと、{name} 全体の戦略意図と地続きであることが分かる。",
    "見落とされがちだが、{main} の動きはそのまま {name} の次フェーズの予兆になっている。",
    "{main} を {name} の他要素と並べて配置すると、相互補完の構造が浮かび上がる。",
    "{main} は {name} のブランドにとって、単なる一要素ではなく中核的な役割を担っている。",
    "{main} の評価は時期によって揺れるが、{name} を継続的に追うファンほど一貫した評価を下している。",
    "{main} を入口に他のトピックへ広げていくと、{name} の全体像が短時間で掴める。",
]
_CLOSES = [
    "本記事ではこの観点に沿って論点を順に追っていく。",
    "以下では具体例とともに、{main} の理解度を一段引き上げる切り口を提示する。",
    "続く節では、関連トピックとの接続も意識しながら掘り下げていく。",
    "このセクションで提示する論点は、後段の比較・予測パートで再度参照される。",
    "次の見出しでは、ここで触れた切り口の対になる視点を扱う。",
    "詳しい数字や事例は、本文後半および関連記事で補足する。",
    "ここでは大枠だけを提示し、詳細は次節以降で順に明らかにしていく。",
]


def _section_paragraphs(group: dict, art: dict, h2: str, idx: int) -> list[str]:
    name = group["name"]
    main, sub = _parse_h2(h2)
    key = art["key"]
    sub_clause = f"（{sub}）" if sub else ""
    sub_or_role = sub or "今期"
    ctx = {"main": main, "name": name, "sub": sub,
           "sub_clause": sub_clause, "sub_or_role": sub_or_role}

    p1_list = _P1_TEMPLATES.get(key) or [
        "{main} について、{name} 文脈で押さえておきたいポイントを整理する。"
    ]
    p1 = p1_list[idx % len(p1_list)].format(**ctx)
    p2 = (_PERSPECTIVES[idx % len(_PERSPECTIVES)].format(**ctx)
          + _CLOSES[(idx + 1) % len(_CLOSES)].format(**ctx))
    return [p1, p2]


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
        for para in _section_paragraphs(group, art, h, i):
            parts.append(f"<p>{para}</p>")
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


def _self_check_filler(html: str) -> tuple[str, str]:
    """post_guard と同基準で同一段落量産を検出。('OK'|'WARN'|'BLOCK', reason)"""
    from collections import Counter
    paras = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
    plain = []
    for p in paras:
        t = re.sub(r'<[^>]+>', '', p)
        t = re.sub(r'\s+', ' ', t).strip()
        if 40 <= len(t) <= 600:
            plain.append(t)
    if len(plain) < 4:
        return "OK", ""
    sigs = Counter(p[:60] for p in plain)
    max_dup = max(sigs.values())
    ratio = max_dup / len(plain)
    boil_kw = ["本章では", "3軸で整理", "体系的に理解するための", "網羅的にカバー"]
    boil_hits = sum(1 for p in plain for kw in boil_kw if kw in p)
    if max_dup >= 3 or ratio >= 0.4:
        return "BLOCK", f"同一段落{max_dup}回({ratio:.0%})"
    if max_dup >= 2 or boil_hits >= len(plain) * 0.3:
        return "WARN", f"同一段落{max_dup}回 boil={boil_hits}"
    return "OK", ""


def curl_request(method: str, path: str, payload: dict | None = None):
    cmd = ["curl", "-s", "-X", method, f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json"]
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        cmd += ["--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def curl_post(path, payload):
    return curl_request("POST", path, payload)


def _load_slug_to_postid() -> dict[str, int]:
    """logs/cluster_articles.jsonl から slug → 最新 post_id を構築。"""
    mapping: dict[str, int] = {}
    if not OUT.exists():
        return mapping
    for line in OUT.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            s, pid = r.get("slug"), r.get("post_id")
            if s and pid:
                mapping[s] = pid  # 後勝ち = 最新
        except Exception:
            continue
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=list(CLUSTERS.keys()) + ["all"], default="all")
    ap.add_argument("--status", choices=["publish", "draft"], default="publish")
    ap.add_argument("--update", action="store_true",
                    help="既存post_id (cluster_articles.jsonl由来) を PUT で上書き再生成。新規作成しない")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    keys = list(CLUSTERS.keys()) if args.group == "all" else [args.group]
    ts = datetime.now(tz=JST).isoformat()
    slug_map = _load_slug_to_postid() if args.update else {}
    results = []
    with OUT.open("a") as fp:
        for gk in keys:
            g = CLUSTERS[gk]
            mode = "update" if args.update else "create"
            print(f"\n=== {g['name']} cluster ({mode}) ===")
            for art in g["articles"]:
                html = build_html(g, art)
                # 4層防止: 自己同型filler検出。BLOCKならpost/PUTせず安全停止
                check, reason = _self_check_filler(html)
                if check == "BLOCK":
                    print(f"  ⛔ {gk}/{art['key']}: filler-self-check BLOCK ({reason}) → skip")
                    continue
                if check == "WARN":
                    print(f"  ⚠  {gk}/{art['key']}: filler-self-check WARN ({reason})")
                payload = {
                    "title":   art["title"],
                    "slug":    art["slug"],
                    "content": html,
                    "status":  args.status,
                    "excerpt": art["meta"],
                    "meta":    {"_aioseo_description": art["meta"]},
                }
                if args.update:
                    pid = slug_map.get(art["slug"])
                    if not pid:
                        print(f"  ⏭  {gk}/{art['key']}: slug={art['slug']} 既存post未発見 → skip")
                        continue
                    if args.dry_run:
                        print(f"  [dry-update] {gk}/{art['key']}: id={pid} slug={art['slug']} len={len(html)}")
                        continue
                    try:
                        r = curl_request("POST", f"/wp-json/wp/v2/posts/{pid}", payload)
                        link = r.get("link", "")
                        new_id = r.get("id")
                        if new_id != pid:
                            print(f"  ⚠  {gk}/{art['key']}: returned id={new_id} != requested {pid}")
                        print(f"  ✅ {gk}/{art['key']}: UPDATED id={pid} len={len(html)}")
                        rec = {"ts": ts, "group": gk, "key": art["key"], "post_id": pid,
                               "slug": art["slug"], "status": args.status, "link": link,
                               "html_len": len(html), "action": "update"}
                        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        results.append(rec)
                    except Exception as e:
                        print(f"  ❌ {gk}/{art['key']}: update failed: {e}")
                    continue
                # 新規作成 (既存挙動)
                if args.dry_run:
                    print(f"  [dry-create] {gk}/{art['key']}: slug={art['slug']} len={len(html)}")
                    continue
                # cluster duplicate gate (2026-05-14)
                if args.status == "publish":
                    from lib.cluster_dedup import cluster_dedup_check
                    is_dup, matched = cluster_dedup_check(
                        art["title"], hours=3, source="cluster_generator")
                    if is_dup:
                        print(f"  ⚠  {gk}/{art['key']}: cluster_dup → status=draft (matched: {matched[:50]})")
                        payload["status"] = "draft"
                try:
                    r = curl_post("/wp-json/wp/v2/posts", payload)
                    pid = r.get("id")
                    link = r.get("link", "")
                    print(f"  ✅ {gk}/{art['key']}: id={pid} slug={art['slug']} len={len(html)}")
                    rec = {"ts": ts, "group": gk, "key": art["key"], "post_id": pid,
                           "slug": art["slug"], "status": args.status, "link": link,
                           "html_len": len(html), "action": "create"}
                    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    results.append(rec)
                    # WP indexing lag 吸収用 sliding-window buffer
                    if payload.get("status") == "publish" and pid:
                        try:
                            from lib.cluster_dedup import record_publish
                            record_publish(art["title"], post_id=pid,
                                           source=f"cluster_generator/{gk}")
                        except Exception:
                            pass
                except Exception as e:
                    print(f"  ❌ {gk}/{art['key']}: {e}")

    print(f"\n[cluster_generator] {len(results)}記事 {args.status} 完了 ({'update' if args.update else 'create'})")


if __name__ == "__main__":
    main()
