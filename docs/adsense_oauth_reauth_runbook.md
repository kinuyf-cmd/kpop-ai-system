# AdSense OAuth 再認証 runbook

最終更新: 2026-07-31

## いま起きていること（2026-07-31 実測）

`refresh_token` が **7日で失効**している。

| 事象 | 実測値（実行日ベース） |
|---|---|
| 7/17 | owner 再認証 |
| 7/17〜**7/24** | AdSense 取得 **OK**（7/24 8:30 の cron も refresh 成功） |
| **7/25 以降** | `invalid_grant: Token has been expired or revoked` で **NG** |

再認証の **7日後まで成功し、8日目に失効** = Google の「7日失効」の境界そのもの。

> ⚠️ 集計の注意: `metrics_history.jsonl` の `date` は**データ対象日**であって実行日ではない。
> `fetched_at` で数えること。`date` で数えると1日ずれて誤読する（実際に誤読した）。

### 同意画面は「本番環境」だった（2026-07-31 owner 確認済）

つまり **「テストだから7日失効」ではない**。この仮説は否定された。

残る説明は **OAuth クライアント自体が本番化より前に作られたもの**であること。

- `adsense_client_secret.json` の作成日 = **2026-04-04**、以後一度も変更なし
- Google のドキュメント/事例では、**Testing → In Production に変更しても、
  それ以前に作成した OAuth クライアントが発行する refresh_token は
  7日失効の扱いが続く**ことがあり、その場合は
  **新しい OAuth クライアントを作り直す**必要がある

> 参考: [Google OAuth invalid_grant — What it means & how to fix it (Nango)](https://nango.dev/blog/google-oauth-invalid-grant-token-has-been-expired-or-revoked/) /
> [Google OAuth Refresh Token: Expiration, 7-Day Limit (Unipile)](https://www.unipile.com/google-oauth-refresh-token/)

これは 6/3 再認証→数日で失効、7/17 再認証→8日目に失効、という
**過去2回の再発とも整合する**（どちらも同じ 4/4 作成のクライアントを使っている）。

## 手順

### STEP 1: OAuth クライアントを作り直す（← これが本丸）

同意画面は既に本番なので、**触るのはクライアントの方**。

1. https://console.cloud.google.com/auth/clients?project=petfortune を開く
2. 「**+ クライアントを作成**」
   - アプリケーションの種類: **デスクトップ アプリ**
   - 名前: 例 `kpop-adsense-2026-07`（既存と区別できる名前に）
3. 作成後、**JSON をダウンロード**
4. VM に配置して既存を置き換える（**バックアップを取ってから**）:
   ```
   cd /home/aiuser/kpop-ai-system/google_metrics
   cp adsense_client_secret.json adsense_client_secret.json.bak-$(date +%Y%m%d)
   # ダウンロードした JSON をこのパスに上書き配置する
   #   scp -P 2222 client_secret_xxx.json aiuser@160.251.254.62:/home/aiuser/kpop-ai-system/google_metrics/adsense_client_secret.json
   chmod 600 adsense_client_secret.json
   ```
5. **古いトークンを消す**（新クライアントと不整合になるため）:
   ```
   rm -f /home/aiuser/kpop-ai-system/google_metrics/adsense_token.json
   ```
6. STEP 2 で再認証する

> 既存クライアントを削除する必要はない。新しい方に差し替えるだけでよい。
> 差し替え後、旧クライアントの refresh_token は使われなくなる。

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

**8日後（再認証日 + 8日）に必ず再確認すること。** ここが成否の分かれ目。

```
# 再認証から8日後に実行。OK が出れば根治成功
venv_kpi/bin/python3 google_metrics/fetch_yesterday_metrics.py
```

- `AdSense=OK` → **クライアント作り直しが効いた**（refresh_token が無期限化）
- また `invalid_grant` → クライアント作り直しでも直っていない。
  その場合の次の手は「効かないこと」節の末尾を参照。

判定を機械化してあるので、health_check の `adsense_token` 項目でも追える
（token mtime が48h以上未更新なら WARN）。

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
  （※ 今回クライアントを作り直せば、この上限のカウントもリセットされる）

### クライアントを作り直しても8日目に失効する場合

その時点で「7日失効」の説明はすべて潰れているので、次を順に疑う。

1. **同意画面の「対象」にテストユーザーが残っていないか** —
   本番環境でもテストユーザー欄に該当アカウントが残っていると
   テスト扱いが継続する事例がある。空にする。
2. **アカウント側でアクセスが取り消されていないか** —
   https://myaccount.google.com/permissions で当該アプリを確認。
   セキュリティ設定変更やパスワード変更でも失効する。
3. **同意画面の「確認ステータス」** — スコープが機微(sensitive)扱いだと
   未確認アプリのままになり、審査完了までトークン寿命が制限される場合がある。
   `adsense.readonly` は機微スコープに該当しうるので、
   確認ステータスが「確認が必要」なら審査申請が要る。

ここまで潰しても直らないなら、**毎週の手動再認証を運用として受け入れる**か、
**AdSense 管理画面を直接見る運用に切り替える**方が費用対効果が高い
（欠けるのは朝ブリーフの数値表示のみで、実収益には影響しないため）。

## 影響範囲

欠けるのは**朝ブリーフへの収益数値の表示のみ**。
実収益は発生しており、AdSense 管理画面では正常に確認できる。
GA4 / GSC は service account の別認証なので**影響なし**。

関連メモリ: `adsense-token-invalid-grant`

---

## 2026-07-31 実施記録（クライアント作り直し）

| 項目 | 値 |
|---|---|
| 旧 client_id | `869886094667-7ka5frh...`（2026-04-04 作成 / 7日失効していた） |
| 新 client_id | `869886094667-rkrcs6r...`（2026-07-31 作成） |
| プロジェクト | `petfortune`（変更なし。他の GA4/GSC/インデックス申請も同じ） |
| 結果 | `AdSense=OK` / 実データ取得（ESTIMATED_EARNINGS 44 等）/ errors 空 |
| 旧クライアント | `adsense_client_secret.json.bak-20260731` に保全 |

**判定日: 2026-08-08（再認証 + 8日）**
この日に `AdSense=OK` なら「本番化前の古いクライアントが原因」という仮説が実証され根治完了。
また `invalid_grant` なら上の「クライアントを作り直しても8日目に失効する場合」へ進む。

### 判定結果: ❌ 仮説は否定された（2026-08-12 実測）

**新クライアントでも7日で失効した。** `fetched_at`（実行日）ベースの実測:

| 実行日 | AdSense |
|---|---|
| 7/31（再認証当日） | OK |
| 8/1 〜 **8/6** | OK（7日間） |
| **8/7 以降** | **NG**（`invalid_grant`） |

7/17再認証→7/24までOK、7/31再認証→8/6までOK。**どちらもきっちり7日**で、
クライアントの新旧に関係なく再現している。よって
「本番化前の古いクライアントが原因」という仮説は**実証されず否定**。

→ 次に疑うのは下の「クライアントを作り直しても8日目に失効する場合」の3項目。
**特に 3.（確認ステータス / 機微スコープ）が最有力**。本件のスコープは
`adsense.readonly` のみで、これは Google の分類で機微スコープに該当しうる。
未確認アプリのままだと refresh_token は7日で失効する仕様のため、
**同意画面の「確認ステータス」を見て、未確認なら審査申請するのが本丸**と考えられる。
1.（テストユーザー残存）は審査申請より先に確認できるので順に潰すこと。

### 未対応（owner 作業）
- **client_secret のローテーション**: 新クライアントのシークレットが
  チャットに平文で露出したため、以下で差し替えることを推奨。
  1. https://console.cloud.google.com/auth/clients?project=petfortune で
     該当クライアントを開く
  2. 「クライアント シークレットを追加」→ 新しいシークレットを発行
  3. ダウンロードした JSON を **scp で** 配置（チャットに貼らない）
  4. `rm -f adsense_token.json` してから再認証
  5. 動作確認後、Console で古いシークレットを削除
  ※ 緊急性は低い（デスクトップアプリのシークレットは Google の設計上
     「機密ではない」扱いで、単体では悪用できず、承認には本人のブラウザ操作が必要）。
     ただし公開の場に出た以上、次の保守機会に差し替えるのが望ましい。
