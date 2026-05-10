# Usage Guide — kpop-quality skill

## 前提

- Anthropic API key: `ANTHROPIC_API_KEY` を `.env` に設定
- Python 3.10+
- 必要パッケージ: `anthropic`, `python-dotenv`, `Pillow`, `matplotlib` (KPI analyzer用)

## クイックスタート

### A. 記事1件のfactcheck

```python
from lib.factcheck_v2 import proofread_post_v2

post = {
    'id': 19623,
    'title': {'rendered': 'IU視聴率自己最高更新'},
    'content': {'rendered': '<本文HTML>'},
}
result = proofread_post_v2(post)

if result['score'] < 60:
    print(f"❌ Critical issues: {result['critical']}")
elif result['score'] < 80:
    print(f"⚠️ High issues: {result['high']}")
else:
    print(f"✅ Score: {result['score']}")
```

### B. 韓国語→日本語翻訳

```python
from lib.translator_v2 import translate_ko_to_ja_v2

r = translate_ko_to_ja_v2(korean_text)
if r['success']:
    print(r['translated'])
    if r['residual_korean_count'] > 0:
        print(f"⚠️ {r['residual_korean_count']}文字のhangulが残存")
```

### C. サムネ画像検証

```python
from lib.thumbnail_vision_gate import vision_validate

# pre-publish gate
ok, reason = vision_validate('/tmp/thumb.jpg', 'aespa')
if not ok:
    print(f"❌ Vision gate BLOCK: {reason}")
    # → 別画像にfallback / 通報
```

### D. KPI トレンド分析

```python
from lib.kpi_analyzer import analyze_x_kpi

r = analyze_x_kpi(focus='engagement_trend')
print(r['summary'])  # ANALYSIS RESULTセクション付き分析
print(r['charts'])   # 生成chart pathリスト
```

## 統合例

### 記事公開パイプラインへの組み込み

```python
# 公開前 — factcheck v2
result = proofread_post_v2(post)
if result['score'] < 60:
    raise BlockError(f"factcheck critical: {result['critical']}")

# 公開前 — vision gate
ok, reason = vision_validate(thumb_path, expected_artist=artist)
if not ok:
    fallback_to_alternative_thumb()

# 公開実行
publish_to_wp(post)

# 公開後 — KPI監視 (cron)
# 22時にdaily_kpi_report.pyが自動実行
```

## トラブルシューティング

### `output_config.format.schema: ... not supported`

JSON schema で `minimum`/`maximum`/`minLength`/`maxLength` 等の数値制約は
Claude構造化出力で非サポート。これらを除いた schema を使うこと。

### Vision gate がfalse positiveを返す

- 公式ロゴ (SMTOWN OFFICIAL等) の有無で精度大きく変わる
- artist指定が曖昧な場合 (例: solo記事に group名指定) は member→group fallback設計
- prompt caching時にartist名を明示するとaccuracy向上

### Web search でTavily quotaに混雑

`lib.claude_websearch_factcheck.verify_with_claude_websearch()` を直接呼べば
Tavilyを完全bypass可能 (Anthropic API quotaのみ消費)。

## アーキテクチャ図

```
[記事生成]
  └→ translator_v2  (KR→JA, caching+schema)
[サムネ生成]
  └→ thumbnail_vision_gate  (画像内容検証)
[公開ゲート]
  ├→ factcheck_v2  (Claude+Web search+caching+schema)
  ├→ vision_gate
  └→ pre_publish_gate (translation_residue_check等)
[公開後]
  ├→ thumbnail_contamination_audit (cron 11:00)
  └→ daily_kpi_report (cron 22:00, Files API+code_execution)
[学習]
  └→ factcheck_lessons.jsonl (自己改善)
```
