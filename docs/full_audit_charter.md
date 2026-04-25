# 完全監査憲章 (Full Audit Charter v1)

## 目的
全投稿(post + popup)の品質を16項目で完全監査し、問題を自動修正する基盤。

## 対象 post types
- post (通常記事)
- popup (ポップアップ情報)

## 16項目チェックリスト

### A. メタデータ完全性 (4項目)
1. **title長**: post 42字 / popup 60字以内、最低10字
2. **slug**: 英数、URLエンコード混入禁止
3. **featured_media**: サムネ必須
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

## severity分類
- **high**: 公開停止検討 (no_thumbnail, content_short, AI言及等)
- **medium**: 修正推奨 (meta_desc_short, x_missing等)
- **low**: 軽微 (title_long, slug_long等)

## パイプライン

```
full_audit_runner (毎時)
  → audit_state.jsonl
  ↓
audit_fixer_universal (毎時+30分)
  → GPT修正 → WP更新
  ↓
popup_publish_enricher (毎時+45分)
  → GSC + X配信
```

## cron スケジュール
- `0 * * * *` full_audit_runner
- `30 * * * *` audit_fixer_universal
- `45 * * * *` popup_publish_enricher
- `45 */6 * * *` popup_audit (既存、段階的に full_audit_runner に統合)
