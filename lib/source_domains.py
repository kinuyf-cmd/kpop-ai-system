"""信頼ソースドメイン共通モジュール。

config/source_domains.json を真ソースとして、本文に含まれるソースリンクの
ドメイン判定に使う regex を生成する。

利用箇所:
  - lib/post_publish_hook.py: 公開後 pre_publish_gate 再実行時のソース抽出
  - pipeline/llm_proofreader.py: ソース有無判定
  - pipeline/comprehensive_audit.py: ソースありの記事監査

新しい collector を cron に追加した際は config/source_domains.json に
ドメインを追加すること。これを怠ると本文に正規ソースリンクがあっても
"ソースなし" と誤判定され大量 draft 化されるリスクがある (2026-05-07事故)。
"""

import json
import re
from pathlib import Path
from functools import lru_cache

CONFIG = Path("/home/aiuser/kpop-ai-system/config/source_domains.json")


@lru_cache(maxsize=1)
def load_domains() -> tuple:
    """信頼ソースドメインのリストを返す (lru_cacheで実質キャッシュ)
    2026-05-07: trusted_global_media (billboard等) も結合
    """
    if not CONFIG.exists():
        return tuple()
    try:
        d = json.loads(CONFIG.read_text())
    except Exception:
        return tuple()
    return tuple(
        d.get("trusted_korean_media", []) +
        d.get("trusted_japan_media", []) +
        d.get("trusted_global_media", [])
    )


def source_url_regex() -> str:
    """記事本文 (HTML) から信頼ソースURLを抽出する compiled-ready regex 文字列を返す。
    使い方:
        import re
        urls = re.findall(source_url_regex(), html)

    任意のサブドメインを許容する: m.entertain.naver.com / n.news.naver.com /
    www.koreaboo.com / koreaboo.com / sports.media.daum.net など全て対応。
    各ドメインキーワードの直前は `.` または `//` (URLの先頭) を要求し、
    `notnaver.com` のような誤マッチを防ぐ。
    """
    domains = load_domains()
    if not domains:
        return r"href=\"https?://NEVER_MATCH/[^\"]+\""
    pat = "|".join(re.escape(d) for d in domains)
    # `(?:[a-z0-9-]+\.)*` で任意のサブドメイン階層 (任意回) を許容
    return r'href="(https?://(?:[a-z0-9-]+\.)*(?:' + pat + r')[^"]+)"'


def is_trusted_source(url: str) -> bool:
    """与えられたURLが信頼ソースドメインに属するか判定"""
    domains = load_domains()
    return any(d in url for d in domains)
