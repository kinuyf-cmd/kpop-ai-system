---
name: qa-test-generator
description: KPOP JOURNAL・補助金AIステーションの主要機能向けにユニット・統合・E2Eテストを自動生成し、リグレッションテストで品質を担保する QAエージェントスキル。webapp-testing をベースに各プロジェクト固有のワークフロー(記事投稿・速報バー・Idol Wiki・収益化導線・申請書生成)をテスト化。「テスト書いて」「QA実行」「リグレッションチェック」「テスト自動生成」「動作確認」「テストカバレッジ確認」といった問い合わせ時に必ず使用。
---

# QA Test Generator

## 1. 目的

主要機能の品質をテストで自動担保する。「動いている」を
「動き続ける」に変え、リグレッション(過去の修正のしわ寄せで
別の箇所が壊れること)を防ぐ。`webapp-testing` を土台に、
KPOP JOURNAL・補助金 固有のテストを構築する。

## 2. webapp-testing skill との連携

`webapp-testing` が提供するもの:
- Playwright によるブラウザ自動化 / スクリーンショット
- `networkidle` 待機 / 複数サーバー同時起動

本スキルが追加するもの:
- KPOP・補助金 固有のテストケース生成
- skill ファイルからのテスト導出(§5)
- 定期実行(cron 連携)/ 失敗時の自動アラート

## 3. テスト対象(プロジェクト別)

### KPOP JOURNAL(stg.kpopjournal.tokyo で実施)
- 記事投稿フロー(`import_to_wp.py`)
- 速報バー表示(子テーマ)/ カテゴリ・タグページ / 個別記事ページ
- メニュー動作 / 検索動作
- Idol Wiki(将来)/ 収益化導線(将来)

### 補助金 AI ステーション
- 申請書生成フロー / LP表示 / 顧客オンボーディング
- 法的境界チェック([[hojokin-legal-boundary]])

> ⚠️ 補助金 SaaS には独立したステージング環境がない(本番が稼働中)。
> §12 の安全設計に従い、補助金のテストは**非破壊の読み取り確認**
> (LP の表示・HTTP応答・静的検証)に限定する。申請書の実送信・
> 決済・顧客データを伴うテストは行わない(§12)。

## 4. テスト種別

- **Unit**(個別関数・モジュール): `import_to_wp.py` の各関数、
  カテゴリ振り分けロジック、サムネキャッシュ機構。Python `pytest` 形式。
- **Integration**(複数モジュール連携): スクリプト→WordPress API→DB、
  記事生成→校正→投稿の連鎖。`python` + `wp-cli` の組み合わせ。
- **E2E**(ユーザー視点): Playwright で実ブラウザ操作。記事閲覧→
  カテゴリ移動→検索。モバイルエミュレーション含む。stg は Basic認証通過。

## 5. テスト生成ロジック

### skill ファイルからのテスト導出
- 各 skill の「絶対方針」「出力ルール」をテスト化する。
- [[error-evidence]] の4点セット必須をテスト。
- `kpop-article` の HARD_FAIL 条件をテスト。
- `kpop-seo-checklist` の全項目をテスト。

### テンプレ生成
- 機能名 → テストファイル名(`test_<feature>.py`)
- assert 文の自動生成 / fixture の共通化

## 6. 実行スケジュール

- **commit 時**(将来 git hook): 変更ファイルに関連する Unit テスト。5分以内。
- **日次 03:00 cron**: 全 Unit + 主要 Integration。結果を朝バッチに含める。
- **週次 日曜 02:00**: 全テスト(Unit + Integration + E2E)+ レポート生成。
  失敗時は [[blue-team-repair]] に連携。

## 7. リグレッションテスト体系

過去のインシデントを必ずテストケース化し、再発を防ぐ:

| 過去インシデント | 再発防止テスト |
|---|---|
| 嘘の完了宣言事件 | 完了宣言時に動作確認テストを必ず走らせる |
| review_queue 無限ループ | クールダウン動作のテスト |
| サムネの豆腐文字 | Playwright で文字化け検出 |
| WordPress(ja)locale | 日本語タイトルでも対象を検出するテスト |
| wp-cli `/dev/stdin` バグ | パスワードリセット動作のテスト |

**新しいインシデントが起きたら、その場で再発防止テストを追加する。**
これがリグレッション体系の肝であり、同じ事故を二度起こさないための仕組み。

## 8. 失敗時の対応

- テスト失敗 → `red_team_log.jsonl` に記録 → 重大度判定 →
  [[blue-team-repair]] が修復を試行。
- 修復不可(テスト失敗 + 修復失敗)→ 関連情報を整理して
  [[owner-decision-queue]] へ。

## 9. テストログ

保存先: `/home/aiuser/.kpop_recovery/qa_test_log.jsonl`(1行1エントリ・追記)。

```json
{
  "timestamp": "2026-05-19T16:45:00+09:00",
  "trigger": "commit|daily|weekly|manual",
  "test_suite": "unit|integration|e2e",
  "test_count": 100,
  "passed": 98,
  "failed": 2,
  "duration_seconds": 120,
  "failures": [
    {
      "test_name": "test_thumbnail_cache_no_duplicate",
      "error": "AssertionError: media_id duplicated",
      "file": "tests/test_import.py:42"
    }
  ],
  "coverage": "78%",
  "report_path": "/tmp/qa_report_YYYYMMDD.html"
}
```

## 10. 100point-rubric-judge N項目との連動

N項目(QAエージェント・4点満点)への対応:

| N項目 | 基準 | 判定方法 |
|---|---|---|
| N-1 | qa-test-generator skill 完成 | スキル存在で 1点 |
| N-2 | 主要機能ユニットテスト自動生成 | テスト件数で判定 |
| N-3 | リグレッションテスト動作 | 週次実行の確認 |
| N-4 | webapp-testing 統合 | 連携動作の確認 |

## 11. 出力ルール

- テスト実行時: 1行サマリ(passed/failed)。失敗があれば失敗テスト名のみ列挙。
- 週次レポート: カバレッジ / 主要失敗 / インシデントから追加した再発防止テスト。
- 詳細は要求されたときだけ出す。
- テスト結果は実測。「たぶん通る」で passed と書かない。

## 12. 安全設計

- **KPOP JOURNAL のテストは `stg.kpopjournal.tokyo` で実施**し、
  本番(`kpopjournal.tokyo`)に対して破壊的テストを行わない。
- **補助金 SaaS はステージングが無く本番が稼働中**のため、テストは
  非破壊の読み取り確認に限定する。申請書の実送信・決済・疑似決済・
  顧客データを伴うテストは**行わない**(過去タスクの禁止事項と一貫)。
  決済や申請フローの検証が必要なときはモック/ローカル環境を用意し、
  本番投入は [[owner-decision-queue]] 経由でオーナー判断を仰ぐ。
- 破壊的テスト(削除等)は trash 経由でリカバリ可能にする。
- E2E テストで stg にアクセスする際は Basic認証を通過する。
