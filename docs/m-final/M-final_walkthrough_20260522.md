# M-final 視覚 walkthrough 所見 (2026-05-22 Day13)

## 主要publishページ巡回(curl HTMLレベル)
全ページ良好: lang属性✓ / h1単一 / alt無しimg 0件
- トップ / category(news/beauty/comeback/oshikatsu/popup) / artists/
- ※pa11y は当セッション未インストール。HTMLレベルの基本a11yチェックで代替。
  本格 axe/pa11y 計測は本番化前にBasic認証埋め込みURL方式で別途([[stg-perf-ceiling-92-server-side]])。

## 取り込み記事(draft 53件)の本文a11y
| 項目 | 結果 |
|---|---|
| alt無しimg含む記事 | ✅ 0件 |
| h2見出し有り | ✅ 53/53 |
| インライン color/background | 🚨 13件(citation §7-2違反) |

## 🚨 インライン色 13記事(要判断)
救出記事に「情報ボックス(枠線+背景色のコールアウト)」が多用され、styleに色指定:
- 装飾ボックス: `background:#faf5ff`(薄紫)/`background:#fff0f5`(薄桃)/`background:#1a1a2e`(濃紺)等
- キャプション文字: `color:#555`/`color:#666`(白背景でAA通過)
- 強調見出し: `color:#e040fb`/`color:#c2185b`(コントラスト要確認)

問題:
- citation skill §7-2「インライン color/background 禁止」に抵触
- 一部(濃紺背景#1a1a2e + 蛍光紫#e040fb 等)はWCAG AAコントラスト懸念
- テーマCSSで制御できない

選択肢:
- A. インライン color/background を機械除去(装飾ボックスは枠線/余白は残り、色だけ消える→地味になるが安全)
- B. インラインstyleをテーマCSSクラスに置換(.kpop-callout 等、見た目維持+AA担保。工数中)
- C. 本番化前に目視で、AA違反のものだけ修正(残りは許容)
- 推奨: A(機械的・確実・安全)or B(品質高いが工数)。本番公開記事の品質ゲートとして対応すべき。

## walkthrough 総括
- ページ構造a11y(lang/h1/alt/見出し): ✅ 良好
- 取り込み記事のインライン色13件: 要対応(本番公開前)
- カテゴリnews偏り(45件): 別途調整候補(本番化前後)
- サムネnews.png偏り: 汎用で一覧成立、個別化は本番化後
