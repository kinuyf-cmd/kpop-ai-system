<?php
/**
 * widgets/sidebar_shortcodes.php — 誕生日/イベント枠をトップ等でも出すためのショートコード化。
 * 2026-05-25: 記事ページは functions.php 直呼びで表示されるが、トップは WP Custom HTML widget
 *   ベースの別サイドバーで誕生日/イベントが出ない。ショートコードでラップし、Custom HTML widget
 *   に [kpop_birthday] / [kpop_events] を貼れるようにする(WP標準・安全)。
 *   Custom HTML widget は既定でショートコード非実行のため widget_text に do_shortcode を有効化。
 * @package kpop-journal-child
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

// 既存の render 関数を出力バッファで捕捉してショートコード戻り値にする
if ( ! function_exists( 'kpop_sc_birthday' ) ) :
function kpop_sc_birthday() {
    if ( ! function_exists( 'kpop_render_today_birthday' ) ) { return ''; }
    ob_start();
    kpop_render_today_birthday();
    return ob_get_clean();
}
add_shortcode( 'kpop_birthday', 'kpop_sc_birthday' );
endif;

if ( ! function_exists( 'kpop_sc_birthday_tomorrow' ) ) :
function kpop_sc_birthday_tomorrow() {
    if ( ! function_exists( 'kpop_render_tomorrow_birthday' ) ) { return ''; }
    ob_start();
    kpop_render_tomorrow_birthday();
    return ob_get_clean();
}
add_shortcode( 'kpop_birthday_tomorrow', 'kpop_sc_birthday_tomorrow' );
endif;

if ( ! function_exists( 'kpop_sc_events' ) ) :
function kpop_sc_events() {
    if ( ! function_exists( 'kpop_render_events_widget' ) ) { return ''; }
    ob_start();
    kpop_render_events_widget();
    return ob_get_clean();
}
add_shortcode( 'kpop_events', 'kpop_sc_events' );
endif;

// Custom HTML / Text widget 内でショートコードを実行可能にする(既定は非実行)
add_filter( 'widget_text', 'do_shortcode' );
add_filter( 'widget_custom_html_content', 'do_shortcode' );
