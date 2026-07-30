# AdSense OAuth 再認証 runbook

最終更新: 2026-07-31

## いま起きていること（2026-07-31 実測）

`refresh_token` が **7日周期で失効**している。

| 事象 | 実測値 |
|---|---|
| 7/17 再認証 | 成功 |
| 7/18〜7/21 | AdSense 取得 **OK** |
| **7/22 以降** | `invalid_grant: Token has been expired or revoked` で **NG** |
| トークン expiry | 2026-07-24 |

再認証からちょうど7日で失効しており、これは Google OAuth の
**「公開ステータスがテストの場合、refresh_token を7日で失効させる」** 挙動と一致する。

> 参考: [Google OAuth Refresh Token: Expiration, 7-Day Limit](https://www.unipile.com/google-oauth-refresh-token/) /
> [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)

**重要**: 過去のメモには「同意画面は本番(Published)確認済(2026-05-27)」とあるが、
現在の失効パターンはテストモードそのもの。**まず公開ステータスを確認すること。**
ここを直さずに再認証しても **7日後に必ず再発する**。

## 手順

### STEP 1: OAuth 同意画面を「本番」にする（← これが本丸）

owner がブラウザで作業する。

1. https://console.cloud.google.com/auth/overview?project=petfortune を開く
   - プロジェクトは **petfortune**（`adsense_client_secret.json` の project_id）
2. 「対象」(Audience) を開く
3. **公開ステータス**を確認
   - `テスト` になっていたら → **「アプリを公開」を押して「本番環境」にする**
   - すでに `本番環境` なら → STEP 1 は不要。STEP 3 の「7日で再発した場合」へ
4. ユーザーの種類が `外部` であることを確認（個人 AdSense なので `内部` は選べない）

> 未確認の外部アプリでも、自分のアカウントで使う分には
> 「詳細設定 → 安全でないページに移動」で承認できる。審査は不要。

### STEP 2: 再認証する

**手元PC** で2つのターミナルを使う。

**ターミナルA — ポート転送を張る**
```
ssh -L 8765:localhost:8765 -p 2222 aiuser@160.251.254.62
```
- `-p 2222` は **必須**（22番は閉じている）
- この接続は承認が終わるまで開いたままにする

**ターミナルB — ターミナルAの接続内で実行**
```
cd /home/aiuser/kpop-ai-system
venv_kpi/bin/python3 google_metrics/fetch_yesterday_metrics.py
```

1. 死んだトークンを検知して**同意URLが表示される**
2. そのURLを**手元PCのブラウザ**で開く
3. AdSense と紐づく Google アカウントで承認
4. `localhost:8765` にリダイレクト → ポート転送経由で VM が受信
5. `google_metrics/adsense_token.json` が自動更新される
6. 出力に `(GA4=OK GSC=OK AdSense=OK)` が出れば完了

**ハマりどころ**
- 承認中に `channel N: open failed: connect failed: Connection refused` が出ても**無害**。
  VM 側は既に受信済みで成功している。
- ブラウザに `localhost:8765/?...code=4/0Ae...` が残って見えても、
  転送が効いていれば成功。判定は **token の mtime が更新されたか**で行う。
- 承認コードは数分で失効するので、URL を開いたら手早く承認する。

### STEP 3: 確認する

```
# トークンが更新されたか
stat -c '%y' google_metrics/adsense_token.json

# 実際に API が通るか
venv_kpi/bin/python3 -c "
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
d=json.load(open('google_metrics/adsense_token.json'))
c=Credentials(token=d['token'],refresh_token=d['refresh_token'],token_uri=d['token_uri'],
              client_id=d['client_id'],client_secret=d['client_secret'],scopes=d['scopes'])
c.refresh(Request()); print('refresh OK ->', c.expiry)
"
```

**7日後にもう一度確認すること。** STEP 1 が効いていれば失効しない。
また 7 日で落ちたら公開ステータスが本番になっていない。

## やってはいけないこと / 効かないこと

- **service account への移行は不可能**（2026-07-17 実測で確定）。
  `kpop-bot@petfortune.iam.gserviceaccount.com` に `adsense.readonly` を付けても
  `accounts().list()` は空 `{}`、`reports().generate()` は **403**。
  AdSense Management API は個人 AdSense アカウントに紐づくため SA 非対応。
  （GA4/GSC が SA で動くのとは別物）→ **owner のブラウザ承認が唯一の道**。
- **cron からの自動再認証は不可**。承認にブラウザが要る。
  2026-07-17 の根治(d2d421d)で、非対話実行時は即 `RuntimeError` で諦めるようにしてある。
  これ以前は `run_local_server` がポート8765を掴んだまま**7日10時間**生存し、
  以降の cron が `Errno 98 Address already in use` で全滅、収益データが25日分ゼロになった。
- **再認証を繰り返さない**。同一 client_id × アカウントの refresh_token には
  発行数上限(~100)があり、超過すると古いものから自動失効する。
  無闇にフローを通すと自己失効を誘発する。

## 影響範囲

欠けるのは**朝ブリーフへの収益数値の表示のみ**。
実収益は発生しており、AdSense 管理画面では正常に確認できる。
GA4 / GSC は service account の別認証なので**影響なし**。

関連メモリ: `adsense-token-invalid-grant`
