<?php get_header(); ?>

<article class="kpj-single" id="kpj-article">

    <!-- Hero -->
    <?php if (has_post_thumbnail()): ?>
    <div class="kpj-single__hero">
        <?php the_post_thumbnail('kpj-hero', ['class' => 'kpj-single__hero-img']); ?>
        <div class="kpj-single__hero-overlay"></div>
        <div class="kpj-single__hero-content">
            <div class="kpj-container">
                <?php echo kpj_category_badge(); ?>
                <h1 class="kpj-single__title"><?php the_title(); ?></h1>
                <div class="kpj-single__meta">
                    <time datetime="<?php echo get_the_date('c'); ?>"><?php echo get_the_date('Y.m.d'); ?></time>
                    <span class="kpj-single__reading"><?php echo kpj_reading_time(); ?> min read</span>
                    <?php if (get_the_modified_date() !== get_the_date()): ?>
                        <span class="kpj-single__updated">Updated <?php echo get_the_modified_date('Y.m.d'); ?></span>
                    <?php endif; ?>
                </div>
            </div>
        </div>
    </div>
    <?php else: ?>
    <div class="kpj-container">
        <header class="kpj-single__header-noimg">
            <?php echo kpj_category_badge(); ?>
            <h1 class="kpj-single__title"><?php the_title(); ?></h1>
            <div class="kpj-single__meta">
                <time datetime="<?php echo get_the_date('c'); ?>"><?php echo get_the_date('Y.m.d'); ?></time>
                <span class="kpj-single__reading"><?php echo kpj_reading_time(); ?> min read</span>
            </div>
        </header>
    </div>
    <?php endif; ?>

    <!-- Content Area -->
    <div class="kpj-container kpj-layout">
        <div class="kpj-content kpj-single__content">

            <!-- Table of Contents -->
            <nav class="kpj-toc" id="kpj-toc">
                <button class="kpj-toc__toggle" id="kpj-toc-toggle">
                    <span>Table of Contents</span>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                </button>
                <ol class="kpj-toc__list" id="kpj-toc-list"></ol>
            </nav>

            <!-- Article Body -->
            <div class="kpj-single__body" id="kpj-article-body">
                <?php the_content(); ?>
            </div>

            <!-- Tags -->
            <?php
            $tags = get_the_tags();
            if ($tags):
            ?>
            <div class="kpj-single__tags">
                <?php foreach ($tags as $tag): ?>
                    <a href="<?php echo get_tag_link($tag->term_id); ?>" class="kpj-single__tag">#<?php echo esc_html($tag->name); ?></a>
                <?php endforeach; ?>
            </div>
            <?php endif; ?>

            <!-- Share -->
            <div class="kpj-single__share">
                <span class="kpj-single__share-label">Share</span>
                <a href="https://twitter.com/intent/tweet?url=<?php echo urlencode(get_permalink()); ?>&text=<?php echo urlencode(get_the_title()); ?>" target="_blank" rel="noopener" class="kpj-single__share-btn kpj-single__share-btn--x">X</a>
                <button class="kpj-single__share-btn kpj-single__share-btn--copy" data-url="<?php the_permalink(); ?>">Copy Link</button>
            </div>

            <!-- Author -->
            <div class="kpj-single__author">
                <?php echo get_avatar(get_the_author_meta('ID'), 48, '', '', ['class' => 'kpj-single__author-avatar']); ?>
                <div>
                    <strong class="kpj-single__author-name"><?php the_author(); ?></strong>
                    <p class="kpj-single__author-bio"><?php echo get_the_author_meta('description'); ?></p>
                </div>
            </div>

            <!-- Related Posts -->
            <?php
            $cats = wp_get_post_categories(get_the_ID());
            $related = new WP_Query([
                'category__in'        => $cats,
                'post__not_in'        => [get_the_ID()],
                'posts_per_page'      => 4,
                'ignore_sticky_posts' => 1,
            ]);
            if ($related->have_posts()):
            ?>
            <section class="kpj-related">
                <h2 class="kpj-related__title">Related Articles</h2>
                <div class="kpj-grid kpj-grid--2col">
                    <?php while ($related->have_posts()): $related->the_post(); ?>
                        <?php kpj_post_card('kpj-card', 'kpj-card--related'); ?>
                    <?php endwhile; wp_reset_postdata(); ?>
                </div>
            </section>
            <?php endif; ?>

            <!-- Comments -->
            <?php if (comments_open() || get_comments_number()): ?>
                <div class="kpj-comments">
                    <?php comments_template(); ?>
                </div>
            <?php endif; ?>

        </div>

        <?php get_sidebar(); ?>
    </div>

</article>

<?php get_footer(); ?>
