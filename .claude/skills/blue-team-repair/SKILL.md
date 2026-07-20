---
name: blue-team-repair
description: red-team-auditor が検出した KPOP JOURNAL の問題を防御・修復する BLUEチームスキル。明確に安全な問題は検証付きで修復し、要判断のものは owner-decision-queue に投入。週次/月次の予防メンテ(バックアップ・更新確認)も担当。「修復して」「BLUEチーム実行」「問題対応」「予防メンテ」「RED検出を直して」「バックアップ取って」「セキュリティ修正」といった問い合わせ時に必ず使用。red-team-auditor・error-evidence・owner-decision-queue と連携。
---

# Blue Team Repair

## 1. 目的

[[red-team-auditor]] の対となるスキル。RED が見つけた問題を
「修復」「防御強化」「予防」の3階層で対応する。

- RED検出の **80%以上を自動修復**することを目標にし、運用負荷を下げる。
- 残り20%(判断を要するもの)は [[owner-decision-queue]] へ回す。
- self-healing できる箇所を最大化しつつ、**本番を壊さないこと**を最優先する。

**重要 — RED は読むだけ、BLUE は本番を変える。** このスキルは
`certbot` / `wp` / nginx / ファイル操作で稼働中システムを変更する。
KPOP JOURNAL と補助金サイトは同一VPSに同居しているため、過剰な
自動修復はサービス障害になりうる。安全設計(§11)を必ず守る。

## 2. red-team-auditor との連携

### トリガー
- `red_team_log.jsonl` に新規検出 → 自動読み込み。
- 重大度別の対応速度:
  - CRITICAL → 即時対応(オーナー通知後)
  - HIGH → 1時間以内
  - MEDIUM → 24時間以内
  - LOW → 週次バッチ

### 検出データの処理
1. `red_team_log.jsonl` の最新エントリを取得
2. 重大度・カテゴリ別に分類
3. 自動修復可能か判定(§4)
4. 対応開始、または owner-decision-queue 投入(§5)

## 3. 修復カテゴリ(red-team-auditor と対称)

### セキュリティ
- SSL証明書の期限近接 → `certbot renew`(§4・§11 の扱いに従う)
- 古いプラグイン → `wp plugin update`
- 露出ファイル(`.env` `.git/`)→ アクセス禁止設定
- HTTP セキュリティヘッダ不足 → nginx 設定追加(要判断・§5)

### UX
- リンク切れ → リダイレクト or 修正で 404 解消
- 遅延ページ → キャッシュ追加・画像最適化
- モバイル表示崩れ → メディアクエリ修正

### 誤情報
- 古い記事日付 → 内容確認のうえ更新 or 削除
- 不正確なリンク先 → 修正 or 削除
- 不適切な表示(故人情報など)→ 編集

### 運用
- ログ肥大 → ローテーション
- ディスク逼迫 → 古いファイル整理
- cron 失敗 → 再実行 or 通知

## 4. 自動修復の可否(80%目標)

### ✅ 自動修復してよい(明確に安全・オーナー通知のみ)
- SSL証明書の `certbot renew`(更新のみ。設定変更を伴わない)
- `wp plugin update`(マイナーバージョン)— **修復前後で動作検証必須**
- 明確に間違っているリンク切れの修正
- ログローテーション / キャッシュクリア / バックアップ実行

### ⚠️ 自動修復しない(必ず owner-decision-queue へ)
- メジャーバージョンアップ(WordPress / PHP)
- データ削除(誤情報の疑いがあるが確証がないもの)
- セキュリティ設定変更(影響範囲が大きいもの)
- **サーバー設定変更(nginx / php-fpm / certbot の設定変更)**
  — 同居サイトに波及しうるため、稼働環境の変更は自動化しない
- バックアップからの復元

判断に迷うものは「自動修復してよい」に入れない。曖昧なら §5 へ回す。

## 5. 要判断項目の owner-decision-queue 連携

自動修復しないものは次の形式で [[owner-decision-queue]] に投入する:

```json
{
  "decision_id": "BLUE-YYYYMMDD-XXX",
  "source": "red-team-auditor:detection_id",
  "issue_type": "security|ux|misinformation|operational",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "description": "問題の1行説明",
  "recommended_action": "推奨対応",
  "auto_repair_possible": false,
  "rationale": "自動修復しない理由",
  "options": [
    {"label": "A", "summary": "推奨案"},
    {"label": "B", "summary": "代替案"},
    {"label": "skip", "summary": "今回はスキップ"}
  ]
}
```

## 6. 予防的メンテナンス

### 週次(日曜 23:00)
- DB + ファイルのバックアップ(UpdraftPlus 等)
- ログローテーション / キャッシュクリア
- SSL有効期限の確認
- ディスク使用量の確認

### 月次(月末)
- WordPress + プラグインの更新確認
- PHPバージョン確認
- データベース最適化 / 古い revision 削除
- メディアライブラリ整理(未使用画像)

## 7. 修復ログ

保存先: `/home/aiuser/.kpop_recovery/blue_team_log.jsonl`(1行1エントリ・追記)。

```json
{
  "timestamp": "2026-05-19T16:30:00+09:00",
  "trigger": "auto|manual|scheduled",
  "source_detection": "red_team_log entry ID",
  "action_type": "repair|prevention|escalation",
  "category": "security|ux|misinformation|operational",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "description": "実施内容",
  "evidence": {
    "files_changed": [],
    "commands_run": [],
    "verification": ""
  },
  "result": "success|failed|escalated",
  "owner_decision_id": "BLUE-XXX or null"
}
```

## 8. error-evidence skill との連動

修復も「完了宣言」にあたるため、[[error-evidence]] の4点セットを必須とする:
- md5 ハッシュの変化
- git diff(該当する場合)
- テスト PASS(該当する場合)
- 修復対象の動作確認(`curl` で 200 等)

嘘の完了宣言を防ぐため、修復後の検証コマンドを必ず実行し、
結果を §7 のログ `evidence.verification` に記録する。
「直したつもり」で終わらせない。

## 9. 出力ルール

修復実行時:
- 1行サマリ(何を修復したか)
- エビデンスファイルのパス
- owner-decision-queue 投入があればその ID

週次/月次レポート:
- 自動修復の件数
- 要判断の件数(投入した decision_id)
- 予防メンテの実行内容
- [[100point-rubric-judge]] M項目スコアの更新提案

詳細レポートは要求されたときだけ出す。

## 10. 100point-rubric-judge M項目との連動

M項目(BLUEチーム・4点満点)への対応:

| M項目 | 基準 | 判定方法 |
|---|---|---|
| M-1 | blue-team-repair skill 完成 | スキル存在で 1点 |
| M-2 | RED検出を80%以上自動修復 | 週次レポートの修復率で判定 |
| M-3 | 修復不可は owner-decision-queue へ | 連携動作の確認で判定 |
| M-4 | 予防メンテ動作(週次バックアップ等)| cron 動作の確認で判定 |

## 11. 安全設計(red-team-auditor と対称)

- 対象は**自社サイトのみ**(KPOP JOURNAL + 補助金AIステーション)。
- 自動修復は「明確に問題と判定でき、かつ修復方法が安全なもの」に限る。
- 曖昧・影響大のケースは必ず owner-decision-queue へ(§4 ⚠️)。
- **稼働環境の変更(nginx / php-fpm / certbot 設定・DNS)は自動化しない。**
  これらは同居サイトに波及しうるため、オーナー判断を経て実施する。
- 修復前に可能な限りバックアップを取る。
- 修復が失敗したら自動ロールバックを試み、結果をログに残す。
- CRITICAL 対応は必ずオーナーに通知してから実施する。
- VPS削除事故([[vps-deletion-incident-2026-05]])の教訓に従い、
  バックアップ・決済・平文パスワードの観点を予防メンテに含める。
