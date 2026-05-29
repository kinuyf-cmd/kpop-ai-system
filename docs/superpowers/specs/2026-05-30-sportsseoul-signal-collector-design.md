# Sports Seoul (스포츠서울) 速報シグナル collector 追加 — 設計

- 日付: 2026-05-30
- 起案: owner 依頼「速報シグナルに https://www.sportsseoul.com/ を追加できますか？」
- ステータス: 承認待ち

## 目的

韓国スポーツ・芸能メディア Sports Seoul を速報シグナルソースに追加し、
trend_signals.jsonl のソース多様性を上げる。収集範囲は owner 決定により
**韓流芸能全般**（K-POP に加え、K-POP 文脈のドラマ/映画/バラエティ/OST/俳優/한류）。

## 背景・既存アーキテクチャ

- 各韓国メディアは `lib/collectors/<name>_collector.py` の `collect()` で
  リスティングページを取得 → 正規表現で記事リンク+タイトル抽出 →
  フィルタ通過分を `make_signal()` 化 → `save_signals()` で
  `data/trend_signals.jsonl` に append（24h URL dedup 内蔵）。
- 全 collector は `collect_all_signals.py` の `COLLECTORS` リストから
  `importlib` で順次実行され、既存の collect-all cron に乗る（新規 cron 不要）。
- `save_signals()` は urgency=high 検出時に breaking_news_detector を起動する。
- 信頼ソース判定は `config/source_domains.json` を全工程が共通参照。
  **collector 追加時にここへドメインを足さないと post_publish_hook が
  新ソース記事を全 BLOCK する**（2026-05-07 事故の再発防止＝本設計の必須項目）。

## サイト実地調査（2026-05-30 実測）

- `https://www.sportsseoul.com/` トップが `/news/read/<数字ID>` 形式の記事リンクを
  **静的に約142件**出力。アンカーテキストがそのまま記事タイトル（クリーン）。
- 例: Red Velvet ジョイ、第35回 서울가요대상 팬투표、K-POP 월드초이스、싸이 흠뻑쇼 など
  K-POP/芸能/スポーツが混在。
- セクション listing ページ（`/news/list/...`, `/category/...`, `/enter` 等）は**全て 404**。
  ナビメニューは JS レンダリングで静的 href 無し。
- 結論: **トップページ1枚を取得元とする**のが唯一確実な静的経路（owner 承認済）。

## 設計

### 変更ファイル（3点のみ）

#### 1. 新規 `lib/collectors/sportsseoul_collector.py`

`sportschosun_collector.py` を雛形に、`korean_base` の
`fetch_html / is_kpop_related / is_urgent / save_signals / make_signal / log` を流用。

- 取得元: `https://www.sportsseoul.com/`
- 抽出パターン: `<a ... href="(/news/read/\d+)" ...>タイトル</a>`
  （`re.DOTALL`、タイトルは `<[^>]+>` 除去 + `korean_base.clean_title` で整形）
- URL 正規化: 相対 → `https://www.sportsseoul.com` 前置
- `seen` セットで同一ページ内 URL 重複排除、タイトル長 < 5 はスキップ
- **フィルタ（韓流芸能全般ゲート）**:
  ```
  kw = is_kpop_related(title)            # K-POP 固有名/イベント語
  if kw:                                  # K-POP は従来通り通過
      keywords = kw
  elif is_entertainment(title):          # 本 collector 専用の芸能ゲート
      keywords = ['한류']                 # generic 芸能シグナルとして記録
  else:
      continue                            # スポーツ/政治/事故はここで除外
  ```
  - `is_entertainment()` は本 collector 内のローカル関数。韓流芸能キーワード
    （드라마/영화/배우/예능/OST/한류/넷플릭스/디즈니+/티빙/주연/출연/방영/시즌 等）を
    substring 判定。**スポーツ専用語（축구/야구/배구/감독/리그/월드컵/시구 等は除外条件）
    は通さない**ことで sports 記事の混入を最小化。
  - 過剰収集（signal 段階での芸能寄り過多）は許容方針: signal ≠ article であり、
    記事化は下流の非K-POPトピック除外フィルタ(476ed0a)が最終防御するため。
- `source_id = 'sports_seoul'`
- 上限 20 signals（既存 collector と同一）
- 緊急判定: `is_urgent(title)`（既存 URGENT_KW 流用）
- 実行関数名 `collect()`（collect_all が `main/collect/run` を順に探索）

#### 2. `collect_all_signals.py`

`COLLECTORS` リストに `"sportsseoul"` を1語追加。これだけで既存 collect-all
cron に自動で乗る。1つ失敗しても他は継続する except 設計のため安全。

#### 3. `config/source_domains.json`

`trusted_korean_media` に `"sportsseoul"` を追加。`_history` に追記。
**省略すると post_publish_hook が当ソース記事を全 BLOCK する**（最重要）。

### やらないこと（YAGNI）

- 新規 cron 登録: 不要（collect-all 相乗り）
- セクション別 listing 巡回: 静的到達不能。Playwright 等の追加依存は導入しない
- dedup キー/記事化ロジック変更: 下流 signal_deduplicator / breaking_news_selector が
  既存通り処理。本タスクの範囲外
- スポーツ記事の積極収集: K-POP メディアの趣旨外

## エラーハンドリング

- fetch 失敗は try/except で握り `log()` 出力 + `return 0`（他 collector を止めない）
- 正規表現でタイトル抽出ゼロでも空 `save_signals([])` で正常終了

## テスト

- `python3 lib/collectors/sportsseoul_collector.py` を直接実行し、
  K-POP記事（Red Velvet 等）が signal 化、純スポーツ（축구/야구）が除外されることを実データで確認
- `python3 collect_all_signals.py` でリストに乗り [ok] sportsseoul が出ることを確認
- `config/source_domains.json` が `json.load` で壊れていないこと
- pre-push hook（py_compile / 機密チェック）通過
