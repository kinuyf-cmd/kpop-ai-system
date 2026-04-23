# バッチ実行レポート

## 定期バッチ一覧

### cron スケジュール（crontab.txt 準拠）

| 時刻 | 頻度 | ジョブ | 説明 |
|------|------|--------|------|
| 05:00 | 毎日 | growth_monetization.sh | 成長・収益化日次処理 |
| 05:30 | 毎日 | fetch_yesterday_metrics.py | GSC/GA4 前日メトリクス取得 |
| 06:00 | 毎日 | daily_audit.sh | 日次品質監査 |
| 06:00 | 毎日 | birthday_article.sh | 誕生日記事自動生成 |
| 06:30 | 毎日 | kpi_feedback_loop.py | KPIフィードバック → agent directive更新 |
| 07:00-21:00 | 2h毎 | kpop_pipeline.sh | メインパイプライン |
| 07:00-21:00 | 30分毎 | kpop_breaking_monitor.sh | 速報モニター |
| 07:30 | 毎朝 | daily_standup.py | 朝会データ生成 |
| 08:00 | 毎日 | morning_report.py | CEOモーニングレポート |
| 09:00 | 毎日 | watchdog.py | システム監視 |
| 11:00 | 毎日 | discord_ceo_report.py | Discord日次レポート |
| 12:00 | 2h毎 | dashboard/v2/render_dashboard.py | ダッシュボード更新 |
| 15:00 | 毎日 | competitor_monitor.py | 競合サイト監視 |
| 21:00 | 毎日 | kpop_strategy_pipeline.sh | 戦略記事パイプライン |
| 21:30 | 毎日 | improvement_engine.sh | 改善エンジン実行 |
| 22:00 | 毎日 | learning_loop.py | パターン学習・自動改善 |
| 03:00 | 毎日 | auto_executor.py | 自律実行（GREEN zone適用） |

## レポート生成場所

### 日次レポート
- `data/meetings/general/standup_YYYY-MM-DD.md` — 朝会議事録
- `logs/daily_report_YYYYMMDD.md` — 日次総合レポート
- `logs/ceo_action_queue.jsonl` — CEO行動キュー

### 週次レポート
- `logs/quality_weekly.jsonl` — 品質週次集計
- `logs/revenue_daily.jsonl` — 収益週次推移
- `logs/learning_history.jsonl` — 学習履歴

### 月次レポート
- `logs/cost_report_monthly.json` — コスト月次レポート
- `logs/kpi_monthly_snapshot.json` — KPI月次スナップショット

## バッチ監視

### 異常検知基準（safety_config.json）
- 連続失敗: 3回でパイプライン緊急停止
- 日次エラー閾値: 15件で警告
- PV低下: 前日比50%以下で警告
- CTR低下: 前日比30%以下で警告
- 12時までにゼロ投稿で警告

### ウォッチドッグ
- `lib/watchdog.py` が全バッチの実行状態を監視
- 異常検知時は Discord `urgent_errors` チャンネルに通知
- 自動修復試行: 最大3回/日（`max_auto_repair_per_day`）
