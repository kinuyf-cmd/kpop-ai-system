<?php
/**
 * Plugin Name: KPJ Headless API
 * Plugin URI: https://kpopjournal.tokyo
 * Description: Headless CMS API endpoints for KpopJournal — /home, /trending, CORS, featured images.
 * Version: 1.0.0
 * Author: KpopJournal
 * Requires PHP: 7.4
 * Text Domain: kpj-headless-api
 */

defined('ABSPATH') || exit;

/* ═══════════════════════════════════════════════════════════
 *  1. CORS Headers for REST API
 * ═══════════════════════════════════════════════════════════ */
add_action('rest_api_init', function () {
    remove_filter('rest_pre_serve_request', 'rest_send_cors_headers');
    add_filter('rest_pre_serve_request', function ($value) {
        $allowed = [
            'https://kpopjournal.tokyo',
            'https://www.kpopjournal.tokyo',
        ];
        $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
        if (in_array($origin, $allowed, true)) {
            header('Access-Control-Allow-Origin: ' . $origin);
        }
        header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
        header('Access-Control-Allow-Headers: Authorization, Content-Type, X-WP-Nonce');
        header('Access-Control-Allow-Credentials: true');
        header('Access-Control-Max-Age: 86400');
        return $value;
    });
}, 15);

/* Handle preflight OPTIONS */
add_action('init', function () {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'OPTIONS') return;
    $allowed = ['https://kpopjournal.tokyo', 'https://www.kpopjournal.tokyo'];
    $origin  = $_SERVER['HTTP_ORIGIN'] ?? '';
    if (in_array($origin, $allowed, true)) {
        header('Access-Control-Allow-Origin: ' . $origin);
    }
    header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
    header('Access-Control-Allow-Headers: Authorization, Content-Type, X-WP-Nonce');
    header('Access-Control-Allow-Credentials: true');
    header('Access-Control-Max-Age: 86400');
    status_header(204);
    exit;
});

/* ═══════════════════════════════════════════════════════════
 *  2. Expose featured_image_urls on standard posts endpoint
 * ═══════════════════════════════════════════════════════════ */
add_action('rest_api_init', function () {
    register_rest_field('post', 'featured_image_urls', [
        'get_callback' => function ($post) {
            $id = get_post_thumbnail_id($post['id']);
            if (!$id) return null;
            return [
                'full'  => wp_get_attachment_image_url($id, 'full'),
                'large' => wp_get_attachment_image_url($id, 'large'),
                'medium'=> wp_get_attachment_image_url($id, 'medium'),
                'thumb' => wp_get_attachment_image_url($id, 'thumbnail'),
            ];
        },
        'schema' => [
            'description' => 'Featured image URLs at various sizes',
            'type'        => 'object',
        ],
    ]);
});

/* ═══════════════════════════════════════════════════════════
 *  3. Helper — format a WP_Post for API output
 * ═══════════════════════════════════════════════════════════ */
function kpj_api_fmt(WP_Post $p): array {
    $tid  = get_post_thumbnail_id($p->ID);
    $cats = get_the_category($p->ID);
    $tags = get_the_tags($p->ID);
    $len  = mb_strlen(strip_tags($p->post_content));

    return [
        'id'             => $p->ID,
        'slug'           => $p->post_name,
        'title'          => get_the_title($p),
        'excerpt'        => wp_trim_words(get_the_excerpt($p), 40),
        'date'           => get_the_date('c', $p),
        'modified'       => get_the_modified_date('c', $p),
        'reading_time'   => max(1, (int) ceil($len / 600)),
        'link'           => get_permalink($p),
        'featured_image' => $tid ? [
            'full'  => wp_get_attachment_image_url($tid, 'full'),
            'large' => wp_get_attachment_image_url($tid, 'large'),
            'medium'=> wp_get_attachment_image_url($tid, 'medium'),
            'thumb' => wp_get_attachment_image_url($tid, 'thumbnail'),
        ] : null,
        'categories'     => array_map(fn($c) => [
            'id' => $c->term_id, 'name' => $c->name, 'slug' => $c->slug,
        ], $cats ?: []),
        'tags'           => $tags ? array_map(fn($t) => [
            'id' => $t->term_id, 'name' => $t->name, 'slug' => $t->slug,
        ], $tags) : [],
    ];
}

/* ═══════════════════════════════════════════════════════════
 *  4. /wp-json/kpopjournal/v1/home
 * ═══════════════════════════════════════════════════════════ */
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/home', [
        'methods'             => 'GET',
        'callback'            => 'kpj_api_home_cb',
        'permission_callback' => '__return_true',
    ]);
});

function kpj_api_home_cb(WP_REST_Request $req): WP_REST_Response {
    $key = 'kpj_api_home_v1';
    $hit = get_transient($key);
    if ($hit !== false) {
        $r = new WP_REST_Response($hit);
        $r->header('X-KPJ-Cache', 'HIT');
        return $r;
    }

    /* Latest 10 */
    $latest = array_map('kpj_api_fmt', (new WP_Query([
        'posts_per_page' => 10, 'post_status' => 'publish',
        'ignore_sticky_posts' => 1,
    ]))->posts);

    /* Trending 5 — most commented past 7 days */
    $trending = array_map('kpj_api_fmt', (new WP_Query([
        'posts_per_page' => 5, 'post_status' => 'publish',
        'orderby' => 'comment_count', 'order' => 'DESC',
        'date_query' => [['after' => '7 days ago']],
    ]))->posts);

    /* BTS / BLACKPINK / aespa — 3 each */
    $by_artist = [];
    foreach (['bts', 'blackpink', 'aespa'] as $slug) {
        $cat = get_category_by_slug($slug);
        $by_artist[$slug] = $cat
            ? array_map('kpj_api_fmt', (new WP_Query([
                'posts_per_page' => 3, 'post_status' => 'publish',
                'cat' => $cat->term_id,
            ]))->posts)
            : [];
    }

    /* Chart 3 */
    $chart_cat = get_category_by_slug('chart');
    $chart = $chart_cat
        ? array_map('kpj_api_fmt', (new WP_Query([
            'posts_per_page' => 3, 'post_status' => 'publish',
            'cat' => $chart_cat->term_id,
        ]))->posts)
        : [];

    $data = [
        'latest'    => $latest,
        'trending'  => $trending,
        'by_artist' => $by_artist,
        'chart'     => $chart,
        'generated' => current_time('c'),
    ];

    set_transient($key, $data, HOUR_IN_SECONDS);
    $r = new WP_REST_Response($data);
    $r->header('X-KPJ-Cache', 'MISS');
    return $r;
}

/* ═══════════════════════════════════════════════════════════
 *  5. /wp-json/kpopjournal/v1/trending
 * ═══════════════════════════════════════════════════════════ */
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/trending', [
        'methods'             => 'GET',
        'callback'            => 'kpj_api_trending_cb',
        'permission_callback' => '__return_true',
    ]);
});

function kpj_api_trending_cb(WP_REST_Request $req): WP_REST_Response {
    $key = 'kpj_api_trending_v1';
    $hit = get_transient($key);
    if ($hit !== false) {
        $r = new WP_REST_Response($hit);
        $r->header('X-KPJ-Cache', 'HIT');
        return $r;
    }

    $trending = [];
    $source   = 'comment_count';

    /* Try WP-Statistics page views (plugin is active on this site) */
    if (function_exists('wp_statistics_pages')) {
        global $wpdb;
        $table = $wpdb->prefix . 'statistics_pages';
        if ($wpdb->get_var("SHOW TABLES LIKE '{$table}'") === $table) {
            $rows = $wpdb->get_results(
                "SELECT id, SUM(count) AS views
                 FROM {$table}
                 WHERE date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                   AND type = 'post'
                 GROUP BY id
                 ORDER BY views DESC
                 LIMIT 10"
            );
            foreach ($rows as $row) {
                $post = get_post((int) $row->id);
                if (!$post || $post->post_status !== 'publish') continue;
                $entry = kpj_api_fmt($post);
                $entry['views'] = (int) $row->views;
                $trending[] = $entry;
            }
            if (!empty($trending)) $source = 'wp-statistics';
        }
    }

    /* Fallback: comment count last 30 days */
    if (empty($trending)) {
        $trending = array_map('kpj_api_fmt', (new WP_Query([
            'posts_per_page' => 10, 'post_status' => 'publish',
            'orderby' => 'comment_count', 'order' => 'DESC',
            'date_query' => [['after' => '30 days ago']],
        ]))->posts);
    }

    $data = [
        'posts'     => $trending,
        'source'    => $source,
        'generated' => current_time('c'),
    ];

    set_transient($key, $data, HOUR_IN_SECONDS);
    $r = new WP_REST_Response($data);
    $r->header('X-KPJ-Cache', 'MISS');
    return $r;
}

/* ═══════════════════════════════════════════════════════════
 *  6. Ensure categories / tags exposed in REST
 * ═══════════════════════════════════════════════════════════ */
add_action('init', function () {
    global $wp_taxonomies;
    if (isset($wp_taxonomies['category']))  $wp_taxonomies['category']->show_in_rest  = true;
    if (isset($wp_taxonomies['post_tag']))  $wp_taxonomies['post_tag']->show_in_rest  = true;
}, 25);

/* ═══════════════════════════════════════════════════════════
 *  7. Cache invalidation on publish / update
 * ═══════════════════════════════════════════════════════════ */
add_action('save_post', function ($id, WP_Post $p) {
    if ($p->post_status !== 'publish') return;
    delete_transient('kpj_api_home_v1');
    delete_transient('kpj_api_trending_v1');
}, 10, 2);
