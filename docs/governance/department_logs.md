# 部門ログ

## ログファイル一覧

### 部門別定例会議ログ
| 部門 | ログファイル | 頻度 |
|------|-------------|------|
| 全体朝会 | logs/standup.log | 毎朝 |
| 監査部 | logs/audit.log | 毎日 |
| 編集部 | logs/editorial_meeting.log | 毎朝 |
| SEO部 | logs/seo_meeting.log | 週次 |
| 収益部 | logs/revenue_meeting.log | 週次 |
| デザイン部 | logs/design_meeting.log | 週次 |
| 経営管理 | logs/management_meeting.log | 週次 |
| 競合分析 | logs/competitive_meeting.log | 毎日 |
| パブリッシング | logs/publishing_meeting.log | 毎日 |
| マーケ・SNS | logs/marketing_meeting.log | 毎日 |
| 部署スタンドアップ | logs/dept_standup.log | 毎朝 |

### 運用ログ
| ログ | パス | 内容 |
|------|------|------|
| パイプライン実行 | logs/pipeline.jsonl | 全パイプライン実行記録 |
| 品質スコア履歴 | logs/quality_score_history.jsonl | エージェント別品質スコア推移 |
| 自律実行 | logs/autonomy_executions.jsonl | auto_executor 実行記録 |
| 学習 | logs/learning_history.jsonl | learning_loop 改善記録 |
| CEO改善キュー | logs/ceo_improvement_queue.jsonl | 改善提案キュー |
| Discord通知 | logs/discord_alert_history.jsonl | Discord送信履歴 |
| コスト | data/cost_ledger.jsonl | API呼び出しコスト記録 |

### KPIログ
| ログ | パス | 内容 |
|------|------|------|
| 記事KPI | logs/kpi_posts.jsonl | 記事別PV・CTR・収益 |
| 日次KPI | logs/kpi_daily.jsonl | 日次集計 |
| エラーKPI | logs/kpi_errors.jsonl | エラー集計 |
| X投稿 | logs/x_post.log | X投稿実行ログ |
| GSCメトリクス | logs/gsc_metrics_latest.json | GSC最新データ |

## ログ管理ルール
1. ログファイルは `logs/` ディレクトリに集約
2. JSONL形式を標準とする（1行1レコード）
3. タイムスタンプは ISO 8601 (JST) を使用
4. 機密情報（APIキー等）はログに書かない
5. ローテーション: 30日以上前のログは圧縮保管
