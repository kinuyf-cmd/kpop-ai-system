# 完全監査憲章 (Full Audit Charter v2)

## 目的
全投稿(post + popup)の品質を17項目で完全監査し、問題を自動修正する基盤。
第13部門「品質監査部」として独立運用。

## 対象 post types
- post (通常記事)
- popup (ポップアップ情報)

## 17項目チェックリスト

### A. メタデータ完全性 (4項目)
1. **title長**: post 42字 / popup 60字以内、最低10字
2. **slug**: 英数、URLエンコード混入禁止、20-60字
3. **featured_media**: サムネ必須 (>0)
4. **category**: post=WPカテゴリ / popup=_popup_city 必須

### B. SEO要件 (4項目)
5. **meta_description**: 80-160字 (excerpt参照)
6. **OGP**: og:image (featured_media) 必須
7. **JSON-LD**: テーマ側で自動生成前提
8. **canonical**: 本文内重複canonical禁止

### C. 本文品質 (3項目)
9. **本文長+日本語比率**: 200字以上、日本語30%以上
10. **誤字・蛇足パターン**: 12種検出 (AI言及/メタ表現/サレシー等)
11. **HTMLタグ閉じ**: h2/p の開閉数一致

### D. 配信完全性 (3項目)
12. **GSC Indexing通知**: 投稿後1時間以内 (indexing_api_sends.jsonl)
13. **X投稿**: 投稿後1時間以内 (x_posts.jsonl)
14. **internal_links**: post 2本以上 / popup 1本以上

### E. 自動回復 (2項目)
15. **rewrite_target**: high issue 3件以上
16. **quarantine_target**: high issue 5件以上

### F. LLM校閲 (1項目) ★v2新設
17. **GPT-4o-mini校閲**: 誤字脱字/事実誤認/不自然な日本語/タイトル不整合
    - critical: 事実誤認・重大誤字 → high扱い、audit_fixerキュー追加
    - high: 不自然な日本語・タイトル不整合 → high扱い
    - medium: 表現の改善余地 → medium扱い

## severity分類
- **high**: 公開停止検討 (no_thumbnail, content_short, AI言及, llm_critical等)
- **medium**: 修正推奨 (meta_desc_short, x_missing, llm_medium等)
- **low**: 軽微 (title_long, slug_long等)

## パイプライン

```
full_audit_runner (毎時05分)
  → 項目1-16チェック → audit_state.jsonl
  → LLM校閲結果参照 (項目17)
  ↓
llm_proofreader (4時間毎)
  → GPT-4o-mini校閲 → logs/llm_audit/YYYYMMDD_HH.json
  → critical/high → llm_audit_alerts.log + audit_state.jsonl
  ↓
audit_fixer_universal (毎時35分)
  → GPT修正 → WP更新
  ↓
popup_publish_enricher (毎時45分)
  → GSC + X配信
  ↓
post_audit_feedback_loop (毎時10分・40分)
  → 投稿5-60分後に再監査
  → docs/agent_lessons/{agent}.md 教訓蓄積
```

## cron スケジュール
| 時刻 | コマンド | 備考 |
|------|---------|------|
| `05 * * * *` | full_audit_runner | 16項目+LLM結果統合 |
| `10,40 * * * *` | post_audit_feedback_loop | 投稿直後再監査 (5-60分window) |
| `25,55 * * * *` | post_thumbnail_generator | サムネ自動生成 |
| `35 * * * *` | audit_fixer_universal | 自動修正 |
| `45 * * * *` | popup_publish_enricher | GSC+X配信 |
| `0 */4 * * *` | llm_proofreader | LLM校閲 (4時間毎) |

## 教訓蓄積
- エージェント別: docs/agent_lessons/{agent}.md
- 全体: docs/lessons_learned.md
- 機械可読: config/latest_rules.json

## 変更履歴
- v1 (2026-04-25): 16項目監査基盤
- v2 (2026-04-26): 項目17 LLM校閲追加、feedback_loop window拡大(5-60分)、agent_lessons初期投入
