"""N-2 ユニットテスト: lib/popup_event_fetcher.py

K-POP キーワード判定 + popup/event 分類のロジックを検証。
"""
import pytest
from lib.popup_event_fetcher import (
    matches_kpop,
    classify,
    detect_korea_genre,
    matches_korea,
    extract_prtimes_event_info,
    extract_prtimes_image,
)


class TestMatchesKpop:
    def test_bts_basic_match(self):
        assert matches_kpop("BTS新作グッズ発売") == "BTS"

    def test_blackpink_substring(self):
        assert matches_kpop("BLACKPINK ポップアップストア東京") == "BLACKPINK"

    def test_newjeans_case_insensitive(self):
        assert matches_kpop("NewJeans ファンミーティング") in ("NewJeans", "Newjeans", "NEWJEANS")

    def test_japanese_kanji_match(self):
        assert matches_kpop("防弾少年団のカフェオープン") == "防弾少年団"

    def test_korean_hangul_match(self):
        assert matches_kpop("방탄소년단 콘서트") == "방탄소년단"

    def test_no_match_returns_none(self):
        assert matches_kpop("Beatles 来日コンサート") is None

    def test_empty_string(self):
        assert matches_kpop("") is None

    def test_kpop_word_match(self):
        assert matches_kpop("K-POP特集ライブ") is not None


class TestWordBoundary:
    """境界マッチ: 過去のインシデント (V → GRAPEVINE 等) の再発防止"""

    def test_v_not_match_grapevine(self):
        # "V" は WORD_BOUND_KEYWORDS から除外済み、誤マッチしないことを確認
        assert matches_kpop("GRAPEVINE 来日公演") is None

    def test_lisa_lowercase_not_match_lisa_jp_artist(self):
        # "Lisa" は別アーティストなので、SUBSTRING_KEYWORDS に含めない
        # ("リサ" も SUBSTRING_KEYWORDS から除外済み)
        assert matches_kpop("LiSA SOLO LIVE") is None

    def test_rm_not_in_word_bound(self):
        # 短語 RM は除外、誤マッチを起こす可能性ある単語が含まれていてもマッチしない
        assert matches_kpop("RMコーヒー店舗") is None

    # --- タスク#25(PRTIMES sitemap-news 切替)で発覚した katakana 衝突の回帰防止 ---
    def test_riize_kana_not_match_common_words(self):
        # "ライズ" は デジライズ / Tales of ARISE 等と衝突するため除外済み
        assert matches_kpop("デジライズ 生成AIリスキリング支援を開始") is None
        assert matches_kpop("Tales of ARISE Switch版 発売") is None

    def test_aespa_kana_not_match_mall(self):
        # "エスパ" は エスパル仙台(商業施設)と衝突するため除外済み
        assert matches_kpop("エスパル仙台にクレープ店オープン") is None

    def test_seventeen_kana_not_match_icecream(self):
        # "セブンティーン" は セブンティーンアイス と衝突するため除外済み
        assert matches_kpop("セブンティーンアイス ホワイトサワー新発売") is None

    def test_seventeen_english_still_matches(self):
        # 英表記 SEVENTEEN は引き続きマッチする(取りこぼし防止)
        assert matches_kpop("SEVENTEEN コラボカフェ 渋谷で開催") == "SEVENTEEN"


class TestClassifyTitleGate:
    """PRTIMES keywords 由来の誤分類(BookLive→LIVE 等)の回帰防止。

    parse_prtimes は classify を title のみに適用する設計。classify 自体は
    渡された文字列の substring を見るので、keywords 文字列を直接渡すと
    ブランド名で誤マッチする —— それを「title だけに使う」ことで回避している。
    ここでは classify がブランド名で event を返してしまう既知の挙動を明示し、
    title-only ゲートの必要性をドキュメント化する。
    """

    def test_booklive_substring_triggers_event(self):
        # keywords に "BookLive" が入ると LIVE が引っかかる(=keywords では分類しない理由)
        assert classify("BookLive,ブックライブ,D'ICON,TWS") == "event"

    def test_descriptive_title_is_safe(self):
        # 一方、説明的な title では誤分類しない
        assert classify("『D’ICON VOLUME N°34 TWS』の日本独占予約販売をスタート") is None


class TestKoreaGenre:
    """タスク#26: K-POP 限定 → 韓国関連全般(5ジャンル)拡大の判定。

    各ジャンル HIT(韓国シグナル内包の複合語 or 確実な固有名)と、
    一般語単独(韓国シグナル無し)の DROP を検証する
    ([[feedback_guard_false_positives]] 誤マッチ回避)。
    """

    # --- ② 韓国ドラマ・俳優・映画 ---
    def test_drama_compound_hit(self):
        g = detect_korea_genre("韓国ドラマ「新入社員カン会長」日本初配信")
        assert g is not None and g[0] == "drama"

    def test_kdrama_hit(self):
        assert detect_korea_genre("Kドラマ特集フェア開催")[0] == "drama"

    def test_drama_proper_noun_hit(self):
        assert detect_korea_genre("「愛の不時着」コラボカフェ開催")[0] == "drama"

    def test_drama_bare_word_drop(self):
        # 「ドラマ」単独は韓国シグナルが無いので拾わない
        assert detect_korea_genre("人気ドラマ原作の舞台化決定") is None
        assert detect_korea_genre("国内ドラマフェア 期間限定開催") is None

    # --- ③ 韓国コスメ・ビューティー ---
    def test_beauty_compound_hit(self):
        assert detect_korea_genre("韓国コスメのポップアップが渋谷に登場")[0] == "beauty"

    def test_kbeauty_hit(self):
        assert detect_korea_genre("K-beauty 体験型イベント開催")[0] == "beauty"

    def test_beauty_brand_hit(self):
        # 実在の distinctive ブランド名
        assert detect_korea_genre("MEDIHEAL 期間限定ストア")[0] == "beauty"
        assert detect_korea_genre("ロムアンド ポップアップ")[0] == "beauty"

    def test_beauty_bare_word_drop(self):
        # 「コスメ」単独・日本の無関係コスメは拾わない
        assert detect_korea_genre("人気コスメブランドの新作発表会") is None
        assert detect_korea_genre("国産コスメのポップアップストア") is None

    # --- ④ 韓国フード・グルメ ---
    def test_food_compound_hit(self):
        assert detect_korea_genre("韓国グルメ「冷やしスンドゥブ」を提案")[0] == "food"

    def test_kfood_hit(self):
        assert detect_korea_genre("Kフードフェス開催")[0] == "food"

    def test_food_bare_word_drop(self):
        # 「グルメ」「カフェ」単独は拾わない
        assert detect_korea_genre("全国ご当地グルメフェア") is None
        assert detect_korea_genre("話題のコラボカフェがオープン") is None

    # --- ⑤ 韓国ファッション ---
    def test_fashion_compound_hit(self):
        assert detect_korea_genre("韓国ファッションのポップアップ開催")[0] == "fashion"

    def test_kfashion_hit(self):
        assert detect_korea_genre("Kファッション展示会")[0] == "fashion"

    def test_fashion_bare_word_drop(self):
        # 「ファッション」単独は拾わない
        assert detect_korea_genre("レディースファッション 春の新作") is None

    # --- 「韓国」を含むだけの無関係リリースは拾わない ---
    def test_bare_korea_no_genre_drop(self):
        # 韓国旅行・韓国進出など、5ジャンルのいずれにも当たらない「韓国」単独文脈
        assert detect_korea_genre("韓国旅行のフォトウェディング受付開始") is None
        assert detect_korea_genre("韓国・米国・台湾、一括配信インフラ刷新") is None

    def test_empty(self):
        assert detect_korea_genre("") is None
        assert detect_korea_genre("", "") is None

    # --- keywords も対象にする(複数引数 OR) ---
    def test_keywords_field_hit(self):
        # title に韓国シグナルが無くても keywords 側で拾える
        assert detect_korea_genre("渋谷で体験型イベント開催", "韓国コスメ,ポップアップ")[0] == "beauty"


class TestMatchesKorea:
    """matches_korea: K-POP 優先 + 4ジャンルの統合判定。既存 K-POP 判定を壊さない。"""

    def test_kpop_priority(self):
        # K-POP がヒットする場合は ("kpop", kw) を返す
        g, kw = matches_korea("BTS ポップアップストア")
        assert g == "kpop" and kw == "BTS"

    def test_kpop_via_keywords(self):
        g, kw = matches_korea("グッズ販売開始", "K-POP,BLACKPINK,popup")
        assert g == "kpop"

    def test_drama_fallback(self):
        # 注: 「韓流」単独は既存 K-POP キーワード(SUBSTRING_KEYWORDS)なので
        # K-POP 優先で kpop になる。drama 専用は「韓国ドラマ」等で判定する。
        g, kw = matches_korea("韓国ドラマ「カン会長」展 開催")
        assert g == "drama"

    def test_beauty_fallback(self):
        g, kw = matches_korea("韓国コスメイベント", "K-Beauty,コスメ")
        assert g == "beauty"

    def test_unrelated_none(self):
        assert matches_korea("国産日本酒フェア") is None
        assert matches_korea("Beatles 来日コンサート") is None

    def test_kpop_existing_behavior_unchanged(self):
        # 既存 matches_kpop の挙動は維持される(誤マッチ語は依然 None)
        assert matches_korea("GRAPEVINE 来日公演") is None


class TestExtractPrtimesEventInfo:
    """タスク#27: PRTIMES 本文 HTML からの開催情報抽出。

    実データ(コスきゅん vol.3 リリース)の「■ 開催概要」ブロック構造を再現し、
    期間/会場/営業時間を正しく拾うこと、prose/会社概要を誤抽出しないことを検証。
    """

    # 実リリースの開催概要ブロック相当(label 行 → 値行)
    STRUCTURED = (
        "<h2>「コスきゅん vol.3」開催概要</h2>"
        "<p>・日時<br>・5/22（金）〜5/24（日） 11:00～19:00<br>"
        "※14:00〜15:00 CLOSE</p>"
        "<p>・会場<br>・LAIDOUT SHIBUYA（東京都渋谷区渋谷1-15-12）</p>"
        "<p>・入場方法<br>初日インフルエンサーのみ招待制</p>"
    )

    def test_structured_period_venue_hours(self):
        info = extract_prtimes_event_info(self.STRUCTURED)
        assert info.get("開催期間", "").startswith("5/22")
        assert "LAIDOUT SHIBUYA" in info.get("会場", "")
        # 営業時間は period 内の時刻レンジから補完される
        assert "11:00" in info.get("営業時間", "")

    def test_prose_venue_not_extracted(self):
        # 「会場は…」のような prose 文を会場値にしない([[feedback_guard_false_positives]])
        prose = "<p>会場は、日本初上陸の体験を求める多くの来場者で連日賑わいました。</p>"
        info = extract_prtimes_event_info(prose)
        assert "会場" not in info

    def test_company_address_not_extracted_as_venue(self):
        # 会社概要の「所在地」は会場/住所として拾わない(発行元 HQ の誤認防止)
        company = "<p>所在地：大阪府大阪市中央区北浜2丁目2番22号</p>"
        info = extract_prtimes_event_info(company)
        assert info == {} or "住所" not in info

    def test_period_requires_date_like_value(self):
        # 「日時」ラベルでも値が日付らしくなければ period にしない
        no_date = "<p>・日時<br>・調整中です</p>"
        info = extract_prtimes_event_info(no_date)
        assert "開催期間" not in info

    def test_empty_text_returns_empty(self):
        assert extract_prtimes_event_info("") == {}

    def test_recap_no_overview_returns_empty(self):
        # 開催概要ブロックの無い recap 系本文は何も抽出しない(捏造禁止)
        recap = (
            "<p>当社は韓国Leferi主催のポップアップを支援しました。"
            "イベント開催期間（計12日間）における累計来場者数は約2.1万人でした。</p>"
        )
        info = extract_prtimes_event_info(recap)
        # 「開催期間（計12日間）」は prose 中であり日付が無いので period にならない
        assert "開催期間" not in info or info["開催期間"] != "（計12日間）"


class TestExtractPrtimesImage:
    """PRTIMES 詳細ページの og:image をサムネ URL として抽出。

    PRTIMES popup signal は従来 thumbnail_url を持たず、後段の
    download_and_attach_thumbnail が呼ばれず featured 画像が欠落していた
    (2026-06-17 発覚)。og:image を拾い、HTML エンティティを解いて返す。
    """

    def test_extracts_og_image_and_unescapes(self):
        html = (
            '<head><meta property="og:image" '
            'content="https://prcdn.freetls.fastly.net/release_image/'
            '77024/206/x.jpg?format=jpeg&amp;auto=webp&amp;width=2400"></head>'
        )
        url = extract_prtimes_image(html)
        assert url == (
            "https://prcdn.freetls.fastly.net/release_image/77024/206/"
            "x.jpg?format=jpeg&auto=webp&width=2400"
        )

    def test_content_before_property_order(self):
        html = (
            '<meta content="https://prcdn.example/img.jpg" '
            'property="og:image">'
        )
        assert extract_prtimes_image(html) == "https://prcdn.example/img.jpg"

    def test_no_og_image_returns_empty(self):
        assert extract_prtimes_image("<head><title>x</title></head>") == ""

    def test_empty_html_returns_empty(self):
        assert extract_prtimes_image("") == ""


class TestClassify:
    def test_popup_keyword(self):
        assert classify("BTS ポップアップストア開催") == "popup"

    def test_event_keyword(self):
        assert classify("BLACKPINK 来日コンサート") == "event"

    def test_popup_priority_over_event(self):
        assert classify("NewJeans ポップアップ + コンサート") == "popup"

    def test_no_keyword(self):
        assert classify("BTS新作グッズ通販") is None

    def test_english_keyword(self):
        assert classify("TWICE FAN MEETING") == "event"

    def test_empty_string(self):
        assert classify("") is None
