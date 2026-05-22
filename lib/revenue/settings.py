#!/usr/bin/env python3
"""lib/revenue/settings.py — J収益化設定ローダー。

優先順位: 環境変数(.env / OS env) > config/revenue/revenue_settings.json > 安全なデフォルト。

設計方針:
  - 未設定でも import エラーにしない(全 getter は安全なデフォルトを返す)。
  - AdSense client id / GA4 measurement id / 本番URL はここ経由でのみ取得する。
  - 配信(delivery_enabled)が False の間、各タグ生成関数は空文字を返す。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
SETTINGS_FILE = BASE / "config" / "revenue" / "revenue_settings.json"


def _load_env() -> dict:
    """`.env` を読む(python-dotenv があれば使う。無ければ OS env のみ)。"""
    env: dict = {}
    try:
        from dotenv import dotenv_values  # type: ignore
        env_path = BASE / ".env"
        if env_path.exists():
            env.update({k: v for k, v in dotenv_values(str(env_path)).items() if v})
    except Exception:
        pass
    # OS 環境変数で上書き
    env.update({k: v for k, v in os.environ.items() if v})
    return env


def load_settings() -> dict:
    """revenue_settings.json を読み込む。ファイルが無ければ空 dict。"""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


_ENV = _load_env()
_CFG = load_settings()


def _cfg(*path, default=None):
    node = _CFG
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


# ── 配信フラグ ──────────────────────────────────────────────
def delivery_enabled() -> bool:
    """env REVENUE_DELIVERY_ENABLED=1/true で強制ON、それ以外は config 値。"""
    raw = _ENV.get("REVENUE_DELIVERY_ENABLED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes", "on")
    return bool(_cfg("delivery_enabled", default=False))


# ── サイトURL ───────────────────────────────────────────────
def site_url() -> str:
    """投稿先サイトURL。

    安全側設計(誤って本番へ書き込まないため):
      - config の site.active_target が "stg"(既定)の間は、必ず stg_url を返す。
        既存 .env の SITE_URL が本番(www)を指していても、それは無視する。
      - 本番化(Phase C-7)で active_target を "production" にした時のみ、
        env SITE_URL > config.production_url を返す。
    env INJECTOR_SITE_URL を設定した場合は(明示オプトイン)それを最優先。
    """
    if _ENV.get("INJECTOR_SITE_URL"):
        return _ENV["INJECTOR_SITE_URL"].rstrip("/")
    target = _cfg("site", "active_target", default="stg")
    if target == "production":
        if _ENV.get("SITE_URL"):
            return _ENV["SITE_URL"].rstrip("/")
        return str(_cfg("site", "production_url",
                        default="https://www.kpopjournal.tokyo")).rstrip("/")
    # active_target == "stg"(既定): 本番URLへの誤爆を防ぐため stg を強制
    return str(_cfg("site", "stg_url",
                    default="https://stg.kpopjournal.tokyo")).rstrip("/")


# ── AdSense (J-1) ───────────────────────────────────────────
def adsense_client_id() -> str:
    """ca-pub-XXXX。env ADSENSE_CLIENT_ID 優先。未設定なら空文字。"""
    return (_ENV.get("ADSENSE_CLIENT_ID") or _cfg("adsense", "client_id", default="") or "").strip()


def adsense_enabled() -> bool:
    """client id があり、かつ enabled(env or config)なら True。"""
    if not adsense_client_id():
        return False
    raw = _ENV.get("ADSENSE_ENABLED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes", "on")
    return bool(_cfg("adsense", "enabled", default=False))


def adsense_auto_ads() -> bool:
    return bool(_cfg("adsense", "auto_ads", default=True))


def adsense_slot(name: str) -> str:
    return str(_cfg("adsense", "manual_slots", name, default="") or "").strip()


# ── GA4 (J-3) ───────────────────────────────────────────────
def ga4_measurement_id() -> str:
    """G-XXXX。env GA4_MEASUREMENT_ID 優先。未設定なら空文字。"""
    return (_ENV.get("GA4_MEASUREMENT_ID") or _cfg("ga4", "measurement_id", default="") or "").strip()


def ga4_property_id() -> str:
    """集計用 GA4 property id(数値)。env GA4_PROPERTY_ID 優先。"""
    env_key = _cfg("ga4", "property_id_env", default="GA4_PROPERTY_ID")
    return (_ENV.get(env_key) or _ENV.get("GA4_PROPERTY_ID") or "").strip()


# ── A8 (J-2) ────────────────────────────────────────────────
def a8_master_path() -> Path:
    return BASE / _cfg("a8", "master_file", default="config/affiliate/a8_master.json")


def a8_banners_path() -> Path:
    return BASE / _cfg("a8", "banners_file", default="cta/a8_banners.json")


def a8_genre_map_path() -> Path:
    return BASE / _cfg("a8", "genre_map_file", default="config/affiliate/cta_genre_map.json")


def a8_click_base_url() -> str:
    return str(_cfg("a8", "click_base_url", default="https://px.a8.net/svt/ejp"))


# ── CTA (J-4) ───────────────────────────────────────────────
def cta_cutoff_date() -> str:
    return str(_cfg("cta", "cutoff_date", default="2026-05-04T00:00:00"))


def cta_min_length() -> int:
    return int(_cfg("cta", "min_article_length", default=2500))


def cta_max_per_article() -> int:
    return int(_cfg("cta", "max_cta_per_article", default=3))


def summary() -> dict:
    """設定の現在値サマリ(機密値は伏せる)。CLI/デバッグ用。"""
    return {
        "delivery_enabled": delivery_enabled(),
        "site_url": site_url(),
        "adsense_client_id_set": bool(adsense_client_id()),
        "adsense_enabled": adsense_enabled(),
        "ga4_measurement_id_set": bool(ga4_measurement_id()),
        "ga4_property_id_set": bool(ga4_property_id()),
        "a8_master_exists": a8_master_path().exists(),
        "a8_banners_exists": a8_banners_path().exists(),
    }


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(summary(), ensure_ascii=False, indent=2))
