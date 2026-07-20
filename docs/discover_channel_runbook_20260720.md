# Google Discover / 新チャネル獲得 runbook(2026-07-20, rev.2)

PV構造転換③「チャネル複線化」の実行runbook。

> **rev.2の訂正(重要)**: 初版は「Publisher Center登録=Discover露出の本丸」としていたが**これは誤り**。
> Google公式(Search Central「Get on Discover」)のとおり、**Discoverに載るのにPublisher Center登録は不要**。
> サイトがインデックスされ、コンテンツポリシーと技術要件を満たせば自動的に対象になる。
> Publisher Centerは「Googleニュース」向けの別プロダクト。やる価値はあるが Discover の直接スイッチではない。
> → 本runbookを Part A(Publisher Center=owner本人作業)と Part B(Discover流入を実際に伸ばす本丸)に分離。

---

## Part A — Google News Publisher Center 登録 ✅ 完了(2026-07-20)

**状態: 完了済み**(owner報告、2026-07-20)。当初「未着手の最重要タスク」と誤記していたが、
実際には登録はとっくに済んでおり、残っていたのはスクエアロゴ1点のみだった(それも2026-07-20に設定完了)。
**かつPart AはDiscover露出の前提条件ではない**(→ [[discover-does-not-need-publisher-center]])。

完了内容(パブリケーション「K-POP JOURNAL」):
- 名称・言語(日本語)・本拠地(日本)設定済み
- URL所有権 VERIFIED
- スクエアロゴ(全面塗り正方形版)アップロード済み。Googleサーバー(lh3.googleusercontent.com)にホスト、
  再読込後も表示、ボタン表記「追加」→「更新」で保存確認済み

> 効果: Googleニュース面への露出・パブリッシャープロフィール確立。Discover流入の本丸は Part B。
> なお、ここでアップした「Publisher Center用ロゴ」と、B-2の「サイトのOrganization schema用 logo」は**別物**
> (前者=Googleニュースのプロフィール画像、後者=構造化データ)。B-2はまだ未設定。

---

## Part B — Discover流入を実際に伸ばす本丸

Discover露出の実体はここ。2026-02-05のDiscover専用コアアップデート(専門性・信頼性・脱煽りを重点化)を反映。

### B-1. 技術要件(実測: 2026-07-20)

| 項目 | 状態 | 備考 |
|---|---|---|
| max-image-preview:large | ✅ 出力済 | Discoverに大きい画像で載る必須条件 |
| アイキャッチ幅1200px以上 | ✅ 96%(594件中568件) | 例外26件+今回のpost13501(596px)が是正対象 |
| Core Web Vitals | ⏳ 未実測 | PageSpeed/CrUXでLCP・INP・CLSを要計測(次スプリント自動化) |
| インデックス済 | ✅ | GSC申請パイプライン稼働 |

**残: 画像1200px未満の是正**
- post 13501(恋は飴模様)= 596×335px。1200px以上の画像に差し替え(著作権フリー素材 or DALL-E段階3)
- 他26件も同様。`tools/thumb/` で幅を実測して低解像度のものを洗い出し→順次是正

### B-2. Organization schema の強化

- **logo**: ✅ **完了(2026-07-20)**。`organizationLogo`(AIOSEO `aioseo_options` JSON内)に og-default.png を設定。
  schemaに `logo`(ImageObject 1200×630)が出力されることを実レンダ確認済み。
  設定手法: wp option get → Pythonで該当1キーのみ書換(差分1件を検証)→ wp option update。バックアップ取得済。
  ※og-default.pngは横長(1200×630)。Googleのlogo構造化データは横長も許容(実質要件=最小辺112px+)。
  将来 正方形の専用ブランドロゴを用意できれば差し替え推奨。
- **sameAs**: ✅ **現状で正**(owner確認、2026-07-20)。公式SNSはX(@lovekpopjournal)のみ=sameAsにXだけ入っているのが正しい。
  Instagram/YouTube等は未開設。存在しないURLをsameAsに書くのは逆効果なので追加しない。
  今後 公式アカウントを開設したら AIOSEO `social.profiles.urls` に追記 → sameAsに自動反映。
- **日本所在の明示**: ✅ **完了(2026-07-20)**。Organization schemaに `address.addressCountry='JP'` を出力。
  **住所は非公開のまま国のみ**(owner方針)。AIOSEOフリー版のschema設定には所在国欄が無いため、
  子テーマ functions.php の `aioseo_schema_output` フィルタで Organizationノードにaddressを注入(構文チェック+本番デプロイ+実レンダ検証済)。
  検証: `curl -s <記事> | grep -o '"addressCountry":"JP"'`

### B-3. 著者E-E-A-T(自動化で潰せる)

現状(実測): 記事schemaの `author @id` = `.../author/#author` が**graph内に実体ノードを持たない宙吊り参照**。
著者アーカイブ /author/kpop-publisher/ も404。

- AIOSEO → Search Appearance → Author で著者情報出力を有効化+編集部プロフィール(略歴・編集方針ページURL)設定
- ゴール: JSON-LD graphに Person(または明示的なOrganization著者)ノードが実体として出る
- 検証: `curl -s <記事> | grep -o '"@type":"Person"'` が1件以上

### B-4. コンテンツ側(2026-02 アップデートの重点)

- **脱・煽りタイトル**: 誇張・クリックベイトはDiscoverで沈む。事実提示型を維持([[ctr-diagnosis-by-position-band-baseline]]の直答メタと同方向)
- **K-POP縦軸の専門性**: 単発ニュースの羅列でなく、クラスタ(相関図/視聴ガイド/FAQ)で"詳しいサイト"の一貫性を出す([[pv-strategy-preemptive-cluster-v1]]の先回りクラスタと合致)
- **鮮度×常緑の両立**: 速報で入口を作り、常緑ハブで滞在を伸ばす

---

## 参考(2026-07-20取得)
- Get on Discover — Google Search Central
- Get started on Google News with Publisher Center
- How Google Discover publisher profiles work — Search Engine Land
- Google Discover February 2026 Update — TechieGigs

## Claude側で完了済み(2026-07-20)
- Part B の技術要件・schema・著者を実測(上表の数値はすべて実機calc)
- **次スプリント自動化予定**: Core Web Vitals計測 / 画像1200px未満の一覧化 / logo・sameAs・Person schemaの定期検証
