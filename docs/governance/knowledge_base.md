# ナレッジベース

## パイプライン構成

### メインパイプライン
| パイプライン | ファイル | 実行頻度 | 用途 |
|---|---|---|---|
| K-POP速報 | kpop_pipeline.sh | cron 2h毎 | 速報記事の自動生成・公開 |
| 速報モニター | kpop_breaking_monitor.sh | 30分毎 (6-21時) | トレンド検知・速報判定 |
| 戦略記事 | kpop_strategy_pipeline.sh | 1日1回 | SEO戦略記事の生成 |
| 美容記事 | kpop_beauty_pipeline.sh | 1日1回 | K-POPコスメ・美容記事 |
| チャート記事 | kpop_chart_pipeline.sh | 週次 | ランキング・チャート記事 |
| ライフスタイル | kpop_lifestyle_pipeline.sh | 1日1回 | ライフスタイル記事 |
| 比較記事 | kpop_comparison_pipeline.sh | 随時 | 比較・まとめ記事 |

### パイプラインフロー（速報の場合）
1. バタフリー: WebSearchでトレンド検知
2. デオキシス: 記事本文生成（WebSearchで裏取り）
3. メタモン: タイトルリライト（複数案生成）
4. イーブイ: タイトルA/B選定
5. ガーデボワール: 品質評価
6. アルセウス: 最終監査
7. WP投稿 + サムネ設定 + X投稿

### 安全装置
- グローバルミューテックスロック: `/tmp/kpop_pipeline_global.flock`
- トピック予約システム: 重複記事防止
- check_output: 空出力・極小出力・boilerplate応答を検出して停止
- pre_publish_hook: 16項目の最終チェック（テンプレート残骸、JSON漏れ、文字数等）

## エラーパターン辞書

### 頻出エラーと対処
| パターン | 発生頻度 | 原因 | 対処 |
|---|---|---|---|
| archive_and_exit code=1 | 57/週 | 上流エージェント出力品質不足 | directive改善 |
| 出力が空 | 9/週 | WebSearch失敗・タイムアウト | 3段階リトライ |
| score=0 | 5/週 | gardevoir品質ゲート | 評価基準見直し |
| x_post失敗 | 8/週 | X API credential問題 | credential復元 |

### error_patterns.json 登録済みパターン
設定ファイル: `config/error_patterns.json`
- 各パターンに ID・検出regex・severity・auto_fix_strategy を定義
- learning_loop.py が新パターンを自動検出・登録

## 技術スタック
- OS: Ubuntu 22.04 (VPS)
- Python: 3.x
- Web: WordPress (REST API)
- LLM: Claude Sonnet 4.5 (メイン), Claude Haiku 4.5 (軽量タスク)
- 画像: PIL/Pillow
- 検索: Google Search Console API, GA4 API
- SNS: X (Twitter) API v2
- 広告: Google AdSense
- 通知: Discord Webhook
- 管理: Notion (ガバナンスドキュメント)

## ファイル構成
```
kpop-ai-system/
├── agents/           # エージェント定義 (50+ .md files)
├── autonomy/         # 自律実行エンジン
├── config/           # 設定ファイル群
├── dashboard/v2/     # ダッシュボード生成
├── data/             # ランタイムデータ
├── docs/governance/  # ガバナンスドキュメント
├── google_metrics/   # GSC/GA4連携
├── lib/              # 共有ライブラリ (200+)
├── logs/             # ログファイル群
├── pipeline/         # パイプライン制御
└── kpop_*.sh         # パイプラインスクリプト
```
