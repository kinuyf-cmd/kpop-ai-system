"""段階3(DALL-E生成)再建テスト(2026-06-16)。

VPS事故で欠損した make_thumbnail_v6._dalle_fallback を再建。
契約: _dalle_fallback(title, body, post_id, output_dir, theme_dalle_prompt='')
  → 成功時 {'verdict':'PASS', 'output_path': <png>}, 失敗時 {'verdict':'FAIL', ...}
generate_thumbnail は本物のAPIを叩くため、テストでは必ずモックする(コスト0)。
"""
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lib"))


def _fake_gen_success(prompt, output_path, **kw):
    # 実ファイルを作って success を返す(呼び出し側が存在チェックする)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake")
    return {"success": True, "path": output_path, "cost_usd": 0.063, "reason": "ok"}


def _fake_gen_fail(prompt, output_path, **kw):
    return {"success": False, "path": "", "cost_usd": 0, "reason": "OPENAI_API_KEY未設定"}


class TestBuildPrompt:
    def test_prompt_is_english_editorial(self):
        import make_thumbnail_v6 as m
        p = m._build_prompt("ラブブ ポップアップ徹底ガイド", "")
        assert "K-pop" in p or "editorial" in p.lower() or "thumbnail" in p.lower()

    def test_prompt_avoids_depicting_real_people(self):
        import make_thumbnail_v6 as m
        p = m._build_prompt("BTS ジョングク 最新", "").lower()
        # 実在人物の顔を描かない指示が含まれる(肖像権/誤認回避)
        assert "no real" in p or "do not depict" in p or "without depicting" in p or "no recognizable" in p

    def test_theme_prompt_is_incorporated(self):
        import make_thumbnail_v6 as m
        p = m._build_prompt("テスト記事", "", theme_dalle_prompt="neon concert stage atmosphere")
        assert "neon concert stage atmosphere" in p


class TestDalleFallback:
    def test_success_returns_pass_and_output_path(self, tmp_path):
        import make_thumbnail_v6 as m
        with mock.patch.object(m, "generate_thumbnail", side_effect=_fake_gen_success):
            r = m._dalle_fallback("ラブブ ポップアップ", "", 9999, str(tmp_path))
        assert r["verdict"] == "PASS"
        assert r["output_path"].endswith(".png")
        assert os.path.exists(r["output_path"])

    def test_api_failure_returns_fail(self, tmp_path):
        import make_thumbnail_v6 as m
        with mock.patch.object(m, "generate_thumbnail", side_effect=_fake_gen_fail):
            r = m._dalle_fallback("テスト", "", 9999, str(tmp_path))
        assert r["verdict"] == "FAIL"

    def test_output_path_uses_post_id(self, tmp_path):
        import make_thumbnail_v6 as m
        with mock.patch.object(m, "generate_thumbnail", side_effect=_fake_gen_success):
            r = m._dalle_fallback("テスト", "", 12345, str(tmp_path))
        assert "12345" in r["output_path"]
