# 収益化ルール v1.3（ニャース/カイリュー管轄）

## CTA挿入タイミング
- WordPress投稿後、Google/Bingインデックス送信前に実行
- `inject_revenue_links.sh` → `inject_abema_cta.sh` → `add_internal_links.sh` の順
- 失敗してもパイプラインは停止しない（エラーログに記録して続行）

## 記事タイプ別CTA設計

### フロー記事（速報/ニュース）
- CTA数: 1（記事末尾）
- 種類: 内部リンク（あわせて読みたい）
- 収益源: AdSense
- 実装: `inject_revenue_links.sh`

### 資産記事（evergreen）
- CTA数: 2（中盤 + 末尾）
- 種類: 内部リンク + 軽量アフィリエイト
- 収益源: AdSense + アフィリエイト
- 実装: `inject_revenue_links.sh` + `add_internal_links.sh`

### 収益記事（CV特化）
- CTA数: 3（導入部 + 中盤 + 末尾）
- 種類: ASP直リンク（A8/Amazon/楽天）
- 収益源: アフィリエイト最優先
- 実装: `strengthen_revenue_cta.sh`（Claude生成CTA）

## ASP優先マッチング（`config/revenue_config.json`準拠）
| カテゴリ | ASP | CTA種別 |
|---------|-----|---------|
| 美容・スキンケア(12,51-56) | A8.net | 商品レビューCTA |
| グッズ・アルバム(6,13) | Amazon Associates | 商品リンクCTA |
| 旅行・ホテル・チケット(5,11,62-70) | 楽天アフィリエイト | 予約CTA |
| 配信・視聴（ABEMA関連） | A8.net | 無料視聴CTA |
| その他 | 内部リンクのみ | あわせて読みたい |

## ABEMA CTA発動条件
- キーワード: スウパ, STREET WOMAN FIGHTER, SWF, 見逃し配信, 無料視聴, ABEMA, 視聴方法
- 最低文字数: 500文字以上
- 重複防止: class="cta-box" の既存チェック
- A8プログラムID: `config/revenue_config.json` で管理

## CTAクリック計測
- 内部リンクCTA: UTMパラメータ付与（utm_source=internal&utm_medium=cta&utm_campaign=revenue_link）
- A8リンク: A8管理画面でコンバージョン追跡
- GA4: utm_campaignベースのイベントフィルタで効果測定

## CTA必須要素
- PRを含む旨の表記（※広告・PRを含みます）
- 明確なボタンまたはリンク
- 記事内容との関連性
- `cta_templates.py` で自動付与
