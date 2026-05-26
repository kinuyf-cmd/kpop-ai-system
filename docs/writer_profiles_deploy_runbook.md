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

## デプロイ(オーナー作業)

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

## 後フェーズ

- アバターのイラスト生成 → 各 `writer` 投稿の featured image に設定(設定すれば自動でプレースホルダから切替)。
- 記事末尾の署名(ー ゆい 等)から該当ライターの `/writers/{key}/` へリンク(content-single.php 拡張)。
