# GOLF PORT バナー ブランド統一版(2026-11-05 公開)

**公開済み**(オーナー裁定 2026-11-05)。**切替日時: 2026-11-05 18:51:26 JST**(旧=グリーン基調版 → 新=GOLF PORT正式ロゴ/アイコン+白〜淡色の無地)。
GOLF PORT 側(5e/be)の確認は公開後の事後確認(be の観点: 変形なし/色の変更なし/余白/背景との組み合わせ)。指摘があれば即修正・差し戻し可能。

## 使用素材(再保存・変換・再描画なし)
| 素材 | 実体(K-POP JOURNALのWPメディア) | md5(原本=配信=一致) | 使う場所 |
|---|---|---|---|
| 横組みロゴ 1637×435 | media 26905 / `https://www.kpopjournal.tokyo/wp-content/uploads/2026/11/logo.png` | `d1893dce2fdb140e81986fbb56a525c0` | 記事末尾・イベントページ(横長の帯) |
| アイコン 512×512 | media 26906 / `https://www.kpopjournal.tokyo/wp-content/uploads/2026/11/icon.png` | `9bcea51c41896765679dfd1c59a67a5a` | トップ右サイドバー(1:1) |
- 原本: `https://golfport.top/logo.png` `icon.png` を 2026-11-05 に取得 = GOLF PORT リポジトリ `public/logo.png` `icon.png` とバイト一致。**オーナー提供の「GOLGPORT logo.png」「Golf port icon(1).png」は、このサーバー上に見当たらず照合できていない**(提供ファイルが上と異なる場合は知らせてほしい)。
- 配信方式の比較(決定=自サイトのWPメディアに無加工で登録): 直接参照は GOLF PORT 側が `Cache-Control: public, max-age=0`(毎回再検証)で稼働にも依存。自サイトのアップロードは `max-age=31536000, immutable`、外部依存なし、再保存なし(md5一致を検証済み)。Data URI は再エンコード不要で作れるが HTML に毎回 約380KB(base64)が載るため不採用。容量(ロゴ281KB・アイコン223KB)は遅延読み込み(`loading=lazy`)・初回のみ。軽量な正式派生版が必要なら GOLF PORT(be)に依頼する。
- 差し替え手順: 新しい正式ファイルを `wp media import`(無加工)→ md5 検証 → `golfport-house-banner.php` の URL を更新 → be の確認。

## デザイン(変更したのは見た目だけ)
- 背景 #f8fafc(白に近い淡色の無地)、枠 #e2e8f0、文字 #1e293b/#475569、CTA #2563eb(白文字)=K-POP JOURNALのサイト色(GOLF PORTのブランドカラーとしては扱わない)。ロゴ専用色 #5064FA は不使用。グラデ・画像背景なし。
- 余白: ロゴ高さ(30px)の半分以上=padding 20px(スマホ18px)。アイコン(72px)は上余白36px以上。縦横比は width/height 属性+`height固定・width:auto`(アイコンは72×72)で固定、`align-self`で引き伸ばし防止。transform/filter/object-fit/opacity/clip/border-radius/mask は使用しない(テストで検査)。
- 不変: コピー/CTA文言/遷移先URL/UTM固定値/utm_content/GA4イベント名/50%可視判定/1ページ1枠/掲載対象/停止制御/「運営関連サービス」表示。

## 証跡(`evidence/`・`review/`)
- `evidence/live_verification.json` … 本番3系統×(PC/390px/320px)の実測(ロゴ読込・比率・URL・イベント・CLS・関連記事・広告枠)。`evidence/{article_footer,event_page,top_sidebar}_{pc,m390,m320}.png` … 本番の実表示。
- `review/` … 事前確認用(スクリーンショット・拡大・HTML/CSS・measurements.json)。

## 検証結果(本番・2026-11-05 18:5x JST)
- 3系統×PC/390/320 全て: バナー1枠・ロゴ/アイコン読込OK・比率一致・UTM4項目一致(utm_content=設置場所)・rel/target なし・横スクロールなし・view 1回(再スクロールでも増えない)・クリックで /record に遷移(PC)。
- バナー自体の寸法は不変(イベントページPCで高さ151px一定)。CLSは既存要因(ヘッダー速報バー/ヒーロー画像、バナーを押し下げる分のみ)でバナー起因ではない。トップに関連記事セクションは元々ない。
- 注意: この検証アクセス(ヘッドレスブラウザ)は GA4 に実イベントとして送られるため、**11/5 のGA4数値は参考値**。評価は 11/6 以降。
