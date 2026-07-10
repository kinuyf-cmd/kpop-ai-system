# SEO 計測レイヤ 3欠陥の根治 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SEO 自己改善ループの計測層（`page_one_tracker.py`）が抱える3欠陥（slug 空固定・theme 破棄・clicks_delta が時間経過を測る）を根治し、下流の feedback_loop / auto_rollback が正しい判断を出せるようにする。

**Architecture:** 新規モジュールは作らない。`page_one_tracker.py` の GSC 呼び出し部から「行の解釈」を純関数（`_slug_of` / `_pick_slug` / `_weighted_position` / `_clicks_delta` / `_last_progress_row`）として切り出し、GSC 非依存にしてフィクスチャで単体テストする。`_query_position` は `query` 次元から `query×page` 次元へ拡張し、slug 逆引きと imp 加重平均を導出する。theme は上流 queue から baseline を経由して progress まで持ち越す。

**Tech Stack:** Python 3, Google Search Console API (`googleapiclient`), pytest 9.0.3

**設計文書:** `docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md`

## Global Constraints

- **本番 WordPress への書き込みは一切発生させない。** tracker / feedback_loop は読み取り専用。rollback は本計画の全期間 `--dry-run` 固定。
- **テストは GSC API を叩かない。** 実測行を写した固定フィクスチャを純関数に渡す。GSC の28日窓は毎週スライドするため、ライブ値をアサートするとテストが時間経過で壊れる。
- **テスト実行コマンドは `python3 -m pytest`（システム python、pytest 9.0.3）。** `venv_kpi` に pytest は入っていない。既存テストの docstring にある `venv_kpi/bin/python3 -m pytest` は現状動かないので真似しない。
- **本番スクリプト実行は `venv_kpi/bin/python3`。** GSC 認証（`google_metrics/service_account.json`）は venv_kpi にのみ入っている。
- `lib.page_one_tracker` はモジュール import 時に GSC 依存を解決しない（`_service()` の関数内 import のため）。よって純関数テストにモックは不要。
- `data/page_one_progress.jsonl` は**追記専用の計測ログ**。壊れた行を書くと取り返しがつかない。progress へ書く前に必ず dry-run で出力を目視する。
- `baseline_pos` は絶対に書き換えない。`baseline_clicks` は算出に使わなくなるが監査のため残置。
- 過去122行の遡及修正はしない（progress は「その時点の観測事実」）。

## 実測済みの前提（すべて検証済み・再確認不要）

| 事実 | 値 |
|---|---|
| `page_one_progress.jsonl` 総行数 | 122行（7週分、2026-05-29〜07-10） |
| 最新週の slug 空率 | 12/16 = 75% |
| `seo_opportunity_queue.json` 採用50件の theme 欠落 | ゼロ（movie_anime 12, dance_show 10, artist 8, other 12, kdrama 4, trend_goods 3, awards 1） |
| `enrich_queue.json` | list 型・6件・`theme` キーを既に保持 |
| `page_one_tracker.py:80` | `qs.setdefault(r["query"], {"slug": "", "potential": ...})` |
| `LOOKBACK_WEEKS` (feedback_loop) | 4 |
| `ROLLBACK_CLICKS_DELTA_THRESHOLD` | -3 |
| ojogang メンバー baseline | `{"baseline_pos": 8.68, "baseline_clicks": 14, "slug": "", "potential": 521}` |

**ojogang メンバー のフィクスチャ（GSC 実測7行を写したもの）**

本文 URL 1行 + `#kpop-h-0`〜`#kpop-h-6` のアンカー6行。

| 項目 | 期待値 |
|---|---|
| impressions 合計 | 104 |
| **imp 加重平均 position** | **5.79** |
| 単純平均 position（誤り） | 9.74 |
| slug | `swf3-osaka-ojo-gang-members` |

---

## Task 1: 純関数 `_slug_of()` — URL から slug を取り出す

GSC の `page` 次元はフラグメント付き URL（`#kpop-h-0`）を別行として返す。slug 逆引きの土台。

**Files:**
- Modify: `lib/page_one_tracker.py`（`_query_position` の直前に追加）
- Create: `tests/unit/test_page_one_tracker.py`

**Interfaces:**
- Consumes: なし
- Produces: `_slug_of(url: str) -> str` — 自サイトの記事 slug。外部ドメイン・トップページなら `""`

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_page_one_tracker.py` を新規作成:

```python
#!/usr/bin/env python3
"""page_one_tracker 計測ロジックの単体テスト (2026-07-10)。

背景: tracker が slug を空固定・theme を破棄・clicks_delta が時間経過を測っていた。
設計: docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md

テストは GSC API を叩かない。実測7行を写した固定フィクスチャを純関数に渡す。
GSC の28日窓は毎週スライドするため、ライブ値をアサートすると時間経過で勝手に壊れる。

実行: python3 -m pytest tests/unit/test_page_one_tracker.py -v
"""
import lib.page_one_tracker as t


def test_slug_of_strips_fragment():
    """GSC が返すアンカー付き URL からフラグメントを除去する。"""
    url = "https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-0"
    assert t._slug_of(url) == "swf3-osaka-ojo-gang-members"


def test_slug_of_strips_query_string():
    """クエリ文字列を除去する。"""
    url = "https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/?utm_source=x"
    assert t._slug_of(url) == "swf3-osaka-ojo-gang-members"


def test_slug_of_handles_no_trailing_slash():
    """末尾スラッシュの有無どちらでも同じ slug を返す。"""
    assert t._slug_of("https://www.kpopjournal.tokyo/foo-bar") == "foo-bar"
    assert t._slug_of("https://www.kpopjournal.tokyo/foo-bar/") == "foo-bar"


def test_slug_of_returns_empty_for_external_domain():
    """外部ドメインは空文字。rollback が誤って他サイトの記事を差し戻さないため。"""
    assert t._slug_of("https://soompi.com/article/123") == ""


def test_slug_of_returns_empty_for_home_page():
    """トップページは記事ではないので空文字。"""
    assert t._slug_of("https://www.kpopjournal.tokyo/") == ""
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: FAIL — `AttributeError: module 'lib.page_one_tracker' has no attribute '_slug_of'`

- [x] **Step 3: 最小実装を書く**

`lib/page_one_tracker.py` の import 群に追加:

```python
from urllib.parse import urlsplit
```

`_query_position` の直前（現在の40行目付近）に挿入:

```python
def _slug_of(url):
    """自サイト記事 URL → slug。外部ドメイン/トップページは ""。

    GSC の page 次元は "#kpop-h-0" 等のフラグメントを別行で返すため除去する。
    """
    if not url:
        return ""
    parts = urlsplit(url)
    site_host = urlsplit(SITE).netloc
    if parts.netloc and parts.netloc != site_host:
        return ""
    return parts.path.strip("/").split("/")[-1]
```

`urlsplit` はフラグメントとクエリを `path` から自動で切り離すため、明示的な除去は不要。

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: PASS — 5 passed

- [x] **Step 5: コミット**

```bash
git add tests/unit/test_page_one_tracker.py lib/page_one_tracker.py
git commit -m "feat(tracker): URL から slug を逆引きする _slug_of を追加"
```

---

## Task 2: 純関数 `_weighted_position()` — imp 加重平均

単純平均は imp=2 のアンカー行に引きずられる。実測 ojogang で 5.79 が 9.74 に化ける。

**Files:**
- Modify: `lib/page_one_tracker.py`（`_slug_of` の直後）
- Modify: `tests/unit/test_page_one_tracker.py`

**Interfaces:**
- Consumes: なし
- Produces: `_weighted_position(rows: list[dict]) -> float` — 各 row は `{"position": float, "impressions": int}` を持つ

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_page_one_tracker.py` の末尾に追加:

```python
# ojogang メンバー の GSC 実測7行を写したフィクスチャ。
# 本文 URL 1行(imp=92) + #kpop-h-0..6 のアンカー6行(各 imp=2)。
# imp 合計 104。加重平均 5.79 / 単純平均 9.74。
# position は GSC 表示値(小数2桁)。この定義がそのまま期待値を決める。
ROWS = [
    {"position": 5.18, "impressions": 92},
    *({"position": 10.50, "impressions": 2} for _ in range(6)),
]


def test_weighted_position_is_impression_weighted():
    """imp 加重平均。単純平均 9.74 に引きずられないこと。"""
    assert round(t._weighted_position(ROWS), 2) == 5.79


def test_weighted_position_differs_from_naive_mean():
    """単純平均との差を明示。この差こそが欠陥2の被害額。"""
    naive = sum(r["position"] for r in ROWS) / len(ROWS)
    assert round(naive, 2) == 9.74
    assert round(t._weighted_position(ROWS), 2) != round(naive, 2)


def test_weighted_position_falls_back_on_zero_impressions():
    """imp 合計 0 ならゼロ除算。単純平均にフォールバックする。"""
    rows = [{"position": 4.0, "impressions": 0}, {"position": 6.0, "impressions": 0}]
    assert t._weighted_position(rows) == 5.0


def test_weighted_position_empty_rows_returns_zero():
    """空行なら 0.0。呼び出し側は rows 非空を保証するが念のため。"""
    assert t._weighted_position([]) == 0.0
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v -k weighted`
Expected: FAIL — `AttributeError: ... has no attribute '_weighted_position'`

- [x] **Step 3: 最小実装を書く**

`lib/page_one_tracker.py` の `_slug_of` の直後に挿入:

```python
def _weighted_position(rows):
    """imp 加重平均 position。imp 合計 0 なら単純平均にフォールバック。

    単純平均だと imp=2 のアンカー行が本文行と同じ重みで効き、順位が悪化して見える。
    """
    if not rows:
        return 0.0
    total_imp = sum(int(r.get("impressions", 0)) for r in rows)
    if total_imp <= 0:
        return sum(float(r.get("position", 0.0)) for r in rows) / len(rows)
    return sum(float(r.get("position", 0.0)) * int(r.get("impressions", 0))
               for r in rows) / total_imp
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: PASS — 9 passed

- [x] **Step 5: コミット**

```bash
git add tests/unit/test_page_one_tracker.py lib/page_one_tracker.py
git commit -m "feat(tracker): imp 加重平均 _weighted_position を追加"
```

---

## Task 3: 純関数 `_pick_slug()` — 集約 imp 最大の slug を決定的に選ぶ

tie-break を怠ると実行ごとに slug が揺れ、rollback の突合が不安定になる。

**Files:**
- Modify: `lib/page_one_tracker.py`（`_weighted_position` の直後）
- Modify: `tests/unit/test_page_one_tracker.py`

**Interfaces:**
- Consumes: `_slug_of(url) -> str`（Task 1）
- Produces: `_pick_slug(rows: list[dict]) -> str` — 各 row は `{"keys": [query, page_url], "impressions": int}`（GSC の query×page 応答形式）

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_page_one_tracker.py` の末尾に追加:

```python
def _row(page_url, imp):
    """GSC query×page 応答の行を作る。keys = [query, page]。"""
    return {"keys": ["ojogang メンバー", page_url], "impressions": imp}


# 実測7行を GSC 応答形式で写したもの。全て同一 slug に集約され imp 104 になる。
SLUG_ROWS = [
    _row("https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/", 92),
    *(_row(f"https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-{i}", 2)
      for i in range(6)),
]


def test_pick_slug_aggregates_fragments():
    """フラグメント別行を同一 slug に集約して選ぶ。"""
    assert t._pick_slug(SLUG_ROWS) == "swf3-osaka-ojo-gang-members"


def test_pick_slug_prefers_highest_aggregate_impressions():
    """集約 imp が最大の slug を選ぶ。行数ではなく imp 合計で決める。"""
    rows = [
        _row("https://www.kpopjournal.tokyo/loser/", 10),
        _row("https://www.kpopjournal.tokyo/loser/#kpop-h-0", 10),
        _row("https://www.kpopjournal.tokyo/winner/", 30),
    ]
    assert t._pick_slug(rows) == "winner"


def test_pick_slug_tie_break_is_deterministic():
    """imp 同数なら slug の辞書順で安定化。実行ごとに揺れると rollback 突合が壊れる。"""
    rows = [
        _row("https://www.kpopjournal.tokyo/zebra/", 50),
        _row("https://www.kpopjournal.tokyo/alpha/", 50),
    ]
    assert t._pick_slug(rows) == "alpha"
    # 入力順を反転しても同じ結果
    assert t._pick_slug(list(reversed(rows))) == "alpha"


def test_pick_slug_ignores_external_domains():
    """外部ドメイン行は slug 候補にしない。"""
    rows = [
        _row("https://soompi.com/article/123", 999),
        _row("https://www.kpopjournal.tokyo/mine/", 5),
    ]
    assert t._pick_slug(rows) == "mine"


def test_pick_slug_returns_empty_when_no_internal_page():
    """自サイト行が1つも無ければ空文字。theme は queue 由来なので生き残る。"""
    assert t._pick_slug([_row("https://soompi.com/a/1", 10)]) == ""
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v -k pick_slug`
Expected: FAIL — `AttributeError: ... has no attribute '_pick_slug'`

- [x] **Step 3: 最小実装を書く**

`lib/page_one_tracker.py` の `_weighted_position` の直後に挿入:

```python
def _pick_slug(rows):
    """query×page 行から代表 slug を選ぶ。集約 imp 最大、tie は辞書順で決定的に。

    GSC はフラグメント別に行を返すため、slug で集約してから比較する。
    tie-break を入れないと実行ごとに slug が揺れ、rollback の突合が不安定になる。
    """
    agg = {}
    for r in rows:
        keys = r.get("keys", [])
        if len(keys) < 2:
            continue
        slug = _slug_of(keys[1])
        if not slug:
            continue
        agg[slug] = agg.get(slug, 0) + int(r.get("impressions", 0))
    if not agg:
        return ""
    # imp 降順 → slug 昇順。max ではなく sorted で意図を明示する。
    return sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: PASS — 14 passed

- [x] **Step 5: コミット**

```bash
git add tests/unit/test_page_one_tracker.py lib/page_one_tracker.py
git commit -m "feat(tracker): 集約 imp 最大の slug を決定的に選ぶ _pick_slug を追加"
```

---

## Task 4: 純関数 `_clicks_delta()` / `_last_progress_row()` — 前週比へ

`cur - baseline_clicks` は28日累積同士の差で、時間経過を測っている。ojogang は順位が改善しても `-14` に固着していた。

**Files:**
- Modify: `lib/page_one_tracker.py`（`_pick_slug` の直後）
- Modify: `tests/unit/test_page_one_tracker.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `_clicks_delta(cur_clicks: int, prev_row: dict | None) -> int`
  - `_last_progress_row(query: str, path: str = PROGRESS) -> dict | None` — progress.jsonl の同一 query 最終行。`clicks_abs` を持つ行のみ対象

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_page_one_tracker.py` の末尾に追加:

```python
import json


def test_clicks_delta_returns_zero_when_no_prev():
    """初回は前週が無い。差分ゼロ = 判断保留。誤って「悪化」と読まれないため。"""
    assert t._clicks_delta(0, None) == 0
    assert t._clicks_delta(37, None) == 0


def test_clicks_delta_is_week_over_week():
    """前週比。累積 baseline との差ではない。"""
    assert t._clicks_delta(5, {"clicks_abs": 3}) == 2
    assert t._clicks_delta(3, {"clicks_abs": 5}) == -2


def test_clicks_delta_ojogang_escapes_minus_14():
    """回帰: ojogang は baseline_clicks=14 に対し cur=0 で -14 固着していた。
    前週も 0 なら delta は 0。順位改善が「劣化」と誤読されない。"""
    assert t._clicks_delta(0, {"clicks_abs": 0}) == 0


def test_last_progress_row_returns_latest_by_week(tmp_path):
    """同一 query の最終行を week 順で返す。"""
    p = tmp_path / "progress.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"week": "2026-07-03", "query": "ojogang メンバー", "clicks_abs": 5},
        {"week": "2026-07-10", "query": "ojogang メンバー", "clicks_abs": 2},
        {"week": "2026-07-10", "query": "別クエリ", "clicks_abs": 99},
    ]) + "\n", encoding="utf-8")
    row = t._last_progress_row("ojogang メンバー", str(p))
    assert row["clicks_abs"] == 2


def test_last_progress_row_ignores_legacy_rows_without_clicks_abs(tmp_path):
    """過去122行に clicks_abs は無い。それらは前週比の基準にできないので無視。"""
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(
        {"week": "2026-07-03", "query": "ojogang メンバー", "clicks_delta": -14},
        ensure_ascii=False) + "\n", encoding="utf-8")
    assert t._last_progress_row("ojogang メンバー", str(p)) is None


def test_last_progress_row_returns_none_when_file_missing(tmp_path):
    """progress が無ければ None。初回実行で落ちない。"""
    assert t._last_progress_row("何か", str(tmp_path / "nope.jsonl")) is None
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v -k "clicks_delta or last_progress"`
Expected: FAIL — `AttributeError: ... has no attribute '_clicks_delta'`

- [x] **Step 3: 最小実装を書く**

`lib/page_one_tracker.py` の `_pick_slug` の直後に挿入:

```python
def _last_progress_row(query, path=PROGRESS):
    """progress.jsonl の同一 query 最終行。clicks_abs を持つ行のみ対象。

    過去行(122行)に clicks_abs は無く、その clicks_delta は baseline 比で
    定義が違う。前週比の基準にはできないため None を返す。
    """
    if not os.path.exists(path):
        return None
    best = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("query") != query or "clicks_abs" not in r:
                continue
            if best is None or r.get("week", "") >= best.get("week", ""):
                best = r
    return best


def _clicks_delta(cur_clicks, prev_row):
    """前週比 clicks。前週が無ければ 0(判断保留)。

    従来は cur - baseline_clicks。両者とも28日累積であり、baseline は
    2026-05-26 固定。5月のバズが窓から抜ければ機械的にマイナスへ張り付く。
    """
    if not prev_row:
        return 0
    return int(cur_clicks) - int(prev_row.get("clicks_abs", 0))
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: PASS — 20 passed

- [x] **Step 5: コミット**

```bash
git add tests/unit/test_page_one_tracker.py lib/page_one_tracker.py
git commit -m "feat(tracker): clicks_delta を前週比に変える _clicks_delta/_last_progress_row を追加"
```

---

## Task 5: `_query_position()` を query×page 次元へ + `_target_queries()` が theme を持ち越す

純関数を組み立てて GSC 呼び出しに接続する。設計の変更1・変更2。

**Files:**
- Modify: `lib/page_one_tracker.py:40-63`（`_query_position`）
- Modify: `lib/page_one_tracker.py:66-83`（`_target_queries`）
- Modify: `lib/page_one_tracker.py:86-100`（`do_baseline` — theme を baseline に載せる）
- Modify: `tests/unit/test_page_one_tracker.py`

**Interfaces:**
- Consumes: `_slug_of`, `_pick_slug`, `_weighted_position`（Task 1-3）
- Produces:
  - `_rows_to_metrics(rows: list[dict]) -> dict` — `{"position": float, "clicks": int, "impressions": int, "slug": str}`
  - `_target_queries() -> dict[str, dict]` — 値に `{"slug", "potential", "theme"}` を含む

`_query_position` は `_rows_to_metrics` を呼ぶだけの薄い GSC ラッパになる。テストは `_rows_to_metrics` に対して行う（GSC を叩かないため）。

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_page_one_tracker.py` の末尾に追加:

```python
def _full_row(page_url, pos, imp, clicks=0):
    """GSC query×page 応答の完全な行。"""
    return {"keys": ["ojogang メンバー", page_url],
            "position": pos, "impressions": imp, "clicks": clicks}


# 実測7行の完全版。clicks は全行 0(ojogang の実測どおり)。
FULL_ROWS = [
    _full_row("https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/", 5.18, 92),
    *(_full_row(f"https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-{i}",
                10.50, 2) for i in range(6)),
]


def test_rows_to_metrics_ojogang_fixture():
    """実測7行 → clicks 0 / imp 104 / pos 5.79(加重) / slug 逆引き成功。"""
    m = t._rows_to_metrics(FULL_ROWS)
    assert m["clicks"] == 0
    assert m["impressions"] == 104
    assert round(m["position"], 2) == 5.79
    assert m["slug"] == "swf3-osaka-ojo-gang-members"


def test_rows_to_metrics_sums_clicks_across_fragments():
    """clicks はアンカー分割を合算する。過小評価を防ぐ。"""
    rows = [
        _full_row("https://www.kpopjournal.tokyo/a/", 3.0, 10, clicks=4),
        _full_row("https://www.kpopjournal.tokyo/a/#kpop-h-0", 3.0, 10, clicks=3),
    ]
    assert t._rows_to_metrics(rows)["clicks"] == 7


def test_rows_to_metrics_empty_returns_none():
    """圏外(空行)は None。従来どおりその週をスキップする。既存挙動を変えない。"""
    assert t._rows_to_metrics([]) is None


def test_target_queries_carries_theme(tmp_path, monkeypatch):
    """enrich_queue と seo_opportunity_queue の双方から theme を meta に載せる。"""
    eq = tmp_path / "enrich_queue.json"
    eq.write_text(json.dumps([
        {"query": "golden 歌手", "slug": "kpop-demon-hunters-golden-analysis",
         "potential": 3797, "theme": "movie_anime"},
    ], ensure_ascii=False), encoding="utf-8")

    oq = tmp_path / "opportunity.json"
    oq.write_text(json.dumps({
        "lane_C_rewrite": [{"query": "ojogang メンバー", "potential": 521,
                            "theme": "dance_show"}],
        "lane_B_new": [{"query": "新規クエリ", "potential": 100, "theme": "artist"}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(t, "ENRICH_QUEUE", str(eq))
    monkeypatch.setattr(t, "QUEUE_IN", str(oq))

    qs = t._target_queries()
    assert qs["golden 歌手"]["theme"] == "movie_anime"
    assert qs["ojogang メンバー"]["theme"] == "dance_show"
    assert qs["新規クエリ"]["theme"] == "artist"


def test_target_queries_theme_defaults_to_unknown_when_absent(tmp_path, monkeypatch):
    """theme 欠落は実測ゼロだが、フォールバックは残す(落とさない)。"""
    oq = tmp_path / "opportunity.json"
    oq.write_text(json.dumps({
        "lane_C_rewrite": [{"query": "theme無し", "potential": 1}],
        "lane_B_new": [],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(t, "ENRICH_QUEUE", str(tmp_path / "nope.json"))
    monkeypatch.setattr(t, "QUEUE_IN", str(oq))

    assert t._target_queries()["theme無し"]["theme"] == "unknown"
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v -k "rows_to_metrics or target_queries"`
Expected: FAIL — `AttributeError: ... has no attribute '_rows_to_metrics'`

- [x] **Step 3: 実装する**

`lib/page_one_tracker.py` の `_clicks_delta` の直後に `_rows_to_metrics` を追加:

```python
def _rows_to_metrics(rows):
    """GSC query×page 行 → 集約メトリクス。空行なら None(圏外)。

    clicks/impressions はアンカー分割を合算、position は imp 加重平均、
    slug は集約 imp 最大のものを逆引きする。
    """
    if not rows:
        return None
    return {
        "position": _weighted_position(rows),
        "clicks": sum(int(r.get("clicks", 0)) for r in rows),
        "impressions": sum(int(r.get("impressions", 0)) for r in rows),
        "slug": _pick_slug(rows),
    }
```

既存の `_query_position`（40-63行）を丸ごと置換:

```python
def _query_position(svc, query, days=28):
    """直近 days のそのクエリの position/clicks/slug。無ければ None。

    query×page 次元で引く。GSC はフラグメント(#kpop-h-N)別に行を返すため、
    slug を逆引きでき、同時に position の imp 加重平均が取れる。
    """
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    body = {
        "startDate": start, "endDate": end,
        "dimensions": ["query", "page"],
        "dimensionFilterGroups": [{
            "filters": [{"dimension": "query", "operator": "equals", "expression": query}]
        }],
        "rowLimit": 25,
    }
    try:
        res = svc.searchanalytics().query(siteUrl=SITE, body=body).execute()
    except Exception as e:
        print(f"  GSC error query={query!r}: {e}", file=sys.stderr)
        return None
    return _rows_to_metrics(res.get("rows", []))
```

既存の `_target_queries`（66-83行）を丸ごと置換:

```python
def _target_queries():
    """追跡対象クエリ = enrich_queue + Lane C/B 上位(着手対象)。

    theme を上流 queue から持ち越す。従来は捨てていたため、下流の
    feedback_loop が slug 経由で引き直そうとして全件 unknown になっていた。
    """
    qs = {}
    if os.path.exists(ENRICH_QUEUE):
        try:
            for r in json.load(open(ENRICH_QUEUE, encoding="utf-8")):
                if r.get("query"):
                    qs[r["query"]] = {"slug": r.get("slug", ""),
                                      "potential": r.get("potential", 0),
                                      "theme": r.get("theme", "unknown")}
        except Exception:
            pass
    if os.path.exists(QUEUE_IN):
        try:
            q = json.load(open(QUEUE_IN, encoding="utf-8"))
            for r in (q.get("lane_C_rewrite", [])[:30] + q.get("lane_B_new", [])[:20]):
                qs.setdefault(r["query"], {"slug": "",
                                           "potential": r.get("potential", 0),
                                           "theme": r.get("theme", "unknown")})
        except Exception:
            pass
    return qs
```

`do_baseline` の `base["queries"][query]` 辞書（93-97行）に theme と slug 逆引きを追加:

```python
        if pos:
            base["queries"][query] = {
                "baseline_pos": round(pos["position"], 2),
                "baseline_clicks": pos["clicks"],
                # slug は GSC 逆引きを優先し、取れなければ queue 由来
                "slug": pos.get("slug") or meta["slug"],
                "potential": meta["potential"],
                "theme": meta.get("theme", "unknown"),
            }
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: PASS — 25 passed

- [x] **Step 5: コミット**

```bash
git add tests/unit/test_page_one_tracker.py lib/page_one_tracker.py
git commit -m "feat(tracker): query×page 次元で slug 逆引き + theme 持ち越し"
```

---

## Task 6: `do_weekly()` を新スキーマで書き出す + `--dry-run` を追加

progress は追記専用の計測ログ。壊れた行を書くと取り返しがつかないので、書き込み前に必ず目視する手段を用意する。

**Files:**
- Modify: `lib/page_one_tracker.py:103-142`（`do_weekly`）
- Modify: `lib/page_one_tracker.py:145-149`（`main` — `--dry-run` 追加）
- Modify: `tests/unit/test_page_one_tracker.py`

**Interfaces:**
- Consumes: `_rows_to_metrics`, `_clicks_delta`, `_last_progress_row`（Task 4-5）
- Produces: `_build_progress_row(week, query, base_meta, cur, prev_row) -> dict` — progress の1行

新規行のスキーマ:

```json
{"week": "2026-07-17", "query": "ojogang メンバー",
 "slug": "swf3-osaka-ojo-gang-members", "theme": "dance_show",
 "baseline_pos": 8.68, "current_pos": 5.80,
 "crossed_10": false, "crossed_3": false,
 "clicks_abs": 0, "clicks_delta": 0, "delta_basis": "prev_week",
 "potential": 521}
```

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_page_one_tracker.py` の末尾に追加:

```python
BASE_META = {"baseline_pos": 8.68, "baseline_clicks": 14, "slug": "",
             "potential": 521, "theme": "dance_show"}
CUR = {"position": 5.7981, "clicks": 0, "impressions": 104,
       "slug": "swf3-osaka-ojo-gang-members"}


def test_build_progress_row_has_new_schema():
    """clicks_abs / delta_basis / theme を必ず持つ。"""
    r = t._build_progress_row("2026-07-17", "ojogang メンバー", BASE_META, CUR, None)
    assert r["clicks_abs"] == 0
    assert r["delta_basis"] == "prev_week"
    assert r["theme"] == "dance_show"


def test_build_progress_row_prefers_reverse_looked_up_slug():
    """baseline の slug が空でも GSC 逆引きの slug を書く。欠陥1の根治。"""
    r = t._build_progress_row("2026-07-17", "ojogang メンバー", BASE_META, CUR, None)
    assert r["slug"] == "swf3-osaka-ojo-gang-members"


def test_build_progress_row_escapes_minus_14_fixation():
    """回帰: 順位が 8.68 → 5.80 と改善しているのに -14 で固着していた。"""
    r = t._build_progress_row("2026-07-17", "ojogang メンバー", BASE_META, CUR, None)
    assert r["current_pos"] == 5.8
    assert r["clicks_delta"] == 0   # -14 ではない


def test_build_progress_row_uses_prev_week_when_available():
    """前週行があれば前週比。"""
    prev = {"week": "2026-07-10", "clicks_abs": 3}
    cur = dict(CUR, clicks=5)
    r = t._build_progress_row("2026-07-17", "ojogang メンバー", BASE_META, cur, prev)
    assert r["clicks_delta"] == 2
    assert r["clicks_abs"] == 5


def test_build_progress_row_preserves_crossing_flags():
    """crossed_10 / crossed_3 の既存判定を壊さない。"""
    base = dict(BASE_META, baseline_pos=12.0)
    r = t._build_progress_row("2026-07-17", "q", base, CUR, None)
    assert r["crossed_10"] is True    # 12.0 >= 10 かつ 5.8 < 10
    assert r["crossed_3"] is False    # 5.8 は 3 未満でない


def test_build_progress_row_never_mutates_baseline_pos():
    """baseline_pos は絶対に書き換えない。"""
    r = t._build_progress_row("2026-07-17", "q", BASE_META, CUR, None)
    assert r["baseline_pos"] == 8.68
    assert BASE_META["baseline_pos"] == 8.68
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v -k build_progress_row`
Expected: FAIL — `AttributeError: ... has no attribute '_build_progress_row'`

- [x] **Step 3: 実装する**

`lib/page_one_tracker.py` の `_rows_to_metrics` の直後に追加:

```python
def _build_progress_row(week, query, base_meta, cur, prev_row):
    """progress.jsonl の1行を組み立てる(純関数・IO しない)。"""
    bp = base_meta["baseline_pos"]
    cp = round(cur["position"], 2)
    return {
        "week": week, "query": query,
        # GSC 逆引きを優先。baseline の slug は空のことが多い(欠陥1)
        "slug": cur.get("slug") or base_meta.get("slug", ""),
        "theme": base_meta.get("theme", "unknown"),
        "baseline_pos": bp, "current_pos": cp,
        "crossed_10": (bp >= 10) and (cp < 10),
        "crossed_3": (bp >= 3) and (cp < 3),
        "clicks_abs": int(cur["clicks"]),
        "clicks_delta": _clicks_delta(cur["clicks"], prev_row),
        "delta_basis": "prev_week",
        "potential": base_meta.get("potential", 0),
    }
```

`do_weekly`（103-142行）を丸ごと置換:

```python
def do_weekly(dry_run=False):
    if not os.path.exists(BASELINE):
        print("[tracker] baseline が無い。先に --baseline を実行してください。", file=sys.stderr)
        return 1
    base = json.load(open(BASELINE, encoding="utf-8"))
    svc = _service()
    week = date.today().isoformat()
    rows = []
    for query, b in base["queries"].items():
        cur = _query_position(svc, query)
        if not cur:
            continue
        prev = _last_progress_row(query)
        rows.append(_build_progress_row(week, query, b, cur, prev))

    if dry_run:
        print(f"[tracker] DRY-RUN {week} — progress へは書き込まない")
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        empty_slug = sum(1 for r in rows if not r["slug"])
        themes = sorted({r["theme"] for r in rows})
        print(f"  slug 空: {empty_slug}/{len(rows)}")
        print(f"  theme 種別: {themes}")
    else:
        with open(PROGRESS, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    crossed_10 = sum(1 for r in rows if r["crossed_10"])
    crossed_3 = sum(1 for r in rows if r["crossed_3"])
    in_page1 = sum(1 for r in rows if r["current_pos"] < 10)
    in_top3 = sum(1 for r in rows if r["current_pos"] < 3)
    total_clicks_delta = sum(r["clicks_delta"] for r in rows)
    print(f"[tracker] 週次計測 {week}")
    print(f"  追跡クエリ: {len(rows)}")
    print(f"  今週 新規 pos<10 進入: {crossed_10} / 新規 pos<3 進入: {crossed_3}")
    print(f"  現在 pos<10: {in_page1} / pos<3: {in_top3}")
    print(f"  clicks増分(前週比): {total_clicks_delta:+d}")
    return 0
```

`main()`（145-149行）を置換:

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="Week0 ベースライン固定")
    ap.add_argument("--dry-run", action="store_true",
                    help="progress へ書かず出力のみ(slug 逆引き率・theme を検証)")
    args = ap.parse_args()
    sys.exit(do_baseline() if args.baseline else do_weekly(dry_run=args.dry_run))
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_page_one_tracker.py -v`
Expected: PASS — 31 passed

- [x] **Step 5: コミット**

```bash
git add tests/unit/test_page_one_tracker.py lib/page_one_tracker.py
git commit -m "feat(tracker): progress を新スキーマ(clicks_abs/delta_basis/theme)で書く + --dry-run"
```

---

## Task 7: baseline に theme を後付けする移行スクリプト

既存 `page_one_baseline.json` には theme が無い。Task 5 の `do_baseline` は新規作成時にしか theme を書かないため、既存 baseline を再作成せずに theme だけ足す。`baseline_pos` を触らないことが絶対条件。

**Files:**
- Create: `tools/migrate_baseline_theme.py`
- Create: `tests/unit/test_migrate_baseline_theme.py`

**Interfaces:**
- Consumes: `lib.page_one_tracker._target_queries()`（Task 5）
- Produces: `migrate(baseline: dict, targets: dict) -> tuple[dict, int]` — `(新 baseline, 更新件数)`

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_migrate_baseline_theme.py` を新規作成:

```python
#!/usr/bin/env python3
"""baseline への theme 後付け移行の単体テスト (2026-07-10)。

絶対条件: baseline_pos / baseline_clicks を書き換えないこと。
実行: python3 -m pytest tests/unit/test_migrate_baseline_theme.py -v
"""
import tools.migrate_baseline_theme as m


BASELINE = {
    "created": "2026-05-26",
    "queries": {
        "ojogang メンバー": {"baseline_pos": 8.68, "baseline_clicks": 14,
                             "slug": "", "potential": 521},
        "golden 歌手": {"baseline_pos": 3.2, "baseline_clicks": 40,
                        "slug": "kpop-demon-hunters-golden-analysis", "potential": 3797},
    },
}
TARGETS = {
    "ojogang メンバー": {"slug": "", "potential": 521, "theme": "dance_show"},
    "golden 歌手": {"slug": "kpop-demon-hunters-golden-analysis",
                    "potential": 3797, "theme": "movie_anime"},
}


def test_migrate_adds_theme():
    out, n = m.migrate(BASELINE, TARGETS)
    assert out["queries"]["ojogang メンバー"]["theme"] == "dance_show"
    assert out["queries"]["golden 歌手"]["theme"] == "movie_anime"
    assert n == 2


def test_migrate_never_touches_baseline_pos_or_clicks():
    """絶対条件。baseline_pos を1つでも動かしたら計測の連続性が壊れる。"""
    out, _ = m.migrate(BASELINE, TARGETS)
    assert out["queries"]["ojogang メンバー"]["baseline_pos"] == 8.68
    assert out["queries"]["ojogang メンバー"]["baseline_clicks"] == 14
    assert out["queries"]["golden 歌手"]["baseline_pos"] == 3.2


def test_migrate_does_not_mutate_input():
    """入力を破壊しない。呼び出し側が diff を取れるようにするため。"""
    m.migrate(BASELINE, TARGETS)
    assert "theme" not in BASELINE["queries"]["ojogang メンバー"]


def test_migrate_defaults_to_unknown_when_query_not_in_targets():
    """queue から消えたクエリは unknown。落とさない。"""
    out, _ = m.migrate(BASELINE, {})
    assert out["queries"]["ojogang メンバー"]["theme"] == "unknown"


def test_migrate_is_idempotent():
    """2回流しても結果が変わらない。"""
    once, _ = m.migrate(BASELINE, TARGETS)
    twice, n = m.migrate(once, TARGETS)
    assert once == twice
    assert n == 2
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_migrate_baseline_theme.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.migrate_baseline_theme'`

`tools/__init__.py` が無ければ `ImportError`。存在確認は Step 3 で行う。

- [x] **Step 3: 実装する**

まず `tools/` が package か確認する:

```bash
ls tools/__init__.py 2>/dev/null || touch tools/__init__.py
```

`tools/migrate_baseline_theme.py` を新規作成:

```python
#!/usr/bin/env python3
"""page_one_baseline.json に theme を後付けする(1回限りの移行)。

baseline_pos / baseline_clicks は絶対に書き換えない。theme のみ追加する。
実行前に必ずバックアップを取り、--dry-run で diff を目視すること。

使い方:
  venv_kpi/bin/python3 tools/migrate_baseline_theme.py --dry-run
  venv_kpi/bin/python3 tools/migrate_baseline_theme.py
"""
import os
import sys
import json
import copy
import shutil
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.page_one_tracker import BASELINE, _target_queries  # noqa: E402


def migrate(baseline, targets):
    """theme のみ後付けした新 baseline と更新件数を返す。入力は破壊しない。"""
    out = copy.deepcopy(baseline)
    n = 0
    for query, meta in out.get("queries", {}).items():
        meta["theme"] = targets.get(query, {}).get("theme", "unknown")
        n += 1
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="書き込まず差分のみ表示")
    args = ap.parse_args()

    if not os.path.exists(BASELINE):
        print(f"[migrate] baseline が無い: {BASELINE}", file=sys.stderr)
        return 1

    base = json.load(open(BASELINE, encoding="utf-8"))
    new, n = migrate(base, _target_queries())

    themes = {}
    for meta in new["queries"].values():
        themes[meta["theme"]] = themes.get(meta["theme"], 0) + 1
    print(f"[migrate] 対象 {n} クエリ / theme 分布: {themes}")

    if args.dry_run:
        print("[migrate] DRY-RUN — 書き込まない")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{BASELINE}.bak_{stamp}"
    shutil.copy2(BASELINE, backup)
    print(f"[migrate] バックアップ: {backup}")

    json.dump(new, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[migrate] theme を後付け: {n} クエリ → {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_migrate_baseline_theme.py -v`
Expected: PASS — 5 passed

- [x] **Step 5: dry-run で実データの theme 分布を確認**

Run: `venv_kpi/bin/python3 tools/migrate_baseline_theme.py --dry-run`
Expected: `theme 分布` が `unknown` 単一でなく、`movie_anime` / `dance_show` / `artist` 等に分かれること。`DRY-RUN — 書き込まない` で終わること。

**この出力が `unknown` 単一なら先へ進まない。** `_target_queries()` が theme を拾えていない。

- [x] **Step 6: 本実行して baseline を更新**

Run: `venv_kpi/bin/python3 tools/migrate_baseline_theme.py`
Expected: `バックアップ: data/page_one_baseline.json.bak_...` と `theme を後付け: N クエリ`

`baseline_pos` と `baseline_clicks` が1つも動いていないことを検証する。**本計画で最も重要な安全弁。**

```bash
python3 - <<'PY'
import json, glob
bak = sorted(glob.glob("data/page_one_baseline.json.bak_*"))[-1]
old = json.load(open(bak, encoding="utf-8"))["queries"]
new = json.load(open("data/page_one_baseline.json", encoding="utf-8"))["queries"]
print(f"バックアップ: {bak}")

assert set(old) == set(new), f"クエリ集合が変わった: {set(old) ^ set(new)}"
bad = [q for q in old
       if old[q]["baseline_pos"] != new[q]["baseline_pos"]
       or old[q].get("baseline_clicks") != new[q].get("baseline_clicks")]
assert not bad, f"baseline が書き換わった!! 即 revert: {bad}"

added = [q for q in new if "theme" not in old[q] and "theme" in new[q]]
print(f"OK: baseline_pos/clicks 不変 ({len(old)} クエリ)")
print(f"theme 追加: {len(added)} クエリ")
PY
```

Expected: `OK: baseline_pos/clicks 不変` と `theme 追加: N クエリ`

`AssertionError` が出たら即 revert する:

```bash
cp "$(ls -1 data/page_one_baseline.json.bak_* | tail -1)" data/page_one_baseline.json
```

- [x] **Step 7: コミット**

```bash
git add tools/migrate_baseline_theme.py tests/unit/test_migrate_baseline_theme.py tools/__init__.py data/page_one_baseline.json
git commit -m "feat(tracker): baseline に theme を後付けする移行スクリプト"
```

---

## Task 8: tracker の dry-run で slug 逆引き率を実測する（本番 GSC・書き込みなし）

設計の Step 3。progress へ書く前に、slug 空率 75% → ほぼ0% を**実測で**確認する。推測で進めない。

**Files:**
- 変更なし（検証のみ）

**Interfaces:**
- Consumes: `do_weekly(dry_run=True)`（Task 6）
- Produces: なし

- [x] **Step 1: 変更前の slug 空率を記録する**

```bash
python3 -c "
import json
rows=[json.loads(l) for l in open('data/page_one_progress.jsonl')]
w=max(r['week'] for r in rows)
cur=[r for r in rows if r['week']==w]
print(f'変更前 最新週 {w}: slug空 {sum(1 for r in cur if not r.get(\"slug\"))}/{len(cur)}')
"
```

Expected: `変更前 最新週 2026-07-10: slug空 12/16`

- [x] **Step 2: dry-run を実行する（GSC を叩くが progress へは書かない）**

Run: `venv_kpi/bin/python3 lib/page_one_tracker.py --dry-run`

Expected: 各行の JSON が出力され、末尾に以下が出ること。

```
  slug 空: 0/16          ← あるいは 1 以下
  theme 種別: ['artist', 'dance_show', 'movie_anime', ...]
```

- [x] **Step 3: 合否を判定する**

| 観測 | 判定 |
|---|---|
| `slug 空` が 1 以下 | 合格。Step 4 へ |
| `slug 空` が 2 以上 | **停止。** `_pick_slug` か `_slug_of` に欠陥。Task 1/3 に戻る |
| `theme 種別` が `['unknown']` のみ | **停止。** Task 7 の移行が効いていない |
| GSC エラーが出る | **停止。** `service_account.json` の権限を確認 |

- [x] **Step 4: progress へ書き込まれていないことを確認する**

```bash
python3 -c "
import json
rows=[json.loads(l) for l in open('data/page_one_progress.jsonl')]
print('行数:', len(rows), '(122 のままなら dry-run は書いていない)')
print('週:', sorted({r['week'] for r in rows})[-1])
"
```

Expected: `行数: 122`

- [x] **Step 5: 実測結果を設計文書に追記してコミット**

`docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md` の「成功基準」の直前に追記:

```markdown
## 実測結果（Step 3 dry-run / 実行日: <実行日を記入>）

- slug 空率: 12/16 (75%) → <実測値>
- theme 種別: `['unknown']` → <実測値>
- progress 行数: 122 のまま（書き込みなし）
```

```bash
git add docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md
git commit -m "docs(tracker): dry-run の実測結果を設計文書に記録"
```

---

## Task 9: `seo_feedback_loop` の slug 迂回を削除し theme を直読みする

設計の変更4。`_slug_theme_map()` は slug 経由で theme を引き直すが、slug が空なので全件ミスして `unknown` になっていた。

**Files:**
- Modify: `lib/seo_feedback_loop.py`（`_slug_theme_map` を削除、`aggregate()` を修正）
- Create: `tests/unit/test_seo_feedback_loop_theme.py`

**Interfaces:**
- Consumes: progress 行の `theme` フィールド（Task 6）
- Produces: `aggregate() -> tuple[dict, list]` — `(summary, rows)`。`summary` は theme をキーとし、値は `{"n": int, "crossed_10_rate": float, "clicks_delta_avg": float}`

**現行実装（確認済み・読み直し不要）**

```python
def aggregate():
    rows = _recent_progress()
    theme_map = _slug_theme_map()          # ← これを消す
    groups = {}
    for r in rows:
        theme = theme_map.get(r.get("slug", ""), "unknown")   # ← ここが全件ミスする
        groups.setdefault(theme, []).append(r)
    summary = {}
    for theme, rs in groups.items():
        n = len(rs)
        crossed10 = sum(1 for r in rs if r.get("crossed_10"))
        clicks_delta_avg = sum(r.get("clicks_delta", 0) for r in rs) / n if n else 0
        summary[theme] = {
            "n": n,
            "crossed_10_rate": round(crossed10 / n, 3) if n else 0,
            "clicks_delta_avg": round(clicks_delta_avg, 2),
        }
    return summary, rows      # ← タプルを返す。テストは第1要素を取る
```

`_slug_theme_map()` は `enrich_queue.json`（現行6件）から `slug -> theme` を作る。tracker が slug を空固定していたため突合が全件ミスし、`unknown` に潰れていた。

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_seo_feedback_loop_theme.py` を新規作成:

```python
#!/usr/bin/env python3
"""feedback_loop が progress の theme を直読みすることの単体テスト (2026-07-10)。

背景: _slug_theme_map() が slug 経由で theme を引き直していたが、
      tracker が slug を空固定していたため直近77件が 77/77 で unknown だった。
実行: python3 -m pytest tests/unit/test_seo_feedback_loop_theme.py -v
"""
import lib.seo_feedback_loop as fb


ROWS = [
    {"week": "2026-07-17", "query": "golden 歌手", "slug": "kpop-demon-hunters-golden-analysis",
     "theme": "movie_anime", "crossed_10": True, "clicks_delta": 3,
     "clicks_abs": 5, "delta_basis": "prev_week", "current_pos": 4.0, "baseline_pos": 11.0},
    {"week": "2026-07-17", "query": "ojogang メンバー", "slug": "swf3-osaka-ojo-gang-members",
     "theme": "dance_show", "crossed_10": False, "clicks_delta": 0,
     "clicks_abs": 0, "delta_basis": "prev_week", "current_pos": 5.8, "baseline_pos": 8.68},
]


def test_slug_theme_map_is_removed():
    """slug 経由の引き直しは構造的に不要。関数ごと消えていること。"""
    assert not hasattr(fb, "_slug_theme_map")


def test_aggregate_reads_theme_directly(monkeypatch):
    """progress 行の theme を直読みし、unknown 単一に潰れないこと。

    aggregate() は (summary, rows) のタプルを返す。summary が theme 別の dict。
    """
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: ROWS)
    summary, rows = fb.aggregate()
    assert set(summary.keys()) == {"movie_anime", "dance_show"}
    assert "unknown" not in summary
    assert len(rows) == 2


def test_aggregate_unknown_disappears(monkeypatch):
    """回帰: 直近77件が 77/77 unknown だった。"""
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: ROWS)
    summary, _ = fb.aggregate()
    assert list(summary.keys()) != ["unknown"]


def test_aggregate_keeps_summary_shape(monkeypatch):
    """summary の各値は n / crossed_10_rate / clicks_delta_avg。下流が依存する。"""
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: ROWS)
    summary, _ = fb.aggregate()
    assert summary["movie_anime"] == {"n": 1, "crossed_10_rate": 1.0, "clicks_delta_avg": 3.0}
    assert summary["dance_show"] == {"n": 1, "crossed_10_rate": 0.0, "clicks_delta_avg": 0.0}


def test_aggregate_falls_back_to_unknown_for_legacy_rows(monkeypatch):
    """theme を持たない過去行は unknown。落とさない。"""
    legacy = [{"week": "2026-07-03", "query": "旧", "slug": "",
               "crossed_10": False, "clicks_delta": -14, "current_pos": 5.11,
               "baseline_pos": 8.68}]
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: legacy)
    summary, _ = fb.aggregate()
    assert "unknown" in summary
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_seo_feedback_loop_theme.py -v`
Expected: FAIL — `test_slug_theme_map_is_removed` が `hasattr` で落ちる

- [x] **Step 3: `_slug_theme_map()` を削除し theme を直読みする**

`lib/seo_feedback_loop.py` の `_slug_theme_map` 関数定義を丸ごと削除する（`def _slug_theme_map():` から次の `def _route_map():` の直前まで）。

`aggregate()` の冒頭2行を置換する。置換前:

```python
    rows = _recent_progress()
    theme_map = _slug_theme_map()
    groups = {}  # key(theme or "unknown") -> list of rows
    for r in rows:
        theme = theme_map.get(r.get("slug", ""), "unknown")
        groups.setdefault(theme, []).append(r)
```

置換後:

```python
    rows = _recent_progress()
    groups = {}  # key(theme or "unknown") -> list of rows
    for r in rows:
        # tracker が progress に theme を直接書く。slug 経由の引き直しは不要。
        theme = r.get("theme", "unknown")
        groups.setdefault(theme, []).append(r)
```

`ENRICH_QUEUE` 定数が `_slug_theme_map` 以外から参照されていなければ削除する。確認:

```bash
grep -n "ENRICH_QUEUE" lib/seo_feedback_loop.py
```

他に参照が残っていれば定数は残す。

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_seo_feedback_loop_theme.py -v`
Expected: PASS — 5 passed

- [x] **Step 5: 全テストが壊れていないことを確認**

Run: `python3 -m pytest tests/ -q`
Expected: 既存テストが1つも新たに失敗していないこと（`failed` が 0）

- [x] **Step 6: コミット**

```bash
git add lib/seo_feedback_loop.py tests/unit/test_seo_feedback_loop_theme.py
git commit -m "fix(feedback): slug 経由の theme 引き直しを削除し progress の theme を直読み"
```

---

## Task 10: `seo_auto_rollback` に `delta_basis` ガードと dry-run 固定を入れる

設計の変更5。閾値は決め打ちしない。**移行第1週は全件 `clicks_delta = 0` になり構造的に発火しない**（想定内）。

**Files:**
- Modify: `lib/seo_auto_rollback.py:58-63`（`_latest_clicks_delta`）
- Modify: `lib/seo_auto_rollback.py:117-152`（`run` / `main` — dry-run 固定）
- Create: `tests/unit/test_seo_auto_rollback_guard.py`

**Interfaces:**
- Consumes: progress 行の `delta_basis` フィールド（Task 6）
- Produces: `_latest_clicks_delta(progress_rows, slug) -> int | None` — `delta_basis == "prev_week"` の行のみ評価

- [x] **Step 1: 失敗するテストを書く**

`tests/unit/test_seo_auto_rollback_guard.py` を新規作成:

```python
#!/usr/bin/env python3
"""rollback の delta_basis ガードの単体テスト (2026-07-10)。

背景: clicks_delta の定義が baseline 比 → 前週比 に変わる。
      定義の混ざった行で判断すると、閾値 -3 の重みが変わり過剰に差し戻す。
実行: python3 -m pytest tests/unit/test_seo_auto_rollback_guard.py -v
"""
import lib.seo_auto_rollback as rb


LEGACY = {"week": "2026-07-03", "slug": "foo", "clicks_delta": -14}          # 定義: baseline 比
NEW = {"week": "2026-07-17", "slug": "foo", "clicks_delta": -5,
       "delta_basis": "prev_week", "clicks_abs": 2}


def test_ignores_legacy_rows_without_delta_basis():
    """delta_basis を持たない過去行は評価しない。-14 は baseline 比で意味が違う。"""
    assert rb._latest_clicks_delta([LEGACY], "foo") is None


def test_reads_prev_week_rows():
    """delta_basis == 'prev_week' の行は読む。"""
    assert rb._latest_clicks_delta([NEW], "foo") == -5


def test_picks_latest_prev_week_row():
    """複数あれば week 最新を採る。"""
    older = dict(NEW, week="2026-07-17", clicks_delta=-1)
    newer = dict(NEW, week="2026-07-24", clicks_delta=-9)
    assert rb._latest_clicks_delta([newer, older], "foo") == -9


def test_legacy_and_new_mixed_uses_only_new():
    """混在時は新定義の行のみ。過去行に引きずられない。"""
    assert rb._latest_clicks_delta([LEGACY, NEW], "foo") == -5


def test_returns_none_for_unknown_slug():
    assert rb._latest_clicks_delta([NEW], "他の slug") is None


def test_first_week_all_zero_never_triggers_rollback():
    """移行第1週は全件 clicks_delta=0(prev が無いため)。
    閾値 -3 を下回らないので rollback は発火しない。安全側の想定内挙動。"""
    first_week = [dict(NEW, clicks_delta=0)]
    delta = rb._latest_clicks_delta(first_week, "foo")
    assert delta == 0
    assert delta > rb.ROLLBACK_CLICKS_DELTA_THRESHOLD   # 0 > -3 → スキップされる
```

- [x] **Step 2: テストを実行し、失敗することを確認**

Run: `python3 -m pytest tests/unit/test_seo_auto_rollback_guard.py -v`
Expected: FAIL — `test_ignores_legacy_rows_without_delta_basis` が `-14` を返して落ちる

- [x] **Step 3: `_latest_clicks_delta` にガードを入れる**

`lib/seo_auto_rollback.py:58-63` を置換:

```python
def _latest_clicks_delta(progress_rows, slug):
    """同一 slug の最新 clicks_delta。前週比定義(delta_basis='prev_week')の行のみ。

    過去行の clicks_delta は baseline(28日累積) 比で、定義が異なる。
    混ぜて判断すると閾値の意味が変わり過剰に差し戻す。
    移行第1週は全件 delta=0 になるため rollback は構造的に発火しない(想定内)。
    """
    matches = [r for r in progress_rows
               if r.get("slug") == slug and r.get("delta_basis") == "prev_week"]
    if not matches:
        return None
    matches.sort(key=lambda r: r.get("week", ""))
    return matches[-1].get("clicks_delta")
```

- [x] **Step 4: テストを実行し、通ることを確認**

Run: `python3 -m pytest tests/unit/test_seo_auto_rollback_guard.py -v`
Expected: PASS — 6 passed

- [x] **Step 5: dry-run を固定する**

`lib/seo_auto_rollback.py` の `main()`（150-152行付近）を置換し、`--dry-run` を強制する。閾値決定までは本実行させない。

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--i-have-set-the-threshold-from-observed-distribution",
                    action="store_true", dest="threshold_set",
                    help="第2週以降の delta 分布を観測し閾値を決めた後にのみ指定")
    args = ap.parse_args()
    if not args.threshold_set:
        # 前週比への移行直後。閾値 -3 は baseline 比の重みで決めた値であり、
        # 前週比では過剰に差し戻す。分布を観測するまで dry-run 固定。
        print("[rollback] 移行期のため --dry-run 固定 "
              "(第2週以降の分布を見て閾値を決めるまで本実行しない)", file=sys.stderr)
        sys.exit(run(dry_run=True))
    sys.exit(run(dry_run=args.dry_run))
```

`sys.exit()` を使う点に注意。ファイル末尾は以下になっており、`main()` を裸で呼んでいる。

```python
if __name__ == "__main__":
    main()
```

`return` に変えると終了コードが常に 0 になり、cron が失敗を検知できなくなる。`main()` 内で `sys.exit()` すること（元の実装もそうなっている）。

- [x] **Step 6: dry-run が発火ゼロで終わることを実測**

Run: `venv_kpi/bin/python3 lib/seo_auto_rollback.py`
Expected: `[rollback] 移行期のため --dry-run 固定` が出て、差し戻し件数 0 で終わること。WP への書き込みが発生しないこと。

- [x] **Step 7: 全テストが壊れていないことを確認してコミット**

Run: `python3 -m pytest tests/ -q`
Expected: `failed` が 0

```bash
git add lib/seo_auto_rollback.py tests/unit/test_seo_auto_rollback_guard.py
git commit -m "fix(rollback): delta_basis ガードを追加し移行期は dry-run 固定"
```

---

## Task 11: pending 提案を却下済みにマークする

`theme='unknown'` は全件だったため、「unknown を enrich 対象から一時除外」は実質「全記事を除外せよ」を意味する。計測バグの産物なので却下する。

**Files:**
- Modify: `logs/seo_config_proposals.jsonl`（append で却下レコードを追加）
- Create: `tools/reject_stale_proposals.py`

**Interfaces:**
- Consumes: なし
- Produces: なし（1回限りの運用スクリプト）

- [x] **Step 1: 却下対象を特定する**

```bash
python3 -c "
import json
for i,l in enumerate(open('logs/seo_config_proposals.jsonl')):
    d=json.loads(l)
    if d.get('status')=='pending_owner_review':
        print(i, d.get('ts'), d.get('theme'), str(d.get('proposal'))[:80])
"
```

Expected: `theme: unknown` の pending 提案が1件以上表示される。0件なら Task 11 は不要（スキップして Task 12 へ）。

- [x] **Step 2: 却下スクリプトを書く**

`tools/reject_stale_proposals.py` を新規作成:

```python
#!/usr/bin/env python3
"""計測バグ由来の pending 提案を却下済みにマークする(1回限り)。

背景: tracker が theme を捨てていたため直近77件が 77/77 unknown になり、
      feedback_loop が「theme='unknown' は効果薄。enrich 対象から除外」を提案した。
      unknown は全件なので、これは実質「全記事を除外せよ」を意味する。却下する。

jsonl は追記専用。既存行は書き換えず、却下レコードを追記する。

使い方:
  venv_kpi/bin/python3 tools/reject_stale_proposals.py --dry-run
  venv_kpi/bin/python3 tools/reject_stale_proposals.py
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSALS = os.path.join(BASE_DIR, "logs", "seo_config_proposals.jsonl")

REASON = ("計測バグ由来。tracker が theme を破棄していたため全件 unknown だった。"
          "2026-07-10 の tracker 修正で theme は実値に分かれる。"
          "設計: docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md")


def find_stale(path):
    """theme='unknown' の pending 提案を返す。"""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("status") == "pending_owner_review" and d.get("theme") == "unknown":
                out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stale = find_stale(PROPOSALS)
    print(f"[reject] 却下対象: {len(stale)} 件")
    for d in stale:
        print(f"  {d.get('ts')} theme={d.get('theme')}")

    if not stale:
        return 0
    if args.dry_run:
        print("[reject] DRY-RUN — 追記しない")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    with open(PROPOSALS, "a", encoding="utf-8") as f:
        for d in stale:
            f.write(json.dumps({
                "ts": now,
                "status": "rejected",
                "rejects_ts": d.get("ts"),
                "theme": d.get("theme"),
                "reason": REASON,
            }, ensure_ascii=False) + "\n")
    print(f"[reject] {len(stale)} 件を却下済みとして追記")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 3: dry-run で対象を確認**

Run: `venv_kpi/bin/python3 tools/reject_stale_proposals.py --dry-run`
Expected: 却下対象の件数と ts が表示され、`DRY-RUN — 追記しない` で終わる

- [x] **Step 4: 本実行**

Run: `venv_kpi/bin/python3 tools/reject_stale_proposals.py`
Expected: `N 件を却下済みとして追記`

- [x] **Step 5: 既存行が壊れていないことを確認**

```bash
python3 -c "
import json
rows=[json.loads(l) for l in open('logs/seo_config_proposals.jsonl') if l.strip()]
print('全行 JSON パース OK:', len(rows))
print('pending 残:', sum(1 for r in rows if r.get('status')=='pending_owner_review'))
print('rejected:', sum(1 for r in rows if r.get('status')=='rejected'))
"
```

Expected: 全行パース成功。`rejected` が Step 4 の件数と一致。

（`pending 残` は減らない。既存行は書き換えず追記する設計のため。下流が pending を読む場合は `rejects_ts` で突合する。）

- [x] **Step 6: コミット**

```bash
git add tools/reject_stale_proposals.py logs/seo_config_proposals.jsonl
git commit -m "chore(seo): 計測バグ由来の unknown 提案を却下済みにマーク"
```

---

## Task 12: 統合確認と本番週次実行

全体が繋がることを確認し、初めて progress へ書き込む。

**Files:**
- 変更なし（検証のみ）

- [x] **Step 1: 全テストを走らせる**

Run: `python3 -m pytest tests/ -q`

Expected: `failed` が 0。新規テストは計 47 件が追加されている。

| ファイル | 件数 |
|---|---|
| `tests/unit/test_page_one_tracker.py` (Task 1-6) | 31 |
| `tests/unit/test_migrate_baseline_theme.py` (Task 7) | 5 |
| `tests/unit/test_seo_feedback_loop_theme.py` (Task 9) | 5 |
| `tests/unit/test_seo_auto_rollback_guard.py` (Task 10) | 6 |
| **計** | **47** |

新規ファイルだけを走らせるなら:

```bash
python3 -m pytest tests/unit/test_page_one_tracker.py \
                 tests/unit/test_migrate_baseline_theme.py \
                 tests/unit/test_seo_feedback_loop_theme.py \
                 tests/unit/test_seo_auto_rollback_guard.py -q
```

- [x] **Step 2: tracker を dry-run して最終確認**

Run: `venv_kpi/bin/python3 lib/page_one_tracker.py --dry-run`

Expected:
- `slug 空` が 1 以下
- `theme 種別` が複数
- 各行に `clicks_abs` / `delta_basis: "prev_week"` がある
- `clicks増分(前週比)` が表示される

**ここで異常があれば progress へ書かない。** 該当タスクへ戻る。

- [~] **Step 3: progress へ本書き込みする** — **スキップ（来週の cron に委譲 / owner 判断）**

実装完了時点で当日分の週次 cron（金 6:15）が既に旧スキーマ16行を書き終えていた。
手動で新スキーマ17行を追記すると同一週に33行が並び、feedback_loop の theme 別集計で
当週だけ `unknown` が16件水増しされる（rollback・前週比には旧行が入らないため無害）。
計測の連続性を優先して見送った。

cron は引数なしで `lib/page_one_tracker.py` を呼ぶため、来週金曜（2026-07-17）の
実行が新スキーマで書き込む。cron 変更は不要。progress は 122 行のまま。

Run: `venv_kpi/bin/python3 lib/page_one_tracker.py`
Expected: `[tracker] 週次計測 <today>` と追跡クエリ数

- [~] **Step 4: 書き込まれた行を検証する** — **Step 3 とともに来週へ繰り延べ**

（同等の検証は Task 8 / Task 12 Step 2 の dry-run 出力で実施済み。
slug 空 0/17・theme 4種・`delta_basis: prev_week`・`clicks_abs` 保持を確認した）

```bash
python3 -c "
import json
rows=[json.loads(l) for l in open('data/page_one_progress.jsonl')]
w=max(r['week'] for r in rows)
cur=[r for r in rows if r['week']==w]
print(f'週 {w}: {len(cur)} 行')
print('slug 空:', sum(1 for r in cur if not r.get('slug')), '/', len(cur))
print('delta_basis:', {r.get('delta_basis') for r in cur})
print('theme:', sorted({r.get('theme') for r in cur}))
print('clicks_abs 保持:', all('clicks_abs' in r for r in cur))
print('全 clicks_delta:', sorted({r['clicks_delta'] for r in cur}))
"
```

Expected:
- `slug 空: 0`（または1）
- `delta_basis: {'prev_week'}`
- `theme` が複数
- `clicks_abs 保持: True`
- `全 clicks_delta: [0]` ← **第1週は全件 0。これが正常。** 前週行が無いため

- [x] **Step 5: 成功基準を照合する**

設計文書の「成功基準」のうち、移行直後に検証できる4項目を確認する。

| # | 基準 | 確認方法 |
|---|---|---|
| 1 | slug 空率 75% → 5% 未満 | Step 4 の `slug 空` |
| 2 | theme が unknown 単一でない | Step 4 の `theme` |
| 3 | ojogang の clicks_delta が -14 固着から解放 | Step 4 で `ojogang メンバー` の行が 0 |
| 4 | 単体テストが全て green | Step 1 |

基準 5・6（rollback が5件を評価 / delta 分布から閾値決定）は**第2週以降でないと検証できない**。progress に `prev_week` 行が2週分そろって初めて成立する。

- [x] **Step 6: feedback_loop を走らせ theme 別集計を確認**

Run: `venv_kpi/bin/python3 lib/seo_feedback_loop.py`

Expected: theme 別の統計が `movie_anime` / `dance_show` / `artist` 等に分かれて出力される。`unknown` 単一でないこと。

新たな pending 提案が出た場合は**まだ承認しない**。第1週は `clicks_delta` が全件 0 であり、`clicks_delta_avg <= 0` の条件を満たしてしまうため、`crossed_10_rate` が低い theme に対して誤って「効果薄」提案が出る可能性がある。第2週以降の判断を待つ。

- [x] **Step 7: 実測結果を設計文書に追記してコミット**

設計文書の「実測結果」節（Task 8 Step 5 で作った節）に本書き込み後の値を追記し、コミットする。

```bash
git add docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md data/page_one_progress.jsonl
git commit -m "docs(tracker): 本書き込み後の実測結果を記録"
```

---

## 第2週以降のフォローアップ（本計画のスコープ外・別途実施）

来週 tracker が2回目の週次実行を終えたら、以下を行う。**本計画には含めない。**

1. `prev_week` 行が2週分そろったことを確認
2. `venv_kpi/bin/python3 lib/seo_auto_rollback.py` の dry-run 出力から delta 分布を観測
3. 分布を見て `ROLLBACK_CLICKS_DELTA_THRESHOLD` を決め、コメントを「前週比」に更新
4. `--i-have-set-the-threshold-from-observed-distribution` を cron に追加し dry-run 固定を解除
5. 成功基準 5・6 を照合

**第1週の dry-run ログで閾値を決めてはならない。** 分布が全件ゼロなのは実態ではなく初期化の副作用である。
