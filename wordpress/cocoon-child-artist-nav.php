
// ============================================================
// アーティスト一覧ナビ — サイドバー+フッター (2026-05-01)
// ============================================================

function kpj_artist_nav_widget() {
    $artists = [
        ['BTS', '/bts-matome/'],
        ['BLACKPINK', '/blackpink-matome/'],
        ['aespa', '/aespa-matome/'],
        ['TWICE', '/twice-matome/'],
        ['NewJeans', '/newjeans-matome/'],
        ['IVE', '/ive-matome/'],
        ['LE SSERAFIM', '/le-sserafim-matome/'],
        ['Stray Kids', '/stray-kids-matome/'],
        ['SEVENTEEN', '/seventeen-matome/'],
        ['ENHYPEN', '/enhypen-matome/'],
        ['ITZY', '/itzy-matome/'],
        ['NMIXX', '/nmixx-matome/'],
        ['BABYMONSTER', '/babymonster-matome/'],
        ['EXO', '/exo-matome/'],
        ['NCT', '/nct-matome/'],
        ['BIGBANG', '/bigbang-matome/'],
    ];

    $html = '<div class="kpj-artist-nav">';
    $html .= '<h3 class="kpj-artist-nav__title">アーティスト一覧</h3>';
    $html .= '<div class="kpj-artist-nav__grid">';
    foreach ($artists as $a) {
        $html .= '<a href="' . esc_url(home_url($a[1])) . '" class="kpj-artist-nav__item">' . esc_html($a[0]) . '</a>';
    }
    $html .= '</div></div>';
    return $html;
}

// サイドバーにウィジェットとして表示
add_action('wp_footer', function() {
    // サイドバーに追加するCSS
    echo '<style>
    .kpj-artist-nav{margin:24px 0;padding:20px;background:#f8f4ff;border-radius:12px;border:1px solid #e8d5f5}
    .kpj-artist-nav__title{font-size:16px;font-weight:700;margin-bottom:12px;color:#333}
    .kpj-artist-nav__grid{display:flex;flex-wrap:wrap;gap:6px}
    .kpj-artist-nav__item{display:inline-block;padding:6px 14px;background:#fff;border:1px solid #e0d0f0;border-radius:20px;font-size:13px;color:#7b2d8e;text-decoration:none;font-weight:500;transition:all .2s}
    .kpj-artist-nav__item:hover{background:#9b59b6;color:#fff;border-color:#9b59b6}
    </style>';
});

// 記事末尾にアーティスト一覧を自動挿入
add_filter('the_content', function($content) {
    if (!is_singular('post') || is_admin()) return $content;
    return $content . kpj_artist_nav_widget();
}, 90);
