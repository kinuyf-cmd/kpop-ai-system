# KPOP JOURNAL 編集憲章 (AI社員自律運営規則)

制定日: 2026-04-27 / 運用開始: C-Fix12 Block3

## 基本理念
K-POPファンに速く・正確で・読みやすい情報を届ける。

## 組織
- 編集長 AI (daily_editor.py, 毎時) — KPI監視+遅延時強制生成
- 速報担当 (breaking_news_detector.py, 3分毎) — urgency=high即時記事化
- イベント/カムバック担当 (auto_event/comeback, 2時間毎) — dynamic max
- クロール部 (14 collectors, 30分毎) — 韓/英/日ソース
- 校正部 (unified_publisher.py) — タイトル42字/slug/meta/サムネ/GSC/X
- 監査部 (audit_publisher.py, 6時間毎) — 10項目チェック+自動修正+学習

## 品質基準
- タイトル: 42字以内 (prefix込み50字)
- スラッグ: 英数字ハイフン
- 本文: 100字以上
- サムネ: featured_media必須、smart_crop
- カテゴリ: 必須
- メタdesc: 80-160字
- GSC/X: 投稿直後に通知

## KPI
- 1日30本 (速報30のみ、その他は速報安定化まで一旦停止) (2026-05-11 改定、旧: 速報50+その他10)

## 禁止事項
- 推測/創作、著作権侵害画像、重複投稿、Phase名改変

## 学習サイクル
投稿 → 監査(6h毎) → 問題検出 → 自動修正 → lessons追記 → rules更新 → 次回適用

## オーナー権限
全自動停止可、個別編集可、憲章変更はオーナー承認必須


## リライト担当AI (C-Fix12 Block4)

### 役割
監査部 or unified_publisher品質ゲートで draft化された記事を自動リライト+再公開。

### フロー
1. draft化時に `data/rewrite_queue.jsonl` へ pending 追加
2. `rewrite_worker.py` (cron毎時15分) が pending をピック (古い順、最大5件)
3. 元ソースURL + 原文から GPT-4o-mini で日本語本文再生成 (500-800字)
4. 品質ゲート再チェック (200字以上 + 日本語30%以上)
5. 合格 → publish + GSC再通知
6. 不合格 → retry (最大3回)、3回失敗 → quarantine (trash + ログ)

### データファイル
- `data/rewrite_queue.jsonl` — 処理キュー
- `logs/quarantine.jsonl` — 修復不能記事の記録
- `logs/rewrite_worker.log` — cron実行ログ


## 削除判定AI (quarantine_cleaner.py) — C-Fix12 B4.5+

### 思想
オーナー介入ゼロ。価値のない記事はサイトから完全排除。

### フロー
1. quarantine到達 (rewrite_worker 3回失敗)
2. source_url+原文>=100字? → GPT-4o救済試行
3. 成功 → 再公開+GSC+X / 失敗 → 即完全削除

### cron
日次 02:00

### ログ
- logs/permanently_deleted.jsonl — 完全削除記録
- logs/rescued.jsonl — GPT-4o救済成功記録
