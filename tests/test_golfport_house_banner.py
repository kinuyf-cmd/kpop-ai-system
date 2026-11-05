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
function is_admin(){return false;} function is_feed(){return false;} function is_embed(){return false;} function is_preview(){return false;}
function is_front_page(){return $GLOBALS['FRONT'];} function is_home(){return false;}
$GLOBALS['FRONT']=false; $GLOBALS['OPT']=array();
function get_option($k,$d=null){return $GLOBALS['OPT'];}
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


def test_url_is_exactly_the_four_fixed_params():
    out = run("$out['u']=kpop_ghb_url();")
    assert out["u"] == ("https://golfport.top/record?utm_source=kpopjournal&utm_medium=house_banner"
                        "&utm_campaign=golf_record_202611&utm_content=article_footer")
    import re
    assert re.fullmatch(r"[a-z0-9_]{1,40}", out["u"].rsplit("utm_content=", 1)[1])


def test_render_once_and_spec_compliant_markup():
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true,'categories'=>array('x')));
$out['first']=kpop_ghb_render($cfg);
$out['second']=kpop_ghb_render($cfg);
""")
    import re as _re
    html = out["first"]
    assert out["second"] == ""  # 二重表示防止
    assert html.count('class="kpop-ghb"') == 1
    assert "運営関連サービスのご案内" in html
    assert "ゴルフの思い出、ひとつに。" in _re.sub(r"<[^>]+>", "", html)
    import re as _re
    assert "ラウンド・練習・写真を記録して振り返る。" in _re.sub(r"<[^>]+>", "", html)  # 句ごとのspanを除いた本文は従来と同一
    assert 'class="kpop-ghb-ph"' in html  # 句の境目で折り返す
    assert "GOLF PORTを見てみる" in html
    for banned in ("無料", "完全", "必ず", "上達する"):
        assert banned not in html, banned
    for banned in ("nofollow", "sponsored", "noreferrer", "_blank", "utm_term"):
        assert banned not in html, banned
    # 正式ロゴ: golfport.top/logo.png を無加工でWPメディアに登録した実体(md5が原本と一致・再保存/再描画/変形/色変更なし)
    assert html.count('<img class="kpop-ghb-logo" src="https://www.kpopjournal.tokyo/wp-content/uploads/2026/11/logo.png"') == 1
    assert 'alt="ゴルフポート GOLF PORT"' in html and 'width="1637" height="435"' in html  # 縦横比(1637:435)を属性で固定
    assert 'loading="lazy"' in html
    assert "<svg" not in html and "kpop-ghb-art" not in html  # 自前のイラスト/ロゴ描画なし


def test_placement_toggles_are_independent_and_back_compatible():
    out = run("""
$legacy=kpop_ghb_config(array('enabled'=>true,'categories'=>array('kdrama')));   // 公開済みの既存オプション
$out['legacy_footer']=$legacy['article_footer']; $out['legacy_top']=$legacy['top_sidebar'];
$ctx=array('is_post'=>true,'is_popup'=>false,'is_preview'=>false,'category_slugs'=>array('kdrama'));
$out['legacy_shows']=kpop_ghb_should_show($legacy,$ctx);
$off=kpop_ghb_config(array('enabled'=>true,'categories'=>array('kdrama'),'article_footer'=>false,'top_sidebar'=>true));
$out['footer_off_hides']=kpop_ghb_should_show($off,$ctx); $out['top_on']=$off['top_sidebar'];
$m=kpop_ghb_config(array('enabled'=>false,'top_sidebar'=>true,'categories'=>array('kdrama')));
$out['master_off_footer']=kpop_ghb_should_show($m,$ctx);
""")
    assert out == {"legacy_footer": True, "legacy_top": False, "legacy_shows": True,
                   "footer_off_hides": False, "top_on": True, "master_off_footer": False}


def test_top_sidebar_url_differs_only_in_utm_content():
    out = run("$out['t']=kpop_ghb_url('top_sidebar'); $out['f']=kpop_ghb_url('article_footer'); $out['bad']=kpop_ghb_url('x&y');")
    assert out["t"] == ("https://golfport.top/record?utm_source=kpopjournal&utm_medium=house_banner"
                        "&utm_campaign=golf_record_202611&utm_content=top_sidebar")
    assert out["f"].endswith("utm_content=article_footer")
    assert out["bad"].endswith("utm_content=article_footer")  # 不正な設置場所名は既定に戻る(注入不可)


def test_top_sidebar_html_only_on_front_page_and_when_enabled():
    out = run("""
$GLOBALS['OPT']=array('enabled'=>true,'top_sidebar'=>true);
$GLOBALS['FRONT']=false; $out['not_front']=kpop_ghb_top_sidebar_html();
$GLOBALS['FRONT']=true;  $out['front']=kpop_ghb_top_sidebar_html();
$out['front_again']=kpop_ghb_top_sidebar_html();   // 二重表示防止
$GLOBALS['OPT']=array('enabled'=>true,'top_sidebar'=>false); $out['off']=kpop_ghb_top_sidebar_html();
""")
    assert out["not_front"] == ""
    assert out["off"] == ""
    assert out["front_again"] == ""
    import re as _re
    h = out["front"]
    assert 'class="kpop-sidebar-box kpop-ad-slot kpop-ghb-slot"' in h  # サイドバー並べ替えの広告枠扱いを維持
    assert "kpop-ghb--square" in h and 'data-ghb-content="top_sidebar"' in h
    assert "utm_content=top_sidebar" in h and "運営関連サービス" in h
    assert "GOLF PORTを見てみる" in h
    assert "ゴルフの思い出、ひとつに。" in _re.sub(r"<[^>]+>", "", h)
    import re as _re
    assert "ラウンド・練習・写真を記録して振り返る。" in _re.sub(r"<[^>]+>", "", h)
    for banned in ("nofollow", "sponsored", "noreferrer", "_blank", "utm_term", "無料", "a8.net", "px.a8"):
        assert banned not in h, banned
    assert h.count("<script>") == 1  # イベント束縛スクリプトは1ページに1回だけ


def test_functions_php_replaces_only_the_fixed_port_slot():
    src = (PHP_FILE.parent / "functions.php").read_text(encoding="utf-8")
    assert "kpop_ghb_top_sidebar_html()" in src
    # 置換は固定枠($fixed)のみ。ローテ枠($rot)には触れない
    seg = src[src.index("function kpop_ad_top_sidebar"):src.index("add_action( 'generate_after_right_sidebar_content', 'kpop_ad_top_sidebar'")]
    assert "$fixed = '';" in seg and "$rot   = kpop_ad_rotate( 1, array( $fkey ) );" in seg


def test_event_page_allowlist_only_and_one_banner_per_page():
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true,'categories'=>array('kdrama'),'event_page'=>true,'event_page_ids'=>array(4826,21866,'999',-1,0)));
$out['ids']=$cfg['event_page_ids'];                       // int の正の値だけ残る
$c=function($id,$cats,$extra=array()){return array_merge(array('post_id'=>$id,'is_post'=>true,'is_popup'=>false,'is_preview'=>false,'category_slugs'=>$cats),$extra);};
$out['hub_news']=kpop_ghb_article_placement($cfg,$c(4826,array('news')));          // 許可リストID→カテゴリ非対象でも出る
$out['hub_live']=kpop_ghb_article_placement($cfg,$c(21866,array('live')));
$out['plain_news_mentions_mama']=kpop_ghb_article_placement($cfg,$c(26321,array('news')));  // 本文にMAMAが出るだけの一般記事は出ない
$out['kdrama_article']=kpop_ghb_article_placement($cfg,$c(22640,array('kdrama')));
$out['event_wins_over_footer']=kpop_ghb_article_placement($cfg,$c(21866,array('kdrama','live')));  // 両方該当→event_pageだけ(1枠)
$out['popup']=kpop_ghb_article_placement($cfg,$c(4826,array('popup'),array('is_popup'=>true)));
$out['preview']=kpop_ghb_article_placement($cfg,$c(4826,array('news'),array('is_preview'=>true)));
$out['not_post']=kpop_ghb_article_placement($cfg,$c(4826,array('news'),array('is_post'=>false)));
""")
    assert out["ids"] == [4826, 21866]
    assert out["hub_news"] == "event_page" and out["hub_live"] == "event_page"
    assert out["plain_news_mentions_mama"] == ""
    assert out["kdrama_article"] == "article_footer"
    assert out["event_wins_over_footer"] == "event_page"
    assert out["popup"] == "" and out["preview"] == "" and out["not_post"] == ""


def test_event_page_toggle_master_and_legacy_options():
    out = run("""
$c=array('post_id'=>4826,'is_post'=>true,'is_popup'=>false,'is_preview'=>false,'category_slugs'=>array('news'));
$legacy=kpop_ghb_config(array('enabled'=>true,'categories'=>array('kdrama'),'article_footer'=>true,'top_sidebar'=>true)); // 公開中の既存オプション形
$out['legacy_event_off']=$legacy['event_page']; $out['legacy_hub']=kpop_ghb_article_placement($legacy,$c);
$off=kpop_ghb_config(array('enabled'=>true,'event_page'=>false,'event_page_ids'=>array(4826)));
$out['event_off']=kpop_ghb_article_placement($off,$c);
$m=kpop_ghb_config(array('enabled'=>false,'event_page'=>true,'event_page_ids'=>array(4826)));
$out['master_off']=kpop_ghb_article_placement($m,$c);
$only_event=kpop_ghb_config(array('enabled'=>true,'article_footer'=>false,'event_page'=>true,'event_page_ids'=>array(4826),'categories'=>array('news')));
$out['footer_off_event_on']=kpop_ghb_article_placement($only_event,$c);   // 記事末尾OFFでもeventは独立して出る
$out['footer_off_plain_news']=kpop_ghb_article_placement($only_event,array_merge($c,array('post_id'=>1)));
""")
    assert out == {"legacy_event_off": False, "legacy_hub": "", "event_off": "",
                   "master_off": "", "footer_off_event_on": "event_page", "footer_off_plain_news": ""}


def test_event_page_url_and_render():
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true,'event_page'=>true,'event_page_ids'=>array(4826)));
$out['u']=kpop_ghb_url('event_page');
$out['h']=kpop_ghb_render($cfg,'event_page');
$out['h2']=kpop_ghb_render($cfg,'event_page');
""")
    assert out["u"] == ("https://golfport.top/record?utm_source=kpopjournal&utm_medium=house_banner"
                        "&utm_campaign=golf_record_202611&utm_content=event_page")
    assert out["h2"] == ""
    h = out["h"]
    assert 'data-ghb-content="event_page"' in h and "utm_content=event_page" in h
    assert '<aside class="kpop-ghb"' in h  # イベントページは横長(記事末尾と同形・squareクラスは付かない)
    for banned in ("nofollow", "sponsored", "noreferrer", "_blank", "utm_term", "無料"):
        assert banned not in h, banned


def test_brand_rules_colors_and_no_logo_transforms():
    """GOLF PORT ブランド規定(5e/be 2026-11-05): ロゴは変形・色変更なし/背景は白か淡色の無地/ロゴ識別色#5064FAとサイトの青をGOLF PORTの色として持ち込まない。"""
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true));
$out['footer']=kpop_ghb_render($cfg,'article_footer');
""")
    h = out["footer"].lower()
    css = h[h.index("<style>"):h.index("</style>")]
    assert "#5064fa" not in h                                   # ロゴ専用色をUIに使わない
    for green in ("#1d6b3f", "#e8f5ec", "#f6fbf8"):             # 旧グリーン案の残骸なし
        assert green not in h, green
    # ロゴ(.kpop-ghb-logo)の規則に変形・フィルタ・色変更・切り抜きを入れない
    import re as _re
    logo_rules = " ".join(_re.findall(r"[^{}]*kpop-ghb-logo[^{}]*\{[^}]*\}", css))
    for banned in ("transform", "filter", "object-fit", "opacity", "clip", "mix-blend", "rotate", "scale", "border-radius", "mask"):
        assert banned not in logo_rules, banned
    assert "height:30px;width:auto" in css                      # 高さ固定・幅auto=縦横比保持
    assert "align-self:flex-start" in css and "align-self:center" in css  # 縦組みflexで引き伸ばされない
    # 背景は白/淡色の無地(グラデーション・画像なし)・余白はロゴ高さ(30px)の半分(15px)以上
    assert "background:#f8fafc" in css and "gradient" not in css and "url(" not in css
    assert "padding:20px" in css                                # >=15px
    assert "background:#2563eb" in css                          # CTA=K-POP JOURNALのサイト色(GOLF PORTのブランド色としては扱わない)


def test_square_uses_official_icon_and_horizontal_uses_logo_with_ratio_locked():
    out = run("""
$cfg=kpop_ghb_config(array('enabled'=>true));
$out['sq']=kpop_ghb_render($cfg,'top_sidebar'); $out['hz']=kpop_ghb_render($cfg,'event_page');
""")
    sq, hz = out["sq"], out["hz"]
    assert '<img class="kpop-ghb-icon" src="https://www.kpopjournal.tokyo/wp-content/uploads/2026/11/icon.png"' in sq
    assert 'width="512" height="512"' in sq and "kpop-ghb-logo\" src" not in sq   # 1:1は正方形のアイコン
    assert '<img class="kpop-ghb-logo"' in hz and 'width="1637" height="435"' in hz and "kpop-ghb-icon\" src" not in hz
    css = sq[sq.index("<style>"):sq.index("</style>")]
    assert "width:72px;height:72px" in css                      # 正方形のまま(引き伸ばさない)
    assert "padding:36px 20px 24px" in css                      # アイコン高さ72pxの半分(36px)以上の上余白
    icon_rules = " ".join(__import__("re").findall(r"[^{}]*kpop-ghb-icon[^{}]*\{[^}]*\}", css))
    for banned in ("transform", "filter", "object-fit", "opacity", "clip", "border-radius", "mask", "rotate", "scale"):
        assert banned not in icon_rules, banned


def test_logo_min_height_and_brand_color_notes():
    """be規定: ロゴの高さ30pxが最小(これより小さくしない)。CTAの#2563ebはK-POP JOURNALのサイト色でGOLF PORTのブランド色ではない(READMEに明記)。"""
    import re as _re
    out = run("""$cfg=kpop_ghb_config(array('enabled'=>true)); $out['h']=kpop_ghb_render($cfg,'article_footer');""")
    css = out["h"][out["h"].index("<style>"):out["h"].index("</style>")]
    heights = [int(v) for v in _re.findall(r"\.kpop-ghb-logo\{[^}]*?height:(\d+)px", css)]
    assert heights and min(heights) >= 30, heights              # ロゴの高さは30px以上
    readme = (PHP_FILE.parents[2] / "docs/golfport_banner_brand/README.md").read_text(encoding="utf-8")
    assert "GOLF PORT のブランド色ではない" in readme and "ロゴの高さ 30px が下限" in readme
