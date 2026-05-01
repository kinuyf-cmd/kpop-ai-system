# 累積教訓 (2026-05-01 現在、130項目)

## 一般教訓
1. 実装完了≠完了 (本番動作+実データ検証必須)
2. テスト成功で本番反映放置しない
3. 心理優先≠システム優先 (オーナー判定依頼禁止)

## インフラ教訓
4. ビルド成功≠本番反映 (GA4 Realtime必須)
5. メディア機能欠如を常に点検
6. API key依存の設計脆弱性を意識

## データ品質
7. 雑な調査で「未設定」判定しない
8. 公開後継続監視を怠らない
9. 集計前提検証せず数字を信じない

## 開発プロセス
10. Phase名定義変更禁止
11. git HEADの既存実装確認せず上書きしない
12. オーナーの時間を奪わない (憲法第7条)

## コンテンツ品質
13. 考察記事タイトル「の全貌/徹底解剖/の真相/衝撃の」等はHARD_FAIL
14. サムネ品質自動検知(_check_thumbnail_quality)+DALL-E 3 fallback

## 参照
- 機械可読ルール: config/latest_rules.json (毎朝06:00更新)
- AI社員向けプロンプト注入: lib/load_latest_rules.py


## 監査教訓 (2026-04-24 23:11)

- **x_missing**: 16件
- **slug_encoded**: 8件
- **title_long**: 7件
- **gsc_missing**: 4件
- **no_thumbnail**: 4件

## 教訓 #17 (2026-04-27) 英語1文のみの記事が公開される品質事故

**事象**: /blackpink-jennie-interview-hatsugen/ (post_id=4068) で英語1文のみの本文で記事公開

**原因**:
- unified_publisher に本文品質チェックが一切なかった
- 翻訳失敗時にソース記事の英語タイトルがそのまま本文として流用された

**予防策**:
1. unified_publisher に本文品質ゲート追加（200字以上 + 日本語比率30%以上で投稿許可）
2. audit_publisher に同条件の厳格チェック + 即draft化（50字未満 or 日本語10%未満）
3. latest_rules.json に quality_gates セクション新設


## 監査教訓 (2026-04-25 00:00)

- **gsc_missing**: 4件
- **meta_short**: 2件
- **no_thumbnail**: 1件
- **x_missing**: 1件


## 監査教訓 (2026-04-25 06:00)

- **no_thumbnail**: 4件
- **meta_short**: 2件


## 監査教訓 (2026-04-25 12:01)

- **gsc_missing**: 2件
- **x_missing**: 2件
- **title_long**: 1件


## 教訓 #21 (2026-04-28) 速報の価値=速度、文字数縛りは速度を殺す

**事象**: 速報も一般記事と同じ200字下限で運用していた
- 速報の本質的価値は「速さ」にある (公式発表後5分以内が理想)
- 200字書こうとすると翻訳待ち+加筆で30分遅延 → 速報価値半減

**対策**: 2段階公開モデル
- Stage 1 (速報、即時公開): 150字以上、5W1H骨子
- Stage 2 (2時間後加筆): 600字以上、背景+関連、GPT-4o-miniで自動加筆
- `_breaking_stage` WP custom fieldで段階管理

## 教訓 #22 (2026-04-28) 翻訳の自然さは専門プロンプトで大幅改善可能

**事象**: GPT-4o-mini汎用プロンプトで韓国語→日本語翻訳すると直訳的
- 「밝혔다」→「明らかにした」が連発、不自然
- アーティスト名のカタカナ表記が混在

**対策**: K-POP専門プロンプト (Lv1)
- アーティスト名英語表記の徹底 (뉴진스→NewJeans等)
- 専門用語統一 (컴백→カムバック等)
- 文末バリエーション指示
- コスト変わらず、自然度向上


## 監査教訓 (2026-04-25 18:00)

- **x_missing**: 8件
- **gsc_missing**: 8件
- **meta_short**: 6件
- **body_short**: 1件


## 教訓 #23 (2026-04-26) feedback_loop の検知windowは余裕を持つ

**事象**: post_audit_feedback_loop が10-20分window固定だったため、4/26投稿6件を全件取りこぼした
- cron起動タイミング(10分・40分)と投稿タイミングが合わず、20分超過で検知漏れ

**対策**: windowを5-60分に拡大。cron周期との不一致を許容する設計にする

## 教訓 #24 (2026-04-26) 通常記事はGSC/X配信パイプラインが未接続

**事象**: popup 20件はGSC+X配信されたが、通常記事6件は全件未配信
- popup_publish_enricherはpopup専用、通常記事を配信するパイプラインが存在しない

**対策**: unified_publisher or 専用enricher で通常記事のGSC+X配信を自動化する

## 教訓 #26 (2026-04-26) GPT生成テンプレートのラベル露出は正規表現+パイプライン処理で封じる

**事象**: 「リード文：」ラベルが80件の記事本文冒頭に露出していた
- GPTがセクション識別子（リード文:, 導入文:, セクション1: 等）をそのまま出力
- LLM校閲でも検出困難（形態素一致で自然な日本語に見える）
- 441件中80件(18%)に影響

**対策**: 3層防御
1. `lib/text_sanitizer.py` の `strip_template_labels()` で投稿前にラベル除去
2. unified_publisher / feature_article_generator / popup_publisher に組み込み
3. GPTプロンプトに「ラベルを含めない」明示的指示を追加

## 教訓 #25 (2026-04-26) LLM校閲は恒常化してこそ価値がある

**事象**: 手動実行のLLM校閲で critical 0 / high 2 を検出 → 恒常パイプライン(llm_proofreader)として組み込み
- 4時間毎cron + audit_state.jsonlへのキュー連携で、検出→修正の自動サイクルを実現

**対策**: pipeline/llm_proofreader.py を4時間毎cronで運用、full_audit_engine に項目17として統合

## 教訓 #27 (2026-04-26) 教訓蓄積だけでは同じエラーが繰り返される

**事象**: agent_lessonsに教訓を蓄積しても、GPT生成プロンプトに注入されなければ次回も同じ失敗が発生
- text_casual_question が9回、slug_encoded が91回と繰り返し検出

**対策**: lib/agent_learning_loop.py の inject_lessons_to_prompt() で教訓→プロンプト自動注入を実装。4つの生成パイプラインに組込済

## 教訓 #28 (2026-04-26) 通常記事のGSC配信パイプラインは既存enricherのcron化で解決

**事象**: post_publish_enricher.py にGSC通知機能があったがcron未登録で稼働していなかった
- 通常記事18件分のGSC通知が未送信状態だった

**対策**: post_publish_enricher を毎時50分cronに登録。既存機能の活用で新規開発不要

## 教訓 #29 (2026-04-27) cron稼働=機能稼働ではない

**事象**: auto_comeback_article のNameErrorが24h検知されず、cron起動記録のみで正常と誤判断
**対策**: pipeline_health_monitor (毎時20分) でNameError/ImportError等を自動検知

## 教訓 #30 (2026-04-27) draft滞留はKPI直撃

**事象**: 品質ゲートでdraftに落とされた30記事が review待ちで放置 → 日次KPI未達
**対策**: high<3かつ200字以上の記事は自動publish。それ以外はrewrite_worker即時投入

## 教訓 #31 (2026-04-27) 個別社員レベルの評価が必要

**事象**: 部門ログでは正常に見えても、個別社員レベルでは未稼働や学習停滞がある
**対策**: 人事部(14部門目)を新設。個別社員ロスタ + 毎日23:30の自動評価 + 緊急介入判定

## 教訓 #32 (2026-04-27) 組織は役職名+コード名の二層管理

**事象**: 部門名(①〜⑭)とポケモン内部コード(デオキシス等)が別系統で管理されていた
**対策**: staff_roster.jsonで両方併記。pipeline→staff_idマッピングで個別社員トレース可能に

#50 (2026-04-27): サムネ生成は make_thumbnail_v6.py (compose_v6 + 実写真優先 + テキストゼロ + 1200x675) 必須。post_thumbnail_generator.py が DALL-E+PIL直描画で1280x720サムネを生成していた事故。compose_v6の出力も1200x630(OG標準)→1200x675(16:9)に修正。DALL-E fallbackパスもcompose_v6経由に統一。生成後にサイズ検証ゲート追加。14件の非準拠サムネを全件再生成。

## 教訓 #33 (2026-04-27) .env改行欠落でAPI停止

**事象**: AMAZON_ASSOCIATE_TAG行末の改行欠落でOPENAI_API_KEYが結合、全パイプライン停止
**対策**: 新規key追加時は前後改行を必ず確認。.envのlint/検証スクリプト検討

## 教訓 #34 (2026-04-27) YouTube公式サムネの動的取得

**改修**: resolve_youtube に prefer=latest/popular パラメータ追加。YouTube Data API v3で公式チャネルから最新MV or 高再生MVのサムネを自動取得
**キャッシュ**: channel_idはofficial_accounts.jsonに書き戻し、以降はAPI呼出不要

## 教訓 #35 (2026-04-27) ファクトチェックなしのGPT単独生成は事故の元

**事象**: ITZY記事でGPTが2024年の情報を「最新ニュース」として生成、そのまま公開された
**直接原因**: ソース(シグナル/ニュースURL)なしでGPTに直接書かせた
**構造原因**: unified_publisherにファクトチェックゲートがなかった
**対策**:
1. lib/fact_checker.py 新設 (ソース必須+日付整合性チェック)
2. unified_publisher に BLOCK ゲート追加 (ソースなし or 2年古い → BLOCK)
3. full_audit_engine に stale_content_date チェック追加
4. 「最新ニュース」記事は必ずWeb検索で実ソースを取得してから執筆

## 教訓 #36 (2026-04-27) GPT出力のTITLE:プレフィックス混入

**事象**: TWICE/BIGBANG記事の本文冒頭に「TITLE: タイトル文字列」が表示された
**原因**: GPT出力のparse処理が1パターンのみ想定、フォーマット揺れに対応できず
**対策**: text_sanitizer.py に TITLE: 除去パターン追加。GPT出力は不安定な前提で多重防御

## 教訓 #37 (2026-04-27) ハングルをDALL-Eに渡すと豆腐文字化

**事象**: ティニーピン(더티니핑)のサムネが黒背景+豆腐文字
**原因**: ハングルタイトルがDALL-Eプロンプトに直接渡され、文字レンダリング失敗
**対策**: make_thumbnail_v6のプロンプトは英語で構成。TEXT ZERO原則の厳守

## 教訓 #38 (2026-04-27) 既存MV画像のDALL-E上書き事故

**事象**: ITZY記事のYouTube MVサムネがDALL-E生成画像に上書きされた
**原因**: 記事修正時にregenerate_for_post()が呼ばれ、resolve_youtube失敗→DALL-E fallback発動
**対策**: 既存v6 MV画像がある場合はスキップする保護ロジックを追加。本文修正のみの場合はサムネ再生成を呼ばない

## 教訓 #39 (2026-04-27) popup OGP画像がデフォルト画像になる事故

**事象**: 全popup記事のXシェア時にog-default.png (サイトデフォルト) が表示された
**根本原因**: popup/[city]/[id]/page.tsx に generateMetadata が未実装。og:image を設定するコードが存在しなかった
**対策**: generateMetadata を追加し、_embedded["wp:featuredmedia"][0].source_url を og:image に設定
**再発防止**: 新規ページ作成時のチェックリストに「generateMetadata + og:image設定」を必須項目として追加

## 教訓 #40 (2026-04-27) サムネ保護は全経路に必要

**事象**: ITZYのMV画像が3回目のDALL-E上書きされた
**根本原因**: regenerate_for_postに保護を追加したが、cronが使う generate_and_attach には保護がなかった。コードパスが2つ存在
**対策**: generate_and_attach にも同じ保護ロジックを追加。「既存ファイル名にv6_mv_またはv6_kpop_thumbが含まれ、dalleが含まれなければスキップ」
**教訓**: 保護ロジックは1箇所ではなく、対象リソースにアクセスする全経路に入れる

## 教訓 #41 (2026-04-27) サムネ更新は1つのゲート関数に集約する

**事象**: ITZYのMV画像が3回DALLEに上書きされた。保護ロジックを追加しても別の経路から上書きされた
**根本原因**: featured_media を書き換える経路が5箇所に分散していた (pipeline/lib/tools各所)
**対策**: lib/thumbnail_guard.py に safe_update_featured_media() を新設。全5経路をこの関数経由に集約
  - is_protected() でMV画像を判定 (v6_mv_ or v6_kpop_thumb でdalle含まない)
  - 保護対象なら force=True でない限りBLOCK
  - 全操作を thumbnail_guard.log にログ記録
**原則**: リソース保護は「個別経路に保護を追加」ではなく「1つのゲートに集約して全経路を通す」設計にする

## 教訓 #42 (2026-04-27) 新品質基準の遡及適用

**事象**: Hearts2Hearts記事2件がファクトチェック未通過・サムネなし・総監査未実行のまま公開されていた
**根本原因**: fact_checker/thumbnail_guard は新規投稿のみゲート。既存記事には遡及適用されない
**対策**:
1. full_audit_runner の定期実行で既存記事もfact_check項目を評価
2. 公開直後の「サムネ+OGP+ソース」3点セット確認をX投稿前に義務化
3. unified_publisher以外の経路で作成された記事をcron監査で遡及チェック
**原則**: 品質基準は「今後の記事」だけでなく「既存記事」にも段階的に適用する仕組みを持つ

## 教訓 #43 (2026-04-27) 記事作成時のアーティストカテゴリ漏れ

**事象**: ITZY/TWICE/BIGBANG/fromis_9の記事がアーティストページに表示されなかった
**原因**: 記事作成時にニュースカテゴリ(id=2)のみ設定し、アーティスト個別カテゴリ(parent=26)を設定し忘れた
**対策**: 記事作成フローにアーティストカテゴリ自動検出+設定を追加。unified_publisherでアーティスト名→カテゴリID自動マッピング

#53 (2026-04-27): AI社員独立人格化はpersona prompt + 教訓注入。役員/部門長/一般社員の階層別、社員間メッセージング対応
#53 (2026-04-27): AI社員独立人格化はpersona prompt + 教訓注入。役員/部門長/一般社員の階層別、社員間メッセージング対応
#54 (2026-04-27): 全社員独立人格化は部門長応答だけでは不十分。一般社員45名が発言機会を持つには (a)部門内最適選択 (b)全部員朝会終礼 (c)雑談pipeline が必要
#55 (2026-04-27): Discord webhookはチャネルあたり10件上限。15名以上の部門はチャネル分割必須
#56 (2026-04-27): Notion組織図を唯一の正規ソースとし、システム実装前に必ず確認する。役員は部署長兼務しない。

#57 (2026-04-28): 月替わり時の前月25日までに翌月情報一括登録ルール

#58 (2026-04-28): スクレイパーは複数ソース冗長化+定期動作確認必須。Naver React化でRSS方式に全面切替

#59 (2026-04-28): v6サムネQUEUE_REVIEW画像は公開禁止。DALL-E代替+目視必須
#60 (2026-04-28): .envに変数名なしの行があるとshell source失敗→X投稿全滅
#61 (2026-04-28): GPT生成HTMLにCSS/style混入する。サニタイズパイプライン必須
#62 (2026-04-28): gpt-4o-miniは長文出力不可。3000字超はgpt-4o+明示的指定
#64 (2026-04-27): pipeline作成 → 動作確��� → cron登録 → ログ確認 の4ステップ完遂義務。cron未登録で44h沈黙の重大事故
#65 (2026-04-27): pipeline_health_monitor にcheck_cron_aliveness追加。ログ沈黙でCRITICAL検知
#66 (2026-04-27): 朝会で必ず全pipeline稼働状況を報告。「記事数」ではなく「自動化の稼働」を見る
#67 (2026-04-27): 完成宣言前にcron_audit + health_monitor必須実行

#69 (2026-04-27): 学習は技術+プロセス+組織知+朝会の4軸で構造化、Claude運用憲法 v2制定

#70 (2026-04-27): signal供給3ソース冗長化完成 (RSS+X+YouTube)、憲法第6条達成
#71 (2026-04-27): サムネなし公開の根本原因修正 — unified_publisher全記事DALL-Eフォールバック+v6 ai_promptパスDALL-E即時生成+日次��限20→50

#71 (2026-04-28夜): 完成宣言は API+目視+多次元判定の3条件必須
#72 (2026-04-28夜): 既存記事修復はpost_id維持で内容上書きしてSEO評価維持
#73 (2026-04-28夜): Markdownコードブロックマーカー除去をスクレイパー/publisherで二重防御
#74 (2026-04-27): HTMLサイズ肥大化監視でnginx 413エラー予防
#75 (2026-04-27): registry網羅性は双方向監査必須

#78 (2026-04-28夜): registry-cron名寄せはaliases/module照合で吸収、重複エントリは統合

#81 (2026-04-29): 月別Topical Authority戦略 - 中核1本+個別5本+双方向リンク+GSC先行申請

## 監査教訓 (2026-04-29 総監査)

32件監査、TOP10 issue根本原因特定+再発防止実装:

#82 (2026-04-29): アーティストカテゴリ自動付与 — unified_publisherにartist_category_map.json照合を追加。_detect_category_slugは基本カテゴリのみでアーティスト個別カテゴリを付与していなかった
#83 (2026-04-29): meta_descフォールバック — body_html[:500]では短い速報記事でmeta_desc<80字に。[:1000]→[:2000]→固定文テンプレートの3段フォールバック実装
#84 (2026-04-29): タイトル42字厳守 — breaking prefix付加後に[:50]で切っていたが監査基準42字。[:42]に統一
#85 (2026-04-29): popup slug ASCII化 — popup_publisherがslug未指定→WPが日本語URLエンコード。generate_slug()呼び出し追加
#86 (2026-04-29): sanitize_gpt_html全パイプライン適用 — unified_publisher+popup_publisherの本文にsanitize_gpt_htmlを適用。unclosed_p/casual表現/文字重複を投稿前に修正
#87 (2026-04-29): unclosed_p検出閾値撤廃 — full_audit_engineの閾値>2→>0に。1-2個のunclosed_pも検出対象に。text_sanitizerは閾値なしで常に修正
#88 (2026-04-29): casual表現パターン拡張 — いかがでしょうか/でしたか/ですかの全バリエーション対応。sanitizer+audit両方で統一
#89 (2026-04-29): 予防コード修正だけでは不十分、既存記事の実データ修正も必須 — 25件slug/cat/meta/content修正 + 17件内部リンク挿入 + popup#5556サムネ復旧
#90 (2026-04-29): internal_links.pyが存在しながらパイプライン未統合だった — unified_publisher + popup_publisherにinsert_internal_links()呼び出し追加。「モジュール作成≠統合完了」
#91 (2026-04-29): meta_descフォールバックはGPT再生成+固定テンプレートでは不十分 — 本文から最初の2段落を抽出する方式が確実(80字確保率100%)
#92 (2026-04-29): unclosed_pの1-2個差分はWP wpautopの仕様 — 閾値>2はmedium、1-2はlowに分離。text_sanitizerでは常に修正するが、監査ではWP側の自動挿入分を考慮
#93 (2026-04-29): popup#5556でMarkdownコードブロックマーカー(```html)がHTMLエンティティ化(&#8220;)で混入 — sanitize_gpt_htmlに加え、WPのHTMLエンティティ変換後のパターンも除去必要
#94 (2026-04-29朝): ログに残る旧SyntaxErrorとコード現状の乖離に注意。cron出力ログにはエラーが残るがコードは既に修正済みのケースがある。ログのタイムスタンプ(mtime)を必ず確認し、コード現状をpy_compile+手動実行で独立検証する
#95 (2026-04-29朝): cronでstdoutリダイレクト(>>)するスクリプトは必ずprint出力を含める。出力なし=ログmtime未更新=pipeline_health_monitorが永久沈黙報告する。4パイプラインに完了print追加で解決
#96 (2026-04-29): 速報プロンプト150-250字→400-600字+5W1H。付帯情報で膨れても本文品質を直接担保する設計に
#97 (2026-04-29): 「1ヶ月以内のイベント」→「近日開催のイベント」。UpcomingEvents.tsx修正+PM2 restart反映確認
#98 (2026-04-29): events_manual.json→frontend events.json同期パイプライン新設(event_calendar_refresh.py)+WP固定ページ(id=5854)+週1cron
#99 (2026-04-29): イベント自動収集はK-POP関連度フィルタ必須。artist_category_map照合+汎用タイトル除外の2層フィルタ。非K-POPイベント(GADORO/アニメタル等)混入防止
#100 (2026-04-29): イベント日付フィルタはdate_end(終了日)ベース。date_startだと開催中POP-UP除外。event_auto_collector+calendar_refresh+UpcomingEvents.tsx全て統一
#101 (2026-04-29): Next.jsフロントエンドの[slug]キャッチオールがrobots.txt/sitemap XMLを横取りしていた。public/robots.txt作成+nginx proxyルール追加で解決。新しい静的ファイル（ads.txt等）は必ずpublic/に配置すること
#102 (2026-04-29): AIOSEOサイトマップにpost_tag含まれていたがNext.jsでタグ→ホームリダイレクト済み。サイトマップとフロントエンドのルーティングが矛盾する設定を常にチェックすること
#103 (2026-04-29): 空カテゴリ（count=0）がnoindexなしで公開→薄いコンテンツ問題。カテゴリページにcount===0時の自動noindex追加。新カテゴリ作成時は記事投入まで自動的にnoindex
#104 (2026-04-29): site_health_check.pyを新設。robots.txt/sitemap整合性/空カテゴリ/空タグ/記事ステータスのインフラレベルSEO問題を定期検出

#105 (2026-04-29): イベントカレンダーUIはCSS Grid月別形式+カラー凡例+関連記事カード。popup CPTからも動的統合で5月39件表示
#106 (2026-04-29): WP固定ページにもfeatured_media(DALL-E生成)必須。OGP/SNS共有時のCTR向上
#107 (2026-04-29): generate_slug()のGPT失敗時フォールバックが空文字→WPがpost-NNNNを自動生成する致命バグ。validate_slug()+_fallback_slug()の2層防御で空slugを絶対に返さない設計に修正
#108 (2026-04-29): trash/draft蓄積はサイト品質を毀損する隠れた負債。毎日cron(site_health_check.py)で検出し0件維持。パイプラインエラー投稿はforce=trueで即完全削除
#109 (2026-04-29): 重複タイトル記事はWPがslugに-2を付加して別記事として黙って受理する。publish前に既存タイトル照合が必要。site_health_check.pyで定期検出
#110 (2026-04-29): 管理用ページ(dashboard等)はpublishではなくprivateステータスで作成する。公開状態だとGoogleにインデックスされリスクになる

#103 (2026-04-29): WP content内のscript/id/onclick/display:noneはKSES除去される。動的UIはNext.jsかCSS-onlyで
#104 (2026-04-29): 長期popup(14日超)はカレンダー開始日のみ表示。全日は他イベントを埋める
#105 (2026-04-29): 旅行キーワード系はカレンダーから分離、関連記事で紹介

#106 (2026-04-29): WP KSES下ではtableベースが安全。gridは除去される
#107 (2026-04-29): URL検証で相対パス(/slug/)も検出パターンに含める

#111 (2026-04-29): 戦略型アフィリエイト記事は「課題提起→比較→推奨→CTA」の4段階構造で構築。中間CTA+末尾CTAの2箇所配置でCV率向上。rel="nofollow"必須
#112 (2026-04-29): アフィリエイト記事のCTAは「脅し」ではなく「安心訴求」。「壊れます」→「壊れる可能性があります。出発前の準備で安心」の表現で信頼性とCV両立

#113 (2026-04-29): LLM翻訳は主語を取り違える。ソースが"fans"を主語にしているのに記事で「アーティストが」に変化する事故が発生。fact_checkerにsource_content_mismatch検出を追加
#114 (2026-04-29): LLMはファンのSNS投稿の数値主張を無検証で採用する。「Spotify2億回」が実際は1.1億回だった。fact_checkerに億/百万/million単位の数値主張を自動WARN化
#115 (2026-04-29): GPT出力が既にHTMLブロック要素(<h2>等)を含む場合にf"<p>{text}</p>"で二重ラップするとunclosed_pが量産される。_wrap_body()で出力形式を判定してからラップ
#116 (2026-04-29): popup記事のURL dedupだけでは同一イベントの重複を防げない（異なるソースURLから同一イベント情報が入る）。タイトル先頭40字による二次dedupが必要
#117 (2026-04-29): X投稿のsilent failure問題。credential期限切れ時にx_retry_queueに入るがretryが実行されない。retry処理の自動化が未完
#118 (2026-04-29): LLMはプロンプトの「今日は○月○日」を記事の「特別な日」と混同する。ミンジ誕生日(5/7)の記事で「4/29は特別な日」と虚偽記載。誕生日・イベント日は公式データで裏取り必須
#119 (2026-04-29): 5つの公開経路のうち3つが品質ゲートをバイパスしていた。統一ゲートpre_publish_gate.pyを全経路に挿入。BLOCKは壊滅6種のみ、WARNを厚く
#120 (2026-04-29): audit_fixerが同じ記事を最大12回リライト（344回中258回が重複）。content_shortはGPTリライトでは解決不可能（ソース情報不足）。3回上限+content_short除外+新記事優先で修正

## 2026-05-01 モーニングブリーフィング教訓

#121 (2026-05-01): BLOCKされたドラフトの無限ループ防止 — draft_auto_publisher.pyにBLOCK回数追跡(draft_block_history.json)+MAX_BLOCK_COUNT=3超過で自動DELETEを実装。「BLOCK=何もしない」設計は毎時の無駄処理を蓄積する。BLOCK後のエスカレーションパスを必ず設計すること
#122 (2026-05-01): 監査基準は全エンジン間で統一必須 — popup_audit(200字)とfull_audit_engine(800字)のcontent_min矛盾を500字に統一。複数の監査エンジンで同指標の閾値が異なると偽陽性が大量発生し信頼性を毀損する
#123 (2026-05-01): feedback_loopの検索ウィンドウはパイプライン間タイミングを考慮して設計 — 10-20分の狭窓→5-40分に拡大+seen.json重複防止。cron起動タイミングと投稿パイプラインの実行タイミングのズレを吸収する設計が必要
#124 (2026-05-01): YouTube API 403は配額超過。残りクエリも全て403なのでbreak即終了 — 3クエリ全失敗でログ3倍増を防止。外部APIのquota errorは早期離脱がベストプラクティス
#125 (2026-05-01): Discord webhookは外部依存。定期的な疎通確認が必要 — 全8 webhook 404で監査通知が完全停止していた。webhook health checkをsite_health_check.pyに追加すべき
#126 (2026-05-01): X投稿の定型テキスト連投はアカウントロックを招く — タイトル+URLだけの素朴なツイートを連続投稿するとduplicate判定→ロック。フック+リプライ方式（URL分離+ハッシュタグ付与）でユニーク化が必須
#127 (2026-05-01): 監査で「検出」しても「修復」パスがなければ意味がない — x_post_error/x_missingは検出されるだけで誰も修復しない設計欠陥だった。新規issue type追加時は必ずFIXABLE_TYPESまたは専用修復ロジックを同時実装すること
#128 (2026-05-01): cron引数のデフォルト値は「何もしない」にしてはいけない — post_publish_enricherが--recent-hours default=0で引数なし時にprint_help()。cronは引数なしで呼ぶことが多いのでデフォルトで有用な動作をすべき
#129 (2026-05-01): HTTP 403の原因は複数ある。一律credential問題と判定してはいけない — duplicate content / account locked / permission不足は全て403だが対処が全く異なる。レスポンスbodyを見て分岐すること
#130 (2026-05-01): 投稿パイプライン（unified_publisher）とX投稿パイプライン（post_to_x.sh）の経路不一致 — unified_publisherはx_poster.py→post_to_x.py直接。post_to_x.shのURL除去・品質チェックをバイパスしていた。全X投稿を1つのゲートに統一すべき（教訓#41のサムネ保護と同じ原則）
#131 (2026-05-01): X投稿にはレート制限が必須 — 1時間に3投稿上限+類似テキスト検知+フック+リプライ方式の3層防御。レート制限なしでパイプラインが連投するとスパムラベルが付き、アカウントの表示範囲が恒久的に制限される。x_poster.py+post_to_x.sh両方に実装必須
