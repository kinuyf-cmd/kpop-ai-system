# 更新ルール

## ドキュメント管理方針

### 正本と副本
- **正本**: Notion（オーナー: Yuta）
- **副本**: VPS `docs/governance/` （バックアップ・参照用）

### 更新フロー
1. Notion側で内容を更新
2. 重要な変更はVPS側にも手動で同期
3. VPS側のみの変更は一時的なもの（次回Notion同期で上書きされる可能性あり）

### 自動同期（Phase 10 予定）
- Notion API → VPS `docs/governance/` への定期同期
- 差分検出・マージ
- 競合時はNotion側を優先

## config ファイル更新ルール

### GREEN zone（AI自動更新OK）
- `config/agent_directives.json` — エージェントへの指示
- `config/auto_directives.json` — 自動指示
- `config/error_patterns.json` — エラーパターン辞書
- `config/exchange_rate.json` — 為替レート

### YELLOW zone（更新後Discord通知）
- `config/seo_config.json` — SEO設定
- `config/revenue_config.json` — 収益設定
- `config/finance_targets.json` — 財務目標

### RED zone（Yuta承認必須）
- `config/safety_config.json` — 安全設定
- `config/autonomy_matrix.json` — 自律性マトリクス
- `config/org_chart.json` — 組織図
- `config/discord_webhooks.json` — Discord Webhook URL

## コード変更ルール

### 変更の安全分類
1. **ログ出力のみ**: 安全（GREEN）
2. **設定ファイル書換**: 内容により GREEN/YELLOW
3. **パイプラインロジック変更**: YELLOW（事後通知）
4. **外部API呼び出し追加**: RED（承認必須）
5. **データ削除**: RED（承認必須）
6. **pm2/nginx/sudo**: RED（承認必須）

### Git 運用
- main ブランチへの直接コミット: GREEN zone の変更のみ
- main マージ（PRからの）: RED zone（承認必須）
- force push: 絶対禁止
