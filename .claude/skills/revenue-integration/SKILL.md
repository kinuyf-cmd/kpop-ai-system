---
name: revenue-integration
description: KPOP JOURNAL の収益化導線統合スキル。AdSense・A8.net アフィリエイト・GA4計測を統合し各記事に CTA を自動配置、本番化(Phase C-7)時に動作開始。「収益化」「AdSense」「アフィリエイト」「CTA配置」「広告タグ」「A8.net」「収益タグ」といった問い合わせ時に必ず使用。100点計画 J項目の達成に必須。
---

# Revenue Integration

## 1. 目的

月額収益を発生させるため、収益化導線を統合する。
100点計画 J項目の達成が狙い。本番化(Phase C-7)時に動作開始。

## 2. 統合する3つの収益源

- Google AdSense(ディスプレイ広告)
- A8.net(アフィリエイト主要3プログラム)
- 楽天・Amazon アソシエイト(K-POP グッズ)

## 3. AdSense 設定

- 自動広告 ON
- 手動配置: 記事冒頭・本文中央・記事末尾・サイドバー
- Ad Inserter プラグインを使用

## 4. A8.net 設定

主要3プログラムを選定: K-POP グッズ販売 / 韓国旅行(航空券・ホテル)/
K-Beauty 化粧品。各記事のカテゴリに応じて CTA を配置。

## 5. GA4 イベント追跡

`page_view` / `scroll`(25/50/75/100%)/ `outbound_click`(広告クリック)/
`affiliate_click`。

## 6. CTA 配置ルール

- 自然な文脈に挿入する
- 過剰配置を避ける(1記事 3〜5箇所まで)
- モバイル最適化

## 7. 本番化(Phase C-7)前の準備

AdSense アカウント承認の確認 / A8.net パートナー承認 /
GA4 プロパティ設定 / タグマネージャ準備。

## 8. 100point-rubric-judge J項目との連動

| J項目 | 基準 |
|---|---|
| J-1 | AdSense 配信中 |
| J-2 | A8.net 主要3プログラム動作 |
| J-3 | GA4 計測動作 |
| J-4 | 各記事への CTA 配置 |

## 9. 安全設計

- 計測前にアフィリエイトタグの動作を stg で検証する
- 規約違反の確認(AdSense ポリシー、薬機法 等)
- [[hojokin-legal-boundary]] と整合させる
- 過剰広告でユーザー体験を損なわない

## 10. KPI 連動

- [[kpi-dashboard]] で収益・CVR を監視する
- 異常時は revenue-integration が自動アラートを出す

ログ: `/home/aiuser/.kpop_recovery/revenue_log.jsonl`
