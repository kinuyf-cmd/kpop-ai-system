

// === FAQ構造化データ (FAQPage JSON-LD) 自動挿入 ===
// h2/h3見出し + 直後の段落からFAQ schemaを生成
// h2が3つ以上ある記事のみ対象

add_action('wp_footer', 'kpj_faq_schema_output');
function kpj_faq_schema_output() {
    if (!is_singular('post')) return;

    global $post;
    $content = $post->post_content;

    // HTMLをパースしてh2/h3 + 直後のpを抽出
    if (!preg_match_all('/<h([23])[^>]*>(.*?)<\/h\1>/is', $content, $headings, PREG_OFFSET_CAPTURE)) {
        return;
    }

    // h2が3つ未満ならスキップ
    $h2_count = 0;
    foreach ($headings[1] as $level) {
        if ($level[0] === '2') $h2_count++;
    }
    if ($h2_count < 3) return;

    $faq_items = [];
    foreach ($headings[0] as $i => $match) {
        $heading_text = strip_tags($headings[2][$i][0]);
        $heading_text = trim(html_entity_decode($heading_text, ENT_QUOTES, 'UTF-8'));
        if (empty($heading_text)) continue;

        // 見出し直後のコンテンツから最初の<p>を探す
        $after_heading = substr($content, $match[1] + strlen($match[0]));
        if (preg_match('/<p[^>]*>(.*?)<\/p>/is', $after_heading, $p_match)) {
            // 次の見出しより前にあるpのみ採用
            $next_heading_pos = PHP_INT_MAX;
            if (preg_match('/<h[23][^>]*>/i', $after_heading, $nh_match, PREG_OFFSET_CAPTURE)) {
                $next_heading_pos = $nh_match[0][1];
            }
            $p_pos = strpos($after_heading, $p_match[0]);
            if ($p_pos !== false && $p_pos < $next_heading_pos) {
                $answer_text = strip_tags($p_match[1]);
                $answer_text = trim(html_entity_decode($answer_text, ENT_QUOTES, 'UTF-8'));
                if (!empty($answer_text) && mb_strlen($answer_text) >= 10) {
                    $faq_items[] = [
                        '@type'          => 'Question',
                        'name'           => $heading_text,
                        'acceptedAnswer' => [
                            '@type' => 'Answer',
                            'text'  => $answer_text,
                        ],
                    ];
                }
            }
        }
    }

    if (count($faq_items) < 2) return;

    $schema = [
        '@context'   => 'https://schema.org',
        '@type'      => 'FAQPage',
        'mainEntity' => $faq_items,
    ];

    $json = wp_json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    if (!$json) return;

    echo "\n<!-- KPJ FAQ Schema -->\n";
    echo '<script type="application/ld+json">' . "\n";
    echo $json . "\n";
    echo "</script>\n";
}
