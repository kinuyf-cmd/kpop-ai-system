---
name: orchestration-leader
description: KPOP JOURNAL・補助金 の AIマルチエージェント体制全体を指揮する「脳」役割のメタスキル。Claude=リード、T1=実装、RED/BLUE/QA/skill-evolution=専門エージェントの階層を管理し、Claude Managed Agents の Multi-agent Orchestration・Outcomes・Dreaming、Webhook、Prompt Caching を統合する。「全体管理」「並列実行」「エージェント指揮」「Orchestration」「マルチエージェント」「AI体制」「並列タスク」「エージェント間連携」といった問い合わせ時に必ず使用。他の全スキルの上位に位置する。
---

# Orchestration Leader

## 1. 目的

AI エージェント階層の「脳」役割を明示化する meta-skill。

- 並列実行で全体スループットを上げる(現状の逐次実行から大幅短縮)。
- Outcomes による自動採点で「嘘の完了宣言」を機械的に検知する。
- Dreaming(申請承認後)でメモリを進化させ、Lessons Learned を自動化。
- 1人運営 + AI の限界を、エージェント階層と並列化で突破する基盤。

## 2. AI エージェント階層

- **[脳] Claude(claude.ai)** — 戦略立案・判断・調整・最終承認。
  16項目ロードマップ統括、オーナーとの対話インターフェース。
- **[副脳]** — Outcomes 採点器 / Dreaming(学習統合)/ Memory(永続記憶)。
- **[実装エージェント] T1(Claude Code on VPS)** — 実装・コード・サーバー操作。
- **[専門エージェント群]** — [[red-team-auditor]] / [[blue-team-repair]] /
  [[qa-test-generator]] / `skill-evolution` / 記事生成パイプライン(将来並列化)。

## 3. 役割定義(階層別)

- **脳**: 全体戦略の決定、優先順位の判断、エージェント間調整、
  オーナーへの説明・確認、[[100point-rubric-judge]] と [[roadmap-tracker]] の統括。
- **実装エージェント**: 脳の指示を実装に変換、コード・サーバー操作、
  完了エビデンス収集([[error-evidence]])、脳への結果報告。
- **専門エージェント**: 専門領域の自律実行(検出・修復・テスト・進化)、
  結果を脳に集約、必要に応じ [[owner-decision-queue]] 経由でオーナー判断を仰ぐ。

## 4. 通信プロトコル

- **Webhook**: エージェント完了通知 → 脳が次の判断。失敗・エラーは即時アラート。
- **Notion**: 共有メモ(ハンドオフ)、各エージェント状態、オーナーレポート。
- **Mem**: 永続記憶(セッション越境)、エージェント固有の学習。
- **MCP**: 外部ツール連携(Slack/Notion/Google Drive/GitHub 等)。
  WordPress MCP / GA4 MCP は将来の追加候補。
- **ファイルベース(同一VPS)**: `/home/aiuser/.kpop_recovery/*.jsonl`(追記ログ)
  と `*.json`(状態)を各エージェントで共有。

## 5. Claude Managed Agents 機能の統合

> このセクションの機能は **Claude Managed Agents** の機能群で、
> 2026-05-06 の "Code with Claude 2026" で発表されたもの。
> 実装着手前に最新の公式ドキュメントで仕様・提供状況を再確認すること
> (availability は変わりうる)。

- **Multi-agent Orchestration**(公開ベータ): リードエージェントがジョブを
  細分化し、専門サブエージェントへ並列委任。共有ファイルシステム上で作業し、
  リードの全体コンテキストに貢献。例: 記事10本を企画・執筆・サムネ・SEO
  担当に並列分担。
- **Outcomes**(公開ベータ): 別の採点エージェントが、出力をルーブリックで
  独立した文脈で評価してから引き渡す。`kpop-article` の HARD_FAIL や
  `error-evidence` の4点セットを機械的に確認し、嘘の完了宣言の検知を強化。
- **Dreaming**(research preview・申請制): セッション間でメモリを洗練し、
  エージェント横断の共通学習を引き出す。Lessons の手動運用を自動化。
  申請承認後に有効化。
- **Agent Skills**(一般提供): 既存運用。progressive disclosure で
  コンテキスト消費を最小化。`skill-evolution` で動的進化。
- **Code Execution / Web Search / Web Fetch**(API): KPI計算・GA4分析・
  K-POP 最新情報のリアルタイム取得。知識カットオフ問題を解消。
- **MCP Connectors**(一般提供): Mem / Notion / Context7 等を運用中。
- **Prompt Caching**: SKILL.md 群をキャッシュし、ロード時間・API コストを削減。
- **Webhooks for Agent Completion**: T1 完了時に Slack/Discord/メール通知。

## 6. 1日のフロー(理想形)

- 07:00 脳が朝バッチ計画 → 07:05 並列実行開始(RED監査 / 記事生成 /
  データ収集 / 補助金テンプレ最適化)→ 07:30 Outcomes 採点 →
  07:35 BLUE が RED 検出を修復 → 07:45 脳が統合 →
  08:00 オーナーに朝サマリ + 判断事項(owner-decision-queue)。
- 12:00 中間バッチ / 17:00 夕方バッチ / 21:00 夜バッチ(X投稿・
  roadmap-tracker 更新)/ 23:00 QA 日次テスト / 00:00 Dreaming(承認後)。

## 7. エージェント間の競合解決

- **同時実行の競合**: ファイルロック(同一ファイルへの同時書き込み防止)、
  排他制御(BLUE が修復中は RED が触らない)、優先順位
  (CRITICAL > HIGH > MEDIUM > LOW)。
- **判断の競合**: エージェントの判断が割れたら脳が裁定。脳が判断
  できなければ owner-decision-queue へ。オーナー判断後は decision_log に
  記録し後続に適用。

## 8. 100point-rubric-judge P項目との連動

| P項目 | 基準 | 判定方法 |
|---|---|---|
| P-1 | Multi-agent 並列実行動作 | 実装確認 |
| P-2 | Outcomes 自動採点ループ動作 | 実装確認 |
| P-3 | Webhook 通知動作 | 実装確認 |
| P-4 | Prompt Caching 動作 | 実装確認 |
| P-5 | 朝バッチで全エージェント並列動作 | 1週間の動作実績で判定 |

## 9. 実装ロードマップ

- **Phase 1(Day 14-17)**: 専門エージェント skill 完成(L/M/N/O)、
  連携プロトコル仕様策定、Webhook 設計。
- **Phase 2(Day 17 以降)**: Multi-agent Orchestration 実装、
  Outcomes ルーブリック定義、Dreaming 申請、Prompt Caching 設定。
- **Phase 3(本番化後)**: 朝バッチでの並列実行開始、計測・改善ループ、
  100点項目の達成。

## 10. 状態管理

保存先: `/home/aiuser/.kpop_recovery/orchestration_state.json`

```json
{
  "agents": {
    "claude_brain":     {"status": "active",    "last_heartbeat": "..."},
    "t1_implementer":   {"status": "active",    "last_heartbeat": "..."},
    "red_team":         {"status": "scheduled", "next_run": "..."},
    "blue_team":        {"status": "scheduled", "next_run": "..."},
    "qa_generator":     {"status": "scheduled", "next_run": "..."},
    "skill_evolution":  {"status": "manual",    "last_run": "..."}
  },
  "active_workflows": [],
  "pending_decisions": [],
  "outcomes_scores": {}
}
```

## 11. 出力ルール

- **日次サマリ**: 各エージェントの稼働状況(1行ずつ)、並列実行数、
  Outcomes 平均スコア、失敗・要判断件数。
- **週次レポート**: 並列化による時間短縮、エージェント別の貢献、
  skill-evolution からの改善提案、100点 P項目スコア更新。
- 詳細は要求されたときだけ出す。実測値と推定値を区別する。

## 12. 安全設計

- エージェント暴走の防止(無限ループ検知)。
- リソース上限(同時並列数・メモリ使用量)。
- 重大な判断は必ず脳を経由する(エージェント間で勝手に決めない)。
- 全アクションをログに記録する。
- オーナーが全停止できるコマンドを1つ用意する。
- 過去インシデントの教訓を反映:
  - 嘘の完了宣言 → Outcomes で機械検知。
  - review_queue 無限ループ → 並列実行にクールダウン。
  - DBパスワード漏洩 → ログのマスキング必須([[vps-deletion-incident-2026-05]])。

## 13. メタ階層(これが「脳」である理由)

他の全スキルが「特定タスクを実行」するのに対し、orchestration-leader は
「他のスキルたちを指揮」する。

- 1つ上の階層: `skill-creator`(skill の作成)/ `skill-evolution`(skill の進化)。
- 最上位の3スキル: **orchestration-leader**(全 skill + エージェント統括)/
  [[100point-rubric-judge]](全項目の達成判定)/ [[roadmap-tracker]](全進捗追跡)。
- この3つが連携して KPOP JOURNAL 100点計画を遂行する。
