---
name: skill-evolution
description: 既存スキルの効果計測と進化を担うメタメタスキル。繰り返しタスクを検出して新スキル化を提案し、使用頻度・Outcomesスコアを計測、改善版を生成、不要スキルの廃棄・統合を判定する。skill-creator(作成)の上位、orchestration-leader(全体指揮)の下位。「skill改善」「skill進化」「新skill提案」「skill効果測定」「繰り返しタスクのskill化」「skillのリファクタリング」「使われていないskill」といった問い合わせ時に必ず使用。
---

# Skill Evolution

## 1. 目的

既存スキルの継続改善・自動進化を担う。「人間がスキルを書く」から
「AI がスキルを書き、評価し、改善する」への進化が狙い。

- `skill-creator` が「作成」を担うのに対し、skill-evolution は
  「改善・廃棄・統合」を担う。
- Dreaming(Claude Managed Agents の機能)が GA になれば、§9 の自動化と
  統合できる。

## 2. skill-creator との関係

- `skill-creator`(下位): 新規スキルの作成、初期 SKILL.md 生成。
- **skill-evolution(中位)**: 既存スキルの効果計測、改善版生成、
  廃棄判定、統合提案。
- [[orchestration-leader]](上位): エージェント全体の指揮。

skill-evolution は `skill-creator` を呼び出して新版を生成し、
既存版との差し替えを提案する。

## 3. 既存スキルの効果計測

計測指標:
- `call_count`: 過去30日の呼び出し回数
- `success_rate`: Outcomes 採点器による平均スコア
- `error_rate`: スキル実行時の失敗率
- `token_cost`: 1回あたりの平均トークン消費
- `user_feedback`: オーナーの A/B/C 評価

保存先: `/home/aiuser/.kpop_recovery/skill_metrics.jsonl`(1行1イベント)

```json
{
  "timestamp": "2026-05-19T17:00:00+09:00",
  "skill_name": "kpop-article",
  "call_count": 1,
  "outcomes_score": 0.85,
  "error": false,
  "token_input": 5000,
  "token_output": 2000,
  "context": "記事生成"
}
```

週次集計: 各スキルの使用統計 / 効果ランキング / 効率(score ÷ token_cost)。

## 4. 繰り返しタスク検出

検出ロジック:
- 同じ作業パターンが3回以上 → スキル化候補
- 同じスキル群を毎回手動で組み合わせ → 統合スキル候補
- 既存スキルで対応できないタスク → 新スキル候補

検出ソース: claude.ai のチャット履歴(memory)/ T1 の作業ログ /
[[error-evidence]] の完了報告 / [[owner-decision-queue]] の頻出パターン。

提案出力:
```json
{
  "candidate_skill": "skill名案",
  "rationale": "なぜスキル化すべきか",
  "frequency": "週X回観測",
  "estimated_value": "高|中|低",
  "draft_description": "skill-creator に渡せる初稿"
}
```

## 5. 新スキル提案ロジック

提案条件: 検出頻度 ≥ 3回/週 / 既存スキル未カバー / 自動化価値が明確。

提案フロー:
1. パターン検出 → スキル化候補生成
2. owner-decision-queue に投入
3. オーナー承認 → `skill-creator` 起動
4. `skill-creator` が SKILL.md 生成
5. skill-evolution が効果計測を開始
6. 4週間後に効果を再評価

## 6. 既存スキルの改善版生成

改善対象の判定基準:
- Outcomes スコア < 0.7(品質が低い)
- エラー率 > 10%(動作が不安定)
- 使用回数ゼロが3週間継続(廃止候補)
- 既存スキル同士の重複(統合候補)

改善プロセス: 既存 SKILL.md 読み込み → 失敗ケース・エラーログ分析 →
改善方針策定 → `skill-creator` で新版生成 → A/B テストへ(§7)。

## 7. A/B テスト(旧版 vs 新版)

設計上の注意: Claude Code はスキルを `name:` で識別するため、
**同名2スキルは併存できない**。A/B テストは旧版・新版を
**別ディレクトリ + 別名**にして行う(例: ディレクトリ
`kpop-article-v2/`、`name: kpop-article-v2`)。

- 旧版 `[skill]-v1` / 新版 `[skill]-v2` を並列稼働。
- 1週間で各10回以上呼び出し、Outcomes スコアで比較、有意差を判定。

結果に基づく決定:
- v2 が有意に優れる → v2 採用、v1 を archive
- 差がない → v1 維持(変更コストを避ける)
- v2 が劣る → 分析・再設計

結果保存: `/home/aiuser/.kpop_recovery/skill_ab_test_log.jsonl`

## 8. 廃棄・統合判定

- **廃棄候補**: 使用回数ゼロ ≥ 3週間 / 機能が他スキルに吸収済み /
  古い前提に基づく。
- **統合候補**: 機能が80%以上重複する2スキル / 連続呼び出しされる
  スキル群(workflow 化候補)。

廃棄・統合は owner-decision-queue 経由で承認後に実施。
archive 先: `/home/aiuser/.claude/skills_archive/`

## 9. Dreaming との連動(将来)

Dreaming(Claude Managed Agents・research preview)が GA になったら:
セッション間のメモリ精錬をスキル改善に活用 / 「同じミスを繰り返す
スキル」の自動検出 / パターン抽出 → 改善版生成。

現状(2026-05時点): Dreaming は申請制 research preview。
skill-evolution は手動 + 半自動で運用し、Dreaming GA 時に再評価する。

## 10. orchestration-leader との連動

skill-evolution は [[orchestration-leader]] の配下:
- 週次レポートを orchestration-leader に集約
- 改善提案を脳経由でオーナーに上申
- 承認後の実装は `skill-creator` 経由

呼び出しトリガー: 週次定期実行(日曜 02:00)/ 手動「skill 効果測定して」/
重大なスキルエラー発生時。

## 11. 100point-rubric-judge O項目との連動

| O項目 | 基準 | 判定方法 |
|---|---|---|
| O-1 | skill-evolution skill 完成 | スキル存在で 1点 |
| O-2 | 繰り返しタスク検出 → 自動スキル化 | 検出回数で判定 |
| O-3 | 既存スキルの効果計測 | 週次レポートで判定 |

## 12. 出力ルール

- **効果計測レポート(週次)**: 上位5スキル(使用頻度・効果)/
  下位3スキル(廃棄・改善候補)/ 新規スキル提案 / A/B テスト結果。
- **改善提案**: 1スキル1行サマリ。詳細は要求時のみ。
  owner-decision-queue 連携時はその ID を示す。
- **廃棄・統合提案**: 影響範囲(依存スキル)/ 移行手順 / ロールバック方法。
- 計測値は実測。「たぶん使われている」で済ませない。

## 13. 安全設計

スキル変更時の保護:
- 改善前に必ず旧版を archive する。
- A/B テスト中は両版を稼働(片方が失敗しても運用継続)。
- 廃棄前に1週間の「警告期間」を置く。
- 統合時は依存スキルをすべて確認する。

暴走防止:
- スキル自動生成は週あたりの上限を設ける。
- 重要スキル([[error-evidence]] 等)は廃棄候補から除外する。
- 統合は手動承認必須(機能消失リスクのため)。

## 14. メタ階層と自己参照

skill-evolution は meta-meta-skill:
スキル(個別タスク)→ `skill-creator`(スキル作成)→
**skill-evolution**(スキル改善)の3階層目。これより上は
[[orchestration-leader]](エージェント指揮)のみ。

**自己参照の注意**: skill-evolution 自身もスキルなので、改善対象に
なりうる。自己参照ループを避けるため、**skill-evolution 自身の改善は
orchestration-leader 経由でオーナー判断を必須**とする。
自分で自分を書き換えない。
