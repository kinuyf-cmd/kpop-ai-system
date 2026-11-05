<?php
/**
 * GOLF PORT 自社バナー(GolfPortHouseBanner)— 運営関連サービス案内。
 * 設置場所は3つ(個別ON/OFF可・utm_content で区別して計測):
 *   article_footer … 記事末尾・関連記事の直前(kdrama 等の許可カテゴリのみ)
 *   event_page     … 大型イベント特設ページ(授賞式ハブ等)の主要情報の下・関連記事の直前。
 *                    記事IDの許可リスト(event_page_ids)だけ。イベント名が本文に出るだけの記事は対象外。
 *                    同じページでは event_page が優先し article_footer は出さない(1ページ1枠)。
 *   top_sidebar    … トップページ右サイドバーの旧PORT広告枠(A8 top_fixed)の置換・1:1
 *
 * 設計(2026-11-05・MKT house banner 施策):
 *  - 画像を使わない(HTML/CSS + インラインSVG)。権利問題なし・CLSなし・外部JSなし。
 *  - 表示可否は WP オプション `kpop_golfport_banner` で制御(コードのデプロイ不要で停止できる)。
 *      {"enabled":true,"categories":["kdrama"],"article_footer":true,"top_sidebar":false,
 *       "event_page":false,"event_page_ids":[4826,21866,23381,23390]}
 *    既定は enabled=false。enabled は全体のマスタースイッチ。
 *    article_footer は未指定=true(従来挙動)、false で記事末尾だけ停止。
 *    event_page は未指定=false。true かつ ID が event_page_ids にある記事にだけ出る。
 *    新しい大型イベントページを作ったら event_page_ids に記事IDを足す(デプロイ不要)。
 *    top_sidebar は未指定=false。true でトップ右サイドバーのPORT広告をGOLF PORTに置換、
 *    false/削除/enabled=false で PORT 広告が即座に戻る。
 *    categories が空なら記事末尾は「どの記事にも出さない」(許可リスト方式)。
 *  - 出さないページ: 非 post / popup カテゴリ / プレビュー / フィード。
 *  - 計測: GA4 イベント house_banner_view(50%可視で1回) / house_banner_click。
 *    gtag が無い環境では何もしない(既存 affiliate_click と同じ作法)。
 *  - リンクは通常の<a>(同一タブ)。短縮/中継/リダイレクト/nofollow/sponsored/noreferrer 禁止(GOLF PORT確定仕様)。
 *  - 文言に「無料」等の断定表現を使わない(GOLF PORT側で条件確認できるまで)。
 */

if ( ! defined( 'ABSPATH' ) ) {
	return;
}

const KPOP_GHB_OPTION = 'kpop_golfport_banner';
const KPOP_GHB_BASE   = 'https://golfport.top';

/** バナー定義。遷移先は GOLF PORT 側確定仕様で /record 固定(変更は GOLF PORT への事前連絡が必要)。
 *  utm_content は設置場所(半角英小文字・数字・_・40字以内)。同一場所で別クリエイティブなら article_footer_a 等。 */
function kpop_ghb_def( $placement = 'article_footer' ) {
	if ( ! in_array( $placement, array( 'article_footer', 'top_sidebar', 'event_page' ), true ) ) {
		$placement = 'article_footer';
	}
	return array(
		'url_base' => 'https://golfport.top/record',
		'campaign' => 'golf_record_202611',
		'content'  => $placement,
		'title'    => 'ゴルフの思い出、ひとつに。',
		'title_parts' => array( 'ゴルフの思い出、', 'ひとつに。' ), // 狭いスマホで「ひ/とつに。」と切れないよう句の境目で折り返す
		'sub'      => 'ラウンド・練習・写真を記録して振り返る。',
		// スマホで「振/り返る。」のように不自然な位置で改行されないよう、句の境目でだけ折り返す(結合した文字列は sub と同一)。
		'sub_parts' => array( 'ラウンド・練習・写真を', '記録して振り返る。' ),
		'cta'      => 'GOLF PORTを見てみる',
		// GOLF PORT 正式ロゴ(横組み 1637×435 透過PNG)を、再保存・再描画・変形・色変更せず本番の正式ファイルのまま参照する。
		// 縦組み/白抜き/簡略版は存在しない(作らない)。規定: ロゴの高さの半分以上の余白・白または淡色の無地背景。
		'logo_src' => 'https://golfport.top/logo.png',
		'logo_w'   => 1637,
		'logo_h'   => 435,
		'logo_alt' => 'ゴルフポート GOLF PORT',
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
	$cats     = array();
	if ( isset( $raw['categories'] ) && is_array( $raw['categories'] ) ) {
		foreach ( $raw['categories'] as $c ) {
			if ( is_string( $c ) && '' !== $c ) {
				$cats[] = $c;
			}
		}
	}
	$ids = array();
	if ( isset( $raw['event_page_ids'] ) && is_array( $raw['event_page_ids'] ) ) {
		foreach ( $raw['event_page_ids'] as $i ) {
			if ( is_int( $i ) && $i > 0 ) {
				$ids[] = $i;
			}
		}
	}
	return array(
		'enabled'        => ! empty( $raw['enabled'] ) && true === (bool) $raw['enabled'],
		'categories'     => $cats,
		'article_footer' => ! array_key_exists( 'article_footer', $raw ) || ! empty( $raw['article_footer'] ),
		'top_sidebar'    => ! empty( $raw['top_sidebar'] ) && true === (bool) $raw['top_sidebar'],
		'event_page'     => ! empty( $raw['event_page'] ) && true === (bool) $raw['event_page'],
		'event_page_ids' => $ids,
	);
}

/**
 * 表示判定(純関数)。
 * @param array $cfg        kpop_ghb_config() の戻り
 * @param array $ctx        is_post(bool) / is_popup(bool) / is_preview(bool) / category_slugs(string[])
 */
function kpop_ghb_should_show( $cfg, $ctx ) {
	if ( empty( $cfg['enabled'] ) || empty( $cfg['article_footer'] ) || empty( $cfg['categories'] ) ) {
		return false;
	}
	if ( empty( $ctx['is_post'] ) || ! empty( $ctx['is_popup'] ) || ! empty( $ctx['is_preview'] ) ) {
		return false;
	}
	$slugs = isset( $ctx['category_slugs'] ) ? (array) $ctx['category_slugs'] : array();
	return (bool) array_intersect( $cfg['categories'], $slugs );
}

/**
 * 記事ページで出す設置場所を1つだけ決める(純関数)。''=出さない。
 * event_page が article_footer より優先(同じページに2枠出さない)。
 * @param array $ctx  post_id(int) / is_post / is_popup / is_preview / category_slugs
 */
function kpop_ghb_article_placement( $cfg, $ctx ) {
	if ( empty( $cfg['enabled'] ) ) {
		return '';
	}
	if ( empty( $ctx['is_post'] ) || ! empty( $ctx['is_popup'] ) || ! empty( $ctx['is_preview'] ) ) {
		return '';
	}
	$pid = isset( $ctx['post_id'] ) ? (int) $ctx['post_id'] : 0;
	if ( ! empty( $cfg['event_page'] ) && $pid > 0 && in_array( $pid, $cfg['event_page_ids'], true ) ) {
		return 'event_page';
	}
	return kpop_ghb_should_show( $cfg, $ctx ) ? 'article_footer' : '';
}

/** UTM 付き遷移先URL。個人情報は入れない。 */
function kpop_ghb_url( $placement = 'article_footer' ) {
	$d = kpop_ghb_def( $placement );
	// 固定4パラメータのみ。短縮・中継・リダイレクト・utm_term・個人情報は付けない。
	return $d['url_base'] . '?utm_source=kpopjournal&utm_medium=house_banner'
		. '&utm_campaign=' . $d['campaign'] . '&utm_content=' . $d['content'];
}

/** CSS/JS は1ページに1回だけ出す(記事末尾とトップが同居しても二重送信しない)。 */
function kpop_ghb_assets() {
	static $done = false;
	if ( $done ) {
		return '';
	}
	$done = true;
	ob_start();
	?>
<style>
.kpop-ghb{margin:2.5em 0 1.5em;padding:0;box-sizing:border-box;min-height:132px}
.kpop-ghb-label{margin:0 0 6px;font-size:12px;line-height:1.4;color:#64748b}
.kpop-ghb-link{display:flex;align-items:center;gap:16px;padding:20px;min-height:96px;box-sizing:border-box;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc;color:#1e293b;text-decoration:none}
.kpop-ghb-link:hover{background:#f1f5f9;border-color:#cbd5e1}
.kpop-ghb-link:focus-visible{outline:3px solid #1e293b;outline-offset:2px}
.kpop-ghb-logo{display:block;height:30px;width:auto;max-width:100%;align-self:flex-start;margin:0 0 6px}
.kpop-ghb-text{display:flex;flex-direction:column;gap:2px;flex:1 1 auto;min-width:0}
.kpop-ghb-title{font-size:18px;line-height:1.4;font-weight:700}
.kpop-ghb-sub{font-size:14px;line-height:1.5;color:#475569}
.kpop-ghb-ph{display:inline-block}
.kpop-ghb-cta{flex:0 0 auto;padding:11px 18px;min-height:44px;box-sizing:border-box;border-radius:999px;background:#2563eb;color:#fff;font-size:14px;font-weight:700;white-space:nowrap;display:inline-flex;align-items:center}
@media (max-width:600px){
.kpop-ghb{min-height:196px}
.kpop-ghb-link{flex-wrap:wrap;gap:12px;padding:18px}
.kpop-ghb-text{flex-basis:100%}
.kpop-ghb-title{font-size:17px}
.kpop-ghb-cta{flex:1 1 100%;justify-content:center}
}
/* トップ右サイドバー用 1:1(正方形)。上のモバイル規則より後ろに置き、詳細度で確実に上書きする。 */
.kpop-ghb.kpop-ghb--square{width:100%;max-width:300px;min-height:0;margin:0 auto}
.kpop-ghb.kpop-ghb--square .kpop-ghb-label{text-align:center}
.kpop-ghb.kpop-ghb--square .kpop-ghb-link{flex-direction:column;flex-wrap:nowrap;justify-content:center;text-align:center;gap:8px;width:100%;aspect-ratio:1/1;min-height:0;padding:14px}
.kpop-ghb.kpop-ghb--square .kpop-ghb-logo{height:38px;align-self:center;margin:0 auto 6px}
.kpop-ghb.kpop-ghb--square .kpop-ghb-text{flex:0 0 auto;align-items:center;gap:3px;width:100%}
.kpop-ghb.kpop-ghb--square .kpop-ghb-title{font-size:18px}
.kpop-ghb.kpop-ghb--square .kpop-ghb-sub{font-size:13px;line-height:1.5}
.kpop-ghb.kpop-ghb--square .kpop-ghb-cta{flex:0 0 auto;justify-content:center;width:100%;padding:10px 12px}
</style>
<script>
(function () {
  if (typeof window.gtag !== 'function') { return; }
  Array.prototype.forEach.call(document.querySelectorAll('.kpop-ghb'), function (el) {
    if (el.getAttribute('data-ghb-bound')) { return; } // 二重送信防止
    el.setAttribute('data-ghb-bound', '1');
    var p = {
      banner_id: 'golfport',
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
  });
})();
</script>
	<?php
	return ob_get_clean();
}

/** バナーHTML。設置場所ごとに1回だけ(二重表示防止)。 */
function kpop_ghb_render( $cfg, $placement = 'article_footer' ) {
	static $rendered = array();
	if ( ! empty( $rendered[ $placement ] ) ) {
		return ''; // 二重表示防止
	}
	$rendered[ $placement ] = true;

	$d      = kpop_ghb_def( $placement );
	$url    = kpop_ghb_url( $placement );
	$square = ( 'top_sidebar' === $placement );
	$label  = $square ? '運営関連サービス' : '運営関連サービスのご案内';

	ob_start();
	?>
<aside class="kpop-ghb<?php echo $square ? ' kpop-ghb--square' : ''; ?>" aria-label="<?php echo esc_attr( $label ); ?>" data-ghb-content="<?php echo esc_attr( $d['content'] ); ?>">
	<p class="kpop-ghb-label"><?php echo esc_html( $label ); ?></p>
	<a class="kpop-ghb-link" href="<?php echo esc_url( $url ); ?>">
		<span class="kpop-ghb-text">
			<img class="kpop-ghb-logo" src="<?php echo esc_url( $d['logo_src'] ); ?>" alt="<?php echo esc_attr( $d['logo_alt'] ); ?>" width="<?php echo (int) $d['logo_w']; ?>" height="<?php echo (int) $d['logo_h']; ?>" loading="lazy" decoding="async">
			<span class="kpop-ghb-title"><?php foreach ( $d['title_parts'] as $kpop_ghb_part ) { echo '<span class="kpop-ghb-ph">' . esc_html( $kpop_ghb_part ) . '</span>'; } ?></span>
			<span class="kpop-ghb-sub"><?php foreach ( $d['sub_parts'] as $kpop_ghb_part ) { echo '<span class="kpop-ghb-ph">' . esc_html( $kpop_ghb_part ) . '</span>'; } ?></span>
		</span>
		<span class="kpop-ghb-cta"><?php echo esc_html( $d['cta'] ); ?><span aria-hidden="true"> →</span></span>
	</a>
</aside>
	<?php
	return ob_get_clean() . kpop_ghb_assets();
}

/**
 * トップページ右サイドバーの旧PORT広告枠(A8 top_fixed)を置換するHTMLを返す。
 * 出さないとき(トップ以外/OFF)は ''。呼び出し側は '' なら従来の A8 広告をそのまま出す。
 * 外側は従来と同じ .kpop-sidebar-box.kpop-ad-slot(サイドバー並べ替えの広告扱い・位置ルールを維持)。
 */
function kpop_ghb_top_sidebar_html() {
	if ( is_admin() || is_feed() || is_embed() || is_preview() ) {
		return '';
	}
	if ( ! ( is_front_page() || is_home() ) ) {
		return '';
	}
	$cfg = kpop_ghb_config();
	if ( empty( $cfg['enabled'] ) || empty( $cfg['top_sidebar'] ) ) {
		return '';
	}
	$inner = kpop_ghb_render( $cfg, 'top_sidebar' );
	if ( '' === $inner ) {
		return '';
	}
	return '<div class="kpop-sidebar-box kpop-ad-slot kpop-ghb-slot" role="complementary" aria-label="運営関連サービス">' . $inner . '</div>';
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
	if ( ! $cfg['article_footer'] && ! $cfg['event_page'] ) {
		return;
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
		'post_id'        => (int) $post_id,
		'is_post'        => is_singular( 'post' ),
		'is_popup'       => in_category( 'popup', $post_id ),
		'is_preview'     => is_preview(),
		'category_slugs' => $slugs,
	);
	$placement = kpop_ghb_article_placement( $cfg, $ctx );
	if ( '' !== $placement ) {
		echo kpop_ghb_render( $cfg, $placement ); // phpcs:ignore WordPress.Security.EscapeOutput -- 内部で esc_* 済み
	}
}
