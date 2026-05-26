<?php
/**
 * widgets/events_widget.php — イベント枠(2026-05-25 新設)
 *
 * 出力: サイドバーボックス「イベント」。The Events Calendar(tribe_events)の
 *   直近〜開催予定イベントを最大5件表示し、詳細はカレンダー /events/ へ誘導。
 * データソース: CPT tribe_events + _EventStartDate(本日以降を優先、無ければ最新)。
 * 詳細リンク: 各イベント→個別ページ、枠下に「カレンダーで見る → /events/」。
 * 安全設計: prepared query / esc_html / esc_url、role="region" aria-label。
 *
 * @package kpop-journal-child
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

if ( ! function_exists( 'kpop_render_events_widget' ) ) :
function kpop_render_events_widget() {
    global $wpdb;
    $today = current_time( 'Y-m-d 00:00:00' );

    // 本日以降の開催予定を開始日昇順で。無ければ開始日のある最新を表示(NULL開始は後ろ)。
    $rows = $wpdb->get_results( $wpdb->prepare(
        "SELECT p.ID, p.post_title, sm.meta_value AS start_date
         FROM {$wpdb->posts} p
         INNER JOIN {$wpdb->postmeta} sm
                 ON sm.post_id = p.ID AND sm.meta_key = '_EventStartDate'
         WHERE p.post_type = 'tribe_events'
           AND p.post_status = 'publish'
           AND sm.meta_value >= %s
         ORDER BY sm.meta_value ASC
         LIMIT 5",
        $today
    ) );
    // 本日以降が無ければ、開始日のあるイベントを新しい順にフォールバック
    if ( empty( $rows ) ) {
        $rows = $wpdb->get_results(
            "SELECT p.ID, p.post_title, sm.meta_value AS start_date
             FROM {$wpdb->posts} p
             INNER JOIN {$wpdb->postmeta} sm
                     ON sm.post_id = p.ID AND sm.meta_key = '_EventStartDate'
             WHERE p.post_type = 'tribe_events' AND p.post_status = 'publish'
             ORDER BY sm.meta_value DESC
             LIMIT 5"
        );
    }

    $calendar_url = home_url( '/events/' );

    // 1ヶ月以内に開催のイベントはカレンダー一覧(/events/)へ誘導する(オーナー指示 2026-05-26)。
    // それより先のイベントは従来どおり個別ページへ。境界=本日+1ヶ月。
    $month_ahead = strtotime( '+1 month', current_time( 'timestamp' ) );

    echo '<div class="kpop-sidebar-box kpop-events" role="region" aria-label="イベント">';
    echo '<h2 class="kpop-box-title">イベント <span class="kpop-box-en">EVENTS</span></h2>';

    if ( empty( $rows ) ) {
        echo '<p class="kpop-empty-msg">現在掲載中のイベントはありません</p>';
    } else {
        echo '<ul class="kpop-events-list">';
        foreach ( $rows as $r ) {
            $start_ts = $r->start_date ? strtotime( $r->start_date ) : 0;
            $date  = $start_ts ? date_i18n( 'n/j', $start_ts ) : '';
            $title = get_the_title( $r->ID );
            // 1ヶ月以内 → カレンダー(/events/)、それ以外 → 個別ページ
            $soon  = ( $start_ts && $start_ts <= $month_ahead );
            $url   = $soon ? $calendar_url : get_permalink( $r->ID );
            printf(
                '<li class="kpop-events-item">%s<a href="%s"%s>%s</a></li>',
                $date ? '<span class="kpop-events-date">' . esc_html( $date ) . '</span> ' : '',
                esc_url( $url ),
                $soon ? ' aria-label="' . esc_attr( $title . ' をカレンダーで見る' ) . '"' : '',
                esc_html( $title )
            );
        }
        echo '</ul>';
    }

    // 詳細はカレンダーへ(オーナー指定: 詳細リンクでカレンダー式イベントを見れるように)
    printf(
        '<p class="kpop-events-more"><a href="%s">カレンダーで見る <span aria-hidden="true">&rarr;</span></a></p>',
        esc_url( $calendar_url )
    );
    echo '</div>';
}
endif;
