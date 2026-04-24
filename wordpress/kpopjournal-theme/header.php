<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
    <meta charset="<?php bloginfo('charset'); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#06060E">
    <?php wp_head(); ?>
</head>
<body <?php body_class('kpj-body'); ?>>
<?php wp_body_open(); ?>

<!-- ── Progress Bar (single posts only) ── -->
<?php if (is_single()): ?>
<div class="kpj-progress" id="kpj-progress">
    <div class="kpj-progress__bar" id="kpj-progress-bar"></div>
</div>
<?php endif; ?>

<!-- ── Header ── -->
<header class="kpj-header" id="kpj-header">
    <div class="kpj-header__inner">
        <!-- Logo -->
        <a href="<?php echo esc_url(home_url('/')); ?>" class="kpj-header__logo">
            <span class="kpj-logo-text">KPOP<span class="kpj-logo-accent">JOURNAL</span></span>
        </a>

        <!-- Navigation -->
        <nav class="kpj-header__nav" id="kpj-nav">
            <?php
            wp_nav_menu([
                'theme_location' => 'primary',
                'container'      => false,
                'menu_class'     => 'kpj-nav__list',
                'depth'          => 2,
                'fallback_cb'    => false,
            ]);
            ?>
        </nav>

        <!-- Right Actions -->
        <div class="kpj-header__actions">
            <!-- Search Toggle -->
            <button class="kpj-header__search-btn" id="kpj-search-toggle" aria-label="<?php esc_attr_e('Search', 'kpopjournal'); ?>">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
                </svg>
            </button>

            <!-- Premium CTA -->
            <a href="#premium" class="kpj-header__cta">PREMIUM</a>

            <!-- Mobile Menu Toggle -->
            <button class="kpj-header__burger" id="kpj-burger" aria-label="<?php esc_attr_e('Menu', 'kpopjournal'); ?>">
                <span></span><span></span><span></span>
            </button>
        </div>
    </div>

    <!-- Search Overlay -->
    <div class="kpj-search-overlay" id="kpj-search-overlay">
        <form role="search" method="get" action="<?php echo esc_url(home_url('/')); ?>" class="kpj-search-form">
            <input type="search" name="s" class="kpj-search-input" placeholder="<?php esc_attr_e('Search articles...', 'kpopjournal'); ?>" value="<?php echo get_search_query(); ?>" autofocus>
            <button type="submit" class="kpj-search-submit">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
            </button>
        </form>
    </div>
</header>

<!-- ── Breaking News Ticker ── -->
<?php
$breaking = kpj_get_breaking_news(8);
if ($breaking->have_posts()):
?>
<div class="kpj-ticker">
    <div class="kpj-ticker__label">BREAKING</div>
    <div class="kpj-ticker__track">
        <div class="kpj-ticker__items" id="kpj-ticker">
            <?php while ($breaking->have_posts()): $breaking->the_post(); ?>
                <a href="<?php the_permalink(); ?>" class="kpj-ticker__item">
                    <?php echo kpj_category_badge(); ?>
                    <span><?php the_title(); ?></span>
                </a>
            <?php endwhile; wp_reset_postdata(); ?>
        </div>
    </div>
</div>
<?php endif; ?>

<!-- ── Mobile Menu Panel ── -->
<div class="kpj-mobile-menu" id="kpj-mobile-menu">
    <div class="kpj-mobile-menu__inner">
        <?php
        wp_nav_menu([
            'theme_location' => 'mobile',
            'container'      => false,
            'menu_class'     => 'kpj-mobile-nav',
            'depth'          => 2,
            'fallback_cb'    => function() {
                wp_nav_menu([
                    'theme_location' => 'primary',
                    'container'      => false,
                    'menu_class'     => 'kpj-mobile-nav',
                    'depth'          => 2,
                    'fallback_cb'    => false,
                ]);
            },
        ]);
        ?>
    </div>
</div>

<main class="kpj-main">
