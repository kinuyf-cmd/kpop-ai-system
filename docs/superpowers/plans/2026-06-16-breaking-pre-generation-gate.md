# 速報の生成前ゲート Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 速報生成のコスト（Web検索＋LLM生成）を払う前に、公開済み記事との重複・短すぎるソースを弾く生成前ゲートを `publish_breaking()` 冒頭に挿入する。

**Architecture:** 既存 `pre_publish_gate.py` 内のインライン重複判定（1g）を `find_duplicate_published()` に抽出し生成前/生成後で共有。`breaking_news_detector.py` に `_pre_generation_gate()` を新設し、`publish_breaking()` 冒頭で重複→短文の順にチェック、不合格なら `mark_processed`＋skipログで `return None`。

**Tech Stack:** Python 3.12, pytest（`monkeypatch`）, WP REST API（urllib）, `lib/source_reader.read_sources`。テストは `python3 -m pytest`（venv_kpi には pytest 無し、system python3 にあり）。

設計: `docs/superpowers/specs/2026-06-16-breaking-pre-generation-gate-design.md`

---

## File Structure

- `lib/pre_publish_gate.py`（変更）: 1g重複判定を `find_duplicate_published()` に抽出し、既存1gはこの関数を呼ぶ形にリファクタ。
- `pipeline/breaking_news_detector.py`（変更）: `read_sources` を module-level import に移動（mock可能化）、`SHORT_SOURCE_MIN` 定数追加、`_pre_generation_gate()` 新設、`publish_breaking()` 冒頭にゲート挿入＋source_text再利用。
- `tests/unit/test_find_duplicate_published.py`（新規）: 抽出関数の単体テスト。
- `tests/unit/test_pre_generation_gate.py`（新規）: 生成前ゲートの単体テスト。

---

## Task 1: 重複判定ロジックを find_duplicate_published に抽出

**Files:**
- Modify: `lib/pre_publish_gate.py:452-483`（1g重複チェック）
- Test: `tests/unit/test_find_duplicate_published.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_find_duplicate_published.py` を新規作成:

```python
"""find_duplicate_published の単体テスト(2026-06-16)
公開済み記事との重複判定を生成前/生成後で共有する抽出関数。
"""
import json
from unittest.mock import patch, MagicMock
from lib.pre_publish_gate import find_duplicate_published


def _fake_resp(payload):
    """urlopen のコンテキストマネージャ戻り値を模す。"""
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def test_returns_dup_when_proper_nouns_overlap():
    # 既存記事タイトルに aespa / Winter が含まれ、入力キーワードと2語一致
    existing = [{"id": 999, "title": {"rendered": "aespa Winter 新ビジュアル公開"}}]
    with patch("urllib.request.urlopen", return_value=_fake_resp(existing)):
        dup = find_duplicate_published(["aespa", "Winter", "ビジュアル"])
    assert dup is not None
    assert dup["id"] == 999


def test_returns_none_when_no_overlap():
    existing = [{"id": 1, "title": {"rendered": "BTS ジョングク 入隊"}}]
    with patch("urllib.request.urlopen", return_value=_fake_resp(existing)):
        dup = find_duplicate_published(["IVE", "ウォニョン"])
    assert dup is None


def test_returns_none_on_api_error():
    # APIエラーは「重複なし」扱い(ブロックしない=従来挙動)
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        dup = find_duplicate_published(["aespa", "Winter"])
    assert dup is None


def test_returns_none_on_empty_keywords():
    with patch("urllib.request.urlopen", return_value=_fake_resp([])):
        dup = find_duplicate_published([])
    assert dup is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_find_duplicate_published.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_duplicate_published'`

- [ ] **Step 3: Add find_duplicate_published function**

`lib/pre_publish_gate.py` の `pre_publish_gate` 関数より前（module-level、例えば既存の import 群の直後）に新関数を追加:

```python
def find_duplicate_published(keywords):
    """公開済み記事に同テーマ(キーワード重複)があれば {'id','title'} を返す。無ければ None。

    keywords: 正規化済みキーワードのリスト(英字2+/カタカナ3+/漢字2+)。
    判定: 固有名詞(英字/カタカナ)が2語以上一致、または overlap>=2 かつ overlap率>40%。
    APIエラー時は None(=重複なし扱い。ブロックしない=従来1g挙動を踏襲)。
    """
    if not keywords:
        return None
    try:
        import urllib.request, urllib.parse
        search_q = ' '.join(keywords[:3])
        wp_api = os.environ.get('WP_API_URL', 'https://www.kpopjournal.tokyo/wp-json/wp/v2')
        search_url = (
            f'{wp_api}/posts?search={urllib.parse.quote(search_q)}'
            f'&status=publish&per_page=5&_fields=id,title'
        )
        req = urllib.request.Request(search_url, headers={'User-Agent': 'KPJ-Gate/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            existing = json.loads(resp.read())
        new_kw = set(k.lower() for k in keywords)
        for ep in existing:
            et = ep.get('title', {})
            et_text = et.get('rendered', '') if isinstance(et, dict) else str(et)
            ex_kw = set(re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{3,}|[一-龥]{2,}', et_text.lower()))
            overlap = new_kw & ex_kw
            proper_overlap = {w for w in overlap if re.match(r'[a-z]', w) or re.match(r'[ァ-ヶー]', w)}
            if len(proper_overlap) >= 2 or (len(overlap) >= 2 and len(overlap) / max(len(new_kw), 1) > 0.4):
                return {'id': ep.get('id'), 'title': et_text}
    except Exception:
        return None
    return None
```

注: `os`, `re`, `json` は `pre_publish_gate.py` で既に import 済み（ファイル先頭を確認）。未 import のものがあれば追加する。

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_find_duplicate_published.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add lib/pre_publish_gate.py tests/unit/test_find_duplicate_published.py
git commit -m "feat(gate): find_duplicate_published を抽出（生成前/後で共有）"
```

---

## Task 2: 既存1gを find_duplicate_published 呼び出しにリファクタ

**Files:**
- Modify: `lib/pre_publish_gate.py:452-483`
- Test: `tests/unit/test_gate_non_kpop_topic.py`, `tests/unit/test_gate_structural_only.py`（回帰）

- [ ] **Step 1: Replace inline 1g with function call**

`lib/pre_publish_gate.py` の 1g ブロック（452-483行、`# 1g. 重複記事チェック` から `pass  # APIエラーは投稿をブロックしない` まで）を次に置換:

```python
    # 1g. 重複記事チェック (2026-05-06追加 / 2026-06-16 find_duplicate_published に集約)
    if status == 'publish' and title:
        _norm_title = re.sub(r'[【\[\(][^】\]\)]*[】\]\)]|！|!|？|\?', '', title).strip()
        _keywords = re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{3,}|[一-龥]{2,}', _norm_title)
        _keywords = [k for k in _keywords if k not in ('ガイド', '完全', '最新', '徹底', '紹介', '解説', 'まとめ', '速報', '必見')]
        _dup = find_duplicate_published(_keywords)
        if _dup:
            issues.append({
                'type': 'duplicate_title',
                'severity': 'block',
                'detail': f'類似テーマの記事が公開済み (ID={_dup["id"]}): {str(_dup["title"])[:40]}',
            })
```

- [ ] **Step 2: Run regression tests**

Run: `python3 -m pytest tests/unit/test_gate_non_kpop_topic.py tests/unit/test_gate_structural_only.py tests/unit/test_find_duplicate_published.py -v`
Expected: PASS（全て。1g抽出で既存ゲート挙動は不変）

- [ ] **Step 3: Run full suite to confirm no breakage**

Run: `python3 -m pytest -q`
Expected: 既存と同じ pass 数（+Task1の4件）、failures 0

- [ ] **Step 4: Commit**

```bash
git add lib/pre_publish_gate.py
git commit -m "refactor(gate): 1g重複判定を find_duplicate_published 呼び出しに集約"
```

---

## Task 3: read_sources を module-level import + SHORT_SOURCE_MIN 定数

**Files:**
- Modify: `pipeline/breaking_news_detector.py:643`（local import 削除）, 先頭 import 群, 定数定義部

- [ ] **Step 1: Move read_sources import to module level**

`pipeline/breaking_news_detector.py` の先頭 import 群（17行目 `from pipeline.auto_event_article import is_processed, mark_processed` の直後）に追加:

```python
from lib.source_reader import read_sources
```

そして `publish_breaking` 内の local import（643行目 `    from lib.source_reader import read_sources`）を**削除**する。

- [ ] **Step 2: Add SHORT_SOURCE_MIN constant**

`BREAKING_LOG = ...`（20行目付近）の近く、module-level 定数として追加:

```python
# 生成前ゲート: ソース本文がこの文字数未満なら「薄すぎ」として生成前にスキップ。
# 保守的な低閾値(Web検索で補える中間長は通す)。pre_publish_gate の content_empty(<400字)
# より手前で、LLM生成コストを払う前に弾くのが目的。
SHORT_SOURCE_MIN = 150
```

- [ ] **Step 3: Verify import still works**

Run: `python3 -c "import pipeline.breaking_news_detector as b; print(b.read_sources, b.SHORT_SOURCE_MIN)"`
Expected: `<function read_sources ...> 150`（エラーなく表示）

- [ ] **Step 4: Run full suite (no behavior change yet)**

Run: `python3 -m pytest -q`
Expected: failures 0

- [ ] **Step 5: Commit**

```bash
git add pipeline/breaking_news_detector.py
git commit -m "refactor(breaking): read_sources を module import 化 + SHORT_SOURCE_MIN 追加"
```

---

## Task 4: _pre_generation_gate を新設

**Files:**
- Modify: `pipeline/breaking_news_detector.py`（`publish_breaking` の直前に新関数）
- Test: `tests/unit/test_pre_generation_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_pre_generation_gate.py` を新規作成:

```python
"""_pre_generation_gate の単体テスト(2026-06-16)
生成前に 重複→短文 を弾く。find_duplicate_published と read_sources をモック。
"""
import pipeline.breaking_news_detector as bnd


_SIGS = [{"title": "aespa Winter 新ビジュアル", "url": "https://x.com/a"}]


def test_blocks_on_duplicate(monkeypatch):
    monkeypatch.setattr(bnd, "find_duplicate_published", lambda kw: {"id": 7, "title": "既存"})
    # read_sources は呼ばれない想定だが、呼ばれても安全な値
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: "x" * 500)
    ok, reason, text = bnd._pre_generation_gate("aespa", _SIGS)
    assert ok is False
    assert "dup_pre_gen" in reason
    assert text == ""


def test_blocks_on_short_source(monkeypatch):
    monkeypatch.setattr(bnd, "find_duplicate_published", lambda kw: None)
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: "短い" * 10)  # 20字 < 150
    ok, reason, text = bnd._pre_generation_gate("aespa", _SIGS)
    assert ok is False
    assert "short_source" in reason
    assert text == ""


def test_passes_when_unique_and_long(monkeypatch):
    monkeypatch.setattr(bnd, "find_duplicate_published", lambda kw: None)
    long_text = "あ" * 500
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: long_text)
    ok, reason, text = bnd._pre_generation_gate("aespa", _SIGS)
    assert ok is True
    assert reason == ""
    assert text == long_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_pre_generation_gate.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute '_pre_generation_gate'`

- [ ] **Step 3: Implement _pre_generation_gate**

`pipeline/breaking_news_detector.py` の `def publish_breaking(...)`（638行目）の直前に追加:

```python
def _pre_generation_gate(artist, sigs):
    """生成前ゲート。重複→短文の順に判定。
    戻り値 (ok: bool, reason: str, source_text: str)。
    ok=False のとき呼び出し側は mark_processed + skip ログで return None する。
    ok=True のとき source_text を生成本体で再利用する(read_sources 二重取得回避)。
    """
    import re as _re
    best = max(sigs, key=lambda s: len(s.get('title', '')))
    # チェックA: 公開済み記事との重複(WP REST API 1回のみで軽い → 先に判定)
    _norm = _re.sub(r'[【\[\(][^】\]\)]*[】\]\)]|！|!|？|\?', '', best.get('title', '')).strip()
    kw = _re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{3,}|[一-龥]{2,}', f'{artist} {_norm}')
    kw = [k for k in kw if k not in ('ガイド', '完全', '最新', '徹底', '紹介', '解説', 'まとめ', '速報', '必見')]
    dup = find_duplicate_published(kw)
    if dup:
        return (False, f'dup_pre_gen:ID={dup.get("id")}', '')
    # チェックB: ソース本文が短すぎる(read_sources は HTTP 取得でやや重い → 後)
    source_text = read_sources(sigs) or ''
    if len(source_text.strip()) < SHORT_SOURCE_MIN:
        return (False, f'short_source:{len(source_text.strip())}字', '')
    return (True, '', source_text)
```

`find_duplicate_published` を使うため、ファイル先頭の import に追加:

```python
from lib.pre_publish_gate import find_duplicate_published
```

（17行目の import 群付近に置く。循環 import が起きないか Step 4 で確認）

- [ ] **Step 4: Run test + import check**

Run: `python3 -c "import pipeline.breaking_news_detector" && python3 -m pytest tests/unit/test_pre_generation_gate.py -v`
Expected: import エラーなし、3 tests PASS。
（循環 import エラーが出た場合は `find_duplicate_published` の import を `_pre_generation_gate` 関数内の local import に変更し、テストの monkeypatch 対象も `bnd._pre_generation_gate` が参照する名前に合わせる。まず module-level を試す。）

- [ ] **Step 5: Commit**

```bash
git add pipeline/breaking_news_detector.py tests/unit/test_pre_generation_gate.py
git commit -m "feat(breaking): _pre_generation_gate を新設（重複→短文）"
```

---

## Task 5: publish_breaking 冒頭にゲートを挿入し source_text を再利用

**Files:**
- Modify: `pipeline/breaking_news_detector.py:638-644`（`publish_breaking` 冒頭）

- [ ] **Step 1: Insert gate at top of publish_breaking**

`publish_breaking` の冒頭（`best = max(...)` と Step 0 の間）を次のように変更する。

変更前（638-644行付近）:
```python
def publish_breaking(artist, sigs, typ):
    """unified_publish経由で速報投稿（ソース本文取得→Web検索→生成→公開）"""
    best = max(sigs, key=lambda s: len(s.get('title', '')))

    # Step 0: ソースURLから本文を直接取得（最も重要な事実の根拠）
    source_text = read_sources(sigs)
```

変更後:
```python
def publish_breaking(artist, sigs, typ):
    """unified_publish経由で速報投稿（生成前ゲート→ソース本文→Web検索→生成→公開）"""
    best = max(sigs, key=lambda s: len(s.get('title', '')))

    # 生成前ゲート(2026-06-16): 重複・短文をコスト発生前に弾く。
    _ok, _reason, _source_text = _pre_generation_gate(artist, sigs)
    if not _ok:
        print(f"  [breaking] 生成前ゲートでskip: {_reason}")
        for s in sigs:
            mark_processed({
                'ts': datetime.now().isoformat(), 'source_url': s['url'],
                'kind': 'breaking_blocked', 'reason': _reason, 'type': typ,
            })
        _log_breaking_skip(_reason, artist=artist, typ=typ,
                           title=best.get('title'), url=best.get('url'))
        return None

    # Step 0: ソース本文(生成前ゲートで取得済みを再利用)
    source_text = _source_text
```

注: 変更前の `source_text = read_sources(sigs)` 行（643行の local import は Task 3 で既に削除済み）を上記の `source_text = _source_text` に置換する。Task 3 で local import を消しているので、ここに `from lib.source_reader import read_sources` は残っていないこと。

- [ ] **Step 2: Run targeted + full suite**

Run: `python3 -m pytest tests/unit/test_pre_generation_gate.py tests/unit/test_find_duplicate_published.py -q && python3 -m pytest -q`
Expected: 全 PASS、failures 0

- [ ] **Step 3: Smoke test publish_breaking gate path (dup) via monkeypatch**

一時確認用に以下をワンライナーで実行（ファイルは作らない）:

Run:
```bash
python3 -c "
import pipeline.breaking_news_detector as b
b.find_duplicate_published = lambda kw: {'id':1,'title':'既存'}
b.read_sources = lambda s: 'x'*500
b.mark_processed = lambda r: None
r = b.publish_breaking('aespa', [{'title':'aespa Winter','url':'https://x/a'}], 'multi')
print('dup path result:', r)
"
```
Expected: `生成前ゲートでskip: dup_pre_gen...` が出力され、最終行 `dup path result: None`（unified_publish に到達せず＝コスト0）

- [ ] **Step 4: Commit**

```bash
git add pipeline/breaking_news_detector.py
git commit -m "feat(breaking): publish_breaking 冒頭に生成前ゲート挿入 + source_text再利用"
```

---

## Task 6: 最終検証

- [ ] **Step 1: Full test suite**

Run: `python3 -m pytest -q`
Expected: failures 0（既存 + 新規 7 件 pass）

- [ ] **Step 2: Syntax check both modules**

Run: `python3 -c "import ast; [ast.parse(open(f).read()) for f in ['lib/pre_publish_gate.py','pipeline/breaking_news_detector.py']]; print('syntax OK')"`
Expected: `syntax OK`

- [ ] **Step 3: Import smoke**

Run: `python3 -c "import pipeline.breaking_news_detector; from lib.pre_publish_gate import find_duplicate_published; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 4: Confirm no double read_sources in publish_breaking**

Run: `grep -n "read_sources" pipeline/breaking_news_detector.py`
Expected: module-level import 1行 + `_pre_generation_gate` 内の呼び出し1行のみ（`publish_breaking` 内に直接呼び出しが残っていないこと）

---

## Self-Review Notes

- **Spec coverage**: find_duplicate_published 抽出(Task1) / 1g集約(Task2) / 短文閾値・read_sources再利用(Task3,5) / _pre_generation_gate A→B順(Task4) / mark_processed＋skipログ(Task5) / テスト(Task1,4)＋回帰(Task2) — 全カバー。
- **観測性**: `_log_breaking_skip` が既存で `breaking_articles.jsonl` に `status:skipped/skip_reason` を書く（新経路追加なし、spec通り）。
- **型整合**: `_pre_generation_gate -> (bool,str,str)`、`find_duplicate_published -> dict|None`。呼び出し側と一致。
- **循環import**: `breaking_news_detector` が `pre_publish_gate` を import。逆向き依存が無いか Task4 Step4 で実機確認、ダメなら local import にフォールバック（手順明記済）。
