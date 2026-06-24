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

/**
 * サムネ + タイトルの 1 リスト項目を生成(Today's Chart / 人気記事 共通)。
 * 2026-05-26: タイトルのみ → サムネ付きに変更(オーナー指示)。
 * サムネ無し記事は薄ピンクのプレースホルダーで枠を保ち、行高のばらつきを防ぐ。
 */
if ( ! function_exists( 'kpop_sc_thumb_item' ) ) :
function kpop_sc_thumb_item( $pid ) {
    $pid   = (int) $pid;
    $url   = get_permalink( $pid );
    $title = get_the_title( $pid );
    // 60x60 を優先(無ければ medium/thumbnail)。get_the_post_thumbnail は srcset 付きで返る。
    $thumb = '';
    if ( has_post_thumbnail( $pid ) ) {
        $thumb = get_the_post_thumbnail( $pid, array( 64, 64 ), array(
            'class'   => 'kpop-thumb-img',
            'alt'     => '',
            'loading' => 'lazy',
        ) );
    }
    if ( '' === $thumb ) {
        $thumb = '<span class="kpop-thumb-img kpop-thumb-placeholder" aria-hidden="true"></span>';
    }
    return sprintf(
        '<li class="kpop-thumb-item"><a class="kpop-thumb-link" href="%s">'
        . '<span class="kpop-thumb-wrap">%s</span>'
        . '<span class="kpop-thumb-title">%s</span>'
        . '</a></li>',
        esc_url( $url ),
        $thumb,
        esc_html( $title )
    );
}
endif;

// 既存の render 関数を出力バッファで捕捉してショートコード戻り値にする
// [kpop_birthday] — 今日+明日を1枚の統合カードで表示(2026-05-26 統合)。
if ( ! function_exists( 'kpop_sc_birthday' ) ) :
function kpop_sc_birthday() {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
    if ( ! function_exists( 'kpop_render_birthday_combined' ) ) { return ''; }
    ob_start();
    kpop_render_birthday_combined();
    return ob_get_clean();
}
add_shortcode( 'kpop_birthday', 'kpop_sc_birthday' );
endif;

// [kpop_birthday_tomorrow] — 旧・明日単独カード。統合カード化に伴い no-op
// (既存 widget が残っていても空カードを出さないよう常に空文字を返す)。
if ( ! function_exists( 'kpop_sc_birthday_tomorrow' ) ) :
function kpop_sc_birthday_tomorrow() {
    return '';
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

// [kpop_chart] — 今日読まれている記事(WPP 24h 人気ランキング)を box 表示。
// 2026-06-25 オーナー指示: 旧「Today's Chart(chartカテゴリ記事の新着列挙)」は
//   見出しと中身が不一致(音楽ランキングでなく記事羅列)だったため、24時間の人気記事
//   ランキングへ差し替え。トップには別途「ミュージックチャート([kpop_chart_ranking]
//   =Soompi Top10)」と「人気記事(累計)」があり、本枠はそれらと重複しない24h軸。
//   shortcode 名 [kpop_chart] は既存ウィジェット互換のため維持。
if ( ! function_exists( 'kpop_sc_chart' ) ) :
function kpop_sc_chart( $atts ) {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
    $a = shortcode_atts( array( 'limit' => 5 ), $atts );
    $limit = max( 1, (int) $a['limit'] );

    // 24h 人気IDの取得。functions.php の共通関数を再利用(無ければ最新記事フォールバック)。
    $ids = array();
    if ( function_exists( 'kpop_sidebar_popular_ids' ) ) {
        $ids = kpop_sidebar_popular_ids( 'last24hours', $limit );
    } else {
        $ids = get_posts( array(
            'post_type' => 'post', 'post_status' => 'publish',
            'numberposts' => $limit, 'fields' => 'ids', 'no_found_rows' => true,
        ) );
    }

    ob_start();
    echo '<div class="kpop-sidebar-box kpop-popular-24h" role="region" aria-label="今日読まれている記事">';
    echo '<h2 class="kpop-box-title">今日読まれている記事 <span class="kpop-box-en">TODAY</span></h2>';
    if ( $ids ) {
        echo '<ul class="kpop-popular-list kpop-thumb-list">';
        foreach ( $ids as $pid ) {
            echo kpop_sc_thumb_item( (int) $pid );
        }
        echo '</ul>';
    } else {
        echo '<p class="kpop-empty-msg">集計中です</p>';
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
    // テーブル名は $wpdb->prefix 由来(ユーザー入力でない)。SHOW TABLES は prepare を使わず
    // 直接エスケープ済みリテラルで判定(prepare("SHOW TABLES LIKE %s") は環境により _doing_it_wrong
    // を誘発し出力停止の恐れがあるため避ける)。クエリ全体を try 相当で安全化。
    $table = $wpdb->prefix . 'popularpostsdata';
    $exists = $wpdb->get_var( "SHOW TABLES LIKE '" . esc_sql( $table ) . "'" );
    if ( $exists === $table ) {
        $rows = $wpdb->get_col( $wpdb->prepare(
            "SELECT d.postid FROM `{$table}` d
             INNER JOIN {$wpdb->posts} p ON p.ID = d.postid
             WHERE p.post_status = 'publish' AND p.post_type = 'post'
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
        echo '<ul class="kpop-popular-list kpop-thumb-list">';
        foreach ( $ids as $pid ) {
            echo kpop_sc_thumb_item( $pid );
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
// 描画本体(関数)。prepend は is_singular でこれを直接呼び、widget shortcode は guard 付きで呼ぶ
// → 記事=prepend経由で1回、トップ=widget経由で1回 = 各ページ1回のみ(二重防止)。
if ( ! function_exists( 'kpop_render_chart_ranking' ) ) :
function kpop_render_chart_ranking( $limit = 10 ) {
    $limit = max( 1, min( 10, (int) $limit ) );
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
        // 集計時点の明示(オーナー指示 2026-05-26): チャート週(title内 "... Week N")を優先し、
        // 無ければ取得日時 fetched_at を日本時間で表示。読者がいつ時点のランキングか判別できるように。
        $asof = '';
        $title = ( is_array( $data ) && ! empty( $data['title'] ) ) ? $data['title'] : '';
        if ( $title && preg_match( '/(\d{4})\s*,\s*([A-Za-z]+)\s*Week\s*(\d+)/i', $title, $wm ) ) {
            $asof = sprintf( '%s %s Week %d 版', $wm[1], $wm[2], (int) $wm[3] );
        }
        if ( '' === $asof && is_array( $data ) && ! empty( $data['fetched_at'] ) ) {
            $ts = strtotime( $data['fetched_at'] );
            if ( $ts ) { $asof = date_i18n( 'Y年n月j日', $ts ) . ' 時点'; }
        }
        if ( $asof ) {
            printf( '<p class="kpop-mchart-asof">%s</p>', esc_html( $asof ) );
        }
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
}
endif;

// shortcode版: widget(全ページ)用。記事ページでは prepend が render を直接呼ぶため suppress(二重防止)
if ( ! function_exists( 'kpop_sc_chart_ranking' ) ) :
function kpop_sc_chart_ranking( $atts ) {
    if ( kpop_sc_suppressed_on_single() ) { return ''; }
    $a = shortcode_atts( array( 'limit' => 10 ), $atts );
    ob_start();
    kpop_render_chart_ranking( (int) $a['limit'] );
    return ob_get_clean();
}
add_shortcode( 'kpop_chart_ranking', 'kpop_sc_chart_ranking' );
endif;

// Custom HTML / Text widget 内でショートコードを実行可能にする(既定は非実行)
add_filter( 'widget_text', 'do_shortcode' );
add_filter( 'widget_custom_html_content', 'do_shortcode' );
