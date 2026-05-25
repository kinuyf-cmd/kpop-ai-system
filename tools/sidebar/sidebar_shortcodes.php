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

// [kpop_chart] — Today's Chart: チャートカテゴリ(slug=chart)の最新記事を box 表示
if ( ! function_exists( 'kpop_sc_chart' ) ) :
function kpop_sc_chart( $atts ) {
    $a = shortcode_atts( array( 'limit' => 5 ), $atts );
    $q = new WP_Query( array(
        'post_type'           => 'post',
        'post_status'         => 'publish',
        'category_name'       => 'chart',
        'posts_per_page'      => (int) $a['limit'],
        'ignore_sticky_posts' => true,
        'no_found_rows'       => true,
    ) );
    ob_start();
    echo '<div class="kpop-sidebar-box kpop-today-chart" role="region" aria-label="Today\'s Chart">';
    echo '<h2 class="kpop-box-title">Today\'s Chart <span class="kpop-box-en">CHART</span></h2>';
    if ( $q->have_posts() ) {
        echo '<ul class="kpop-chart-list">';
        while ( $q->have_posts() ) { $q->the_post();
            printf(
                '<li class="kpop-chart-item"><a href="%s">%s</a></li>',
                esc_url( get_permalink() ),
                esc_html( get_the_title() )
            );
        }
        echo '</ul>';
        wp_reset_postdata();
    } else {
        echo '<p class="kpop-empty-msg">チャート記事は準備中です</p>';
    }
    echo '</div>';
    return ob_get_clean();
}
add_shortcode( 'kpop_chart', 'kpop_sc_chart' );
endif;

// [kpop_popular] — 人気記事: WordPress Popular Posts を box でラップ。WPP無効時は最新記事にフォールバック
if ( ! function_exists( 'kpop_sc_popular' ) ) :
function kpop_sc_popular( $atts ) {
    $a = shortcode_atts( array( 'limit' => 5, 'range' => 'last7days' ), $atts );
    ob_start();
    echo '<div class="kpop-sidebar-box kpop-popular-box" role="region" aria-label="人気記事">';
    echo '<h2 class="kpop-box-title">人気記事 <span class="kpop-box-en">POPULAR</span></h2>';
    if ( function_exists( 'wpp_get_mostpopular' ) ) {
        // WPP のレンダリングを利用(閲覧集計に基づく実人気)
        wpp_get_mostpopular( array(
            'limit'     => (int) $a['limit'],
            'range'     => $a['range'],
            'post_type' => 'post',
            'wrapper'   => 'ul',
            'wrapper_class' => 'kpop-popular-list',
        ) );
    } else {
        // フォールバック: 最新記事(WPPが未集計/無効でも空にしない)
        $q = new WP_Query( array(
            'post_type' => 'post', 'post_status' => 'publish',
            'posts_per_page' => (int) $a['limit'], 'no_found_rows' => true,
        ) );
        if ( $q->have_posts() ) {
            echo '<ul class="kpop-popular-list">';
            while ( $q->have_posts() ) { $q->the_post();
                printf( '<li><a href="%s">%s</a></li>', esc_url( get_permalink() ), esc_html( get_the_title() ) );
            }
            echo '</ul>';
            wp_reset_postdata();
        } else {
            echo '<p class="kpop-empty-msg">人気記事は集計中です</p>';
        }
    }
    echo '</div>';
    return ob_get_clean();
}
add_shortcode( 'kpop_popular', 'kpop_sc_popular' );
endif;

// Custom HTML / Text widget 内でショートコードを実行可能にする(既定は非実行)
add_filter( 'widget_text', 'do_shortcode' );
add_filter( 'widget_custom_html_content', 'do_shortcode' );
