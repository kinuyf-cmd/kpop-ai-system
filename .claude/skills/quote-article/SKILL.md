---
name: quote-article
description: K-POP元記事 (Soompi/Allkpop/Osen/MyDaily/Koreaboo等) を引用して KpopJournal に news/breaking 記事を1件生成・公開する。Claude が手動で生成する際の手順固定+drift防止。pipeline/breaking_news_detector.py の publish_breaking() と同じ10ステージを Claude が辿る。Use when the user asks "この記事を書いて <URL>" or "/quote-article <URL>".
---

# quote-article — K-POP引用記事1件生成

## 入力
ユーザーが `/quote-article <URL>` または「この記事を書いて <URL>」と指定した URL を1つ受け取る。
URL不在なら「ソースURLを指定してください」で停止すること。**勝手に signal queue から拾うな** (それは breaking_news_detector cron の仕事)。

## 必須前提 — これを守らないと過去事故 (post 20962 / x_queue ループ) が再発する

- **信頼ドメインのみ**: URL のホストが `lib/source_domains.py` の trusted_korean/japan/global media に含まれていること。含まれなければ STOP (`feature_no_source` BLOCK確実 + post_publish_hook で draft化される)。
- **ソース本文取得必須**: `lib.source_reader.read_sources` で本文 100字以上取得できなければ STOP (`source_not_read` WARN だが品質低い)。
- **GPT単独生成禁止**: 本文や固有名詞をソースから引用すること。memory `feedback_must_read_source` 違反は捏造率18%。
- **タイトルは忠実翻訳**: 煽り・意訳・要約禁止。memory `feedback_title_faithful_translation`。
- **現在日付プロンプト注入**: prompt に `today=YYYY年MM月DD日` を必ず含める。memory `feedback_llm_prompt_date_context`。

## 実行手順 — 10ステージ全て完了するまで報告禁止

各ステージの結果を「ステージ進行ログ」として user-facing で1行報告すること。

### Stage 1 — URL検証
```python
from lib.source_domains import is_trusted_source
assert is_trusted_source(url), f"信頼ドメイン外: {url}"
```
失敗時: `❌ 信頼ドメイン外` で STOP。

### Stage 2 — ソース本文取得
```python
from lib.source_reader import read_sources
text = read_sources([{'url': url, 'title': '', 'language': 'ko'}])
assert text and len(text) >= 100
```
失敗時: `❌ ソース本文取得失敗 (XX字)` で STOP。

### Stage 3 — Web検索補完 (Tavily上限到達なら DDG fallback自動)
```python
from pipeline.breaking_news_detector import _enrich_with_web_search
web_facts = _enrich_with_web_search(title, [{'url': url, ...}])
```
注意: Tavily上限到達は `data/tavily_quota_exhausted.json` で判定済 (skip 自動)。

### Stage 4 — アーティスト profile 注入
```python
from pipeline.breaking_news_detector import _get_artist_profile_context
profile = _get_artist_profile_context(artist, sigs=[...])
```

### Stage 5 — プロンプト構築 (現在日付必須)
```python
from datetime import datetime
today = datetime.now().strftime('%Y年%m月%d日')
# breaking_news_detector._BREAKING_PROMPT_TEMPLATE を再利用
prompt = template.format(today=today, year_month=..., combined=..., web_context_section=..., profile_context=...)
```

### Stage 6 — 翻訳 (タイトル + 本文)
```python
from lib.korean_translator import translate_ko_to_ja
title_r = translate_ko_to_ja(src_title, 'ニュース見出しの忠実翻訳。意味を変えない。煽らない。')
body_r = translate_ko_to_ja(prompt, 'K-POP速報記事の翻訳・要約。ソースにない情報は絶対に追加しない')
```
チェック: `title_r['translated']` にハングル `[가-힯]` が残ってないこと (popup_publisher で同じ事故あり)。

### Stage 7 — unified_publish (pre_publish_gate 自動通過)
```python
from lib.unified_publisher import unified_publish
r = unified_publish(
    raw_title=title, body_html=body, source_url=url,
    artist=artist, kind='breaking', confidence='high',
    source_signals=[{'url': url, 'title': src_title, 'trusted': True}],
    is_breaking=True,
)
```
失敗時: `❌ Gate BLOCK: <reasons>` で STOP。BLOCK 内容 (no_source_no_signal / codeblock / portrait_thumb 等) を user に報告。

### Stage 8 — stage 記録
```python
from pipeline.breaking_news_detector import _mark_breaking_stage
_mark_breaking_stage(post_id, 1)
```

### Stage 9 — post_publish_hook (4項目 audit + draft化判定)
```python
from lib.post_publish_hook import run_post_publish
hook_r = run_post_publish(post_id)
```
ここで draft化されたら、その理由 (`hook_r['issues']`) を必ず報告。**draft化 = 失敗ではないが「公開状態でない」を明示する**。
hook 内で自動的に x_post_queue から該当 pid 除去される (本日修正済)。

### Stage 10 — 4項目 audit 揃ったか確認
```bash
grep "\"post_id\": <PID>," logs/audit_steps.jsonl
```
4 step (`structure`/`thumbnail`/`factcheck`/`body_read`) 全entry揃っていなければ手動補完するか、cron `audit_steps_enforcer` (15分間隔) に任せる。

## 完了報告フォーマット

```
✅ pid=<PID> status=<publish|draft> kind=breaking
  source: <url>
  title:  <translated_title>
  audit:  structure=<ok|warn|miss> thumbnail=<ok|miss> factcheck=<ok|warn|miss> body_read=<ok|miss>
  hook:   <pass|draft (理由)>
  url:    https://www.kpopjournal.tokyo/<slug>/
```

部分報告禁止 (CLAUDE.md procedural)。Stage 1-10 全完了+結果記載がない限り「完了」と書くな。

## 過去事故 — これを再発したら同じ穴に落ちる

| 事故 | 原因 | 防衛 |
|---|---|---|
| post 20962 (推し活で学ぶ韓国語学習法) | DuckDuckGo一般ドメインを source_signals に積んで pre をすり抜け→post_publish_hookで BLOCK→draft化→x_queue ゴミ pid | Stage 1 信頼ドメイン判定で先に弾く |
| x_queue skip ループ (15分毎 6/7件 skip) | _draft_post() が x_queue 除去しなかった | 本日修正済 (lib/post_publish_hook.py)。Stage 9 hook が自動除去 |
| popup 縦長サムネ BLOCK 28件 | アスペクト比チェックなしでアップロード | popup_publisher.upload_image_to_wp で h>w REJECT (本日修正) — quote-article は速報サムネで unified_publisher 経由のため通常問題ないが、サムネ抽出失敗時は no_thumbnail BLOCK |
| popup ハングル残存 BLOCK | 韓国ソースタイトルを翻訳せず WP に投げた | Stage 6 翻訳後にハングル残存チェック必須 |
| sanitize ``` 残存 BLOCK 70件 | sanitize_gpt_html がコードブロックマーカー除去なし | 本日修正済 (lib/text_sanitizer.py) |

## やってはいけないこと

- **batch生成**: この skill は「1記事ずつ手動」を想定。`--max N` で複数件回したいなら breaking_news_detector cron (`*/5 * * * *`) を使う。
- **dry-run 偽装**: `dry_run=True` で動かして「✅完了」報告するな。本物 publish するか STOP するか二択。
- **失敗を成功っぽく報告**: hook で draft化されたら「draft化された」と書く。「publish ok」と書くな。
- **Stage 飛ばし**: 「Stage 3 はスキップ」「Stage 9 は手動でやって」等の手抜き禁止。10ステージ全実行してから報告。
- **trusted_signals 偽装**: signal dict に `trusted: True` を手で書き込んで pre_publish_gate を騙すな (post 20962 と同じ事故になる)。
