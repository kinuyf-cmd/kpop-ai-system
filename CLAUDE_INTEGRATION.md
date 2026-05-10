# Claude / Anthropic API Integration

K-pop メディア運用システム kpop-ai-system における Anthropic SDK 主要機能の使用一覧。
2026-05-10 のセッションで構築。

## 設計原則

1. **既存 OpenAI / Tavily を即時置換しない** — env flag (`FACTCHECK_V2=1`, `TRANSLATOR_V2=1`) で切替可能
2. **fail open** — Claude API 障害時は既存 path にフォールバック (過剰BLOCK回避)
3. **Schema enforcement** — 全モジュール `output_config.format` で JSON 強制
4. **Prompt caching** — system prompt の K-pop 知識prefix を5分TTLでcache
5. **Self-improving** — factcheck検出を local jsonl で蓄積し将来の prompt に注入

## モジュール一覧

| モジュール | 機能 | Claude機能 |
|---|---|---|
| `lib/factcheck_v2.py` | 記事内容のfactcheck | Web search + Caching + Schema |
| `lib/translator_v2.py` | 韓国語→日本語翻訳 | Caching + Schema |
| `lib/thumbnail_vision_gate.py` | サムネ画像と期待artistの整合 | Vision + Caching + Schema |
| `lib/claude_websearch_factcheck.py` | Tavily quota fallback | Web search + Schema |
| `lib/factcheck_lessons.py` | 自己学習 (検出pattern蓄積) | local jsonl |
| `lib/kpi_analyzer.py` | x_kpi.jsonl の自動分析 | Files API + Code execution |
| `pipeline/daily_kpi_report.py` | 22時 cron でKPI日報 | (kpi_analyzer 経由) |

## env 変数

```bash
ANTHROPIC_API_KEY=sk-ant-...     # 必須
FACTCHECK_V2=1                   # llm_proofreader を Claude版に切替
TRANSLATOR_V2=1                  # korean_translator を Claude版に切替
DISCORD_WEBHOOK_URL=...          # 通知 (optional)
```

## production cron での Claude 利用

```cron
# 全auditをClaude factcheckで稼働 (2026-05-10〜)
0 7 * * *        cd .../kpop-ai-system && FACTCHECK_V2=1 python3 pipeline/daily_batch_audit.py --auto-fix --quiet
0 10,16,21 * * * cd .../kpop-ai-system && FACTCHECK_V2=1 python3 -m pipeline.comprehensive_audit
0 11 * * *       cd .../kpop-ai-system && python3 pipeline/thumbnail_contamination_audit.py  # Vision gate内蔵
0 22 * * *       cd .../kpop-ai-system && python3 pipeline/daily_kpi_report.py             # Files API + Code execution
```

## モデル選択

| モデル | 用途 | 理由 |
|---|---|---|
| `claude-sonnet-4-6` | factcheck / translator / vision | K-pop知識精度、コスト効率 |
| `claude-opus-4-7` | 未使用 | sonnet で十分なため |
| `claude-haiku-4-5` | 廃止 | aespa↔TWICE誤認の前科 |

OpenAI (`gpt-4o-mini`) は **記事生成** のみで継続使用 (output 25倍コスト差)。
factcheck で品質を後段でcatchする経済的な役割分担。

## Schema仕様 (重要)

Claude `output_config.format.schema` の制限:

```python
# ❌ NOT supported (400 error)
{"type": "integer", "minimum": 0, "maximum": 100}
{"type": "string", "minLength": 1, "maxLength": 500}

# ✅ Supported
{"type": "integer"}
{"type": "string"}
{"type": "string", "enum": ["YES", "NO"]}
{"type": "object", "properties": {...}, "required": [...], "additionalProperties": False}
{"type": "array", "items": {"type": "string"}}
```

JSON Schema の `minimum`/`maximum`/`minLength`/`maxLength`/`pattern` 等の数値・
文字列制約は受け付けない。範囲確認は post-validation で行う。

## トラブルシューティング

### "output_config.format.schema: ... not supported"
→ `minimum`/`maximum` 等の制約を schema から削除

### Vision gate がfalse positive
→ artist指定が曖昧 / 公式ロゴで判定しがち
→ `KPOP_FACTCHECK_PREFIX` 改善 (主要グループの所属事務所 を更に詳細化)

### Tavily quota超過
→ `lib/claude_websearch_factcheck.py` が自動fallback (web_factcheck.py内蔵)

### Prompt cache が効かない
→ `system` block の最初の text に `cache_control={'type': 'ephemeral'}` 必須
→ 1024+ tokens 必要 (短いprefixはcache対象外、silent skip)
→ `usage.cache_read_input_tokens` で hit確認

## 実証された価値

### 19623 IU記事 — factcheck v2 が web search で発見した事実誤り
- 「2049視聴率」 → 韓国原文は「2054視聴率」(20-54歳層)
- 旧 OpenAI proofreader が見逃した
- → factcheck_lessons.jsonl に蓄積、将来の同種記事で事前checkに

### 19571 BOYNEXTDOOR記事 — Vision gate がサムネ汚染を発見
- 男性6人組記事に**3人女性レッドカーペット写真**が貼られていた
- Vision API が "性別不一致" で BLOCK
- 自動修復で正しい BOYNEXTDOOR ステージ写真に差替

### KPI 14日分析 — Code execution で歪な構造発見
- engagement_rate 5/9 spike 1.1% は **reply主体 (likes/RT=0)** = 「ツッコミ系」
- 人間が手で計算するには面倒、Claude が定量で看破
- → 釣り見出し → 一次情報投稿への転換を具体推奨

## Skill folder

`skills/kpop-quality/` — Claude Skill 規約での packaging (SKILL.md frontmatter + USAGE.md)

## 今後の拡張候補

- **Memory tool 直接利用**: 現在は local jsonl で代替。Anthropicのmemory APIへ移行可能
- **Managed Agents**: 監査agentをAnthropic側にホスト (ops転換が必要)
- **Computer use**: X analytics dashboard の自動screenshot
- **記事生成 v2**: 現在 OpenAI gpt-4o-mini → Claude移行はcost跳ね上がる(25倍)ため検討中
