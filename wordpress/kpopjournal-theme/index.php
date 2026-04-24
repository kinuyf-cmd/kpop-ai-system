<?php get_header(); ?>

<div class="kpj-container kpj-layout">
    <div class="kpj-content">
        <?php if (have_posts()): ?>

            <?php if (is_search()): ?>
                <header class="kpj-page-header">
                    <h1 class="kpj-page-header__title">
                        <?php printf(esc_html__('Search: "%s"', 'kpopjournal'), get_search_query()); ?>
                    </h1>
                </header>
            <?php endif; ?>

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
                <p><?php esc_html_e('Try a different search term.', 'kpopjournal'); ?></p>
            </div>
        <?php endif; ?>
    </div>

    <?php get_sidebar(); ?>
</div>

<?php get_footer(); ?>
