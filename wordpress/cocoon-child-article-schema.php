
// === Article (NewsArticle) 構造化データ JSON-LD 自動挿入 ===
// wp_footer フックで全投稿に NewsArticle schema を出力
// FAQ schema (cocoon-child-faq-schema.php) と同パターン

add_action('wp_footer', 'kpj_article_schema_output');
function kpj_article_schema_output() {
    if (!is_singular('post')) return;

    global $post;

    // 既に JSON-LD の NewsArticle/Article が出力済みならスキップ
    // （AIOSEOプラグイン等との競合回避）
    // ※ wp_footer は本文の後なので、本文内の JSON-LD は検出不可
    //   → テーマ/プラグイン側で出力済みかは wp_head 側で確認が必要だが、
    //     現環境では AIOSEO Free に Article schema 機能がないため常時出力

    $title = get_the_title();
    $url   = get_permalink();
    $desc  = get_the_excerpt();
    if (empty($desc)) {
        $desc = wp_trim_words(strip_tags($post->post_content), 80, '...');
    }
    // 200文字以内に収める
    if (mb_strlen($desc) > 200) {
        $desc = mb_substr($desc, 0, 197) . '...';
    }

    $date_published = get_the_date('c');
    $date_modified  = get_the_modified_date('c');

    // アイキャッチ画像
    $image_url = '';
    $image_width = 0;
    $image_height = 0;
    $thumb_id = get_post_thumbnail_id();
    if ($thumb_id) {
        $img_data = wp_get_attachment_image_src($thumb_id, 'full');
        if ($img_data) {
            $image_url    = $img_data[0];
            $image_width  = $img_data[1];
            $image_height = $img_data[2];
        }
    }

    // カテゴリからセクション名を取得
    $section = 'K-POP';
    $cats = get_the_category();
    if (!empty($cats)) {
        $section = $cats[0]->name;
    }

    // schema 構築
    $schema = array(
        '@context'        => 'https://schema.org',
        '@type'           => 'NewsArticle',
        'headline'        => mb_substr($title, 0, 110),
        'name'            => $title,
        'description'     => $desc,
        'url'             => $url,
        'articleSection'   => $section,
        'inLanguage'      => 'ja',
        'datePublished'   => $date_published,
        'dateModified'    => $date_modified,
        'author'          => array(
            '@type' => 'Organization',
            'name'  => 'KPOP JOURNAL',
            'url'   => 'https://www.kpopjournal.tokyo',
        ),
        'publisher'       => array(
            '@type' => 'Organization',
            'name'  => 'KPOP JOURNAL',
            'url'   => 'https://www.kpopjournal.tokyo',
            'logo'  => array(
                '@type'  => 'ImageObject',
                'url'    => 'https://www.kpopjournal.tokyo/wp-content/uploads/kpop-journal-logo.png',
                'width'  => 600,
                'height' => 60,
            ),
        ),
        'mainEntityOfPage' => array(
            '@type' => 'WebPage',
            '@id'   => $url,
        ),
    );

    // 画像がある場合のみ追加
    if (!empty($image_url)) {
        $img_obj = array(
            '@type' => 'ImageObject',
            'url'   => $image_url,
        );
        if ($image_width > 0)  $img_obj['width']  = $image_width;
        if ($image_height > 0) $img_obj['height'] = $image_height;
        $schema['image'] = $img_obj;
    }

    // キーワード（カテゴリ + タグ）
    $keywords = array();
    foreach ($cats as $c) {
        $keywords[] = $c->name;
    }
    $tags = get_the_tags();
    if ($tags) {
        foreach ($tags as $tg) {
            $keywords[] = $tg->name;
        }
    }
    if (!empty($keywords)) {
        $schema['keywords'] = array_values(array_unique(array_slice($keywords, 0, 10)));
    }

    // ワード数
    $word_count = mb_strlen(strip_tags($post->post_content));
    if ($word_count > 0) {
        $schema['wordCount'] = $word_count;
    }

    $json = wp_json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if (!$json) return;

    echo "\n<!-- KPJ Article Schema -->\n";
    echo '<script type="application/ld+json">' . "\n";
    echo $json . "\n";
    echo "</script>\n";
}
