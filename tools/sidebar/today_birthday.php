<?php
/**
 * widgets/today_birthday.php — A-2 今日の誕生日 ウィジェット
 *
 * 出力: サイドバーボックス「今日の誕生日」
 * データソース: CPT idol_artist の wp_postmeta `members_{i}_member_birthday`
 *
 * 【2026-05-25 修正】生年月日の実データは YYYYMMDD(8桁、例 20020525)だが、
 *   旧コードは YYYY-MM-DD / MM-DD(ハイフン区切り)を前提に LIKE していたため
 *   1件もマッチせず常に「本日該当メンバーなし」になっていた(空表示バグ)。
 *   → YYYYMMDD(8桁)の MMDD 一致を主条件にしつつ、旧ハイフン形式も後方互換で維持。
 *
 * @package kpop-journal-child
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

if ( ! function_exists( 'kpop_render_today_birthday' ) ) :
function kpop_render_today_birthday() {
    global $wpdb;
    $mmdd_hyphen = date_i18n( 'm-d' ); // 例: 05-25(旧ハイフン形式用)
    $mmdd        = date_i18n( 'md' );  // 例: 0525(YYYYMMDD 末尾4桁用)

    // 生年月日の格納形式は混在しうるため複数条件で対応:
    //   ① YYYYMMDD(8桁): 5〜8文字目(MMDD)が今日と一致     ← 現行データの主形式
    //   ② YYYY-MM-DD: 末尾 -MM-DD 一致 / ③ MM-DD: 完全一致  ← 旧形式の後方互換
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
        $mmdd,                                       // ① 0525
        '%-' . $wpdb->esc_like( $mmdd_hyphen ),      // ② 例 1995-05-25 末尾一致
        $wpdb->esc_like( $mmdd_hyphen )              // ③ 例 05-25 完全一致
    );

    $rows = $wpdb->get_results( $query );

    echo '<div class="kpop-sidebar-box kpop-birthday-today" role="region" aria-label="今日の誕生日">';
    echo '<h2 class="widget-title">今日の誕生日</h2>';

    if ( empty( $rows ) ) {
        echo '<p class="kpop-empty-msg">本日該当メンバーなし</p>';
        echo '</div>';
        return;
    }

    // グループごとにまとめる: post_id → [member names]
    $by_group = array();
    foreach ( $rows as $r ) {
        if ( ! preg_match( '/members_(\d+)_member_birthday/', $r->meta_key, $m ) ) { continue; }
        $idx = $m[1];
        $name_key = "members_{$idx}_member_name";
        $member_name = get_post_meta( $r->post_id, $name_key, true );
        if ( ! $member_name ) { continue; }
        $by_group[ $r->post_id ][] = $member_name;
    }

    if ( empty( $by_group ) ) {
        echo '<p class="kpop-empty-msg">本日該当メンバーなし</p>';
        echo '</div>';
        return;
    }

    echo '<ul class="kpop-birthday-list">';
    foreach ( $by_group as $post_id => $members ) {
        $group_title = get_the_title( $post_id );
        $group_url   = get_permalink( $post_id );
        foreach ( $members as $mn ) {
            printf(
                '<li class="kpop-birthday-item"><a href="%s">%s</a> <span class="kpop-birthday-group">(%s)</span></li>',
                esc_url( $group_url ),
                esc_html( $mn ),
                esc_html( $group_title )
            );
        }
    }
    echo '</ul>';
    echo '</div>';
}
endif;
