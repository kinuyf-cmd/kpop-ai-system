<aside class="kpj-sidebar">

    <!-- Trending Now -->
    <div class="kpj-widget kpj-widget--trending">
        <h3 class="kpj-widget__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FF1B6B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            今日読まれている記事
        </h3>
        <div class="kpj-trending-list">
            <?php
            /* 2026-05-12: 旧実装は orderby=comment_count で「過去2日の新着順と区別つかない」
               虚偽表示状態だった。kpj_api_trending() (GA4 metrics_yesterday.json ベース) を
               使用して実 pageviews 順で表示する。GA4 不在時は endpoint 内部で
               comment_count fallback。 */
            $trending_posts = [];
            if (function_exists('kpj_api_trending')) {
                $resp = kpj_api_trending(new WP_REST_Request('GET', '/kpopjournal/v1/trending'));
                $trending_posts = $resp->get_data()['posts'] ?? [];
            }
            if (empty($trending_posts)) {
                $q = new WP_Query([
                    'posts_per_page' => 5, 'post_status' => 'publish',
                    'orderby' => 'comment_count', 'order' => 'DESC',
                    'date_query' => [['after' => '30 days ago']],
                ]);
                foreach ($q->posts as $p) {
                    $trending_posts[] = [
                        'link'  => get_permalink($p->ID),
                        'title' => get_the_title($p->ID),
                        'date'  => get_the_date('c', $p->ID),
                    ];
                }
                wp_reset_postdata();
            }
            $rank = 1;
            foreach (array_slice($trending_posts, 0, 5) as $item):
                $link  = $item['link']  ?? '#';
                $title = $item['title'] ?? '';
                $date  = !empty($item['date']) ? mysql2date('m.d', $item['date']) : '';
            ?>
                <a href="<?php echo esc_url($link); ?>" class="kpj-trending-item">
                    <span class="kpj-trending-item__rank"><?php echo str_pad($rank++, 2, '0', STR_PAD_LEFT); ?></span>
                    <div class="kpj-trending-item__body">
                        <h4 class="kpj-trending-item__title"><?php echo esc_html($title); ?></h4>
                        <span class="kpj-trending-item__meta"><?php echo esc_html($date); ?></span>
                    </div>
                </a>
            <?php endforeach; ?>
        </div>
    </div>

    <!-- Chart Widget -->
    <div class="kpj-widget kpj-widget--chart">
        <h3 class="kpj-widget__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7B2FFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>
            Chart Picks
        </h3>
        <div class="kpj-chart-list">
            <?php
            $chart_cat = get_category_by_slug('chart');
            if ($chart_cat) {
                $chart_posts = new WP_Query([
                    'posts_per_page' => 5,
                    'cat'            => $chart_cat->term_id,
                ]);
                while ($chart_posts->have_posts()): $chart_posts->the_post();
                ?>
                    <a href="<?php the_permalink(); ?>" class="kpj-chart-item">
                        <?php if (has_post_thumbnail()): ?>
                            <div class="kpj-chart-item__thumb">
                                <?php the_post_thumbnail('thumbnail', ['loading' => 'lazy']); ?>
                            </div>
                        <?php endif; ?>
                        <div class="kpj-chart-item__body">
                            <h4 class="kpj-chart-item__title"><?php the_title(); ?></h4>
                            <span class="kpj-chart-item__meta"><?php echo get_the_date('m.d'); ?></span>
                        </div>
                    </a>
                <?php
                endwhile;
                wp_reset_postdata();
            }
            ?>
        </div>
    </div>

    <!-- Artist Quick Nav -->
    <div class="kpj-widget kpj-widget--artists">
        <h3 class="kpj-widget__title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FF1B6B" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
            Artists
        </h3>
        <div class="kpj-artist-tags">
            <?php
            $cats = get_categories([
                'orderby' => 'count',
                'order'   => 'DESC',
                'number'  => 15,
                'exclude' => [1], // exclude uncategorized
            ]);
            foreach ($cats as $cat):
            ?>
                <a href="<?php echo get_category_link($cat->term_id); ?>" class="kpj-artist-tag">
                    <?php echo esc_html($cat->name); ?>
                    <span class="kpj-artist-tag__count"><?php echo $cat->count; ?></span>
                </a>
            <?php endforeach; ?>
        </div>
    </div>

    <?php if (is_active_sidebar('sidebar-main')): ?>
        <?php dynamic_sidebar('sidebar-main'); ?>
    <?php endif; ?>

</aside>
