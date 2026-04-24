<?php
/**
 * K-POP Journal PWA対応 — functions.php に追記するスニペット
 *
 * 機能:
 *   - manifest.json の <link> タグ挿入
 *   - Service Worker 登録スクリプト挿入
 *   - Apple Touch Icon メタタグ挿入
 *   - theme-color メタタグ挿入
 */

// PWA マニフェスト + メタタグ
add_action('wp_head', function() {
    echo '<link rel="manifest" href="/manifest.json" crossorigin="use-credentials">' . "\n";
    echo '<meta name="theme-color" content="#FF2D55">' . "\n";
    echo '<meta name="apple-mobile-web-app-capable" content="yes">' . "\n";
    echo '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' . "\n";
    echo '<link rel="apple-touch-icon" href="/wp-content/uploads/kpopjournal-icon-192.png">' . "\n";
});

// Service Worker 登録
add_action('wp_footer', function() {
    ?>
    <script>
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function() {
            navigator.serviceWorker.register('/sw.js', { scope: '/' })
                .then(function(reg) {
                    // 自動アップデートチェック（1時間ごと）
                    setInterval(function() { reg.update(); }, 3600000);
                })
                .catch(function() {});
        });
    }
    </script>
    <?php
}, 99);
