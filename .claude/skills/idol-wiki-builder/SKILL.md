---
name: idol-wiki-builder
description: KPOP JOURNAL の Idol Wiki(アーティストハブページ)を構築するスキル。CPT UI + ACF で69組のアーティスト・グループのプロフィールページを作り、画像・基本情報・メンバー・関連記事を一元表示。「Idol Wiki」「アーティストページ」「グループプロフィール」「ハブページ」「アーティスト登録」「69組」といった問い合わせ時に必ず使用。
---

# Idol Wiki Builder

## 1. 目的

KPOP JOURNAL の差別化機能であるアーティストハブページ群を構築する。
SEO 上のハブページとして機能し、個別記事との回遊を生む。

## 2. 技術スタック

- **CPT UI** プラグイン(カスタム投稿タイプ)
- **ACF** プラグイン(高度なカスタムフィールド)
- 子テーマ `generatepress-kpop` に専用テンプレート

> 注: CPT 採用は元サイト構成(標準 posts のみ)からの変更点。
> 既存記事(標準 posts)とは独立して動くため影響は出ないが、
> 構成変更であることを `PHASE_C_INVENTORY` 等と合わせて認識しておく。

## 3. カスタム投稿タイプ

- `idol`(個人アーティスト)
- `group`(グループ)

## 4. ACF フィールド定義

`artist_image`(メイン画像)/ `logo`(ロゴ・公式マーク)/
`debut_date` / `agency` / `nationality` / `genres`(複数選択)/
`members`(リピーター: name, position, birthday, image)/
`sns_official_x` / `sns_official_instagram` / `sns_official_youtube` /
`related_artists`(他アーティストへのリンク)/ `latest_album` /
`awards`(リピーター)。

## 5. テンプレート(single-idol.php)

- ヘッダー: 画像 + ロゴ + 基本情報
- メンバープロフィール(グループの場合)
- 関連記事の自動表示(§7)
- 公式 SNS リンク / ディスコグラフィー

## 6. インデックスページ /idol-wiki/

- アルファベット順 / 五十音順
- 検索可能
- グループ・個人のフィルタ

## 7. 関連記事の自動表示ロジック

- アーティスト名タグでマッチング
- カスタム分類 `artist_tag` で連動
- 最新10件を表示
- 個別記事 ⇔ Wiki の双方向リンクを張る

## 8. 69組の優先登録順

- **上位ティア**: BTS, BLACKPINK, NewJeans, IVE, NCT, Seventeen,
  ENHYPEN, aespa, TWICE, Stray Kids
- **中位ティア**: その他の主要グループ・ソロ
- **下位ティア**: 新人・小規模

## 9. 100point-rubric-judge E項目との連動

| E項目 | 基準 |
|---|---|
| E-1 | 69組の基盤ページが存在 |
| E-2 | サンプル5組の完全データ |
| E-3 | 関連記事の自動表示 |
| E-4 | アルファベット順検索 |
| E-5 | 個別記事 ⇔ Wiki の双方向リンク |

## 10. 安全設計

- 既存記事への影響なし(カスタム投稿タイプは独立)
- WordPress 標準機能の範囲で実装
- SEO に有効な構造化データを自動生成
- アーティスト画像はライセンス安全なもの(Wikimedia 等)を使う
