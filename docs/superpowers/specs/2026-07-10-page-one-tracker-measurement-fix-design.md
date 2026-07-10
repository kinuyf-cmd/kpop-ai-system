# SEO 計測レイヤ 3欠陥の根治 — 設計

- 日付: 2026-07-10
- 対象: `lib/page_one_tracker.py`, `lib/seo_feedback_loop.py`, `lib/seo_auto_rollback.py`
- 方針: 採用案 A（計測の3欠陥をまとめて直す）

## 背景

SEO 自己改善ループ（scanner → bridge → enrich/rewrite → tracker → feedback → rollback）の
うち、計測にあたる tracker に欠陥があり、下流の feedback_loop と auto_rollback が
誤った判断を出していた。

`data/page_one_progress.jsonl` の週次トレンド自体は回復基調にある
（Σclicks 増減 -16 → -15 → -13 → -5 → +9、順位改善 5/17 → 12/16）。
パイプラインは停止していない。壊れているのは計測と、それに基づく判断である。

なお `body_enrich` / `auto_rewriter` の cron は故障ではない。cron 追加が 07-08(水)、
実行指定が月曜のため初回発火が 07-13(月) でまだ来ていないだけ。両者とも dry-run で
正常動作を確認済み。

## 問題（実測で確認した3つ）

### 欠陥1: tracker が slug を空文字で固定

`lib/page_one_tracker.py:80`

```python
qs.setdefault(r["query"], {"slug": "", "potential": r.get("potential", 0)})
```

`seo_opportunity_queue.json` 由来（lane_C/B）のクエリは slug を持たないまま baseline に
入り、progress にも空のまま流れる。

- 実測: `page_one_progress.jsonl` の slug 空率は各週 71〜88%（最新週 12/16 = 75%）
- 被害: `seo_auto_rollback._latest_clicks_delta()` が slug で突合するため、
  enrich 済み5件のうち3件（`kpop-demon-hunters-golden-analysis`,
  `kpop-demon-hunters-inserted-songs`, `xg-fashion-visual-concept-analysis`）が
  `delta is None` で素通りし、効果判定されない。効かなかった拡充が差し戻されない。

### 欠陥2: tracker が上流の theme を捨てる

`seo_opportunity_queue.json` は最初から theme を持つ。

```json
{"query": "golden 歌手", "theme": "movie_anime", "potential": 3797, ...}
```

tracker はこれを baseline に載せない。そのため `seo_feedback_loop._slug_theme_map()` は
slug 経由で theme を引き直そうとし、slug が空なので全件ミスする。

- 実測: 直近77件が **77/77 で `theme="unknown"`**。
  enrich_queue と progress の slug 積集合はわずか1件。
- 被害: 2026-07-10 に以下の提案が生成され owner 承認待ちになっている。

  > `theme='unknown'` は効果薄。enrich 対象からの一時除外を検討

  unknown は全件なので、これは実質「全記事を enrich 対象から外せ」を意味する。**却下対象。**

### 欠陥3: clicks_delta が時間経過を測っている

`do_weekly()` は `cur["clicks"] - b["baseline_clicks"]` を計算する。両者とも
**28日間の累積クリック**であり、baseline は 2026-05-26 に固定されている。
5月のバズが28日窓から抜ければ機械的にマイナスへ張り付く。

実測（`ojogang メンバー`, baseline_clicks=14, 現在 clicks=0）:

```
2026-06-12 pos8.68→10.14 clk_delta=-14
2026-06-19 pos8.68→10.38 clk_delta=-14
2026-06-26 pos8.68→10.38 clk_delta=-14
2026-07-03 pos8.68→ 8.33 clk_delta=-14
2026-07-10 pos8.68→ 5.11 clk_delta=-14   ← 順位は改善しているのに -14 で固着
```

0 − 14 = −14 の下限に張り付いているだけで、劣化ではない。
そして **この値が feedback_loop の判定根拠 `clicks_delta_avg` そのもの**である。

欠陥1と2だけを直すと、theme が正しく分類されるぶん
「dance_show テーマは効果薄」のような、より説得力のある誤提案が出るようになり、
かえって危険。3つは同じ関数に同居しており、分割して直す利益がない。

## 変更内容

新規モジュールは作らない。既存関数の置換のみ。本番 WordPress への書き込みは発生しない。

### 変更1: `_target_queries()` が theme を持ち越す

`enrich_queue` / `seo_opportunity_queue` 双方から `theme` を meta に載せる。
実測で **採用50件（lane_C 30 + lane_B 20）の theme 欠落はゼロ**
（`movie_anime` 12, `dance_show` 10, `artist` 8, `other` 12, `kdrama` 4, `trend_goods` 3, `awards` 1）。
`unknown` フォールバックは実質不要。

### 変更2: `_query_position()` を query×page 次元へ

```python
body = {
    "dimensions": ["query", "page"],
    "dimensionFilterGroups": [{"filters": [
        {"dimension": "query", "operator": "equals", "expression": query}]}],
    "rowLimit": 25,
}
```

返却行から以下を導出する。

- `clicks` / `impressions`: 全行の合算（アンカー分割による過小評価を防ぐ）
- `position`: **imp 加重平均**。単純平均は imp=2 のアンカー行に引きずられる
- `slug`: フラグメント除去 → slug 集約 → 集約 imp 最大。
  tie-break は `(imp, slug)` タプルで辞書順に安定化する。
  これを怠ると実行ごとに slug が揺れ、rollback の突合が不安定になる

実測 `ojogang メンバー`（窓 2026-06-10..07-07、7行、imp 92 + 2×6）での期待値:

| 項目 | 期待値 | 備考 |
|---|---|---|
| clicks | 0 | 全行0 |
| impressions | 104 | 合算 |
| position | **5.79** | 加重平均。単純平均だと 9.74 |
| slug | `swf3-osaka-ojo-gang-members` | 集約 imp 104 |

この 7 行は本文 URL 1 行 + `#kpop-h-0`〜`#kpop-h-6` のアンカー 6 行。
単純平均が 9.74 まで悪化するのは、imp=2 のアンカー行が本文行と同じ重みで
効いてしまうため。加重平均ならアンカーの影響は 12/104 に収まる。

なお 5.79 は GSC 表示値（小数2桁に丸めた 5.18 / 10.50）から計算した値。
GSC が内部で返す未丸め float から計算すると 5.80 になる。テストは前者を
使う（下記フィクスチャの定義がそのまま期待値を決めるため）。

query×page で slug が実際に取れることは検証済み。
`golden 歌手` → `kpop-demon-hunters-golden-analysis`、
`デーモンハンターズ 曲` → `kpop-demon-hunters-inserted-songs`。
いずれも欠陥1で rollback が判定不能だった3件に含まれる。逆引きで同時に治る。

### 変更3: `clicks_delta` を前週比へ

```python
prev = _last_progress_row(query)   # progress.jsonl の同一 query 最終行
clicks_delta = cur["clicks"] - (prev["clicks_abs"] if prev else cur["clicks"])
```

progress の行に絶対値と基準の別を必ず書く。

```json
{"week": "2026-07-17", "query": "ojogang メンバー",
 "slug": "swf3-osaka-ojo-gang-members", "theme": "dance_show",
 "clicks_abs": 0, "clicks_delta": 0, "delta_basis": "prev_week",
 "baseline_pos": 8.68, "current_pos": 5.80}
```

- `clicks_abs` が無いと翌週の前週比が計算できない。新設必須。
- 過去122行に `clicks_abs` は無いため、初回のみ `prev is None` として
  `clicks_delta=0` から再出発する（差分ゼロ＝判断保留。誤って「悪化」と読まれない）。
- `delta_basis` は `"baseline"`（過去行）と `"prev_week"`（新規行）を区別する。
  下流はこれで定義の混在を判別できる。

`baseline_pos` は変更しない。`baseline_clicks` は算出に使わなくなるが、監査のため残置。

### 変更4: `seo_feedback_loop.aggregate()` の迂回を削除

`_slug_theme_map()` を削除し、progress 行の `theme` を直読みする。
slug 経由の引き直しは構造的に不要。

### 変更5: `seo_auto_rollback` に安全弁

`ROLLBACK_CLICKS_DELTA_THRESHOLD = -3` のコメントは
「baseline比でこれ以下悪化していたら差し戻し」。前週比に変わると -3 の重みが変わる。
累積比の -3 は「5月比で3クリック減」、前週比の -3 は「先週から3クリック落ちた」で、
はるかに起きやすい。そのまま流すと過剰に差し戻す。

1. `delta_basis == "prev_week"` の行しか評価しない（定義の混ざった行で判断しない）
2. 初回1サイクルは `--dry-run` 固定で cron 実行し、新しい delta 分布をログ出力するのみ
3. 分布を観測してから閾値を決め、その後 dry-run を外す

**閾値はこの設計では決め打ちしない。** 推測で数字を置くと、
`potential`（480日累積の幻）と同じ轍を踏む。

#### 移行第1週は rollback が構造的に発火しない（想定内）

`_latest_clicks_delta()` は同一 slug の progress 行を週順に並べ最終行を返す。
移行直後は以下が連鎖する。

- 過去122行の slug は 75% が空。slug 突合で拾えるのは4件のみ
- その4件に `delta_basis` は無く、ガード1で評価対象から外れる
- 変更3により新規行の初回は `prev is None` → `clicks_delta = 0`

結果、**移行第1週の `prev_week` 行は全件 `clicks_delta = 0`** となり、
閾値 -3 を下回る行は構造的に存在しない。rollback は第2週まで発火しない。

これは安全側の正しい挙動だが、**第1週の dry-run ログを見て閾値を決めてはならない。**
分布が全件ゼロなのは実態ではなく初期化の副作用である。
閾値決定に使えるのは、`prev_week` 行が2週分そろった**第2週以降**の分布のみ。

## エラー処理

| 事象 | 挙動 |
|---|---|
| GSC が空行を返す（圏外） | 従来どおり `None` を返しその週はスキップ。既存挙動を変えない |
| `impressions` 合計が 0 | 加重平均がゼロ除算。position は単純平均にフォールバック |
| slug 逆引き不能（外部ドメイン等） | `slug=""` を許容。theme は queue 由来なので生き残る |

theme は slug に依存しない。変更2が失敗しても変更4は機能する。この独立性は意図的。

## テスト

GSC API 呼び出しと判断ロジックを分離し、純関数を単体テストする。

**テストは GSC を叩かない。** 実測7行を写し取った固定フィクスチャを関数に渡す。
GSC の28日窓は毎週スライドするため、ライブ値をアサートするとテストが時間経過で
勝手に壊れる。実測値は「そういう形の行が実在する」ことの根拠として設計文書に
記録し、テストからは切り離す。

```python
# tests/test_page_one_tracker.py
ROWS = [
    {"position": 5.18, "impressions": 92},
    *({"position": 10.50, "impressions": 2} for _ in range(6)),
]
```

| 対象 | 種別 | 検証内容 |
|---|---|---|
| `_slug_of(url)` | 単体 | `#kpop-h-0` 除去、クエリ文字列除去、末尾スラッシュ、外部ドメインで `""` |
| `_pick_slug(rows)` | 単体 | フィクスチャ → `swf3-osaka-ojo-gang-members`。imp 同数時に辞書順で決定的 |
| `_weighted_position(rows)` | 単体 | フィクスチャ → **5.79**（単純平均 9.74 でないこと） |
| `_weighted_position` | 単体 | imp 合計0 → 単純平均にフォールバック |
| `_clicks_delta(cur, prev)` | 単体 | `prev=None` → 0、`prev` あり → 前週差 |
| `aggregate()` | 統合 | theme 直読みで `unknown` が消える |

5.79 / 9.74 はフィクスチャから決まる定数であり、GSC の状態に依存しない。

rollback は閾値を決め打ちしないため合否テストを書かない。
代わりに dry-run が delta 分布を出力することを確認する。

## 移行手順（順序が重要）

1. `migrate_baseline_theme.py` を作り、baseline に **theme のみ** 後付け。
   `baseline_pos` は一切触らない。事前にコピーを取り、差分を diff で目視確認
2. `page_one_tracker.py` を変更（変更1〜3）。単体テストを先に書く（TDD）
3. dry-run 相当で1回走らせ、progress へ書かずに出力だけ検証。
   **slug 逆引き率が 75%空 → ほぼ0% になることを実測**
4. `seo_feedback_loop.py` の `_slug_theme_map()` を削除（変更4）。
   theme 別集計が `movie_anime` / `dance_show` / `artist` に分かれることを確認
5. `seo_auto_rollback.py` に `delta_basis` ガードと dry-run 固定を入れる（変更5）
6. `logs/seo_config_proposals.jsonl` の pending 提案を却下済みにマーク

Step 3 を挟むのは、`page_one_progress.jsonl` が追記専用の計測ログであり、
壊れた行を書くと取り返しがつかないため。推測でなく実測で確認してから進める。

## ロールバック計画

- `page_one_progress.jsonl` は追記のみ。異常行は `week` が当日の行を削除すれば原状復帰
- `page_one_baseline.json` は Step 1 の前にコピーを取る
- コード変更は git で戻せる
- 本番 WP への書き込みは発生しない（tracker/feedback_loop は読み取り専用、rollback は dry-run 固定）

## スコープ外（意図的に含めない）

- `potential` の再計算。480日累積の幻は既知だが、着手判断をするのは人間であり、
  今回の計測バグとは独立
- 過去122行の遡及修正。progress は「その時点の観測事実」であり、
  後から書き換えると監査性が壊れる。feedback_loop は直近4週しか見ないため、
  3週後には自然に全件正しい theme になる
- `baseline_clicks` の削除。監査のため残置

## 実測結果（Step 3 dry-run / 実行日: 2026-07-10）

本番 GSC を叩き、progress へは書き込まずに出力のみを検証した。

- slug 空率: 12/16 (75%) → **0/17 (0%)**
- theme 種別: `['unknown']` → **`['dance_show', 'movie_anime', 'trend_goods', 'unknown']`**
  （baseline 26クエリのうち unknown は 4件。現 queue から消えたクエリ）
- progress 行数: 122 のまま（書き込みなし・`clicks_abs` を持つ行 0）
- `ojogang メンバー`: `baseline_pos 8.68 → current_pos 5.83`、`clicks_delta` は **-14 固着から 0（判断保留）へ**

実測 position 5.83 は、フィクスチャで検証した imp 加重平均 5.79 とほぼ一致した
（GSC の28日窓が dry-run 実行日までスライドしたぶんの差）。

## 成功基準

移行直後に検証できるもの（Step 3 の dry-run 出力で確認）:

1. progress 新規行の slug 空率が 75% → 5% 未満
2. feedback_loop の theme 別集計が `unknown` 単一でなく実 theme に分かれる
3. `ojogang メンバー` の `clicks_delta` が -14 固着から解放される（初回は 0）
4. 単体テストが全て green

第2週以降でないと検証できないもの:

5. rollback が enrich 済み5件すべてを評価対象にできる（`delta is None` が消える）。
   slug 付き `prev_week` 行が2週分そろって初めて成立する
6. `prev_week` の delta 分布が観測でき、閾値を実測から決められる
