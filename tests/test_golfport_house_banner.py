"""GOLF PORT 自社バナー(themes/generatepress-kpop/golfport-house-banner.php)の純関数テスト。
WP 関数を最小スタブして php CLI で実行する。"""
import json
import subprocess
from pathlib import Path

PHP_FILE = Path(__file__).resolve().parents[1] / "themes/generatepress-kpop/golfport-house-banner.php"

HARNESS = r"""<?php
define('ABSPATH', '/');
function esc_attr($s){return htmlspecialchars($s, ENT_QUOTES);}
function esc_html($s){return htmlspecialchars($s, ENT_QUOTES);}
function esc_url($s){return htmlspecialchars($s, ENT_QUOTES);}
function get_option($k,$d=null){return $d;}
require %s;
$out = array();
%s
echo json_encode($out, JSON_UNESCAPED_UNICODE);
"""


def run(body):
    code = HARNESS % (json.dumps(str(PHP_FILE)), body)
    r = subprocess.run(["php", "-d", "display_errors=1"], input=code, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return json.loads(r.stdout)


def test_default_is_off_even_for_empty_or_broken_config():
    out = run("""
$out['empty']=kpop_ghb_config(array())['enabled'];
$out['broken']=kpop_ghb_config('not json')['enabled'];
$out['string_true']=kpop_ghb_config(array('enabled'=>'0'))['enabled'];
""")
    assert out == {"empty": False, "broken": False, "string_true": False}


def test_should_show_requires_allowlist_category_post_and_not_popup():
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true,'categories'=>array('kdrama')));
$base=array('is_post'=>true,'is_popup'=>false,'is_preview'=>false,'category_slugs'=>array('kdrama'));
$out['ok']=kpop_ghb_should_show($cfg,$base);
$out['other_cat']=kpop_ghb_should_show($cfg,array_merge($base,array('category_slugs'=>array('news'))));
$out['popup']=kpop_ghb_should_show($cfg,array_merge($base,array('is_popup'=>true)));
$out['not_post']=kpop_ghb_should_show($cfg,array_merge($base,array('is_post'=>false)));
$out['preview']=kpop_ghb_should_show($cfg,array_merge($base,array('is_preview'=>true)));
$empty=kpop_ghb_config(array('enabled'=>true,'categories'=>array()));
$out['empty_allowlist']=kpop_ghb_should_show($empty,$base);
""")
    assert out == {"ok": True, "other_cat": False, "popup": False, "not_post": False,
                   "preview": False, "empty_allowlist": False}


def test_url_has_spec_utm_and_no_pii():
    out = run("""
$out['a']=kpop_ghb_url(kpop_ghb_config(array('enabled'=>true,'categories'=>array('x'))));
$out['b']=kpop_ghb_url(kpop_ghb_config(array('variant'=>'b')));
$out['bad_campaign']=kpop_ghb_config(array('campaign'=>'a b&c=d'))['campaign'];
""")
    assert out["a"] == ("https://golfport.top/record?utm_source=kpopjournal&utm_medium=house_banner"
                        "&utm_campaign=golfport_202611&utm_content=article_end_free_record")
    assert "utm_content=article_end_coach" in out["b"]
    assert out["bad_campaign"] == "golfport_202611"  # 不正値は既定に戻る


def test_render_once_with_disclosure_nofollow_and_copy():
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true,'categories'=>array('x')));
$out['first']=kpop_ghb_render($cfg);
$out['second']=kpop_ghb_render($cfg);
""")
    html = out["first"]
    assert out["second"] == ""  # 二重表示防止
    assert html.count('class="kpop-ghb"') == 1
    assert "運営関連サービスのご案内" in html
    assert "ゴルフの思い出、無料で記録。" in html
    assert "ラウンド・練習・写真をひとつに。" in html
    assert "GOLF PORTを見てみる" in html
    assert 'rel="nofollow noopener"' in html
    assert "<img" not in html  # 外部画像なし
    assert "src=" not in html  # 外部JSなし
