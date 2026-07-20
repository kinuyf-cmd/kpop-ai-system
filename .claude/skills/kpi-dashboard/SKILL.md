---
name: kpi-dashboard
description: KPOP JOURNAL・補助金 の主要KPIダッシュボードを自動構築・更新するスキル。GA4・Search Console・WordPress統計を統合し7指標を朝バッチで集計、data:build-dashboard と連携。「KPI確認」「ダッシュボード」「PV確認」「CTR」「収益指標」「アクセス分析」「KPI集計」といった問い合わせ時に必ず使用。100点計画 K項目の達成に必須。
---

# KPI Dashboard

## 1. 目的

数値に基づく事業判断のため、主要KPIをダッシュボードで可視化し
朝バッチで自動更新する。100点計画 K項目の達成が狙い。

## 2. 主要 7 KPI

日次PV / 主要キーワード順位(Top 50)/ CTR(SERP)/ 直帰率 /
平均滞在時間 / AdSense RPM(本番化後)/ アフィリエイト CVR(本番化後)。

## 3. データソース

- GA4 API(PV、滞在時間、直帰率)
- Search Console API(順位、CTR)
- WordPress 統計(投稿数、コメント)
- AdSense API(RPM、CTR)

## 4. 朝バッチ集計(09:00 cron)

前日24hデータ取得 → 7KPI計算 → 異常検知(前日比 ±30%以上)→
`morning-brief` スキルに統合。

## 5. 異常時の通知

- PV 急落 → [[red-team-auditor]] 連携
- 順位下落 → 該当記事をリスト化
- エラー急増 → 即時アラート

## 6. ダッシュボード生成

- `data:build-dashboard` スキルを使用
- HTML/JS で自己完結
- 配置: `/home/aiuser/.kpop_recovery/kpi_dashboard.html`

> 注: 素材では `data:interactive-dashboard-builder` という名称だったが、
> 導入済みの該当スキルは `data:build-dashboard`。こちらを使う。

## 7. ダッシュボード設計

- 折れ線グラフ(7日 / 30日 / 90日)
- ヒートマップ(時間帯 × 曜日)
- Top 10 記事 / Top 10 キーワード

## 8. 100point-rubric-judge K項目との連動

| K項目 | 基準 |
|---|---|
| K-1 | 主要KPIダッシュボードの稼働 |
| K-2 | 朝バッチの自動集計 |
| K-3 | 異常時の自動通知 |
| K-4 | 7指標すべての計測 |

## 9. 安全設計

- API キーは `/root/.credentials/` 配下に置く(平文をコード/ログに残さない)
- データ取得失敗時のフォールバック(前回値の表示等)
- 過去30日分のデータを保管

ログ: `/home/aiuser/.kpop_recovery/kpi_log.jsonl`
