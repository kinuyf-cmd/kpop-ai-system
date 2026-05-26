<?php
/**
 * content-single.php — KPOP JOURNAL 個別記事の本体テンプレート
 *
 * M1 段階5。GP の content-single.php を子テーマで上書き
 * (generate_do_template_part('single') が子テーマ版を優先採用)。
 *
 * 構造(元サイト reference/スクリーンショット 2026-05-07 0.53.39/0.53.48 準拠):
 *   パンくず → ヒーロー画像 → カテゴリバッジ + h1 + メタ →
 *   3行まとめボックス → 本文(the_content) → フッター(タグ/シェア/関連)
 *
 * @package generatepress-kpop
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
?>

<?php
/* ── 個別改修2: popup 記事のみ「左バー + 本文」の2カラムにする ────────────
   popup カテゴリの個別記事は右サイドバー撤去済(functions.php
   generate_show_right_sidebar フィルター)。代わりに左へカテゴリ/エリア/
   ジャンルのナビバーを常設する。article を .kpop-popup-single-layout でラップ。
   他カテゴリ記事には一切影響しないよう in_category('popup') でゲート。 */
$kpop_is_popup_single = is_singular( 'post' ) && in_category( 'popup' );
if ( $kpop_is_popup_single ) {
	echo '<div class="kpop-popup-single-layout">';
	echo '<aside class="kpop-popup-single-aside" aria-label="ポップアップナビ">';
	if ( function_exists( 'kpop_render_popup_side_nav' ) ) {
		kpop_render_popup_side_nav( get_the_ID() );
	}
	echo '</aside>';
	echo '<div class="kpop-popup-single-body">';
}
?>
<article id="post-<?php the_ID(); ?>" <?php post_class( 'kpop-single' ); ?> <?php generate_do_microdata( 'article' ); ?>>
	<div class="inside-article">

		<?php
		/* ── 段階5a: パンくず ────────────────────────────────────────────
		   GP 無印にパンくず機能はないため functions.php の
		   kpop_breadcrumb() で自前出力(ホーム > カテゴリ > 記事)。 */
		if ( function_exists( 'kpop_breadcrumb' ) ) {
			kpop_breadcrumb();
		}
		?>

		<?php
		/* ── M11 B-1: タイトル → サムネ の順に変更(旧: サムネ → タイトル)
		   カテゴリバッジ + h1 + メタ を header として先に出力し、その後に
		   ヒーロー画像、3行要約、本文 の順序にする。 */
		?>
		<header class="entry-header kpop-single-header">
			<?php
			/* ── 段階5b: カテゴリバッジ ─────────────────────────────── */
			$kpop_cats = get_the_category();
			if ( $kpop_cats ) :
				$kpop_cat = $kpop_cats[0];
				?>
				<a class="kpop-single-cat" href="<?php echo esc_url( get_category_link( $kpop_cat->term_id ) ); ?>">
					<?php echo esc_html( $kpop_cat->name ); ?>
				</a>
			<?php endif; ?>

			<?php // h1: 記事タイトル。 ?>
			<h1 class="entry-title" itemprop="headline"><?php the_title(); ?>
				<?php /* M11 B-4b: お気に入りハートアイコン(JS で切替) */ ?>
				<button class="kpop-fav-heart" data-post-id="<?php echo esc_attr( get_the_ID() ); ?>" aria-pressed="false" aria-label="お気に入りに追加">♡</button>
			</h1>

			<?php
			/* ── 段階5b: メタ情報(公開日 / 更新日 / 執筆者 / 読了時間) ── */
			$kpop_published = get_the_date( 'c' );
			$kpop_modified  = get_the_modified_date( 'c' );
			$kpop_show_mod  = get_the_modified_date( 'Ymd' ) !== get_the_date( 'Ymd' );
			?>
			<div class="kpop-single-meta">
				<time class="kpop-meta-item kpop-meta-date" datetime="<?php echo esc_attr( $kpop_published ); ?>" itemprop="datePublished">
					<span class="kpop-meta-label">公開</span><?php echo esc_html( get_the_date( 'Y.m.d' ) ); ?>
				</time>
				<?php if ( $kpop_show_mod ) : ?>
					<time class="kpop-meta-item kpop-meta-mod" datetime="<?php echo esc_attr( $kpop_modified ); ?>" itemprop="dateModified">
						<span class="kpop-meta-label">更新</span><?php echo esc_html( get_the_modified_date( 'Y.m.d' ) ); ?>
					</time>
				<?php endif; ?>
				<span class="kpop-meta-item kpop-meta-author" itemprop="author">
					<span class="kpop-meta-label">執筆</span><?php echo esc_html( get_the_author() ); ?>
				</span>
				<?php if ( function_exists( 'kpop_reading_time' ) ) : ?>
					<span class="kpop-meta-item kpop-meta-time">
						<span class="kpop-meta-label">読了</span><?php echo esc_html( kpop_reading_time() ); ?>分
					</span>
				<?php endif; ?>
			</div>
		</header>

		<?php
		/* ── 本文を先にバッファリングして 3行まとめ(.kpj-summary)を確定抽出する。
		   the_content filter(kpop_extract_summary, prio4)が本文から summary を
		   除去して $GLOBALS['kpop_extracted_summary'] に退避する。DB は非破壊。
		   こうすることで、まとめ→ヒーロー→本文 の順を表示時に組み立てられる。 */
		$kpop_held_cta = '';
		ob_start();
		the_content();
		$kpop_rendered = ob_get_clean();

		/* ── タイトル直後に 3行まとめ を配置(最優先の冒頭 TL;DR) ──
		   1) 本文埋め込みの kpj-summary を抽出できたらそれを冒頭に。
		   2) 無ければ従来の ACF 由来 summary box(kopp_summary)にフォールバック。 */
		if ( ! empty( $GLOBALS['kpop_extracted_summary'] ) ) {
			kpop_render_extracted_summary();
		} elseif ( function_exists( 'kpop_render_summary_box' ) ) {
			kpop_render_summary_box( get_the_ID() );
		}
		?>

		<?php
		/* ── ヒーロー画像 を 3行まとめの後、本文の前に配置 */
		if ( has_post_thumbnail() ) :
			?>
			<figure class="kpop-single-hero">
				<?php the_post_thumbnail( 'large', array( 'alt' => esc_attr( get_the_title() ) ) ); ?>
			</figure>
		<?php endif; ?>

		<div class="entry-content" itemprop="text">
			<?php
			/* ── popup 限定: CTA(citation-cta〜本文末)を本文から切り離し、
			   開催情報box・SNS・地図の後ろへ移動する。位置だけ移動し HTML は改変しない。
			   非popup・マーカー未検出は full content をそのまま出力(壊さない)。 */
			if ( $kpop_is_popup_single ) {
				$kpop_cta_pos = strpos( $kpop_rendered, '<p class="kpop-citation-cta"' );
				if ( false !== $kpop_cta_pos ) {
					echo substr( $kpop_rendered, 0, $kpop_cta_pos ); // 本文〜出典まで
					$kpop_held_cta = substr( $kpop_rendered, $kpop_cta_pos ); // CTA〜本文末を保持
				} else {
					echo $kpop_rendered; // マーカー未検出: 改変せず全出力
				}
			} else {
				echo $kpop_rendered; // バッファ済み本文(summary 抽出済み)を出力
			}
			wp_link_pages( array(
				'before' => '<div class="page-links">' . esc_html__( 'Pages:', 'generatepress' ),
				'after'  => '</div>',
			) );
			?>
		</div>

		<?php
		/* ── Popup 専用: 開催情報 詳細セクション + おすすめポップアップ ───────
		   popup カテゴリの記事のときだけ、本文(the_content)直後に ACF 12項目の
		   開催情報セクションを描画し、その後におすすめポップアップを並べる。
		   (旧実装は the_content filter 経由だったが、二重描画と順序の都合で
		    テンプレ直呼びに統一。functions.php の filter は撤去済み。) */
		if ( in_category( 'popup' ) ) {
			if ( function_exists( 'kpop_render_popup_details_box' ) ) {
				kpop_render_popup_details_box( get_the_ID() );
			}
			/* 個別改修3: 下部に「おすすめ」+「近日開催予定」の2セクション */
			if ( function_exists( 'kpop_render_popup_recommendations' ) ) {
				kpop_render_popup_recommendations( get_the_ID() );
			}
			if ( function_exists( 'kpop_render_popup_upcoming' ) ) {
				kpop_render_popup_upcoming( get_the_ID() );
			}
		}
		/* ── 保持していた CTA(出典〜a8 banner〜disclosure)を最後に出力。
		   HTML は本文から切り出したまま無改変。PR/sponsored/nofollow/disclosure 維持。 */
		if ( '' !== $kpop_held_cta ) {
			echo $kpop_held_cta;
		}
		?>

		<?php
		/* ── M11 B-4a: 関連記事 5枚カード強化 ───────────────────────────
		   タグ + カテゴリ + 直近性で重みづけして 5件選出。
		   サムネ + タイトル + 抜粋(2行)を grid で表示。 */
		$kpop_related_q = null;
		$kpop_related_tag_ids = array();
		$kpop_related_post_tags = get_the_tags( get_the_ID() );
		if ( $kpop_related_post_tags && ! is_wp_error( $kpop_related_post_tags ) ) {
			foreach ( $kpop_related_post_tags as $t ) { $kpop_related_tag_ids[] = $t->term_id; }
		}
		if ( ! empty( $kpop_related_tag_ids ) ) {
			$kpop_related_q = new WP_Query( array(
				'post_type'           => 'post',
				'post_status'         => 'publish',
				'tag__in'             => $kpop_related_tag_ids,
				'post__not_in'        => array( get_the_ID() ),
				'posts_per_page'      => 5,
				'orderby'             => 'date',
				'order'               => 'DESC',
				'ignore_sticky_posts' => true,
				'no_found_rows'       => true,
			) );
		}
		// タグマッチが少ない場合はカテゴリでフォールバック
		if ( ! $kpop_related_q || ! $kpop_related_q->have_posts() ) {
			$kpop_related_cats_fb = get_the_category( get_the_ID() );
			if ( $kpop_related_cats_fb ) {
				$kpop_related_q = new WP_Query( array(
					'post_type'           => 'post',
					'post_status'         => 'publish',
					'cat'                 => $kpop_related_cats_fb[0]->term_id,
					'post__not_in'        => array( get_the_ID() ),
					'posts_per_page'      => 5,
					'orderby'             => 'date',
					'order'               => 'DESC',
					'no_found_rows'       => true,
				) );
			}
		}
		if ( $kpop_related_q && $kpop_related_q->have_posts() ) :
			?>
			<section class="kpop-related-section" aria-label="関連記事">
				<h2 class="kpop-related-heading">関連記事</h2>
				<ul class="kpop-related-cards" aria-label="関連記事5件">
					<?php
					while ( $kpop_related_q->have_posts() ) :
						$kpop_related_q->the_post();
						$excerpt = get_the_excerpt();
						if ( mb_strlen( $excerpt ) > 60 ) { $excerpt = mb_substr( $excerpt, 0, 60 ) . '…'; }
						?>
						<li class="kpop-related-card">
							<a href="<?php echo esc_url( get_permalink() ); ?>">
								<?php if ( has_post_thumbnail() ) :
									the_post_thumbnail( 'thumbnail', array( 'alt' => '', 'loading' => 'lazy' ) );
								endif; ?>
								<span class="kpop-rc-title"><?php the_title(); ?></span>
								<span class="kpop-rc-excerpt"><?php echo esc_html( $excerpt ); ?></span>
							</a>
						</li>
						<?php
					endwhile;
					wp_reset_postdata();
					?>
				</ul>
			</section>
			<?php
		endif;
		?>

		<?php
		/* ── M6 段階6.10 — E-5 記事 → Idol Wiki 直接リンク ───────────────
		   記事に付いた post_tag と同 slug の idol_artist CPT が publish 状態で
		   存在すれば、本文末尾に「<アーティスト名> の詳細プロフィール」リンクを
		   表示する。これにより「個別記事 ⇔ Wiki 双方向リンク」を完成させる
		   (Wiki → 記事は single-idol_artist.php の関連記事リストで実装済み)。 */
		$kpop_post_tags = get_the_tags( get_the_ID() );
		if ( $kpop_post_tags && ! is_wp_error( $kpop_post_tags ) ) {
			$kpop_wiki_links = array();
			foreach ( $kpop_post_tags as $kpop_tag ) {
				$kpop_idol = get_page_by_path( $kpop_tag->slug, OBJECT, 'idol_artist' );
				if ( $kpop_idol && 'publish' === $kpop_idol->post_status ) {
					$kpop_wiki_links[] = array(
						'name' => get_the_title( $kpop_idol ),
						'url'  => get_permalink( $kpop_idol ),
					);
				}
			}
			if ( ! empty( $kpop_wiki_links ) ) :
			?>
			<aside class="kpop-idol-wiki-link" aria-label="アーティストの詳細プロフィール">
				<p class="kpop-idol-wiki-link-label">メンバー・所属事務所・公式SNS など詳しくは Idol Wiki へ</p>
				<ul class="kpop-idol-wiki-link-list">
					<?php foreach ( $kpop_wiki_links as $kpop_link ) : ?>
						<li>
							<a href="<?php echo esc_url( $kpop_link['url'] ); ?>" class="kpop-idol-wiki-link-anchor">
								<?php echo esc_html( $kpop_link['name'] ); ?> の詳細プロフィール
							</a>
						</li>
					<?php endforeach; ?>
				</ul>
			</aside>
			<?php
			endif;
		}

		/* ── 段階5e: 記事フッター(タグ / シェア / フィードバック / 関連) ──
		   functions.php の kpop_render_single_footer() で出力。 */
		if ( function_exists( 'kpop_render_single_footer' ) ) {
			kpop_render_single_footer( get_the_ID() );
		}
		?>
	</div>
</article>
<?php
/* 個別改修2: popup 記事の2カラムラッパを閉じる */
if ( $kpop_is_popup_single ) {
	echo '</div>'; // .kpop-popup-single-body
	echo '</div>'; // .kpop-popup-single-layout
}
?>
