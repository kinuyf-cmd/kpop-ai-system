<?php
/**
 * KPJ trending GA4 override (2026-05-12)
 *
 * /wp-json/kpopjournal/v1/trending の response を GA4 metrics_yesterday.json ベースで
 * 上書きする。既存 theme/plugin の kpj_api_trending 系 callback がデータ構造の
 * 認識違い ($metrics をリスト扱い) で常に空扱い→comment_count fallback していた問題を
 * 修正する。
 *
 * 配置: Code Snippets プラグイン経由で active 化 (PHP コードを WP DB に保存して実行)
 * → theme/plugin ファイルの直接編集不要で deploy 可能。
 */

add_filter('rest_pre_dispatch', function ($result, $server, $request) {
    if ($request->get_route() !== '/kpopjournal/v1/trending') {
        return $result;
    }

    $cache_key = 'kpj_api_trending_v2_ga4';
    $cached    = get_transient($cache_key);
    if ($cached !== false) {
        $r = new WP_REST_Response($cached);
        $r->header('X-KPJ-Cache', 'HIT');
        $r->header('X-KPJ-Override', 'ga4-snippet-2026-05-12');
        return $r;
    }

    $trending = [];
    $source   = 'comment_count';

    // GA4 metrics_yesterday.json の候補パス
    $candidates = [
        ABSPATH . '../../google_metrics/metrics_yesterday.json',
        ABSPATH . '../google_metrics/metrics_yesterday.json',
        '/home/aiuser/kpop-ai-system/google_metrics/metrics_yesterday.json',
    ];
    if (defined('KPJ_DIR')) {
        $candidates[] = dirname(KPJ_DIR, 2) . '/google_metrics/metrics_yesterday.json';
    }

    $metrics_file = null;
    foreach ($candidates as $c) {
        if (file_exists($c)) { $metrics_file = $c; break; }
    }

    if ($metrics_file) {
        $raw = @file_get_contents($metrics_file);
        $metrics = $raw ? json_decode($raw, true) : null;
        $ga_pages = is_array($metrics) ? ($metrics['ga4']['top_landing_pages'] ?? []) : [];

        if (!empty($ga_pages) && is_array($ga_pages)) {
            usort($ga_pages, function ($a, $b) {
                return intval($b['pageviews'] ?? 0) - intval($a['pageviews'] ?? 0);
            });

            foreach ($ga_pages as $item) {
                $path = $item['page'] ?? '';
                if (empty($path) || $path === '/') continue;
                $post_id = url_to_postid(home_url($path));
                if (!$post_id) continue;
                $post = get_post($post_id);
                if (!$post || $post->post_status !== 'publish') continue;

                // 既存の format 関数 (theme or plugin) を再利用、無ければ最小構造
                if (function_exists('kpj_api_format_post')) {
                    $entry = kpj_api_format_post($post);
                } elseif (function_exists('kpj_api_fmt')) {
                    $entry = kpj_api_fmt($post);
                } else {
                    $entry = [
                        'id'    => $post->ID,
                        'title' => get_the_title($post),
                        'link'  => get_permalink($post),
                        'date'  => get_the_date('c', $post),
                    ];
                }
                $entry['ga4'] = [
                    'pageviews' => intval($item['pageviews'] ?? 0),
                    'users'     => intval($item['users'] ?? 0),
                    'sessions'  => intval($item['sessions'] ?? 0),
                ];
                $entry['views'] = intval($item['pageviews'] ?? 0);
                $trending[] = $entry;
                if (count($trending) >= 10) break;
            }
            if (!empty($trending)) $source = 'ga4';
        }
    }

    if (empty($trending)) {
        $q = new WP_Query([
            'posts_per_page' => 10,
            'post_status'    => 'publish',
            'orderby'        => 'comment_count',
            'order'          => 'DESC',
            'date_query'     => [['after' => '30 days ago']],
        ]);
        foreach ($q->posts as $p) {
            $trending[] = [
                'id'    => $p->ID,
                'title' => get_the_title($p->ID),
                'link'  => get_permalink($p->ID),
                'date'  => get_the_date('c', $p->ID),
            ];
        }
    }

    $data = [
        'posts'     => $trending,
        'source'    => $source,
        'generated' => current_time('c'),
    ];
    set_transient($cache_key, $data, 30 * MINUTE_IN_SECONDS);

    $r = new WP_REST_Response($data);
    $r->header('X-KPJ-Cache', 'MISS');
    $r->header('X-KPJ-Override', 'ga4-snippet-2026-05-12');
    return $r;
}, 1, 3);
