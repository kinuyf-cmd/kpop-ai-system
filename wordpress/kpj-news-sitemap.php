<?php
/**
 * Plugin Name: KPJ News Sitemap
 * Description: Google News Sitemap — AIOSEOのPro限定空レスポンスを上書きし、直近48時間の記事をnews:仕様で配信
 * Version: 1.0.0
 * Author: KPOP JOURNAL
 *
 * 設置場所: wp-content/mu-plugins/kpj-news-sitemap.php
 *   mu-plugins は通常プラグインより先にロードされるため、
 *   AIOSEOのルーティングを確実に上書きできる。
 *
 * 解決する問題:
 *   - AIOSEO無料版が /news-sitemap.xml を空XMLで横取りしている
 *   - XML Sitemap & Google News プラグインとの競合（無効化済み）
 *   - robots.txt の Googlebot-News セクション構文破損
 */

if (!defined('ABSPATH')) {
    exit;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 0. AIOSEOのニュースサイトマップを無効化
//    AIOSEO ���フィルタ 'aioseo_sitemap_types' で有効なサイト
//    マップタイプを制御している。'news' を除去すれば空XML問題が解消。
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// 方法A: AIOSEO の news sitemap 出力を無効化
add_filter('aioseo_sitemap_types', function ($types) {
    if (is_array($types)) {
        $types = array_filter($types, function ($t) {
            return $t !== 'news';
        });
    }
    return $types;
}, 1);

// 方法B: AIOSEO �� news-sitemap.xml をハンドルする前にインターセプト
// parse_request は template_redirect より早い段��で発火する
add_action('parse_request', function ($wp) {
    // URL パスをチェック
    $request_uri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '';
    $path = parse_url($request_uri, PHP_URL_PATH);
    $path = rtrim($path, '/');

    if ($path !== '/news-sitemap.xml') {
        return;
    }

    // ここに到達 = /news-sitemap.xml へのリ���エスト
    kpj_serve_news_sitemap();
    exit; // AIOSEOに制御を渡さない
}, 1); // 優先度1 = 最速

// 方法C: ��らに早い段階（send_headers）でもキャッチ
// ConoHa のキャッシュが parse_request をバイパスするケースの保険
add_action('send_headers', function () {
    $request_uri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '';
    $path = parse_url($request_uri, PHP_URL_PATH);
    $path = rtrim($path, '/');

    if ($path !== '/news-sitemap.xml') {
        return;
    }

    kpj_serve_news_sitemap();
    exit;
}, 1);


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 1. ニュースサイトマップ配信
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function kpj_serve_news_sitemap() {
    // パイプラインからアップロードされたXMLキャッシュを優先
    $cached_xml  = get_option('kpj_news_sitemap_xml', '');
    $cached_time = get_option('kpj_news_sitemap_updated', '');

    if ($cached_xml && $cached_time) {
        $updated = strtotime($cached_time);
        // 2時間以内のキャッシュなら使用
        if ($updated && (time() - $updated) < 7200) {
            kpj_output_xml($cached_xml);
            return;
        }
    }

    // キャッシュ切れ or 未設定 → WP_Query で動的生成
    $xml = kpj_generate_news_sitemap();

    // 生成結果をキャッシュ（次回リクエスト高速化）
    update_option('kpj_news_sitemap_xml', $xml, false);
    update_option('kpj_news_sitemap_updated', current_time('c'), false);

    kpj_output_xml($xml);
}

function kpj_output_xml($xml) {
    // LiteSpeed Cache / ConoHa キャッシュが介入しないようヘッダ制御
    if (function_exists('litespeed_purge_single')) {
        // LiteSpeed に明示的にキャッシュさせない（動的なので）
        do_action('litespeed_control_set_nocache', 'news-sitemap dynamic');
    }

    status_header(200);
    header('Content-Type: application/xml; charset=UTF-8');
    header('X-Robots-Tag: noindex');
    header('Cache-Control: public, max-age=1800, s-maxage=1800');
    header('X-KPJ-News-Sitemap: custom-v1.0');
    echo $xml;
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 2. 動的 XML 生成（直近48時間）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function kpj_generate_news_sitemap() {
    $args = array(
        'post_type'              => 'post',
        'post_status'            => 'publish',
        'posts_per_page'         => 1000,
        'orderby'                => 'date',
        'order'                  => 'DESC',
        'date_query'             => array(
            array(
                'after'     => '48 hours ago',
                'inclusive' => true,
            ),
        ),
        'no_found_rows'          => true,
        'update_post_term_cache' => true,
        'update_post_meta_cache' => false,
    );

    $query   = new WP_Query($args);
    $entries = '';
    $count   = 0;

    if ($query->have_posts()) {
        while ($query->have_posts()) {
            $query->the_post();
            $post_id = get_the_ID();

            $title = html_entity_decode(get_the_title(), ENT_XML1, 'UTF-8');
            $title = wp_strip_all_tags($title);
            $title = kpj_esc_xml($title);

            $link     = esc_url(get_permalink());
            $pub_date = get_the_date('c'); // ISO 8601

            // カテゴリ + タグからキーワード抽出
            $keywords = array();
            $categories = get_the_category($post_id);
            foreach ($categories as $cat) {
                $keywords[] = $cat->name;
            }
            $tags = get_the_tags($post_id);
            if ($tags) {
                foreach ($tags as $tag) {
                    $keywords[] = $tag->name;
                }
            }
            $keywords = array_slice(array_unique($keywords), 0, 10);
            $kw_xml   = '';
            if (!empty($keywords)) {
                $kw_xml = "\n        <news:keywords>" . kpj_esc_xml(implode(', ', $keywords)) . "</news:keywords>";
            }

            // サムネイル画像（Google Discover 最適化）
            $image_xml = '';
            $thumb_id  = get_post_thumbnail_id($post_id);
            if ($thumb_id) {
                $thumb_url = wp_get_attachment_url($thumb_id);
                if ($thumb_url) {
                    $image_xml  = "\n    <image:image>";
                    $image_xml .= "\n      <image:loc>" . esc_url($thumb_url) . "</image:loc>";
                    $image_xml .= "\n      <image:title>" . $title . "</image:title>";
                    $image_xml .= "\n    </image:image>";
                }
            }

            $entries .= "  <url>\n";
            $entries .= "    <loc>{$link}</loc>\n";
            $entries .= "    <news:news>\n";
            $entries .= "      <news:publication>\n";
            $entries .= "        <news:name>KPOP JOURNAL</news:name>\n";
            $entries .= "        <news:language>ja</news:language>\n";
            $entries .= "      </news:publication>\n";
            $entries .= "      <news:publication_date>{$pub_date}</news:publication_date>\n";
            $entries .= "      <news:title>{$title}</news:title>{$kw_xml}\n";
            $entries .= "    </news:news>{$image_xml}\n";
            $entries .= "  </url>\n";
            $count++;
        }
        wp_reset_postdata();
    }

    $generated = current_time('c');
    $xml  = '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
    $xml .= "<!-- KPJ News Sitemap | {$count} articles | Generated: {$generated} -->\n";
    $xml .= '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' . "\n";
    $xml .= '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"' . "\n";
    $xml .= '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">' . "\n";
    $xml .= $entries;
    $xml .= '</urlset>';

    return $xml;
}


/**
 * XML 安全エスケープ
 */
function kpj_esc_xml($text) {
    if (function_exists('esc_xml')) {
        return esc_xml($text);
    }
    $safe = wp_check_invalid_utf8($text);
    return htmlspecialchars($safe, ENT_XML1 | ENT_QUOTES, 'UTF-8');
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 3. REST API（パイプラインからのアップロード受付）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/news-sitemap', array(
        array(
            'methods'             => 'POST',
            'callback'            => 'kpj_rest_update_news_sitemap',
            'permission_callback' => function () {
                return current_user_can('manage_options');
            },
        ),
        array(
            'methods'             => 'GET',
            'callback'            => 'kpj_rest_get_news_sitemap_status',
            'permission_callback' => function () {
                return current_user_can('manage_options');
            },
        ),
    ));
});

function kpj_rest_update_news_sitemap(WP_REST_Request $request) {
    $xml     = $request->get_param('news_sitemap_xml');
    $updated = $request->get_param('news_sitemap_updated');

    if (empty($xml)) {
        return new WP_REST_Response(array(
            'success' => false,
            'message' => 'news_sitemap_xml is required',
        ), 400);
    }

    update_option('kpj_news_sitemap_xml', $xml, false);
    update_option('kpj_news_sitemap_updated', $updated ?: current_time('c'), false);

    // LiteSpeed Cache パージ（news-sitemap.xml のキャッシュを即時更新）
    if (function_exists('litespeed_purge_url')) {
        litespeed_purge_url(home_url('/news-sitemap.xml'));
    }

    return new WP_REST_Response(array(
        'success'  => true,
        'message'  => 'News sitemap updated',
        'size'     => strlen($xml),
        'updated'  => $updated ?: current_time('c'),
    ));
}

function kpj_rest_get_news_sitemap_status(WP_REST_Request $request) {
    $xml     = get_option('kpj_news_sitemap_xml', '');
    $updated = get_option('kpj_news_sitemap_updated', '');

    return new WP_REST_Response(array(
        'has_cache'  => !empty($xml),
        'updated'    => $updated,
        'size'       => strlen($xml),
        'url_count'  => substr_count($xml, '<url>'),
    ));
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 4. robots.txt 修正
//    既存の壊れた Googlebot-News エントリを除去し、正しい形式で追加。
//    AIOSEOやテーマが追加した壊れた行もクリーンアップする。
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

add_filter('robots_txt', function ($output, $public) {
    if (!$public) {
        return $output;
    }

    $site_url = home_url();

    // 既存の壊れた Googlebot-News セクションを除去
    // パターン: "User-agent: Googlebot-News" から次の空行 or User-agent まで
    $output = preg_replace(
        '/User-agent:\s*Googlebot-News[^\n]*\n(?:[^\n]*\n)*?(?=\s*$|\s*User-agent:|\s*Sitemap:)/i',
        '',
        $output
    );

    // 壊れた "Allow: /https://..." 行を除去
    $output = preg_replace('/^Allow:\s*\/https?:\/\/[^\n]+$/m', '', $output);

    // 重複 Sitemap 行のうち news-sitemap.xml のものを除去（後で正しく追加）
    $output = preg_replace('/^Sitemap:\s*[^\n]*news-sitemap\.xml[^\n]*$/m', '', $output);

    // 連続空行をクリーンアップ
    $output = preg_replace('/\n{3,}/', "\n\n", $output);
    $output = rtrim($output) . "\n";

    // 正しい形式で追加
    $output .= "\n# Google News\n";
    $output .= "User-agent: Googlebot-News\n";
    $output .= "Allow: /\n";
    $output .= "\nSitemap: {$site_url}/news-sitemap.xml\n";

    return $output;
}, 9999, 2); // 最後に実行（他プラグインの後）


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 5. サイトマップインデックスにニュースサイトマップを追加
//    AIOSEOの sitemap.xml に news-sitemap.xml へのリンクを注入
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

add_filter('aioseo_sitemap_indexes', function ($indexes) {
    if (!is_array($indexes)) {
        return $indexes;
    }

    $news_entry = array(
        'loc'     => home_url('/news-sitemap.xml'),
        'lastmod' => current_time('c'),
    );

    // 既に含まれていなければ追加
    $already = false;
    foreach ($indexes as $idx) {
        if (isset($idx['loc']) && strpos($idx['loc'], 'news-sitemap') !== false) {
            $already = true;
            break;
        }
    }
    if (!$already) {
        $indexes[] = $news_entry;
    }

    return $indexes;
}, 10);
