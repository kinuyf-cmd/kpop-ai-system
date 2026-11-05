<?php
/**
 * GOLF PORT 自社バナー(GolfPortHouseBanner)— 記事末尾に1枠だけ出す運営関連サービス案内。
 *
 * 設計(2026-11-05・MKT house banner 施策):
 *  - 画像を使わない(HTML/CSS + インラインSVG)。権利問題なし・CLSなし・外部JSなし。
 *  - 表示可否は WP オプション `kpop_golfport_banner` で制御(コードのデプロイ不要で停止できる)。
 *      {"enabled":true,"variant":"a","categories":["kdrama","k-pop"]}
 *    既定は enabled=false。categories が空なら「どの記事にも出さない」(許可リスト方式)。
 *  - 出さないページ: 非 post / popup カテゴリ / プレビュー / フィード。
 *  - 計測: GA4 イベント house_banner_view(50%可視で1回) / house_banner_click。
 *    gtag が無い環境では何もしない(既存 affiliate_click と同じ作法)。
 *  - リンクは rel="nofollow noopener"(SEO目的の内部リンク構造にしない)。
 */

if ( ! defined( 'ABSPATH' ) ) {
	return;
}

const KPOP_GHB_OPTION = 'kpop_golfport_banner';
const KPOP_GHB_BASE   = 'https://golfport.top';

/** variant 定義。a=無料記録(初回の本命)、b=コーチ(比較テスト候補・初回は出さない)。 */
function kpop_ghb_variants() {
	return array(
		'a' => array(
			'path'    => '/record',
			'content' => 'article_end_free_record',
			'title'   => 'ゴルフの思い出、無料で記録。',
			'sub'     => 'ラウンド・練習・写真をひとつに。',
			'cta'     => 'GOLF PORTを見てみる',
		),
		'b' => array(
			'path'    => '/',
			'content' => 'article_end_coach',
			'title'   => 'あなたに合うゴルフコーチを。',
			'sub'     => 'コーチを探して、相談・予約。',
			'cta'     => 'GOLF PORTを見てみる',
		),
	);
}

/** 設定を正規化して返す(壊れた値でも安全側=非表示)。 */
function kpop_ghb_config( $raw = null ) {
	if ( null === $raw ) {
		$raw = get_option( KPOP_GHB_OPTION, array() );
	}
	if ( is_string( $raw ) ) {
		$raw = json_decode( $raw, true );
	}
	if ( ! is_array( $raw ) ) {
		$raw = array();
	}
	$variants = kpop_ghb_variants();
	$variant  = ( isset( $raw['variant'] ) && isset( $variants[ $raw['variant'] ] ) ) ? $raw['variant'] : 'a';
	$cats     = array();
	if ( isset( $raw['categories'] ) && is_array( $raw['categories'] ) ) {
		foreach ( $raw['categories'] as $c ) {
			if ( is_string( $c ) && '' !== $c ) {
				$cats[] = $c;
			}
		}
	}
	return array(
		'enabled'    => ! empty( $raw['enabled'] ) && true === (bool) $raw['enabled'],
		'variant'    => $variant,
		'categories' => $cats,
		'campaign'   => ( isset( $raw['campaign'] ) && is_string( $raw['campaign'] ) && preg_match( '/^[a-z0-9_]{1,40}$/', $raw['campaign'] ) )
			? $raw['campaign'] : 'golfport_202611',
	);
}

/**
 * 表示判定(純関数)。
 * @param array $cfg        kpop_ghb_config() の戻り
 * @param array $ctx        is_post(bool) / is_popup(bool) / is_preview(bool) / category_slugs(string[])
 */
function kpop_ghb_should_show( $cfg, $ctx ) {
	if ( empty( $cfg['enabled'] ) || empty( $cfg['categories'] ) ) {
		return false;
	}
	if ( empty( $ctx['is_post'] ) || ! empty( $ctx['is_popup'] ) || ! empty( $ctx['is_preview'] ) ) {
		return false;
	}
	$slugs = isset( $ctx['category_slugs'] ) ? (array) $ctx['category_slugs'] : array();
	return (bool) array_intersect( $cfg['categories'], $slugs );
}

/** UTM 付き遷移先URL。個人情報は入れない。 */
function kpop_ghb_url( $cfg ) {
	$v = kpop_ghb_variants();
	$d = $v[ $cfg['variant'] ];
	return KPOP_GHB_BASE . $d['path'] . '?' . http_build_query(
		array(
			'utm_source'   => 'kpopjournal',
			'utm_medium'   => 'house_banner',
			'utm_campaign' => $cfg['campaign'],
			'utm_content'  => $d['content'],
		),
		'',
		'&',
		PHP_QUERY_RFC3986
	);
}

/** バナーHTML(1回だけ出力するための静的ガード付き)。 */
function kpop_ghb_render( $cfg ) {
	static $rendered = false;
	if ( $rendered ) {
		return ''; // 二重表示防止
	}
	$rendered = true;

	$v   = kpop_ghb_variants();
	$d   = $v[ $cfg['variant'] ];
	$url = kpop_ghb_url( $cfg );

	ob_start();
	?>
<aside class="kpop-ghb" aria-label="運営関連サービスのご案内" data-ghb-variant="<?php echo esc_attr( $cfg['variant'] ); ?>" data-ghb-content="<?php echo esc_attr( $d['content'] ); ?>">
	<p class="kpop-ghb-label">運営関連サービスのご案内</p>
	<a class="kpop-ghb-link" href="<?php echo esc_url( $url ); ?>" rel="nofollow noopener" target="_blank">
		<svg class="kpop-ghb-art" viewBox="0 0 120 120" width="72" height="72" aria-hidden="true" focusable="false">
			<rect width="120" height="120" rx="16" fill="#e8f5ec"/>
			<path d="M0 92c28-14 52-16 120-4v32H0z" fill="#8cc9a0"/>
			<path d="M0 104c34-10 66-10 120 0v16H0z" fill="#5aa874"/>
			<line x1="76" y1="28" x2="76" y2="86" stroke="#3b6b4a" stroke-width="3" stroke-linecap="round"/>
			<path d="M76 28l24 9-24 9z" fill="#e5484d"/>
			<ellipse cx="56" cy="90" rx="9" ry="3.5" fill="#4a8a62"/>
			<circle cx="56" cy="82" r="7" fill="#fff" stroke="#c9d6cd" stroke-width="1.5"/>
		</svg>
		<span class="kpop-ghb-text">
			<span class="kpop-ghb-brand">GOLF PORT</span>
			<span class="kpop-ghb-title"><?php echo esc_html( $d['title'] ); ?></span>
			<span class="kpop-ghb-sub"><?php echo esc_html( $d['sub'] ); ?></span>
		</span>
		<span class="kpop-ghb-cta"><?php echo esc_html( $d['cta'] ); ?><span aria-hidden="true"> →</span></span>
	</a>
</aside>
<style>
.kpop-ghb{margin:2.5em 0 1.5em;padding:0;box-sizing:border-box;min-height:132px}
.kpop-ghb-label{margin:0 0 6px;font-size:12px;line-height:1.4;color:#5b6470}
.kpop-ghb-link{display:flex;align-items:center;gap:16px;padding:16px 18px;min-height:96px;box-sizing:border-box;border:1px solid #cfe3d6;border-radius:12px;background:#f6fbf8;color:#1f2a24;text-decoration:none}
.kpop-ghb-link:hover{background:#eef8f1;border-color:#9fcdb0}
.kpop-ghb-link:focus-visible{outline:3px solid #1d6b3f;outline-offset:2px}
.kpop-ghb-art{flex:0 0 72px;width:72px;height:72px}
.kpop-ghb-text{display:flex;flex-direction:column;gap:2px;flex:1 1 auto;min-width:0}
.kpop-ghb-brand{font-size:12px;font-weight:700;letter-spacing:.06em;color:#1d6b3f}
.kpop-ghb-title{font-size:18px;line-height:1.4;font-weight:700}
.kpop-ghb-sub{font-size:14px;line-height:1.5;color:#3d4852}
.kpop-ghb-cta{flex:0 0 auto;padding:11px 18px;min-height:44px;box-sizing:border-box;border-radius:999px;background:#1d6b3f;color:#fff;font-size:14px;font-weight:700;white-space:nowrap;display:inline-flex;align-items:center}
@media (max-width:600px){
.kpop-ghb{min-height:196px}
.kpop-ghb-link{flex-wrap:wrap;gap:12px;padding:14px}
.kpop-ghb-art{flex-basis:56px;width:56px;height:56px}
.kpop-ghb-text{flex-basis:calc(100% - 72px)}
.kpop-ghb-title{font-size:17px}
.kpop-ghb-cta{flex:1 1 100%;justify-content:center}
}
</style>
<script>
(function () {
  var el = document.querySelector('.kpop-ghb');
  if (!el || typeof window.gtag !== 'function') { return; }
  var p = {
    banner_id: 'golfport',
    banner_variant: el.getAttribute('data-ghb-variant') || '',
    banner_content: el.getAttribute('data-ghb-content') || '',
    page_path: window.location.pathname
  };
  var sent = false;
  function view() { if (sent) { return; } sent = true; window.gtag('event', 'house_banner_view', p); }
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { view(); io.disconnect(); } });
    }, { threshold: 0.5 });
    io.observe(el);
  }
  var a = el.querySelector('a');
  if (a) { a.addEventListener('click', function () { window.gtag('event', 'house_banner_click', p); }, true); }
})();
</script>
	<?php
	return ob_get_clean();
}

/** テンプレートから呼ぶ入口。出す条件を満たさなければ何も出力しない。 */
function kpop_render_golfport_house_banner( $post_id = 0 ) {
	if ( is_admin() || is_feed() || is_embed() ) {
		return;
	}
	$cfg = kpop_ghb_config();
	if ( ! $cfg['enabled'] ) {
		return; // 無効時は DB クエリも走らせない
	}
	$post_id = $post_id ? $post_id : get_the_ID();
	$cats    = get_the_category( $post_id );
	$slugs   = array();
	if ( is_array( $cats ) ) {
		foreach ( $cats as $c ) {
			$slugs[] = $c->slug;
		}
	}
	$ctx = array(
		'is_post'        => is_singular( 'post' ),
		'is_popup'       => in_category( 'popup', $post_id ),
		'is_preview'     => is_preview(),
		'category_slugs' => $slugs,
	);
	if ( kpop_ghb_should_show( $cfg, $ctx ) ) {
		echo kpop_ghb_render( $cfg ); // phpcs:ignore WordPress.Security.EscapeOutput -- 内部で esc_* 済み
	}
}
