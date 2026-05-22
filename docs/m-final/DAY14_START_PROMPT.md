# Day 14 開始プロンプト — 本番化フェーズ (2026-05-24 想定)

## 現状
- 100point: **57/63**。未達は H(2/5)・J(1/4)、**両方とも本番化トリガー**。
- 本番化(noindex解除+配信開始)で 57→63 が射程。
- ブランチ: rebuild-20260521
- 本番化方式: **A(stg WP を本番ドメインで公開)** 確定
- stg コンテンツ: publish34 + draft57(速報4+救出53)、サムネ/タグ/メタ/インライン色 整備済

## Day 14 本番化手順

### ① WP セキュリティ硬化(オーナー sudo)
- WP本体/プラグイン/テーマ最新化
- WP bot 新規ユーザー作成 + アプリパスワード発行 → .env(WP_USER/WP_PASS)更新
- 旧 kpop-bot/kpop-bot2(rF.../vl1H...、漏洩済)を WP管理画面で削除
- /wp-admin IP制限 or Basic認証、xmlrpc無効、ファイル編集無効、fail2ban

### ② nginx 本番構成変更(オーナー sudo)
- kpopjournal.conf に PHP-FPM ハンドラ + WPルーティング追加
  (現: 静的`/var/www/kpopjournal_site` → WP `/var/www/wp_stg` or 本番WP path)
- stg の Basic認証(.htpasswd_stg)解除(本番公開)
- 投稿経路確立 + 認証検証(DRAFT POST→201→即削除)

### ③ WP 設定(本番化トリガー)
- `blog_public=1`(noindex解除)→ **H-1/H-2 自動改善**
- SITE_URL を本番ドメインに / active_target=production(revenue_settings.json)

### ④ 収益化点灯(J → 4/4)
- AdSense: `ADSENSE_CLIENT_ID`(ca-pub-XXX) + `ADSENSE_ENABLED=true`
- GA4: `GA4_MEASUREMENT_ID`(G-XXX)
- CTA: new_post_injector.py を本番記事に適用(投稿経路確立後)

### ⑤ コンテンツ公開
- 速報4件(ID 398-401) + 救出53件 draft を publish
- (任意)カニバリ最終trash 5件、固定ページmeta、カテゴリ偏り調整

### ⑥ 本番化後 監査(H/J 点灯確認)
- pa11y/Lighthouse 実測(本番URL、Basic認証なしに) → H-1 SEO 95+ 確認
- GSC 警告0確認(noindex解除後)
- 100point-rubric-judge で H/J 再採点 → 63/63 射程
- 視覚 walkthrough(本番URL、全ページ)

## M11.5.H 別 repo 化(オーナー GitHub repo 作成)
- `.kpop_recovery` → `kpop-recovery-docs`(private)
- 子テーマ `stage2/` → `kpop-wp-theme`(private)

## 本番化前 必須 ToDo
- WP bot パスワード新規発行(旧 rF.../vl1H... 無効化)← 漏洩済
- Basic認証ローテ(stg→本番なら不要に)
- kbuzzlab.com LINE証跡保管
- E-2 アーティスト画像投入(owner script)

## 残タスク(低優先)
- post_audit.sh 未復元の3監査項目(漢字率/内部リンク本数/タイトル20字)
- import_to_wp.py と import_recovered_to_stg.py の統合(本文クリーン化+サムネ+タグの正規1本)

## Day14 ロードマップ
本番化実行 → H/J 点灯 → 100点監査 → 公開確認。target_completion 2026-06-05 維持。
