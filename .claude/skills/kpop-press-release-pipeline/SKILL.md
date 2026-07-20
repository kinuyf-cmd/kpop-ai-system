---
name: kpop-press-release-pipeline
description: KPOP JOURNAL が取引先(EXODUS Ent./最愛ドルスター等)から受領したプレスリリース・提供素材を、記事化→公開→投稿後8フェーズ点検→拡散→取引先への掲載報告まで一気通貫で対応するオーケストレーションスキル。プレスリリース提供という外部関係者がからむ案件特有の「画像受け渡し・出典/画像提供表記・X スレッド投稿・取引先報告メール・関係構築」を成文化する。「プレスリリース」「press release」「PR資料」「提供素材で記事」「最愛ドルスター」「EXODUS」「取引先から記事依頼」「掲載報告」「掲載完了メール」「企画情報をもらった」「投稿後チェックして拡散して報告まで」といった問い合わせ時に必ず使用。記事本体の生成ルール(著作権・引用率・字数・ハルシネーション検証)は kpop-citation-article(Layer2)に委任し、本スキルはその前後の取引先対応フロー全体を束ねる。X投稿の文面ルールは x-posting-rules、公開前後監査は audit-rules、引用作法は citation-rules に委任。
---

# KPOP Press Release Pipeline

## 1. 目的

取引先からプレスリリース・提供素材を受け取って記事化する案件は、通常の引用記事と
違い「**社外の関係者がいる**」点が本質的に異なる。記事の品質だけでなく、出典・画像
クレジットの誠実さ、取引先への報告、次の供給につながる関係構築までが成果に含まれる。

このスキルは、記事生成そのもの([[kpop-citation-article]] Layer2)を中核に据えつつ、
その前(素材受領・画像受け渡し)と後(投稿後点検・拡散・取引先報告)を束ねる
オーケストレーターである。EXODUS Ent./最愛ドルスター(担当 村井真悠様)が継続的に
供給する見込みで(owner 2026-06-26)、毎回同じ品質と誠実さで高速に回すために定型化する。

## 2. レイヤー判定とゴール

- プレスリリース由来 = **Layer 2(リリース引用、引用率上限60%)**。カテゴリは通常 `news`。
- 字数は **owner 指示の範囲を優先**(例: 1,200〜1,800字)。プレスリリース1件の事実報道は
  短くなるのが自然で、`post_audit` の「3000字必須CRITICAL」は Layer2 では想定内。
  **水増しは提供資料に無い記述=ハルシネーションを生むので絶対にしない**([[kpop-citation-article]] §6)。
- ゴール: ①誠実で読みやすい記事 ②正しい出典・画像クレジット ③拡散 ④取引先との関係構築。

## 3. 全体フロー(9ステップ)

記事を**書く前**に、まず `kpop-citation-article` のLayer2ルールを読むこと。
本スキルはその外側の段取りを定義する。

```
[0] 素材受領・整理 → [1] 記事生成(委任) → [2] 出力物の確定 → [3] 投稿(stg WP)
→ [4] 画像受け渡し&figure挿入 → [5] 公開 → [6] 投稿後8フェーズ点検 → [7] 拡散(X)
→ [8] 取引先への掲載報告メール
```

### [0] 素材受領・整理
- 事実(順位・票数・締切・今後の企画・公式URL)を箇条書きで確定する。
- **公式SNS/サイトURLは実在確認してから載せる**。WebFetch で到達と名称を確認し、
  確認できないもの(URL不明のブログ等)は出典から外す。X共有の `?s=20` 等の
  トラッキングパラメータは除去して素のURLにする。
- 取引先の社名・担当者名は**記事本文には出さない**(社内メールのみ)。

### [1] 記事生成 — kpop-citation-article(Layer2)に委任
- タイトル案複数 / メタ説明(110-130字) / 英数字slug / カテゴリ / alt / キャプションを作る。
- 宣伝色を抑え事実ベース。取引先紹介は記事後半に簡潔に。メール本文の丸写し禁止。
- H2 は3個以上。インライン color/background 禁止(テーマCSSのクラスを使う)。

### [2] 出力物の確定
- 本文HTMLは scratchpad にファイル保存し、`<[^>]+>` 除去後の字数・H2数・必須要素
  (票数・順位・出典URL)を機械チェックしてから投稿に進む。

### [3] 投稿(stg WP)
- `sudo /usr/local/sbin/kpop/kpop-wp-rw.sh post create --post_type=post --post_status=draft ...`。
- **本文は stdin パイプ禁止**。`CONTENT=$(cat file)` してから `--post_content="$CONTENT"` に
  直接渡す([[wp-post-update-stdin-piping-data-loss]])。`--porcelain` で post_id を得る。
- メタ説明は AIOSEO テーブルへ直INSERT: `wp_aioseo_posts (post_id,title,description,created,updated)`
  ([[aioseo-meta-in-wp-aioseo-posts-table]])。RWラッパーの db query は WHERE 必須・DDL禁止。

### [4] 画像受け渡し & figure 明示挿入 ★ハマりどころ
- 添付画像のパスが `/Users/...`(Mac側)で来ても**この環境からは読めない**。SSHで同一
  サーバーにいる構成なら owner のターミナルも `~/` はサーバー側を指す。→ **owner に
  stg WP の Media へ直接アップロードしてもらう**のが確実([[wp-bot-users-absent-only-kpopstg-admin]])。
- アップ後、`wp_posts WHERE post_type='attachment' ORDER BY ID DESC` で新規IDを特定。
  寸法・タイトルで投票結果画像/ロゴを取り違えないよう確認する。
- アイキャッチ: `post meta update <post> _thumbnail_id <att>`。
  画像alt: `post meta update <att> _wp_attachment_image_alt "..."`、
  キャプション: `post update <att> --post_excerpt "..."`。
- **アイキャッチはテーマが「ヒーロー画像」として本文上部に大きく自動表示する**
  (`<figure class="kpop-single-hero">` 内の `wp-post-image`)。だが2つ弱点がある:
  ①テーマが alt を記事タイトルで上書きする(要件語を含まない) ②figcaption を出さないので
  「画像提供」クレジットがページに出ない。
- **やってはいけない対処**: 同じ画像を本文先頭にも `<figure><img></figure>` で挿入すること。
  ヒーロー画像と本文画像が**同一画像の二重表示**になる(実際に起きた失敗)。
- **正しい対処**: 本文に画像は**入れず**、ヒーロー画像の直下に来るよう、リード文の直後へ
  クレジット行だけを置く。これで重複なく出典表記を満たす:
  ```html
  <p>リード文……。</p>
  <p class="kpop-image-credit"><small>▲「<企画>」投票結果。画像提供: <提供元></small></p>
  ```
  alt要件は attachment 側の `_wp_attachment_image_alt`(要件語を含める)に持たせ、
  クレジット行で出典をページ表示する。挿入後は必ず実HTMLで `kpop-single-hero` が1件・
  本文に重複 `<img>` が無いことを確認する。
- 提供元画像のクレジット(「画像提供: ◯◯」「提供: ◯◯ Ent.」)は**絶対に消さない**。

### [5] 公開
- `post update <post> --post_status=publish`。本番URL(slug permalink)に curl で HTTP 200 を確認。

### [6] 投稿後 8フェーズ点検
詳細は `references/post_publish_phases.md` を参照(チェック項目とコマンド例)。要点:
1. 表示(HTTP200/H1/事実/提供元・画像提供表記/誤字) — **実HTMLを見て確認**([[verify-rendered-output-not-just-code]])
2. SEO(title/meta 110-130字/slug不変/canonical/noindexなし/OGP/alt)
3. 画像(アイキャッチ/見切れなし/altに要件語/キャプション提供元/メディアalt-caption)
4. 内部リンク(関連記事3-5本→新記事へ被リンク。追加ID・文言をログ化。本文末尾追記は非破壊で)
5. GSC(`venv_kpi/bin/python3 lib/gsc_indexing.py --url`。当日重複は skipped_dup=正常。sitemap収録確認)
6. SNS文3案(ニュース型/共感型/結果強調型)
7. 取引先報告メール作成
8. 最終レポート(9項目: 各フェーズ結果+未対応+次の1アクション)

### [7] 拡散 — X 投稿(x-posting-rules 準拠)
- **メイン本文(URLなし)＋ URL をリプライに分離**したスレッド形式。
  `python3 google_metrics/post_to_x.py "本文"` → 得た TWEET_ID で
  `python3 google_metrics/post_to_x.py "記事はこちら👇\nURL" --reply-to <TID>`。
- ハッシュタグ最大3、内部メトリクス/GSC数値を入れない、HTMLエンティティを残さない。
- 投稿前に `validate_credentials()` で認証OKを確認。投稿後 `config/x_post_queue.json` に
  posted=true と tweet_id を記録し、未使用案は重複防止で除去。
- **scoring/tracking/A-B test 系には触らない**。
- X投稿は外部公開アクション。**owner の明示指示があるときのみ実投稿**し、無ければ queue 保存に留める。

### [8] 取引先への掲載報告メール
- 雛形 `templates/partner_outreach/press_release_publish_report.md`(プロジェクト側)を使う。
- 含める: 資料提供への御礼 / 掲載完了 / 記事URL / 今後も情報共有を依頼 / 取材・インタビュー
  相談の打診 / 外部配信(Yahoo!ニュース等)は**未実施を誠実に**書き、SEO・SNS・自社発信の
  強化を伝える。**実態以上の表現は禁止**(「Yahoo配信中」等を書かない)。
- メール送信は外部アクション。**文面はここで生成し、送信は owner が実施**。

## 4. 禁止事項(取引先案件の信頼を守るための絶対則)
- slug 変更・URL 変更禁止(公開後は特に)。
- 事実未確認の追記禁止(提供資料に無い日付・数値・発言を足さない)。
- Yahoo!ニュース配信中など**実態以上の表現**禁止。
- 提供元画像の**出典/画像提供表記を消さない**。
- A/B test・tracking・scoring に触らない。
- 取引先の担当者名・社名を記事本文に出さない。

## 5. 関連スキル/メモリ
- 記事生成中核: [[kpop-citation-article]](Layer2)。引用作法: citation-rules。監査: audit-rules。
- X文面: x-posting-rules。
- フロー全体の運用知見: メモリ [[press-release-to-article-workflow]]。
- 8フェーズの具体コマンド: `references/post_publish_phases.md`。
