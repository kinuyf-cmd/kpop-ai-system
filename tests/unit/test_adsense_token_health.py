"""AdSense OAuth トークン失効の監視テスト。

背景（2026-07-31 実測）:
  refresh_token が7日で失効していた。実行日(fetched_at)ベースで
  7/17 再認証 → 7/24 まで取得OK → 7/25 から invalid_grant（= 8日目に失効）。

  同意画面は本番環境であることを owner が確認済のため「テストだから7日失効」
  ではない。真因は OAuth クライアント自体が本番化より前(2026-04-04)に
  作られたもので、7日失効の扱いが継続していること。
  → クライアントの作り直しが必要（docs/adsense_oauth_reauth_runbook.md）。

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


def test_runbook_exists_and_documents_client_recreation():
    """runbook が本丸（OAuth クライアントの作り直し）を明記していること。

    同意画面は本番環境と確認済なので、「公開ステータスを本番に」は打ち手にならない。
    """
    p = ROOT / "docs" / "adsense_oauth_reauth_runbook.md"
    assert p.exists(), "runbook が無い"
    text = p.read_text(encoding="utf-8")
    assert "クライアントを作り直す" in text, "本丸の打ち手が書かれていない"
    assert "adsense_token.json" in text, "古いトークン削除の指示が要る"
    assert "-p 2222" in text, "ssh のポート指定が抜けると owner が詰まる"
    assert "service account" in text.lower()


def test_runbook_warns_about_fetched_at_vs_date():
    """date で数えると1日ずれる罠を runbook が明記していること（実際に誤読した）。"""
    text = (ROOT / "docs" / "adsense_oauth_reauth_runbook.md").read_text(encoding="utf-8")
    assert "fetched_at" in text
    assert "対象日" in text


def test_runbook_has_fallback_when_recreation_fails():
    """クライアント作り直しでも直らない場合の次手が書かれていること。"""
    text = (ROOT / "docs" / "adsense_oauth_reauth_runbook.md").read_text(encoding="utf-8")
    assert "テストユーザー" in text
    assert "myaccount.google.com/permissions" in text


# ── 2026-08-31 追加: 空ファイル検知 ──────────────────────────────
# 2026-08-29 のディスク満杯で adsense_token.json が **0バイト**になり、
# 以降 AdSense が JSONDecodeError で取得不能になった(収益3日欠測)。
# 当時の判定は mtime だけを見ていたため、書き込みで mtime は更新されており
# 「48h以内=PASS」と鳴らなかった。**中身の妥当性まで見ないと検知できない**。
def test_0バイトのトークンをFAILとして検知する(tmp_path, monkeypatch):
    import sys
    ROOT = Path(__file__).resolve().parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import importlib
    m = importlib.import_module("tools.health.daily_health_check")

    tok = tmp_path / "adsense_token.json"
    tok.write_text("")            # 満杯で切れた状態を再現(mtimeは今)
    monkeypatch.setattr(m, "BASE", tmp_path.parent)
    (tmp_path.parent / "google_metrics").mkdir(exist_ok=True)
    real = tmp_path.parent / "google_metrics" / "adsense_token.json"
    real.write_text("")

    results = []
    m.check_adsense_token(results, {})
    levels = {k: lv for lv, k, _ in results}
    assert levels.get("adsense_token") == "FAIL", "空トークンが検知されていない"


def test_壊れたJSONのトークンも検知する(tmp_path, monkeypatch):
    import sys, importlib
    ROOT = Path(__file__).resolve().parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    m = importlib.import_module("tools.health.daily_health_check")
    (tmp_path / "google_metrics").mkdir(exist_ok=True)
    (tmp_path / "google_metrics" / "adsense_token.json").write_text('{"refresh')
    monkeypatch.setattr(m, "BASE", tmp_path)
    results = []
    m.check_adsense_token(results, {})
    levels = {k: lv for lv, k, _ in results}
    assert levels.get("adsense_token") == "FAIL"
