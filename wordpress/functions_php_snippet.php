
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// KPJ News Sitemap — functions.php 追記用 v1.2
// AIOSEO の空 news-sitemap.xml を上書きし、直近48時間の記事を配信
// PHP 7.4+ 完全互換
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if ( ! function_exists( 'kpj_ns_serve' ) ) :

add_filter('aioseo_sitemap_types', function ($types) {
    if (!is_array($types)) { return $types; }
    return array_filter($types, function ($t) { return $t !== 'news'; });
}, 1);

add_action('parse_request', 'kpj_ns_intercept', 1);
add_action('send_headers', 'kpj_ns_intercept', 1);

function kpj_ns_intercept() {
    $uri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '';
    $path = parse_url($uri, PHP_URL_PATH);
    if ($path === false) { return; }
    $path = rtrim($path, '/');
    if ($path !== '/news-sitemap.xml') { return; }
    kpj_ns_serve();
    exit;
}

function kpj_ns_serve() {
    $xml = get_option('kpj_news_sitemap_xml', '');
    $ts  = get_option('kpj_news_sitemap_updated', '');
    if ($xml && $ts && (time() - strtotime($ts)) < 7200) {
        kpj_ns_out($xml);
        return;
    }
    $xml = kpj_ns_gen();
    update_option('kpj_news_sitemap_xml', $xml, false);
    update_option('kpj_news_sitemap_updated', current_time('c'), false);
    kpj_ns_out($xml);
}

function kpj_ns_out($xml) {
    status_header(200);
    header('Content-Type: application/xml; charset=UTF-8');
    header('X-Robots-Tag: noindex');
    header('Cache-Control: public, max-age=1800');
    header('X-KPJ-News-Sitemap: custom-v1.2');
    echo $xml;
}

function kpj_ns_gen() {
    $q = new WP_Query(array(
        'post_type'      => 'post',
        'post_status'    => 'publish',
        'posts_per_page' => 1000,
        'orderby'        => 'date',
        'order'          => 'DESC',
        'date_query'     => array( array( 'after' => '48 hours ago', 'inclusive' => true ) ),
        'no_found_rows'  => true,
    ));
    $entries = '';
    $n = 0;
    while ($q->have_posts()) {
        $q->the_post();
        $raw_title = html_entity_decode(get_the_title(), ENT_XML1, 'UTF-8');
        $t = htmlspecialchars(wp_strip_all_tags($raw_title), ENT_XML1 | ENT_QUOTES, 'UTF-8');
        $u = esc_url(get_permalink());
        $d = get_the_date('c');

        $kw = array();
        $cats = get_the_category();
        foreach ($cats as $c) { $kw[] = $c->name; }
        $tags = get_the_tags();
        if ($tags) { foreach ($tags as $tg) { $kw[] = $tg->name; } }
        $kw = array_slice(array_unique($kw), 0, 10);

        $kwx = '';
        if (!empty($kw)) {
            $kw_escaped = htmlspecialchars(implode(', ', $kw), ENT_XML1 | ENT_QUOTES, 'UTF-8');
            $kwx = "\n        <news:keywords>" . $kw_escaped . "</news:keywords>";
        }

        $img = '';
        $tid = get_post_thumbnail_id();
        if ($tid) {
            $tu = wp_get_attachment_url($tid);
            if ($tu) {
                $img = "\n    <image:image>";
                $img .= "\n      <image:loc>" . esc_url($tu) . "</image:loc>";
                $img .= "\n      <image:title>" . $t . "</image:title>";
                $img .= "\n    </image:image>";
            }
        }

        $entries .= "  <url>\n";
        $entries .= "    <loc>" . $u . "</loc>\n";
        $entries .= "    <news:news>\n";
        $entries .= "      <news:publication>\n";
        $entries .= "        <news:name>KPOP JOURNAL</news:name>\n";
        $entries .= "        <news:language>ja</news:language>\n";
        $entries .= "      </news:publication>\n";
        $entries .= "      <news:publication_date>" . $d . "</news:publication_date>\n";
        $entries .= "      <news:title>" . $t . "</news:title>" . $kwx . "\n";
        $entries .= "    </news:news>" . $img . "\n";
        $entries .= "  </url>\n";
        $n++;
    }
    wp_reset_postdata();

    $now = current_time('c');
    $xml = '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
    $xml .= '<!-- KPJ News Sitemap | ' . $n . ' articles | ' . $now . ' -->' . "\n";
    $xml .= '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"';
    $xml .= ' xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"';
    $xml .= ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">' . "\n";
    $xml .= $entries;
    $xml .= '</urlset>';
    return $xml;
}

add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/news-sitemap', array(
        array(
            'methods'             => 'POST',
            'callback'            => 'kpj_ns_rest_update',
            'permission_callback' => function () { return current_user_can('manage_options'); },
        ),
        array(
            'methods'             => 'GET',
            'callback'            => 'kpj_ns_rest_status',
            'permission_callback' => function () { return current_user_can('manage_options'); },
        ),
    ));
});

function kpj_ns_rest_update($req) {
    $xml = $req->get_param('news_sitemap_xml');
    if (empty($xml)) {
        return new WP_REST_Response(array('success' => false, 'message' => 'xml required'), 400);
    }
    update_option('kpj_news_sitemap_xml', $xml, false);
    $ts = $req->get_param('news_sitemap_updated');
    if (!$ts) { $ts = current_time('c'); }
    update_option('kpj_news_sitemap_updated', $ts, false);
    return new WP_REST_Response(array('success' => true, 'size' => strlen($xml)));
}

function kpj_ns_rest_status($req) {
    $xml = get_option('kpj_news_sitemap_xml', '');
    return new WP_REST_Response(array(
        'has_cache' => !empty($xml),
        'updated'   => get_option('kpj_news_sitemap_updated', ''),
        'url_count' => substr_count($xml, '<url>'),
    ));
}

add_filter('robots_txt', 'kpj_ns_fix_robots', 9999, 2);
function kpj_ns_fix_robots($out, $pub) {
    if (!$pub) { return $out; }
    $out = preg_replace('/User-agent:\s*Googlebot-News[^\n]*\n(?:[^\n]*\n)*?(?=\s*$|\s*User-agent:|\s*Sitemap:)/i', '', $out);
    $out = preg_replace('/^Sitemap:\s*[^\n]*news-sitemap\.xml[^\n]*$/m', '', $out);
    $out = preg_replace('/\n{3,}/', "\n\n", rtrim($out));
    $out .= "\n\nUser-agent: Googlebot-News\nAllow: /\n";
    $out .= "\nSitemap: " . home_url('/news-sitemap.xml') . "\n";
    return $out;
}

add_filter('aioseo_sitemap_indexes', 'kpj_ns_add_to_index', 10);
function kpj_ns_add_to_index($idx) {
    if (!is_array($idx)) { return $idx; }
    foreach ($idx as $i) {
        if (isset($i['loc']) && strpos($i['loc'], 'news-sitemap') !== false) {
            return $idx;
        }
    }
    $idx[] = array('loc' => home_url('/news-sitemap.xml'), 'lastmod' => current_time('c'));
    return $idx;
}

endif;
// ━━━ KPJ News Sitemap END ━━━
