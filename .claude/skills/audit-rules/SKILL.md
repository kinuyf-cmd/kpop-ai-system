---
name: audit-rules
description: KPOP JOURNAL・補助金 の日次・週次・月次監査ルール体系スキル。自動監査の実行スケジュール・チェック項目・違反検知時の対応フローを定義し、error-evidence・red-team-auditor・blue-team-repair と連携。「監査ルール」「日次チェック」「週次レビュー」「月次監査」「コンプライアンス確認」「自動チェック」といった問い合わせ時に必ず使用。
---

# Audit Rules

## 1. 目的

品質維持・リスクの早期検知・100点計画 D項目の達成のため、
日次/週次/月次の3層で監査を体系化する。

## 2. 3層監査体系

- **日次**(03:00 cron 想定)
- **週次**(日曜 02:00)
- **月次**(月末)

## 3. 日次監査項目

- 新規記事の品質チェック(`kpop-article` の HARD_FAIL)
- [[error-evidence]] スキル違反の検出
- エラーログの集計
- ディスク・メモリ使用率
- cron 失敗の検知

## 4. 週次監査項目

- SEO 順位変動(Search Console データ)
- PV/CTR の異常検知
- サーバー異常(エラーログ集計)
- [[red-team-auditor]] スキャンの実行
- [[skill-evolution]] の効果計測
- バックアップ動作の確認

## 5. 月次監査項目

- 全コンテンツの再評価 / リライト候補抽出
- スキル群の有効性検証
- WordPress + プラグインの更新確認
- SSL 証明書の有効期限
- 法的境界の遵守確認([[hojokin-legal-boundary]])

## 6. 違反検知時の対応フロー

- **CRITICAL** → 即時 [[blue-team-repair]] + オーナー通知
- **HIGH** → 1時間以内、blue-team-repair が自動対応
- **MEDIUM** → 24時間以内、計画的に修復
- **LOW** → 週次バッチで対応

## 7. 監査ログ

`/home/aiuser/.kpop_recovery/audit_log.jsonl`(1行1イベント・追記式)。

## 8. error-evidence との連動

監査結果の「完了宣言」も [[error-evidence]] の証跡を必須とする。
「監査した」だけで終わらせず、確認した内容と結果を証跡として残す。

## 9. 100point-rubric-judge D項目との連動

| D項目 | 基準 |
|---|---|
| D-1 | 日次監査の自動実行 |
| D-2 | 週次監査の自動実行 |
| D-3 | 月次監査の自動実行 |
| D-4 | error-evidence スキルの必須遵守 |

## 10. 出力ルール

違反件数のみを報告する。詳細は要求されたときだけ出す。
件数は実測に基づく。

---

## 10. M3 段階3.8 D cron 実装(2026-05-20)

D-a/b/c の自動 cron 実装を完了。`audit_72h.py` v2.0 を時間幅別に再利用し、
3スクリプトに集約。

### 10-1. 実装ファイル

| ファイル | 役割 | 起動時刻 |
|---|---|---|
| `audit_daily.sh` | 直近24h 監査 + 全公開記事HTTP/サムネ整合性 | 毎日 05:00 |
| `audit_weekly.sh` | 直近7日 + WoW 比較 + 採用5媒体 robots.txt + sanitize 集計 | 月曜 06:00 |
| `audit_monthly.sh` | 直近30日 + 100point 達成度 + 利用規約到達性 + sanitize 月次 | 月初1日 07:00 |

### 10-2. 通知先(config/discord_webhooks.json)

| 監査 | webhook key | CRITICAL 補助通知 |
|---|---|---|
| 日次 | `daily_ceo_report` | `urgent_errors`(HTTP失敗時) |
| 週次 | `weekly_board_report` | `urgent_errors`(新規 AI bot Disallow 検出時) |
| 月次 | `monthly_board_report` | (なし、レポート1本のみ) |

### 10-3. ログ保存先

`~/.kpop_recovery/audit_logs/`:
- `daily_YYYYMMDD.log` + `daily_YYYYMMDD_audit72h.txt` + `daily_YYYYMMDD_consistency.json`
- `weekly_YYYYMMDD.log` + `weekly_YYYYMMDD_audit168h.txt` + `weekly_YYYYMMDD_robots.json`
- `monthly_YYYYMM.log` + `monthly_YYYYMM_audit720h.txt` + `monthly_YYYYMM_terms.json`
- `cron_daily.log` / `cron_weekly.log` / `cron_monthly.log`(crontab redirect)

### 10-4. 起動方法

cron で自動起動。手動起動も可能:

```
bash audit_daily.sh                   # 通常実行(Discord 通知)
AUDIT_DRY_RUN=1 bash audit_daily.sh   # ドライラン(通知スキップ)
```

3スクリプト全て set -uo pipefail、通知失敗(`AUDIT_NOTIFY_EXIT != 0`)でも
監査ロジック本体は exit 0 で完走するロバスト設計。

### 10-5. 失敗時の挙動

- audit_72h.py 失敗 → ログに残し処理続行
- WP API タイムアウト → ログに残し当該項目だけ 0 扱い
- Discord 通知失敗 → ログに残し exit 0(監査自体は成功扱い)
- `urgent_errors` 通知失敗 → ログに残し exit 0

### 10-6. 100point D 項目との連動

- D-a(日次) ✅ `audit_daily.sh` で達成
- D-b(週次) ✅ `audit_weekly.sh` で達成
- D-c(月次) ✅ `audit_monthly.sh` で達成
- D-d(error-evidence) ✅ M3 全段階で実践(SKILL.md §1)

D 4/4 を 100point-rubric-judge で確認後、`roadmap_state.json` 反映。
