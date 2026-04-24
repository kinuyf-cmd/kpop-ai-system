"""growth_exclude.py — 成長パイプライン共通の除外判定

rewriter / cta_ab / cv_article が共通で参照する URL 除外ロジック。
config/growth_exclude_urls.json を読んで slug / パターンで弾く。
"""
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse

_BASE = Path(__file__).resolve().parent.parent
_CONFIG = _BASE / "config" / "growth_exclude_urls.json"
_CACHE: dict | None = None


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            _CACHE = {"exclude_slugs": [], "exclude_url_patterns": []}
    return _CACHE


def is_excluded(url: str) -> tuple[bool, str]:
    """URL が除外対象なら (True, 理由)。そうでなければ (False, "")"""
    cfg = _load()

    for pat in cfg.get("exclude_url_patterns", []):
        if pat in url:
            return True, f"url_pattern:{pat}"

    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return False, ""

    if not path:
        return True, "home"
    if "/" in path:
        # 2階層以上はカテゴリ/アーカイブ等の可能性
        head = path.split("/", 1)[0]
        if head in cfg.get("exclude_slugs", []):
            return True, f"slug_prefix:{head}"
        return False, ""

    if path in cfg.get("exclude_slugs", []):
        return True, f"slug:{path}"

    return False, ""


if __name__ == "__main__":
    import sys
    for u in sys.argv[1:]:
        hit, reason = is_excluded(u)
        print(f"{'EXCLUDE' if hit else 'OK     '} {u}  {reason}")
