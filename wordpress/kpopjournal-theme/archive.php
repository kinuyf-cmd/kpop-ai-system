<?php get_header(); ?>

<div class="kpj-container kpj-layout">
    <div class="kpj-content">

        <header class="kpj-page-header">
            <?php
            the_archive_title('<h1 class="kpj-page-header__title">', '</h1>');
            the_archive_description('<p class="kpj-page-header__desc">', '</p>');
            ?>
            <div class="kpj-page-header__count">
                <?php
                global $wp_query;
                printf(esc_html__('%d articles', 'kpopjournal'), $wp_query->found_posts);
                ?>
            </div>
        </header>

        <?php if (have_posts()): ?>

            <!-- First post featured -->
            <?php the_post(); ?>
            <div class="kpj-featured-single">
                <?php kpj_post_card('kpj-hero', 'kpj-card--featured'); ?>
            </div>

            <!-- Grid -->
            <div class="kpj-grid kpj-grid--2col">
                <?php while (have_posts()): the_post(); ?>
                    <?php kpj_post_card('kpj-card'); ?>
                <?php endwhile; ?>
            </div>

            <nav class="kpj-pagination">
                <?php
                the_posts_pagination([
                    'mid_size'  => 2,
                    'prev_text' => '&larr;',
                    'next_text' => '&rarr;',
                ]);
                ?>
            </nav>

        <?php else: ?>
            <div class="kpj-no-results">
                <h2><?php esc_html_e('No articles found', 'kpopjournal'); ?></h2>
            </div>
        <?php endif; ?>

    </div>

    <?php get_sidebar(); ?>
</div>

<?php get_footer(); ?>
