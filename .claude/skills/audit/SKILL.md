---
name: audit
description: KpopJournal の記事を CLAUDE.md procedural 規定の4項目セット (structure + thumbnail visual + factcheck + body_read) で監査し、logs/audit_steps.jsonl に記録する。1項目だけの部分監査は禁止。Use when the user asks "監査して", "audit", "チェック", "確認" with a post_id or post URL, or invokes /audit <post_id>.
---

# audit — 4項目セット監査

CLAUDE.md procedural の最重要規定:

> ユーザーが「監査」「audit」「チェック」「確認」を依頼した時、以下を完全にこの順番で実行してから初回報告すること。途中報告禁止。
>
> 1. structure: full_audit_runner.py 等のscriptを走らせる
> 2. thumbnail: 対象記事のサムネを Read ツールで全件目視
> 3. factcheck: llm_proofreader を新規実行 (cache依存禁止、新規jsonが logs/llm_audit/ に書き出されることを確認)
> 4. body_read: 各記事の本文を読み、関連リンク混入/HTML entity残存/slug年度不整合/タイトル乖離を確認

**1だけで報告するのは規約違反** (2026-05-10事故の再発防止)。

## 入力
ユーザーが指定する post_id (1件 or 複数件) または「直近X時間の投稿」指定。
ID不在で「監査して」だけ言われたら最近12時間の post をデフォルトで全件対象 (`fetch_posts`)。

## 実行手順 — 4 step全完了するまで報告禁止

### Stage 1 — structure 監査
```python
from lib.full_audit_engine import full_audit, fetch_posts
from lib.audit_steps_log import record_step

# 単一pidなら WP API で fetch、複数なら fetch_posts
# 各 post に full_audit を実行
for p in posts:
    issues = full_audit(p, post_type='post')  # or 'popup'
    struct_issues = [i for i in issues if i.get('type') in {
        'unclosed_p', 'unclosed_h2', 'unclosed_h3', 'title_too_long',
        'title_too_short', 'slug_too_long', 'content_short', 'low_jp_ratio',
    }]
    status = 'error' if any(i.get('severity') == 'high' for i in struct_issues) else \
             ('warn' if struct_issues else 'ok')
    record_step(p['id'], 'structure', status,
                detail=f'struct_issues={len(struct_issues)}',
                source='audit_skill')
```

CRITICAL/HIGH 出た記事は Stage 4 で **必ず本文を Read で開いて確認**。

### Stage 2 — thumbnail 目視
**サイズ・alt・スコアの数値だけで PASS 判定するのは「目視」ではない** (CLAUDE.md規定)。

```python
# 1. WP API で featured_media取得
import urllib.request, json, base64, os
auth = base64.b64encode(f"{os.getenv('WP_USER')}:{os.getenv('WP_PASS')}".encode()).decode()
for p in posts:
    fm = p.get('featured_media', 0)
    if not fm:
        record_step(p['id'], 'thumbnail', 'error', detail='no featured_media', source='audit_skill')
        continue
    # 2. media 詳細取得
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{fm}",
        headers={'Authorization': f'Basic {auth}'})
    media = json.loads(urllib.request.urlopen(req, timeout=10).read())
    src_url = media.get('source_url', '')
    alt = media.get('alt_text', '')
    # 3. ローカルにダウンロード
    img_data = urllib.request.urlopen(src_url, timeout=15).read()
    tmp_path = f'/tmp/audit_thumb_{p["id"]}.jpg'
    with open(tmp_path, 'wb') as f:
        f.write(img_data)
    # 4. Read ツールで画像を開いて目視 (Claude が画像を実際に見る)
```
→ ここで Read ツールを必ず呼ぶ。「ファイルサイズ XX KB だから OK」は目視ではない。

確認項目 (画像を見て判断):
- 記事タイトルとアーティスト一致しているか
- 縦長 (h>w) ではないか
- 顔がちゃんと写っているか / 別アーティスト混入していないか
- alt が空でないか / 記事内容と整合しているか
- letterbox/blur padding になっていないか

```python
record_step(p['id'], 'thumbnail', status, detail=visual_finding, source='audit_skill')
```

### Stage 3 — factcheck (llm_proofreader 新規実行)
**cache依存禁止**。`_already_proofread(pid)` が True 返しても force で再実行。

```python
from pipeline.llm_proofreader import proofread_post
import os, json
from datetime import datetime
# 単一post向け: proofread_post を直接呼ぶ
r = proofread_post(post)
# 新規 json が logs/llm_audit/ に書き出されることを確認
audit_dir = '/home/aiuser/kpop-ai-system/logs/llm_audit/'
ts_now = datetime.now()
new_json = f'{audit_dir}{ts_now.strftime("%Y%m%d_%H")}_skill_pid{p["id"]}.json'
with open(new_json, 'w', encoding='utf-8') as f:
    json.dump({'pid': p['id'], 'result': r, 'ts': ts_now.isoformat()}, f, ensure_ascii=False, indent=2)

crit = len(r.get('critical', []))
high = len(r.get('high', []))
status = 'error' if crit else ('warn' if high else 'ok')
record_step(p['id'], 'factcheck', status,
            detail=f'critical={crit} high={high}',
            source='audit_skill')
```

**HIGH/CRITICAL があれば Stage 4 で必ず本文 Read** (memory: feedback_audit_read_content)。

### Stage 4 — body_read (本文精読)

各記事の本文を Read ツールで読み、以下4観点で確認:

1. **関連リンク混入**: 関連記事ブロックが本文中段に潜り込んでいないか (`related_inline_dup`)
2. **HTML entity残存**: `&amp;` `&#038;` `&hellip;` 等が rendered状態で残っていないか
3. **slug年度不整合**: slug に 2024 等古い年が含まれているのに本文は最新年を扱っているか / 逆も
4. **タイトル乖離**: タイトルが本文内容と乖離していないか (memory: feedback_title_faithful_translation)

```python
# WP API で本文+slug取得
req = urllib.request.Request(
    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}?context=edit",
    headers={'Authorization': f'Basic {auth}'})
post_full = json.loads(urllib.request.urlopen(req, timeout=10).read())
title = post_full['title']['rendered']
slug = post_full['slug']
content = post_full['content']['rendered']
# Read ツールで /tmp に書いて開く or 直接プレーンテキスト化して目視
issues_found = []
import re as _re
# entity 検出
if _re.search(r'&[a-z]+;|&#\d+;', content):
    issues_found.append('html_entity_undecoded')
# slug年度
m = _re.search(r'(20\d\d)', slug)
if m and int(m.group(1)) < 2025:
    issues_found.append(f'stale_slug_year={m.group(1)}')
# 関連リンク混入 (本文中の <h3>関連記事</h3> 等)
if _re.search(r'<h[23][^>]*>関連記事</h[23]>', content[:len(content)//2]):
    issues_found.append('related_block_inline')
# タイトル乖離: タイトル中の固有名詞が本文に出現するか
title_keywords = [w for w in _re.findall(r'[A-Z][A-Za-z]+|[一-鿿]{2,}', title) if len(w) >= 2]
plain = _re.sub(r'<[^>]+>', '', content)
missing = [w for w in title_keywords if w not in plain]
if missing:
    issues_found.append(f'title_drift_missing={missing[:3]}')

status = 'error' if issues_found else 'ok'
record_step(pid, 'body_read', status, detail=','.join(issues_found) or 'clean', source='audit_skill')
```

## 完了報告フォーマット

```
=== 4項目監査結果 (N件) ===
| pid   | structure | thumbnail | factcheck | body_read | サマリ                       |
|-------|-----------|-----------|-----------|-----------|------------------------------|
| 21006 | warn (1)  | ok        | ok        | ok        | unclosed_p修正済              |
| 20982 | ok        | warn      | error (2) | error     | factcheck CRITICAL: 固有名詞捏造 |
...

CRITICAL/HIGH があった記事の本文 Read 結果:
- pid=20982: <本文Read で確認した内容>
```

部分報告禁止。4 step全実行+結果記載がない限り「完了」と書くな。

## 過去事故 — これを再発したら同じ穴に落ちる

| 事故日 | 内容 | 教訓 |
|---|---|---|
| 2026-05-10 | 「12時間以内の投稿の監査して」要求にscriptで2件報告 → ユーザー指摘で残り3項目実行 → CRITICAL含む追加6件発覚 | scriptが回ったこと ≠ 監査が完了したこと。4項目セット必須 |
| 過去多数 | factcheck cache に当たって `_already_proofread=True` で skip → factcheckしてないのに「PASS」報告 | Stage 3 で必ず新規 proofread_post 実行、cache無視 |
| 過去多数 | サムネサイズだけ見て「OGP表示OK」報告 → 実は別アーティスト混入 | Stage 2 で Read ツールで画像を実際に見る |

## やってはいけないこと

- **structure script だけ走らせて「監査PASS」報告**: 4項目全実行するまで報告禁止
- **factcheck cache 流用**: `_already_proofread` skip された pid は factcheck していない=報告に含めるな
- **数値だけのサムネ判定**: 「480x720 px、容量 50KB だから OK」は目視ではない
- **CRITICAL を本文 Read せず報告**: HIGH/CRITICAL 出たら必ず本文 Read で原因確認
- **完了の偽装**: logs/audit_steps.jsonl に4 step entry揃ってないなら「完了」と書くな
- **失敗を成功っぽく報告**: thumbnail 不在を「N/A」で逃げるな。`error: no featured_media` と書け
