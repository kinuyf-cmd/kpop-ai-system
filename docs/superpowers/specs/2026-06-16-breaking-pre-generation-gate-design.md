# 速報の生成前ゲート設計（上流での無駄削減）

作成日: 2026-06-16
対象: `pipeline/breaking_news_detector.py` / `lib/pre_publish_gate.py`

## 背景・目的

速報自動生成の公開率は44%（blocked 56%）。直近300件の内訳：

| ブロック理由 | 割合 | 性質 |
|---|---|---|
| 重複（類似テーマ既公開） | 37% | 全文生成＋factcheck後にWP REST API検索で発覚＝丸ごと無駄 |
| 本文が短すぎる | 20% | 薄いソースを生成にかけている |
| factcheck（未確認事実） | 9% | 正当 |
| サムネ・古い年・矛盾 | 残り | 正当 |

ゲート自体は健全（ハルシネ・重複・古ネタを正しく止めている）。問題は **コスト（Web検索＋LLM生成2回）を払い終えた後に捨てている**こと。重複37%＋短文20%＝**約57%は生成前に止められる**。1日速報77本・重複37%＝約28本/日が無駄（直近300レコードで$8.5）。

参照: `[[breaking-blocked-57pct-upstream-waste]]` `[[breaking-news-hit-rate-5pct-upstream-problem]]`

## スコープ

- **やる**: `publish_breaking()` の冒頭に生成前ゲートを挿入し、重複・短文ソースをコスト発生前に弾く。既存の重複判定ロジックを共通関数に抽出して生成前/生成後で共有。
- **やらない**: 重複判定の基準値変更（誤検知を増やさないため既存と同一基準）、ネタ選定（select_candidates）自体のスコアリング改善、サムネ/古年ゲートの前倒し（本タスク外）。

## アーキテクチャ

`publish_breaking(artist, sigs, typ)` の冒頭（既存 Step 0 = `read_sources` の前）に生成前ゲートを挿入する。

```
publish_breaking(artist, sigs, typ)
 ├─ 【新】_pre_generation_gate(artist, sigs) -> (ok: bool, reason: str, source_text: str)
 │    ├─ チェックA: 公開済み記事との重複
 │    │     find_duplicate_published(keywords) を呼ぶ（既存1gを抽出した共通関数）
 │    │     キーワード = artist + best(sigs)['title'] から抽出
 │    │     → 重複あり: ok=False, reason='dup_pre_gen'
 │    ├─ チェックB: ソース本文が極端に短い
 │    │     source_text = read_sources(sigs)   ← ここで1回だけ取得
 │    │     len(source_text) < 150 → ok=False, reason='short_source'
 │    └─ ok=True, source_text を返す（生成本体で再利用）
 ├─ ゲート不合格時:
 │     mark_processed(各sig) + _log_breaking_skip(reason) + _log_skipped_breaking(status:skipped)
 │     return None   ← Web検索/LLM生成に進まない
 ├─ Step 0: read_sources  → ゲートで取得済みの source_text を再利用
 ├─ Step 1: Web検索
 └─ 生成・publish...（既存のまま）
```

**順序の根拠**: チェックA（重複）はWP REST API 1回のみで軽い。チェックB（短文）は `read_sources`（ソースHTTP取得）が必要でやや重い。よって **A→B の順**にし、重複で先に弾けるものは `read_sources` も省く。

## コンポーネント詳細

### 1. `find_duplicate_published(keywords: list[str]) -> dict | None`（lib/pre_publish_gate.py）

既存 `pre_publish_gate.py:452-483`（1g重複チェック）のコア部分を抽出した新関数。

- 入力: キーワードのリスト（呼び出し側が `_norm_title` → `re.findall` で抽出）
- 処理: WP REST API `/posts?search=...&status=publish&per_page=5` で公開済み記事を検索し、既存と同じ重複判定（固有名詞2語以上一致 or overlap>=2かつ40%超）を行う
- 戻り値: 重複記事があれば `{'id':..., 'title':...}`、無ければ `None`
- 例外時: `None`（=ブロックしない。既存の「APIエラーは投稿をブロックしない」を踏襲）
- env: `WP_API_URL`（既定 `https://www.kpopjournal.tokyo/wp-json/wp/v2`）

既存1gは、この関数を呼ぶ形にリファクタ（インラインロジックを置換）。キーワード抽出（`_norm_title`/除外語リスト）は呼び出し側に残し、関数は「キーワード→重複記事」に専念。判定基準は1か所に一元化される。

### 2. `_pre_generation_gate(artist, sigs) -> tuple[bool, str, str]`（pipeline/breaking_news_detector.py）

- チェックA: `best = max(sigs, key=lambda s: len(s.get('title','')))` のタイトル + artist からキーワード抽出 → `find_duplicate_published()`。重複あり → `(False, 'dup_pre_gen:ID=...', '')`
- チェックB: `source_text = read_sources(sigs)`。`len(source_text.strip()) < SHORT_SOURCE_MIN`（=150）→ `(False, 'short_source:N字', '')`
- 通過: `(True, '', source_text)`
- `SHORT_SOURCE_MIN = 150` はモジュール定数（保守的な低閾値。Web検索で補える中間長は通す）

### 3. スキップ時の処理（publish_breaking 内）

ゲート不合格時、既存の factcheck ブロック時（`publish_breaking` 末尾 768-776行）と**同一形式**の後処理を行う:
- 各 sig を `mark_processed({'ts':..., 'source_url': s['url'], 'kind':'breaking_blocked', 'reason': reason, 'type': typ})`（既存blocked時と同じ record 形。次サイクルで `is_processed` により再候補化しない）
- `_log_breaking_skip(reason, artist=artist, typ=typ, title=best.get('title'), url=best.get('url'))`
- `_log_breaking_skip` は内部で `breaking_articles.jsonl` に `status:skipped` を記録する既存関数（週次skip監査に乗る。`[[breaking-skip-observability]]`）。新たな書き込み経路は追加しない

### 4. source_text の再利用

`_pre_generation_gate` が返した `source_text` を `publish_breaking` の Step 0 で使い、`read_sources` の二重呼び出しを避ける。

## データフロー

```
select_candidates → [(artist, sigs, typ), ...]
  各候補 → publish_breaking(artist, sigs, typ)
    _pre_generation_gate(artist, sigs)
      A: find_duplicate_published(keywords)  [WP REST API]
      B: read_sources(sigs)                  [source HTTP]  ← source_text 確保
    不合格 → mark_processed + log + return None   （コスト0）
    合格   → source_text 再利用 → Web検索 → LLM生成×2 → unified_publish
                                              └ pre_publish_gate（1g含む、保険で残す）
```

## エラーハンドリング

- `find_duplicate_published` の WP API 例外 → `None`（ブロックしない＝従来挙動）。生成前ゲートは「重複が確実な時だけ弾く」安全側。
- `read_sources` が例外/空 → `source_text=''` → 短文判定で `short_source` スキップ（薄い記事を出すよりスキップが安全。ただしソース取得失敗とソース本来短いの区別はしない＝保守的）。

## テスト方針

- `find_duplicate_published`:
  - 重複あり（固有名詞2語一致）→ dict 返す
  - 重複なし → None
  - WP API 例外（urlopen をモックで raise）→ None（ブロックしない）
- `_pre_generation_gate`（`find_duplicate_published`/`read_sources` をモック）:
  - 重複検出 → (False, 'dup_pre_gen...', '')
  - 短文（read_sources が100字）→ (False, 'short_source...', '')
  - 正常（重複なし＋十分長い）→ (True, '', source_text)
- 回帰: 既存 `tests/unit/test_gate_*.py` が緑のまま（1g抽出リファクタの安全確認）

## リスクと対策

| リスク | 対策 |
|---|---|
| 誤スキップ（健全な速報を落とす） | 重複判定は既存1gと**同一基準**。新たな誤検知は増えない（前倒しするだけ）。閾値据え置き |
| 中核パイプライン変更 | TDD。各ステップで既存テスト緑を確認。生成後gateは保険で残す（2重防御） |
| ソース取得失敗を短文扱いでスキップ | 保守的に許容（薄い記事公開よりスキップが安全）。skipログで観測可能、必要なら後で閾値調整 |
| read_sources 二重取得 | ゲートで取得した source_text を呼び出し側へ返して再利用 |

## 成功基準

- 重複・短文の候補が **生成前に** スキップされ、Web検索/LLM生成に進まない（ログで確認）
- 既存テスト全緑 + 新規テスト緑
- blocked のうち「重複」「短文」が生成後gateからほぼ消える（次回スキャン/監査で確認、目安1週間後）
