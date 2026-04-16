# 現在のシステム状態（2026-04-13 更新）

## 環境

| 項目 | 値 |
|------|-----|
| サーバー | VPS Ubuntu |
| 実行ユーザー | aiuser |
| プロジェクトディレクトリ | /home/aiuser/kpop-ai-system |
| Claude CLI | 導入済み |
| WordPress投稿 | API正常（HTTP 200確認済み） |
| cron | 毎日 07:00 / 08:00 / 09:00 / 12:00 / 13:00 / 15:00 / 17:00 / 18:00 / 19:00 実行中、毎時0・30分 watchdog |
| 設計書バージョン | ai_company_master_spec v3.3 / operations_runbook v1.0 |

---

## 現在のフェーズ判定（2026-04-12時点）

### A. 実装済み・本番観測済み

| 機能 | 観測根拠 |
|------|---------|
| X_SUCCESS guard [⑤] | 2256型再発ゼロ |
| Arceus却下検出修正 | 過剰却下ループ解消確認済み |
| gardevoir HARD_FAIL時の詳細JSONL記録 | logs/gardevoir_hook.jsonl に run_id 付きエントリ確認済み（HARD_FAILのみ） |
| post_audit [2b] K-POPプレフィクス付与 | post_audit.log 2026-04-12 17:55:07 に `[2b] Hearts2Hearts タイトルK-POPキーワードなし → 追記` 記録確認済み |
| **post_audit [7b] silent exit 修正** | ID=2310（2026-04-12 19:49）: slug修正あり記事で `--- [7b] X投稿品質監査 ---` → `ℹ️ X投稿スコア: PRE_SCORE: 81.0/100` → `--- [8]` 以降継続を本番cronログで確認 |
| **improvement_engine User-Agent 追加** | 2026-04-12 21:30 cron run: `Discord通知完了` 記録あり・同run内 `HTTP Error 403` なし（本番Discord到達確認） |
| **gardevoir SCOREパース 7フォーマット対応** | pipeline.jsonlに `score=81/88/88/82/91` 等の実数値が記録されている（2026-04-12 複数run確認） |
| **gardevoir_hook.jsonl 全verdictに run_id 追加（PASS含む）** | PASSエントリに `"run_id": "20260412_180031"` 等のフィールドあり（gardevoir_hook.jsonl確認済み） |
| **post_watchdog 通知クールダウン 24h** | `logs/watchdog_notif_cooldown.json` 生成確認・`recurring_error_patterns` / `pipeline_external_wp_post` エントリあり（2026-04-11） |
| **post_watchdog external_wp検知** | `watchdog_alerts.jsonl` に `pipeline_external_wp_post` エントリ複数確認（2026-04-12 03:00〜05:00: post_id=2234/2241/2249 の3件を実データで検知・Discord通知済み） |

### B. 実装済み・再現確認済み（本番cron経路での観測は未実施）

| 機能 | 確認内容 | 昇格条件 |
|------|---------|---------|
| **improvement_engine 品質比率集計** | Pythonスクリプト単体で正常出力確認（syntax error修正済み 2026-04-12）。修正後cron runはまだ実行されていない | 次回21:30 cronのDiscord通知に `📊 品質比率:` 行が出て `[[: 0\n0: syntax error` が出ない |
| **butterfree 空出力リトライ＋フォールバック** | bash -n 構文確認済み。30秒待機リトライ→アーカイブfallback→停止の3段階 | 次回strategy 12:00 cronで発火しない（正常run）またはfallbackログが出る |
| **deoxys 空出力リトライ（breaking）** | bash -n 構文確認済み。30秒待機後テーマ/newsモードでリトライ | 次回breaking cronで発火しない（正常run）またはリトライ成功ログが出る |
| **gardevoir SCOREパース 総合点/フォールバック追加（9/10パターン）** | dry-run: 190034（total_point型）・220036（合計型）ともにscore=81→PASSに変わることを確認 | 次回strategy cronで score= が取得されHARD_FAILにならない |
| **watchdog silence 閾値緩和（4h/6h→26h）** | post_watchdog.py修正確認済み。1日1投稿保証ベース | 次回watchdog runで誤検知アラートが出ない |
| **タイトル型崩れガード [B束]** | bash -n 確認済み。メタ表現パターンをPHASE5に追加 | 次回strategy cronで「確認します」等のタイトルが投稿停止される |
| **[14.9] CTR最適化** | bash -n 確認済み。全5タイトルケースで動作確認済み。`｜`区切りバグ修正済み | 次回strategy 12:00 cronのログに `[14.9] CTR最適化` 行が出る |

### C. 実装済み・本番未観測（次回run以降に観測予定）

| 機能 | 実装場所 | 昇格条件・未発火理由 |
|------|---------|---------|
| post_audit [11b] href="#" 除去 | post_audit.sh | 到達経路復旧済み・コード正常。未発火理由: 処理済み全記事に `href="#"` が含まれていない（正常）。kairyu生成記事に href="#" アンカーが含まれた時に初発火 |
| gardevoir VERDICTフォールバック（breaking側） | kpop_pipeline.sh | VERDICT行欠落条件依存。`ℹ️ [gardevoir] VERDICT行なし → score=XX からPASSに推定` がlogに出ると昇格 |
| kairyu_kpop.md href="#" 禁止明記 | agents/kairyu_kpop.md | 次回kairyu実行記事にhref="#"が消えることを確認 |
| kpop_words リスト強化（Coachella等） | 両パイプライン | Coachella等のキーワードを含む記事が投稿停止されなくなる |
| arceus前ハードガード [3.9] / [13.9] | 両パイプライン | pipeline.jsonlに `✅ GUARD:` 記録または7日間誤検知ゼロ |
| gossip_source_guard | kpop_pipeline.sh / post_audit.sh | gossip_source_guard.log なし（カテゴリ14のgossip記事が未実行）。初回実行で初観測 |

### D. 要手動対応（自動解決不可）

| 案件 | 対応内容 |
|------|---------|
| **POST_ID=2272 draft化（未復旧）** | WordPress管理画面でタイトルに「K-POP」等のSEOキーワードを手動追加してpublish。自動修正ループ3回失敗済みのため自動解決不可。 |

---

## 【重要バグ修正】post_audit [7b] silent exit（2026-04-12 特定・修正）

**現象**: post_audit が `--- [7b] X投稿品質監査 ---` を記録した後、内部メッセージも [8]-[13] も出力されずに終了。今日の全4件（ID=2286/2290/2295/2300）で発生。

**根本原因（確定）**:
1. `set -euo pipefail`（post_audit.sh line 29）が有効
2. [0] slug修正後、`POST_URL` が新URLに更新される（line 189）
3. `x_post.log` には X投稿時（[0]実行前）の旧URLが記録されている
4. [7b] line 1159: `grep -nF "$POST_URL" logs/x_post.log` が新URLでno-match → exit 1
5. `set -e` + `pipefail` によりスクリプトがfallback到達前にsilent exit

**修正**（最小差分 1行）:
```diff
- _X_URL_LINE=$(grep -nF "$POST_URL" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | head -1 | cut -d: -f1)
+ _X_URL_LINE=$(grep -nF "$POST_URL" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | head -1 | cut -d: -f1 || true)
```

**因果連鎖**: [7b] → [11b] は直列であるため、この修正により [8]-[13] 全体（GSC登録・ファクトチェック確認・内部リンクチェック・[11b] href="#"除去 等）の到達経路が復旧した。

---

## 修正履歴（直近）

| 日付 | 修正内容 | 対象ファイル |
|------|---------|------------|
| 2026-04-12 | **post_audit [7b] silent exit 修正**（slug修正後URL不一致 + set -euo pipefail）: line 1159 に `\|\| true` 追加 | post_audit.sh |
| 2026-04-13 | **butterfree/deoxys 空出力リトライ＋フォールバック** | kpop_strategy_pipeline.sh / kpop_pipeline.sh |
| 2026-04-13 | **gardevoir SCOREパース 総合点/フォールバック追加（9/10パターン）** dry-run確認済み | kpop_strategy_pipeline.sh |
| 2026-04-13 | **watchdog silence 閾値 4h/6h→26h 緩和** | lib/post_watchdog.py |
| 2026-04-13 | **タイトル型崩れガード [B束] 追加** | kpop_strategy_pipeline.sh |
| 2026-04-13 | **[14.9] CTR最適化 `｜`区切りバグ修正** | kpop_strategy_pipeline.sh |
| 2026-04-12 | gardevoir SCOREパース多フォーマット対応（7パターン） | kpop_strategy_pipeline.sh / kpop_pipeline.sh |
| 2026-04-12 | gardevoir VERDICTフォールバック breaking側追加 | kpop_pipeline.sh |
| 2026-04-12 | gardevoir_hook.jsonl 全verdictに run_id/pipeline/title/category追加 | 両パイプライン |
| 2026-04-12 | 設計書 v3.3 更新（AI オーナー型運営前提・CEO表現修正・修正履歴反映） | docs/ |
| 2026-04-11以前 | X_SUCCESS guard、Arceus却下検出修正、post_watchdog 24h稼働 等 | 各種 |

---

## 次回本番観測で確認する項目（2026-04-13 更新）

| 優先 | 観測対象 | 判定ログ | 成立条件 |
|------|---------|---------|---------|
| 1位 | **[14.9] CTR最適化 B→A昇格** | `logs/strategy_pipeline.log` | `[14.9] CTR最適化` 行が出る |
| 2位 | **gardevoir SCOREパース修正 B→A昇格** | `logs/gardevoir_hook.jsonl` | HARD_FAIL エントリが `score=0 format_error` でなく実数値になる |
| 3位 | **improvement_engine 品質比率集計 B→A昇格** | `logs/improvement_engine.log` | 21:30 cronで `📊 品質比率:` 行が出て syntax error なし |
| 4位 | **[11b] 初回発火確認** | `logs/post_audit.log` | `✅ [11b] href="#" アンカー N件を除去` が1行でも記録される |

---

## 参照先

- 完全実装指示書: `docs/ai_company_master_spec_v3.0.md`（v3.3）
- 運営ランブック: `docs/operations_runbook_v1.0.md`
- 投稿ログ: `logs/pipeline.jsonl`
- gardevoir観測: `logs/gardevoir_hook.jsonl`
- post_audit観測: `logs/post_audit.log`
- 手動対応ログ: `logs/auto_repair.log`
