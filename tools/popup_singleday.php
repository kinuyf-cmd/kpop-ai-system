<?php
/**
 * popup_singleday.php — popup イベント(🛍)を「単日」に正規化する owner 実行スクリプト。
 *
 * 背景: popup 98件が会期4月〜の長期 multiday イベントのため、TEC 月カレンダーで
 *   (1) 名前なし継続バーを全日量産(→ tribe_get_event で表示は単日化済)
 *   (2) occurrence の取得順が元の開始日のままで、各日の先頭を占有 → 当日開始の
 *       誕生日が events_per_day の枠から漏れる(モバイル当日リスト・過密日で
 *       誕生日が見えない真因)。
 * これは非破壊PHPでは制御できず、occurrence を単日化する以外に根治できない。
 * postmeta 直接更新は TEC Custom Tables の整合を壊すため、TEC 公式 API
 * tribe_update_event() で更新し occurrence を正しく再生成する。
 *
 * 安全装置:
 *   - --dry-run: 変更せず対象と新旧値だけ表示
 *   - 既に単日(start日==end日)のものはスキップ
 *   - バックアップCSV(data/popup_eventdate_backup_*.csv)で復元可能
 *   - 🛍 prefix のイベントのみ対象(誕生日🎂・ライブは触らない)
 *   - 会期データ(記事本文の開催期間)は別管理なので影響なし
 *
 * 実行(owner、stg WP のドキュメントルートで):
 *   wp eval-file /home/aiuser/kpop-ai-system/tools/popup_singleday.php --dry-run   # 確認
 *   wp eval-file /home/aiuser/kpop-ai-system/tools/popup_singleday.php             # 本実行
 *
 * 復元(万一の時、owner):
 *   wp eval-file /home/aiuser/kpop-ai-system/tools/popup_singleday.php --restore=/path/to/backup.csv
 */

if ( ! defined( 'ABSPATH' ) ) {
	fwrite( STDERR, "WordPress 環境で wp eval-file から実行してください。\n" );
	exit( 1 );
}

// --- 引数 ---
// WP-CLI `wp eval-file <file> <arg1> <arg2> ...` は追加の「位置引数」を $args 配列で
// 渡す。`--dry-run` のような --フラグ形式は WP-CLI 本体が未知オプションとして弾く
// ため、ここでは `--` を付けない位置引数で受ける:
//   wp eval-file popup_singleday.php dry-run            → $args = ['dry-run']
//   wp eval-file popup_singleday.php restore /path.csv  → $args = ['restore','/path.csv']
$opts = array();
if ( isset( $args ) && is_array( $args ) ) {
	$opts = $args;             // WP-CLI eval-file の標準
} elseif ( isset( $argv ) && is_array( $argv ) ) {
	$opts = $argv;             // フォールバック
}
// 旧 --dry-run / --restore= 形式も後方互換で受ける。
$dry_run = in_array( 'dry-run', $opts, true ) || in_array( '--dry-run', $opts, true );
$restore = '';
foreach ( $opts as $i => $o ) {
	$o = (string) $o;
	if ( strpos( $o, '--restore=' ) === 0 ) {
		$restore = substr( $o, strlen( '--restore=' ) );
	} elseif ( $o === 'restore' && isset( $opts[ $i + 1 ] ) ) {
		$restore = (string) $opts[ $i + 1 ];
	}
}

if ( ! function_exists( 'tribe_update_event' ) ) {
	WP_CLI::error( 'The Events Calendar が有効ではありません(tribe_update_event 不在)。' );
	return;
}

/* ============================ 復元モード ============================ */
if ( $restore !== '' ) {
	if ( ! is_readable( $restore ) ) {
		WP_CLI::error( "復元CSVが読めません: {$restore}" );
		return;
	}
	$fh = fopen( $restore, 'r' );
	$header = fgetcsv( $fh ); // ID,start,end
	$done = 0; $fail = 0;
	while ( ( $row = fgetcsv( $fh ) ) !== false ) {
		list( $id, $start, $end ) = array( (int) $row[0], $row[1], $row[2] );
		$ok = tribe_update_event( $id, array(
			'EventStartDate' => $start,
			'EventEndDate'   => $end,
			'EventAllDay'    => true,
		) );
		if ( $ok ) { $done++; } else { $fail++; WP_CLI::warning( "復元失敗 ID={$id}" ); }
	}
	fclose( $fh );
	WP_CLI::success( "復元完了: {$done}件 / 失敗 {$fail}件" );
	return;
}

/* ============================ 単日化モード ============================ */
// 🛍 で始まる publish の tribe_events を取得
$q = new WP_Query( array(
	'post_type'      => 'tribe_events',
	'post_status'    => 'publish',
	'posts_per_page' => -1,
	'fields'         => 'ids',
	'no_found_rows'  => true,
) );

$targets = array();
foreach ( $q->posts as $pid ) {
	$title = get_the_title( $pid );
	if ( mb_strpos( $title, '🛍' ) === 0 ) {
		$targets[] = $pid;
	}
}

WP_CLI::log( sprintf( '対象 popup(🛍): %d 件 / モード: %s', count( $targets ), $dry_run ? 'DRY-RUN' : '本実行' ) );

$changed = 0; $skipped = 0; $failed = 0;
foreach ( $targets as $pid ) {
	$start = get_post_meta( $pid, '_EventStartDate', true );
	$end   = get_post_meta( $pid, '_EventEndDate', true );
	if ( ! $start ) { $skipped++; continue; }

	$start_day = substr( $start, 0, 10 );
	$end_day   = substr( (string) $end, 0, 10 );

	if ( $start_day === $end_day ) {
		$skipped++; // 既に単日
		continue;
	}

	$new_end = $start_day . ' 23:59:59';

	if ( $dry_run ) {
		WP_CLI::log( sprintf( '  [DRY] ID=%d "%s"  end %s -> %s',
			$pid, mb_substr( get_the_title( $pid ), 0, 22 ), $end, $new_end ) );
		$changed++;
		continue;
	}

	// TEC 公式 API で更新(postmeta + wp_tec_occurrences を整合更新)。
	// TZ は各イベントの _EventTimezone(本サイトは全件 Asia/Tokyo)を TEC が
	// 踏襲し UTC を再計算する。TZ が混在する環境では 'EventTimezone' も
	// 明示すること(本サイトでは不要)。
	$ok = tribe_update_event( $pid, array(
		'EventStartDate' => $start_day . ' 00:00:00',
		'EventEndDate'   => $new_end,
		'EventAllDay'    => true, // 終日は維持(時刻なし表示)。単日終日になる。
	) );

	if ( $ok ) {
		$changed++;
		if ( $changed % 20 === 0 ) {
			WP_CLI::log( "  ... {$changed} 件更新" );
		}
	} else {
		$failed++;
		WP_CLI::warning( "更新失敗 ID={$pid}" );
	}
}

WP_CLI::success( sprintf(
	'%s: 単日化 %d件 / スキップ(既単日含む) %d件 / 失敗 %d件',
	$dry_run ? 'DRY-RUN(変更なし)' : '完了',
	$changed, $skipped, $failed
) );

if ( ! $dry_run && $changed > 0 ) {
	// TEC のビューキャッシュを消して即反映
	if ( function_exists( 'tribe' ) ) {
		WP_CLI::log( '※ 反映には wp transient delete --all と wp cache flush を推奨。' );
	}
}
