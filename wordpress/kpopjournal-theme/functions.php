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

    // パンくず・関連記事・著者・シェア・投票のCSS
    $inline_css = '
    /* Breadcrumb */
    .kpj-breadcrumb{padding:12px 0;font-size:13px;color:#aaa;border-bottom:1px solid rgba(255,255,255,.06)}
    .kpj-breadcrumb__list{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:4px;align-items:center}
    .kpj-breadcrumb__item::after{content:"›";margin-left:8px;color:#666}
    .kpj-breadcrumb__item:last-child::after{content:""}
    .kpj-breadcrumb__item a{color:#e491d4;text-decoration:none}
    .kpj-breadcrumb__item a:hover{text-decoration:underline}
    .kpj-breadcrumb__item--current{color:#fff;font-weight:500;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

    /* Related Posts */
    .kpj-related{margin-top:48px;padding-top:32px;border-top:2px solid rgba(228,145,212,.2)}
    .kpj-related__title{font-size:20px;font-weight:700;margin-bottom:20px;color:#fff;position:relative;padding-left:16px}
    .kpj-related__title::before{content:"";position:absolute;left:0;top:4px;width:4px;height:22px;background:linear-gradient(180deg,#e491d4,#9b59b6);border-radius:2px}

    /* Author Box */
    .kpj-single__author{display:flex;gap:16px;align-items:center;padding:24px;margin-top:32px;background:rgba(255,255,255,.04);border-radius:12px;border:1px solid rgba(255,255,255,.08)}
    .kpj-single__author-avatar{border-radius:50%;width:48px;height:48px}
    .kpj-single__author-name{color:#fff;font-size:15px}
    .kpj-single__author-bio{color:#aaa;font-size:13px;margin-top:4px;line-height:1.5}

    /* Share Buttons */
    .kpj-single__share{display:flex;align-items:center;gap:12px;margin-top:24px;padding:16px 0;border-top:1px solid rgba(255,255,255,.06)}
    .kpj-single__share-label{color:#888;font-size:13px;font-weight:500}
    .kpj-single__share-btn{padding:8px 20px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;border:none;cursor:pointer;transition:all .2s}
    .kpj-single__share-btn--x{background:#000;color:#fff;border:1px solid #333}
    .kpj-single__share-btn--x:hover{background:#1a1a2e;border-color:#e491d4}
    .kpj-single__share-btn--copy{background:rgba(228,145,212,.15);color:#e491d4;border:1px solid rgba(228,145,212,.3)}
    .kpj-single__share-btn--copy:hover{background:rgba(228,145,212,.25)}

    /* Fan Poll */
    .kpj-poll{margin:32px 0;padding:24px;background:linear-gradient(135deg,rgba(228,145,212,.08),rgba(155,89,182,.08));border-radius:16px;border:1px solid rgba(228,145,212,.2)}
    .kpj-poll__title{font-size:17px;font-weight:700;color:#fff;margin-bottom:16px}
    .kpj-poll__options{display:flex;flex-direction:column;gap:8px}
    .kpj-poll__option{display:flex;align-items:center;gap:12px;padding:12px 16px;background:rgba(255,255,255,.04);border-radius:10px;cursor:pointer;border:1px solid rgba(255,255,255,.08);transition:all .2s}
    .kpj-poll__option:hover{border-color:rgba(228,145,212,.4);background:rgba(228,145,212,.08)}
    .kpj-poll__option--selected{border-color:#e491d4;background:rgba(228,145,212,.12)}
    .kpj-poll__bar{height:6px;background:rgba(255,255,255,.1);border-radius:3px;flex:1;overflow:hidden}
    .kpj-poll__bar-fill{height:100%;background:linear-gradient(90deg,#e491d4,#9b59b6);border-radius:3px;transition:width .5s ease}
    .kpj-poll__count{color:#aaa;font-size:12px;min-width:40px;text-align:right}
    .kpj-poll__total{text-align:center;color:#888;font-size:12px;margin-top:12px}

    /* AdSense Ad Slot */
    .kpj-ad{margin:24px 0;text-align:center}
    ';
    wp_add_inline_style('kpj-main', $inline_css);
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

    // Trending 5 (most commented in last 2 days)
    $trending_q = new WP_Query([
        'posts_per_page' => 5,
        'post_status'    => 'publish',
        'orderby'        => 'comment_count',
        'order'          => 'DESC',
        'date_query'     => [['after' => '2 days ago']],
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

/* ── 6. /wp-json/kpopjournal/v1/posts/<id>/related ──────── */
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/posts/(?P<id>\d+)/related', [
        'methods'             => 'GET',
        'callback'            => 'kpj_api_related',
        'permission_callback' => '__return_true',
        'args' => [
            'id' => [
                'validate_callback' => fn($v) => is_numeric($v),
                'sanitize_callback' => 'absint',
            ],
            'count' => [
                'default'           => 4,
                'sanitize_callback' => fn($v) => min(absint($v), 8),
            ],
        ],
    ]);
});

function kpj_api_related(WP_REST_Request $request): WP_REST_Response {
    $post_id = $request['id'];
    $count   = $request->get_param('count') ?: 4;
    $post    = get_post($post_id);

    if (!$post || $post->post_status !== 'publish') {
        return new WP_REST_Response(['error' => 'Post not found'], 404);
    }

    $cache_key = "kpj_related_{$post_id}_v1";
    $cached    = get_transient($cache_key);
    if ($cached !== false) {
        $response = new WP_REST_Response($cached);
        $response->header('X-KPJ-Cache', 'HIT');
        return $response;
    }

    // 元記事のカテゴリ・タグ・タイトルトークンを取得
    $cats     = wp_get_post_categories($post_id);
    $tags     = wp_get_post_tags($post_id, ['fields' => 'ids']);
    $title    = get_the_title($post);
    $title_tokens = kpj_tokenize_title($title);

    // 候補取得: 同カテゴリ記事を最大40件
    $candidates = new WP_Query([
        'category__in'        => $cats,
        'post__not_in'        => [$post_id],
        'posts_per_page'      => 40,
        'ignore_sticky_posts' => 1,
        'post_status'         => 'publish',
    ]);

    $scored = [];
    while ($candidates->have_posts()) {
        $candidates->the_post();
        $cand_id = get_the_ID();
        $score   = 0;

        // カテゴリ一致 (max 25)
        $cand_cats = wp_get_post_categories($cand_id);
        $cat_overlap = count(array_intersect($cats, $cand_cats));
        $score += min($cat_overlap * 12, 25);

        // タグ一致 (max 30)
        $cand_tags = wp_get_post_tags($cand_id, ['fields' => 'ids']);
        $tag_overlap = count(array_intersect($tags ?: [], $cand_tags ?: []));
        $score += min($tag_overlap * 10, 30);

        // タイトルキーワード共起 (max 25)
        $cand_tokens = kpj_tokenize_title(get_the_title());
        $token_overlap = count(array_intersect($title_tokens, $cand_tokens));
        $score += min($token_overlap * 8, 25);

        // 鮮度ボーナス: 7日以内 +10, 30日以内 +5
        $days_old = (time() - get_post_time('U', true)) / 86400;
        if ($days_old <= 7) $score += 10;
        elseif ($days_old <= 30) $score += 5;

        // サムネあり +10
        if (has_post_thumbnail($cand_id)) $score += 10;

        $scored[] = ['score' => $score, 'post' => get_post()];
    }
    wp_reset_postdata();

    // スコア降順ソート
    usort($scored, fn($a, $b) => $b['score'] - $a['score']);
    $top = array_slice($scored, 0, $count);

    $related = array_map(fn($item) => array_merge(
        kpj_api_format_post($item['post']),
        ['relevance_score' => $item['score']]
    ), $top);

    $data = [
        'post_id'   => $post_id,
        'related'   => $related,
        'generated' => current_time('c'),
    ];

    set_transient($cache_key, $data, 2 * HOUR_IN_SECONDS);

    $response = new WP_REST_Response($data);
    $response->header('X-KPJ-Cache', 'MISS');
    return $response;
}

function kpj_tokenize_title(string $title): array {
    preg_match_all('/[a-zA-Z]{2,}|[\x{3041}-\x{3093}\x{30A1}-\x{30F6}\x{30FC}]{2,}|[\x{4E00}-\x{9FFF}]{2,}/u', mb_strtolower($title), $matches);
    return array_values(array_unique($matches[0] ?? []));
}

/* ── 7. Ensure categories/tags/media are exposed in REST ── */
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
    delete_transient("kpj_related_{$post_id}_v1");
}, 10, 2);

/* ── 8. ポップアップボタンから件数表示を削除 ─────────────── */
add_action('template_redirect', function () {
    if (!is_front_page()) return;
    ob_start(function ($html) {
        // 「(開催中N件 / 予定N件)」の件数表示を除去
        return preg_replace(
            '/(\全ポップアップ情報はこちら)\s*\(開催中\d+件\s*\/\s*予定\d+件\)/',
            '$1',
            $html
        );
    });
});

/* ═══════════════════════════════════════════════════════════
 *  PAGE SPEED — WebP変換 & Google Fonts最適化
 * ═══════════════════════════════════════════════════════════ */

/* ── 9. WebP変換: アップロード時にWebPコピーを自動生成 ──── */
function kpj_convert_to_webp($upload) {
    if (!in_array($upload['type'], ['image/jpeg', 'image/png'], true)) {
        return $upload;
    }
    if (!function_exists('imagewebp')) {
        return $upload; // GDライブラリWebP未対応時はスキップ
    }

    $file    = $upload['file'];
    $webp    = preg_replace('/\.(jpe?g|png)$/i', '.webp', $file);
    $quality = 80;

    if ($upload['type'] === 'image/jpeg') {
        $img = @imagecreatefromjpeg($file);
    } else {
        $img = @imagecreatefrompng($file);
        if ($img) {
            imagepalettetotruecolor($img);
            imagealphablending($img, true);
            imagesavealpha($img, true);
        }
    }

    if ($img) {
        imagewebp($img, $webp, $quality);
        imagedestroy($img);
    }

    return $upload;
}
add_filter('wp_handle_upload', 'kpj_convert_to_webp');

/* ── 10. WebP srcset: <img>を<picture>+<source type=webp>に変換 */
function kpj_webp_srcset($content) {
    if (is_admin() || empty($content)) {
        return $content;
    }

    return preg_replace_callback(
        '/<img\b([^>]*)\bsrc=["\']([^"\']+\.(jpe?g|png))["\']([^>]*)>/i',
        function ($m) {
            $before  = $m[1];
            $src     = $m[2];
            $ext     = $m[3];
            $after   = $m[4];
            $img_tag = $m[0];

            $webp_src = preg_replace('/\.(jpe?g|png)$/i', '.webp', $src);

            // srcset属性があればWebP版も生成
            $webp_srcset = '';
            if (preg_match('/srcset=["\']([^"\']+)["\']/i', $before . $after, $ss)) {
                $webp_srcset = preg_replace('/\.(jpe?g|png)\b/i', '.webp', $ss[1]);
                $webp_srcset = ' srcset="' . $webp_srcset . '"';
            }

            // sizes属性を引き継ぎ
            $sizes = '';
            if (preg_match('/sizes=["\']([^"\']+)["\']/i', $before . $after, $sz)) {
                $sizes = ' sizes="' . $sz[1] . '"';
            }

            return '<picture>'
                . '<source type="image/webp" srcset="' . esc_attr($webp_src) . '"' . $webp_srcset . $sizes . '>'
                . $img_tag
                . '</picture>';
        },
        $content
    );
}
add_filter('the_content', 'kpj_webp_srcset', 99);
add_filter('post_thumbnail_html', 'kpj_webp_srcset', 99);

/* ═══════════════════════════════════════════════════════════
 *  AdSense — 記事内広告自動挿入
 * ═══════════════════════════════════════════════════════════ */

/* ── 12. AdSense広告スロットをh2前・記事末尾に自動挿入 ──── */
function kpj_adsense_ad_unit() {
    $client = defined('ADSENSE_CLIENT_ID') ? ADSENSE_CLIENT_ID : (getenv('ADSENSE_CLIENT_ID') ?: 'ca-pub-XXXXXXXX');
    $slot   = defined('ADSENSE_AD_SLOT')   ? ADSENSE_AD_SLOT   : (getenv('ADSENSE_AD_SLOT')   ?: 'XXXXXXXX');

    return '<div class="kpj-ad">'
        . '<ins class="adsbygoogle" style="display:block"'
        . ' data-ad-client="' . esc_attr($client) . '"'
        . ' data-ad-slot="' . esc_attr($slot) . '"'
        . ' data-ad-format="auto"'
        . ' data-full-width-responsive="true"></ins>'
        . '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>'
        . '</div>';
}

function kpj_insert_ads_in_content($content) {
    // 管理画面・フィード・固定ページではスキップ
    if (is_admin() || is_feed() || !is_singular('post')) {
        return $content;
    }

    // 1000字未満の短い記事には広告を入れない（UX保護）
    $text_length = mb_strlen(strip_tags($content));
    if ($text_length < 1000) {
        return $content;
    }

    $ad = kpj_adsense_ad_unit();

    // h2タグの位置をすべて検出
    $h2_pattern = '/<h2[\s>]/i';
    preg_match_all($h2_pattern, $content, $matches, PREG_OFFSET_CAPTURE);

    if (empty($matches[0])) {
        // h2がない場合は末尾にのみ広告追加
        return $content . $ad;
    }

    $h2_positions = $matches[0];
    $insert_positions = [];

    // 最初のh2の直前に広告1つ
    if (isset($h2_positions[0])) {
        $insert_positions[] = $h2_positions[0][1];
    }

    // 3番目のh2の直前に広告1つ
    if (isset($h2_positions[2])) {
        $insert_positions[] = $h2_positions[2][1];
    }

    // 後ろから挿入（オフセットがずれないように）
    rsort($insert_positions);
    foreach ($insert_positions as $pos) {
        $content = substr($content, 0, $pos) . $ad . substr($content, $pos);
    }

    // 記事末尾に広告1つ（関連記事の前 = the_content の末尾）
    $content .= $ad;

    return $content;
}
// WebP変換(priority 99)より前に実行
add_filter('the_content', 'kpj_insert_ads_in_content', 20);

/* ── 11. Google Fonts preconnect & preload最適化 ────────── */
add_action('wp_head', function () {
    echo '<link rel="preconnect" href="https://fonts.googleapis.com" crossorigin>' . "\n";
    echo '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' . "\n";
}, 1);

/* ═══════════════════════════════════════════════════════════
 *  FAN POLL — ファン投票機能
 *  ショートコード: [kpj_poll question="質問" options="選択肢1,選択肢2,選択肢3"]
 * ═══════════════════════════════════════════════════════════ */

function kpj_poll_shortcode($atts) {
    $atts = shortcode_atts([
        'question' => '',
        'options'  => '',
        'id'       => '',
    ], $atts, 'kpj_poll');

    if (!$atts['question'] || !$atts['options']) return '';

    $poll_id = $atts['id'] ?: 'poll_' . md5($atts['question']);
    $options = array_map('trim', explode(',', $atts['options']));
    if (count($options) < 2) return '';

    $votes = get_option("kpj_poll_{$poll_id}", []);
    $total = array_sum($votes);
    $voted = isset($_COOKIE["kpj_voted_{$poll_id}"]);

    $html = '<div class="kpj-poll" data-poll-id="' . esc_attr($poll_id) . '">';
    $html .= '<h3 class="kpj-poll__title">' . esc_html($atts['question']) . '</h3>';
    $html .= '<div class="kpj-poll__options">';

    foreach ($options as $i => $opt) {
        $count = $votes[$i] ?? 0;
        $pct = $total > 0 ? round(($count / $total) * 100) : 0;
        $selected = $voted ? ' kpj-poll__option--voted' : '';
        $html .= '<div class="kpj-poll__option' . $selected . '" data-index="' . $i . '">'
            . '<span class="kpj-poll__label">' . esc_html($opt) . '</span>'
            . '<div class="kpj-poll__bar"><div class="kpj-poll__bar-fill" style="width:' . $pct . '%"></div></div>'
            . '<span class="kpj-poll__count">' . ($voted ? "{$pct}%" : '') . '</span>'
            . '</div>';
    }
    $html .= '</div>';
    if ($total > 0) {
        $html .= '<p class="kpj-poll__total">' . number_format($total) . '票</p>';
    }
    $html .= '</div>';
    return $html;
}
add_shortcode('kpj_poll', 'kpj_poll_shortcode');

/* ── 投票AJAXハンドラー ────────────────────────────────────── */
add_action('wp_ajax_kpj_vote', 'kpj_handle_vote');
add_action('wp_ajax_nopriv_kpj_vote', 'kpj_handle_vote');
function kpj_handle_vote() {
    check_ajax_referer('kpj_nonce', 'nonce');
    $poll_id = sanitize_text_field($_POST['poll_id'] ?? '');
    $index = intval($_POST['index'] ?? -1);
    if (!$poll_id || $index < 0) wp_send_json_error('Invalid');
    if (isset($_COOKIE["kpj_voted_{$poll_id}"])) wp_send_json_error('Already voted');

    $votes = get_option("kpj_poll_{$poll_id}", []);
    $votes[$index] = ($votes[$index] ?? 0) + 1;
    update_option("kpj_poll_{$poll_id}", $votes);
    setcookie("kpj_voted_{$poll_id}", '1', time() + 86400 * 30, '/');

    $total = array_sum($votes);
    $results = [];
    foreach ($votes as $i => $c) {
        $results[$i] = $total > 0 ? round(($c / $total) * 100) : 0;
    }
    wp_send_json_success(['results' => $results, 'total' => $total]);
}

/* ── 投票UIのJS ────────────────────────────────────────────── */
add_action('wp_footer', function () {
    if (!is_single()) return;
    ?>
    <script>
    document.addEventListener('click',function(e){
        var o=e.target.closest('.kpj-poll__option');
        if(!o||o.classList.contains('kpj-poll__option--voted'))return;
        var p=o.closest('.kpj-poll');if(!p)return;
        fetch(kpjData.ajaxUrl,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
            body:'action=kpj_vote&nonce='+kpjData.nonce+'&poll_id='+p.dataset.pollId+'&index='+o.dataset.index})
        .then(function(r){return r.json()}).then(function(d){
            if(!d.success)return;
            p.querySelectorAll('.kpj-poll__option').forEach(function(opt){
                opt.classList.add('kpj-poll__option--voted');
                var pct=d.data.results[opt.dataset.index]||0;
                var f=opt.querySelector('.kpj-poll__bar-fill');if(f)f.style.width=pct+'%';
                var c=opt.querySelector('.kpj-poll__count');if(c)c.textContent=pct+'%';
            });
            var t=p.querySelector('.kpj-poll__total');
            if(t)t.textContent=d.data.total.toLocaleString()+'票';
            else{var np=document.createElement('p');np.className='kpj-poll__total';
                np.textContent=d.data.total.toLocaleString()+'票';p.querySelector('.kpj-poll__options').after(np);}
        });
    });
    </script>
    <?php
});
