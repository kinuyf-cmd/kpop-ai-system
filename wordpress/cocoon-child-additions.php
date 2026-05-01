
// ============================================================
// K-POP JOURNAL 改善追加 (2026-05-01)
// ============================================================

/* ── AdSense広告をh2前・記事末尾に自動挿入 ──────────────── */
function kpj_adsense_ad_unit() {
    $client = defined('ADSENSE_CLIENT_ID') ? ADSENSE_CLIENT_ID : (getenv('ADSENSE_CLIENT_ID') ?: 'ca-pub-XXXXXXXX');
    $slot   = defined('ADSENSE_AD_SLOT')   ? ADSENSE_AD_SLOT   : (getenv('ADSENSE_AD_SLOT')   ?: 'XXXXXXXX');
    return '<div class="kpj-ad" style="margin:24px 0;text-align:center">'
        . '<ins class="adsbygoogle" style="display:block"'
        . ' data-ad-client="' . esc_attr($client) . '"'
        . ' data-ad-slot="' . esc_attr($slot) . '"'
        . ' data-ad-format="auto"'
        . ' data-full-width-responsive="true"></ins>'
        . '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>'
        . '</div>';
}

function kpj_insert_ads_in_content($content) {
    if (is_admin() || is_feed() || !is_singular('post')) return $content;
    if (mb_strlen(strip_tags($content)) < 1000) return $content;

    $ad = kpj_adsense_ad_unit();
    preg_match_all('/<h2[\s>]/i', $content, $matches, PREG_OFFSET_CAPTURE);
    if (empty($matches[0])) return $content . $ad;

    $positions = [];
    if (isset($matches[0][0])) $positions[] = $matches[0][0][1];
    if (isset($matches[0][2])) $positions[] = $matches[0][2][1];
    rsort($positions);
    foreach ($positions as $pos) {
        $content = substr($content, 0, $pos) . $ad . substr($content, $pos);
    }
    return $content . $ad;
}
add_filter('the_content', 'kpj_insert_ads_in_content', 20);

/* ── WebP自動変換 ─────────────────────────────────────────── */
function kpj_convert_to_webp($upload) {
    if (!function_exists('imagewebp')) return $upload;
    $file = $upload['file'] ?? '';
    $type = $upload['type'] ?? '';
    if (!in_array($type, ['image/jpeg', 'image/png'])) return $upload;
    $webp = preg_replace('/\.(jpe?g|png)$/i', '.webp', $file);
    if ($type === 'image/jpeg') {
        $img = imagecreatefromjpeg($file);
    } else {
        $img = imagecreatefrompng($file);
        imagesavealpha($img, true);
    }
    if ($img) {
        imagewebp($img, $webp, 80);
        imagedestroy($img);
    }
    return $upload;
}
add_filter('wp_handle_upload', 'kpj_convert_to_webp');

/* ── ファン投票ショートコード [kpj_poll] ──────────────────── */
function kpj_poll_shortcode($atts) {
    $atts = shortcode_atts(['question'=>'','options'=>'','id'=>''], $atts, 'kpj_poll');
    if (!$atts['question'] || !$atts['options']) return '';
    $poll_id = $atts['id'] ?: 'poll_' . md5($atts['question']);
    $options = array_map('trim', explode(',', $atts['options']));
    if (count($options) < 2) return '';

    $votes = get_option("kpj_poll_{$poll_id}", []);
    $total = array_sum($votes);
    $voted = isset($_COOKIE["kpj_voted_{$poll_id}"]);

    $css = '<style>.kpj-poll{margin:32px 0;padding:24px;background:linear-gradient(135deg,rgba(228,145,212,.08),rgba(155,89,182,.08));border-radius:16px;border:1px solid rgba(228,145,212,.2)}.kpj-poll__title{font-size:17px;font-weight:700;margin-bottom:16px}.kpj-poll__options{display:flex;flex-direction:column;gap:8px}.kpj-poll__option{display:flex;align-items:center;gap:12px;padding:12px 16px;background:rgba(0,0,0,.02);border-radius:10px;cursor:pointer;border:1px solid rgba(0,0,0,.08);transition:all .2s}.kpj-poll__option:hover{border-color:rgba(228,145,212,.4);background:rgba(228,145,212,.08)}.kpj-poll__bar{height:6px;background:rgba(0,0,0,.1);border-radius:3px;flex:1;overflow:hidden}.kpj-poll__bar-fill{height:100%;background:linear-gradient(90deg,#e491d4,#9b59b6);border-radius:3px;transition:width .5s}.kpj-poll__count{font-size:12px;min-width:40px;text-align:right;color:#888}.kpj-poll__total{text-align:center;color:#888;font-size:12px;margin-top:12px}</style>';

    $html = $css . '<div class="kpj-poll" data-poll-id="' . esc_attr($poll_id) . '">';
    $html .= '<h3 class="kpj-poll__title">' . esc_html($atts['question']) . '</h3>';
    $html .= '<div class="kpj-poll__options">';
    foreach ($options as $i => $opt) {
        $count = $votes[$i] ?? 0;
        $pct = $total > 0 ? round(($count / $total) * 100) : 0;
        $vc = $voted ? ' kpj-poll__option--voted' : '';
        $html .= '<div class="kpj-poll__option' . $vc . '" data-index="' . $i . '">'
            . '<span>' . esc_html($opt) . '</span>'
            . '<div class="kpj-poll__bar"><div class="kpj-poll__bar-fill" style="width:' . $pct . '%"></div></div>'
            . '<span class="kpj-poll__count">' . ($voted ? "{$pct}%" : '') . '</span></div>';
    }
    $html .= '</div>';
    if ($total > 0) $html .= '<p class="kpj-poll__total">' . number_format($total) . '票</p>';
    $html .= '</div>';
    return $html;
}
add_shortcode('kpj_poll', 'kpj_poll_shortcode');

add_action('wp_ajax_kpj_vote', 'kpj_handle_vote');
add_action('wp_ajax_nopriv_kpj_vote', 'kpj_handle_vote');
function kpj_handle_vote() {
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
    foreach ($votes as $i => $c) $results[$i] = $total > 0 ? round(($c / $total) * 100) : 0;
    wp_send_json_success(['results' => $results, 'total' => $total]);
}

add_action('wp_footer', function () {
    if (!is_singular('post')) return;
    ?>
    <script>
    document.addEventListener('click',function(e){
        var o=e.target.closest('.kpj-poll__option');
        if(!o||o.classList.contains('kpj-poll__option--voted'))return;
        var p=o.closest('.kpj-poll');if(!p)return;
        fetch('<?php echo admin_url("admin-ajax.php"); ?>',{method:'POST',
            headers:{'Content-Type':'application/x-www-form-urlencoded'},
            body:'action=kpj_vote&poll_id='+p.dataset.pollId+'&index='+o.dataset.index})
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
