# Runbook: wp_stg 資格情報の再設置（DBバックアップ5週停止の復旧）

対象: owner のみ（`sudo` 対話実行が必要なため、エージェントでは実行不能）
作成: 2026-09-14 / 背景: [[tmp-creds-loss-cascades-into-false-alerts]]

## なぜ必要か

`/tmp/wp_stg.txt` が消失し、以下が同時に壊れている。

| 症状 | 影響 | 緊急度 |
|---|---|---|
| `kpop_backup_weekly.sh` が DB ダンプをスキップ | **2026-08-24 以降 5週連続でDBバックアップ無し** | 最優先 |
| `popup_smoke_test.sh` の DB/HTTP 検証が不能 | 検証カバレッジ低下（誤報自体は修正済） | 中 |
| `strip_inline_colors.py` / `red_team_scan.sh` | 実行不能 | 低 |

`/tmp` は OS やテストに消されるため、**復旧先は `/tmp` ではなく永続パス**にする。
コード側は `${HOME}/.kpop_recovery/wp_stg.txt` を優先参照するよう修正済み（commit ec5e0d1）。

## 手順

### Step 1. DBパスワードを取得する

DB名とユーザーは判明済み（取得不要）:

- `WP_DB_NAME=wp_kpopjournal_stg`
- `WP_DB_USER=wp_kpop_stg`

パスワードのみ `wp-config.php` から取得する。このファイルは `www-data` 専用（`0640`）で、
`sudo -n` では読めないため **対話 sudo が必要**。

```bash
sudo grep -E "DB_PASSWORD" /var/www/wp_stg/wp-config.php
```

### Step 2. BASIC認証（stg）のユーザー/パスワードを用意する

`https://stg.kpopjournal.tokyo/` は nginx の BASIC 認証で保護されている（実測 401）。
これは WordPress の REST 認証（`WP_USER`/`WP_PASS`）とは**別物**なので `.env` からは流用しない。

nginx 側の設定から参照先を確認する:

```bash
sudo grep -rn "auth_basic" /etc/nginx/sites-enabled/ | grep -i stg
# auth_basic_user_file で指定された .htpasswd のユーザー名を確認
sudo cat <上で出た .htpasswd のパス>   # ユーザー名のみ確認可（パスワードはハッシュ）
```

パスワードが不明な場合は再設定してよい（既存の利用者は自動化のみ）:

```bash
sudo htpasswd <.htpasswd のパス> <ユーザー名>
sudo nginx -t && sudo systemctl reload nginx
```

### Step 3. 資格情報ファイルを永続パスに作成する

**形式の制約**（既存コードの契約なので厳守）:

- `KEY=value` を1行1つ。`export` は付けない
- `kpop_backup_weekly.sh` が `source` するため **シェルとして valid** であること
- 値に `#` `$` `"` 等が含まれる場合はシングルクォートで囲む
- Markdown リンクを値に混ぜない（[[no-markdown-links-in-shell-values]]）

```bash
umask 077
cat > ~/.kpop_recovery/wp_stg.txt <<'EOF'
WP_DB_NAME=wp_kpopjournal_stg
WP_DB_USER=wp_kpop_stg
WP_DB_PASSWORD='<Step 1 の値>'
BASIC_AUTH_USER='<Step 2 のユーザー>'
BASIC_AUTH_PASS='<Step 2 のパスワード>'
EOF
chmod 600 ~/.kpop_recovery/wp_stg.txt
```

`umask 077` と `chmod 600` は必須。平文パスワードを 644 で置かない
（[[vps_backup_payment_safeguards]]）。

### Step 4. 検証する（成功ログでなく実値で確認）

```bash
cd /home/aiuser/kpop-ai-system

# 4-1. DB接続
set -a; . ~/.kpop_recovery/wp_stg.txt; set +a
mysql -u"$WP_DB_USER" -p"$WP_DB_PASSWORD" "$WP_DB_NAME" -N -e "SELECT COUNT(*) FROM wp_posts;"
#   → 数値が返れば OK

# 4-2. BASIC認証
curl -s -o /dev/null -w "%{http_code}\n" -u "$BASIC_AUTH_USER:$BASIC_AUTH_PASS" \
  https://stg.kpopjournal.tokyo/
#   → 200 なら OK（401 なら Step 2 をやり直す）

# 4-3. スモークテスト（FAILS=0 を期待）
bash popup_smoke_test.sh 2>&1 | tail -5
```

`4-1` が通らないうちは先に進まないこと。
「Success」表示ではなく**返ってきた実値**で判断する（[[aioseo-desc-write-traps]] の教訓）。

### Step 5. バックアップを手動で1回走らせて復旧を確認する

5週分の欠落は取り戻せないが、**直近のダンプを即座に確保する**のが目的。

```bash
bash kpop_backup_weekly.sh 2>&1 | tail -20
ls -lh ~/.kpop_recovery/backups/*_db.sql.gz | tail -3
```

`_db.sql.gz` が当日日付で数十MB以上あれば復旧完了。
0バイトや極端に小さい場合は失敗しているので中身を確認する
（[[adsense-token-zero-byte-nonatomic-write]] と同型の事故に注意）。

## 再発防止（Step 5 完了後に実施を推奨）

現状、バックアップ失敗は**ログに ERROR 1行**が出るだけで通知されない。
これが5週間気づかれなかった直接の原因なので、通知経路に載せる:

- `kpop_backup_weekly.sh` の資格情報欠落・`mysqldump` 失敗時に
  `lib/resolve_discord_webhook.py urgent_errors` へ通知を飛ばす
- ダンプ生成後にサイズ下限チェック（例: 1MB未満なら異常扱い）を追加する

この2点はエージェント側で実装可能。owner の Step 1-5 完了後に依頼してよい。

## 補足: なぜエージェントが自分で直せないか

- `wp-config.php` は `www-data:www-data 0640` で `sudo -n` 不可
- `kpop-wp-ro` は `db export` / `eval` を DENY
- `kpop-wp-rw.sh` も `db export` を明示的に DENY

いずれも意図的なガードなので、**迂回せず owner 実行とする**のが正しい。
