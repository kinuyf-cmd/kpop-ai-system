# DAY 13 START PROMPT

> 作成: 2026-05-22(Day12 終了時)。ブランチ rebuild-20260521、HEAD e2b97d3、origin 同期済(ahead 0)。

## 現在地
- 100point: **55/63**(未達 = H 0/5 SEO / J 1/4 収益化)。両者とも本番化C-7で点灯し最大 +8。
- 本番 www.kpopjournal.tokyo は **静的サイト(WP不在)**。唯一の WP は stg(/var/www/wp_stg、2層認証=nginx Basic `kpopadmin` + WP `kpopstg_admin`)。
- 速報DRAFT 4件 stg 投入済(post ID 398 STAYC/399 ONF/400 RESCENE/401 RIIZE、全 draft)。publish は Day14。
- M2 J 収益化はコード完成(commit ab91a0c)、delivery_enabled=false で待機。

## Day 13 タスク(確定ロードマップより)
1. **M5 着手**(内容は roadmap-tracker / kpop-100point-roadmap で確認)。
2. **H(SEO)準備**: stg 全面 noindex(prod-site-sitewide-noindex-pre-launch)が H 0/5 の主因。C-7 解除前提で、メタ description の head 配線(E-2所見/E-5)・Article schema・XMLサイトマップ・GSC 警告0 の準備。
3. **本番化方式 A/B/C 決定**:
   - A: stg WP を本番ドメインで公開(nginx に PHP ハンドラ追加)
   - B: stg WP → 静的書き出し(SSG/WP静的化)→ 本番静的更新(memory の「Next.js front」想定はこれ寄り)
   - C: 別の本番 WP 構築 + stg マイグレーション
   - → Day13 で確定、Day14 で実行。
4. **M-final 視覚 walkthrough**(ui-polish 連携)。

## Day 14(本番化)申し送り
- stg→本番公開、速報4件 publish、AdSense/GA4 配信開始(owner が ADSENSE_CLIENT_ID/GA4_MEASUREMENT_ID/active_target=production/delivery_enabled=true 設定)、100点監査。
- WP 認証ローテ(rF... 漏洩済): `STG_AUTH_ROTATION_RUNBOOK.md` 手順1。本番化前に実施。

## 運用知見(認証境界)
- stg 操作は **wp-cli + オーナー対話 sudo**(REST は2層 Basic 衝突で不可)。認証値は会話に出さず env 経由。
- 投入: `sudo bash stg_push_breaking_drafts.sh` / 検証: `sudo bash verify_stg_drafts.sh`。

## 絶対方針(継続)
- 前提を T1 で実証してから着手。Layer1引用ルール+ハルシ排除。流用前後 secrets 検査。実機密(adsense_*.json)に触れない。rebuild-20260521 で commit。error-evidence 4点。
