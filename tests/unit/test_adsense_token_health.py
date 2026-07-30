"""AdSense OAuth トークン失効の監視テスト。

背景（2026-07-31 実測）:
  refresh_token が7日周期で失効していた（7/17 再認証 → 7/21 まで取得OK →
  7/22 から invalid_grant）。OAuth 同意画面の公開ステータスが「テスト」の
  場合の Google 側挙動。

  従来は metrics 取得時に WARN が出るだけで health_check の項目になく、
  収益データが7日以上欠測しても気付けなかった。

  なお実際に refresh を試す実装にはしない。同一 client_id × アカウントの
  refresh_token には発行数上限(~100)があり、無用なフロー実行が自己失効を
  誘発するため、ローカルの mtime だけで判定する。
"""
import datetime
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "daily_health_check", ROOT / "tools" / "health" / "daily_health_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dhc = _load()


@pytest.fixture
def fake_base(tmp_path, monkeypatch):
    (tmp_path / "google_metrics").mkdir()
    monkeypatch.setattr(dhc, "BASE", tmp_path)
    return tmp_path


def _write_token(base, age_hours):
    p = base / "google_metrics" / "adsense_token.json"
    p.write_text('{"token": "x"}', encoding="utf-8")
    ts = datetime.datetime.now().timestamp() - age_hours * 3600
    os.utime(p, (ts, ts))
    return p


def test_fresh_token_passes(fake_base):
    _write_token(fake_base, age_hours=2)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert results[0][0] == "PASS"
    assert results[0][1] == "adsense_token"


def test_stale_token_warns(fake_base):
    """cron が毎朝 refresh するので 48h 超の未更新は失効を意味する。"""
    _write_token(fake_base, age_hours=72)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert results[0][0] == "WARN"
    assert "更新されていない" in results[0][2]


def test_warn_points_to_runbook(fake_base):
    """owner がすぐ復旧手順に辿れること。"""
    _write_token(fake_base, age_hours=200)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert "adsense_oauth_reauth_runbook.md" in results[0][2]


def test_seven_day_expiry_is_detected(fake_base):
    """実測された7日周期の失効を確実に拾う（これを見逃していた）。"""
    _write_token(fake_base, age_hours=7 * 24)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert results[0][0] == "WARN"
    assert digest["adsense_token_age_h"] == pytest.approx(168, abs=1)


def test_missing_token_warns(fake_base):
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert results[0][0] == "WARN"
    assert "存在しない" in results[0][2]


def test_boundary_just_under_48h_passes(fake_base):
    _write_token(fake_base, age_hours=47)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert results[0][0] == "PASS"


def test_digest_records_age(fake_base):
    _write_token(fake_base, age_hours=10)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)
    assert digest["adsense_token_age_h"] == pytest.approx(10, abs=0.5)


def test_does_not_perform_network_refresh(fake_base, monkeypatch):
    """発行数上限(~100)を消費しないよう、実 refresh は行わない。"""
    def boom(*a, **k):
        raise AssertionError("ネットワーク経由の refresh を実行してはいけない")

    monkeypatch.setattr(dhc, "build", boom, raising=False)
    _write_token(fake_base, age_hours=200)
    results, digest = [], {}
    dhc.check_adsense_token(results, digest)  # 例外が出なければOK
    assert results[0][0] == "WARN"


def test_runbook_exists_and_documents_publishing_status():
    """runbook が本丸（公開ステータスを本番にする）を明記していること。"""
    p = ROOT / "docs" / "adsense_oauth_reauth_runbook.md"
    assert p.exists(), "runbook が無い"
    text = p.read_text(encoding="utf-8")
    assert "本番" in text
    assert "-p 2222" in text, "ssh のポート指定が抜けると owner が詰まる"
    assert "service account" in text.lower()
