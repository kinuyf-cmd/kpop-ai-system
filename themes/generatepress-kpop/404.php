<?php
/**
 * 404.php — KPOP JOURNAL カスタム 404 ページ
 *
 * 存在しない/削除済みURLで WordPress が自動採用するテンプレート。
 * HTTP ステータスは 404 のまま(ソフト404にしない)、ユーザーには
 * トップ・サイト内検索・最新記事への導線を提供して回遊を促す。
 *
 * デザインは既存のブランドトークン(:root の --kpop-* / AA達成済み)と
 * カードCSS(.kpop-card / .kpop-cat-grid)を再利用する。新規CSSは
 * style.css 末尾の .kpop-404-* のみ。
 *
 * @package generatepress-kpop
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

get_header();
?>

<div class="kpop-404" role="main">
	<nav class="kpop-404-breadcrumb" aria-label="パンくず">
		<a href="<?php echo esc_url( home_url( '/' ) ); ?>">ホーム</a>
		<span aria-hidden="true">›</span>
		<span>ページが見つかりません</span>
	</nav>

	<section class="kpop-404-hero" aria-labelledby="kpop-404-title">
		<p class="kpop-404-emoji" aria-hidden="true">🎵</p>
		<p class="kpop-404-code">404</p>
		<h1 id="kpop-404-title" class="kpop-404-title">お探しのページは見つかりませんでした</h1>
		<p class="kpop-404-lead">
			ページが削除されたか、URL が変更された可能性があります。<br>
			下のリンクや検索から、お探しの情報を見つけてください。
		</p>

		<p class="kpop-404-cta-wrap">
			<a class="kpop-404-cta" href="<?php echo esc_url( home_url( '/' ) ); ?>">トップページへ戻る</a>
		</p>

		<form class="kpop-404-search" role="search" method="get"
			action="<?php echo esc_url( home_url( '/' ) ); ?>">
			<label class="screen-reader-text" for="kpop-404-s">サイト内を検索</label>
			<input type="search" id="kpop-404-s" name="s" class="search-field"
				placeholder="記事を検索（例: BTS、カムバック、ソウル旅行）"
				value="<?php echo esc_attr( get_search_query() ); ?>">
			<button type="submit" class="kpop-404-search-btn">検索</button>
		</form>
	</section>

	<?php
	$q = new WP_Query( array(
		'post_type'           => 'post',
		'post_status'         => 'publish',
		'posts_per_page'      => 8,
		'ignore_sticky_posts' => true,
		'no_found_rows'       => true,
	) );
	if ( $q->have_posts() ) :
		?>
		<section class="kpop-cat-section kpop-404-latest" aria-label="最新記事">
			<h2 class="kpop-section-title">最新の記事 <span class="kpop-section-en">LATEST</span></h2>
			<ul class="kpop-cat-grid">
				<?php
				while ( $q->have_posts() ) :
					$q->the_post();
					?>
					<li class="kpop-card">
						<a class="kpop-card-link" href="<?php echo esc_url( get_permalink() ); ?>">
							<span class="kpop-card-thumb">
								<?php
								if ( has_post_thumbnail() ) {
									the_post_thumbnail( 'medium', array(
										'class'   => 'kpop-card-img',
										'loading' => 'lazy',
										'alt'     => '',
									) );
								} else {
									echo '<span class="kpop-card-thumb--placeholder" aria-hidden="true"></span>';
								}
								?>
							</span>
							<span class="kpop-card-title"><?php echo esc_html( get_the_title() ); ?></span>
							<span class="kpop-card-date"><?php echo esc_html( get_the_date( 'n/j' ) ); ?></span>
						</a>
					</li>
					<?php
				endwhile;
				?>
			</ul>
		</section>
		<?php
	endif;
	wp_reset_postdata();
	?>
</div>

<?php
get_footer();
