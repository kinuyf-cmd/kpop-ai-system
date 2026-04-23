# K-POP Journal AI Company — ガバナンスドキュメント

## 概要
K-POP Journal AI Company の運営ルール・組織構造・戦略をまとめたドキュメント集。
Notion上の正本をVPSにバックアップとして配置。

## Notion ページ
- 正本URL: Notion ワークスペース内「K-POP Journal AI Company」
- 更新権限: Yuta（オーナー）

## ファイル一覧

| ファイル | 内容 | 重要度 |
|---------|------|--------|
| [constitution.md](constitution.md) | 憲法 & 理念 — ミッション・基本理念・自律性3ゾーン・禁止事項 | 最重要 |
| [article_rules.md](article_rules.md) | 記事投稿ルール — 品質基準・BLOCK条件・AI語尾禁止・サムネルール | 最重要 |
| [organization.md](organization.md) | 組織状況 — 経営陣・12部署・エージェント一覧・KPI | 重要 |
| [knowledge_base.md](knowledge_base.md) | ナレッジベース — パイプライン構成・エラー辞書・技術スタック | 重要 |
| [department_logs.md](department_logs.md) | 部門ログ — ログファイル一覧・管理ルール | 参照 |
| [strategy_roadmap.md](strategy_roadmap.md) | 戦略ロードマップ — Phase 1-10・KPI目標 | 重要 |
| [batch_reports.md](batch_reports.md) | バッチ実行レポート — cronスケジュール・監視基準 | 参照 |
| [update_rules.md](update_rules.md) | 更新ルール — ドキュメント管理・config更新・コード変更 | 重要 |
| [morning_brief.md](morning_brief.md) | 朝のブリーフ — テンプレート・生成手順 | テンプレート |
| [weekly_review.md](weekly_review.md) | 週次レビュー — テンプレート・KPI項目 | テンプレート |
| [thumbnail_constitution.md](thumbnail_constitution.md) | サムネイル命令書 — v6仕様・ソース優先順位・Vision検証 | 重要 |

## 更新ルール

### 正本・副本の関係
- **Notion = 正本**: 全変更はNotionで行う
- **VPS = 副本**: バックアップ・AI参照用
- 競合時はNotion側を優先

### 更新手順
1. Notionで内容を編集
2. 重要な変更はVPS側にも手動コピー
3. `git add docs/governance/ && git commit -m "docs: update governance from Notion"`

### 自動同期（Phase 10 予定）
Notion API → VPS への定期同期を実装予定。

## 初回作成
- 作成日: 2026-04-23
- 作成者: Claude Code (Phase 9)
- ソース: Notion + コードベース実データ
