# SNS自動投稿設定ガイド v1.0

K-POP Journal の SNS 自動投稿を有効化するための設定手順書。
各チャネルの credential を設定し、`config/sns_config.json` で `enabled: true` にすると
パイプラインが記事投稿時に自動で各 SNS へクロスポストします。

---

## 1. Instagram 設定手順

### 1-1. Meta アプリ作成
1. https://developers.facebook.com/ にログイン
2. 「マイアプリ」→「アプリを作成」→ タイプ「ビジネス」を選択
3. アプリ名: `KPOPJournal-Instagram` など任意

### 1-2. Instagram Graph API 有効化
1. アプリダッシュボード → 「製品を追加」→ **Instagram Graph API** を追加
2. 必要な権限を申請:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_read_engagement`
3. Facebookページと Instagram ビジネスアカウントを連携

### 1-3. アクセストークン取得
1. Graph API Explorer でショートトークンを生成
2. 長期トークンに交換（60日有効）:
```bash
curl -s "https://graph.facebook.com/v19.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id={APP_ID}&\
client_secret={APP_SECRET}&\
fb_exchange_token={SHORT_TOKEN}" | python3 -m json.tool
```
3. Instagram ビジネスアカウント ID を取得:
```bash
curl -s "https://graph.facebook.com/v19.0/me/accounts?\
fields=instagram_business_account&\
access_token={LONG_TOKEN}" | python3 -m json.tool
```

### 1-4. Credential 保存
```bash
cat > ~/.instagram_credentials << 'CRED'
{
  "access_token": "EAAxxxxxx...",
  "instagram_account_id": "17841400000000000",
  "facebook_page_id": "100000000000000"
}
CRED
chmod 600 ~/.instagram_credentials
```

### 1-5. 検証
```bash
python3 lib/post_to_instagram.py --validate
python3 lib/post_to_instagram.py --dry-run --title "テスト投稿" --url "https://kpopjournal.tokyo" --image "https://kpopjournal.tokyo/wp-content/uploads/test.jpg"
```

### 1-6. 有効化
`config/sns_config.json` の `instagram.enabled` を `true` に変更。

### 注意事項
- アクセストークンは60日で失効。`crontab` でトークンリフレッシュを自動化推奨
- 1日最大3投稿、最小間隔120分（`sns_config.json` で変更可能）
- 画像は1080x1080px以上、JPEG形式、8MB以下

---

## 2. LINE 設定手順

### 2-1. LINE Developers チャンネル作成
1. https://developers.line.biz/ にログイン
2. プロバイダー作成（未作成の場合）
3. 「Messaging API」チャンネルを新規作成
   - チャンネル名: `K-POP Journal`
   - 説明: K-POP最新ニュースをお届け

### 2-2. チャンネル設定
1. Messaging API タブ → チャンネルアクセストークン（長期）を発行
2. 応答メッセージ: 無効にする（自動応答を使わない場合）
3. あいさつメッセージ: カスタマイズ推奨

### 2-3. Credential 保存
```bash
cat > ~/.line_credentials << 'CRED'
{
  "channel_access_token": "xxxxxxxxxxxxxxxx",
  "channel_secret": "xxxxxxxxxxxxxxxx"
}
CRED
chmod 600 ~/.line_credentials
```

### 2-4. 検証
```bash
python3 lib/post_to_line.py --validate
python3 lib/post_to_line.py --dry-run --title "テスト投稿" --url "https://kpopjournal.tokyo" --image "https://kpopjournal.tokyo/wp-content/uploads/test.jpg"
```

### 2-5. 有効化
`config/sns_config.json` の `line.enabled` を `true` に変更。

### 注意事項
- 無料プランは月1000通まで（友だち数 x 配信数）
- クワイエットアワー 23:00-07:00 JST は自動で配信しない
- 1日最大5通、最小間隔60分
- breaking / comeback カテゴリのみ配信（設定で変更可能）

---

## 3. Brevo（メルマガ）設定手順

### 3-1. Brevo アカウント作成
1. https://app.brevo.com/ でアカウント作成（無料プランあり: 300通/日）
2. 送信者情報を設定（ドメイン認証推奨）

### 3-2. API キー取得
1. 設定 → SMTP & API → API Keys
2. 「Generate a new API key」で v3 API キーを生成

### 3-3. コンタクトリスト作成
1. Contacts → Lists → 「Create a list」
2. リスト名: `K-POP Journal Weekly`
3. リスト ID をメモ（`sns_config.json` の `newsletter.list_id` に設定）

### 3-4. Credential 保存
```bash
cat > ~/.brevo_credentials << 'CRED'
{
  "api_key": "xkeysib-xxxxxxxxxxxxxxxx"
}
CRED
chmod 600 ~/.brevo_credentials
```

### 3-5. 設定更新
`config/sns_config.json` の `newsletter` セクション:
```json
{
  "newsletter": {
    "enabled": true,
    "list_id": "3"
  }
}
```

### 3-6. 検証
```bash
python3 lib/post_to_newsletter.py --validate
python3 lib/post_to_newsletter.py --preview
python3 lib/post_to_newsletter.py --dry-run
```

### 3-7. 有効化
`config/sns_config.json` の `newsletter.enabled` を `true` に変更。
crontab に週次送信を追加:
```cron
0 10 * * 0 cd /home/aiuser/kpop-ai-system && python3 lib/post_to_newsletter.py --send >> logs/newsletter.log 2>&1
```

### 注意事項
- 無料プランは1日300通まで
- ドメイン認証（SPF/DKIM）でスパム判定を回避
- 配信停止リンクは自動挿入される
- 毎週日曜 10:00 JST に自動送信（設定で変更可能）

---

## 4. X (Twitter) 復旧手順

現在アカウント凍結中。凍結解除後:

1. `~/.x_credentials` が存在することを確認
2. `config/sns_config.json` の `twitter.enabled` を `true` に変更
3. テスト: `bash google_metrics/post_to_x.sh "テスト投稿" "https://kpopjournal.tokyo"`

---

## 5. クロスポスト設定

`config/sns_config.json` の `cross_post` セクションで、カテゴリごとの配信先を制御:

```json
{
  "cross_post": {
    "auto_share_on_publish": true,
    "channels_by_category": {
      "breaking": ["x", "line", "webpush", "instagram"],
      "comeback": ["x", "line", "webpush", "instagram"],
      "ranking": ["x", "instagram"],
      "beauty": ["x", "instagram"],
      "default": ["x"]
    }
  }
}
```

全チャネルが `enabled: false` でも、パイプラインはエラーにならず
グレースフルスキップします（exit 0）。

---

## 6. トラブルシューティング

| 症状 | 確認コマンド | 対処 |
|------|------------|------|
| Instagram 投稿失敗 | `tail logs/instagram_retry_log.jsonl` | トークン期限確認 → 再発行 |
| LINE 配信されない | `python3 lib/post_to_line.py --validate` | チャンネルトークン確認 |
| メルマガ送信エラー | `tail logs/newsletter_history.jsonl` | API キー・リスト ID 確認 |
| 全SNS停止 | `cat config/sns_config.json \| python3 -c "..."` | enabled フラグ確認 |

ログファイル一覧:
- `logs/instagram_post_history.jsonl`
- `logs/line_post_history.jsonl`
- `logs/newsletter_history.jsonl`
- `logs/x_post_history.jsonl`
