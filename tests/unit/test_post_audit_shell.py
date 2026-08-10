"""N-2 ユニットテスト: post_audit.sh

post_audit.sh は Bash スクリプトだが、TEST MODE で標準入力から
モック投稿を渡すことができる。ここでは subprocess で起動し、
exit code と stdout の重大度分類を検証する。

注: post_audit.sh は実 stg WP API に問い合わせる箇所があるため、
TEST MODE か HEALTH_CHECK_ONLY で起動。これが不可能な場合は skip。
"""
import json
import os
import subprocess
import tempfile
import pytest
from pathlib import Path


POST_AUDIT = Path(__file__).resolve().parents[2] / "post_audit.sh"


# ─── 3ペルソナ・ゲート（C-4）テスト用ヘルパ ──────────────────────────────
# Layer3 独自記事の本文を組み立てる。persona フラグで各視点の signal を制御。
def _persona_body(beginner=True, fan=True, search=True):
    para = (
        "韓国のカフェ文化は年々進化しており、季節限定メニューや地域ごとの特色が楽しめます。"
        "旅行者にとっては休憩の場であると同時に、その土地の雰囲気を味わえる体験の場になります。"
        "店ごとに看板メニューが異なるため、訪れる前に下調べをしておくと効率よく回れます。"
        "周辺の観光地と合わせて巡れば一日を有意義に使えますし、夜まで営業する店もあります。"
    ) * 4
    h = []
    h.append("<h1>韓国ソウルのカフェ案内2026年版</h1>")
    h.append(f"<p>ソウルのカフェ巡りを紹介します。{para}</p>")
    # ① 初心者向け説明
    if beginner:
        h.append(f"<h2>そもそも韓国カフェ文化とは?入門解説</h2><p>初心者の方向けに基礎から説明します。{para}</p>")
    else:
        h.append(f"<h2>店内の雰囲気について</h2><p>落ち着いた空間が広がります。{para}</p>")
    # ③ 検索意図への結論
    if search:
        h.append(f"<h2>エリア別おすすめカフェの比較と行き方</h2><p>料金とアクセスを比較しランキングで紹介します。{para}</p>")
    else:
        h.append(f"<h2>滞在中の過ごし方</h2><p>ゆったりとした時間を過ごせます。{para}</p>")
    # ② ファン向け深掘り（固有グループ名 + ファン文脈語）
    if fan:
        h.append(f"<h2>BTS・NewJeansゆかりの聖地カフェ</h2><p>推しのメンバーゆかりの店をファン目線で深掘りします。グッズ展示も。{para}</p>")
    else:
        h.append(f"<h2>持ち物と注意点</h2><p>歩きやすい靴を用意しましょう。{para}</p>")
    return "\n".join(h)


def _mock_post_json(cat_slug, *, beginner=True, fan=True, search=True):
    return {
        "id": 99999, "status": "publish", "slug": "seoul-cafe-guide-2026",
        "title": {"raw": "韓国ソウルのカフェ案内2026年版"},
        "content": {"raw": _persona_body(beginner, fan, search)},
        "featured_media": 0, "categories": [], "categories_slug": [cat_slug],
        "tags": [101, 102],
        "meta": {"_aioseo_description": (
            "ソウルのおすすめカフェを初心者向けに基礎から徹底解説します。弘大や聖水洞や漢南洞などのエリア別に"
            "行き方と料金をわかりやすく比較し、初めての韓国旅行でも迷わず巡れる人気の名店を厳選してまとめた完全ガイドです。注意点も網羅。"
        )},
    }


def _run_audit(post_json):
    """post_audit.sh を TEST MODE で起動し (returncode, stdout) を返す。"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(post_json, f, ensure_ascii=False)
        path = f.name
    try:
        env = dict(os.environ)
        env.update({
            "KPOP_AUDIT_TEST_MODE": "1",
            "KPOP_AUDIT_TEST_POST_JSON_FILE": path,
            "KPOP_AUDIT_TEST_HTTP_STATUS": "200",
        })
        r = subprocess.run(
            ["bash", str(POST_AUDIT), "99999", "https://example.test/x", "韓国ソウルのカフェ案内2026年版", "pytest"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        return r.returncode, r.stdout + r.stderr
    finally:
        os.unlink(path)


@pytest.mark.skipif(not POST_AUDIT.exists(), reason="post_audit.sh not present")
class TestPostAuditShell:
    def test_script_is_executable(self):
        """post_audit.sh は chmod +x されていて、bash で読める"""
        assert POST_AUDIT.exists()
        assert os.access(POST_AUDIT, os.R_OK)

    def test_script_syntax_valid(self):
        """bash -n でシンタックスチェック(実行はしない)"""
        result = subprocess.run(
            ["bash", "-n", str(POST_AUDIT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"syntax error: {result.stderr}"

    def test_severity_keywords_present(self):
        """4段階重大度(CRITICAL/HIGH/MEDIUM/LOW)が定義されている"""
        text = POST_AUDIT.read_text(encoding="utf-8", errors="replace")
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            assert sev in text, f"severity '{sev}' missing"

    def test_critical_min_chars_check(self):
        """本文 3000字未満 → CRITICAL 判定のロジックが存在する"""
        text = POST_AUDIT.read_text(encoding="utf-8", errors="replace")
        assert "3000" in text and "CONTENT_LEN" in text


# ─── C-4: 3ペルソナ・ゲートのユニットテスト ──────────────────────────────
# skill はプロジェクト配下 .claude/skills/ が正本(旧: ~/.claude/skills/)
SKILL_FILE = (
    Path(__file__).resolve().parents[2]
    / ".claude" / "skills" / "kpop-original-article" / "SKILL.md"
)


@pytest.mark.skipif(not POST_AUDIT.exists(), reason="post_audit.sh not present")
class TestThreePersonaGate:
    """C-4「3ペルソナ視点 必須化」: post_audit.sh [14b] 3ペルソナ・ゲート"""

    def test_gate_block_present_in_script(self):
        """post_audit.sh に [14b] 3ペルソナ・ゲートのロジックが存在する"""
        text = POST_AUDIT.read_text(encoding="utf-8", errors="replace")
        assert "[14b]" in text
        assert "3ペルソナ" in text
        # Layer3 限定で発火する（引用記事=L1/L2 は対象外）
        assert 'CITE_LAYER:-1}" == "3"' in text or 'CITE_LAYER" == "3"' in text

    def test_original_article_skill_exists(self):
        """kpop-original-article skill が存在し、3ペルソナと C-4 を明記している"""
        assert SKILL_FILE.exists(), f"skill missing: {SKILL_FILE}"
        body = SKILL_FILE.read_text(encoding="utf-8", errors="replace")
        assert "3ペルソナ" in body
        assert "C-4" in body

    def test_layer3_missing_persona_is_hard_fail(self):
        """Layer3 でファン視点(②)が欠落 → CRITICAL(HARD_FAIL) かつ exit 2"""
        rc, out = _run_audit(_mock_post_json("travel", fan=False))
        assert "3ペルソナ" in out
        assert "3ペルソナ・ゲート不成立" in out, out[-1500:]
        assert rc == 2, f"expected HARD_FAIL exit 2, got {rc}\n{out[-1500:]}"

    def test_layer3_all_personas_passes_gate(self):
        """Layer3 で3ペルソナ揃い → ゲート PASS、persona 起因の CRITICAL なし"""
        rc, out = _run_audit(_mock_post_json("travel", beginner=True, fan=True, search=True))
        assert "3ペルソナ・ゲート PASS" in out, out[-1500:]
        assert "3ペルソナ・ゲート不成立" not in out

    def test_layer1_citation_skips_gate(self):
        """Layer1 引用記事(news)は 3ペルソナ・ゲートの対象外でスキップされる"""
        rc, out = _run_audit(_mock_post_json("news", fan=False))
        assert "3ペルソナ・ゲートは対象外" in out, out[-1500:]
        # ファン視点を欠いても citation 記事は persona 起因では落ちない
        assert "3ペルソナ・ゲート不成立" not in out
