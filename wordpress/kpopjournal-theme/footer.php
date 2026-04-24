</main><!-- /.kpj-main -->

<!-- ── Footer ── -->
<footer class="kpj-footer">
    <div class="kpj-footer__inner">
        <div class="kpj-footer__grid">
            <!-- Column 1: About -->
            <div class="kpj-footer__col">
                <a href="<?php echo esc_url(home_url('/')); ?>" class="kpj-footer__logo">
                    <span class="kpj-logo-text">KPOP<span class="kpj-logo-accent">JOURNAL</span></span>
                </a>
                <p class="kpj-footer__desc">
                    <?php echo esc_html(get_bloginfo('description')); ?>
                </p>
                <div class="kpj-footer__social">
                    <a href="#" class="kpj-footer__social-link" aria-label="X (Twitter)">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                    </a>
                    <a href="#" class="kpj-footer__social-link" aria-label="Instagram">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="20" height="20" x="2" y="2" rx="5"/><circle cx="12" cy="12" r="5"/><circle cx="17.5" cy="6.5" r="1.5" fill="currentColor" stroke="none"/></svg>
                    </a>
                    <a href="#" class="kpj-footer__social-link" aria-label="YouTube">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
                    </a>
                </div>
            </div>

            <!-- Column 2 -->
            <div class="kpj-footer__col">
                <?php if (is_active_sidebar('footer-2')): ?>
                    <?php dynamic_sidebar('footer-2'); ?>
                <?php else: ?>
                    <h3 class="kpj-footer__heading">Categories</h3>
                    <ul class="kpj-footer__links">
                        <?php wp_list_categories(['title_li' => '', 'number' => 8]); ?>
                    </ul>
                <?php endif; ?>
            </div>

            <!-- Column 3 -->
            <div class="kpj-footer__col">
                <?php if (is_active_sidebar('footer-3')): ?>
                    <?php dynamic_sidebar('footer-3'); ?>
                <?php else: ?>
                    <h3 class="kpj-footer__heading">Popular Tags</h3>
                    <div class="kpj-footer__tags">
                        <?php
                        $tags = get_tags(['number' => 12, 'orderby' => 'count', 'order' => 'DESC']);
                        foreach ($tags as $tag):
                        ?>
                            <a href="<?php echo get_tag_link($tag->term_id); ?>" class="kpj-footer__tag">#<?php echo esc_html($tag->name); ?></a>
                        <?php endforeach; ?>
                    </div>
                <?php endif; ?>
            </div>

            <!-- Column 4 -->
            <div class="kpj-footer__col">
                <?php if (is_active_sidebar('footer-4')): ?>
                    <?php dynamic_sidebar('footer-4'); ?>
                <?php else: ?>
                    <h3 class="kpj-footer__heading">Newsletter</h3>
                    <p class="kpj-footer__newsletter-desc">Get the latest K-POP news delivered to your inbox.</p>
                    <form class="kpj-footer__newsletter">
                        <input type="email" placeholder="your@email.com" class="kpj-footer__newsletter-input" required>
                        <button type="submit" class="kpj-footer__newsletter-btn">Subscribe</button>
                    </form>
                <?php endif; ?>
            </div>
        </div>

        <!-- Bottom Bar -->
        <div class="kpj-footer__bottom">
            <p>&copy; <?php echo date('Y'); ?> <?php bloginfo('name'); ?>. All rights reserved.</p>
            <?php
            wp_nav_menu([
                'theme_location' => 'footer',
                'container'      => false,
                'menu_class'     => 'kpj-footer__bottom-links',
                'depth'          => 1,
                'fallback_cb'    => false,
            ]);
            ?>
        </div>
    </div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
