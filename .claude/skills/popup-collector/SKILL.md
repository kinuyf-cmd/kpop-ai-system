---
name: popup-collector
description: KPOP JOURNAL の K-POP ポップアップストア情報を自動収集するスキル。mewtwo_popup スクリプトを基盤に新規ポップアップ情報を週次収集し、投稿を自動化。「ポップアップ収集」「Popup自動投稿」「mewtwo_popup」「アーティストグッズ販売」「期間限定ストア」といった問い合わせ時に必ず使用。100点計画 F項目の達成に必須。
---

# Popup Collector

## 1. 目的

K-POP のポップアップストア情報を自動収集し記事化する。
KPOP JOURNAL の差別化と 100点計画 F項目の達成が狙い。

## 2. mewtwo_popup の再起動

- `mewtwo_popup` は Phase C-6 で復活予定(現状は停止中)。
- VPS に既存スクリプトが残存。配置:
  `/home/aiuser/kpop-ai-system/scripts/mewtwo_popup/`
- 再起動には新WordPressへの接続情報更新が必要(Phase C-6)。

## 3. 情報源

- 公式アーティスト SNS(X, Instagram)
- 公式事務所サイト(SM, HYBE, JYP, YG)
- ポップアップ専門サイト(韓国メディア)
- イベント情報サイト

## 4. 収集ルール

- 期間: 開催前2週間〜開催中
- 地域: 日本 + 韓国 + 主要国
- アーティスト: 上位30組を優先

## 5. 投稿自動化

- カテゴリ: news / タグ: `popup`
- タイトルテンプレートに沿う
- 本文構造: 場所・期間・グッズ・アクセス
- アイキャッチ: アーティスト画像 + ポップアップ告知

## 6. 実行スケジュール

- 週次(日曜 04:00)
- 速報性のある情報は即時(SNS 監視)

## 7. 重複排除

- 既存記事との照合を行う
- 同一ポップアップは新規投稿せず更新のみ

## 8. 100point-rubric-judge F項目との連動

| F項目 | 基準 |
|---|---|
| F-1 | mewtwo_popup の再稼働 |
| F-2 | 週次の自動収集 |
| F-3 | 新規 Popup → 自動投稿 |

## 9. 安全設計

- 公式情報源のみを使う
- 誤情報チェック(複数ソースで確認)
- [[red-team-auditor]] と連携し、誤情報を監査対象にする
- 自動投稿は [[citation-rules]] に従い出典を明記する

ログ: `/home/aiuser/.kpop_recovery/popup_collector_log.jsonl`
