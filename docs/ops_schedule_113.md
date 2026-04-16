# カテゴリ113「初心者ガイド」クラスター 運用スケジュール

作成日: 2026-04-13

## 対象記事
- 2432〜2441: 初心者ガイド10本（カテゴリ113）
- 2442: 113ハブ記事

## 定期確認コマンド

### 2026-04-20（公開7日後）GSCインデックス確認
```bash
cd /home/aiuser/kpop-ai-system
python3 google_metrics/check_gsc_index_beginner.py --save
```
→ logs/gsc_index_check_beginner.jsonl にベースライン差分を追記

### 2026-04-27（公開14日後）高リスク記事reviewer実行
```bash
cd /home/aiuser/kpop-ai-system
python3 lib/beginner_guide_reviewer.py
# next_review_due <= 2026-04-27 の記事が対象
```

### 2026-05-13（公開30日後）全件reviewer実行
```bash
cd /home/aiuser/kpop-ai-system
python3 lib/beginner_guide_reviewer.py --all
```

## CTRデータ取得
- 2026-04-20以降: GSC管理画面 → 検索パフォーマンス → フィルタ: ページ=/カテゴリ113のURL
- logs/beginner_guide_ctr.jsonl に手動記入（impressions_7d, clicks_7d等）

## 111クラスターとの対比
| 項目 | 111 | 113 |
|------|-----|-----|
| GSCスクリプト | check_gsc_index_streaming.py | check_gsc_index_beginner.py |
| reviewerスクリプト | lib/streaming_guide_reviewer.py | lib/beginner_guide_reviewer.py |
| review台帳 | logs/streaming_guide_review.jsonl | logs/beginner_guide_review.jsonl |
| CTR台帳 | logs/streaming_guide_ctr.jsonl | logs/beginner_guide_ctr.jsonl |
| GSCベースライン | logs/gsc_index_check.jsonl | logs/gsc_index_check_beginner.jsonl |

## 注意
- 既存cronは /home/aiuser/kpop-ai-system/cron/ 配下。上書き禁止。
- 111側のstreaming_guide_reviewer.pyのcronが既に動いている場合は別ファイルで管理する
