# stg WordPress 認証ローテ + 速報DRAFT push runbook(オーナー対話実行)

> 作成: 2026-05-22 (Day12)。Claude は sudo 不可のため push/ローテを自動実行できない。
> 認証値は会話・claude.ai に出さない。以下は **オーナーが VPS 上で対話実行** する手順。

## 背景(値非表示の確認結果)
- stg WP 管理者 = `kpopstg_admin`(stg WP は `kpop-bot2` ではない)。
- `.env` の `WP_USER=kpop-bot2` / `WP_PASS`(31文字)は **旧本番用で stg では無効**(`~/.kpop_recovery/wp_connection_spec.md` 記載)。
- stg は nginx Basic認証(`kpopadmin`)+ WP login の2層。両方 `Authorization: Basic` を使うため **REST 経由の push は衝突して不可**。
- VPS 内の平文は `/tmp/wp_stg.txt`(root所有, BASIC_AUTH_*/WP_ADMIN_* 等)。ただし WP_ADMIN_PASSWORD は **login 用で REST App Password ではない**。
- ⇒ push は **wp-cli(DB直結, 認証ヘッダ不要)** が最短。

## 手順1: パスワードローテ(rF... は GitHub アーカイブに平文流出済=漏洩扱い)
```bash
# WP 管理者ログインPWのローテ(必要に応じて)
sudo -u www-data wp --path=/var/www/wp_stg user list --fields=ID,user_login,roles   # 現状確認
sudo -u www-data wp --path=/var/www/wp_stg user update kpopstg_admin --user_pass="$(openssl rand -base64 24)"
# ↑ 新PWは画面に出さず、パスワードマネージャ等へ。/tmp/wp_stg.txt も更新するなら別途。

# REST 用 Application Password を新規発行(将来 post_to_wp.py を REST で使う場合)
sudo -u www-data wp --path=/var/www/wp_stg user application-password create kpopstg_admin "kpop-pipeline" --porcelain
# ↑ 出力された App PW を ~/.env 等へ安全に保存(会話に出さない)。SITE_URL=https://stg... とセットで。
```
> 注: 本runbookの push はwp-cli直結なので App PW 無しでも実行可。App PW は将来のREST投稿の布石。

## 手順2: 速報DRAFT 4件を push(wp-cli, 認証値不要)
```bash
cd /home/aiuser/kpop-ai-system
sudo bash stg_push_breaking_drafts.sh
```
- 4件(STAYC/ONF/RESCENE/RIIZE)を `status=draft` で投入。同 slug 既存ならスキップ(冪等)。
- 完了後、下書き一覧が table 表示される。

## 手順3: サムネ複製(M3方式, www-data 権限)
- 各記事の `og:image`(Soompi)を stg `wp-content/uploads/2026/05/` に複製 → media import → featured_media 設定。
- 現状 push スクリプトは本文内に `<img src=soompi…>`(hotlink)で表示は出る。複製は任意の後続。
  ```bash
  # 例(1件): URLを wp media import し添付IDを featured に
  sudo -u www-data wp --path=/var/www/wp_stg media import "<og_image_url>" --post_id=<DRAFT_ID> --featured_image --porcelain
  ```

## 手順4: 視覚確認
- `https://stg.kpopjournal.tokyo/wp-admin/edit.php?post_status=draft`(Basic認証ダイアログに `kpopadmin` で入る)
- タイトル/本文/出典URL/サムネ/メタを確認。publish は **本番化フェーズ(Day14)**。

## 絶対方針
- 認証値を会話・claude.ai に出さない。スクリプトにハードコードしない(wp-cli が wp-config から読む)。
- publish しない(DRAFT のみ)。本番公開は Day14。
