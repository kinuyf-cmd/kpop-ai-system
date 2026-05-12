# KpopJournal — Claude 行動契約

このファイルは system prompt 直挿入で読み込まれる**最高優先度の行動規約**。
memory ファイルより強い。違反は許容されない。

## 最重要: 「監査」要求時の4項目procedural

ユーザーが「監査」「audit」「チェック」「確認」を依頼した時、以下を **完全にこの順番で** 実行してから初回報告すること。途中報告禁止。

```
[ ] 1. structure: full_audit_runner.py 等のscriptを走らせる
[ ] 2. thumbnail: 対象記事のサムネを Read ツールで全件目視
[ ] 3. factcheck: llm_proofreader を新規実行 (cache依存禁止、新規jsonが logs/llm_audit/ に書き出されることを確認)
[ ] 4. body_read: 各記事の本文を読み、関連リンク混入/HTML entity残存/slug年度不整合/タイトル乖離を確認
```

**1だけで報告してはいけない。** scriptの出力は「構造項目1個分の中間結果」にすぎない。
全4項目が完了するまで「監査結果」とは呼ばない。

violation pattern (2026-05-10 発生):
- 「12時間以内の投稿の監査して」要求にscriptで2件報告 → ユーザー指摘で残り3項目実行 → CRITICAL含む追加6件発覚
- 教訓: scriptが回ったこと ≠ 監査が完了したこと

## 報告ルール

- 4項目すべての結果を表で報告する。「構造OKです」のような部分報告禁止
- CRITICAL/HIGH が出た記事は **必ず本文を読む**。数値だけで判断禁止
- サムネ目視は **画像をReadで開く**。サイズ・alt・スコアの数値だけでPASS判定するのは「目視」ではない
- 「完了」と書く前に: logs/audit_steps.jsonl に当該post_idの4項目entryが揃っているか確認

## 自動防御層 (2026-05-11 構築)

私が違反した場合の自動回収機構が稼働中:
1. `pipeline/audit_steps_enforcer.py` cron (15分間隔) が publish後30分で4項目entry揃わない記事を自動 draft化
2. `lib/audit_steps_log.py` に4項目それぞれのentry記録 — `record_step(post_id, step, status, detail, source)`
3. `lib/unified_publisher.py` のソース短/サムネ無し記事自動 draft化

私が手を抜いても cron が捕捉する設計。だが**捕捉されないように振る舞うのが正しい**。

## 巻き込みcommit回避

`git status` でM (modified) 状態のファイル群が常時複数ある (pipeline自動更新ファイル等)。
編集する際は必ず diff 量を確認し、100行超なら退避→HEAD戻し→再適用→commit→復元の手順で巻き込みを避ける。

## 関連 memory (詳細はmemory読み込み)

- `feedback_never_publish_without_audit`: 4項目セット必須の根拠
- `feedback_audit_script_is_not_audit`: scriptは構造1個分にすぎない
- `feedback_120_percent_quality`: 速度より網羅性
- `feedback_no_excuses_follow_rules`: 違反は意志の問題
- `feedback_definition_of_done`: 本番動作+証跡なしで完了報告禁止
