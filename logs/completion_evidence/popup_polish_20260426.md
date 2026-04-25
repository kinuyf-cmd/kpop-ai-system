# Popup Polish 完了 2026-04-26

## 1. ヘッダー太字強化
- Phase11Header.tsx: mobile-link font-weight 600→900
- globals.css: .p11-header__nav-link, .p11-header__mobile-link font-weight: 900 !important
- 本番確認: font-weight: 900 3箇所検出

## 2. ```html コードブロック除去
- audit_fixer_universal.py: 正規表現修正 (複数パターン+markdown ## → h2変換)
- 一斉クリーンアップ実行: 17件 (popup 16件 + post 1件)
- 本番確認: /popup/seoul-seongsu/4337/ で ```カウント=0

## 3. 住所→MAP自動
- popup_geocoder.py 新設 (OpenStreetMap Nominatim、無料)
- popup_publisher.py: 投稿時に住所→geocode自動実行
- 詳細ページ: 緯度経度なし+住所ありの場合もGoogle Maps住所検索iframeで表示
- cron 日次07:00

## 4. メタ8項目UI刷新
- popup.module.css: metaGrid/metaCard/metaCardHighlight/metaIconWrap
- 色分けアイコン円 (40px、カテゴリ別背景色)
- 期間カードは強調 (グラデ背景+太上線6px)
- ホバーアニメーション (translateY + shadow)
- モバイル1カラム対応
- 本番確認: metaGrid/metaCard/metaIconWrap検出
