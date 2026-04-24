<?php
/**
 * KPOP JOURNAL — Google News Sitemap (AIOSEO Pro不要)
 *
 * このファイルの内容をテーマの functions.php に追加してください。
 * または、mu-plugins ディレクトリに kpopjournal-news-sitemap.php として配置。
 *
 * 機能:
 *   1. /news-sitemap.xml を動的生成するリライトルール
 *   2. 直近48時間の公開記事からXMLを動的生成
 *   3. パイプライン側からのXMLアップロード用REST APIエンドポイント
 *   4. robots.txt に Googlebot-News 許可を自動追加
 *
 * 設置方法（2つから選択）:
 *   A) テーマ functions.php に追記:
 *      このファイルの内容を functions.php の末尾に貼り付け
 *   B) mu-plugins として配置:
 *      wp-content/mu-plugins/kpopjournal-news-sitemap.php にアップロード
 *      （mu-plugins は自動有効化されるため管理画面操��不要）
 *
 * 設置後: WordPress管理画面 → 設定 → パーマリンク → 「変更を保存」をクリック
 * （リライトルールのフラッシュが必要）
 */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 1. リライトルール: /news-sitemap.xml ��� 動的��成
// ━━━━━━━━━━━━━━━━��━━━━━━━━━━━━━━━

add_action('init', function () {
    add_rewrite_rule(
        '^news-sitemap\.xml$',
        'index.php?kpj_news_sitemap=1',
        'top'
    );
});

add_filter('query_vars', function ($vars) {
    $vars[] = 'kpj_news_sitemap';
    return $vars;
});

// ━━━━━��━━━━━━━━━━━━━━━━━━━━━━━━━━
// 2. news-sitemap.xml 動的生成
// ━━━━━━━━━━━━━━━━━━━━━━��━━━━━━━━━

add_action('template_redirect', function () {
    if (!get_query_var('kpj_news_sitemap')) {
        return;
    }

    // パイプラインからアップロードされたXMLがあればそれを優先
    $cached_xml = get_option('kpj_news_sitemap_xml', '');
    $cached_time = get_option('kpj_news_sitemap_updated', '');

    if ($cached_xml && $cached_time) {
        $updated = strtotime($cached_time);
        // 2時間以内のキャッシュなら使用
        if ($updated && (time() - $updated) < 7200) {
            header('Content-Type: application/xml; charset=UTF-8');
            header('X-Robots-Tag: noindex');
            header('Cache-Control: public, max-age=1800');
            echo $cached_xml;
            exit;
        }
    }

    // キャッシュがない/古い場合は動的生成
    $xml = kpj_generate_news_sitemap();

    header('Content-Type: application/xml; charset=UTF-8');
    header('X-Robots-Tag: noindex');
    header('Cache-Control: public, max-age=1800');
    echo $xml;
    exit;
});


/**
 * 直近48時間の公開記事からニュースサイトマップXMLを生成
 */
function kpj_generate_news_sitemap() {
    $args = array(
        'post_type'      => 'post',
        'post_status'    => 'publish',
        'posts_per_page' => 1000,
        'orderby'        => 'date',
        'order'          => 'DESC',
        'date_query'     => array(
            array(
                'after'     => '48 hours ago',
                'inclusive' => true,
            ),
        ),
        'no_found_rows'          => true,
        'update_post_term_cache' => true,
        'update_post_meta_cache' => false,
    );

    $query = new WP_Query($args);
    $entries = '';

    if ($query->have_posts()) {
        while ($query->have_posts()) {
            $query->the_post();
            $post_id = get_the_ID();

            $title = html_entity_decode(get_the_title(), ENT_XML1, 'UTF-8');
            $title = wp_strip_all_tags($title);
            // XML特殊文字をエスケープ
            $title = esc_xml($title);

            $link = esc_url(get_permalink());
            $pub_date = get_the_date('c'); // ISO 8601

            // カテゴリからキーワードを取得
            $categories = get_the_category($post_id);
            $keywords = array();
            foreach ($categories as $cat) {
                $keywords[] = $cat->name;
            }
            // タグも追加
            $tags = get_the_tags($post_id);
            if ($tags) {
                foreach ($tags as $tag) {
                    $keywords[] = $tag->name;
                }
            }
            $keywords = array_slice(array_unique($keywords), 0, 10);
            $kw_xml = '';
            if (!empty($keywords)) {
                $kw_xml = "\n        <news:keywords>" . esc_xml(implode(', ', $keywords)) . "</news:keywords>";
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
            $entries .= "    </news:news>\n";
            $entries .= "  </url>\n";
        }
        wp_reset_postdata();
    }

    $xml  = '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
    $xml .= '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' . "\n";
    $xml .= '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' . "\n";
    $xml .= $entries;
    $xml .= '</urlset>';

    return $xml;
}


/**
 * esc_xml ヘルパー（WordPress 5.5+は内蔵、旧版用フォールバック）
 */
if (!function_exists('esc_xml')) {
    function esc_xml($text) {
        $safe_text = wp_check_invalid_utf8($text);
        $safe_text = htmlspecialchars($safe_text, ENT_XML1 | ENT_QUOTES, 'UTF-8');
        return $safe_text;
    }
}


// ━━━━━━━━━━━━━━━━━━━━━━━━���━━━━━━━
// 3. REST API エンドポイント（パイプラインからのアップロード用）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/news-sitemap', array(
        'methods'             => 'POST',
        'callback'            => 'kpj_update_news_sitemap',
        'permission_callback' => function () {
            return current_user_can('manage_options');
        },
    ));
});

function kpj_update_news_sitemap(WP_REST_Request $request) {
    $xml = $request->get_param('news_sitemap_xml');
    $updated = $request->get_param('news_sitemap_updated');

    if (empty($xml)) {
        return new WP_REST_Response(array(
            'success' => false,
            'message' => 'news_sitemap_xml is required',
        ), 400);
    }

    update_option('kpj_news_sitemap_xml', $xml, false);
    update_option('kpj_news_sitemap_updated', $updated ?: current_time('c'), false);

    return new WP_REST_Response(array(
        'success' => true,
        'message' => 'News sitemap updated',
        'size'    => strlen($xml),
    ));
}


// ━━━━━━━━━━━━━━━━━━━━━���━━━━━━━━━━
// 4. robots.txt に Googlebot-News 許可を自動追加
// ━━━━━━━━━━���━━━━━━━���━━━━━━━━━━━━━

add_filter('robots_txt', function ($output, $public) {
    if ($public) {
        $site_url = home_url();
        $additions = "\n# Google News\n";
        $additions .= "User-agent: Googlebot-News\n";
        $additions .= "Allow: /\n";
        $additions .= "\nSitemap: {$site_url}/news-sitemap.xml\n";

        // 既に含まれていなければ追加
        if (strpos($output, 'Googlebot-News') === false) {
            $output .= $additions;
        }
        // news-sitemap.xml が含まれていなければ追加
        if (strpos($output, 'news-sitemap.xml') === false) {
            $output .= "Sitemap: {$site_url}/news-sitemap.xml\n";
        }
    }
    return $output;
}, 100, 2);


// ━━━━━━━━━━━━━━━━━━━��━━━━━━━━━━━━
// 5. パーマリンクフラッシュ時にリライトルールを確実に登録
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

register_activation_hook(__FILE__, function () {
    add_rewrite_rule(
        '^news-sitemap\.xml$',
        'index.php?kpj_news_sitemap=1',
        'top'
    );
    flush_rewrite_rules();
});
