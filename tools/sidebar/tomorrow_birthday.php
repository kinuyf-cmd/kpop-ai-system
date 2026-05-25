<?php
/**
 * widgets/tomorrow_birthday.php — 明日の誕生日 ウィジェット
 * 【2026-05-25 修正】today_birthday.php と同じ空表示バグ(YYYYMMDD非対応)を修正。
 * @package kpop-journal-child
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

if ( ! function_exists( 'kpop_render_tomorrow_birthday' ) ) :
function kpop_render_tomorrow_birthday() {
    global $wpdb;
    $ts          = current_time( 'timestamp' ) + DAY_IN_SECONDS;
    $mmdd_hyphen = date_i18n( 'm-d', $ts ); // 例: 05-26
    $mmdd        = date_i18n( 'md', $ts );  // 例: 0526

    $query = $wpdb->prepare(
        "SELECT pm.post_id, pm.meta_key, pm.meta_value
         FROM {$wpdb->postmeta} pm
         INNER JOIN {$wpdb->posts} p ON p.ID = pm.post_id
         WHERE p.post_type = 'idol_artist'
           AND p.post_status = 'publish'
           AND pm.meta_key LIKE %s
           AND (
                ( CHAR_LENGTH(pm.meta_value) = 8 AND SUBSTRING(pm.meta_value, 5, 4) = %s )
                OR pm.meta_value LIKE %s
                OR pm.meta_value LIKE %s
           )
         ORDER BY pm.post_id ASC, pm.meta_key ASC
         LIMIT 50",
        'members_%_member_birthday',
        $mmdd,
        '%-' . $wpdb->esc_like( $mmdd_hyphen ),
        $wpdb->esc_like( $mmdd_hyphen )
    );
    $rows = $wpdb->get_results( $query );

    echo '<div class="kpop-sidebar-box kpop-birthday-tomorrow" role="region" aria-label="明日の誕生日">';
    echo '<h2 class="widget-title">明日の誕生日</h2>';

    if ( empty( $rows ) ) {
        echo '<p class="kpop-empty-msg">明日該当メンバーなし</p>';
        echo '</div>';
        return;
    }
    $by_group = array();
    foreach ( $rows as $r ) {
        if ( ! preg_match( '/members_(\d+)_member_birthday/', $r->meta_key, $m ) ) { continue; }
        $name_key = "members_{$m[1]}_member_name";
        $member_name = get_post_meta( $r->post_id, $name_key, true );
        if ( ! $member_name ) { continue; }
        $by_group[ $r->post_id ][] = $member_name;
    }
    if ( empty( $by_group ) ) {
        echo '<p class="kpop-empty-msg">明日該当メンバーなし</p></div>';
        return;
    }
    echo '<ul class="kpop-birthday-list">';
    foreach ( $by_group as $post_id => $members ) {
        $group_title = get_the_title( $post_id );
        $group_url   = get_permalink( $post_id );
        foreach ( $members as $mn ) {
            printf(
                '<li class="kpop-birthday-item"><a href="%s">%s</a> <span class="kpop-birthday-group">(%s)</span></li>',
                esc_url( $group_url ), esc_html( $mn ), esc_html( $group_title )
            );
        }
    }
    echo '</ul></div>';
}
endif;
