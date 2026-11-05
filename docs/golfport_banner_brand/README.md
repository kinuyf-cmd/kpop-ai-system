# GOLF PORT バナー ブランド版(公開前確認用・本番未反映) 2026-11-05

**これは公開前の確認用です。本番には出していません。** 本番反映は GOLF PORT 側(be)の確認が済んでから。

## 5e が求めた確認の4点
1. **スクリーンショット**(`review/`): 実寸 `pc_footer.png` `pc_square.png`(PC)、`mobile_footer.png` `mobile_square.png`(スマホ・2倍密度)。ロゴ拡大(3倍) `pc_logo_zoom.png` `mobile_logo_zoom.png`。
   - 3か所の対応: 記事末尾(kdrama)=横長・イベントページ(MAMA/KGMA/MMA/AAA)=同じ横長・トップ右サイドバー=1:1。記事末尾とイベントページは同一デザインで、違うのは `utm_content`(article_footer / event_page)だけ。
2. **HTML と CSS**: `review/banner_markup.html`(ロゴの指定)、`review/banner.css`(縦横比・余白・背景色の値)。実装 `themes/generatepress-kpop/golfport-house-banner.php`。
3. **ロゴは正式ファイルそのもの**: `<img src="https://golfport.top/logo.png" width="1637" height="435">` で本番の正式ファイルを**直接参照**している。当方でファイルを保存・変換・再エンコード・描画していない(複製を持たない)。
   - 参照時点の `logo.png` = 1637×435 / 280713 bytes / md5 `d1893dce2fdb140e81986fbb56a525c0`、`icon.png` = 512×512 / md5 `9bcea51c41896765679dfd1c59a67a5a`(取得日 2026-11-05。icon.png は今回使っていない)。
   - 画像は遅延読み込み(`loading=lazy`)。縦横比は width/height 属性(1637:435)と CSS(`height:30px; width:auto`)で固定。
4. **公開前の確認用**であり、本番反映は be の確認後。

## be の4観点に対する実測(`review/measurements.json`)
| 観点 | 結果 |
|---|---|
| 変形なし | 描画 112.9×30.0(比率3.763)= 元 1637:435(3.7632)。1:1側 143.0×38.0(3.7632)。ロゴの規則に transform/filter/object-fit/opacity/clip/border-radius/mask なし(テストで検査) |
| 色の変更なし | 画像そのまま。ロゴ専用色 #5064FA はUIに使っていない。CSSの色変更・不透明度変更なし |
| 余白 | ロゴ高さの半分以上(要件)。実測: 横長 21px(≥15)、1:1 は上下左右 77px以上。スマホ横長 19px(≥15)。padding 20px(スマホ18px) |
| 背景との組み合わせ | 白〜淡色の無地 #f8fafc(グラデーション・画像なし)。サイトの青は背景/補助色に使っていない |

## 色の扱い(5e/be の指示どおり)
- ロゴの周りは淡色の無地(#f8fafc)、枠 #e2e8f0、文字 #1e293b / #475569。
- **CTA ボタン #2563eb は「K-POP JOURNAL のサイト色」**であり、GOLF PORT のブランドカラーとしては扱わない(5e 了承済み)。
- 旧グリーン案・自作のゴルフ場イラスト(SVG)は撤去。ロゴの縦組み/白抜き/簡略版は作っていない。

## 変えていないもの
コピー(ゴルフの思い出、ひとつに。/ラウンド・練習・写真を記録して振り返る。/GOLF PORTを見てみる)、遷移先 URL・固定4つのUTM・utm_content、「運営関連サービス」表示、枠別 ON/OFF、GA4 イベント。禁止表現(効果の言い切り・完全無料/すべて無料・最上級・実名/写真・料金/返金の数字)は含まない。

## 権利の台帳について
画像は GOLF PORT の正式ファイルの直接参照のみ。当方で作った画像ファイルは無い(スクリーンショットは確認用の画面キャプチャ)。台帳に載せる必要のある「作った版のファイル」は `review/` 一式(確認用スクリーンショット・HTML/CSS)。
