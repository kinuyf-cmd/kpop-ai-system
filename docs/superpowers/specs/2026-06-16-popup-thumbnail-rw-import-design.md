# popup サムネ DL を rw 経路へ寄せる根治 — 設計

- 日付: 2026-06-16
- 対象: `lib/popup_event_to_post.py` の `download_and_attach_thumbnail`
- 関連教訓: `[[popup-cron-thumbnail-aiuser-write-fail]]` / `[[popup-update-stall-ssl-and-autopublish]]`

## 問題

日次 cron `popup_event_weekly.sh`(`0 4 * * *`)は **aiuser** で走る。
`download_and_attach_thumbnail` がサムネを `/var/www/wp_stg/wp-content/uploads/YYYY/MM/`
へ **直書き**(`target_path.write_bytes`)するが、uploads は `www-data:www-data` 755 で
aiuser 書込不可 → `[Errno 13] Permission denied` → featured 未設定のまま記事だけ publish。
記事/速報経路は `kpop-wp-rw.sh`(www-data 権限ラッパー)経由のため通り、popup だけ毎朝欠落する。

加えて現実装は手動 SQL で attachment を INSERT し、`_wp_attachment_metadata`(リサイズ/srcset)
を作らない。今日の手動復旧でも別途 `wp media regenerate` が必要だった。

## 採用アプローチ: A(rw 委譲・手動 SQL 削除)

`download_and_attach_thumbnail` の本体を差し替える。**シグネチャ・戻り値・呼び出し側
(`lib/popup_event_to_post.py:1031`)は不変**(`(post_id, image_url, sig) -> attachment_id`、
失敗時 0)。

### 新フロー

1. `image_url` から安全な filename を決定(既存ロジック流用)。
2. aiuser 書込可の **一時ファイル**(`tempfile`、0644 world-readable)へ画像を DL。
   - SSL は既存 `_IMG_SSL_CTX`(`data/ca/kpop_ca_bundle.pem`)を継続使用 → kbuzzlab の
     LE Root YR 問題を回避。
   - 既存の安全装置(5MB 上限、Content-Type、タイムアウト 30s、UA)を踏襲。
   - `DRY_RUN` 時は DL せず 0 を返す(既存挙動)。
3. `sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh media import <tmpfile>
   --post_id=<id> --featured_image --porcelain` を呼ぶ。
   - www-data 権限で uploads へ複製 + attachment 登録 + `_wp_attachment_metadata`
     正規生成(リサイズ/srcset)+ `_thumbnail_id` セットを WP が一括で行う。
   - `--porcelain` の stdout 末尾行が attachment_id。
4. alt(出典明示)を `sudo -n kpop-wp-rw.sh post meta update <att>
   _wp_attachment_image_alt "出典: {media} - {title}"` で設定。
   - `media = sig.get("source_media") or "kbuzzlab.com"`(既存ロジック踏襲)。
5. `finally` で一時ファイルを削除。
6. import 失敗(returncode≠0 / att_id parse 失敗)時は WARN を出して **0 を返す**
   (既存の失敗時挙動と同一 = 記事は出るが featured 無し。後で手動復旧手順で回収可)。

### 削除されるコード

- 直書き(`target_dir` mkdir / `target_path.write_bytes`)。
- attachment / `_wp_attached_file` / `_thumbnail_id` の手動 SQL INSERT 群(~50 行)。
- それに伴い `guid`/`rel_path` 等の手組みも不要。

### 不変点

- 関数シグネチャ・戻り値・呼び出し側。
- SSL コンテキスト `_IMG_SSL_CTX`。
- DRY_RUN 挙動(DL も import もしない)。
- alt の出典フォーマット。

## エラーハンドリング

| 事象 | 挙動 |
|------|------|
| DL 失敗(HTTP/SSL/timeout) | WARN ログ + return 0(featured 無し) |
| 画像が 5MB 超 | WARN + return 0 |
| rw import returncode≠0 | WARN(stderr 先頭) + tmp 削除 + return 0 |
| porcelain 出力 parse 失敗 | WARN + return 0 |
| 正常 | featured セット済 attachment_id を返す |

いずれも例外を投げず、記事 publish 自体は継続する(現状と同じ非ブロッキング)。

## テスト

`tests/unit/test_popup_event_to_post.py` に追加(subprocess をモック):

1. **正常系**: DL(urlopen モック)→ rw `media import` が
   `['sudo','-n', WP_RW,'media','import', <tmp>, '--post_id=<id>','--featured_image','--porcelain']`
   形で呼ばれ、porcelain stdout の att_id を返す。続けて alt の `post meta update` が呼ばれる。
2. **import 失敗**: returncode=1 → 0 を返し、`post meta update` は呼ばれない。
3. **DRY_RUN**: import も urlopen 書込も呼ばれず 0 を返す。
4. **tmp cleanup**: 成功/失敗どちらでも一時ファイルが残らない。

実機検証: signals 1 件で実行 → `_thumbnail_id` 充足 + stg HTML に `og:image`/`wp-post-image`。

## ロールアウト

- コード変更のみ(owner 作業・NOPASSWD 設定変更 **不要**。`*.sh` 既存ルール内)。
- 翌朝の cron で popup featured が自動付与されることを確認(ログに Permission denied が消える)。
- stg = 本番同一 DB のため別途デプロイ工程なし。
