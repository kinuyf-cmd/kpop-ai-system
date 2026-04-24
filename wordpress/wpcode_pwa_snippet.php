// === KPJ PWA + コメント拡張 (WPCode用スニペット) ===
// WPCode管理画面 → Add Snippet → Add Your Custom Code
// Code Type: PHP Snippet
// Insert Method: Auto Insert / Run Everywhere
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// ─── PART 1: /manifest.json 配信 ───
add_action('parse_request', function ($wp) {
    $path = trim($_SERVER['REQUEST_URI'] ?? '', '/');
    $path = strtok($path, '?');

    if ($path === 'manifest.json') {
        header('Content-Type: application/manifest+json; charset=utf-8');
        header('Cache-Control: public, max-age=86400');
        header('Access-Control-Allow-Origin: *');
        echo <<<'KPJ_MANIFEST'
{
  "name": "K-POP Journal",
  "short_name": "KPJ",
  "description": "K-POP最新ニュース・チャート・ファンダム情報を毎日配信",
  "start_url": "/?utm_source=pwa&utm_medium=homescreen",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait-primary",
  "background_color": "#0A0A0F",
  "theme_color": "#FF2D55",
  "lang": "ja",
  "dir": "ltr",
  "categories": ["entertainment", "news"],
  "icons": [
    {"src": "/wp-content/uploads/kpopjournal-icon-72.png", "sizes": "72x72", "type": "image/png"},
    {"src": "/wp-content/uploads/kpopjournal-icon-96.png", "sizes": "96x96", "type": "image/png"},
    {"src": "/wp-content/uploads/kpopjournal-icon-128.png", "sizes": "128x128", "type": "image/png"},
    {"src": "/wp-content/uploads/kpopjournal-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
    {"src": "/wp-content/uploads/kpopjournal-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
  ],
  "screenshots": [
    {"src": "/wp-content/uploads/kpj-screenshot-wide.png", "sizes": "1280x720", "type": "image/png", "form_factor": "wide", "label": "K-POP Journal - Top Page"},
    {"src": "/wp-content/uploads/kpj-screenshot-mobile.png", "sizes": "390x844", "type": "image/png", "form_factor": "narrow", "label": "K-POP Journal - Mobile"}
  ],
  "shortcuts": [
    {"name": "Latest News", "short_name": "News", "description": "K-POP最新ニュース", "url": "/category/kpop-news/?utm_source=pwa_shortcut", "icons": [{"src": "/wp-content/uploads/kpopjournal-icon-96.png", "sizes": "96x96"}]},
    {"name": "Charts", "short_name": "Chart", "description": "チャートランキング", "url": "/category/chart/?utm_source=pwa_shortcut", "icons": [{"src": "/wp-content/uploads/kpopjournal-icon-96.png", "sizes": "96x96"}]}
  ],
  "related_applications": [],
  "prefer_related_applications": false
}
KPJ_MANIFEST;
        exit;
    }

    // ─── PART 2: /sw.js 配信（Service-Worker-Allowed ヘッダー付き）───
    if ($path === 'sw.js') {
        header('Content-Type: application/javascript; charset=utf-8');
        header('Cache-Control: no-cache');
        header('Service-Worker-Allowed: /');
        // アップロード済みSWファイルを読み込み
        $sw_path = ABSPATH . 'wp-content/uploads/2026/04/kpj-sw.js';
        if (file_exists($sw_path)) {
            readfile($sw_path);
        }
        exit;
    }
}, 1);

// ─── PART 3: PWA ヘッダータグ ───
add_action('wp_head', function () {
    echo '<link rel="manifest" href="/manifest.json" crossorigin="use-credentials">' . "\n";
    echo '<meta name="theme-color" content="#FF2D55">' . "\n";
    echo '<meta name="apple-mobile-web-app-capable" content="yes">' . "\n";
    echo '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' . "\n";
    echo '<link rel="apple-touch-icon" href="/wp-content/uploads/kpopjournal-icon-192.png">' . "\n";
}, 1);

// ─── PART 4: Service Worker 登録スクリプト ───
add_action('wp_footer', function () {
    ?>
    <script>
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function() {
            navigator.serviceWorker.register('/sw.js', { scope: '/' })
                .then(function(reg) {
                    setInterval(function() { reg.update(); }, 3600000);
                })
                .catch(function() {});
        });
    }
    </script>
    <?php
}, 99);

// ─── PART 5: コメント — ハニーポット（bot対策）───
add_action('comment_form_after_fields', function () {
    echo '<div style="display:none !important;"><label>Leave empty</label>';
    echo '<input type="text" name="kpj_hp_field" value="" tabindex="-1" autocomplete="off"></div>';
});
add_filter('preprocess_comment', function ($data) {
    if (!empty($_POST['kpj_hp_field'])) {
        wp_die('スパムと判定されました。');
    }
    return $data;
});

// ─── PART 6: コメント — レート制限（1IP/時間 10件）───
add_filter('preprocess_comment', function ($data) {
    $ip = $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
    $transient_key = 'kpj_comment_rate_' . md5($ip);
    $count = (int) get_transient($transient_key);
    if ($count >= 10) {
        wp_die('コメント投稿の制限に達しました。しばらくしてからお試しください。');
    }
    set_transient($transient_key, $count + 1, HOUR_IN_SECONDS);
    return $data;
}, 1);

// ─── PART 7: コメント — リアクション表示 ───
add_filter('comment_text', function ($text, $comment) {
    $reactions = get_comment_meta($comment->comment_ID, 'kpj_reactions', true);
    if ($reactions && is_array($reactions)) {
        $html = '<div class="kpj-reactions" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">';
        $emojis = ['heart' => '&#10084;&#65039;', 'fire' => '&#128293;', 'laugh' => '&#128514;', 'surprise' => '&#128562;'];
        foreach ($reactions as $type => $count) {
            if (isset($emojis[$type]) && $count > 0) {
                $html .= '<span class="kpj-reaction" data-type="' . esc_attr($type) . '"'
                    . ' style="background:#1E1E2E;border:1px solid #2D2D3F;border-radius:16px;padding:4px 10px;font-size:13px;cursor:pointer">'
                    . $emojis[$type] . ' ' . (int) $count . '</span>';
            }
        }
        $html .= '</div>';
        $text .= $html;
    }
    return $text;
}, 10, 2);

// ─── PART 8: OGP コメント数メタ ───
add_action('wp_head', function () {
    if (is_single()) {
        $count = get_comments_number();
        if ($count > 0) {
            echo '<meta property="og:comments" content="' . (int) $count . '">' . "\n";
        }
    }
}, 20);

// ─── PART 9: REST API — リアクション + Webプッシュ ───
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/comment-reaction', [
        'methods'  => 'POST',
        'callback' => function ($request) {
            $comment_id = (int) $request->get_param('comment_id');
            $type       = sanitize_text_field($request->get_param('type'));
            $allowed    = ['heart', 'fire', 'laugh', 'surprise'];
            if (!in_array($type, $allowed, true) || !$comment_id) {
                return new WP_Error('invalid', '不正なリクエスト', ['status' => 400]);
            }
            $reactions        = get_comment_meta($comment_id, 'kpj_reactions', true) ?: [];
            $reactions[$type] = ($reactions[$type] ?? 0) + 1;
            update_comment_meta($comment_id, 'kpj_reactions', $reactions);
            return ['success' => true, 'reactions' => $reactions];
        },
        'permission_callback' => '__return_true',
    ]);
    register_rest_route('kpopjournal/v1', '/webpush/subscribe', [
        'methods'  => 'POST',
        'callback' => function ($request) {
            $sub = $request->get_json_params();
            if (empty($sub['endpoint']) || empty($sub['keys'])) {
                return new WP_Error('invalid', '不正な購読情報', ['status' => 400]);
            }
            $file = ABSPATH . '../kpop-ai-system/logs/webpush_subscriptions.jsonl';
            file_put_contents($file, json_encode($sub) . "\n", FILE_APPEND | LOCK_EX);
            return ['success' => true];
        },
        'permission_callback' => '__return_true',
    ]);
    register_rest_route('kpopjournal/v1', '/webpush/unsubscribe', [
        'methods'  => 'POST',
        'callback' => function ($request) {
            $endpoint = sanitize_text_field($request->get_param('endpoint'));
            if (!$endpoint) {
                return new WP_Error('invalid', '不正なリクエスト', ['status' => 400]);
            }
            $file = ABSPATH . '../kpop-ai-system/logs/webpush_subscriptions.jsonl';
            if (file_exists($file)) {
                $lines    = file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
                $filtered = array_filter($lines, function ($line) use ($endpoint) {
                    $sub = json_decode($line, true);
                    return ($sub['endpoint'] ?? '') !== $endpoint;
                });
                file_put_contents($file, implode("\n", $filtered) . "\n", LOCK_EX);
            }
            return ['success' => true];
        },
        'permission_callback' => '__return_true',
    ]);
});
