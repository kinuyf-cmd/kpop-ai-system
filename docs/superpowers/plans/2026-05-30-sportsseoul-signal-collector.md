# Sports Seoul 速報シグナル collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sports Seoul (스포츠서울) を速報シグナルソースに追加し、韓流芸能全般の signal を trend_signals.jsonl に収集する。

**Architecture:** 既存 `lib/collectors/<name>_collector.py` パターンを踏襲。トップページ静的HTMLから `/news/read/<id>` 記事を正規表現抽出 → K-POPゲート(is_kpop_related)OR芸能ゲート(ローカル is_entertainment)で通過 → save_signals()。collect_all_signals.py に登録し既存 collect-all cron に相乗り。source_domains.json にドメイン追加で post_publish_hook の BLOCK を回避。

**Tech Stack:** Python 3 (venv_kpi), urllib + re (korean_base 共通基盤), json

---

### Task 1: sportsseoul_collector の新規作成

**Files:**
- Create: `lib/collectors/sportsseoul_collector.py`

- [ ] **Step 1: collector 本体を書く**

```python
#!/usr/bin/env python3
"""Sports Seoul (스포츠서울) scraper

トップページ (https://www.sportsseoul.com/) が /news/read/<id> 記事リンクを
静的に出力する唯一の確実な経路 (セクションlistは全404・navはJS依存)。
収集範囲は owner 決定により韓流芸能全般:
  - K-POP は is_kpop_related で従来通り
  - K-POP 不在でも芸能語 (드라마/배우/예능/OST/한류 等) を含めば '한류' signal 化
  - スポーツ専用語 (축구/야구/배구/감독/리그/월드컵/시구 等) は除外
signal 段階の過剰収集は許容 (記事化は下流の非K-POPトピック除外フィルタ476ed0aが最終防御)。
"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import (
    fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log, clean_title,
)

# 韓流芸能ゲート (K-POP ゲートを通らなかったタイトルの second-chance)
_ENT_KW = [
    '드라마', '영화', '예능', '배우', 'ost', '한류', '넷플릭스', '디즈니+', '티빙',
    '주연', '출연', '방영', '시즌', '캐스팅', '뮤지컬', '미니시리즈', '시사회',
    '컴백', '신곡', '데뷔',  # 芸能寄りだが korean_base GENERIC と重複しても無害
]
# スポーツ記事を弾く除外語 (Sports Seoul はスポーツ紙のため必須)
_SPORTS_KW = [
    '축구', '야구', '배구', '농구', '골프', '감독', '리그', '월드컵', '시구',
    '구단', '선수', '경기', 'kbo', 'k리그', '프로야구', '대표팀', '승부',
]


def is_entertainment(title: str) -> bool:
    """K-POP 以外の韓流芸能か。芸能語を含みスポーツ語を含まない場合 True。"""
    tl = title.lower()
    if any(s in tl for s in _SPORTS_KW):
        return False
    return any(k in tl for k in _ENT_KW)


def collect():
    signals = []
    try:
        html = fetch_html('https://www.sportsseoul.com/')
    except Exception as e:
        log(f"Sports Seoul fetch error: {e}")
        return 0

    pat = r'<a[^>]+href="(/news/read/\d+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>'
    seen = set()
    for m in re.finditer(pat, html, re.DOTALL):
        path = m.group(1)
        title = clean_title(m.group(2))
        url = 'https://www.sportsseoul.com' + path
        if url in seen or len(title) < 5:
            continue
        seen.add(url)
        keywords = is_kpop_related(title)
        if not keywords:
            if is_entertainment(title):
                keywords = ['한류']
            else:
                continue
        signals.append(make_signal('sports_seoul', title, url, keywords, is_urgent(title)))
        if len(signals) >= 20:
            break

    save_signals(signals)
    log(f"Sports Seoul: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
```

- [ ] **Step 2: 構文チェック**

Run: `./venv_kpi/bin/python -m py_compile lib/collectors/sportsseoul_collector.py && echo OK`
Expected: `OK`

- [ ] **Step 3: 実データで実行し、K-POP記事がsignal化・スポーツが除外されることを確認**

Run: `./venv_kpi/bin/python lib/collectors/sportsseoul_collector.py`
Expected: `Sports Seoul: N` (N>=1)。直前に saved ログ。`축구`/`야구` 単独タイトルが signal 化していないこと(tail data/trend_signals.jsonl で source_id=sports_seoul を目視)

- [ ] **Step 4: コミット**

```bash
git add lib/collectors/sportsseoul_collector.py
git commit -m "feat(signal): Sports Seoul collector追加(韓流芸能全般ゲート)"
```

---

### Task 2: collect_all_signals.py に登録

**Files:**
- Modify: `collect_all_signals.py:24-28` (COLLECTORS リスト)

- [ ] **Step 1: COLLECTORS リストに sportsseoul を追加**

`"sportschosun", "xportsnews", "topstarnews", "wowkorea",` の行に `"sportsseoul"` を追記:

```python
COLLECTORS = [
    "soompi", "koreaboo", "allkpop", "mydaily", "osen",
    "kstyle", "koreaherald", "starnews", "newsen",
    "sportschosun", "xportsnews", "topstarnews", "wowkorea",
    "sportsseoul",
]
```

- [ ] **Step 2: collect-all 経由で sportsseoul が回ることを確認**

Run: `./venv_kpi/bin/python collect_all_signals.py 2>&1 | grep -E "sportsseoul|完了"`
Expected: `[ok] sportsseoul: N signals` と `=== collect-all 完了 ...` の行

- [ ] **Step 3: コミット**

```bash
git add collect_all_signals.py
git commit -m "feat(signal): collect-allにsportsseoul登録"
```

---

### Task 3: source_domains.json に信頼ドメイン追加

**Files:**
- Modify: `config/source_domains.json` (trusted_korean_media 配列 + _history)

- [ ] **Step 1: trusted_korean_media に sportsseoul を追加し _history に追記**

`"circlechart"` の前に `"sportsseoul",` を追加(配列順は任意・末尾近くで可)。
`_history` 末尾に追記: `/ 2026-05-30: sportsseoul 追加 (Sports Seoul collector 新設に伴う post_publish_hook BLOCK 回避)`

- [ ] **Step 2: JSON が壊れていないことを確認**

Run: `./venv_kpi/bin/python -c "import json; d=json.load(open('config/source_domains.json')); assert 'sportsseoul' in d['trusted_korean_media']; print('OK', len(d['trusted_korean_media']), 'korean domains')"`
Expected: `OK 25 korean domains`

- [ ] **Step 3: コミット**

```bash
git add config/source_domains.json
git commit -m "feat(signal): sportsseoulを信頼韓国メディアに登録"
```

---

### Task 4: 最終検証

- [ ] **Step 1: pre-push hook 相当の構文+機密チェック**

Run: `./venv_kpi/bin/python -m py_compile lib/collectors/sportsseoul_collector.py collect_all_signals.py && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

- [ ] **Step 2: signal が実際に書き込まれたか最終確認**

Run: `grep -c '"source_id": "sports_seoul"' data/trend_signals.jsonl`
Expected: 1 以上
