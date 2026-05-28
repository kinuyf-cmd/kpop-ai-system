"""factcheck v2 — Claude Sonnet 4.6 + Web search + Prompt caching + Structured outputs

llm_proofreader.proofread_post() の Claude版。OpenAI gpt-4o-mini代替。

機能:
- Web search tool (server-side) で外部ファクトチェック (Tavily不要)
- Prompt caching で K-pop知識prefix を90%コスト削減
- Structured outputs でJSON parse失敗ゼロ
- メンバー人数/所属事務所/デビュー年の誤りを web search で実証

Usage:
    from lib.factcheck_v2 import proofread_post_v2
    result = proofread_post_v2(post)  # post: {'id', 'title', 'content'}
    # → {'score': 0-100, 'critical': [...], 'high': [...], 'medium': [...]}

統合方法:
    proofread_post() で env flag FACTCHECK_V2=1 のとき呼び出し
"""
from __future__ import annotations
import os
import json
import re
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

LOG_PATH = Path('/home/aiuser/kpop-ai-system/logs/factcheck_v2.jsonl')
CACHE_PATH = Path('/home/aiuser/kpop-ai-system/data/factcheck_v2_cache.json')
# 2026-05-12 (Phase 2 コスト削減): 6h → 30日 に拡張。
# factcheck 結果は content (title+本文) が同じなら同じ判定が返るため、本文修正されない
# 限り再評価する必要はない。これで pre_publish_gate → post_publish_hook → audit cron 群
# の重複呼出しを恒久遮断 (品質完全同一)。
CACHE_TTL_SEC = 30 * 86400  # 30 days

# 2026-05-13 (Phase 8 コスト削減): pid 軸 24h dedup を追加。
# enricher 等が記事本文を後追い編集するため content_hash が変動し永続cacheが
# miss してしまう問題への対策。同じ post_id の記事を 24h 以内に再評価する場合は
# 本文の微修正を無視して前回判定を返す。24h 経過後は再評価 (大きな修正検知)。
PID_CACHE_PATH = Path('/home/aiuser/kpop-ai-system/data/factcheck_v2_pid_cache.json')
PID_CACHE_TTL_SEC = 24 * 3600  # 24h

# 2026-05-28: CTA/アフィリ注入起因の指摘はキャッシュに保存しない(再発防止)。
# 注入はpre_publish_gate(注入前評価)の後段で行われるため、ここで critical/high に
# 残っているCTA関連指摘は過去の評価対象汚染(注入後本文をLLMに渡していた時代の遺物)。
_CTA_NOISE_RE = re.compile(
    r'エアトリ|見出し風|推し活|アフィリエイトリンクが複数挿入|商業アフィリエイト|別記事の見出し|無関係な見出し|別コンテンツ'
)


def _strip_cta_noise(result: dict) -> dict:
    """result内のcritical/high/mediumからCTA注入起因のnoiseを除去して返す。"""
    if not isinstance(result, dict):
        return result
    out = dict(result)
    for level in ('critical', 'high', 'medium'):
        items = out.get(level) or []
        if items:
            out[level] = [x for x in items if not _CTA_NOISE_RE.search(str(x))]
    return out

# Prompt caching用 K-pop審査基準 (1500+ tokens, 5分TTL)
KPOP_FACTCHECK_PREFIX = """あなたはK-POP専門メディアの校閲AIです。以下のK-pop知識基盤と判定ルールに従って記事を校閲してください。

## 主要K-popグループ覚え書き
- BLACKPINK (YG, 2016年デビュー, 4人, 女性): Jisoo/Jennie/Rosé/Lisa
- aespa (SM, 2020年, 4人, 女性): Karina/Giselle/Winter/Ningning
- BTS (HYBE/Bighit, 2013年, 7人, 男性): RM/Jin/Suga/J-Hope/Jimin/V/Jungkook
- TWICE (JYP, 2015年, 9人, 女性): Nayeon/Jeongyeon/Momo/Sana/Jihyo/Mina/Dahyun/Chaeyoung/Tzuyu
- NewJeans (ADOR/HYBE, 2022年, 5人, 女性): Minji/Hanni/Danielle/Haerin/Hyein
- IVE (Starship, 2021年, 6人, 女性): Yujin/Gaeul/Rei/Wonyoung/Liz/Leeseo
- LE SSERAFIM (Source/HYBE, 2022年, 5人, 女性): Sakura/Chaewon/Yunjin/Kazuha/Eunchae
- ITZY (JYP, 2019年, 5人, 女性): Yeji/Lia/Ryujin/Chaeryeong/Yuna
- SEVENTEEN (Pledis/HYBE, 2015年, 13人, 男性)
- Stray Kids (JYP, 2018年, 8人, 男性)
- ENHYPEN (Belift/HYBE, 2020年, 7人, 男性)
- TXT/TOMORROW X TOGETHER (Bighit, 2019年, 5人, 男性)
- ATEEZ (KQ, 2018年, 8人, 男性)
- TREASURE (YG, 2020年, 10人 → 現在7人, 男性)
- NMIXX (JYP, 2022年, 6人, 女性)
- ILLIT (Belift/HYBE, 2024年, 5人, 女性)
- BABYMONSTER (YG, 2023年, 7人, 女性): Ahyeon/Pharita/Asa/Rami/Ruka/Rora/Chiquita
- BOYNEXTDOOR (KOZ/HYBE, 2023年, 6人, 男性)
- RIIZE (SM, 2023年, 7人, 男性)
- TWS (Pledis/HYBE, 2024年, 6人, 男性)
- KISS OF LIFE (S2, 2023年, 4人, 女性)

## 判定基準
- **critical**: 人名/グループ名間違い, 数値矛盾, 存在しない人物, ソース記事にない事実の追加(捏造), タイトル本文不一致(妹/姉間違い等), バラエティ番組を新曲と誤記
- **high**: 不自然な日本語, タイトルと本文の不整合, 重要事実の省略, リリース日の誤り
- **medium**: 表現の改善余地, 軽微な表記揺れ

## 絶対に問題として報告してはいけないもの (LLM proofreader 誤検知 memory rule)
- 2026年以降の日付は正常 (現在は2026年)
- 曜日と日付の整合性チェック (暦計算は不正確)
- K-POPアーティスト名の英語/韓国語/日本語表記揺れ
- カムバック/ファンミ/アンコール等のK-POPファン用語
- 「TWICE・ITZY・Stray Kids」のようなグループ列挙は「TWICEはX人」と主張していないので、メンバー数誤りとして報告してはならない
- 「JYP所属のTWICE」のような所属関係の記述は事実関係でメンバー数とは無関係
- slug/URL/メタ情報は本文の事実とは無関係

## スコア基準
- 95-100: 問題なし
- 80-94: medium問題のみ
- 60-79: high問題あり
- 60未満: critical問題あり

## 検証手順
1. タイトルと本文の整合性チェック (主語/数字/日付の一致)
2. 上記K-pop覚え書きと矛盾しないか
3. 必要なら web_search ツールで信頼メディア (soompi/allkpop/billboard/naver/newsen/starnewskorea等) で裏取り
4. 結果をJSON schemaに従って返却
"""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# Claude structured outputs はnumerical constraints (minimum/maximum)非サポート
# verified_facts は呼び出し側で参照されておらず output token を圧迫していたため削除 (2026-05-12)
_FACTCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "critical": {"type": "array", "items": {"type": "string"}},
        "high": {"type": "array", "items": {"type": "string"}},
        "medium": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "critical", "high", "medium"],
    "additionalProperties": False,
}


def _cache_key(title: str, plain: str) -> str:
    h = hashlib.sha256()
    # 2026-05-15: 強正規化 (lower + 非英数字除去) で enricher 後の link/CTA 追加や
    # punctuation/whitespace の揺れを吸収。日本語/韓国語は \w で保持される。
    norm_title = re.sub(r'\W+', '', (title or '').lower(), flags=re.UNICODE)
    norm_plain = re.sub(r'\W+', '', (plain or '').lower(), flags=re.UNICODE)
    h.update(norm_title.encode('utf-8', errors='ignore'))
    h.update(b'\x1f')
    h.update(norm_plain[:3000].encode('utf-8', errors='ignore'))
    return h.hexdigest()[:24]


def _cache_load() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _cache_get(key: str) -> dict | None:
    cache = _cache_load()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get('ts', 0) > CACHE_TTL_SEC:
        return None
    return entry.get('result')


def _cache_put(key: str, result: dict) -> None:
    try:
        cache = _cache_load()
        now = time.time()
        cache = {k: v for k, v in cache.items() if now - v.get('ts', 0) <= CACHE_TTL_SEC}
        cache[key] = {'ts': now, 'result': _strip_cta_noise(result)}
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def _pid_cache_get(pid) -> dict | None:
    """pid 軸 24h dedup cache の lookup。enricher 本文編集対策。"""
    if not pid:
        return None
    if not PID_CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(PID_CACHE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return None
    entry = cache.get(str(pid))
    if not entry:
        return None
    if time.time() - entry.get('ts', 0) > PID_CACHE_TTL_SEC:
        return None
    return entry.get('result')


def _pid_cache_put(pid, result: dict) -> None:
    if not pid:
        return
    try:
        cache = json.loads(PID_CACHE_PATH.read_text(encoding='utf-8')) if PID_CACHE_PATH.exists() else {}
    except Exception:
        cache = {}
    now = time.time()
    cache = {k: v for k, v in cache.items() if now - v.get('ts', 0) <= PID_CACHE_TTL_SEC}
    cache[str(pid)] = {'ts': now, 'result': _strip_cta_noise(result)}
    try:
        PID_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PID_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def proofread_post_v2(post: dict, use_web_search: bool = True) -> dict:
    """Claude Sonnet 4.6で記事校閲

    Args:
        post: {'id', 'title', 'content'}
        use_web_search: True ならweb_searchツール有効化 (3回まで)

    Returns:
        {'score', 'critical', 'high', 'medium'}
    """
    title = post['title']['rendered'] if isinstance(post.get('title'), dict) else post.get('title', '')
    content = post['content']['rendered'] if isinstance(post.get('content'), dict) else post.get('content', '')
    plain = re.sub(r'<[^>]+>', ' ', content)
    plain = re.sub(r'\s+', ' ', plain).strip()[:2500]
    pid = post.get('id')

    # Layer 1: pid 軸 24h dedup (enricher 本文編集対策、2026-05-13)。
    # 同じ post_id の記事を 24h 以内に再評価する場合は本文の微修正を無視。
    pid_cached = _pid_cache_get(pid)
    if pid_cached is not None:
        _log({
            'pid': pid,
            'title': title[:60],
            'score': pid_cached.get('score'),
            'critical_count': len(pid_cached.get('critical', [])),
            'high_count': len(pid_cached.get('high', [])),
            'medium_count': len(pid_cached.get('medium', [])),
            'usage': {'pid_cache_hit': True},
        })
        return pid_cached

    # Layer 2: content_hash 30日永続 cache (本文修正検知)
    ck = _cache_key(title, plain)
    cached = _cache_get(ck)
    if cached is not None:
        _pid_cache_put(pid, cached)
        _log({
            'pid': pid,
            'title': title[:60],
            'score': cached.get('score'),
            'critical_count': len(cached.get('critical', [])),
            'high_count': len(cached.get('high', [])),
            'medium_count': len(cached.get('medium', [])),
            'usage': {'cache_hit': True},
        })
        return cached

    # 2026-05-12 (Phase 6): cost guard — kill switch (ANTHROPIC_DISABLE=1) や
    # KPJ_TEST_MODE で API 呼出を skip し、安全な中立結果を返す。
    # 予算超過/rate 異常は warning のみで block しない (品質維持優先)。
    try:
        from lib.anthropic_cost_guard import guard_before_call
        if not guard_before_call('factcheck_v2'):
            return {'score': 80, 'critical': [], 'high': [], 'medium': [],
                    '_skipped': 'cost_guard'}
    except ImportError:
        pass

    today = datetime.now(timezone.utc).strftime('%Y年%m月%d日')

    # 2026-05-12 (Phase 2): lessons は system cached block 側に移動 (cache_read 0.1x で再利用)。
    # 旧実装は user_prompt 末尾に注入していたため毎回 input token として課金されていた。
    # lessons の追加は低頻度なので 1h cache TTL 内では同じ内容を返し cache hit する。
    try:
        from lib.factcheck_lessons import get_recent_lessons, format_lessons_for_prompt
        lessons = get_recent_lessons(days=30, max_count=12)
        lessons_section = format_lessons_for_prompt(lessons)
    except Exception:
        lessons_section = ''

    user_prompt = f"""今日の日付: {today}

## 校閲対象記事
【タイトル】{title}
【本文抜粋】{plain}

上記K-pop知識基盤と判定ルールに従って校閲し、JSONで返却してください。
不明な事実 (新曲名/最新リリース日等) があれば web_search ツールで信頼メディアで裏取りしてからJSON結果を返してください。
"""

    tools = []
    if use_web_search:
        tools = [{
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": 3,
        }]

    try:
        client = _get_client()
        # 2026-05-12 (Phase 2): cache_control に ttl=1h を明示。
        # default の 5min TTL は publish 散発時に頻繁に miss して cache_create 課金が
        # 発生していた (write は read の 12.5x コスト)。1h TTL は write 1.6x だが、
        # 並列racing + cron 間隔 (8h ごとの llm_proofreader) で hit 率が劇的に上がる。
        # lessons は時間窓で動的なので 2つ目の cache breakpoint として独立 cache する。
        system_blocks = [{
            "type": "text",
            "text": KPOP_FACTCHECK_PREFIX,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }]
        if lessons_section:
            system_blocks.append({
                "type": "text",
                "text": lessons_section,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            })

        # 2026-05-12 (Phase 4): artist_master.json から生成した K-POP コーパスを
        # document block で渡し、cache_control 1h で固定する。メンバー人数/デビュー日/
        # 所属事務所等の確定情報を Web Search に頼らず参照可能になり、捏造検出が
        # 決定的になる + Web Search 発火頻度をさらに削減できる。
        # 注: Citations (citations.enabled=true) は structured outputs と非互換のため
        # ここでは citations 無効で純粋な参考資料として渡す。
        try:
            from lib.factcheck_corpus import build_corpus
            corpus = build_corpus()
        except Exception:
            corpus = ''

        if corpus:
            user_content = [
                {
                    "type": "document",
                    "source": {
                        "type": "text",
                        "media_type": "text/plain",
                        "data": corpus,
                    },
                    "title": "K-POP artist master data",
                    "context": "確定済みの K-POP アーティスト基礎情報。本文と矛盾があれば指摘する根拠として使用。",
                    "citations": {"enabled": False},
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                },
                {"type": "text", "text": user_prompt},
            ]
        else:
            user_content = user_prompt

        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1500,
            system=system_blocks,
            tools=tools,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _FACTCHECK_SCHEMA,
                },
            },
            messages=[{"role": "user", "content": user_content}],
        )
        # 最初のtext blockがschema-validated JSON
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            return {'score': 50, 'critical': [], 'high': [f'schema parse err: {text[:100]}'], 'medium': []}

        # ログ
        _log({
            'pid': post.get('id'),
            'title': title[:60],
            'score': result.get('score'),
            'critical_count': len(result.get('critical', [])),
            'high_count': len(result.get('high', [])),
            'medium_count': len(result.get('medium', [])),
            'usage': {
                'input': response.usage.input_tokens,
                'output': response.usage.output_tokens,
                'cache_create': getattr(response.usage, 'cache_creation_input_tokens', 0),
                'cache_read': getattr(response.usage, 'cache_read_input_tokens', 0),
            },
        })

        # CTA注入起因のnoiseを除去してから返す&キャッシュ(2026-05-28)
        result = _strip_cta_noise(result)
        # 同一 title+content の連続呼び出しを 1回に折り畳むため結果をキャッシュ
        _cache_put(ck, result)
        # pid 軸 24h dedup にも書き込み (enricher 編集後の再factcheck を遮断)
        _pid_cache_put(pid, result)

        # 2026-05-12 (Phase 6): cost ledger に記録 (予算アラート/監視用)
        try:
            from lib.anthropic_cost_guard import log_usage
            log_usage('factcheck_v2', model='claude-sonnet-4-6', usage=response.usage)
        except Exception:
            pass

        # 自己学習: critical/high issue を lessons.jsonl に追加
        try:
            from lib.factcheck_lessons import append_lessons
            append_lessons(post.get('id', 0), title, result)
        except Exception:
            pass

        return result

    except anthropic.RateLimitError:
        return {'score': 50, 'critical': [], 'high': ['Claude rate limit'], 'medium': []}
    except anthropic.APIStatusError as e:
        return {'score': 50, 'critical': [], 'high': [f'API err {e.status_code}'], 'medium': []}
    except Exception as e:
        return {'score': 50, 'critical': [], 'high': [f'err: {type(e).__name__}'], 'medium': []}


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**entry, 'ts': datetime.now().isoformat()}, ensure_ascii=False) + '\n')
    except OSError:
        pass


if __name__ == '__main__':
    import sys
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 19623
    import urllib.request
    d = json.load(urllib.request.urlopen(f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}?_fields=id,title,content', timeout=15))
    r = proofread_post_v2(d)
    print(json.dumps(r, ensure_ascii=False, indent=2))
