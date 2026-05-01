# ポップアップ編集憲章 (Popup Editorial Charter)

## 1. 担当社員 (10部門目「ポップアップ担当」)

| 役割 | システム |
|---|---|
| 探す | popup_prtimes_collector / popup_kbuzz_collector (毎時) |
| 投稿 | popup_publisher.py (3時間毎、最大10件) |
| 監査 | popup_audit.py (6時間毎) |
| 削除判定 | quarantine_cleaner (popup post type も対象) |

## 2. 投稿ルール (品質基準)

### MUST (絶対遵守)
- タイトル: 10-60字
- 本文: 200字以上、h2セクション最低3つ
- 都市判定: 8区域いずれか必須
- 注意書き: `<p class="kpj-disclaimer">※情報は変更...</p>` 末尾必須
- featured_media: サムネ必須 (OG → DALL-E fallback)
- 状態: upcoming/ongoing/ended のいずれか

### SHOULD (推奨)
- 期間 (_popup_start_date, _popup_end_date)
- 営業時間 (_popup_hours)
- 場所 (_popup_address)
- 公式URL (_popup_official_url)
- 事前予約要否 (_popup_reservation)
- 特典 (_popup_perks)
- SNS情報 (_popup_sns)
- 緯度経度 (_popup_lat, _popup_lng) → 地図表示用

### MAY (任意)
- 入場料 (_popup_admission)
- ブランド (_popup_brand)
- 関連アーティスト (_popup_artist)

## 3. 構造化記事フォーマット

### 必須h2セクション
1. イベント概要
2. 開催詳細
3. 特典・限定アイテム
4. アクセス

### 文末バリエーション
~開催 / ~オープン / ~登場 / ~実施 / ~始まる / ~公開
※「明らかにした」「発表した」連発禁止

## 4. 監査基準 (popup_audit.py 10項目)

| # | チェック | severity |
|---|---|---|
| 1 | title_long (>60字) | low |
| 2 | title_short (<10字) | high |
| 3 | content_short (<200字) | high |
| 4 | no_city | high |
| 5 | no_start_date | medium |
| 6 | unknown_status | medium |
| 7 | no_thumbnail | high |
| 8 | no_official_url | low |
| 9 | no_disclaimer | medium |
| 10 | no_h2 | low |

## 5. 削除ポリシー

- 終了後30日経過: archive (publish状態維持、/popup/archive/ で表示)
- 終了後90日経過: draft化 (一覧から除外)
- 終了後180日経過: quarantine_cleaner で削除判定

## 6. 著作権

- 公式OG画像優先 (主催者承諾推定)
- なければDALL-E 3生成 (オリジナル画像)
- 公式画像転載は出典明記必須
- アーティスト写真の直接転載禁止

## 7. 掲載希望対応

- kpopjournal.biz@gmail.com でメール受付
- 編集部判断 (編集長AI=daily_editor)
- 掲載決定後2-5営業日で公開
- お断りする場合の理由提示
