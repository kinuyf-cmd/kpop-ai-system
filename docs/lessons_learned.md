# 累積教訓 (2026-04-26 現在、17項目)

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
