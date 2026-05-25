<?php
/**
 * category-popup.php — KPOP JOURNAL /category/popup/ 専用テンプレート
 *
 * M11.5 段階9.5.8-A(2026-05-20、Day 9 オーナー視覚確認フィードバック反映)
 * オーナー要望: 「左サイドに選択を出してほしい」
 *
 * 構造(kbuzzlab.com /popup/ 参考):
 *   パンくず → カテゴリヘッダーバナー →
 *   [CSS Grid 2カラム] 左:フィルタサイドバー | 右:カードグリッド
 *
 * WP テンプレ階層: category-{slug}.php > category.php > archive.php > index.php
 * 本ファイルは popup カテゴリ専用、他カテゴリは archive.php を継続使用。
 *
 * @package generatepress-kpop
 */

if ( ! defined( 'ABSPATH' ) ) { exit; }

get_header();

$kpop_arch_title = get_the_archive_title();
$kpop_arch_name  = trim( preg_replace( '/^[^:：]+[:：]\s*/u', '', wp_strip_all_tags( $kpop_arch_title ) ) );
$kpop_total      = (int) $GLOBALS['wp_query']->found_posts;
$kpop_desc       = term_description();

$cur_area   = isset( $_GET['area'] )   ? sanitize_key( $_GET['area'] )   : '';
$cur_status = isset( $_GET['status'] ) ? sanitize_key( $_GET['status'] ) : '';
$cur_genre  = isset( $_GET['genre'] )  ? sanitize_key( $_GET['genre'] )  : '';

// カウント計算用 — taxonomy term ごとの popup category 内記事数
function kpop_popup_count_by_term( $taxonomy, $term_slug ) {
	$q = new WP_Query( array(
		'post_type'      => 'post',
		'post_status'    => 'publish',
		'category_name'  => 'popup',
		'posts_per_page' => -1,
		'fields'         => 'ids',
		'no_found_rows'  => false,
		'tax_query'      => array(
			array(
				'taxonomy' => $taxonomy,
				'field'    => 'slug',
				'terms'    => $term_slug,
			),
		),
	) );
	return (int) $q->found_posts;
}

$popup_areas    = get_terms( array( 'taxonomy' => 'popup_area',   'hide_empty' => false ) );
$popup_statuses = get_terms( array( 'taxonomy' => 'popup_status', 'hide_empty' => false ) );
$popup_genres   = get_terms( array( 'taxonomy' => 'popup_genre',  'hide_empty' => false ) );
if ( is_wp_error( $popup_areas ) )    { $popup_areas    = array(); }
if ( is_wp_error( $popup_statuses ) ) { $popup_statuses = array(); }
if ( is_wp_error( $popup_genres ) )   { $popup_genres   = array(); }

// 1.4: エリアを「主要3」+「地方(北→南)」に分けて表示。
//   主要3 = ソウル/釜山/東京 のうち実在 term のみ。残りは地理順マップで 北→南。
//   地理順 / 主要判定は functions.php のヘルパーに集約。
$kpop_major_slugs = function_exists( 'kpop_popup_major_area_slugs' ) ? kpop_popup_major_area_slugs() : array( 'seoul', 'busan', 'tokyo' );
$kpop_areas_major   = array();
$kpop_areas_regional = array();
foreach ( $popup_areas as $a ) {
	if ( in_array( $a->slug, $kpop_major_slugs, true ) ) {
		$kpop_areas_major[] = $a;
	} else {
		$kpop_areas_regional[] = $a;
	}
}
// 主要3 は major_slugs の指定順、地方は地理順(北→南)に並べる。
if ( ! empty( $kpop_areas_major ) ) {
	usort( $kpop_areas_major, function( $x, $y ) use ( $kpop_major_slugs ) {
		$ix = array_search( $x->slug, $kpop_major_slugs, true );
		$iy = array_search( $y->slug, $kpop_major_slugs, true );
		$ix = ( false === $ix ) ? PHP_INT_MAX : $ix;
		$iy = ( false === $iy ) ? PHP_INT_MAX : $iy;
		return $ix <=> $iy;
	} );
}
if ( function_exists( 'kpop_sort_popup_areas' ) ) {
	$kpop_areas_regional = kpop_sort_popup_areas( $kpop_areas_regional );
}
?>

<nav class="kpop-breadcrumb kpop-breadcrumb--archive" aria-label="パンくずリスト">
	<ol itemscope itemtype="https://schema.org/BreadcrumbList">
		<li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
			<a itemprop="item" href="<?php echo esc_url( home_url( '/' ) ); ?>"><span itemprop="name">ホーム</span></a>
			<meta itemprop="position" content="1" />
		</li>
		<li class="kpop-breadcrumb-current" itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem" aria-current="page">
			<span itemprop="name"><?php echo esc_html( $kpop_arch_name ); ?></span>
			<meta itemprop="position" content="2" />
		</li>
	</ol>
</nav>

<section class="kpop-archive-banner" aria-label="<?php echo esc_attr( $kpop_arch_name ); ?>カテゴリ">
	<div class="kpop-archive-banner-inner">
		<?php /* 個別改修8: 「CATEGORY」ラベルは冗長なので撤去(縦幅圧縮は CSS 側) */ ?>
		<h1 class="kpop-archive-title">
			<?php echo esc_html( $kpop_arch_name ); ?>
			<span class="kpop-archive-count"><?php echo esc_html( number_format( $kpop_total ) ); ?>件</span>
		</h1>
		<?php if ( $kpop_desc ) : ?>
			<div class="kpop-archive-desc"><?php echo wp_kses_post( $kpop_desc ); ?></div>
		<?php endif; ?>
	</div>
</section>

<main class="popup-archive-layout" id="main">
	<?php do_action( 'generate_before_main_content' ); ?>

	<aside class="popup-sidebar-filter" role="region" aria-label="ポップアップ絞り込み">
		<h2 class="filter-heading">絞り込み</h2>

		<?php /* エリア: 韓国 / 日本 でグループ化、横並びタグ、count 表示なし(9.5.8-G) */ ?>
		<div class="filter-group filter-group--area" data-filter="area">
			<h3 class="filter-group-title">エリア</h3>
			<ul class="filter-list filter-list--tags">
				<li>
					<a href="<?php echo esc_url( remove_query_arg( 'area' ) ); ?>" class="filter-tag<?php echo $cur_area === '' ? ' active' : ''; ?>"<?php echo $cur_area === '' ? ' aria-current="true"' : ''; ?>>
						すべて
					</a>
				</li>
			</ul>

			<?php if ( ! empty( $kpop_areas_major ) ) : ?>
				<h4 class="filter-subgroup-title">主要エリア</h4>
				<ul class="filter-list filter-list--tags">
					<?php foreach ( $kpop_areas_major as $a ) :
						$count = kpop_popup_count_by_term( 'popup_area', $a->slug );
						$href = esc_url( add_query_arg( 'area', $a->slug ) );
						$is_active = ( $cur_area === $a->slug );
						$classes = array( 'filter-tag' );
						if ( $is_active )   { $classes[] = 'active'; }
						if ( $count === 0 && ! $is_active ) { $classes[] = 'is-zero'; }
						$class_attr = ' class="' . esc_attr( implode( ' ', $classes ) ) . '"';
						?>
						<li>
							<a href="<?php echo $href; ?>"<?php echo $class_attr; ?><?php echo $is_active ? ' aria-current="true"' : ''; ?>>
								<?php echo esc_html( $a->name ); ?>
							</a>
						</li>
					<?php endforeach; ?>
				</ul>
			<?php endif; ?>

			<?php if ( ! empty( $kpop_areas_regional ) ) : ?>
				<h4 class="filter-subgroup-title">地方(北→南)</h4>
				<ul class="filter-list filter-list--tags">
					<?php foreach ( $kpop_areas_regional as $a ) :
						$count = kpop_popup_count_by_term( 'popup_area', $a->slug );
						$href = esc_url( add_query_arg( 'area', $a->slug ) );
						$is_active = ( $cur_area === $a->slug );
						$classes = array( 'filter-tag' );
						if ( $is_active )   { $classes[] = 'active'; }
						if ( $count === 0 && ! $is_active ) { $classes[] = 'is-zero'; }
						$class_attr = ' class="' . esc_attr( implode( ' ', $classes ) ) . '"';
						?>
						<li>
							<a href="<?php echo $href; ?>"<?php echo $class_attr; ?><?php echo $is_active ? ' aria-current="true"' : ''; ?>>
								<?php echo esc_html( $a->name ); ?>
							</a>
						</li>
					<?php endforeach; ?>
				</ul>
			<?php endif; ?>
		</div>

		<?php /* 状況 */ ?>
		<div class="filter-group" data-filter="status">
			<h3 class="filter-group-title">状況</h3>
			<ul class="filter-list">
				<li>
					<a href="<?php echo esc_url( remove_query_arg( 'status' ) ); ?>" class="<?php echo $cur_status === '' ? 'active' : ''; ?>"<?php echo $cur_status === '' ? ' aria-current="true"' : ''; ?>>
						すべて
					</a>
				</li>
				<?php foreach ( $popup_statuses as $s ) :
					$count = kpop_popup_count_by_term( 'popup_status', $s->slug );
					$href = esc_url( add_query_arg( 'status', $s->slug ) );
					$is_active = ( $cur_status === $s->slug );
					?>
					<li>
						<a href="<?php echo $href; ?>" class="<?php echo $is_active ? 'active' : ''; ?>"<?php echo $is_active ? ' aria-current="true"' : ''; ?>>
							<?php echo esc_html( $s->name ); ?> <span class="count"><?php echo esc_html( $count ); ?></span>
						</a>
					</li>
				<?php endforeach; ?>
			</ul>
		</div>

		<?php /* 1.6: ジャンル(popup_genre)。エリアと同じ ?genre=slug クエリ方式。
		   term が無い場合はグループごと非表示(UI を壊さない)。 */ ?>
		<?php if ( ! empty( $popup_genres ) ) : ?>
			<div class="filter-group filter-group--genre" data-filter="genre">
				<h3 class="filter-group-title">ジャンル</h3>
				<ul class="filter-list filter-list--tags">
					<li>
						<a href="<?php echo esc_url( remove_query_arg( 'genre' ) ); ?>" class="filter-tag<?php echo $cur_genre === '' ? ' active' : ''; ?>"<?php echo $cur_genre === '' ? ' aria-current="true"' : ''; ?>>
							すべて
						</a>
					</li>
					<?php foreach ( $popup_genres as $g ) :
						$count = kpop_popup_count_by_term( 'popup_genre', $g->slug );
						$href = esc_url( add_query_arg( 'genre', $g->slug ) );
						$is_active = ( $cur_genre === $g->slug );
						$classes = array( 'filter-tag' );
						if ( $is_active )   { $classes[] = 'active'; }
						if ( $count === 0 && ! $is_active ) { $classes[] = 'is-zero'; }
						$class_attr = ' class="' . esc_attr( implode( ' ', $classes ) ) . '"';
						?>
						<li>
							<a href="<?php echo $href; ?>"<?php echo $class_attr; ?><?php echo $is_active ? ' aria-current="true"' : ''; ?>>
								<?php echo esc_html( $g->name ); ?>
							</a>
						</li>
					<?php endforeach; ?>
				</ul>
			</div>
		<?php endif; ?>

		<?php if ( $cur_area || $cur_status || $cur_genre ) : ?>
			<p class="filter-reset">
				<a href="<?php echo esc_url( get_category_link( get_queried_object_id() ) ); ?>">絞り込みを解除</a>
			</p>
		<?php endif; ?>

		<?php /* 広告掲載をご希望の企業・団体さま向け導線(広告ページへ) */ ?>
		<div class="filter-group kpop-popup-filter-advertise">
			<a class="kpop-popup-advertise-link" href="<?php echo esc_url( home_url( '/advertise/' ) ); ?>">ポップアップ・イベントの掲載をご希望の方へ</a>
		</div>
	</aside>

	<section class="popup-list-section">
		<?php if ( have_posts() ) : ?>
			<ul class="popup-list">
				<?php
				while ( have_posts() ) :
					the_post();
					$post_id = get_the_ID();
					// kbuzzlab フィード由来の場合は organizer + 期間を取り出して
					// カード上にも軽くサマリ表示する。
					$organizer = get_post_meta( $post_id, 'popup_organizer', true );
					$start     = get_post_meta( $post_id, 'popup_period_start', true );
					$end       = get_post_meta( $post_id, 'popup_period_end', true );
					$area      = get_post_meta( $post_id, 'popup_area', true );
					// 開催状況バッジ + 期間短縮表示(個別と共有のヘルパー)
					$card_badge  = function_exists( 'kpop_popup_status_badge' ) ? kpop_popup_status_badge( $start, $end ) : null;
					$card_period = function_exists( 'kpop_popup_period_short' ) ? kpop_popup_period_short( $start, $end ) : '';
					// プレースホルダ用の頭文字(タイトル先頭1文字)。"POP UP" 表記は CSS 側。
					$card_initial = mb_substr( wp_strip_all_tags( get_the_title() ), 0, 1 );
					?>
					<li class="popup-card">
						<a class="popup-card-link" href="<?php the_permalink(); ?>">
							<span class="popup-card-thumb">
								<?php
								if ( has_post_thumbnail() ) {
									the_post_thumbnail( 'medium', array( 'alt' => '', 'loading' => 'lazy' ) );
								} else {
									?>
									<span class="popup-card-thumb--placeholder" aria-hidden="true">
										<span class="popup-card-ph-initial"><?php echo esc_html( $card_initial ); ?></span>
										<span class="popup-card-ph-label">POP UP</span>
									</span>
									<?php
								}
								if ( $card_badge ) {
									echo '<span class="popup-card-badge ' . esc_attr( $card_badge['class'] ) . '">' . esc_html( $card_badge['label'] ) . '</span>';
								}
								?>
							</span>
							<span class="popup-card-body">
								<span class="popup-card-label">POP-UP</span>
								<span class="popup-card-title"><?php the_title(); ?></span>
								<?php if ( $area || $card_period ) : ?>
									<span class="popup-card-meta">
										<?php if ( $card_period ) : ?>
											<span class="popup-card-date"><span class="popup-card-ic" aria-hidden="true">📅</span><?php echo esc_html( $card_period ); ?></span>
										<?php endif; ?>
										<?php if ( $area ) : ?>
											<span class="popup-card-area"><span class="popup-card-ic" aria-hidden="true">📍</span><?php echo esc_html( $area ); ?></span>
										<?php endif; ?>
									</span>
								<?php endif; ?>
							</span>
						</a>
					</li>
				<?php endwhile; ?>
			</ul>

			<?php
			$pagination = paginate_links( array(
				'type'      => 'array',
				'prev_text' => '&larr; 前へ',
				'next_text' => '次へ &rarr;',
				'mid_size'  => 2,
			) );
			if ( $pagination ) : ?>
				<nav class="kpop-pagination" aria-label="ページ送り">
					<ul>
						<?php foreach ( $pagination as $link ) : ?>
							<li><?php echo $link; // phpcs:ignore ?></li>
						<?php endforeach; ?>
					</ul>
				</nav>
			<?php endif; ?>
		<?php else : ?>
			<div class="popup-empty">
				<p class="kpop-empty-title">条件に合うポップアップがありません。</p>
				<p class="kpop-empty-sub">絞り込みを変更するか、「すべて」を選んでみてください。</p>
				<?php if ( $cur_area || $cur_status || $cur_genre ) : ?>
					<a class="kpop-more" href="<?php echo esc_url( get_category_link( get_queried_object_id() ) ); ?>">絞り込みを解除</a>
				<?php endif; ?>
			</div>
		<?php endif; ?>
	</section>

	<?php do_action( 'generate_after_main_content' ); ?>
</main>

<?php
do_action( 'generate_after_primary_content_area' );
get_footer();
