# 累積教訓 (2026-04-27 現在、14項目)

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
