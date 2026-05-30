<?php
/**
 * GeneratePress KPOP Child Theme Functions
 */

// 子テーマのスタイルシートを読み込む。
// GeneratePress(親)は自身のスタイルを自前で読み込むため、ここでは
// 子テーマの style.css のみを enqueue する(親を手動 enqueue すると二重読み込みになる)。
add_action( 'wp_enqueue_scripts', function () {
	// バージョンは style.css の更新時刻(filemtime)に連動させる。
	// ハードコード('1.0.0')だとデプロイしても ?ver= が変わらず、ブラウザ/
	// サーバが古い CSS をキャッシュし続けて変更が反映されない事故になる
	// (2026-05-21 発生)。filemtime なら配置のたびに自動でキャッシュバスト。
	$style_path = get_stylesheet_directory() . '/style.css';
	$style_ver  = file_exists( $style_path ) ? (string) filemtime( $style_path ) : '1.0.0';
	wp_enqueue_style(
		'generatepress-kpop',
		get_stylesheet_directory_uri() . '/style.css',
		array( 'generate-style' ), // GeneratePress 親テーマのスタイルハンドルに依存
		$style_ver
	);
} );

/**
 * 速報バー — 「速報」タグ(slug: breaking)の最新4件をページ上部に表示する。
 * 速報記事が無いときは何も出力しない(案Y)。
 *
 * シームレスループ: CSS のみで実現するため、記事リストを2回出力する。
 * トラックを translateX(0 → -50%) で動かすと、後半の複製がちょうど
 * 前半と同じ位置に来るため、繋ぎ目のないループになる(JS不要)。
 */
function kpop_render_breaking_bar() {
	$posts = get_posts( array(
		'post_type'        => 'post',
		'post_status'      => 'publish',
		'tag'              => 'breaking',
		'posts_per_page'   => 4,
		'orderby'          => 'date',
		'order'            => 'DESC',
		'suppress_filters' => false,
	) );

	if ( empty( $posts ) ) {
		return; // 速報なし → バー非表示
	}

	// 1セット分の記事リンクHTMLを組み立てる。
	$items = '';
	foreach ( $posts as $p ) {
		$items .= sprintf(
			'<a class="bar-item" href="%s"><span class="bar-time">%s</span>%s</a>',
			esc_url( get_permalink( $p ) ),
			esc_html( get_the_date( 'n/j H:i', $p ) ),
			esc_html( get_the_title( $p ) )
		);
	}

	echo '<div class="kpop-breaking-bar" role="region" aria-label="速報">';
	echo '<span class="bar-label">速報</span>';
	echo '<div class="bar-track">';
	echo $items; // 1セット目(読み上げ対象)
	// 2セット目: シームレスループ用の複製。スクリーンリーダーには重複させない。
	// 複製セットの <a> はフォーカス不可にする(aria-hidden 下の focusable 違反回避)
	$items_dup = str_replace( '<a class="bar-item"', '<a class="bar-item" tabindex="-1"', $items );
	echo '<span class="bar-dup" aria-hidden="true">' . $items_dup . '</span>';
	echo '</div>'; // .bar-track
	echo '</div>'; // .kpop-breaking-bar
}
add_action( 'wp_body_open', 'kpop_render_breaking_bar' );

/* ==========================================================================
   M1 段階1 — ロゴ分割 + ヘッダー検索 (2026-05-20)
   ui_gap_analysis #2, #3
   ========================================================================== */

/**
 * サイトタイトル「KPOP JOURNAL」を 2 パートに分割する。
 * 「KPOP」= 黒太字、「JOURNAL」= ピンク細字(.logo-journal で着色)。
 * GeneratePress は site-title を 'generate_site_title_output' でフィルタ可能。
 */
add_filter( 'generate_site_title_output', function ( $html ) {
	// site-title 内の「KPOP JOURNAL」テキストを span 分割版に置換。
	return preg_replace(
		'/KPOP\s*JOURNAL/u',
		'KPOP<span class="logo-journal">JOURNAL</span>',
		$html
	);
} );

/**
 * ヘッダー右側に検索ボックスを出力する。
 * GeneratePress の 'generate_after_header_content' フックに差し込む。
 * プレースホルダは元サイト同様「アーティスト・記事を検索」。
 */
function kpop_header_search() {
	?>
	<div class="header-search">
		<form role="search" method="get" action="<?php echo esc_url( home_url( '/' ) ); ?>">
			<label class="screen-reader-text" for="kpop-header-s">サイト内検索</label>
			<input type="search" id="kpop-header-s" name="s"
			       placeholder="アーティスト・記事を検索"
			       value="<?php echo esc_attr( get_search_query() ); ?>">
			<?php // submit ボタン: Pa11y H32.2(form に submit 必須)対応 + 元サイトのボタン一体型に一致。 ?>
			<button type="submit" class="header-search-submit" aria-label="検索">
				<span aria-hidden="true">&#128269;</span>
			</button>
		</form>
	</div>
	<?php
}
add_action( 'generate_after_header_content', 'kpop_header_search' );

/* ==========================================================================
   M1 段階1b — ナビ位置を nav-below-header に変更 (2026-05-20)
   visual_diff_stage1 不具合1 の修正。
   無印 GeneratePress 3.6.1 は設定を
     wp_parse_args( get_option('generate_settings', array()), generate_get_defaults() )
   で解決する(theme-functions.php:21-28 で確認)。
   generate_get_defaults() は 'generate_option_defaults' フィルタを通すため、
   DB option を作らず子テーマでデフォルト自体を上書きできる(子テーマ完結)。
   元サイト: ロゴ行 → その下にナビ独立行 = nav-below-header。
   ========================================================================== */
add_filter( 'generate_option_defaults', function ( $defaults ) {
	$defaults['nav_position_setting'] = 'nav-below-header';
	return $defaults;
} );

/* ==========================================================================
   M1 段階2a — 2カラム比率を 70:30 に (2026-05-20)
   stage2_design §3。GP デフォルトの右サイドバー幅は 25%。
   元サイトは約30% → generate_right_sidebar_width フィルタで 30 に変更。
   GP は generate_smart_content_width() でこの値を使い content 幅を算出する。
   ========================================================================== */
add_filter( 'generate_right_sidebar_width', function () {
	return 30;
} );

/* ==========================================================================
   M1 段階4 — フッター4カラム再構築 (2026-05-20)
   元サイト参照: reference/スクリーンショット 2026-04-25 21.06.33.png(末尾)。
   構造: 中央ロゴ + サブテキスト → 4カラム(CATEGORY/ARTISTS/ABOUT/FOLLOW)
         → 著作権バー。
   実装方式: GP の 'generate_before_footer_content' フックに差し込む
            (子テーマ footer.php を作らず、親テンプレートを汚さない方式)。
            著作権は 'generate_credits' フィルタで上書き。
   リンク方針: 404 ゼロ。CATEGORY は実在カテゴリ、ARTISTS は段階4a で作成する
              7タグ、ABOUT は段階4a で作成する3固定ページに対応させる。
   推測(オーナー確認事項):
     - SNS URL(X / Instagram)は未確定 → href="#" プレースホルダ。
       確定後にこの配列の url を差し替える。
   ========================================================================== */

/**
 * フッター4カラムブロックを出力する。
 * generate_before_footer_content フックで GP の .site-footer 内・
 * .site-info(著作権バー)の前に差し込まれる。
 */
function kpop_render_footer_columns() {
	// --- 中央ロゴ + サブテキスト ---
	?>
	<div class="kpop-footer">
		<div class="kpop-footer-inner">
			<div class="kpop-footer-brand">
				<span class="kpop-footer-logo">KPOP<span class="logo-journal">JOURNAL</span></span>
				<p class="kpop-footer-tagline">日本最大の K-POP 専門メディア</p>
			</div>

			<nav class="kpop-footer-cols" aria-label="フッターナビゲーション">
				<?php
				/* 各カラム: 見出し(JP + EN)+ リンクリスト。
				   url は段階4a で作成する実在のカテゴリ/タグ/ページに対応。 */
				$columns = array(
					array(
						'title' => 'カテゴリー',
						'en'    => 'CATEGORY',
						'links' => array(
							array( 'ニュース',        home_url( '/category/news/' ) ),
							array( 'チャート',        home_url( '/category/chart/' ) ),
							// Day10 2.3: カムバック残存削除。M11 A-3 でサイドバー箱は
							// 削除済、本フッターナビに残っていた /category/comeback/ への
							// リンクを除去(カテゴリは空のため導線を残さない)。
							array( 'ビューティー',    home_url( '/category/beauty/' ) ),
							array( 'ファッション',    home_url( '/category/fashion/' ) ),
							array( 'ポップアップ',    home_url( '/category/popup/' ) ),
							array( '推し活ガイド',    home_url( '/category/oshikatsu/' ) ),
						),
					),
					array(
						'title' => 'アーティスト',
						'en'    => 'ARTISTS',
						'links' => array(
							array( 'BTS',        home_url( '/tag/bts/' ) ),
							array( 'BLACKPINK',  home_url( '/tag/blackpink/' ) ),
							array( 'aespa',      home_url( '/tag/aespa/' ) ),
							array( 'NewJeans',   home_url( '/tag/newjeans/' ) ),
							array( 'SEVENTEEN',  home_url( '/tag/seventeen/' ) ),
							array( 'TWICE',      home_url( '/tag/twice/' ) ),
							array( 'IVE',        home_url( '/tag/ive/' ) ),
						),
					),
					array(
						'title' => 'サイト情報',
						'en'    => 'ABOUT',
						'links' => array(
							array( 'サイトについて',          home_url( '/about/' ) ),
							array( 'ライター紹介',            home_url( '/writers/' ) ),
							array( 'お問い合わせ',            home_url( '/contact/' ) ),
							array( 'プライバシーポリシー',    home_url( '/privacy-policy/' ) ),
						),
					),
				);
				foreach ( $columns as $col ) :
					?>
					<div class="kpop-footer-col">
						<h2 class="kpop-footer-coltitle">
							<?php echo esc_html( $col['title'] ); ?>
							<span class="kpop-footer-colen"><?php echo esc_html( $col['en'] ); ?></span>
						</h2>
						<ul class="kpop-footer-list">
							<?php foreach ( $col['links'] as $link ) : ?>
								<li>
									<a href="<?php echo esc_url( $link[1] ); ?>"><?php echo esc_html( $link[0] ); ?></a>
								</li>
							<?php endforeach; ?>
						</ul>
					</div>
				<?php endforeach; ?>

				<?php /* FOLLOW カラム: SNS アイコン(ピンク円形)。URL は推測のため href="#"。 */ ?>
				<div class="kpop-footer-col kpop-footer-col--follow">
					<h2 class="kpop-footer-coltitle">
						フォロー
						<span class="kpop-footer-colen">FOLLOW</span>
					</h2>
					<ul class="kpop-footer-sns">
						<li>
							<?php /* X(旧Twitter): URL 確定済み(オーナー提供 2026-05-20)。 */ ?>
							<a class="kpop-sns-link" href="https://x.com/lovekpopjournal"
							   target="_blank" rel="noopener noreferrer"
							   aria-label="X(旧Twitter)で KPOP JOURNAL をフォロー(新しいタブで開く)">
								<svg class="kpop-sns-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
									<path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
								</svg>
							</a>
						</li>
						<li>
							<?php /* Instagram: URL 未確定 → href="#" プレースホルダ(オーナー確認待ち)。 */ ?>
							<a class="kpop-sns-link" href="#" aria-label="Instagram で KPOP JOURNAL をフォロー">
								<svg class="kpop-sns-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
									<path fill="currentColor" d="M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41a3.7 3.7 0 0 1-1.38-.9 3.7 3.7 0 0 1-.9-1.38c-.16-.42-.36-1.06-.41-2.23C2.17 15.58 2.16 15.2 2.16 12s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41C8.42 2.17 8.8 2.16 12 2.16zm0 1.94c-3.15 0-3.5.01-4.74.07-1.14.05-1.76.24-2.17.4-.55.21-.94.47-1.35.88-.41.41-.67.8-.88 1.35-.16.41-.35 1.03-.4 2.17-.06 1.24-.07 1.59-.07 4.74s.01 3.5.07 4.74c.05 1.14.24 1.76.4 2.17.21.55.47.94.88 1.35.41.41.8.67 1.35.88.41.16 1.03.35 2.17.4 1.24.06 1.59.07 4.74.07s3.5-.01 4.74-.07c1.14-.05 1.76-.24 2.17-.4.55-.21.94-.47 1.35-.88.41-.41.67-.8.88-1.35.16-.41.35-1.03.4-2.17.06-1.24.07-1.59.07-4.74s-.01-3.5-.07-4.74c-.05-1.14-.24-1.76-.4-2.17a3.6 3.6 0 0 0-.88-1.35 3.6 3.6 0 0 0-1.35-.88c-.41-.16-1.03-.35-2.17-.4-1.24-.06-1.59-.07-4.74-.07zm0 3.3a4.6 4.6 0 1 1 0 9.2 4.6 4.6 0 0 1 0-9.2zm0 7.59a2.99 2.99 0 1 0 0-5.98 2.99 2.99 0 0 0 0 5.98zm5.86-7.81a1.08 1.08 0 1 1-2.15 0 1.08 1.08 0 0 1 2.15 0z"/>
								</svg>
							</a>
						</li>
					</ul>
				</div>
			</nav>
		</div>
	</div>
	<?php
}
add_action( 'generate_before_footer_content', 'kpop_render_footer_columns' );

/**
 * フッター著作権テキストを元サイト準拠に上書きする。
 * GP の 'generate_credits' フィルタで「Built with GeneratePress」を置換。
 */
add_filter( 'generate_copyright', function () {
	return '<span class="copyright">&copy; ' . esc_html( gmdate( 'Y' ) ) . ' KPOP JOURNAL. All rights reserved.</span>';
} );

/* ==========================================================================
   M1 段階5 — 個別記事ページ (2026-05-20)
   元サイト参照: reference/スクリーンショット 2026-05-07 0.53.39 / 0.53.48。
   子テーマ single.php + content-single.php と連動するヘルパ群。
   ========================================================================== */

/**
 * 段階5a — パンくずリスト(ホーム > カテゴリ > 記事)。
 * GP 無印にパンくず機能はないため自前出力。schema.org BreadcrumbList 付き。
 */
function kpop_breadcrumb() {
	if ( ! is_singular( 'post' ) ) {
		return;
	}
	$items = array();
	$items[] = array( home_url( '/' ), 'ホーム' );

	$cats = get_the_category();
	if ( $cats ) {
		$items[] = array( get_category_link( $cats[0]->term_id ), $cats[0]->name );
	}
	// 現在記事(リンクなし)。
	$current = get_the_title();

	echo '<nav class="kpop-breadcrumb" aria-label="パンくずリスト">';
	echo '<ol itemscope itemtype="https://schema.org/BreadcrumbList">';
	$pos = 1;
	foreach ( $items as $it ) {
		printf(
			'<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">'
			. '<a itemprop="item" href="%s"><span itemprop="name">%s</span></a>'
			. '<meta itemprop="position" content="%d" /></li>',
			esc_url( $it[0] ),
			esc_html( $it[1] ),
			$pos++
		);
	}
	printf(
		'<li class="kpop-breadcrumb-current" itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem" aria-current="page">'
		. '<span itemprop="name">%s</span><meta itemprop="position" content="%d" /></li>',
		esc_html( $current ),
		$pos
	);
	echo '</ol>';
	echo '</nav>';
}

/**
 * 段階5b — 読了時間(分)。本文の文字数 ÷ 500字/分(日本語の目安)。
 * @return int 1 以上の分数。
 */
function kpop_reading_time() {
	$content = get_post_field( 'post_content', get_the_ID() );
	$text    = wp_strip_all_tags( strip_shortcodes( $content ) );
	// 日本語はスペース区切りでないため文字数でカウント。
	$chars   = mb_strlen( preg_replace( '/\s+/u', '', $text ) );
	$minutes = (int) ceil( $chars / 500 );
	return max( 1, $minutes );
}

/**
 * 段階5c — 3行まとめボックス。
 * カスタムフィールド 'kpop_summary'(1行1項目)を優先。無ければ非表示。
 * ※ 元サイトは本文先頭の箇条書きをまとめにしている可能性があるが、
 *    抽出ロジックは確定不可 → カスタムフィールド方式(運用が明快)。
 *    フィールド未設定の記事では出さない(誤った自動要約を出さない)。
 *
 * @param int $post_id 記事ID。
 */
function kpop_render_summary_box( $post_id ) {
	$raw = get_post_meta( $post_id, 'kpop_summary', true );
	if ( ! $raw ) {
		return; // まとめ未設定 → ボックス非表示(推測要約は出さない)
	}
	$lines = array_filter( array_map( 'trim', preg_split( '/\r\n|\r|\n/', $raw ) ) );
	if ( empty( $lines ) ) {
		return;
	}
	echo '<aside class="kpop-summary-box" aria-label="この記事のまとめ">';
	echo '<p class="kpop-summary-title">この記事のポイント</p>';
	echo '<ul class="kpop-summary-list">';
	foreach ( $lines as $line ) {
		echo '<li>' . esc_html( $line ) . '</li>';
	}
	echo '</ul>';
	echo '</aside>';
}

/**
 * 段階5e — 記事フッター(タグ / SNSシェア / フィードバック / 関連記事)。
 *
 * @param int $post_id 記事ID。
 */
function kpop_render_single_footer( $post_id ) {
	echo '<footer class="kpop-single-footer">';

	// --- タグ群 ---
	$tags = get_the_tags( $post_id );
	if ( $tags ) {
		echo '<div class="kpop-single-tags">';
		foreach ( $tags as $tag ) {
			printf(
				'<a class="kpop-tag" href="%s">#%s</a>',
				esc_url( get_tag_link( $tag->term_id ) ),
				esc_html( $tag->name )
			);
		}
		echo '</div>';
	}

	// --- SNS シェアボタン(X / Facebook) ---
	$url   = rawurlencode( get_permalink( $post_id ) );
	$title = rawurlencode( get_the_title( $post_id ) );
	echo '<div class="kpop-share">';
	echo '<span class="kpop-share-label">シェアする</span>';
	printf(
		'<a class="kpop-share-btn kpop-share-x" href="https://twitter.com/intent/tweet?url=%s&text=%s" target="_blank" rel="noopener noreferrer" aria-label="X(旧Twitter)でシェア(新しいタブで開く)">'
		. '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>'
		. '<span>ポスト</span></a>',
		$url,
		$title
	);
	printf(
		'<a class="kpop-share-btn kpop-share-fb" href="https://www.facebook.com/sharer/sharer.php?u=%s" target="_blank" rel="noopener noreferrer" aria-label="Facebook でシェア(新しいタブで開く)">'
		. '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07c0 6.03 4.39 11.03 10.13 11.93v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.79-4.69 4.53-4.69 1.31 0 2.69.24 2.69.24v2.97h-1.52c-1.49 0-1.96.93-1.96 1.89v2.26h3.33l-.53 3.49h-2.8v8.44C19.61 23.1 24 18.1 24 12.07z"/></svg>'
		. '<span>シェア</span></a>',
		$url
	);
	echo '</div>';

	// --- フィードバック(役に立った / 改善が必要) ---
	// ※ 集計の保存先は未実装 → ボタンは表示のみ。動作は段階後半 or J項目で
	//    連携予定(推測実装。現状はクリックしても記録されない)。
	echo '<div class="kpop-feedback" aria-label="記事の評価">';
	echo '<p class="kpop-feedback-q">この記事は役に立ちましたか?</p>';
	echo '<div class="kpop-feedback-btns">';
	echo '<button type="button" class="kpop-feedback-btn" data-value="useful">役に立った</button>';
	echo '<button type="button" class="kpop-feedback-btn" data-value="improve">改善が必要</button>';
	echo '</div>';
	echo '</div>';

	// --- 関連記事はここでは描画しない ---
	// content-single.php の B-4a「関連記事5枚カード」(タグ+カテゴリ重みづけ)に一本化。
	// 以前はこのフッター関数でも同カテゴリ4件を描画しており、1記事に「関連記事」が
	// 二重(B-4a 5枚 + フッター4件)に出ていた([4]重複の主因、2026-05-26 解消)。

	echo '</footer>';
}

/**
 * A8 バナー広告の共通基盤。素材は config/affiliate/sidebar_ad.json。
 *   banners: キー→A8公式バナーHTML(<a>+<img>+計測px をそのまま)。
 *   rotate_pool: ページ読込毎にランダムで1つ出すキー群。
 *   top_fixed_key: トップに固定表示するキー。
 * A8 公式素材は信頼できる前提でそのまま出力(rel 補完のみ)。enabled:false で全停止。
 */
function kpop_ad_config() {
	static $cfg = null;
	if ( $cfg !== null ) { return $cfg; }
	$path = get_stylesheet_directory() . '/../../../../config/affiliate/sidebar_ad.json';
	if ( ! file_exists( $path ) ) {
		$alt = '/home/aiuser/kpop-ai-system/config/affiliate/sidebar_ad.json';
		if ( file_exists( $alt ) ) { $path = $alt; }
	}
	$cfg = file_exists( $path ) ? json_decode( (string) file_get_contents( $path ), true ) : array();
	if ( ! is_array( $cfg ) ) { $cfg = array(); }
	return $cfg;
}

/** 指定キーのバナーHTMLを安全に整形して返す(rel 補完 + カード wrap)。無効なら ''。 */
function kpop_ad_banner_html( $key ) {
	$cfg = kpop_ad_config();
	if ( empty( $cfg['enabled'] ) || empty( $cfg['banners'][ $key ] ) ) { return ''; }
	$html = (string) $cfg['banners'][ $key ];
	// rel に nofollow/sponsored と target=_blank を補完(A8素材は rel="nofollow" のみのことが多い)。
	if ( strpos( $html, 'sponsored' ) === false ) {
		$html = preg_replace( '/<a\s+href=/i', '<a rel="nofollow sponsored" target="_blank" href=', $html, 1 );
	}
	return '<div class="kpop-ad-a8">' . $html . '</div>';
}

/** rotate_pool からランダムに1つ選んで描画(ページ読込毎に変わる)。 */
function kpop_ad_rotate( $count = 1, $exclude = array() ) {
	$cfg = kpop_ad_config();
	$pool = isset( $cfg['rotate_pool'] ) && is_array( $cfg['rotate_pool'] ) ? $cfg['rotate_pool'] : array();
	$pool = array_values( array_diff( $pool, (array) $exclude ) ); // 固定表示中のキー等を除外
	if ( empty( $pool ) ) { return ''; }
	shuffle( $pool );                          // ページ読込毎にランダム順
	$pick = array_slice( $pool, 0, max( 1, (int) $count ) ); // プール超過分は重複させず打ち止め
	$out = '';
	foreach ( $pick as $key ) {
		$out .= kpop_ad_banner_html( $key );
	}
	return $out;
}

/** サイドバー Advertisement 枠の中身(rotate 3枚)。空ならプレースホルダに戻す。 */
function kpop_render_sidebar_ad() {
	$out = kpop_ad_rotate( 3 );
	return $out !== '' ? $out : '<p class="kpop-box-placeholder">広告枠</p>';
}

/** placement が config で有効か。 */
function kpop_ad_placement_on( $name ) {
	$cfg = kpop_ad_config();
	return ! empty( $cfg['enabled'] ) && ! empty( $cfg['placements'][ $name ] );
}

/** top_header_pool(横長バナー)からランダム1枚。 */
function kpop_ad_header_rotate() {
	$cfg  = kpop_ad_config();
	$pool = isset( $cfg['top_header_pool'] ) && is_array( $cfg['top_header_pool'] ) ? $cfg['top_header_pool'] : array();
	if ( empty( $pool ) ) { return ''; }
	return kpop_ad_banner_html( $pool[ array_rand( $pool ) ] );
}

/**
 * トップページのヘッダーカテゴリー下に「横長バナー(ローテ1枚)」を出す。
 * generate_after_header(ナビ下)で front-page のときだけ。
 */
function kpop_ad_top() {
	if ( ! ( is_front_page() || is_home() ) || ! kpop_ad_placement_on( 'top_header' ) ) { return; }
	$rot = kpop_ad_header_rotate();
	if ( $rot === '' ) { return; }
	echo '<div class="kpop-ad-row kpop-ad-top kpop-ad-lead">';
	echo '<span class="kpop-ad-label">Advertisement <span class="kpop-ad-pr">PR</span></span>';
	echo '<div class="kpop-ad-row-inner">' . $rot . '</div>'; // phpcs:ignore WordPress.Security.EscapeOutput
	echo '</div>';
}
add_action( 'generate_after_header', 'kpop_ad_top' );

/**
 * トップページのサイドバーに広告ボックス(固定 + ローテ1枚)を「出力」する。
 * 配置順の保証は kpop_sidebar_reorder()(全ページ共通の並べ替え)が担うため、
 * ここでは順序を気にせずボックスを emit するだけでよい。
 */
function kpop_ad_top_sidebar() {
	if ( ! ( is_front_page() || is_home() ) || ! kpop_ad_placement_on( 'top_sidebar' ) ) { return; }
	$cfg   = kpop_ad_config();
	$fkey  = isset( $cfg['top_fixed_key'] ) ? $cfg['top_fixed_key'] : '';
	$fixed = $fkey !== '' ? kpop_ad_banner_html( $fkey ) : '';
	$rot   = kpop_ad_rotate( 1, array( $fkey ) );
	foreach ( array( $fixed, $rot ) as $b ) {
		if ( $b === '' ) { continue; }
		echo '<div class="kpop-sidebar-box kpop-ad-slot" role="complementary" aria-label="広告">';
		echo '<span class="kpop-ad-label">Advertisement <span class="kpop-ad-pr">PR</span></span>';
		echo $b; // phpcs:ignore WordPress.Security.EscapeOutput
		echo '</div>';
	}
}
add_action( 'generate_after_right_sidebar_content', 'kpop_ad_top_sidebar', 30 );

/* ─────────────────────────────────────────────────────────────────────────
 * サイドバー広告の「非連続」を全ページ共通で保証する並べ替え。
 * GP の右サイドバー出力全体(widget + before/after フックのカード)をバッファし、
 * トップレベルの .kpop-sidebar-box を分解 → 広告ボックス(.kpop-ad-slot)が
 *   ①先頭でない ②末尾でない ③広告同士が隣接しない
 * ように非広告カードの「間」に分散配置する。挟める非広告カードが無ければ広告は出さない。
 * ページ種別(トップ/記事/一覧/その他)に依存せず効くのが利点。
 * ───────────────────────────────────────────────────────────────────────── */
function kpop_sidebar_buffer_start() { ob_start(); }
add_action( 'generate_before_right_sidebar_content', 'kpop_sidebar_buffer_start', 1 );

function kpop_sidebar_buffer_end() {
	$html = ob_get_clean();
	if ( $html === false || $html === '' ) { return; }

	// トップレベルの <div class="...kpop-sidebar-box...">…</div> を順に切り出す。
	// ネストした div を正しく対応付けるため、開始タグ位置から手動で深さを数える。
	$boxes = array();      // 各 .kpop-sidebar-box の完全な HTML
	$other = '';           // box 以外(空白等)はそのまま末尾保持用に捨てない
	$offset = 0;
	$len = strlen( $html );
	if ( ! preg_match_all( '/<div\b[^>]*class="[^"]*kpop-sidebar-box[^"]*"[^>]*>/i', $html, $m, PREG_OFFSET_CAPTURE ) ) {
		echo $html; // box が無ければそのまま(並べ替え不要)
		return;
	}
	foreach ( $m[0] as $hit ) {
		$start = $hit[1];
		// この <div> に対応する </div> を深さカウントで探す。
		$i = $start;
		$depth = 0;
		while ( $i < $len ) {
			$next_open  = stripos( $html, '<div', $i );
			$next_close = stripos( $html, '</div>', $i );
			if ( $next_close === false ) { break; }
			if ( $next_open !== false && $next_open < $next_close ) {
				$depth++; $i = $next_open + 4;
			} else {
				$depth--; $i = $next_close + 6;
				if ( $depth === 0 ) { break; }
			}
		}
		$boxes[] = substr( $html, $start, $i - $start );
	}

	// 広告 / 非広告に仕分け。
	$ads = array();
	$cards = array();
	foreach ( $boxes as $b ) {
		if ( strpos( $b, 'kpop-ad-slot' ) !== false ) { $ads[] = $b; } else { $cards[] = $b; }
	}

	// 挟める非広告カードが無ければ広告は出さない(=連続/孤立を作らない)。
	if ( empty( $cards ) ) {
		echo implode( '', $cards );
		return;
	}
	// 非広告カードの「間(末尾含む各カードの後ろ)」に広告を1枚ずつ分散。
	// gap 候補は cards[0]の後, cards[1]の後 … で、先頭(cards前)には置かない=広告は必ず
	// 上に非広告カードがある。隣接も起きない(各 gap に最大1枚)。
	$result = '';
	$gap = 1; // cards[0] の後ろから挿入(先頭を避ける)
	$ai = 0;
	for ( $ci = 0; $ci < count( $cards ); $ci++ ) {
		$result .= $cards[ $ci ];
		// このカードの後ろに広告を1枚(まだ残っていて、末尾カードの後でなければ)。
		if ( $ai < count( $ads ) && $ci < count( $cards ) - 1 && $ci >= 0 ) {
			// 先頭カード(ci=0)の後は OK、ただし最後のカードの後(ci=last)は末尾広告になるので避ける。
			$result .= $ads[ $ai ];
			$ai++;
		}
	}
	// 余った広告(カードが少なく gap が足りない場合)は出さない=連続を避ける。
	echo $result;
}
add_action( 'generate_after_right_sidebar_content', 'kpop_sidebar_buffer_end', 999 );

/** 記事一覧(カテゴリ/アーカイブ)のヘッダー下にトップと同じ横長バナー(ローテ1枚)。 */
function kpop_ad_archive() {
	if ( ! ( is_category() || is_archive() || is_tax() ) || ! kpop_ad_placement_on( 'archive' ) ) { return; }
	$rot = kpop_ad_header_rotate(); // トップ(kpop_ad_top)と同じ横長プール・1枚
	if ( $rot === '' ) { return; }
	echo '<div class="kpop-ad-row kpop-ad-top kpop-ad-lead kpop-ad-archive">';
	echo '<span class="kpop-ad-label">Advertisement <span class="kpop-ad-pr">PR</span></span>';
	echo '<div class="kpop-ad-row-inner">' . $rot . '</div>'; // phpcs:ignore WordPress.Security.EscapeOutput
	echo '</div>';
}
add_action( 'generate_after_header', 'kpop_ad_archive' );
// 記事本文中の広告は廃止(オーナー要望3)。kpop_ad_in_content は削除。

/**
 * 段階5f — 個別記事の右サイドバー追加コンテンツ。
 * GP の 'generate_before_right_sidebar_content' フックで、個別記事のときだけ
 * 目次 / ADVERTISEMENT 枠 / このカテゴリの最新記事 を sidebar-1 ウィジェットの
 * 前に差し込む。目次は JS(kpop_single_toc_script)でクライアント生成する。
 */
function kpop_single_sidebar_extras() {
	if ( ! is_singular( 'post' ) ) {
		return;
	}

	// --- 目次(枠だけ出力、中身は JS が .entry-content の h2/h3 から生成) ---
	echo '<div class="kpop-sidebar-box kpop-toc" aria-label="目次">';
	echo '<h2 class="kpop-box-title">目次 <span class="kpop-box-en">CONTENTS</span></h2>';
	echo '<nav class="kpop-toc-nav"><ol class="kpop-toc-list"></ol></nav>';
	// 見出しが無い記事用フォールバック(JS が空なら箱ごと隠す)。
	echo '</div>';

	// --- ADVERTISEMENT 枠(A8アフィリエイト。config/affiliate/sidebar_ad.json で素材差替) ---
	echo '<div class="kpop-sidebar-box kpop-ad-slot">';
	echo '<span class="kpop-ad-label">Advertisement <span class="kpop-ad-pr">PR</span></span>';
	echo kpop_render_sidebar_ad(); // phpcs:ignore WordPress.Security.EscapeOutput -- 内部で必要箇所をエスケープ済み
	echo '</div>';

	// --- このカテゴリの最新記事5件 ---
	$cats = get_the_category();
	if ( $cats ) {
		$cat   = $cats[0];
		$latest = new WP_Query( array(
			'post_type'           => 'post',
			'post_status'         => 'publish',
			'cat'                 => $cat->term_id,
			'post__not_in'        => array( get_the_ID() ),
			'posts_per_page'      => 5,
			'orderby'             => 'date',
			'order'               => 'DESC',
			'ignore_sticky_posts' => true,
			'no_found_rows'       => true,
		) );
		if ( $latest->have_posts() ) {
			echo '<div class="kpop-sidebar-box">';
			printf(
				'<h2 class="kpop-box-title">%sの最新記事 <span class="kpop-box-en">LATEST</span></h2>',
				esc_html( $cat->name )
			);
			echo '<ul class="kpop-thumb-list">';
			while ( $latest->have_posts() ) {
				$latest->the_post();
				echo function_exists( 'kpop_sc_thumb_item' )
					? kpop_sc_thumb_item( get_the_ID() )
					: '<li><a href="' . esc_url( get_permalink() ) . '">' . esc_html( get_the_title() ) . '</a></li>';
			}
			echo '</ul>';
			echo '</div>';
			wp_reset_postdata();
		}
	}
}
add_action( 'generate_before_right_sidebar_content', 'kpop_single_sidebar_extras' );

/**
 * 段階5f — 目次の自動生成スクリプト。
 * .entry-content 内の h2/h3 に id を振り、.kpop-toc-list を組み立てる。
 * スクロール位置に応じて現在地をハイライト(IntersectionObserver)。
 * 個別記事ページでのみ読み込む。
 */
function kpop_single_toc_script() {
	if ( ! is_singular( 'post' ) ) {
		return;
	}
	?>
	<script>
	(function () {
		var content = document.querySelector('.kpop-single .entry-content');
		var list = document.querySelector('.kpop-toc-list');
		var box = document.querySelector('.kpop-toc');
		if (!content || !list || !box) { return; }
		var heads = content.querySelectorAll('h2, h3');
		if (!heads.length) { box.style.display = 'none'; return; }
		var links = [];
		heads.forEach(function (h, i) {
			if (!h.id) { h.id = 'kpop-h-' + i; }
			var li = document.createElement('li');
			li.className = 'kpop-toc-' + h.tagName.toLowerCase();
			var a = document.createElement('a');
			a.href = '#' + h.id;
			a.textContent = h.textContent;
			li.appendChild(a);
			list.appendChild(li);
			links.push(a);
		});
		// 現在地ハイライト
		if ('IntersectionObserver' in window) {
			var obs = new IntersectionObserver(function (entries) {
				entries.forEach(function (e) {
					if (e.isIntersecting) {
						links.forEach(function (l) { l.classList.remove('is-active'); });
						var active = list.querySelector('a[href="#' + e.target.id + '"]');
						if (active) { active.classList.add('is-active'); }
					}
				});
			}, { rootMargin: '0px 0px -75% 0px' });
			heads.forEach(function (h) { obs.observe(h); });
		}
	})();
	</script>
	<?php
}
add_action( 'wp_footer', 'kpop_single_toc_script' );

/**
 * 段階8.1b — 本文 <table> のキーボードアクセス確保。
 *
 * 記事生成パイプラインが出力する素の <table> は、モバイルで
 * style.css により display:block + overflow-x:auto となりスクロール
 * 領域化するが tabindex が無く、キーボード/支援技術でスクロール
 * できない(axe: scrollable-region-focusable / WCAG 2.1.1)。
 *
 * 真因はパイプライン側(table 生成時に属性が付かない)で、その修正は
 * C項目に記録済み(C_pipeline_fixes.md)。ここではテーマ側の防御として
 * 既存記事も含め tabindex="0" + role="region" + aria-label を付与する。
 * フォーカス枠は段階8b の :focus-visible(table 用は段階8.1 CSS)で表示。
 *
 * 個別記事ページでのみ実行。
 */
function kpop_single_table_a11y() {
	if ( ! is_singular( 'post' ) ) {
		return;
	}
	?>
	<script>
	(function () {
		var content = document.querySelector('.kpop-single .entry-content');
		if (!content) { return; }
		var tables = content.querySelectorAll('table');
		tables.forEach(function (t) {
			if (!t.hasAttribute('tabindex')) { t.setAttribute('tabindex', '0'); }
			if (!t.hasAttribute('role'))     { t.setAttribute('role', 'region'); }
			if (!t.hasAttribute('aria-label')) {
				t.setAttribute('aria-label', '記事内の表(横スクロール可能)');
			}
		});
	})();
	</script>
	<?php
}
add_action( 'wp_footer', 'kpop_single_table_a11y' );

/**
 * イベントアーカイブ(The Events Calendar)の a11y 補正。
 *
 * 真因はプラグイン側のビューテンプレート出力で、テーマからは直せない:
 *  (1) 空状態の「次のイベントへ進む」リンク(.tribe-events-...message-list-item-link
 *      / data-js="tribe-events-view-link")が、JS 再描画時にアクセシブル名の
 *      無い <a> として複製されることがある(axe: link-name / WCAG 4.1.2)。
 *  (2) ビュー切替の <ul class="tribe-events-c-view-selector__list"> が直下に
 *      <a> を持ち、<li> 以外を含む不正なリスト構造になる(axe: list / WCAG 1.3.1)。
 *
 * プラグインのビューは AJAX で再描画されるため、初回 + MutationObserver で
 * 再適用する。既存の table a11y シムと同じ「テーマ側の防御」方針。
 */
function kpop_events_archive_a11y() {
	if ( ! function_exists( 'is_post_type_archive' ) || ! is_post_type_archive( 'tribe_events' ) ) {
		return;
	}
	?>
	<script>
	(function () {
		function isHidden(el) {
			var cs = getComputedStyle(el);
			if (cs.display === 'none' || cs.visibility === 'hidden') { return true; }
			var r = el.getBoundingClientRect();
			return (r.width === 0 && r.height === 0);
		}
		function fix(root) {
			if (!root) { return; }
			// (1) リンクのアクセシブル名を整える。
			//   プラグインは「次のイベントへ進む」リンクを非表示・0サイズの複製として
			//   DOM に残すため、axe が link-name 違反として検出する。
			//   - 不可視/0サイズのものは a11y ツリーとタブ順から除外(aria-hidden + tabindex=-1)
			//   - 可視で名前が無いものだけ aria-label を補う
			root.querySelectorAll('a[data-js="tribe-events-view-link"], a.tribe-events-c-messages__message-list-item-link').forEach(function (a) {
				if (isHidden(a)) {
					a.setAttribute('aria-hidden', 'true');
					a.setAttribute('tabindex', '-1');
					return;
				}
				var name = (a.textContent || '').trim();
				if (!name && !a.getAttribute('aria-label')) {
					a.setAttribute('aria-label', '次のイベントを表示');
				}
			});
			// (1b) プラグイン i18n の二重語「イベントイベント」を 1 語に正規化
			root.querySelectorAll('a[data-js="tribe-events-view-link"]').forEach(function (a) {
				if (a.childElementCount === 0 && a.textContent.indexOf('イベントイベント') !== -1) {
					a.textContent = a.textContent.replace(/イベントイベント/g, 'イベント');
				}
			});
			// (2) view-selector の <ul> 直下 <a> を <li> でラップして正しいリスト構造に
			root.querySelectorAll('ul.tribe-events-c-view-selector__list').forEach(function (ul) {
				Array.prototype.slice.call(ul.children).forEach(function (child) {
					if (child.tagName === 'A') {
						var li = document.createElement('li');
						li.className = 'tribe-events-c-view-selector__list-item';
						ul.insertBefore(li, child);
						li.appendChild(child);
					}
				});
			});
		}
		var view = document.querySelector('.tribe-events-view') || document.body;
		fix(view);
		// プラグインの AJAX 再描画に追随
		if (window.MutationObserver && view) {
			var mo = new MutationObserver(function () { fix(view); });
			mo.observe(view, { childList: true, subtree: true });
		}
	})();
	</script>
	<?php
}
add_action( 'wp_footer', 'kpop_events_archive_a11y' );

/**
 * 段階6 — カテゴリ/アーカイブページはサイドバーなしの全幅1カラム。
 * archive.php は generate_construct_sidebars() を呼ばないが、GP が
 * body class やコンテナ幅でサイドバー前提のレイアウトを出さないよう、
 * アーカイブでは右サイドバーを無効化する。
 */
add_filter( 'generate_show_right_sidebar', function ( $show ) {
	if ( is_archive() || is_category() || is_tag() ) {
		return false;
	}
	/* M6 段階6.5 — Idol Wiki 個別ページもサイドバーなし全幅 */
	if ( is_singular( 'idol_artist' ) ) {
		return false;
	}
	return $show;
} );

/**
 * ============================================================
 * M6 段階6.3 — Idol Wiki 用 CPT「idol_artist」+ taxonomy + REST API
 * (2026-05-20、M3 と並ぶ最大配点項目 E の実装)
 *
 * 設計方針:
 * - post_type: idol_artist(個人・グループ問わず1スキーマで管理)
 * - URL構造: /artists/{slug}/(M1 段階7 の page-artists ハブと整合)
 * - rewrite slug: artists(/artists/bts/、/artists/blackpink/ 等)
 * - REST API exposure: true(将来の Headless 連携・Skill からのアクセス)
 * - taxonomy: artist_group(将来の「グループ別」絞り込み用)
 * - メニュー上に出して管理画面から ACF で入力できる
 *
 * ACF プラグイン未インストール時もこのコード単体で CPT は動く
 * (フィールドが無いだけ)。ACF field group は別途 /acf-json/ で管理。
 * ============================================================
 */

function kpop_register_idol_artist_cpt() {
	$labels = array(
		'name'                  => 'アーティスト',
		'singular_name'         => 'アーティスト',
		'menu_name'             => 'アーティスト',
		'name_admin_bar'        => 'アーティスト',
		'add_new'               => '新規追加',
		'add_new_item'          => 'アーティストを追加',
		'new_item'              => '新規アーティスト',
		'edit_item'             => 'アーティストを編集',
		'view_item'             => 'アーティストを表示',
		'all_items'             => 'すべてのアーティスト',
		'search_items'          => 'アーティストを検索',
		'not_found'             => 'アーティストが見つかりません',
		'not_found_in_trash'    => 'ゴミ箱にアーティストはありません',
		'featured_image'        => 'メイン画像',
		'set_featured_image'    => 'メイン画像を設定',
		'remove_featured_image' => 'メイン画像を削除',
		'use_featured_image'    => 'メイン画像として使用',
	);
	$args = array(
		'labels'             => $labels,
		'public'             => true,
		'publicly_queryable' => true,
		'show_ui'            => true,
		'show_in_menu'       => true,
		'show_in_rest'       => true,
		'rest_base'          => 'idol_artists',
		'menu_icon'          => 'dashicons-microphone',
		'menu_position'      => 20,
		'query_var'          => true,
		'rewrite'            => array(
			'slug'       => 'artists',
			'with_front' => false,
		),
		'capability_type'    => 'post',
		'has_archive'        => false, /* /artists/ は page-artists.php で実装 */
		'hierarchical'       => false,
		'supports'           => array( 'title', 'editor', 'thumbnail', 'excerpt', 'custom-fields', 'revisions' ),
	);
	register_post_type( 'idol_artist', $args );
}
add_action( 'init', 'kpop_register_idol_artist_cpt' );

/**
 * artist_group taxonomy(将来の絞り込み用)
 * 例: men's group / women's group / mixed / solo
 */
function kpop_register_artist_group_taxonomy() {
	$labels = array(
		'name'              => 'グループ種別',
		'singular_name'     => 'グループ種別',
		'menu_name'         => 'グループ種別',
		'all_items'         => 'すべての種別',
		'edit_item'         => '種別を編集',
		'view_item'         => '種別を表示',
		'add_new_item'      => '新規追加',
		'search_items'      => '検索',
	);
	register_taxonomy( 'artist_group', array( 'idol_artist' ), array(
		'labels'            => $labels,
		'hierarchical'      => true,
		'public'            => true,
		'show_admin_column' => true,
		'show_in_rest'      => true,
		'rewrite'           => array( 'slug' => 'artist-group' ),
	) );
}
add_action( 'init', 'kpop_register_artist_group_taxonomy' );

/**
 * ACF JSON 同期 — field group 定義をコード管理する
 * 保存先: 子テーマ /acf-json/(group_*.json として保存される)
 * 読込先: 同じ /acf-json/(プラグイン有効化時、自動同期)
 *
 * これにより stg → 本番への移行時、field 定義の手動コピーが不要になる。
 * オーナー指示「ACF JSON 同期を有効化」の実装。
 */
add_filter( 'acf/settings/save_json', function( $path ) {
	return get_stylesheet_directory() . '/acf-json';
} );
add_filter( 'acf/settings/load_json', function( $paths ) {
	unset( $paths[0] );
	$paths[] = get_stylesheet_directory() . '/acf-json';
	return $paths;
} );

/**
 * URL リライトのフラッシュ(プラグイン/CPT 追加後 1回だけ動かす)
 * オーナーが手動で /wp-admin/options-permalink.php を開けば自動で flush するが
 * コード側でも fallback として保証する。
 */
function kpop_maybe_flush_rewrite() {
	if ( get_option( 'kpop_idol_cpt_rewrite_flushed' ) !== '1' ) {
		flush_rewrite_rules();
		update_option( 'kpop_idol_cpt_rewrite_flushed', '1' );
	}
}
add_action( 'init', 'kpop_maybe_flush_rewrite', 99 );

/* ==========================================================================
   M11 段階9 (Day 9) — UI/UX 品質改善 13項目(A 7 + B 6)
   2026-05-20、オーナー指示
   ========================================================================== */

/* --- A-1: 速報バーの位置をヘッダー最上部 → ナビ下に変更 ---
 * 旧: add_action( 'wp_body_open', 'kpop_render_breaking_bar' );
 * 新: generate_after_header (GeneratePress のヘッダー直下フック)
 * - wp_body_open フックは上で登録済みなので、ここで remove + 再 add する。
 * - axe / breaking_bar の構造自体は変えない(role="region" 維持)。
 */
remove_action( 'wp_body_open', 'kpop_render_breaking_bar' );
add_action( 'generate_after_header', 'kpop_render_breaking_bar' );

/* ------------------------------------------------------------------
 * イベントアーカイブ(/events/)の見出し帯 + 説明文
 * The Events Calendar 既定では .tribe-events-header__title が非表示で、
 * 初見の来訪者に「何のページか」が伝わらない。アーカイブ表示時のみ
 * ブランド見出し + 一文の説明を出して文脈を与える。
 * 速報バー(priority 10)の直後に出すため priority 15 で登録。
 * ------------------------------------------------------------------ */
function kpop_events_archive_intro() {
	if ( ! function_exists( 'is_post_type_archive' ) ) {
		return;
	}
	// TEC のアーカイブ(月/リスト/日いずれのビューでも post_type は tribe_events)
	if ( ! is_post_type_archive( 'tribe_events' ) ) {
		return;
	}
	echo '<section class="kpop-events-intro" role="region" aria-label="イベント情報">';
	echo '<h1>K-POP イベントカレンダー</h1>';
	echo '<p>K-POP アーティストの来日公演・ライブ・ファンミーティング・フェス出演に加え、'
		. 'メンバーのお誕生日 🎂 やポップアップストア情報も表示しています。'
		. '下のフィルタで種別を切り替えられます。</p>';

	// フィルタトグル(イベント/誕生日/Popup)
	echo '<div class="kpj-event-filter" role="group" aria-label="表示するイベント種別">';
	echo '<span class="kpj-event-filter__label">表示:</span>';
	echo '<button type="button" class="kpj-event-filter__btn" data-kind="event" aria-pressed="true">🎤 ライブ・イベント</button>';
	echo '<button type="button" class="kpj-event-filter__btn" data-kind="birthday" aria-pressed="true">🎂 誕生日</button>';
	echo '<button type="button" class="kpj-event-filter__btn" data-kind="popup" aria-pressed="true">🛍️ ポップアップ</button>';
	echo '</div>';

	echo '</section>';

	// イベント種別フィルタ JS (インライン、依存ライブラリなし)
	// 各イベントカードを title prefix で分類: 🎂→birthday / 🛍️ or POPUP→popup / else→event
	?>
	<script>
	(function(){
	  var state = { event: true, birthday: true, popup: true };
	  function detectKind(text){
	    if (!text) return 'event';
	    if (text.indexOf('🎂') === 0 || /^\s*🎂/.test(text)) return 'birthday';
	    if (text.indexOf('🛍') >= 0 || text.indexOf('POPUP') >= 0 || text.indexOf('ポップアップ') >= 0) return 'popup';
	    return 'event';
	  }
	  function apply(){
	    // 月表示の日別イベントセル + リスト表示のイベント行
	    var nodes = document.querySelectorAll(
	      '.tribe-events-calendar-month__calendar-event, ' +
	      '.tribe-events-calendar-month__multiday-event, ' +
	      '.tribe-events-calendar-month__mobile-events-mobile-day-marker ~ * .tribe-events-calendar-month__mobile-events-mobile-event, ' +
	      '.tribe-events-calendar-list__event-row, ' +
	      '.tribe-events-calendar-day__event'
	    );
	    nodes.forEach(function(node){
	      var titleEl = node.querySelector('a, .tribe-events-calendar-month__calendar-event-title, .tribe-events-calendar-list__event-title');
	      var text = (titleEl ? titleEl.textContent : node.textContent) || '';
	      var kind = detectKind(text);
	      node.classList.toggle('kpj-event-hidden', !state[kind]);
	      if (kind === 'birthday') node.classList.add('kpj-birthday-event');
	    });
	  }
	  document.addEventListener('click', function(e){
	    var btn = e.target.closest('.kpj-event-filter__btn');
	    if (!btn) return;
	    var kind = btn.getAttribute('data-kind');
	    state[kind] = !state[kind];
	    btn.setAttribute('aria-pressed', state[kind] ? 'true' : 'false');
	    apply();
	  });
	  // 初回 + TEC が ajax で月切替した時に再適用
	  document.addEventListener('DOMContentLoaded', apply);
	  document.addEventListener('tribeViewLoaded', apply);
	  // SPAっぽい遷移にも保険でMutationObserver
	  var obs = new MutationObserver(function(){ apply(); });
	  document.addEventListener('DOMContentLoaded', function(){
	    var root = document.querySelector('.tribe-events-view, .tribe-events-l-container');
	    if (root) obs.observe(root, {childList: true, subtree: true});
	  });
	})();
	</script>
	<?php
}
add_action( 'generate_after_header', 'kpop_events_archive_intro', 15 );

/* ------------------------------------------------------------------
 * イベントアーカイブの meta description
 * Lighthouse SEO 監査で /events/ アーカイブに meta description が無いと
 * 検出された(SEO 82 の主因の一つ)。本サイトは AIOSEO が稼働中だが、
 * tribe_events アーカイブには Search Appearance の説明が未設定で
 * description が出ていない。
 *
 * 方針: 自前で <meta> を直書きすると AIOSEO のタグと二重化する恐れが
 * あるため、AIOSEO の description フィルタに供給する。AIOSEO が既に
 * 非空の説明を持っていればそれを尊重し、空のときだけ補完する。
 * AIOSEO 不在の環境にも備え、フィルタが一度も走らなければ wp_head で
 * フォールバック出力する(二重化はフラグで防止)。
 * ------------------------------------------------------------------ */
function kpop_events_archive_description_text() {
	return 'K-POP アーティストの来日公演・ライブ・ファンミーティング・フェス出演スケジュールを'
		. '開催日順に掲載。月表示／リスト表示と検索で気になる公演を探せる K-POP イベントカレンダーです。';
}

$GLOBALS['kpop_events_desc_handled'] = false;

// AIOSEO 稼働時: description フィルタで補完(空のときだけ)。
add_filter( 'aioseo_description', function ( $description ) {
	if ( function_exists( 'is_post_type_archive' ) && is_post_type_archive( 'tribe_events' ) ) {
		$GLOBALS['kpop_events_desc_handled'] = true;
		if ( empty( trim( (string) $description ) ) ) {
			return kpop_events_archive_description_text();
		}
	}
	return $description;
} );

// フォールバック: SEO プラグインが description を扱わなかった場合のみ直書き。
function kpop_events_archive_meta_description_fallback() {
	if ( ! function_exists( 'is_post_type_archive' ) || ! is_post_type_archive( 'tribe_events' ) ) {
		return;
	}
	if ( ! empty( $GLOBALS['kpop_events_desc_handled'] ) ) {
		return; // AIOSEO 側で処理済み
	}
	echo "\n" . '<meta name="description" content="'
		. esc_attr( kpop_events_archive_description_text() ) . '">' . "\n";
}
add_action( 'wp_head', 'kpop_events_archive_meta_description_fallback', 99 );

/* --- A-2: 誕生日ウィジェット(今日/明日) を読み込む --- */
require_once get_stylesheet_directory() . '/widgets/today_birthday.php';
require_once get_stylesheet_directory() . '/widgets/tomorrow_birthday.php';

/* --- サイドバー用ショートコード([kpop_birthday]/[kpop_popular]/[kpop_chart]/
 *     [kpop_chart_ranking]/[kpop_events])を登録する。
 * これらは sidebar-1 の Custom HTML widget に貼られているが、定義ファイルの
 * require が抜けていたため未登録で、トップのサイドバーに生のショートコード
 * 文字列([kpop_birthday] 等)が表示されていた(2026-05-26 修復)。
 * ファイル側で widget_text / widget_custom_html_content に do_shortcode を有効化し、
 * is_singular('post') では二重表示を抑制する設計(ファイル冒頭コメント参照)。 */
$kpop_sidebar_sc = get_stylesheet_directory() . '/widgets/sidebar_shortcodes.php';
if ( file_exists( $kpop_sidebar_sc ) ) {
	require_once $kpop_sidebar_sc;
}

/* --- ライター紹介ページ(writer CPT・JSON 連動)を読み込む ---
 * config/x_writer_personas.json を真実のソースに /writers/ を生成。
 * 詳細は inc/writer-profiles.php 冒頭コメント参照。 */
$kpop_writer_inc = get_stylesheet_directory() . '/inc/writer-profiles.php';
if ( file_exists( $kpop_writer_inc ) ) {
	require_once $kpop_writer_inc;
}

/* --- A-3: カムバック予定ボックスを削除 ---
 * 既存サイドバー4箱に「カムバック予定」がある場合、CSS で表示抑制。
 * (functions.php に PHP 出力は無い — 段階5f の kpop_single_sidebar_extras
 *  は目次/広告/カテゴリ最新の3つで、カムバックは含まれていない。
 *  万一ウィジェットエリアにあれば style.css で .kpop-comeback-box{display:none})
 */

/* --- A-6: サイドバー新順序(個別記事のみ)---
 * 順序: 今日の誕生日 → 人気記事(WPP)→ Today's Chart → 今日読まれている記事 → 1ヶ月以内のイベント
 * 既存 kpop_single_sidebar_extras に追加する形で、新ウィジェットを generate_after_right_sidebar_content にも掛ける。
 *
 * 重要: 既存「目次/広告/カテゴリ最新」は維持。
 * 上に「今日の誕生日」を、下に「明日の誕生日」「人気記事」「Today's Chart」「今日読まれている記事」「1ヶ月以内のイベント」を追加。
 */
function kpop_m11_sidebar_prepend() {
	if ( ! is_singular( 'post' ) ) { return; }
	// 順序の先頭: 誕生日(今日+明日を1枚の統合カードで。2026-05-26 統合)
	if ( function_exists( 'kpop_render_birthday_combined' ) ) {
		kpop_render_birthday_combined();
	} elseif ( function_exists( 'kpop_render_today_birthday' ) ) {
		kpop_render_today_birthday(); // フォールバック(統合版未ロード時)
	}
}
add_action( 'generate_before_right_sidebar_content', 'kpop_m11_sidebar_prepend', 5 );
// priority 5 < 10 (kpop_single_sidebar_extras) で先頭に出る

/**
 * 人気記事の投稿ID配列を返す(サイドバー記事ページ用)。
 * range='all'      → wp_popularpostsdata(累計)を pageviews 降順
 * range='last24hours' → wp_popularpostssummary を直近24時間で集計し降順
 * 不足分は最新記事で top-up し常に $limit 件埋める(トップ [kpop_popular] と同方針)。
 * 2026-05-26: トップと記事ページのサイドバーUI統一に伴い切り出し。
 */
function kpop_sidebar_popular_ids( $range = 'all', $limit = 5 ) {
	global $wpdb;
	$limit = max( 1, (int) $limit );
	$ids   = array();

	if ( 'last24hours' === $range ) {
		$table = $wpdb->prefix . 'popularpostssummary';
		if ( $wpdb->get_var( "SHOW TABLES LIKE '" . esc_sql( $table ) . "'" ) === $table ) {
			$rows = $wpdb->get_col( $wpdb->prepare(
				"SELECT s.postid FROM `{$table}` s
				 INNER JOIN {$wpdb->posts} p ON p.ID = s.postid
				 WHERE p.post_status='publish' AND p.post_type='post'
				   AND s.view_datetime >= ( NOW() - INTERVAL 24 HOUR )
				 GROUP BY s.postid ORDER BY SUM(s.pageviews) DESC LIMIT %d", $limit ) );
			if ( $rows ) { $ids = array_map( 'intval', $rows ); }
		}
	} else {
		$table = $wpdb->prefix . 'popularpostsdata';
		if ( $wpdb->get_var( "SHOW TABLES LIKE '" . esc_sql( $table ) . "'" ) === $table ) {
			$rows = $wpdb->get_col( $wpdb->prepare(
				"SELECT d.postid FROM `{$table}` d
				 INNER JOIN {$wpdb->posts} p ON p.ID = d.postid
				 WHERE p.post_status='publish' AND p.post_type='post'
				 ORDER BY d.pageviews DESC LIMIT %d", $limit ) );
			if ( $rows ) { $ids = array_map( 'intval', $rows ); }
		}
	}

	// 不足分を最新記事で補完(重複除外)
	if ( count( $ids ) < $limit ) {
		$recent = get_posts( array(
			'post_type' => 'post', 'post_status' => 'publish',
			'numberposts' => $limit, 'fields' => 'ids',
			'exclude' => $ids, 'no_found_rows' => true,
		) );
		foreach ( $recent as $rid ) {
			if ( count( $ids ) >= $limit ) { break; }
			if ( ! in_array( (int) $rid, $ids, true ) ) { $ids[] = (int) $rid; }
		}
	}
	return $ids;
}

function kpop_m11_sidebar_append() {
	if ( ! is_singular( 'post' ) ) { return; }

	// 明日の誕生日は今日と統合カード(prepend)に移動済み。ここでは出さない。

	// 人気記事(WPP 累計)— トップの [kpop_popular] と同じサムネ付きUIに統一(2026-05-26)
	$popular_ids = kpop_sidebar_popular_ids( 'all', 5 );
	if ( $popular_ids ) {
		echo '<div class="kpop-sidebar-box kpop-popular-all" role="region" aria-label="人気記事(累計)">';
		echo '<h2 class="kpop-box-title">人気記事 <span class="kpop-box-en">POPULAR</span></h2>';
		echo '<ul class="kpop-popular-list kpop-thumb-list">';
		foreach ( $popular_ids as $pid ) {
			echo function_exists( 'kpop_sc_thumb_item' )
				? kpop_sc_thumb_item( $pid )
				: '<li><a href="' . esc_url( get_permalink( $pid ) ) . '">' . esc_html( get_the_title( $pid ) ) . '</a></li>';
		}
		echo '</ul></div>';
	}

	// Today's Chart — チャートカテゴリ最新5件(サムネ付きに統一)
	$chart_cat = get_category_by_slug( 'chart' );
	if ( $chart_cat ) {
		$chart_q = new WP_Query( array(
			'post_type'      => 'post',
			'post_status'    => 'publish',
			'cat'            => $chart_cat->term_id,
			'posts_per_page' => 5,
			'orderby'        => 'date',
			'order'          => 'DESC',
			'no_found_rows'  => true,
		) );
		if ( $chart_q->have_posts() ) {
			echo '<div class="kpop-sidebar-box kpop-today-chart" role="region" aria-label="Today\'s Chart">';
			echo '<h2 class="kpop-box-title">Today\'s Chart <span class="kpop-box-en">CHART</span></h2>';
			echo '<ul class="kpop-chart-list kpop-thumb-list">';
			while ( $chart_q->have_posts() ) {
				$chart_q->the_post();
				echo function_exists( 'kpop_sc_thumb_item' )
					? kpop_sc_thumb_item( get_the_ID() )
					: '<li><a href="' . esc_url( get_permalink() ) . '">' . esc_html( get_the_title() ) . '</a></li>';
			}
			echo '</ul></div>';
			wp_reset_postdata();
		}
	}

	// 今日読まれている記事(WPP 24h)— サムネ付きに統一
	$today_ids = kpop_sidebar_popular_ids( 'last24hours', 5 );
	if ( $today_ids ) {
		echo '<div class="kpop-sidebar-box kpop-popular-24h" role="region" aria-label="今日読まれている記事">';
		echo '<h2 class="kpop-box-title">今日読まれている記事 <span class="kpop-box-en">TODAY</span></h2>';
		echo '<ul class="kpop-popular-list kpop-thumb-list">';
		foreach ( $today_ids as $pid ) {
			echo function_exists( 'kpop_sc_thumb_item' )
				? kpop_sc_thumb_item( $pid )
				: '<li><a href="' . esc_url( get_permalink( $pid ) ) . '">' . esc_html( get_the_title( $pid ) ) . '</a></li>';
		}
		echo '</ul></div>';
	}

	// 1ヶ月以内のイベント — TEC tribe_events から
	if ( post_type_exists( 'tribe_events' ) ) {
		$event_q = new WP_Query( array(
			'post_type'      => 'tribe_events',
			'post_status'    => 'publish',
			'posts_per_page' => 5,
			'orderby'        => 'meta_value',
			'meta_key'       => '_EventStartDate',
			'order'          => 'ASC',
			'meta_query'     => array(
				array(
					'key'     => '_EventStartDate',
					'value'   => array( date( 'Y-m-d' ), date( 'Y-m-d', strtotime( '+1 month' ) ) ),
					'compare' => 'BETWEEN',
					'type'    => 'DATE',
				),
			),
			'no_found_rows'  => true,
		) );
		if ( $event_q->have_posts() ) {
			// 2026-05-26 オーナー指示: この箱は定義上「1ヶ月以内」のイベントのみ →
			// 各行は個別ページでなくカレンダー(/events/)へ誘導する。
			$events_cal = home_url( '/events/' );
			echo '<div class="kpop-sidebar-box kpop-upcoming-events" role="region" aria-label="1ヶ月以内のイベント">';
			echo '<h2 class="widget-title">1ヶ月以内のイベント</h2>';
			echo '<ul class="kpop-side-list">';
			while ( $event_q->have_posts() ) {
				$event_q->the_post();
				$start = get_post_meta( get_the_ID(), '_EventStartDate', true );
				echo '<li><a href="' . esc_url( $events_cal ) . '" aria-label="' . esc_attr( get_the_title() . ' をカレンダーで見る' ) . '">'
					. esc_html( get_the_title() ) . '</a>'
					. ( $start ? ' <span class="kpop-event-date">' . esc_html( mysql2date( 'n/j', $start ) ) . '</span>' : '' )
					. '</li>';
			}
			echo '</ul></div>';
			wp_reset_postdata();
		}
	}
}
add_action( 'generate_before_right_sidebar_content', 'kpop_m11_sidebar_append', 20 );
// priority 20 > 10 で kpop_single_sidebar_extras の後ろに

/* --- トップページ「近日開催イベント」EVENT セクション(2026-05-26 追加)---
 * トップのメインカラムには LATEST / POP-UP / 各カテゴリ … は並ぶが
 * イベント(tribe_events)への導線が無かった(実 HTML 確認済み)。
 * front-page テンプレートはリポジトリ管理外(本番のみ)で直接編集は乖離リスクが
 * 高いため、GeneratePress の generate_after_main_content フックで「トップのみ」
 * メインカラム末尾に EVENT セクションを差し込む(kpop_render_breaking_bar と同じ
 * フック差し込み方式)。データはサイドバー箱と同じ tribe_events / _EventStartDate。
 */
function kpop_home_events_section() {
	// トップ(front page)かつメインクエリのみ。アーカイブ/個別では出さない。
	if ( ! is_front_page() || ! is_main_query() ) { return; }
	if ( ! post_type_exists( 'tribe_events' ) ) { return; }

	$today = current_time( 'Y-m-d' );
	$event_q = new WP_Query( array(
		'post_type'      => 'tribe_events',
		'post_status'    => 'publish',
		'posts_per_page' => 6,
		'orderby'        => 'meta_value',
		'meta_key'       => '_EventStartDate',
		'order'          => 'ASC',
		'meta_query'     => array(
			array(
				'key'     => '_EventStartDate',
				'value'   => $today,
				'compare' => '>=',
				'type'    => 'DATE',
			),
		),
		'no_found_rows'  => true,
	) );

	if ( ! $event_q->have_posts() ) { wp_reset_postdata(); return; }

	$events_url = function_exists( 'tribe_get_events_link' ) ? tribe_get_events_link() : home_url( '/events/' );
	// 2026-05-26 オーナー指示: 1ヶ月以内のイベントはカレンダー(/events/)へ、それ以降は個別ページへ。
	$events_cal  = home_url( '/events/' );
	$month_limit = date( 'Y-m-d', strtotime( '+1 month', strtotime( $today ) ) );

	echo '<section class="kpop-cat-section kpop-home-events" aria-label="近日開催イベント">';
	echo '<h2 class="kpop-section-title">近日開催イベント <span class="kpop-section-en">EVENT</span></h2>';
	echo '<ul class="kpop-home-event-list">';
	while ( $event_q->have_posts() ) {
		$event_q->the_post();
		$start = get_post_meta( get_the_ID(), '_EventStartDate', true );
		$venue = '';
		// 会場は本文の開催概要から拾わず、まず TEC Venue → 無ければ未表示。
		if ( function_exists( 'tribe_get_venue' ) ) {
			$venue = tribe_get_venue( get_the_ID() );
		}
		// 開始日(YYYY-MM-DD部分)が +1ヶ月以内ならカレンダーへ、先のものは個別ページへ。
		$soon       = ( $start && substr( $start, 0, 10 ) <= $month_limit );
		$event_href = $soon ? $events_cal : get_permalink();
		$date_label = $start ? esc_html( mysql2date( 'n月j日', $start ) ) : '';
		echo '<li class="kpop-home-event-item">';
		echo '<a class="kpop-home-event-link" href="' . esc_url( $event_href ) . '"'
			. ( $soon ? ' aria-label="' . esc_attr( get_the_title() . ' をカレンダーで見る' ) . '"' : '' ) . '>';
		if ( $date_label ) {
			echo '<span class="kpop-home-event-date">' . $date_label . '</span>';
		}
		echo '<span class="kpop-home-event-title">' . esc_html( get_the_title() ) . '</span>';
		if ( $venue ) {
			echo '<span class="kpop-home-event-venue">' . esc_html( $venue ) . '</span>';
		}
		echo '</a></li>';
	}
	echo '</ul>';
	echo '<p class="kpop-more-wrap"><a class="kpop-more" href="' . esc_url( $events_url ) . '">イベントカレンダーをすべて見る</a></p>';
	echo '</section>';
	wp_reset_postdata();
}
// オーナー要望(2026-05-27): トップ新着記事下の EVENT セクションは削除。
// サイドバーのイベントカード(kpop_home_sidebar_events)は残す。
// add_action( 'generate_after_main_content', 'kpop_home_events_section' );

/**
 * トップページ本文下(新着記事の下)に「POPUP」セクションを出す(2026-05-27 オーナー要望)。
 * popup は category=popup の通常記事。新着記事と同じ .kpop-card / .kpop-cat-grid で
 * 6件カード表示し、/category/popup/ への導線を付ける。EVENT 削除で空いた
 * generate_after_main_content に差し込む(トップのメインクエリのみ)。
 */
function kpop_home_popup_section() {
	if ( ! is_front_page() || ! is_main_query() ) { return; }

	$q = new WP_Query( array(
		'post_type'           => 'post',
		'post_status'         => 'publish',
		'category_name'       => 'popup',
		'posts_per_page'      => 8,
		'ignore_sticky_posts' => true,
		'no_found_rows'       => true,
	) );
	if ( ! $q->have_posts() ) { wp_reset_postdata(); return; }

	$popup_url = home_url( '/category/popup/' );
	echo '<section class="kpop-cat-section kpop-home-popup" aria-label="ポップアップ">';
	echo '<h2 class="kpop-section-title">ポップアップ <span class="kpop-section-en">POPUP</span></h2>';
	echo '<ul class="kpop-cat-grid">';
	while ( $q->have_posts() ) {
		$q->the_post();
		echo '<li class="kpop-card">';
		echo '<a class="kpop-card-link" href="' . esc_url( get_permalink() ) . '">';
		echo '<span class="kpop-card-thumb">';
		if ( has_post_thumbnail() ) {
			the_post_thumbnail( 'medium', array( 'class' => 'kpop-card-img', 'loading' => 'lazy', 'alt' => the_title_attribute( array( 'echo' => false ) ) ) );
		}
		echo '</span>';
		echo '<span class="kpop-card-badge">ポップアップ</span>';
		echo '<span class="kpop-card-title">' . esc_html( get_the_title() ) . '</span>';
		echo '<span class="kpop-card-date">' . esc_html( get_the_date( 'n/j' ) ) . '</span>';
		echo '</a></li>';
	}
	echo '</ul>';
	echo '<p class="kpop-more-wrap"><a class="kpop-more" href="' . esc_url( $popup_url ) . '">ポップアップをすべて見る</a></p>';
	echo '</section>';
	wp_reset_postdata();
}
add_action( 'generate_after_main_content', 'kpop_home_popup_section' );

/* --- トップページ サイドバー「1ヶ月以内のイベント」箱(2026-05-26 追加)---
 * 個別記事ページには kpop_m11_sidebar_append が同じ箱を出すが、トップ(front page)
 * のサイドバーはウィジェット/本番テンプレ側で構成されておりイベント箱が無かった。
 * 既存ウィジェットとの順序競合を避けるため generate_after_right_sidebar_content
 * (サイドバー末尾)に「トップのみ」差し込む。個別記事の append 箱とは出る面が
 * 排他(is_front_page vs is_singular)なので二重表示しない。 */
function kpop_home_sidebar_events() {
	if ( ! is_front_page() || ! is_main_query() ) { return; }
	if ( ! post_type_exists( 'tribe_events' ) ) { return; }

	$today = current_time( 'Y-m-d' );
	$event_q = new WP_Query( array(
		'post_type'      => 'tribe_events',
		'post_status'    => 'publish',
		'posts_per_page' => 5,
		'orderby'        => 'meta_value',
		'meta_key'       => '_EventStartDate',
		'order'          => 'ASC',
		'meta_query'     => array(
			array(
				'key'     => '_EventStartDate',
				'value'   => array( $today, date( 'Y-m-d', strtotime( '+1 month' ) ) ),
				'compare' => 'BETWEEN',
				'type'    => 'DATE',
			),
		),
		'no_found_rows'  => true,
	) );
	if ( ! $event_q->have_posts() ) { wp_reset_postdata(); return; }

	// 2026-05-26 オーナー指示: 1ヶ月以内のイベントは個別ページでなくカレンダー(/events/)へ。
	$events_cal = home_url( '/events/' );
	echo '<div class="kpop-sidebar-box kpop-upcoming-events" role="region" aria-label="1ヶ月以内のイベント">';
	echo '<h2 class="widget-title">1ヶ月以内のイベント</h2>';
	echo '<ul class="kpop-side-list">';
	while ( $event_q->have_posts() ) {
		$event_q->the_post();
		$start = get_post_meta( get_the_ID(), '_EventStartDate', true );
		echo '<li><a href="' . esc_url( $events_cal ) . '" aria-label="' . esc_attr( get_the_title() . ' をカレンダーで見る' ) . '">'
			. esc_html( get_the_title() ) . '</a>'
			. ( $start ? ' <span class="kpop-event-date">' . esc_html( mysql2date( 'n/j', $start ) ) . '</span>' : '' )
			. '</li>';
	}
	echo '</ul></div>';
	wp_reset_postdata();
}
add_action( 'generate_after_right_sidebar_content', 'kpop_home_sidebar_events' );

/* --- Event 構造化データ(JSON-LD)の補完(2026-05-26 GSC重大エラー対応)---
 * GSC が tribe_events の Event JSON-LD で「location 欠落(重大)」「organizer/offers/image
 * 欠落(推奨)」を検出。原因: 収集パイプラインは会場名を本文の開催概要box
 * (.kpop-event-info-value)に書くだけで TEC の Venue エンティティ(_EventVenueID)に
 * 登録していないため、TEC が location を出力できない。
 * → データ移行(Venue登録)は DB リスクが高いので、TEC の JSON-LD フィルタで
 *   本文から会場名を抽出して location(Place)を補完する。image は featured→og-default、
 *   organizer はサイト運営者、url は出典(本文の出典リンク)を入れる。
 *   offers は価格データが無く不正確な offers は逆にペナルティのため出さない(url で代替)。
 * フィルタ tribe_json_ld_event_object は TEC が各 Event オブジェクトを出力直前に通す安定API。 */
if ( ! function_exists( 'kpop_event_extract_venue' ) ) :
function kpop_event_extract_venue( $post_id ) {
	// 本文の開催概要box: <span class="kpop-event-info-label">会場</span>
	//                    <span class="kpop-event-info-value">○○</span>
	$content = get_post_field( 'post_content', $post_id );
	if ( ! $content ) { return ''; }
	if ( preg_match(
		'/kpop-event-info-label">\s*会場\s*<\/span>\s*<span class="kpop-event-info-value">([^<]+)<\/span>/u',
		$content, $m ) ) {
		return trim( $m[1] );
	}
	return '';
}
endif;

if ( ! function_exists( 'kpop_augment_event_json_ld' ) ) :
function kpop_augment_event_json_ld( $data, $args, $type ) {
	// $data は stdClass の Event オブジェクト群(post_id => obj)または単一 obj。
	$objects = is_array( $data ) ? $data : array( $data );
	foreach ( $objects as $obj ) {
		if ( ! is_object( $obj ) || empty( $obj->{'@type'} ) ) { continue; }
		// post_id 解決: TEC は url から、または別途。ここでは現在ループ post を使う。
		$pid = get_the_ID();
		if ( ! $pid && isset( $obj->url ) ) {
			$pid = url_to_postid( $obj->url );
		}
		// location 補完(重大エラーの本丸)
		if ( empty( $obj->location ) && $pid ) {
			$venue = kpop_event_extract_venue( $pid );
			if ( $venue ) {
				$obj->location = array(
					'@type' => 'Place',
					'name'  => $venue,
					// 住所は不明だが Place.address が無いと一部で弱いため会場名を addressLocality 代替に
					'address' => array(
						'@type'           => 'PostalAddress',
						'addressCountry'  => 'JP',
						'addressLocality' => $venue,
					),
				);
			}
		}
		// image 補完(featured → og-default fallback)
		if ( empty( $obj->image ) && $pid ) {
			$img = get_the_post_thumbnail_url( $pid, 'full' );
			if ( ! $img ) {
				$img = home_url( '/wp-content/uploads/2026/05/og-default.png' );
			}
			$obj->image = array( $img );
		}
		// organizer 補完(サイト運営者)
		if ( empty( $obj->organizer ) ) {
			$obj->organizer = array(
				'@type' => 'Organization',
				'name'  => get_bloginfo( 'name' ),
				'url'   => home_url( '/' ),
			);
		}
		// url 補完(個別イベントページ)
		if ( empty( $obj->url ) && $pid ) {
			$obj->url = get_permalink( $pid );
		}
	}
	return $data;
}
endif;
add_filter( 'tribe_json_ld_event_object', 'kpop_augment_event_json_ld', 20, 3 );

/* --- B-4b: お気に入り機能(cookie/localStorage)— ハートアイコン + 専用ページ ---
 * 進化的拡張 (Progressive Enhancement): JS なしでも記事は読める。
 * - 個別記事ページのタイトル横にハートアイコン(クライアント JS で切替)
 * - localStorage に post_id 配列を保存
 * - /favorites/ ページで一覧表示(/page-favorites.php、固定ページ "favorites" 自動)
 */
function kpop_favorites_script() {
	if ( ! is_singular( 'post' ) && ! is_page( 'favorites' ) ) { return; }
	?>
	<script>
	(function(){
		var KEY = 'kpop_favorites';
		function load() {
			try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch(e) { return []; }
		}
		function save(arr) { localStorage.setItem(KEY, JSON.stringify(arr)); }
		// 個別記事: ハートアイコン挿入
		var heart = document.querySelector('.kpop-fav-heart');
		var pid = heart && heart.getAttribute('data-post-id');
		if (heart && pid) {
			var favs = load();
			heart.setAttribute('aria-pressed', favs.indexOf(pid) >= 0 ? 'true' : 'false');
			heart.textContent = favs.indexOf(pid) >= 0 ? '♥' : '♡';
			heart.addEventListener('click', function() {
				favs = load();
				var i = favs.indexOf(pid);
				if (i >= 0) { favs.splice(i, 1); heart.textContent = '♡'; heart.setAttribute('aria-pressed','false'); }
				else        { favs.push(pid);    heart.textContent = '♥'; heart.setAttribute('aria-pressed','true'); }
				save(favs);
			});
		}
		// /favorites/ ページ: クライアント側で一覧描画
		var listEl = document.getElementById('kpop-fav-list');
		if (listEl) {
			var favs = load();
			if (favs.length === 0) {
				listEl.innerHTML = '<p>お気に入りに登録された記事はまだありません。記事ページのハートアイコンから追加できます。</p>';
				return;
			}
			// REST API で post 情報取得(WordPress 標準 /wp-json/wp/v2/posts)
			fetch('/wp-json/wp/v2/posts?include=' + favs.join(',') + '&_embed=1')
				.then(function(r){ return r.json(); })
				.then(function(data){
					if (!Array.isArray(data) || data.length === 0) {
						listEl.innerHTML = '<p>記事を取得できませんでした。</p>';
						return;
					}
					var html = '<ul class="kpop-fav-grid">';
					data.forEach(function(p){
						var thumb = (p._embedded && p._embedded['wp:featuredmedia'] && p._embedded['wp:featuredmedia'][0]) ? p._embedded['wp:featuredmedia'][0].source_url : '';
						html += '<li class="kpop-fav-card"><a href="' + p.link + '">';
						if (thumb) html += '<img src="' + thumb + '" alt="' + (p.title.rendered || '').replace(/<[^>]*>/g, '').replace(/"/g, '&quot;') + '" loading="lazy">';
						html += '<span class="kpop-fav-title">' + (p.title.rendered || '') + '</span>';
						html += '</a></li>';
					});
					html += '</ul>';
					listEl.innerHTML = html;
				})
				.catch(function(){ listEl.innerHTML = '<p>読み込み中にエラーが発生しました。</p>'; });
		}
	})();
	</script>
	<?php
}
add_action( 'wp_footer', 'kpop_favorites_script' );

/* --- B-7: 内部リンク自動生成(CPT idol_artist 連動)---
 * 本文中の CPT idol_artist 投稿タイトルにマッチするキーワードを /artists/{slug}/ にリンク化。
 * 同一キーワードは初回出現のみリンク(冗長回避)。
 * K-POPキーワード境界マッチ(Day 6 知見): 短語 V/RM/Lisa の誤マッチ防止のため
 * 既存 lib/popup_event_fetcher.py の語境界ロジック相当を PHP 側にも実装。
 */
function kpop_inject_internal_links( $content ) {
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) { return $content; }
	static $cache = null;
	if ( $cache === null ) {
		$cache = array();
		$q = new WP_Query( array(
			'post_type'      => 'idol_artist',
			'post_status'    => 'publish',
			'posts_per_page' => 100,
			'no_found_rows'  => true,
		) );
		while ( $q->have_posts() ) {
			$q->the_post();
			$title = get_the_title();
			$slug  = get_post_field( 'post_name', get_the_ID() );
			// 3文字未満のタイトルは誤マッチ多発なのでスキップ(V/RM 等)
			if ( mb_strlen( $title ) < 3 ) { continue; }
			$cache[ $title ] = $slug;
		}
		wp_reset_postdata();
		// 長いキーワードから優先マッチ(GRAPEVINE が V より先にマッチするのを保証)
		uksort( $cache, function( $a, $b ) { return mb_strlen( $b ) - mb_strlen( $a ); } );
	}
	if ( empty( $cache ) ) { return $content; }

	// HTML を「タグ」と「テキスト」に分割し、テキストノードだけを置換対象にする。
	// こうしないと <img src="...Jungkook.jpg" alt="..."> の属性値内にもマッチし、
	// タグ内に <a> を注入して画像タグを破壊してしまう(alt 欠落 = a11y 違反の真因)。
	$segments = preg_split( '/(<[^>]+>)/', $content, -1, PREG_SPLIT_DELIM_CAPTURE );

	// 既存リンク(<a>...</a>)の内側にもネストさせない。タグ深度を追う。
	$in_anchor = 0;
	$linked    = array();

	foreach ( $segments as $i => $seg ) {
		if ( $seg === '' ) { continue; }
		// タグ要素はそのまま通す。<a>/<a ...> で深度+1、</a> で深度-1。
		if ( $seg[0] === '<' ) {
			if ( preg_match( '/^<a[\s>]/i', $seg ) )      { $in_anchor++; }
			elseif ( preg_match( '/^<\/a\s*>/i', $seg ) ) { $in_anchor = max( 0, $in_anchor - 1 ); }
			continue;
		}
		// アンカー内のテキストは二重リンク防止のためスキップ。
		if ( $in_anchor > 0 ) { continue; }

		// このテキストノードに対してのみ、キーワードを1回ずつ置換。
		foreach ( $cache as $title => $slug ) {
			if ( isset( $linked[ $title ] ) ) { continue; }
			$pattern = '/(?<![\w])(' . preg_quote( $title, '/' ) . ')(?![\w])/u';
			$seg = preg_replace_callback( $pattern, function( $m ) use ( $slug, $title, &$linked ) {
				if ( isset( $linked[ $title ] ) ) { return $m[0]; }
				$linked[ $title ] = true;
				return sprintf(
					'<a class="kpop-auto-link" href="/artists/%s/">%s</a>',
					esc_attr( $slug ),
					esc_html( $m[1] )
				);
			}, $seg, 1 );
		}
		$segments[ $i ] = $seg;
	}

	return implode( '', $segments );
}
add_filter( 'the_content', 'kpop_inject_internal_links', 30 );

/* ── 3行まとめ(.kpj-summary)を本文から抜き出して冒頭(ヒーロー画像の前)へ ──
 * パイプラインは本文HTML内に <div class="kpj-summary">...</div> を埋め込むが、
 * 出典行の後ろなどに沈んで「冒頭の TL;DR」として機能していなかった。
 * 表示時に本文から除去してグローバルに退避し、content-single.php が
 * タイトル直後に描画する。DB本文は一切変更しない(非破壊)。
 * prio 4 = 出典マーキング(5)・リンク注入(30)より前に実行。 */
$GLOBALS['kpop_extracted_summary'] = '';
function kpop_extract_summary( $content ) {
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) { return $content; }
	// kpj-summary は単純構造(ネスト div なし)。最初の1個だけを対象に抽出。
	if ( preg_match( '/<div class="kpj-summary">.*?<\/div>/s', $content, $m ) ) {
		$GLOBALS['kpop_extracted_summary'] = $m[0];
		$content = str_replace( $m[0], '', $content );
	}
	return $content;
}
add_filter( 'the_content', 'kpop_extract_summary', 4 );

/* テンプレートから呼ぶ: 退避した3行まとめを描画(無ければ何もしない)。
 * 呼び出し前に本文(the_content)を一度バッファリングして抽出を確定させること。
 * content-single.php がその順序制御を担う。 */
function kpop_render_extracted_summary() {
	if ( ! empty( $GLOBALS['kpop_extracted_summary'] ) ) {
		echo '<div class="kpj-summary-lead">' . $GLOBALS['kpop_extracted_summary'] . '</div>';
	}
}

/* 引用記事の先頭にある出典キャプション(<p>画像: ...元記事より</p>)に
 * クラス kpop-img-credit を付与する。これがないと CSS の
 * .entry-content > p:first-of-type(リード段落拡大)が出典行に誤適用され、
 * 本文より出典が大きく表示される不具合になる(soompi以外の引用記事で発覚)。
 * prio 5 = リンク注入(30)より前に走らせ、構造判定を素の状態で行う。 */
function kpop_mark_image_credit( $content ) {
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) { return $content; }
	// 先頭の <p>(属性なし)で、中身が「画像:」で始まるものだけにクラスを付ける。
	return preg_replace(
		'/\A(\s*)<p>(\s*画像[:：])/u',
		'$1<p class="kpop-img-credit">$2',
		$content,
		1
	);
}
add_filter( 'the_content', 'kpop_mark_image_credit', 5 );

/* [2] 本文中にバラバラに出る出典表記を、末尾に小さくまとめる(2026-05-26)。
 * 対象: 本文直下の <p>(class に citation-source / citation-cta を含む、または
 *       「出典:」「引用元:」で始まる段落)。
 * 保護: <figure> 内の figcaption 出典(画像の著作権明示)は動かさない。
 *       → <figure>...</figure> をプレースホルダに退避してから処理する。
 * 動作: 該当 <p> を本文から除去し、URLで重複排除のうえ末尾に
 *       <aside class="kpop-sources"> としてまとめて小さく描画。DBは非破壊。 */
function kpop_consolidate_sources( $content ) {
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) { return $content; }

	// 既存記事の <h2>情報ソース</h2><ul>...</ul> を控えめな aside に格下げ([2])。
	// 本文と同格の大見出しで出典が目立つ問題を、表示時に小サイズ化(DB非破壊)。
	$content = preg_replace_callback(
		'/<h2[^>]*>\s*情報ソース\s*<\/h2>\s*(<ul\b.*?<\/ul>)/is',
		function ( $m ) {
			return '<aside class="kpop-sources" aria-label="情報ソース">'
				. '<p class="kpop-sources-label">情報ソース・出典</p>'
				. preg_replace( '/<ul\b[^>]*>/i', '<ul class="kpop-sources-list">', $m[1], 1 )
				. '</aside>';
		},
		$content
	);
	// h2 の直後が <p>(元記事リンク等)のパターンも格下げ
	$content = preg_replace_callback(
		'/<h2[^>]*>\s*情報ソース\s*<\/h2>\s*(<p\b.*?<\/p>)/is',
		function ( $m ) {
			return '<aside class="kpop-sources" aria-label="情報ソース">'
				. '<p class="kpop-sources-label">情報ソース・出典</p>' . $m[1] . '</aside>';
		},
		$content
	);

	if ( strpos( $content, '出典' ) === false && strpos( $content, '引用元' ) === false ) {
		return $content;
	}

	// figure ブロックを退避(figcaption の出典は保持・移動しない)
	$figures = array();
	$content = preg_replace_callback( '/<figure\b.*?<\/figure>/is', function ( $m ) use ( &$figures ) {
		$key = '%%KPOPFIG' . count( $figures ) . '%%';
		$figures[ $key ] = $m[0];
		return $key;
	}, $content );

	// 本文直下の出典段落を収集して除去。
	// 注意: popup 記事の <p class="kpop-citation-cta"> は content-single.php の
	// CTA 移動ロジックがマーカーとして参照するため、消さない(除外)。
	$collected = array();
	$pattern = '/<p\b[^>]*>\s*(?:出典|引用元)[:：].*?<\/p>/isu';
	$content = preg_replace_callback( $pattern, function ( $m ) use ( &$collected ) {
		if ( strpos( $m[0], 'kpop-citation-cta' ) !== false ) {
			return $m[0]; // popup CTA マーカーは温存
		}
		// <a href> を取り出して dedup 用に保持
		if ( preg_match( '/<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)<\/a>/is', $m[0], $a ) ) {
			$collected[ $a[1] ] = wp_strip_all_tags( $a[2] ) ?: $a[1];
		} else {
			// リンク無し出典はテキストだけ拾う
			$txt = trim( wp_strip_all_tags( $m[0] ) );
			if ( $txt ) { $collected[ $txt ] = ''; }
		}
		return ''; // 本文からは除去
	}, $content );

	// figure を復元
	if ( $figures ) {
		$content = strtr( $content, $figures );
	}

	// 収集した出典が複数あるときだけ末尾に集約(1件以下なら元のままで十分)
	if ( count( $collected ) >= 2 ) {
		$items = '';
		foreach ( $collected as $url => $label ) {
			if ( $label === '' && filter_var( $url, FILTER_VALIDATE_URL ) === false ) {
				// テキストのみ出典
				$items .= '<li>' . esc_html( $url ) . '</li>';
			} else {
				$items .= '<li><a href="' . esc_url( $url ) . '" rel="noopener nofollow">'
					. esc_html( $label ?: $url ) . '</a></li>';
			}
		}
		$content .= '<aside class="kpop-sources" aria-label="情報ソース">'
			. '<p class="kpop-sources-label">情報ソース・出典</p>'
			. '<ul class="kpop-sources-list">' . $items . '</ul></aside>';
	} elseif ( count( $collected ) === 1 ) {
		// 1件のみ: 元の位置から消してしまったので末尾に小さく1行で戻す
		foreach ( $collected as $url => $label ) {
			$content .= '<aside class="kpop-sources" aria-label="情報ソース">'
				. '<p class="kpop-sources-label">出典: '
				. ( ( $label === '' && filter_var( $url, FILTER_VALIDATE_URL ) === false )
					? esc_html( $url )
					: '<a href="' . esc_url( $url ) . '" rel="noopener nofollow">' . esc_html( $label ?: $url ) . '</a>' )
				. '</p></aside>';
		}
	}

	return $content;
}
add_filter( 'the_content', 'kpop_consolidate_sources', 35 );

/* ==========================================================================
   M11.5 段階9.5 (Day 9) — C ポップアップ刷新
   ACF 12項目 + taxonomy(popup_area / popup_status)+ archive フィルタ
   ========================================================================== */

/* --- C-1: 専用 taxonomy 登録 ---
 * popup_area:   14区分 + 韓国2区分 = 16 terms
 * popup_status: 開催前 / 開催中 / 終了
 * post_type='post' に紐付け(既存 popup カテゴリ運用と共存)
 */
function kpop_register_popup_taxonomies() {
	// popup_area
	register_taxonomy( 'popup_area', array( 'post' ), array(
		'labels' => array(
			'name'          => 'ポップアップエリア',
			'singular_name' => 'エリア',
			'menu_name'     => 'エリア',
		),
		'public'            => true,
		'show_ui'           => true,
		'show_in_rest'      => true,
		'show_admin_column' => true,
		'hierarchical'      => false,
		'rewrite'           => array( 'slug' => 'popup-area', 'with_front' => false ),
	) );
	// popup_status
	register_taxonomy( 'popup_status', array( 'post' ), array(
		'labels' => array(
			'name'          => 'ポップアップ状況',
			'singular_name' => '状況',
			'menu_name'     => '状況',
		),
		'public'            => true,
		'show_ui'           => true,
		'show_in_rest'      => true,
		'show_admin_column' => true,
		'hierarchical'      => false,
		'rewrite'           => array( 'slug' => 'popup-status', 'with_front' => false ),
	) );
	// popup_genre(1.6: kbuzzlab sp-cat 由来のジャンル。post に紐付け、非階層)
	register_taxonomy( 'popup_genre', array( 'post' ), array(
		'labels' => array(
			'name'          => 'ポップアップジャンル',
			'singular_name' => 'ジャンル',
			'menu_name'     => 'ジャンル',
		),
		'public'            => true,
		'show_ui'           => true,
		'show_in_rest'      => true,
		'show_admin_column' => true,
		'hierarchical'      => false,
		'rewrite'           => array( 'slug' => 'popup-genre', 'with_front' => false ),
	) );
}
add_action( 'init', 'kpop_register_popup_taxonomies', 5 );

/* --- 初回 term 投入(エリア16 + 状況3)---
 * 既に terms があれば skip(冪等)
 */
function kpop_seed_popup_terms() {
	if ( get_option( 'kpop_popup_terms_seeded' ) === '1' ) { return; }
	$areas = array(
		'tokyo'     => '東京',
		'osaka'     => '大阪',
		'nagoya'    => '名古屋',
		'hokkaido'  => '北海道',
		'tohoku'    => '東北',
		'kanto'     => '関東',
		'chubu'     => '中部',
		'kinki'     => '近畿',
		'chugoku'   => '中国',
		'shikoku'   => '四国',
		'kyushu'    => '九州',
		'okinawa'   => '沖縄',
		'seoul'     => 'ソウル',
		'busan'     => '釜山',
	);
	foreach ( $areas as $slug => $name ) {
		if ( ! term_exists( $slug, 'popup_area' ) ) {
			wp_insert_term( $name, 'popup_area', array( 'slug' => $slug ) );
		}
	}
	$statuses = array(
		'upcoming' => '開催前',
		'ongoing'  => '開催中',
		'ended'    => '終了',
	);
	foreach ( $statuses as $slug => $name ) {
		if ( ! term_exists( $slug, 'popup_status' ) ) {
			wp_insert_term( $name, 'popup_status', array( 'slug' => $slug ) );
		}
	}
	update_option( 'kpop_popup_terms_seeded', '1' );
}
add_action( 'init', 'kpop_seed_popup_terms', 20 );

/* --- 1.6: popup_genre の term 投入(kbuzzlab sp-cat 踏襲)---
 * area/status とは別 option フラグで管理(既存サイトは既に terms_seeded=1 の
 * ため、ジャンルだけ別途冪等投入する)。
 */
function kpop_seed_popup_genre_terms() {
	if ( get_option( 'kpop_popup_genre_seeded' ) === '1' ) { return; }
	$genres = array(
		'celebrity'     => '芸能人・セレブ',
		'entertainment' => 'エンターテインメント',
		'character'     => 'アニメ・キャラクター',
		'gourmet'       => 'グルメ・カフェ',
		'fashion'       => 'ファッション・ビューティー',
	);
	foreach ( $genres as $slug => $name ) {
		if ( ! term_exists( $slug, 'popup_genre' ) ) {
			wp_insert_term( $name, 'popup_genre', array( 'slug' => $slug ) );
		}
	}
	update_option( 'kpop_popup_genre_seeded', '1' );
}
add_action( 'init', 'kpop_seed_popup_genre_terms', 21 );

/* --- C-1: 左サイドバーフィルタは category-popup.php 内に直接描画する方針へ変更
 * (9.5.8-A、オーナー視覚確認フィードバック反映)
 * 旧 kpop_render_popup_filter (form 横並び) は撤去。
 */

/* --- 1.4: エリア表示順マップ + ソートヘルパー -------------------------------
 * 「主要3エリア」を上段、残りを地理的に 北→南 で並べるための連想配列。
 * - kpop_popup_major_area_slugs(): 主要3エリア slug(実在 term の有無は呼び出し
 *   側でフィルタ)。ソウル/釜山/東京 を主要とする(韓国 + 日本の主力)。
 * - kpop_popup_area_geo_order(): slug => ソート順(小さいほど上=北寄り)。
 *   韓国(ソウル→仁川→…→釜山→済州)/日本(北海道→東北→関東→東京→…→沖縄)。
 *   マップに無い slug は PHP_INT_MAX 扱いで末尾。
 * - kpop_sort_popup_areas( $terms ): term 配列を地理順に並べ替えて返す。 */
function kpop_popup_major_area_slugs() {
	return array( 'seoul', 'busan', 'tokyo' );
}
function kpop_popup_area_geo_order() {
	// 韓国: 北(ソウル/仁川)→ 南(釜山)→ 済州。日本: 北海道 → 沖縄。
	// 国の塊を保つため 韓国を 100番台、日本を 200番台に分離。
	return array(
		// 韓国(北 → 南)
		'seoul'    => 100,
		'incheon'  => 110,
		'gyeonggi' => 120,
		'daejeon'  => 130,
		'daegu'    => 140,
		'gwangju'  => 150,
		'busan'    => 160,
		'jeju'     => 170,
		// 日本(北 → 南)
		'hokkaido' => 200,
		'tohoku'   => 210,
		'kanto'    => 220,
		'tokyo'    => 230,
		'chubu'    => 240,
		'nagoya'   => 250,
		'kinki'    => 260,
		'osaka'    => 270,
		'chugoku'  => 280,
		'shikoku'  => 290,
		'kyushu'   => 300,
		'okinawa'  => 310,
	);
}
function kpop_sort_popup_areas( $terms ) {
	if ( empty( $terms ) || is_wp_error( $terms ) ) { return array(); }
	$order = kpop_popup_area_geo_order();
	$terms = array_values( $terms );
	usort( $terms, function( $a, $b ) use ( $order ) {
		$oa = isset( $order[ $a->slug ] ) ? $order[ $a->slug ] : PHP_INT_MAX;
		$ob = isset( $order[ $b->slug ] ) ? $order[ $b->slug ] : PHP_INT_MAX;
		if ( $oa === $ob ) { return strcmp( $a->slug, $b->slug ); }
		return ( $oa < $ob ) ? -1 : 1;
	} );
	return $terms;
}

/* --- C-1: フィルタクエリ反映 ---
 * /category/popup/?area=tokyo&status=ongoing でクエリ修正
 */
function kpop_popup_filter_query( $query ) {
	if ( is_admin() || ! $query->is_main_query() ) { return; }
	if ( ! $query->is_category( 'popup' ) ) { return; }

	$tax_query = array();
	if ( ! empty( $_GET['area'] ) ) {
		$tax_query[] = array(
			'taxonomy' => 'popup_area',
			'field'    => 'slug',
			'terms'    => sanitize_key( $_GET['area'] ),
		);
	}
	if ( ! empty( $_GET['status'] ) ) {
		$tax_query[] = array(
			'taxonomy' => 'popup_status',
			'field'    => 'slug',
			'terms'    => sanitize_key( $_GET['status'] ),
		);
	}
	if ( ! empty( $_GET['genre'] ) ) {
		$tax_query[] = array(
			'taxonomy' => 'popup_genre',
			'field'    => 'slug',
			'terms'    => sanitize_key( $_GET['genre'] ),
		);
	}
	if ( ! empty( $tax_query ) ) {
		if ( count( $tax_query ) > 1 ) {
			$tax_query['relation'] = 'AND';
		}
		$query->set( 'tax_query', $tax_query );
	}
}
add_action( 'pre_get_posts', 'kpop_popup_filter_query' );

/**
 * トップページ(フロント)の新着記事を 30 件にする。
 * WP 全体の posts_per_page(20)は変えず、フロントのメインクエリのみ上書き=
 * カテゴリ/アーカイブ等は 20 のまま(オーナー要望: トップを 20→30)。
 */
function kpop_front_posts_per_page( $query ) {
	if ( is_admin() || ! $query->is_main_query() ) { return; }
	if ( $query->is_home() || $query->is_front_page() ) {
		$query->set( 'posts_per_page', 30 );
	}
}
add_action( 'pre_get_posts', 'kpop_front_posts_per_page' );

/* --- C-3: popup 開催状況バッジ判定(一覧 category-popup.php と個別 content-single.php で共有)
 * 開催期間(popup_period_start 〜 popup_period_end、いずれも Y-m-d 文字列)を
 * current_time('Y-m-d') と比較して 開催中 / 開催予定 / 終了 を判定する。
 * ISO(Y-m-d)文字列は辞書順 = 時系列順なので文字列比較で日付比較できる。
 *
 * @param string $start popup_period_start(Y-m-d)。空可。
 * @param string $end   popup_period_end(Y-m-d)。空可(start のみなら end=start とみなす)。
 * @return array|null  array('state'=>'ongoing|upcoming|ended', 'label'=>表示文字, 'class'=>CSSクラス接尾辞) / 判定不能なら null
 */
function kpop_popup_status_badge( $start, $end ) {
	$start = is_string( $start ) ? trim( $start ) : '';
	$end   = is_string( $end ) ? trim( $end ) : '';
	// 開始も終了も無ければ判定不能
	if ( '' === $start && '' === $end ) {
		return null;
	}
	$today = current_time( 'Y-m-d' );
	// 片方しか無い場合は補完(start のみ → 単日扱い / end のみ → 開始未定で end まで)
	$s = '' !== $start ? $start : $end;
	$e = '' !== $end ? $end : $start;
	if ( $today < $s ) {
		return array( 'state' => 'upcoming', 'label' => '開催予定', 'class' => 'is-upcoming' );
	}
	if ( $today > $e ) {
		return array( 'state' => 'ended', 'label' => '終了', 'class' => 'is-ended' );
	}
	return array( 'state' => 'ongoing', 'label' => '開催中', 'class' => 'is-ongoing' );
}

/* 開催期間を短縮表示(一覧カード用)。例: 2026-05-22 / 2026-05-31 → "5/22-5/31"。
 * 同年なら年を省く。end が無ければ start のみ。Y-m-d 以外はそのまま esc して返す側で扱う。 */
function kpop_popup_period_short( $start, $end ) {
	$fmt = function( $d ) {
		if ( preg_match( '/^(\d{4})-(\d{2})-(\d{2})$/', $d, $m ) ) {
			return (int) $m[2] . '/' . (int) $m[3];
		}
		return $d;
	};
	$start = is_string( $start ) ? trim( $start ) : '';
	$end   = is_string( $end ) ? trim( $end ) : '';
	if ( '' === $start && '' === $end ) { return ''; }
	if ( '' === $end || $end === $start ) { return $fmt( $start ); }
	if ( '' === $start ) { return $fmt( $end ); }
	return $fmt( $start ) . '-' . $fmt( $end );
}

/* 終了日(Y-m-d)から「あと何日」を算出。終了済み・算出不能は null。
 * 上段カードの期間補助テキスト用(再設計 2026-05-23)。捏造せず日付からのみ算出。 */
function kpop_popup_days_left( $end ) {
	$end = is_string( $end ) ? trim( $end ) : '';
	if ( ! preg_match( '/^(\d{4})-(\d{2})-(\d{2})$/', $end ) ) { return null; }
	$today = strtotime( current_time( 'Y-m-d' ) );
	$e = strtotime( $end );
	if ( false === $today || false === $e ) { return null; }
	$d = (int) floor( ( $e - $today ) / 86400 );
	return $d;
}

/* --- 個別改修1: SNS URL → ブランドアイコン+ラベルのピル ----------------------
 * Idol Wiki single-idol_artist.php の汎用 SVG アイコン(x/instagram/youtube/
 * tiktok)を流用。URL のドメインからプラットフォームを判定し、該当しない場合は
 * 汎用リンクアイコン(link)にフォールバックする。
 * .kpop-sns-link / .kpop-sns-icon / .kpop-sns-label の CSS パターンを共有
 * (width:max-content でラベル潰れ防止)。rel/target/aria-label を付与。 */
function kpop_popup_sns_icon_defs() {
	return array(
		'x'         => '<path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24h-6.66l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>',
		'instagram' => '<path d="M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.43.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.43.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41a3.7 3.7 0 0 1-1.38-.9 3.7 3.7 0 0 1-.9-1.38c-.16-.43-.36-1.06-.41-2.23C2.17 15.58 2.16 15.2 2.16 12s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.43-.16 1.06-.36 2.23-.41C8.42 2.17 8.8 2.16 12 2.16zm0 1.94c-3.15 0-3.5.01-4.74.07-1.14.05-1.76.24-2.17.4-.55.21-.94.47-1.35.88-.41.41-.67.8-.88 1.35-.16.41-.35 1.03-.4 2.17-.06 1.24-.07 1.59-.07 4.74s.01 3.5.07 4.74c.05 1.14.24 1.76.4 2.17.21.55.47.94.88 1.35.41.41.8.67 1.35.88.41.16 1.03.35 2.17.4 1.24.06 1.59.07 4.74.07s3.5-.01 4.74-.07c1.14-.05 1.76-.24 2.17-.4.55-.21.94-.47 1.35-.88.41-.41.67-.8.88-1.35.16-.41.35-1.03.4-2.17.06-1.24.07-1.59.07-4.74s-.01-3.5-.07-4.74c-.05-1.14-.24-1.76-.4-2.17a3.6 3.6 0 0 0-.88-1.35 3.6 3.6 0 0 0-1.35-.88c-.41-.16-1.03-.35-2.17-.4-1.24-.06-1.59-.07-4.74-.07zm0 3.3a4.6 4.6 0 1 1 0 9.2 4.6 4.6 0 0 1 0-9.2zm0 7.59a2.99 2.99 0 1 0 0-5.98 2.99 2.99 0 0 0 0 5.98zm5.86-7.81a1.08 1.08 0 1 1-2.15 0 1.08 1.08 0 0 1 2.15 0z"/>',
		'youtube'   => '<path d="M23.5 6.19a3.02 3.02 0 0 0-2.12-2.14C19.5 3.55 12 3.55 12 3.55s-7.5 0-9.38.5A3.02 3.02 0 0 0 .5 6.19C0 8.08 0 12 0 12s0 3.92.5 5.81a3.02 3.02 0 0 0 2.12 2.14c1.88.5 9.38.5 9.38.5s7.5 0 9.38-.5a3.02 3.02 0 0 0 2.12-2.14C24 15.92 24 12 24 12s0-3.92-.5-5.81zM9.55 15.57V8.43L15.82 12z"/>',
		'tiktok'    => '<path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64c.3 0 .58.05.85.13V9.4a6.34 6.34 0 0 0-5.39 10.4 6.34 6.34 0 0 0 10.86-4.43V8.69a8.16 8.16 0 0 0 4.77 1.52V6.76a4.85 4.85 0 0 1-.99-.07z"/>',
		'link'      => '<path d="M3.9 12a3.1 3.1 0 0 1 3.1-3.1h4V7H7a5 5 0 0 0 0 10h4v-1.9H7A3.1 3.1 0 0 1 3.9 12zM8 13h8v-2H8v2zm9-6h-4v1.9h4a3.1 3.1 0 0 1 0 6.2h-4V17h4a5 5 0 0 0 0-10z"/>',
	);
}
/* URL のドメインからプラットフォーム判定(該当なしは link)。 */
function kpop_popup_sns_platform( $url ) {
	$host = strtolower( (string) wp_parse_url( $url, PHP_URL_HOST ) );
	if ( false !== strpos( $host, 'x.com' ) || false !== strpos( $host, 'twitter.com' ) ) { return array( 'x', 'X' ); }
	if ( false !== strpos( $host, 'instagram.com' ) )                                      { return array( 'instagram', 'Instagram' ); }
	if ( false !== strpos( $host, 'youtube.com' ) || false !== strpos( $host, 'youtu.be' ) ) { return array( 'youtube', 'YouTube' ); }
	if ( false !== strpos( $host, 'tiktok.com' ) )                                         { return array( 'tiktok', 'TikTok' ); }
	// 汎用: ホスト名(www. を除く)をラベルに
	$label = preg_replace( '/^www\./', '', $host );
	if ( '' === $label ) { $label = '公式リンク'; }
	return array( 'link', $label );
}

/* --- C-3: popup 個別記事の 12項目テンプレート挿入 ---
 * popup カテゴリの単記事のとき、本文末に ACF 12項目を出力。
 * content-single.php から the_content() 直後に直接呼び出す
 * (旧: the_content filter priority 40。二重描画を避けるため filter は撤去し
 *  テンプレ直呼びに統一。詳細→おすすめの順序もテンプレ側で保証する)。
 *
 * 個別改修5: 「いつ・どこで・何時」を最優先で大きく見せるレイアウトに整理。
 *   ① ヒーロー行(期間 + エリア + 営業時間)= 大きいパステルカード3枚
 *   ② サブ情報(住所 + 主催 + 予約 + 特典)= 小さい定義リスト(6色維持)
 *   空項目は行ごと非表示(個別改修6、捏造禁止)。
 */
function kpop_render_popup_details_box( $post_id ) {
	$has_in_category = has_category( 'popup', $post_id );
	if ( ! $has_in_category ) { return; }

	$has_acf = function_exists( 'get_field' );

	// 12項目を取得(ACF 優先、無ければ wp_postmeta フォールバック)
	$get = function( $key ) use ( $post_id, $has_acf ) {
		$v = $has_acf ? get_field( $key, $post_id ) : '';
		if ( '' === $v || null === $v || false === $v ) {
			$v = get_post_meta( $post_id, $key, true );
		}
		return is_string( $v ) ? trim( $v ) : $v;
	};
	$organizer    = $get( 'popup_organizer' );
	/* 主催が出典名(例 kbuzzlab)の場合は『主催』行を抑制(出典は本文末に別途明記済み、重複回避)。
	   実ブランド名が入っているときは表示を維持する。survey: 396/397=kbuzzlab, 398-400=空。 */
	$kpop_source_organizers = array( 'kbuzzlab' );
	if ( is_string( $organizer ) && in_array( strtolower( trim( $organizer ) ), $kpop_source_organizers, true ) ) {
		$organizer = '';
	}
	$period_start = $get( 'popup_period_start' );
	$period_end   = $get( 'popup_period_end' );
	$hours        = $get( 'popup_hours' );
	$area         = $get( 'popup_area' );
	$address      = $get( 'popup_address' );
	$detail       = $get( 'popup_detail' );
	$sns          = $get( 'popup_sns' );
	$reservation  = $get( 'popup_reservation' );
	$benefit      = $get( 'popup_benefit' );
	$map_embed    = $get( 'popup_map_embed' );
	$address_ko   = $get( 'popup_address_ko' );
	$source_url   = $get( 'popup_source_url' );

	// 何もデータが無いなら出力しない
	if ( ! $organizer && ! $period_start && ! $detail && ! $address && ! $source_url ) { return; }

	$badge = kpop_popup_status_badge( $period_start, $period_end );

	echo '<section class="kpop-popup-detail" role="region" aria-label="ポップアップ開催情報">';

	/* ── 見出し + 開催状況バッジ ───────────────────────────── */
	echo '<div class="kpop-popup-detail-head">';
	echo '<h2 class="kpop-popup-detail-title">開催情報</h2>';
	if ( $badge ) {
		echo '<span class="kpop-popup-badge ' . esc_attr( $badge['class'] ) . '">' . esc_html( $badge['label'] ) . '</span>';
	}
	echo '</div>';

	/* ── ① 上段3カード(再設計 2026-05-23): 期間 / エリア / 予約 ──────────
	 * 1秒の視認性。各カード: アイコン+ラベル(小)+値(大)+補助テキスト(小)。
	 * 予約が空なら 予約カードを出さない(=2カード)。flex 均等で崩れない。
	 * 営業時間は per-item リストへ移動。6色は rose/mint/teal。 */
	$days_left = kpop_popup_days_left( $period_end ? $period_end : $period_start );
	$period_val = ( $period_start || $period_end ) ? kpop_popup_period_short( $period_start, $period_end ) : '';
	if ( '' === $period_val && ( $period_start || $period_end ) ) { $period_val = trim( $period_start . ' 〜 ' . $period_end ); }
	$period_sub = '';
	if ( $badge && 'ended' === $badge['state'] ) { $period_sub = '終了'; }
	elseif ( null !== $days_left && $days_left > 0 ) { $period_sub = 'あと' . $days_left . '日'; }
	elseif ( null !== $days_left && 0 === $days_left ) { $period_sub = '本日まで'; }
	$resv_sub = '';
	if ( $reservation ) {
		if ( false !== strpos( $reservation, '不要' ) ) { $resv_sub = '当日OK'; }
		elseif ( false !== strpos( $reservation, '予約' ) ) { $resv_sub = '要チェック'; }
	}
	$hero = array(
		array( 'icon' => '📅', 'label' => '期間',  'color' => 'rose', 'val' => $period_val,   'sub' => $period_sub ),
		array( 'icon' => '📍', 'label' => 'エリア', 'color' => 'mint', 'val' => $area,         'sub' => $area ? 'ソウル' : '' ),
		array( 'icon' => '🎫', 'label' => '予約',  'color' => 'teal', 'val' => $reservation,  'sub' => $resv_sub ),
	);
	$has_hero = false;
	foreach ( $hero as $h ) { if ( $h['val'] ) { $has_hero = true; break; } }
	if ( $has_hero ) {
		echo '<div class="kpop-popup-hero kpop-popup-hero--3">';
		foreach ( $hero as $h ) {
			if ( ! $h['val'] ) { continue; }
			$ccls = ' kpop-popup-row--' . sanitize_html_class( $h['color'] );
			echo '<div class="kpop-popup-hero-card' . esc_attr( $ccls ) . '">';
			echo '<span class="kpop-popup-hero-label"><span class="kpop-popup-ic" aria-hidden="true">' . esc_html( $h['icon'] ) . '</span>' . esc_html( $h['label'] ) . '</span>';
			echo '<span class="kpop-popup-hero-val">' . nl2br( esc_html( $h['val'] ) ) . '</span>';
			if ( $h['sub'] ) { echo '<span class="kpop-popup-hero-sub">' . esc_html( $h['sub'] ) . '</span>'; }
			echo '</div>';
		}
		echo '</div>';
	}

	/* ── ①.5 特典 強調バー(再設計): ピンク主役・値ありのみ・1段。 */
	if ( $benefit ) {
		echo '<div class="kpop-popup-benefit-bar">';
		echo '<span class="kpop-popup-benefit-ic" aria-hidden="true">🎁</span>';
		echo '<span class="kpop-popup-benefit-label">特典</span>';
		echo '<span class="kpop-popup-benefit-text">' . nl2br( esc_html( $benefit ) ) . '</span>';
		echo '</div>';
	}

	/* ── ② サブ情報(定義リスト)。アイコン文字 + ラベル + 値 ──
	 * 1.1: 項目ごとにパステル6色をローテーション('color' = CSS クラス接尾辞)。
	 * 6色(rose/lavender/mint/peach/blue/teal)は style.css で
	 * 不透明パステル背景 + 同系濃色文字(全ペア AA 4.5:1+ を python WCAG 検証済)。
	 * 改修5/6: 住所・主催を上に、予約・特典はデータがあるときのみ。 */
	$rows = array(
		array( 'icon' => '🏢', 'label' => '主催',   'color' => 'blue',     'val' => $organizer ),
		array( 'icon' => '🕒', 'label' => '営業時間', 'color' => 'lavender', 'val' => $hours ),
	);
	$has_rows = false;
	foreach ( $rows as $r ) { if ( $r['val'] ) { $has_rows = true; break; } }
	if ( $has_rows ) {
		echo '<dl class="kpop-popup-detail-list">';
		foreach ( $rows as $r ) {
			if ( ! $r['val'] ) { continue; }
			$ccls = ' kpop-popup-row--' . sanitize_html_class( $r['color'] );
			/* 住所分割バグ根治: dt+dd を1カード(.kpop-popup-item)で囲む。
			   div in dl は HTML5 で valid。grid item が1カード=ラベルと値が分離しない。 */
			echo '<div class="kpop-popup-item' . esc_attr( $ccls ) . '">';
			echo '<dt class="kpop-popup-dt' . esc_attr( $ccls ) . '"><span class="kpop-popup-ic" aria-hidden="true">' . esc_html( $r['icon'] ) . '</span>' . esc_html( $r['label'] ) . '</dt>';
			echo '<dd class="kpop-popup-dd' . esc_attr( $ccls ) . '">' . nl2br( esc_html( $r['val'] ) ) . '</dd>';
			echo '</div>';
		}
		echo '</dl>';
	}

	/* ── イベント詳細(本文段落) ───────────────────────────── */
	if ( $detail ) {
		echo '<div class="kpop-popup-desc">';
		echo '<h3 class="kpop-popup-subhead">イベント詳細</h3>';
		echo '<p class="kpop-popup-desc-text">' . nl2br( esc_html( $detail ) ) . '</p>';
		echo '</div>';
	}

	/* ── SNS(改行区切りの複数 URL を ブランドアイコン+ラベルのピルに)──
	 * 個別改修1: テキストリンクから .kpop-sns-link(Idol Wiki と共有)へ。
	 * URL ドメインからプラットフォーム判定、該当なしは汎用 link アイコン。 */
	if ( $sns && preg_match_all( '#https?://[^\s]+#', $sns, $m ) ) {
		$icon_defs = kpop_popup_sns_icon_defs();
		echo '<div class="kpop-popup-sns">';
		echo '<h3 class="kpop-popup-subhead">SNS・公式リンク</h3>';
		echo '<ul class="kpop-popup-sns-list kpop-idol-sns" aria-label="公式アカウントとリンク">';
		foreach ( $m[0] as $u ) {
			$u = rtrim( $u, '.,)】」' );
			list( $platform, $label ) = kpop_popup_sns_platform( $u );
			$svg = isset( $icon_defs[ $platform ] ) ? $icon_defs[ $platform ] : $icon_defs['link'];
			echo '<li>';
			echo '<a class="kpop-sns-link kpop-sns-' . esc_attr( $platform ) . '" href="' . esc_url( $u ) . '" rel="noopener noreferrer nofollow" target="_blank" aria-label="' . esc_attr( $label . '（外部サイト・新しいタブで開く）' ) . '">';
			echo '<svg class="kpop-sns-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false">' . $svg . '</svg>'; // phpcs:ignore — 固定SVGリテラル
			echo '<span class="kpop-sns-label">' . esc_html( $label ) . '</span>';
			echo '</a>';
			echo '</li>';
		}
		echo '</ul>';
		echo '</div>';
	}

	/* ── 地図(1.3) ──────────────────────────────────────────────
	 * 優先: popup_map_embed があればそれを iframe 表示。
	 * フォールバック: map_embed が空でも popup_address があれば、住所から
	 *   https://www.google.com/maps?q={URLエンコード住所}&output=embed を
	 *   自前生成して iframe 表示(kbuzzlab は naver.me リンクのみで Google
	 *   iframe を持たないため)。iframe は loading=lazy + title 属性(a11y)。
	 *   さらに住所がある場合は「Google マップで開く」外部リンクも併記。 */
	/* ── 住所+地図 統合カード(再設計): 日本語住所 + ハングル併記 + iframe 同梱。
	 *   Googleマップ「で開く」CTA は削除(地図は同カード内に表示済みのため)。
	 *   map_embed があればそれを、無ければ住所から Google maps embed を自前生成。 */
	if ( $address || $map_embed ) {
		echo '<div class="kpop-popup-addrmap kpop-popup-row--peach">';
		if ( $address ) {
			echo '<div class="kpop-popup-addrmap-head">';
			echo '<span class="kpop-popup-ic" aria-hidden="true">🏠</span>';
			echo '<div class="kpop-popup-addrmap-text">';
			echo '<span class="kpop-popup-addr-ja">' . nl2br( esc_html( $address ) ) . '</span>';
			if ( $address_ko ) {
				echo '<span class="kpop-popup-addr-ko" lang="ko">' . esc_html( $address_ko ) . '</span>';
			}
			echo '</div>';
			echo '</div>';
		}
		$map_src = $map_embed;
		if ( ! $map_src && $address ) {
			$map_src = 'https://www.google.com/maps?q=' . rawurlencode( $address ) . '&output=embed';
		}
		if ( $map_src ) {
			$map_title = $address ? '開催場所の地図(' . $address . ')' : '開催場所の地図';
			echo '<div class="kpop-popup-addrmap-frame">';
			echo '<iframe src="' . esc_url( $map_src ) . '" width="100%" height="300" style="border:0" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="' . esc_attr( $map_title ) . '"></iframe>';
			echo '</div>';
		}
		echo '</div>';
	}

	/* ── 引用元URL(Layer 2 引用記事のため著作権表示として必須) ── */
	if ( $source_url ) {
		echo '<div class="kpop-popup-source">';
		echo '<p class="kpop-popup-source-label">出典: <a href="' . esc_url( $source_url ) . '" rel="nofollow noopener external" target="_blank" class="kpop-popup-source-link">' . esc_html( $source_url ) . '</a></p>';
		echo '</div>';
	}
	echo '</section>';
}

/* ==========================================================================
   M11.5 段階9.5.8-F E: popup 個別記事のサイドバー撤去 + おすすめ popup 5件
   オーナー視覚確認フィードバック反映
   ========================================================================== */

/* --- E-1: in_category('popup') の単記事はサイドバー非表示 --- */
add_filter( 'generate_show_right_sidebar', function( $show ) {
	if ( is_singular( 'post' ) && in_category( 'popup' ) ) {
		return false;
	}
	return $show;
} );
/* generate_show_right_sidebar だけでは GP のレイアウト/ウィジェット構築が残る場合が
   あるため、generate_sidebar_layout でも no-sidebar を強制(popup単記事のみ)。
   左バーはテンプレ側 .kpop-popup-single-layout で別途描画(2026-05-21)。 */
add_filter( 'generate_sidebar_layout', function( $layout ) {
	if ( is_singular( 'post' ) && in_category( 'popup' ) ) {
		return 'no-sidebar';
	}
	return $layout;
} );

/* --- E-2: in_category('popup') の単記事は本文末に「おすすめのポップアップ」5件
 *   the_content filter で popup 詳細(kpop_render_popup_details_box)の後ろに
 *   推奨セクションを追加する。 */
function kpop_render_popup_recommendations( $current_post_id ) {
	// 同じ popup_area の他 popup を優先
	$area_terms = wp_get_post_terms( $current_post_id, 'popup_area', array( 'fields' => 'ids' ) );
	$args = array(
		'post_type'           => 'post',
		'post_status'         => 'publish',
		'category_name'       => 'popup',
		'post__not_in'        => array( $current_post_id ),
		'posts_per_page'      => 5,
		'orderby'             => 'date',
		'order'               => 'DESC',
		'ignore_sticky_posts' => true,
		'no_found_rows'       => true,
	);
	if ( ! empty( $area_terms ) && ! is_wp_error( $area_terms ) ) {
		$args['tax_query'] = array( array(
			'taxonomy' => 'popup_area',
			'field'    => 'term_id',
			'terms'    => $area_terms,
		) );
	}
	$q = new WP_Query( $args );
	// 件数が足らない場合は area 制限を外して再取得(5件確保)
	if ( $q->found_posts < 3 && isset( $args['tax_query'] ) ) {
		unset( $args['tax_query'] );
		$q = new WP_Query( $args );
	}
	if ( ! $q->have_posts() ) { return; }

	echo '<section class="kpop-popup-recommendations" aria-label="おすすめのポップアップ">';
	echo '<h2 class="kpop-popup-recommendations-heading">おすすめのポップアップ</h2>';
	echo '<ul class="kpop-popup-recommendations-grid">';
	while ( $q->have_posts() ) {
		$q->the_post();
		$rec_id   = get_the_ID();
		$rec_area = get_post_meta( $rec_id, 'popup_area', true );
		$rec_start = get_post_meta( $rec_id, 'popup_period_start', true );
		?>
		<li class="popup-card">
			<a class="popup-card-link" href="<?php the_permalink(); ?>">
				<span class="popup-card-thumb">
					<?php if ( has_post_thumbnail() ) {
						the_post_thumbnail( 'medium', array( 'alt' => the_title_attribute( array( 'echo' => false ) ), 'loading' => 'lazy' ) );
					} else {
						echo '<span class="popup-card-thumb--placeholder" aria-hidden="true"></span>';
					} ?>
				</span>
				<span class="popup-card-body">
					<span class="popup-card-label">POP-UP</span>
					<span class="popup-card-title"><?php the_title(); ?></span>
					<?php if ( $rec_area || $rec_start ) : ?>
						<span class="popup-card-meta">
							<?php if ( $rec_area ) : ?>
								<span class="popup-card-area">📍 <?php echo esc_html( $rec_area ); ?></span>
							<?php endif; ?>
							<?php if ( $rec_start ) : ?>
								<span class="popup-card-date">📅 <?php echo esc_html( $rec_start ); ?></span>
							<?php endif; ?>
						</span>
					<?php endif; ?>
				</span>
			</a>
		</li>
		<?php
	}
	echo '</ul></section>';
	wp_reset_postdata();
}

/* おすすめのポップアップは content-single.php から popup 詳細の直後に直接呼び出す。
 * (旧: the_content filter priority 50。詳細を the_content filter から外してテンプレ
 *  直呼びに統一したため、順序保証のため推奨もテンプレ側で呼ぶ。二重描画も回避。) */

/* --- 個別改修3: 「近日開催予定」popup カード(popup_period_start が今日以降を期間が近い順)
 * WP_Query で meta_key=popup_period_start を meta_value で昇順に並べ、今日以降のものを
 * 期間が近い順にカード表示。現在記事は除外。カードは category-popup.php の .popup-card 流用。 */
function kpop_render_popup_upcoming( $current_post_id ) {
	$today = current_time( 'Y-m-d' );
	$q = new WP_Query( array(
		'post_type'           => 'post',
		'post_status'         => 'publish',
		'category_name'       => 'popup',
		'post__not_in'        => array( $current_post_id ),
		'posts_per_page'      => 5,
		'meta_key'            => 'popup_period_start',
		'orderby'             => 'meta_value',
		'order'               => 'ASC',
		'ignore_sticky_posts' => true,
		'no_found_rows'       => true,
		'meta_query'          => array(
			array(
				'key'     => 'popup_period_start',
				'value'   => $today,
				'compare' => '>=',
				'type'    => 'DATE',
			),
		),
	) );
	if ( ! $q->have_posts() ) { wp_reset_postdata(); return; }

	echo '<section class="kpop-popup-upcoming" aria-label="近日開催予定のポップアップ">';
	echo '<h2 class="kpop-popup-recommendations-heading">近日開催予定</h2>';
	echo '<ul class="kpop-popup-recommendations-grid">';
	while ( $q->have_posts() ) {
		$q->the_post();
		$uid    = get_the_ID();
		$u_area = get_post_meta( $uid, 'popup_area', true );
		$u_start = get_post_meta( $uid, 'popup_period_start', true );
		$u_end   = get_post_meta( $uid, 'popup_period_end', true );
		$u_period = function_exists( 'kpop_popup_period_short' ) ? kpop_popup_period_short( $u_start, $u_end ) : $u_start;
		$u_badge  = function_exists( 'kpop_popup_status_badge' ) ? kpop_popup_status_badge( $u_start, $u_end ) : null;
		?>
		<li class="popup-card">
			<a class="popup-card-link" href="<?php the_permalink(); ?>">
				<span class="popup-card-thumb">
					<?php if ( has_post_thumbnail() ) {
						the_post_thumbnail( 'medium', array( 'alt' => the_title_attribute( array( 'echo' => false ) ), 'loading' => 'lazy' ) );
					} else {
						echo '<span class="popup-card-thumb--placeholder" aria-hidden="true">';
						echo '<span class="popup-card-ph-initial">' . esc_html( mb_substr( wp_strip_all_tags( get_the_title() ), 0, 1 ) ) . '</span>';
						echo '<span class="popup-card-ph-label">POP UP</span>';
						echo '</span>';
					}
					if ( $u_badge ) {
						echo '<span class="popup-card-badge ' . esc_attr( $u_badge['class'] ) . '">' . esc_html( $u_badge['label'] ) . '</span>';
					} ?>
				</span>
				<span class="popup-card-body">
					<span class="popup-card-label">POP-UP</span>
					<span class="popup-card-title"><?php the_title(); ?></span>
					<?php if ( $u_area || $u_period ) : ?>
						<span class="popup-card-meta">
							<?php if ( $u_period ) : ?>
								<span class="popup-card-date"><span class="popup-card-ic" aria-hidden="true">📅</span><?php echo esc_html( $u_period ); ?></span>
							<?php endif; ?>
							<?php if ( $u_area ) : ?>
								<span class="popup-card-area"><span class="popup-card-ic" aria-hidden="true">📍</span><?php echo esc_html( $u_area ); ?></span>
							<?php endif; ?>
						</span>
					<?php endif; ?>
				</span>
			</a>
		</li>
		<?php
	}
	echo '</ul></section>';
	wp_reset_postdata();
}

/* --- 個別改修2: popup 個別記事の左ナビバー(カテゴリ/エリア/ジャンル常設)----------
 * category-popup.php のフィルタサイドバーと同種の内容を個別記事の左に置く。
 * エリアは popup_area の /category/popup/?area=slug リンク、ジャンルは popup_genre。
 * content-single.php(popup 記事のみ)から呼ぶ。捏造はせず、term が無いグループは非表示。 */
function kpop_render_popup_side_nav( $current_post_id ) {
	// get_cat_ID('popup') はカテゴリ「名」照合で、実カテゴリは name="ポップアップ"
	// (slug=popup) のため 0 を返し、get_category_link(0) が空文字 → サイドバーの
	// 「ポップアップ一覧」リンクとエリア/ジャンルリンクが href="" で機能しなかった。
	// slug 照合で確実に term を引く。
	$popup_term = get_term_by( 'slug', 'popup', 'category' );
	$popup_link = ( $popup_term && ! is_wp_error( $popup_term ) ) ? get_category_link( $popup_term->term_id ) : home_url( '/category/popup/' );
	// term をエリア(地理順)/ジャンルで取得
	$areas  = get_terms( array( 'taxonomy' => 'popup_area',  'hide_empty' => true ) );
	$genres = get_terms( array( 'taxonomy' => 'popup_genre', 'hide_empty' => true ) );
	if ( is_wp_error( $areas ) )  { $areas  = array(); }
	if ( is_wp_error( $genres ) ) { $genres = array(); }
	if ( function_exists( 'kpop_sort_popup_areas' ) ) {
		$areas = kpop_sort_popup_areas( $areas );
	}
	// この記事自身の area / genre slug(現在地ハイライト用)
	$cur_area_terms  = wp_get_post_terms( $current_post_id, 'popup_area',  array( 'fields' => 'slugs' ) );
	$cur_genre_terms = wp_get_post_terms( $current_post_id, 'popup_genre', array( 'fields' => 'slugs' ) );
	$cur_area  = ( ! is_wp_error( $cur_area_terms )  && ! empty( $cur_area_terms ) )  ? $cur_area_terms[0]  : '';
	$cur_genre = ( ! is_wp_error( $cur_genre_terms ) && ! empty( $cur_genre_terms ) ) ? $cur_genre_terms[0] : '';

	echo '<nav class="kpop-popup-sidenav" aria-label="ポップアップのカテゴリ・地域ナビ">';
	echo '<p class="kpop-popup-sidenav-heading"><a href="' . esc_url( $popup_link ) . '">ポップアップ一覧</a></p>';

	if ( ! empty( $areas ) ) {
		echo '<div class="kpop-popup-sidenav-group">';
		echo '<h3 class="kpop-popup-sidenav-title">エリア</h3>';
		echo '<ul class="kpop-popup-sidenav-list">';
		foreach ( $areas as $a ) {
			$href      = esc_url( add_query_arg( 'area', $a->slug, $popup_link ) );
			$is_active = ( $cur_area === $a->slug );
			$cls       = 'kpop-popup-sidenav-link' . ( $is_active ? ' is-current' : '' );
			echo '<li><a class="' . esc_attr( $cls ) . '" href="' . $href . '"' . ( $is_active ? ' aria-current="true"' : '' ) . '>' . esc_html( $a->name ) . '</a></li>';
		}
		echo '</ul>';
		echo '</div>';
	}

	if ( ! empty( $genres ) ) {
		echo '<div class="kpop-popup-sidenav-group">';
		echo '<h3 class="kpop-popup-sidenav-title">ジャンル</h3>';
		echo '<ul class="kpop-popup-sidenav-list">';
		foreach ( $genres as $g ) {
			$href      = esc_url( add_query_arg( 'genre', $g->slug, $popup_link ) );
			$is_active = ( $cur_genre === $g->slug );
			$cls       = 'kpop-popup-sidenav-link' . ( $is_active ? ' is-current' : '' );
			echo '<li><a class="' . esc_attr( $cls ) . '" href="' . $href . '"' . ( $is_active ? ' aria-current="true"' : '' ) . '>' . esc_html( $g->name ) . '</a></li>';
		}
		echo '</ul>';
		echo '</div>';
	}

	// 広告掲載をご希望の企業・団体さま向け導線(広告ページへ)
	echo '<div class="kpop-popup-sidenav-group kpop-popup-sidenav-advertise">';
	echo '<a class="kpop-popup-advertise-link" href="' . esc_url( home_url( '/advertise/' ) ) . '">ポップアップ・イベントの掲載をご希望の方へ</a>';
	echo '</div>';

	echo '</nav>';
}

/* --- E-3: popup 個別記事では「関連記事(B-4a 5枚カード)」を非表示
 *   content-single.php に直接書かれているため、CSS で対応する方が安全。
 *   ただし「おすすめのポップアップ」と二重表示にならないよう、関連記事を
 *   popup ページでは body class で hide する。 */
add_filter( 'body_class', function( $classes ) {
	if ( is_singular( 'post' ) && in_category( 'popup' ) ) {
		$classes[] = 'is-popup-single';
	}
	// M11.5 9.5.8-G C: カテゴリページに kpop-cat-{slug} body class を付与してパステル切替
	if ( is_category() ) {
		$cat = get_queried_object();
		if ( $cat && ! empty( $cat->slug ) ) {
			$classes[] = 'kpop-cat-' . sanitize_html_class( $cat->slug );
		}
	}
	return $classes;
} );

// 将来のカスタム機能はここに追加
/**
 * KPOP JOURNAL 収益化タグ wp_head 注入 (Day15 Phase3-5)
 * 子テーマ functions.php の末尾に追記する。
 *
 * 公開値(client_id / measurement_id / enabled)はテーマ内 revenue-config.json から読む。
 *   - これらは元々ページHTMLに出力される非機密値(client_id は page source 公開、G-ID も同様)。
 *   - AdSense token / secret 等の実機密はここに含めない(.env/gitignore のまま)。
 * 各フラグ false / 値なし のときは何も出力しない(本番化前と同じ無害動作)。
 * lib/revenue/adsense_tags.py のタグ形式と一致。
 */
function kpj_revenue_config() {
    static $cfg = null;
    if ($cfg !== null) return $cfg;
    $path = get_stylesheet_directory() . '/revenue-config.json';
    $cfg = array();
    if (is_readable($path)) {
        $data = json_decode(file_get_contents($path), true);
        if (is_array($data)) $cfg = $data;
    }
    return $cfg;
}

function kpj_revenue_head_tags() {
    $cfg = kpj_revenue_config();
    if (empty($cfg['delivery_enabled'])) return; // 配信無効なら何も出さない

    // --- AdSense ローダー(auto ads) ---
    $client = isset($cfg['adsense']['client_id']) ? trim($cfg['adsense']['client_id']) : '';
    $ads_on = !empty($cfg['adsense']['enabled']);
    if ($ads_on && $client !== '') {
        // client は ca-pub-XXXX 形式のみ許可(値の混入防止)
        if (preg_match('/^ca-pub-[0-9]+$/', $client)) {
            echo "\n<!-- KPJ AdSense -->\n";
            echo '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
               . esc_attr($client) . '" crossorigin="anonymous"></script>' . "\n";
        }
    }

    // --- GA4 gtag(Measurement ID G-XXXX があるときのみ) ---
    $mid = isset($cfg['ga4']['measurement_id']) ? trim($cfg['ga4']['measurement_id']) : '';
    if ($mid !== '' && preg_match('/^G-[A-Z0-9]+$/', $mid)) {
        echo "\n<!-- KPJ GA4 -->\n";
        echo '<script async src="https://www.googletagmanager.com/gtag/js?id='
           . esc_attr($mid) . '"></script>' . "\n";
        echo '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
           . 'gtag("js",new Date());gtag("config","' . esc_js($mid) . '");</script>' . "\n";
    }
}
add_action('wp_head', 'kpj_revenue_head_tags', 20);
