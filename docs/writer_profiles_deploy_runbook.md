# ライター紹介ページ デプロイ runbook

X 架空ライター陣(8人)のサイト紹介ページ(`/writers/`)を本番に出す手順。
真実のソースは `config/x_writer_personas.json`。X 投稿生成とサイト紹介ページで共有する。

## 構成(実装済み・リポジトリ内)

| ファイル | 役割 |
|---|---|
| `config/x_writer_personas.json` | **真実のソース**。8人の設定。X 投稿生成が読む |
| `themes/generatepress-kpop/data/x_writer_personas.json` | テーマ同梱コピー。紹介ページが読む(stg/本番でリポ config/ が隣に無い為) |
| `scripts/sync_writer_personas.sh` | config/ → テーマ同梱コピーへ同期(JSON 編集後に実行) |
| `themes/generatepress-kpop/inc/writer-profiles.php` | writer CPT 登録 + JSON 駆動の個別/一覧描画 + CSS |
| `themes/generatepress-kpop/functions.php` | 上記 inc を `require_once`(末尾) |

- ACF 不使用・stg 手作業テンプレ不要。**コードを反映するだけ**で動く。
- 器投稿(各ライターの `writer` 投稿)は `kpop_seed_writer_posts()` が **init 時に冪等自動生成**
  (未作成分のみ。1日1回 transient で抑制)。手動作成は不要。
- URL: 一覧 `/writers/`、個別 `/writers/{key}/`(key = yui / mina / nono / saki / haruka / aya / rika / editorial)。

## JSON を編集したとき(名前・推し・口癖の変更)

```bash
# 1) config/x_writer_personas.json を編集
# 2) テーマ同梱コピーへ同期
bash scripts/sync_writer_personas.sh
# 3) 通常のテーマ反映(下記デプロイ)
```

## デプロイ — ワンコマンド(オーナー作業)

テーマ dir は www-data 所有のため sudo 必須 = オーナー実行。以下1コマンドで反映:

```bash
sudo bash scripts/deploy_writer_pages_stg.sh          # stg へ
# 本番へは stg 検証 OK 後:
sudo TARGET=/path/to/本番theme bash scripts/deploy_writer_pages_stg.sh
```

スクリプトは PHP 構文チェック → functions.php バックアップ → 3ファイル反映 →
chown www-data → rewrite flush → 器投稿シード確認、までを実施する。

## デプロイ — 手動手順(参考)

メモリ [[kpop-stg-deploy-workflow]] / [[repo-stylecss-overwrites-built-sidebar-css]] の方針に従う。
テーマファイルの本番反映は owner 実行。

1. **stg にテーマ反映**(リポジトリ → `/var/www/wp_stg/wp-content/themes/generatepress-kpop/`)
   反映対象:
   - `functions.php`(末尾の require 追加)
   - `inc/writer-profiles.php`(新規)
   - `data/x_writer_personas.json`(新規)
2. **rewrite flush**: 初回アクセスで `kpop_flush_writer_rewrite()` が一度だけ自動 flush。
   即時にしたい場合は管理画面 設定 > パーマリンク を開いて保存(flush)、または
   `wp rewrite flush`(wp-cli は sudo パス、メモリ [[readonly-sudo-wrapper-installed]] は参照系のみ。
   書込 flush は owner 実行)。
3. **確認(stg)**: `/writers/` で8人のカード、`/writers/yui/` 等で個別プロフィールが出るか。
   器投稿が自動生成されるので、出なければ パーマリンク保存 → 再アクセス。
4. **本番反映**: stg 検証 OK 後、同ファイル群を本番テーマへ反映(通常のテーマデプロイ手順)。

## 確認観点

- [ ] `/writers/` 一覧に8人、各カードから個別へ遷移
- [ ] 個別ページに 名前 / 年齢・肩書 / 自己紹介 / 推し / 担当 / よく話すこと / 署名
- [ ] サイドバー無し全幅(Idol Wiki と同レイアウト)
- [ ] アバターはイラスト未設定なのでイニシャル+カラーのプレースホルダ(後フェーズで画像差し替え)
- [ ] PHP エラーログにフェイタル無し

## アバター(生成済み)

8人分のイラスト風アバターを生成済み: `assets/writer_avatars/{key}.png`
(架空人物・フラットベクター。実在アイドル非依拠)。

- 再生成: `python3 scripts/gen_writer_avatars.py --force`(または `--only {key}`)。
  プロンプトは `config/x_writer_personas.json` の各 `avatar_prompt`。OpenAI 課金(約 $0.04/枚)。
- **featured image 設定(オーナー作業)**: 各 `writer` 投稿(slug=key)のアイキャッチに
  対応する `{key}.png` を設定すると、プロフィール/一覧のプレースホルダ(イニシャル)から
  自動でイラストに切り替わる(`inc/writer-profiles.php` が has_post_thumbnail を見る)。
  - 手順例(wp-cli, owner 実行): メディアに import → 各 writer 投稿へ set featured。
    `wp media import assets/writer_avatars/yui.png --post_id=<yui投稿ID> --featured_image`
  - 画像は stg/本番のメディアライブラリに入れる(テーマ同梱ではない)。

## 記事の執筆者バイライン(実装済み)

記事メタの「執筆」を、担当ライターの `/writers/{key}/` へのリンクにした(`content-single.php` +
`inc/writer-profiles.php` の `kpop_writer_byline()` / `kpop_resolve_post_writer()`)。

- 担当解決: 記事の**タグ(アーティスト名)で最長一致 → カテゴリ(ジャンル)→ fallback(編集部)**。
  X 投稿の `select_writer`(Python)と同じ思想を PHP で再現。
- **DB 変更なし・既存記事に遡及適用・同記事は常に同じライター**(安定割当)。
- 関数未ロード時は従来の `get_the_author()` にフォールバック。
- 反映には `content-single.php` も含む(deploy スクリプトは対応済み)。

## 後フェーズ(任意)

- バイラインのアバター小表示、記事末尾の「この記事を書いた人」カード 等の追加装飾。
