---
name: kpop-quality
description: K-POPメディア記事の品質保証スキル群 — factcheck (Claude+Web search+caching+schema), 翻訳 (KR→JA), サムネ画像検証 (Vision gate), KPI分析 (Files API+Code execution)。Claude API/Anthropic SDKを使ったK-POPコンテンツ運用の各タスクで参照。
---

# K-POP Quality Assurance Skill

K-POPメディアサイト運用で頻発する品質課題に対する、Claude APIベースの統合ソリューション。

## 含まれるツール

### 1. factcheck v2 — 記事内容のファクトチェック
Claude Sonnet 4.6 + Web search + Prompt caching + Structured outputs

**使い方**:
```python
from lib.factcheck_v2 import proofread_post_v2
result = proofread_post_v2(post)  # post: {'id', 'title', 'content'}
# result: {'score': 0-100, 'critical': [...], 'high': [...], 'medium': [...], 'verified_facts': [...]}
```

**機能**:
- K-pop主要22グループの所属/人数/デビュー年を内蔵 (cache済)
- web_search ツールで信頼メディア (soompi/allkpop/billboard等) で裏取り
- JSON schema強制でparse失敗ゼロ
- 過去の検出を `factcheck_lessons.jsonl` に蓄積し自己学習

**実証**: 「2049視聴率」→「2054視聴率」の誤記を web search で検出済

### 2. translator v2 — 韓国語→日本語翻訳
Claude Sonnet 4.6 + Prompt caching + Structured outputs

**使い方**:
```python
from lib.translator_v2 import translate_ko_to_ja_v2
r = translate_ko_to_ja_v2(korean_text, context='K-POP entertainment news')
# r: {'success': bool, 'translated': str, 'residual_korean_count': int, ...}
```

**機能**:
- 翻訳ルール+グロッサリー(1500tokens)を prompt cacheで90%cost削減
- 22主要グループ + 専門用語(컴백/음원/팬미팅等) の正規化
- 固有名詞辞書 (config/korean_proper_nouns.json) との二段防御
- residual_korean_count で hangul残存検出 (gate判定用)

### 3. thumbnail vision gate — サムネ画像検証
Claude Sonnet 4.6 + Vision API + Prompt caching + Structured outputs

**使い方**:
```python
from lib.thumbnail_vision_gate import vision_validate
ok, reason = vision_validate(image_path, expected_artist='BLACKPINK')
```

**機能**:
- 画像内容と期待artistが一致するか判定
- 公式ロゴ識別 (SMTOWN/YG OFFICIAL/ADOR等)
- SHA256キャッシュで再検証回避

**実証**: aespa→TWICE誤指定を SMTOWN(SM)≠JYP判定でBLOCK確認

### 4. KPI analyzer — エンゲージメント分析
Files API + Code execution tool

**使い方**:
```python
from lib.kpi_analyzer import analyze_x_kpi
r = analyze_x_kpi(focus='engagement_trend')  # or 'template_comparison', 'best_tweet_pattern'
# r: {'summary': str, 'charts': [...], 'code_runs': int}
```

**機能**:
- x_kpi.jsonl を Files API でupload → code_execution tool で pandas+matplotlib分析
- 3-panel chart自動生成 (followers/imp/engagement)
- 「ANALYSIS RESULT」マーカーで構造化抽出

## 環境変数

```bash
ANTHROPIC_API_KEY=...        # 必須
FACTCHECK_V2=1               # llm_proofreaderをClaude版に切替
TRANSLATOR_V2=1              # korean_translatorをClaude版に切替
DISCORD_WEBHOOK_URL=...      # 通知用 (optional)
```

## Anthropic SDK / API 機能の使用一覧

| 機能 | 使用箇所 |
|---|---|
| Vision (base64 image) | thumbnail_vision_gate |
| Web search tool | factcheck_v2 / claude_websearch_factcheck |
| Code execution tool | kpi_analyzer |
| Files API | kpi_analyzer |
| Prompt caching (cache_control) | factcheck_v2 / translator_v2 / vision_gate |
| Structured outputs (output_config.format) | 全モジュール |

## モデル選択基準

- **claude-sonnet-4-6**: factcheck/translator/vision (K-pop知識精度重視)
- **claude-haiku-4-5**: 廃止 (aespa↔TWICE誤認の前科)
- **claude-opus-4-7**: 未使用 (cost対効果でsonnetで十分)

## 共通設計パターン

すべてのモジュールが従う:
1. `cache_control={"type": "ephemeral"}` で system prompt を caching
2. `output_config.format` で JSON schema強制
3. RateLimitError → fail open (過剰BLOCK回避)
4. JSONL log で観測性 (logs/factcheck_v2.jsonl 等)
5. `dotenv` load + `os.environ.get()` で env flag切替
