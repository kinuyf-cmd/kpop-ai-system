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
    global $wpdb;
    $a = shortcode_atts( array( 'limit' => 5 ), $atts );
    $limit = max( 1, (int) $a['limit'] );

    // WPP の wpp_get_mostpopular は client-side AJAX shell を出力し、サーバーHTML/クローラに
    // 記事が出ない。読者・SEO のため WPP集計テーブル(wp_popularpostsdata)を直接読み、
    // 閲覧数上位を server-render する。不足分は最新記事で top-up し常に limit 件埋める。
    $ids = array();
    $table = $wpdb->prefix . 'popularpostsdata';
    // テーブル存在チェック(WPP無効でも落ちないように)
    if ( $wpdb->get_var( $wpdb->prepare( "SHOW TABLES LIKE %s", $table ) ) === $table ) {
        $rows = $wpdb->get_col( $wpdb->prepare(
            "SELECT d.postid FROM {$table} d
             INNER JOIN {$wpdb->posts} p ON p.ID = d.postid
             WHERE p.post_status='publish' AND p.post_type='post'
             ORDER BY d.pageviews DESC LIMIT %d", $limit ) );
        if ( $rows ) { $ids = array_map( 'intval', $rows ); }
    }
    // 不足分を最新記事で補完(重複除外)
    if ( count( $ids ) < $limit ) {
        $recent = get_posts( array(
            'post_type' => 'post', 'post_status' => 'publish',
            'numberposts' => $limit, 'fields' => 'ids',
            'exclude' => $ids, 'no_found_rows' => true,
        ) );
        foreach ( $recent as $rid ) {
            if ( count( $ids ) >= $limit ) break;
            if ( ! in_array( (int) $rid, $ids, true ) ) { $ids[] = (int) $rid; }
        }
    }

    ob_start();
    echo '<div class="kpop-sidebar-box kpop-popular-box" role="region" aria-label="人気記事">';
    echo '<h2 class="kpop-box-title">人気記事 <span class="kpop-box-en">POPULAR</span></h2>';
    if ( $ids ) {
        echo '<ul class="kpop-popular-list">';
        foreach ( $ids as $pid ) {
            printf(
                '<li><a href="%s">%s</a></li>',
                esc_url( get_permalink( $pid ) ),
                esc_html( get_the_title( $pid ) )
            );
        }
        echo '</ul>';
    } else {
        echo '<p class="kpop-empty-msg">人気記事は集計中です</p>';
    }
    echo '</div>';
    return ob_get_clean();
}
add_shortcode( 'kpop_popular', 'kpop_sc_popular' );
endif;

// Custom HTML / Text widget 内でショートコードを実行可能にする(既定は非実行)
add_filter( 'widget_text', 'do_shortcode' );
add_filter( 'widget_custom_html_content', 'do_shortcode' );
