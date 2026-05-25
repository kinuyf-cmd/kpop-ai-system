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

/**
 * 2026-05-25 重複防止: これらの shortcode は WP widget(sidebar-1)経由で全ページのサイドバーに出る。
 * 一方、単一記事ページ(is_singular('post'))では functions.php の kpop_m11_sidebar_prepend/append
 * フックが同じ枠を直接描画するため、widget由来の shortcode を記事ページで実行すると二重表示になる。
 * → 記事ページでは shortcode を no-op にし、widget出力を抑止(記事=hooks / 非記事=widget の住み分け)。
 */
if ( ! function_exists( 'kpop_sc_suppressed_on_single' ) ) :
function kpop_sc_suppressed_on_single() {
    return function_exists( 'is_singular' ) && is_singular( 'post' );
}
endif;

// 既存の render 関数を出力バッファで捕捉してショートコード戻り値にする
if ( ! function_exists( 'kpop_sc_birthday' ) ) :
function kpop_sc_birthday() {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
    if ( ! function_exists( 'kpop_render_today_birthday' ) ) { return ''; }
    ob_start();
    kpop_render_today_birthday();
    return ob_get_clean();
}
add_shortcode( 'kpop_birthday', 'kpop_sc_birthday' );
endif;

if ( ! function_exists( 'kpop_sc_birthday_tomorrow' ) ) :
function kpop_sc_birthday_tomorrow() {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
    if ( ! function_exists( 'kpop_render_tomorrow_birthday' ) ) { return ''; }
    ob_start();
    kpop_render_tomorrow_birthday();
    return ob_get_clean();
}
add_shortcode( 'kpop_birthday_tomorrow', 'kpop_sc_birthday_tomorrow' );
endif;

if ( ! function_exists( 'kpop_sc_events' ) ) :
function kpop_sc_events() {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
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
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
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
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
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

// [kpop_chart_ranking] — Soompi K-Pop Music Chart の Top10 ランキング(曲+アーティスト)
// データ: wp_option 'kpop_soompi_chart'(Node collector が取得→owner scriptで取り込み)。
// 引用ポリシー: 出典(Soompi)を明記しリンク。順位/曲/アーティストの事実のみ表示(捏造なし)。
if ( ! function_exists( 'kpop_sc_chart_ranking' ) ) :
function kpop_sc_chart_ranking( $atts ) {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
    $a = shortcode_atts( array( 'limit' => 10 ), $atts );
    $limit = max( 1, min( 10, (int) $a['limit'] ) );
    $data = get_option( 'kpop_soompi_chart' );
    if ( is_string( $data ) ) { $data = json_decode( $data, true ); }
    $items = ( is_array( $data ) && ! empty( $data['items'] ) ) ? $data['items'] : array();

    ob_start();
    echo '<div class="kpop-sidebar-box kpop-music-chart" role="region" aria-label="ミュージックチャート">';
    echo '<h2 class="kpop-box-title">ミュージックチャート <span class="kpop-box-en">MUSIC CHART</span></h2>';
    if ( $items ) {
        echo '<ol class="kpop-mchart-list">';
        $n = 0;
        foreach ( $items as $it ) {
            if ( $n++ >= $limit ) break;
            $rank   = isset( $it['rank'] ) ? (int) $it['rank'] : ( $n );
            $song   = isset( $it['song'] ) ? $it['song'] : '';
            $artist = isset( $it['artist'] ) ? $it['artist'] : '';
            printf(
                '<li class="kpop-mchart-item"><span class="kpop-mchart-rank">%d</span>'
                . '<span class="kpop-mchart-body"><span class="kpop-mchart-song">%s</span>'
                . '<span class="kpop-mchart-artist">%s</span></span></li>',
                $rank, esc_html( $song ), esc_html( $artist )
            );
        }
        echo '</ol>';
        // 出典明記(citation-rules 準拠)
        $src = ( is_array( $data ) && ! empty( $data['url'] ) ) ? $data['url'] : 'https://www.soompi.com/';
        printf(
            '<p class="kpop-mchart-source">出典: <a href="%s" rel="nofollow noopener">Soompi K-Pop Music Chart</a></p>',
            esc_url( $src )
        );
    } else {
        echo '<p class="kpop-empty-msg">チャートを取得中です</p>';
    }
    echo '</div>';
    return ob_get_clean();
}
add_shortcode( 'kpop_chart_ranking', 'kpop_sc_chart_ranking' );
endif;

// Custom HTML / Text widget 内でショートコードを実行可能にする(既定は非実行)
add_filter( 'widget_text', 'do_shortcode' );
add_filter( 'widget_custom_html_content', 'do_shortcode' );
