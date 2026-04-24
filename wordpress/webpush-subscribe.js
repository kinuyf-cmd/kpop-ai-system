/**
 * K-POP Journal — Webプッシュ通知 購読登録スクリプト
 *
 * WordPressテーマの footer.php で読み込む:
 *   <script src="/wp-content/themes/your-theme/webpush-subscribe.js" defer></script>
 *
 * 購読ボタンのHTML例:
 *   <button id="kpj-push-subscribe" style="display:none">通知を受け取る</button>
 */

(function() {
  'use strict';

  // VAPID公開鍵（config/sns_config.json の webpush.vapid_public_key と同じ値を設定）
  // サーバー側で生成した公開鍵を Base64 URL-safe 形式で貼り付ける
  const VAPID_PUBLIC_KEY = '';  // TODO: 生成後に設定

  const SUBSCRIBE_ENDPOINT = '/wp-json/kpopjournal/v1/webpush/subscribe';
  const UNSUBSCRIBE_ENDPOINT = '/wp-json/kpopjournal/v1/webpush/unsubscribe';

  const btn = document.getElementById('kpj-push-subscribe');
  if (!btn) return;

  // Service Worker 対応チェック
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    console.log('[KPJ Push] ブラウザがWebプッシュ未対応');
    return;
  }

  // Base64 URL-safe → Uint8Array 変換
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; ++i) {
      arr[i] = raw.charCodeAt(i);
    }
    return arr;
  }

  // 現在の購読状態を確認
  async function checkSubscription() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    updateButton(!!sub);
    return sub;
  }

  function updateButton(isSubscribed) {
    btn.style.display = 'inline-block';
    if (isSubscribed) {
      btn.textContent = '通知をオフにする';
      btn.classList.add('kpj-push-active');
    } else {
      btn.textContent = '速報通知を受け取る';
      btn.classList.remove('kpj-push-active');
    }
  }

  // 購読登録
  async function subscribe() {
    try {
      if (!VAPID_PUBLIC_KEY) {
        console.warn('[KPJ Push] VAPID公開鍵が未設定');
        return;
      }

      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
      });

      // サーバーへ購読情報を送信
      await fetch(SUBSCRIBE_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sub.toJSON()),
      });

      updateButton(true);
      console.log('[KPJ Push] 購読登録完了');
    } catch (err) {
      if (Notification.permission === 'denied') {
        console.log('[KPJ Push] 通知が拒否されています');
        btn.textContent = '通知がブロックされています';
        btn.disabled = true;
      } else {
        console.error('[KPJ Push] 購読失敗:', err);
      }
    }
  }

  // 購読解除
  async function unsubscribe() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await sub.unsubscribe();

        // サーバーへ解除を通知
        await fetch(UNSUBSCRIBE_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        });
      }
      updateButton(false);
      console.log('[KPJ Push] 購読解除完了');
    } catch (err) {
      console.error('[KPJ Push] 解除失敗:', err);
    }
  }

  // ボタンクリックハンドラ
  btn.addEventListener('click', async function() {
    const sub = await checkSubscription();
    if (sub) {
      await unsubscribe();
    } else {
      await subscribe();
    }
  });

  // Service Worker 登録 & 初期状態チェック
  navigator.serviceWorker.register('/sw.js').then(function() {
    checkSubscription();
  }).catch(function(err) {
    console.error('[KPJ Push] SW登録失敗:', err);
  });
})();
