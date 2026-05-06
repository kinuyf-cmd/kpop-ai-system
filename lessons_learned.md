
## #131: a8mat ID命名衝突
既存配置案件（a8_materials.json）と新規Phase 30バナー案件（a8_banners.json）が
同じa8mat ID命名規則だが値は別。上書き時は a8_master.json と a8_banners.json の
二重突合必須。hybrid_banner_matrixが参照するキーはa8_banners.json内に限定すること。

## #132: バナーサイズ揃いの非対称
NEWT/MATILDA/italki = 300x250のみ取得可。position_topスキップ判定を
size_limitation フィールドで明示し、cta_genre_map.json側の制約処理と連動。
728x90がない案件をposition_topに指定するとSP(320x50)フォールバック、
それもなければスキップ。テスト時は全ポジションの出力を確認すること。
