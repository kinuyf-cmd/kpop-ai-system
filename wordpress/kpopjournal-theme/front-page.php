<?php get_header(); ?>

<?php
// Queries
$hero_query = new WP_Query(['posts_per_page' => 5, 'ignore_sticky_posts' => 0]);
$hero_posts = $hero_query->posts;
$main_post  = $hero_posts[0] ?? null;
$side_posts = array_slice($hero_posts, 1, 4);

$grid_query = new WP_Query([
    'posts_per_page' => 8,
    'offset'         => 5,
    'ignore_sticky_posts' => 1,
]);

$list_query = new WP_Query([
    'posts_per_page' => 6,
    'offset'         => 13,
    'ignore_sticky_posts' => 1,
]);
?>

<!-- ── Hero Section ── -->
<section class="kpj-hero">
    <div class="kpj-container">
        <div class="kpj-hero__grid">
            <!-- Main Feature -->
            <?php if ($main_post): setup_postdata($main_post); ?>
            <article class="kpj-hero__main">
                <a href="<?php echo get_permalink($main_post); ?>" class="kpj-hero__main-link">
                    <?php if (has_post_thumbnail($main_post)): ?>
                        <div class="kpj-hero__main-thumb">
                            <?php echo get_the_post_thumbnail($main_post, 'kpj-hero', ['class' => 'kpj-hero__main-img']); ?>
                            <div class="kpj-hero__main-overlay"></div>
                        </div>
                    <?php endif; ?>
                    <div class="kpj-hero__main-content">
                        <?php
                        $cats = get_the_category($main_post->ID);
                        if (!empty($cats)):
                        ?>
                            <span class="kpj-badge"><?php echo esc_html($cats[0]->name); ?></span>
                        <?php endif; ?>
                        <h2 class="kpj-hero__main-title"><?php echo get_the_title($main_post); ?></h2>
                        <p class="kpj-hero__main-excerpt"><?php echo wp_trim_words(get_the_excerpt($main_post), 30); ?></p>
                        <div class="kpj-hero__main-meta">
                            <time datetime="<?php echo get_the_date('c', $main_post); ?>"><?php echo get_the_date('Y.m.d', $main_post); ?></time>
                            <span><?php echo kpj_reading_time($main_post->ID); ?> min</span>
                        </div>
                    </div>
                </a>
            </article>
            <?php wp_reset_postdata(); endif; ?>

            <!-- Side Stack -->
            <div class="kpj-hero__side">
                <?php foreach ($side_posts as $sp): setup_postdata($sp); ?>
                <article class="kpj-hero__side-item">
                    <a href="<?php echo get_permalink($sp); ?>" class="kpj-hero__side-link">
                        <?php if (has_post_thumbnail($sp)): ?>
                            <div class="kpj-hero__side-thumb">
                                <?php echo get_the_post_thumbnail($sp, 'kpj-list', ['class' => 'kpj-hero__side-img', 'loading' => 'lazy']); ?>
                            </div>
                        <?php endif; ?>
                        <div class="kpj-hero__side-body">
                            <?php
                            $cats = get_the_category($sp->ID);
                            if (!empty($cats)):
                            ?>
                                <span class="kpj-badge kpj-badge--sm"><?php echo esc_html($cats[0]->name); ?></span>
                            <?php endif; ?>
                            <h3 class="kpj-hero__side-title"><?php echo get_the_title($sp); ?></h3>
                            <time class="kpj-hero__side-date" datetime="<?php echo get_the_date('c', $sp); ?>"><?php echo get_the_date('m.d', $sp); ?></time>
                        </div>
                    </a>
                </article>
                <?php endforeach; wp_reset_postdata(); ?>
            </div>
        </div>
    </div>
</section>

<!-- ── Article Grid ── -->
<section class="kpj-section">
    <div class="kpj-container kpj-layout">
        <div class="kpj-content">
            <h2 class="kpj-section__title">Latest Articles</h2>
            <?php if ($grid_query->have_posts()): ?>
            <div class="kpj-grid kpj-grid--2col">
                <?php while ($grid_query->have_posts()): $grid_query->the_post(); ?>
                    <?php kpj_post_card('kpj-card'); ?>
                <?php endwhile; wp_reset_postdata(); ?>
            </div>
            <?php endif; ?>

            <!-- List Format Section -->
            <?php if ($list_query->have_posts()): ?>
            <h2 class="kpj-section__title kpj-section__title--mt">More Stories</h2>
            <div class="kpj-list">
                <?php while ($list_query->have_posts()): $list_query->the_post(); ?>
                    <?php kpj_post_list_item(); ?>
                <?php endwhile; wp_reset_postdata(); ?>
            </div>
            <?php endif; ?>

            <!-- Load More -->
            <div class="kpj-load-more">
                <a href="<?php echo get_permalink(get_option('page_for_posts')); ?>" class="kpj-load-more__btn">View All Articles</a>
            </div>
        </div>

        <?php get_sidebar(); ?>
    </div>
</section>

<!-- ── Artist Quick Nav ── -->
<section class="kpj-section kpj-section--artists">
    <div class="kpj-container">
        <h2 class="kpj-section__title">Browse by Artist</h2>
        <div class="kpj-artist-nav">
            <?php
            $cats = get_categories([
                'orderby' => 'count',
                'order'   => 'DESC',
                'number'  => 20,
                'exclude' => [1],
            ]);
            foreach ($cats as $cat):
            ?>
                <a href="<?php echo get_category_link($cat->term_id); ?>" class="kpj-artist-nav__item">
                    <span class="kpj-artist-nav__name"><?php echo esc_html($cat->name); ?></span>
                    <span class="kpj-artist-nav__count"><?php echo $cat->count; ?> articles</span>
                </a>
            <?php endforeach; ?>
        </div>
    </div>
</section>

<?php get_footer(); ?>
