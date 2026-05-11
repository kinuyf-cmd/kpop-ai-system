# Generator 統合・段階的 deprecation 計画 (2026-05-11)

## 背景
13本の generator が並立し、それぞれ独自に source処理 / 翻訳 / サムネ / publish を実装。
2026-05-11 に canonical な `lib/simple_publish_pipeline.py` (232行) を新設。
新規 trusted source 由来の publish はこの canonical pipeline 経由に統一していく。

## 現状 inventory

| generator | 用途 | 主な問題 | 統合方針 |
|---|---|---|---|
| `lib/cv_article_generator.py` | CV (キャリア) 記事 | status='draft'固定で実害低 | **保持** (固定情報生成の特殊用途) |
| `lib/cluster_generator.py` | アーティスト記事クラスター | pre_publish_gate 統合済 (2026-05-11) | **保持** (artist固定page) |
| `lib/demon_hunters_generator.py` | デモハン特集 | pre_publish_gate 統合済 | **保持** (特集記事) |
| `lib/birthday_article_generator.py` | 誕生日記事 | 固定slug `*-birthday-{year}` | **保持** (定期生成) |
| `lib/kpop_quiz_generator.py` | クイズ記事 | テンプレ生成 | **保持** (特殊用途) |
| `lib/media_kit_generator.py` | メディアキット | 内部用 | **保持** |
| `lib/news_sitemap_generator.py` | sitemap生成 | publish と独立 | **保持** |
| ~~`lib/seo_longtail_generator.py`~~ → `lib/deprecated/` | longtail SEO テーマ生成 | 2026-04-17 以降未稼働 / 消費者0 | **deprecated (2026-05-11)** |
| ~~`lib/stock_topic_generator.py`~~ → `lib/deprecated/` | ストック topic 提案 | 2026-04-16 以降未稼働 / 消費者0 | **deprecated (2026-05-11)** |
| `lib/artist_page_generator.py` | artist固定page | スケジュールUPDATE | **保持** |
| `pipeline/feature_article_generator.py` | feature記事 | LLM単独生成、ソースなしリスク | **deprecate** → simple_publish推奨 |
| `pipeline/search_driven_generator.py` | 検索意図駆動 | 検索クエリベース、ソース弱い | **要レビュー** |
| `pipeline/post_thumbnail_generator.py` | 既存記事サムネ補修 | publish起点ではない | **保持** |
| **`lib/simple_publish_pipeline.py`** | **canonical (新設)** | **og:image最優先 + draft default + 232行** | **これを新標準とする** |

## 段階的 deprecation 方針

### Phase 1: 新規 trusted source は simple_publish_pipeline 経由に集約 (今すぐ)
- `pipeline/simple_publish_bridge.py` cron `0 7-21/3 * * *` で稼働
- soompi/koreaboo/allkpop/kpophit/kstyle 等の信頼ドメインを優先
- **既存 generator は新規 trusted source 由来記事を生成しない**

### Phase 2: feature_article_generator は別職務認定 (2026-05-11確定)
- feature_article_generator は **テーマ駆動の LLM 生成記事** (factcheck込み)
- simple_publish は **1ソース直接翻訳記事** (LLM最小限)
- 両者は別職務 → 委譲ではなく **共存**
- 確認済:
  - feature_article_generator は unified_publish 経由 → pre_publish_gate統合済
  - `_verify_against_sources` で hallucination 検出
  - `post_publish_audit` で公開後即時監査
  - **追加対応不要**

### Phase 3: search_driven_generator は publish path 外 (2026-05-11確定)
- 確認済: search_driven は GSCデータ → `auto_directives.json` テーマ注入のみ
- **publish 自体は行わない** (他 generator が auto_directives を見て生成)
- 直接の hallucinationリスク無し → **追加対応不要**
- ただし auto_directives 経由のテーマが品質低下を招く可能性は残る → 月次品質メトリクスで観察

### Phase 4: deprecate候補の正式 deprecation (2026-05-11 完了)
- ✅ `lib/seo_longtail_generator.py` → `lib/deprecated/` 移動済
- ✅ `lib/stock_topic_generator.py` → `lib/deprecated/` 移動済
- 廃止根拠 (30日測定の代わりに silent rot 検出):
  - 両者とも cron 未登録 → 25日以上稼働実績なし
  - 出力ファイル (`stock_topics.json` / `seo_longtail_themes.json`) の消費者なし (grep 全件確認)
  - Python import / agent prompt 参照なし
  - `auto_directives.focus_themes` 46件中 source=seo_longtail は 0件 (実績なし)
  - 同等機能は search_driven / pv_kpi_winner_expansion / gsc_unmet_demand / winning_pattern_expander が代替
- 副次変更:
  - `run_seo_daily.sh` から longtail step / Discord longtail summary 削除
  - docstring 先頭に `[DEPRECATED 2026-05-11]` ヘッダ追加

### 永久に保持
- 特殊用途generator (cv/cluster/demon/birthday/quiz/artist_page/media_kit/sitemap)
- これらは固有のフォーマット保持が目的でsource-from-translateとは別パス

## 移行 KPI

| 指標 | 現状 | 1週後目標 | 1ヶ月後目標 |
|---|---|---|---|
| simple_publish 経由 publish 率 | 0% | 30% | 60% |
| 新規 hallucination CRITICAL 件数/週 | 不明 | <2 | 0 |
| og:image 設定率 (new posts) | ~70% | 95% | 99% |
| 直接WP API publish (gate bypass) 件数 | 不明 | 0 | 0 |

## 実装済 (2026-05-11)
- ✅ canonical pipeline (`lib/simple_publish_pipeline.py`)
- ✅ bridge cron (`pipeline/simple_publish_bridge.py`)
- ✅ memory_compliance test 5件 (`test_simple_pipeline_canonical.py`)
- ✅ smoke test: BTS V × IVE Wonyoung 記事を draft化、4項目 全 pass
- ✅ smoke test: BOYNEXTDOOR comeback記事を bridge経由で draft化
- ✅ Phase 4 完了: seo_longtail_generator / stock_topic_generator を lib/deprecated/ へ移動

## 未実装 (継続観察)
- 月次 generator 出力品質メトリクス (auto_directives 経由テーマの品質測定含む)
- ※ feature_article / search_driven は Phase 2/3 で「対応不要」と確定済
