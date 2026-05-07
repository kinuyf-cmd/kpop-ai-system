<?php get_header(); ?>

<style>
/* TOC removed — reclaim its space for article body */
.kpj-single__content .kpj-toc { display: none; }
.kpj-single .kpj-single__content {
    max-width: 100%;
    width: 100%;
    flex: 1 1 0%;
}
.kpj-single .kpj-single__body {
    max-width: 100%;
}
</style>

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

    <!-- Breadcrumb -->
    <nav class="kpj-breadcrumb" aria-label="パンくずリスト">
        <div class="kpj-container">
            <ol class="kpj-breadcrumb__list" itemscope itemtype="https://schema.org/BreadcrumbList">
                <li class="kpj-breadcrumb__item" itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
                    <a href="<?php echo home_url('/'); ?>" itemprop="item"><span itemprop="name">ホーム</span></a>
                    <meta itemprop="position" content="1" />
                </li>
                <?php
                $cats = get_the_category();
                if ($cats):
                    $cat = $cats[0];
                ?>
                <li class="kpj-breadcrumb__item" itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
                    <a href="<?php echo get_category_link($cat->term_id); ?>" itemprop="item"><span itemprop="name"><?php echo esc_html($cat->name); ?></span></a>
                    <meta itemprop="position" content="2" />
                </li>
                <?php endif; ?>
                <li class="kpj-breadcrumb__item kpj-breadcrumb__item--current" itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
                    <span itemprop="name"><?php the_title(); ?></span>
                    <meta itemprop="position" content="3" />
                </li>
            </ol>
        </div>
    </nav>

    <!-- Content Area -->
    <div class="kpj-container kpj-layout">
        <div class="kpj-content kpj-single__content">
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

            <!-- Related Posts (multi-factor scoring) -->
            <?php
            $related_data = kpj_api_related(new WP_REST_Request('GET', '/kpopjournal/v1/posts/' . get_the_ID() . '/related'));
            $related_posts = $related_data->get_data()['related'] ?? [];
            if (!empty($related_posts)):
            ?>
            <section class="kpj-related">
                <h2 class="kpj-related__title">関連記事</h2>
                <div class="kpj-grid kpj-grid--2col">
                    <?php foreach ($related_posts as $rp):
                        $rpost = get_post($rp['id']);
                        if ($rpost): setup_postdata($rpost);
                            kpj_post_card('kpj-card', 'kpj-card--related');
                        endif;
                    endforeach; wp_reset_postdata(); ?>
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
