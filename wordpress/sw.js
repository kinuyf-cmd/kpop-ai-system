/**
 * K-POP Journal Service Worker v2.0
 *
 * Features:
 *   - Webプッシュ通知受信
 *   - オフラインキャッシュ（記事ページ / CSS / 画像）
 *   - ネットワーク優先 + キャッシュフォールバック戦略
 *   - 古いキャッシュの自動クリーンアップ
 *
 * 設置: WordPressルート (/sw.js)
 */

const CACHE_VERSION = 'kpj-v2';
const CACHE_NAME = `${CACHE_VERSION}-${new Date().toISOString().slice(0,10)}`;
const OFFLINE_URL = '/offline/';

// キャッシュ対象パターン
const CACHE_PATTERNS = [
  /\.css(\?.*)?$/,
  /\.js(\?.*)?$/,
  /\.woff2?(\?.*)?$/,
  /kpopjournal-icon/,
];

// 静的プリキャッシュ
const PRECACHE_URLS = [
  '/',
  '/manifest.json',
];

// プッシュ通知受信
self.addEventListener('push', function(event) {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch (e) {
    data = {
      title: 'K-POP Journal',
      body: event.data.text(),
      url: 'https://www.kpopjournal.tokyo',
    };
  }

  const options = {
    body: data.body || '',
    icon: data.icon || '/wp-content/uploads/kpopjournal-icon-192.png',
    badge: data.badge || '/wp-content/uploads/kpopjournal-badge-72.png',
    image: data.image || undefined,
    tag: data.tag || 'kpopjournal-news',
    renotify: data.renotify !== false,
    requireInteraction: data.requireInteraction || false,
    vibrate: data.vibrate || [200, 100, 200],
    data: {
      url: data.url || 'https://www.kpopjournal.tokyo',
      timestamp: Date.now(),
    },
    actions: [
      { action: 'open', title: '記事を読む' },
      { action: 'close', title: '閉じる' },
    ],
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'K-POP Journal', options)
  );
});

// 通知クリック処理
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  if (event.action === 'close') return;

  const url = event.notification.data?.url || 'https://www.kpopjournal.tokyo';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      for (const client of clientList) {
        if (client.url === url && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});

// インストール — プリキャッシュ
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(PRECACHE_URLS).catch(function() {
        // プリキャッシュ失敗は致命的ではない
      });
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

// アクティベーション — 古いキャッシュ削除
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames
          .filter(function(name) {
            return name.startsWith('kpj-') && name !== CACHE_NAME;
          })
          .map(function(name) {
            return caches.delete(name);
          })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

// Fetch — ネットワーク優先 + キャッシュフォールバック
self.addEventListener('fetch', function(event) {
  const url = new URL(event.request.url);

  // 管理画面・APIリクエストはスルー
  if (url.pathname.startsWith('/wp-admin') ||
      url.pathname.startsWith('/wp-json') ||
      url.pathname.startsWith('/wp-login') ||
      event.request.method !== 'GET') {
    return;
  }

  // 静的アセット（CSS/JS/フォント）はキャッシュ優先
  const isStaticAsset = CACHE_PATTERNS.some(function(p) { return p.test(url.pathname); });

  if (isStaticAsset) {
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        if (cached) {
          // バックグラウンドで更新
          fetch(event.request).then(function(response) {
            if (response && response.status === 200) {
              caches.open(CACHE_NAME).then(function(cache) {
                cache.put(event.request, response);
              });
            }
          }).catch(function() {});
          return cached;
        }
        return fetch(event.request).then(function(response) {
          if (response && response.status === 200) {
            var clone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, clone);
            });
          }
          return response;
        });
      })
    );
    return;
  }

  // HTMLページ（記事）はネットワーク優先
  if (event.request.headers.get('accept') &&
      event.request.headers.get('accept').includes('text/html')) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        if (response && response.status === 200) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      }).catch(function() {
        return caches.match(event.request).then(function(cached) {
          return cached || caches.match(OFFLINE_URL) || new Response(
            '<html><head><meta charset="utf-8"><title>K-POP Journal - Offline</title></head>' +
            '<body style="font-family:sans-serif;text-align:center;padding:60px 20px;background:#0A0A0F;color:#F1F5F9">' +
            '<h1 style="color:#FF2D55">K-POP Journal</h1>' +
            '<p>現在オフラインです。インターネット接続を確認してください。</p>' +
            '<a href="/" style="color:#7B61FF">ホームに戻る</a></body></html>',
            { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
          );
        });
      })
    );
    return;
  }

  // 画像はキャッシュ優先
  if (url.pathname.match(/\.(png|jpg|jpeg|gif|webp|svg|ico)(\?.*)?$/)) {
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        return cached || fetch(event.request).then(function(response) {
          if (response && response.status === 200) {
            var clone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, clone);
            });
          }
          return response;
        }).catch(function() {
          return new Response('', { status: 404 });
        });
      })
    );
    return;
  }
});
