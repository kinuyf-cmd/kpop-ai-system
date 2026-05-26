<?php
/**
 * ライター紹介ページ(writer CPT・JSON 連動型)
 * ============================================================
 * X 架空ライター陣(config/x_writer_personas.json)の紹介ページを /writers/ に出す。
 * 設計はバイブル: .claude/plans/x-writer-personas-bible.md
 *
 * 方針(JSON 連動・ACF 不使用):
 *  - プロフィールの「真実のソース」は config/x_writer_personas.json(X 投稿生成と共有)。
 *  - writer CPT 投稿は slug=ライターキー(yui 等)の「器」。本文描画は JSON から動的生成。
 *  - ACF UI 設定も stg 手作業テンプレも不要 → コード反映だけで本番に出る。
 *  - 器投稿は kpop_seed_writer_posts() が冪等に自動生成(init 時、未作成分のみ)。
 *
 * URL: /writers/(一覧) /writers/{key}/(個別、key=yui/mina/...)
 * ============================================================
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * ライター JSON のパスを解決する。
 * stg/本番ではテーマが /var/www/.../wp-content/themes/ に配置されリポジトリ config/ は
 * 隣に無いため、まず**テーマ同梱コピー**(data/x_writer_personas.json)を読む。
 * これは scripts/sync_writer_personas.sh が config/ から同期する(デプロイ単位で同行)。
 * 開発環境(リポジトリ直下)向けに ../../config/ もフォールバックで探す。
 */
function kpop_writers_json_path() {
	$candidates = array(
		get_stylesheet_directory() . '/data/x_writer_personas.json',          // テーマ同梱(本番)
		dirname( get_stylesheet_directory(), 2 ) . '/config/x_writer_personas.json', // リポジトリ(開発)
	);
	foreach ( $candidates as $p ) {
		if ( is_readable( $p ) ) {
			return $p;
		}
	}
	return $candidates[0];
}

/** ライター定義を読み込む(失敗時は空配列)。1リクエスト内はキャッシュ。 */
function kpop_get_writers() {
	static $cache = null;
	if ( $cache !== null ) {
		return $cache;
	}
	$path = kpop_writers_json_path();
	$cache = array();
	if ( is_readable( $path ) ) {
		$data = json_decode( (string) file_get_contents( $path ), true );
		if ( is_array( $data ) && isset( $data['writers'] ) && is_array( $data['writers'] ) ) {
			$cache = $data['writers'];
		}
	}
	return $cache;
}

/* ── CPT 登録 ───────────────────────────────────────────────────────────── */
function kpop_register_writer_cpt() {
	$labels = array(
		'name'               => 'ライター',
		'singular_name'      => 'ライター',
		'menu_name'          => 'ライター',
		'add_new_item'       => 'ライターを追加',
		'edit_item'          => 'ライターを編集',
		'view_item'          => 'ライターを表示',
		'all_items'          => 'すべてのライター',
		'search_items'       => 'ライターを検索',
		'not_found'          => 'ライターが見つかりません',
		'featured_image'     => 'プロフィール画像',
		'set_featured_image' => 'プロフィール画像を設定',
	);
	$args = array(
		'labels'             => $labels,
		'public'             => true,
		'publicly_queryable' => true,
		'show_ui'            => true,
		'show_in_menu'       => true,
		'show_in_rest'       => true,
		'rest_base'          => 'writers',
		'menu_icon'          => 'dashicons-edit',
		'menu_position'      => 21,
		'query_var'          => true,
		'rewrite'            => array(
			'slug'       => 'writers',
			'with_front' => false,
		),
		'capability_type'    => 'post',
		'has_archive'        => true, /* /writers/ 一覧 */
		'hierarchical'       => false,
		'supports'           => array( 'title', 'thumbnail' ),
	);
	register_post_type( 'writer', $args );
}
add_action( 'init', 'kpop_register_writer_cpt' );

/* ── 器投稿の冪等シード(未作成のライターのみ作成) ──────────────────────── */
function kpop_seed_writer_posts() {
	// 1日1回程度で十分。毎リクエスト走らせない。
	if ( get_transient( 'kpop_writer_seed_done' ) ) {
		return;
	}
	$writers = kpop_get_writers();
	if ( empty( $writers ) ) {
		return;
	}
	foreach ( $writers as $key => $w ) {
		$existing = get_page_by_path( $key, OBJECT, 'writer' );
		if ( $existing ) {
			continue;
		}
		wp_insert_post( array(
			'post_type'    => 'writer',
			'post_name'    => sanitize_title( $key ),
			'post_title'   => isset( $w['name'] ) ? $w['name'] : $key,
			'post_status'  => 'publish',
			'post_content' => '', // 本文は JSON から動的描画
		) );
	}
	set_transient( 'kpop_writer_seed_done', '1', DAY_IN_SECONDS );
}
add_action( 'init', 'kpop_seed_writer_posts', 20 );

/** CPT rewrite を一度だけ flush(404 防止)。 */
function kpop_flush_writer_rewrite() {
	if ( get_option( 'kpop_writer_cpt_rewrite_flushed' ) !== '1' ) {
		kpop_register_writer_cpt();
		flush_rewrite_rules( false );
		update_option( 'kpop_writer_cpt_rewrite_flushed', '1' );
	}
}
add_action( 'init', 'kpop_flush_writer_rewrite', 99 );

/* ── サイドバー無し全幅(Idol Wiki と同方針) ──────────────────────────── */
add_filter( 'generate_show_right_sidebar', function ( $show ) {
	if ( is_singular( 'writer' ) || is_post_type_archive( 'writer' ) ) {
		return false;
	}
	return $show;
} );

/* ── 記事 → 担当ライターの解決(署名リンク用) ─────────────────────────
 * lib/x_persona_voice.select_writer と同じ思想を PHP で再現。
 * 記事のタグ(=アーティスト名)優先 → カテゴリ(=ジャンル)→ fallback。
 * DB 変更なし・既存記事に遡及適用・同記事は常に同じライター(安定割当)。
 */
function kpop_genre_aliases() {
	$path = kpop_writers_json_path();
	if ( is_readable( $path ) ) {
		$data = json_decode( (string) file_get_contents( $path ), true );
		if ( isset( $data['genre_aliases'] ) ) {
			return $data['genre_aliases'];
		}
	}
	return array();
}

/** カテゴリ名/slug から大まかなジャンルキーを推定(日本語カテゴリ対応)。 */
function kpop_guess_genre_from_terms( $post_id ) {
	$cats = get_the_category( $post_id );
	$names = array();
	foreach ( (array) $cats as $c ) {
		$names[] = $c->slug;
		$names[] = $c->name;
	}
	$blob = mb_strtolower( implode( ' ', $names ) );
	$map = array(
		'breaking' => array( 'breaking', '速報', 'news', 'ニュース' ),
		'comeback' => array( 'comeback', 'カムバック', '新曲' ),
		'chart'    => array( 'chart', 'チャート', 'ランキング', 'billboard' ),
		'fashion'  => array( 'fashion', 'ファッション', 'beauty', '美容', 'コスメ' ),
		'travel'   => array( 'travel', '旅行', 'グルメ', 'gourmet', 'ドラマ', 'cafe', 'カフェ' ),
		'scandal'  => array( '熱愛', '炎上', 'scandal', '話題' ),
		'analysis' => array( 'analysis', '考察', '解説' ),
	);
	foreach ( $map as $genre => $needles ) {
		foreach ( $needles as $n ) {
			if ( $n && mb_strpos( $blob, mb_strtolower( $n ) ) !== false ) {
				return $genre;
			}
		}
	}
	return '';
}

/** 記事 ID → 担当ライターキー(無ければ fallback / 'editorial')。 */
function kpop_resolve_post_writer( $post_id ) {
	$writers = kpop_get_writers();
	if ( empty( $writers ) ) {
		return '';
	}
	// 1) タグ(アーティスト名)で最長一致
	$tags = get_the_tags( $post_id );
	$tagblob = '';
	foreach ( (array) $tags as $t ) {
		$tagblob .= ' ' . mb_strtolower( $t->name );
	}
	$best_key = '';
	$best_len = 0;
	if ( trim( $tagblob ) !== '' ) {
		foreach ( $writers as $key => $w ) {
			foreach ( (array) ( isset( $w['oshi'] ) ? $w['oshi'] : array() ) as $o ) {
				$ol = mb_strtolower( $o );
				if ( $ol !== '' && mb_strpos( $tagblob, $ol ) !== false && mb_strlen( $ol ) > $best_len ) {
					$best_key = $key;
					$best_len = mb_strlen( $ol );
				}
			}
		}
	}
	if ( $best_key ) {
		return $best_key;
	}
	// 2) カテゴリ→ジャンル一致
	$genre = kpop_guess_genre_from_terms( $post_id );
	$aliases = kpop_genre_aliases();
	if ( isset( $aliases[ $genre ] ) ) {
		$genre = $aliases[ $genre ];
	}
	if ( $genre ) {
		foreach ( $writers as $key => $w ) {
			if ( in_array( $genre, (array) ( isset( $w['genres'] ) ? $w['genres'] : array() ), true ) ) {
				return $key;
			}
		}
	}
	// 3) fallback
	$path = kpop_writers_json_path();
	$fb = '';
	if ( is_readable( $path ) ) {
		$data = json_decode( (string) file_get_contents( $path ), true );
		$fb = isset( $data['fallback_writer'] ) ? $data['fallback_writer'] : '';
	}
	return isset( $writers[ $fb ] ) ? $fb : 'editorial';
}

/**
 * 記事の執筆者バイライン(リンク付き)を返す。
 * content-single.php から呼ぶ。担当ライターが解決できれば名前を /writers/{key}/ へリンク。
 * 解決不能なら従来の get_the_author() 名(リンクなし)を返す。
 */
function kpop_writer_byline( $post_id = 0 ) {
	if ( ! $post_id ) {
		$post_id = get_the_ID();
	}
	$writers = kpop_get_writers();
	$key = kpop_resolve_post_writer( $post_id );
	if ( $key && isset( $writers[ $key ] ) ) {
		$name = isset( $writers[ $key ]['name'] ) ? $writers[ $key ]['name'] : $key;
		$post = get_page_by_path( $key, OBJECT, 'writer' );
		$url  = $post ? get_permalink( $post ) : home_url( '/writers/' . $key . '/' );
		return '<a class="kpop-byline-link" href="' . esc_url( $url ) . '" rel="author">' . esc_html( $name ) . '</a>';
	}
	return esc_html( get_the_author() );
}

/* ── 個別ページ本文を JSON から描画 ───────────────────────────────────── */
function kpop_render_writer_profile( $key, $w ) {
	$name      = isset( $w['name'] ) ? $w['name'] : $key;
	$age       = isset( $w['age'] ) && $w['age'] ? intval( $w['age'] ) : 0;
	$stance    = isset( $w['stance'] ) ? $w['stance'] : '';
	$bio       = isset( $w['bio'] ) ? $w['bio'] : '';
	$signature = isset( $w['signature'] ) ? $w['signature'] : '';
	$oshi      = isset( $w['oshi'] ) && is_array( $w['oshi'] ) ? $w['oshi'] : array();
	$topics    = isset( $w['topics'] ) && is_array( $w['topics'] ) ? $w['topics'] : array();

	// 担当ジャンル(英語キー)を日本語ラベルに
	$genre_labels = array(
		'legacy' => 'レジェンド', 'generation' => '世代論', 'anniversary' => '周年',
		'retrospective' => '振り返り', 'analysis' => '考察', 'bts' => 'BTS',
		'solo_bts' => 'メンバーソロ', 'enlistment' => '入隊・除隊', 'gen4' => '第4世代',
		'rookie' => '新人', 'comeback' => 'カムバック', 'mv' => 'MV', 'festival' => 'フェス',
		'bigbang' => 'BIGBANG', 'solo_general' => 'ソロ活動', 'goods' => 'グッズ', 'tour' => 'ツアー',
		'travel' => '韓国旅行', 'gourmet' => 'グルメ', 'drama' => '韓国ドラマ', 'ost' => 'OST',
		'cafe' => 'カフェ', 'fashion' => 'ファッション', 'beauty' => '美容', 'airport' => '空港ファッション',
		'brand' => 'ブランド', 'gravure' => '画報', 'chart' => 'チャート', 'record' => '記録',
		'award' => '受賞', 'streaming' => 'ストリーミング', 'boxoffice' => '動員', 'breaking' => '速報',
		'scandal' => '熱愛・話題', 'dating' => '熱愛', 'collab' => 'コラボ', 'general' => '総合',
	);
	$genres = array();
	if ( isset( $w['genres'] ) && is_array( $w['genres'] ) ) {
		foreach ( $w['genres'] as $g ) {
			$genres[] = isset( $genre_labels[ $g ] ) ? $genre_labels[ $g ] : $g;
		}
	}

	// アバター: featured 画像があれば使用、無ければイニシャル+カラーのプレースホルダ。
	$colors = array( '#ec4899', '#8b5cf6', '#06b6d4', '#f59e0b', '#10b981', '#ef4444', '#3b82f6', '#6366f1' );
	$cidx   = abs( crc32( $key ) ) % count( $colors );
	$color  = $colors[ $cidx ];
	$initial = function_exists( 'mb_substr' ) ? mb_substr( $name, 0, 1 ) : substr( $name, 0, 1 );

	ob_start();
	?>
	<div class="kpop-writer-profile">
		<div class="kpop-writer-hero">
			<?php if ( has_post_thumbnail() ) : ?>
				<div class="kpop-writer-avatar"><?php the_post_thumbnail( 'medium' ); ?></div>
			<?php else : ?>
				<div class="kpop-writer-avatar kpop-writer-avatar--ph" style="background:<?php echo esc_attr( $color ); ?>;">
					<span><?php echo esc_html( $initial ); ?></span>
				</div>
			<?php endif; ?>
			<div class="kpop-writer-headline">
				<h1 class="kpop-writer-name"><?php echo esc_html( $name ); ?></h1>
				<p class="kpop-writer-stance">
					<?php echo $age ? esc_html( $age . '歳・' ) : ''; ?><?php echo esc_html( $stance ); ?>
				</p>
			</div>
		</div>

		<?php if ( $bio ) : ?>
			<p class="kpop-writer-bio"><?php echo esc_html( $bio ); ?></p>
		<?php endif; ?>

		<div class="kpop-writer-meta">
			<?php if ( $oshi ) : ?>
				<div class="kpop-writer-metarow">
					<span class="kpop-writer-metalabel">推し</span>
					<span class="kpop-writer-metaval"><?php echo esc_html( implode( '、', array_slice( $oshi, 0, 6 ) ) ); ?></span>
				</div>
			<?php endif; ?>
			<?php if ( $genres ) : ?>
				<div class="kpop-writer-metarow">
					<span class="kpop-writer-metalabel">担当</span>
					<span class="kpop-writer-metaval">
						<?php foreach ( $genres as $g ) : ?>
							<span class="kpop-writer-tag"><?php echo esc_html( $g ); ?></span>
						<?php endforeach; ?>
					</span>
				</div>
			<?php endif; ?>
			<?php if ( $topics ) : ?>
				<div class="kpop-writer-metarow">
					<span class="kpop-writer-metalabel">よく話すこと</span>
					<span class="kpop-writer-metaval"><?php echo esc_html( implode( '、', array_slice( $topics, 0, 6 ) ) ); ?></span>
				</div>
			<?php endif; ?>
		</div>

		<?php if ( $signature ) : ?>
			<p class="kpop-writer-sign">記事末尾の署名: <strong><?php echo esc_html( $signature ); ?></strong></p>
		<?php endif; ?>
	</div>
	<?php
	return ob_get_clean();
}

/**
 * writer 個別ページの本文を JSON プロフィールに差し替える。
 * (器投稿の本文は空なので、the_content フィルタで動的描画)
 */
add_filter( 'the_content', function ( $content ) {
	if ( ! is_singular( 'writer' ) || ! in_the_loop() || ! is_main_query() ) {
		return $content;
	}
	$post = get_post();
	if ( ! $post ) {
		return $content;
	}
	$writers = kpop_get_writers();
	$key     = $post->post_name;
	if ( isset( $writers[ $key ] ) ) {
		return kpop_render_writer_profile( $key, $writers[ $key ] );
	}
	return $content;
} );

/* ── 一覧(/writers/)を JSON から描画 ─────────────────────────────────── */
/**
 * post_type archive のループ本文を、シンプルなカードグリッドに置換する。
 * GeneratePress の archive ループ内 the_content / the_excerpt が CPT では空なので、
 * archive タイトル直下にグリッドを出すフックで一覧を構築する。
 */
add_action( 'generate_before_main_content', function () {
	if ( ! is_post_type_archive( 'writer' ) ) {
		return;
	}
	$writers = kpop_get_writers();
	if ( empty( $writers ) ) {
		return;
	}
	$colors = array( '#ec4899', '#8b5cf6', '#06b6d4', '#f59e0b', '#10b981', '#ef4444', '#3b82f6', '#6366f1' );
	echo '<div class="kpop-writers-archive"><h1 class="kpop-writers-archive-title">ライター紹介</h1>';
	echo '<p class="kpop-writers-archive-lead">KPOP JOURNAL を書いているメンバーです。それぞれ推しも視点もバラバラ。</p>';
	echo '<div class="kpop-writers-grid">';
	foreach ( $writers as $key => $w ) {
		$post = get_page_by_path( $key, OBJECT, 'writer' );
		$url  = $post ? get_permalink( $post ) : home_url( '/writers/' . $key . '/' );
		$name = isset( $w['name'] ) ? $w['name'] : $key;
		$stance = isset( $w['stance'] ) ? $w['stance'] : '';
		$cidx = abs( crc32( $key ) ) % count( $colors );
		$color = $colors[ $cidx ];
		$initial = function_exists( 'mb_substr' ) ? mb_substr( $name, 0, 1 ) : substr( $name, 0, 1 );
		$thumb = ( $post && has_post_thumbnail( $post ) ) ? get_the_post_thumbnail( $post, 'thumbnail' ) : '';
		echo '<a class="kpop-writer-card" href="' . esc_url( $url ) . '">';
		if ( $thumb ) {
			echo '<span class="kpop-writer-card-av">' . $thumb . '</span>';
		} else {
			echo '<span class="kpop-writer-card-av kpop-writer-card-av--ph" style="background:' . esc_attr( $color ) . ';">' . esc_html( $initial ) . '</span>';
		}
		echo '<span class="kpop-writer-card-name">' . esc_html( $name ) . '</span>';
		echo '<span class="kpop-writer-card-stance">' . esc_html( $stance ) . '</span>';
		echo '</a>';
	}
	echo '</div></div>';
}, 5 );

/* ── 最低限のスタイル(テーマ style.css を汚さず inline で同梱) ──────────── */
add_action( 'wp_head', function () {
	if ( ! is_singular( 'writer' ) && ! is_post_type_archive( 'writer' ) ) {
		return;
	}
	?>
	<style id="kpop-writer-css">
	.kpop-writer-profile{max-width:720px;margin:0 auto}
	.kpop-writer-hero{display:flex;align-items:center;gap:1.2rem;margin-bottom:1.4rem}
	.kpop-writer-avatar{width:96px;height:96px;border-radius:50%;overflow:hidden;flex:0 0 auto}
	.kpop-writer-avatar img{width:100%;height:100%;object-fit:cover}
	.kpop-writer-avatar--ph{display:flex;align-items:center;justify-content:center;color:#fff;font-size:2.4rem;font-weight:700}
	.kpop-writer-name{margin:0;font-size:1.6rem}
	.kpop-writer-stance{margin:.2rem 0 0;color:#555;font-size:.95rem}
	.kpop-writer-bio{line-height:1.9;color:#333}
	.kpop-writer-meta{margin:1.2rem 0;border-top:1px solid #eee}
	.kpop-writer-metarow{display:flex;gap:.8rem;padding:.7rem 0;border-bottom:1px solid #eee;font-size:.95rem}
	.kpop-writer-metalabel{flex:0 0 7.5em;color:#888}
	.kpop-writer-metaval{color:#222}
	.kpop-writer-tag{display:inline-block;background:#f3f0fb;color:#6d28d9;border-radius:999px;padding:.1rem .7rem;margin:0 .3rem .3rem 0;font-size:.85rem}
	.kpop-writer-sign{color:#666;font-size:.9rem}
	.kpop-writers-archive{max-width:920px;margin:0 auto}
	.kpop-writers-archive-title{font-size:1.7rem;margin-bottom:.3rem}
	.kpop-writers-archive-lead{color:#666;margin-bottom:1.6rem}
	.kpop-writers-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:1rem}
	.kpop-writer-card{display:flex;flex-direction:column;align-items:center;text-align:center;gap:.4rem;padding:1.2rem .6rem;border:1px solid #eee;border-radius:14px;text-decoration:none;color:inherit;transition:box-shadow .15s}
	.kpop-writer-card:hover{box-shadow:0 4px 18px rgba(0,0,0,.08)}
	.kpop-writer-card-av{width:64px;height:64px;border-radius:50%;overflow:hidden}
	.kpop-writer-card-av img{width:100%;height:100%;object-fit:cover}
	.kpop-writer-card-av--ph{display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.6rem;font-weight:700}
	.kpop-writer-card-name{font-weight:700;font-size:1rem}
	.kpop-writer-card-stance{color:#777;font-size:.8rem;line-height:1.4}
	</style>
	<?php
} );
