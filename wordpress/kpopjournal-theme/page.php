<?php get_header(); ?>

<div class="kpj-container">
    <article class="kpj-page">
        <header class="kpj-page__header">
            <h1 class="kpj-page__title"><?php the_title(); ?></h1>
        </header>
        <div class="kpj-page__content kpj-single__body">
            <?php
            while (have_posts()): the_post();
                the_content();
            endwhile;
            ?>
        </div>
    </article>
</div>

<?php get_footer(); ?>
