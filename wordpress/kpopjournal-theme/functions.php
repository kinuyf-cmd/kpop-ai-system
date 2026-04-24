<?php
/**
 * KpopJournal Theme Functions
 */

defined('ABSPATH') || exit;

define('KPJ_VERSION', '1.0.0');
define('KPJ_DIR', get_template_directory());
define('KPJ_URI', get_template_directory_uri());

/* ── Theme Setup ─────────────────────────────────────────── */
add_action('after_setup_theme', function () {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('html5', ['comment-list', 'comment-form', 'search-form', 'gallery', 'caption']);
    add_theme_support('custom-logo', [
        'height'      => 48,
        'width'       => 200,
        'flex-height' => true,
        'flex-width'  => true,
    ]);
    add_theme_support('editor-styles');
    add_theme_support('responsive-embeds');
    add_theme_support('wp-block-styles');

    set_post_thumbnail_size(1200, 630, true);
    add_image_size('kpj-hero', 1400, 780, true);
    add_image_size('kpj-card', 600, 340, true);
    add_image_size('kpj-list', 280, 160, true);

    register_nav_menus([
        'primary'   => __('Primary Navigation', 'kpopjournal'),
        'footer'    => __('Footer Navigation', 'kpopjournal'),
        'mobile'    => __('Mobile Navigation', 'kpopjournal'),
    ]);
});

/* ── Enqueue Assets ──────────────────────────────────────── */
add_action('wp_enqueue_scripts', function () {
    // Google Fonts
    wp_enqueue_style(
        'kpj-fonts',
        'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Noto+Sans+JP:wght@300;400;500;700&display=swap',
        [],
        null
    );

    // Main stylesheet
    wp_enqueue_style('kpj-main', KPJ_URI . '/assets/css/main.css', ['kpj-fonts'], KPJ_VERSION);

    // Main script
    wp_enqueue_script('kpj-main', KPJ_URI . '/assets/js/main.js', [], KPJ_VERSION, true);

    wp_localize_script('kpj-main', 'kpjData', [
        'ajaxUrl' => admin_url('admin-ajax.php'),
        'nonce'   => wp_create_nonce('kpj_nonce'),
        'siteUrl' => home_url('/'),
    ]);
});

/* ── Widgets ─────────────────────────────────────────────── */
add_action('widgets_init', function () {
    $defaults = [
        'before_widget' => '<div id="%1$s" class="kpj-widget %2$s">',
        'after_widget'  => '</div>',
        'before_title'  => '<h3 class="kpj-widget__title">',
        'after_title'   => '</h3>',
    ];

    register_sidebar(array_merge($defaults, [
        'name' => __('Sidebar', 'kpopjournal'),
        'id'   => 'sidebar-main',
    ]));

    register_sidebar(array_merge($defaults, [
        'name' => __('Footer 1', 'kpopjournal'),
        'id'   => 'footer-1',
    ]));
    register_sidebar(array_merge($defaults, [
        'name' => __('Footer 2', 'kpopjournal'),
        'id'   => 'footer-2',
    ]));
    register_sidebar(array_merge($defaults, [
        'name' => __('Footer 3', 'kpopjournal'),
        'id'   => 'footer-3',
    ]));
    register_sidebar(array_merge($defaults, [
        'name' => __('Footer 4', 'kpopjournal'),
        'id'   => 'footer-4',
    ]));
});

/* ── Helper: Reading Time ────────────────────────────────── */
function kpj_reading_time($post_id = null) {
    $content = get_post_field('post_content', $post_id ?: get_the_ID());
    $word_count = mb_strlen(strip_tags($content));
    $minutes = max(1, ceil($word_count / 600)); // Japanese ~600 chars/min
    return $minutes;
}

/* ── Helper: Category Badge ──────────────────────────────── */
function kpj_category_badge($post_id = null) {
    $cats = get_the_category($post_id);
    if (empty($cats)) return '';
    $cat = $cats[0];
    return sprintf(
        '<a href="%s" class="kpj-badge">%s</a>',
        esc_url(get_category_link($cat->term_id)),
        esc_html($cat->name)
    );
}

/* ── Helper: Post Card ───────────────────────────────────── */
function kpj_post_card($size = 'kpj-card', $class = '') {
    ?>
    <article class="kpj-card <?php echo esc_attr($class); ?>">
        <a href="<?php the_permalink(); ?>" class="kpj-card__link">
            <?php if (has_post_thumbnail()): ?>
                <div class="kpj-card__thumb">
                    <?php the_post_thumbnail($size, ['class' => 'kpj-card__img', 'loading' => 'lazy']); ?>
                    <div class="kpj-card__overlay"></div>
                </div>
            <?php endif; ?>
            <div class="kpj-card__body">
                <?php echo kpj_category_badge(); ?>
                <h3 class="kpj-card__title"><?php the_title(); ?></h3>
                <div class="kpj-card__meta">
                    <time datetime="<?php echo get_the_date('c'); ?>"><?php echo get_the_date('Y.m.d'); ?></time>
                    <span class="kpj-card__reading"><?php echo kpj_reading_time(); ?>min</span>
                </div>
            </div>
        </a>
    </article>
    <?php
}

/* ── Helper: Post List Item ──────────────────────────────── */
function kpj_post_list_item() {
    ?>
    <article class="kpj-list-item">
        <a href="<?php the_permalink(); ?>" class="kpj-list-item__link">
            <?php if (has_post_thumbnail()): ?>
                <div class="kpj-list-item__thumb">
                    <?php the_post_thumbnail('kpj-list', ['class' => 'kpj-list-item__img', 'loading' => 'lazy']); ?>
                </div>
            <?php endif; ?>
            <div class="kpj-list-item__body">
                <?php echo kpj_category_badge(); ?>
                <h3 class="kpj-list-item__title"><?php the_title(); ?></h3>
                <div class="kpj-list-item__meta">
                    <time datetime="<?php echo get_the_date('c'); ?>"><?php echo get_the_date('Y.m.d'); ?></time>
                </div>
            </div>
        </a>
    </article>
    <?php
}

/* ── Breaking News (uses sticky posts or latest) ─────────── */
function kpj_get_breaking_news($count = 8) {
    $sticky = get_option('sticky_posts');
    if (!empty($sticky)) {
        $q = new WP_Query([
            'post__in'            => $sticky,
            'posts_per_page'      => $count,
            'ignore_sticky_posts' => 1,
        ]);
        if ($q->have_posts()) return $q;
    }
    return new WP_Query([
        'posts_per_page' => $count,
        'orderby'        => 'date',
        'order'          => 'DESC',
    ]);
}

/* ── Excerpt Length ───────────────────────────────────────── */
add_filter('excerpt_length', fn() => 40);
add_filter('excerpt_more', fn() => '...');

/* ── Remove WP Emoji ─────────────────────────────────────── */
remove_action('wp_head', 'print_emoji_detection_script', 7);
remove_action('wp_print_styles', 'print_emoji_styles');

/* ── Admin: Editor Dark Styles ───────────────────────────── */
add_action('admin_init', function () {
    add_editor_style('assets/css/main.css');
});

/* ═══════════════════════════════════════════════════════════
 *  HEADLESS CMS — REST API Extensions
 * ═══════════════════════════════════════════════════════════ */

/* ── 1. CORS Headers ────────────────────────────────────── */
add_action('rest_api_init', function () {
    remove_filter('rest_pre_serve_request', 'rest_send_cors_headers');
    add_filter('rest_pre_serve_request', function ($value) {
        $origin = 'https://kpopjournal.tokyo';
        header('Access-Control-Allow-Origin: ' . $origin);
        header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
        header('Access-Control-Allow-Headers: Authorization, Content-Type, X-WP-Nonce');
        header('Access-Control-Allow-Credentials: true');
        header('Access-Control-Max-Age: 86400');
        return $value;
    });
}, 15);

/* Handle preflight OPTIONS */
add_action('init', function () {
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
        header('Access-Control-Allow-Origin: https://kpopjournal.tokyo');
        header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
        header('Access-Control-Allow-Headers: Authorization, Content-Type, X-WP-Nonce');
        header('Access-Control-Allow-Credentials: true');
        header('Access-Control-Max-Age: 86400');
        status_header(204);
        exit;
    }
});

/* ── 2. Expose featured image URL in REST responses ─────── */
add_action('rest_api_init', function () {
    register_rest_field('post', 'featured_image_urls', [
        'get_callback' => function ($post) {
            $thumb_id = get_post_thumbnail_id($post['id']);
            if (!$thumb_id) {
                return null;
            }
            return [
                'full'     => wp_get_attachment_image_url($thumb_id, 'full'),
                'hero'     => wp_get_attachment_image_url($thumb_id, 'kpj-hero'),
                'card'     => wp_get_attachment_image_url($thumb_id, 'kpj-card'),
                'list'     => wp_get_attachment_image_url($thumb_id, 'kpj-list'),
                'thumb'    => wp_get_attachment_image_url($thumb_id, 'thumbnail'),
            ];
        },
        'schema' => [
            'description' => 'Featured image URLs at various sizes',
            'type'        => 'object',
        ],
    ]);
});

/* ── 3. Helper: Format post for API response ────────────── */
function kpj_api_format_post(WP_Post $post): array {
    $thumb_id   = get_post_thumbnail_id($post->ID);
    $categories = get_the_category($post->ID);
    $tags       = get_the_tags($post->ID);

    return [
        'id'            => $post->ID,
        'slug'          => $post->post_name,
        'title'         => get_the_title($post),
        'excerpt'       => wp_trim_words(get_the_excerpt($post), 40),
        'date'          => get_the_date('c', $post),
        'modified'      => get_the_modified_date('c', $post),
        'reading_time'  => kpj_reading_time($post->ID),
        'link'          => get_permalink($post),
        'featured_image' => $thumb_id ? [
            'full' => wp_get_attachment_image_url($thumb_id, 'full'),
            'hero' => wp_get_attachment_image_url($thumb_id, 'kpj-hero'),
            'card' => wp_get_attachment_image_url($thumb_id, 'kpj-card'),
            'list' => wp_get_attachment_image_url($thumb_id, 'kpj-list'),
        ] : null,
        'categories' => array_map(fn($c) => [
            'id'   => $c->term_id,
            'name' => $c->name,
            'slug' => $c->slug,
            'link' => get_category_link($c->term_id),
        ], $categories ?: []),
        'tags' => $tags ? array_map(fn($t) => [
            'id'   => $t->term_id,
            'name' => $t->name,
            'slug' => $t->slug,
        ], $tags) : [],
    ];
}

/* ── 4. /wp-json/kpopjournal/v1/home ────────────────────── */
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/home', [
        'methods'             => 'GET',
        'callback'            => 'kpj_api_home',
        'permission_callback' => '__return_true',
    ]);
});

function kpj_api_home(WP_REST_Request $request): WP_REST_Response {
    $cache_key = 'kpj_api_home_v1';
    $cached    = get_transient($cache_key);

    if ($cached !== false) {
        $response = new WP_REST_Response($cached);
        $response->header('X-KPJ-Cache', 'HIT');
        return $response;
    }

    // Latest 10
    $latest_q = new WP_Query([
        'posts_per_page'      => 10,
        'post_status'         => 'publish',
        'ignore_sticky_posts' => 1,
    ]);
    $latest = array_map('kpj_api_format_post', $latest_q->posts);

    // Trending 5 (most commented in last 7 days)
    $trending_q = new WP_Query([
        'posts_per_page' => 5,
        'post_status'    => 'publish',
        'orderby'        => 'comment_count',
        'order'          => 'DESC',
        'date_query'     => [['after' => '7 days ago']],
    ]);
    $trending = array_map('kpj_api_format_post', $trending_q->posts);

    // Category posts — BTS / BLACKPINK / aespa (3 each)
    $artist_slugs    = ['bts', 'blackpink', 'aespa'];
    $by_artist       = [];
    foreach ($artist_slugs as $slug) {
        $cat = get_category_by_slug($slug);
        if (!$cat) {
            $by_artist[$slug] = [];
            continue;
        }
        $q = new WP_Query([
            'posts_per_page' => 3,
            'post_status'    => 'publish',
            'cat'            => $cat->term_id,
        ]);
        $by_artist[$slug] = array_map('kpj_api_format_post', $q->posts);
    }

    // Chart posts (3)
    $chart_cat   = get_category_by_slug('chart');
    $chart_posts = [];
    if ($chart_cat) {
        $q = new WP_Query([
            'posts_per_page' => 3,
            'post_status'    => 'publish',
            'cat'            => $chart_cat->term_id,
        ]);
        $chart_posts = array_map('kpj_api_format_post', $q->posts);
    }

    $data = [
        'latest'    => $latest,
        'trending'  => $trending,
        'by_artist' => $by_artist,
        'chart'     => $chart_posts,
        'generated' => current_time('c'),
    ];

    set_transient($cache_key, $data, HOUR_IN_SECONDS);

    $response = new WP_REST_Response($data);
    $response->header('X-KPJ-Cache', 'MISS');
    return $response;
}

/* ── 5. /wp-json/kpopjournal/v1/trending ────────────────── */
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/trending', [
        'methods'             => 'GET',
        'callback'            => 'kpj_api_trending',
        'permission_callback' => '__return_true',
    ]);
});

function kpj_api_trending(WP_REST_Request $request): WP_REST_Response {
    $cache_key = 'kpj_api_trending_v1';
    $cached    = get_transient($cache_key);

    if ($cached !== false) {
        $response = new WP_REST_Response($cached);
        $response->header('X-KPJ-Cache', 'HIT');
        return $response;
    }

    $trending = [];

    // Try GA4 pageview data from local metrics file
    $metrics_file = ABSPATH . '../../google_metrics/metrics_yesterday.json';
    if (!file_exists($metrics_file)) {
        $metrics_file = dirname(KPJ_DIR, 2) . '/google_metrics/metrics_yesterday.json';
    }

    if (file_exists($metrics_file)) {
        $raw = file_get_contents($metrics_file);
        $ga_data = json_decode($raw, true);

        if (!empty($ga_data) && is_array($ga_data)) {
            // Sort by pageviews descending, take top 10
            usort($ga_data, fn($a, $b) => ($b['pageviews'] ?? 0) - ($a['pageviews'] ?? 0));
            $top = array_slice($ga_data, 0, 10);

            foreach ($top as $item) {
                $path = $item['page'] ?? $item['pagePath'] ?? '';
                if (empty($path) || $path === '/') continue;

                $post_id = url_to_postid(home_url($path));
                if (!$post_id) continue;

                $post = get_post($post_id);
                if (!$post || $post->post_status !== 'publish') continue;

                $entry = kpj_api_format_post($post);
                $entry['ga4'] = [
                    'pageviews' => (int) ($item['pageviews'] ?? 0),
                    'users'     => (int) ($item['users'] ?? $item['activeUsers'] ?? 0),
                ];
                $trending[] = $entry;

                if (count($trending) >= 10) break;
            }
        }
    }

    // Fallback: if GA4 data unavailable, use comment count
    if (empty($trending)) {
        $q = new WP_Query([
            'posts_per_page' => 10,
            'post_status'    => 'publish',
            'orderby'        => 'comment_count',
            'order'          => 'DESC',
            'date_query'     => [['after' => '30 days ago']],
        ]);
        $trending = array_map('kpj_api_format_post', $q->posts);
    }

    $data = [
        'posts'     => $trending,
        'source'    => file_exists($metrics_file) ? 'ga4' : 'comment_count',
        'generated' => current_time('c'),
    ];

    set_transient($cache_key, $data, HOUR_IN_SECONDS);

    $response = new WP_REST_Response($data);
    $response->header('X-KPJ-Cache', 'MISS');
    return $response;
}

/* ── 6. Ensure categories/tags/media are exposed in REST ── */
add_action('init', function () {
    global $wp_taxonomies;
    if (isset($wp_taxonomies['category'])) {
        $wp_taxonomies['category']->show_in_rest = true;
    }
    if (isset($wp_taxonomies['post_tag'])) {
        $wp_taxonomies['post_tag']->show_in_rest = true;
    }
}, 25);

/* ── 7. Cache invalidation on post save ─────────────────── */
add_action('save_post', function ($post_id, WP_Post $post) {
    if ($post->post_status !== 'publish') return;
    delete_transient('kpj_api_home_v1');
    delete_transient('kpj_api_trending_v1');
}, 10, 2);
