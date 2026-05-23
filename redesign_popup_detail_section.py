#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""popup 詳細「開催情報」セクション再設計(オーナー承認 2026-05-23)。

functions.php / style.css を保守的なアンカー一致で書き換える。
  1) 上段3カード: 期間(+残N日) / エリア(+ソウル等) / 予約(+補助文)。営業時間→per-itemリストへ。
  2) 特典ピンク強調バー(値ありのみ)。
  3) 住所+地図 1カード統合(日本語 + ハングル popup_address_ko 併記 + iframe 枠線区切り)。
  4) Googleマップ CTA(.kpop-popup-map-fallback)削除。地図 iframe は維持。
  5) kpop_popup_days_left() ヘルパ追加。popup_address_ko を $get に追加。
  6) 出典維持・空非表示・6色AA維持。

冪等: アンカーが既に new 形に置換済みなら skip(再実行で二重適用しない)。
バックアップ: 編集前に *.bak.<TS> を残す。実行後に呼び出し側で php -l すること。

  sudo -u www-data DRY_RUN=0 python3 redesign_popup_detail_section.py        # 適用
  DRY_RUN=1 python3 redesign_popup_detail_section.py                          # 差分のみ表示
"""
import os
import sys
import time
import shutil

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
THEME = "/var/www/wp_stg/wp-content/themes/generatepress-kpop"
FUNC = os.path.join(THEME, "functions.php")
CSS = os.path.join(THEME, "style.css")
TS = time.strftime("%Y%m%d_%H%M%S")

# ── functions.php: $get 群に popup_address_ko を追加 ──────────────────
GET_ANCHOR = "\t$map_embed    = $get( 'popup_map_embed' );\n"
GET_NEW = (
    "\t$map_embed    = $get( 'popup_map_embed' );\n"
    "\t$address_ko   = $get( 'popup_address_ko' );\n"
)

# ── functions.php: ヒーロー(期間/エリア/営業時間)→(期間+残N日/エリア+補助/予約+補助)──
HERO_OLD = '''	/* ── ① ヒーロー行: 「いつ・どこで・何時」を大きく(個別改修5)──────────
	 * 期間 / エリア / 営業時間 を最優先の大きいパステルカード3枚で先頭表示。
	 * 空項目は出さない(個別改修6)。6色のうち rose/mint/lavender を使用。 */
	$hero = array(
		array( 'icon' => '📅', 'label' => '期間',    'color' => 'rose',     'val' => ( $period_start || $period_end ) ? trim( $period_start . ' 〜 ' . $period_end ) : '' ),
		array( 'icon' => '📍', 'label' => 'エリア',   'color' => 'mint',     'val' => $area ),
		array( 'icon' => '🕒', 'label' => '営業時間', 'color' => 'lavender', 'val' => $hours ),
	);
	$has_hero = false;
	foreach ( $hero as $h ) { if ( $h['val'] ) { $has_hero = true; break; } }
	if ( $has_hero ) {
		echo '<div class="kpop-popup-hero">';
		foreach ( $hero as $h ) {
			if ( ! $h['val'] ) { continue; }
			$ccls = ' kpop-popup-row--' . sanitize_html_class( $h['color'] );
			echo '<div class="kpop-popup-hero-card' . esc_attr( $ccls ) . '">';
			echo '<span class="kpop-popup-hero-label"><span class="kpop-popup-ic" aria-hidden="true">' . esc_html( $h['icon'] ) . '</span>' . esc_html( $h['label'] ) . '</span>';
			echo '<span class="kpop-popup-hero-val">' . nl2br( esc_html( $h['val'] ) ) . '</span>';
			echo '</div>';
		}
		echo '</div>';
	}
'''

HERO_NEW = '''	/* ── ① 上段3カード(再設計 2026-05-23): 期間 / エリア / 予約 ──────────
	 * 1秒の視認性。各カード: アイコン+ラベル(小)+値(大)+補助テキスト(小)。
	 * 予約が空なら 予約カードを出さない(=2カード)。flex 均等で崩れない。
	 * 営業時間は per-item リストへ移動。6色は rose/mint/teal。 */
	$days_left = kpop_popup_days_left( $period_end ? $period_end : $period_start );
	$period_val = ( $period_start || $period_end ) ? kpop_popup_period_short( $period_start, $period_end ) : '';
	if ( '' === $period_val && ( $period_start || $period_end ) ) { $period_val = trim( $period_start . ' 〜 ' . $period_end ); }
	$period_sub = '';
	if ( $badge && 'ended' === $badge['state'] ) { $period_sub = '終了'; }
	elseif ( null !== $days_left && $days_left > 0 ) { $period_sub = 'あと' . $days_left . '日'; }
	elseif ( null !== $days_left && 0 === $days_left ) { $period_sub = '本日まで'; }
	$resv_sub = '';
	if ( $reservation ) {
		if ( false !== strpos( $reservation, '不要' ) ) { $resv_sub = '当日OK'; }
		elseif ( false !== strpos( $reservation, '予約' ) ) { $resv_sub = '要チェック'; }
	}
	$hero = array(
		array( 'icon' => '📅', 'label' => '期間',  'color' => 'rose', 'val' => $period_val,   'sub' => $period_sub ),
		array( 'icon' => '📍', 'label' => 'エリア', 'color' => 'mint', 'val' => $area,         'sub' => $area ? 'ソウル' : '' ),
		array( 'icon' => '🎫', 'label' => '予約',  'color' => 'teal', 'val' => $reservation,  'sub' => $resv_sub ),
	);
	$has_hero = false;
	foreach ( $hero as $h ) { if ( $h['val'] ) { $has_hero = true; break; } }
	if ( $has_hero ) {
		echo '<div class="kpop-popup-hero kpop-popup-hero--3">';
		foreach ( $hero as $h ) {
			if ( ! $h['val'] ) { continue; }
			$ccls = ' kpop-popup-row--' . sanitize_html_class( $h['color'] );
			echo '<div class="kpop-popup-hero-card' . esc_attr( $ccls ) . '">';
			echo '<span class="kpop-popup-hero-label"><span class="kpop-popup-ic" aria-hidden="true">' . esc_html( $h['icon'] ) . '</span>' . esc_html( $h['label'] ) . '</span>';
			echo '<span class="kpop-popup-hero-val">' . nl2br( esc_html( $h['val'] ) ) . '</span>';
			if ( $h['sub'] ) { echo '<span class="kpop-popup-hero-sub">' . esc_html( $h['sub'] ) . '</span>'; }
			echo '</div>';
		}
		echo '</div>';
	}

	/* ── ①.5 特典 強調バー(再設計): ピンク主役・値ありのみ・1段。 */
	if ( $benefit ) {
		echo '<div class="kpop-popup-benefit-bar">';
		echo '<span class="kpop-popup-benefit-ic" aria-hidden="true">🎁</span>';
		echo '<span class="kpop-popup-benefit-label">特典</span>';
		echo '<span class="kpop-popup-benefit-text">' . nl2br( esc_html( $benefit ) ) . '</span>';
		echo '</div>';
	}
'''

# ── functions.php: サブ情報リスト(住所/主催/予約/特典 → 主催/営業時間)──────────
# 住所は地図統合カードへ・予約は上段へ・特典はバーへ移したので、リストは 主催/営業時間 のみ。
ROWS_OLD = '''	$rows = array(
		array( 'icon' => '🏠', 'label' => '住所', 'color' => 'peach', 'val' => $address ),
		array( 'icon' => '🏢', 'label' => '主催', 'color' => 'blue',  'val' => $organizer ),
		array( 'icon' => '🎫', 'label' => '予約', 'color' => 'teal',  'val' => $reservation ),
		array( 'icon' => '🎁', 'label' => '特典', 'color' => 'rose',  'val' => $benefit ),
	);'''
ROWS_NEW = '''	$rows = array(
		array( 'icon' => '🏢', 'label' => '主催',   'color' => 'blue',     'val' => $organizer ),
		array( 'icon' => '🕒', 'label' => '営業時間', 'color' => 'lavender', 'val' => $hours ),
	);'''

# ── functions.php: 地図ブロック → 住所+地図 統合カード(CTA 削除・iframe 維持・ハングル併記)──
MAP_OLD = '''	if ( $map_embed ) {
		echo '<div class="kpop-popup-map">';
		echo '<iframe src="' . esc_url( $map_embed ) . '" width="100%" height="320" style="border:0" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="開催場所の地図"></iframe>';
		echo '</div>';
	} elseif ( $address ) {
		$map_q  = rawurlencode( $address );
		$gen_src = 'https://www.google.com/maps?q=' . $map_q . '&output=embed';
		echo '<div class="kpop-popup-map">';
		echo '<iframe src="' . esc_url( $gen_src ) . '" width="100%" height="320" style="border:0" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="開催場所の地図(' . esc_attr( $address ) . ')"></iframe>';
		echo '</div>';
		echo '<p class="kpop-popup-map-fallback"><a href="https://www.google.com/maps/search/?api=1&amp;query=' . esc_attr( $map_q ) . '" rel="nofollow noopener external" target="_blank">Google マップで開く →</a></p>';
	}'''
MAP_NEW = '''	/* ── 住所+地図 統合カード(再設計): 日本語住所 + ハングル併記 + iframe 同梱。
	 *   Googleマップ「で開く」CTA は削除(地図は同カード内に表示済みのため)。
	 *   map_embed があればそれを、無ければ住所から Google maps embed を自前生成。 */
	if ( $address || $map_embed ) {
		echo '<div class="kpop-popup-addrmap kpop-popup-row--peach">';
		if ( $address ) {
			echo '<div class="kpop-popup-addrmap-head">';
			echo '<span class="kpop-popup-ic" aria-hidden="true">🏠</span>';
			echo '<div class="kpop-popup-addrmap-text">';
			echo '<span class="kpop-popup-addr-ja">' . nl2br( esc_html( $address ) ) . '</span>';
			if ( $address_ko ) {
				echo '<span class="kpop-popup-addr-ko" lang="ko">' . esc_html( $address_ko ) . '</span>';
			}
			echo '</div>';
			echo '</div>';
		}
		$map_src = $map_embed;
		if ( ! $map_src && $address ) {
			$map_src = 'https://www.google.com/maps?q=' . rawurlencode( $address ) . '&output=embed';
		}
		if ( $map_src ) {
			$map_title = $address ? '開催場所の地図(' . $address . ')' : '開催場所の地図';
			echo '<div class="kpop-popup-addrmap-frame">';
			echo '<iframe src="' . esc_url( $map_src ) . '" width="100%" height="300" style="border:0" loading="lazy" referrerpolicy="no-referrer-when-downgrade" title="' . esc_attr( $map_title ) . '"></iframe>';
			echo '</div>';
		}
		echo '</div>';
	}'''

# ── functions.php: kpop_popup_days_left ヘルパ(kpop_popup_period_short の直後に挿入)──
HELPER_ANCHOR = "/* --- 個別改修1: SNS URL → ブランドアイコン+ラベルのピル ----------------------"
HELPER_NEW = '''/* 終了日(Y-m-d)から「あと何日」を算出。終了済み・算出不能は null。
 * 上段カードの期間補助テキスト用(再設計 2026-05-23)。捏造せず日付からのみ算出。 */
function kpop_popup_days_left( $end ) {
	$end = is_string( $end ) ? trim( $end ) : '';
	if ( ! preg_match( '/^(\\d{4})-(\\d{2})-(\\d{2})$/', $end ) ) { return null; }
	$today = strtotime( current_time( 'Y-m-d' ) );
	$e = strtotime( $end );
	if ( false === $today || false === $e ) { return null; }
	$d = (int) floor( ( $e - $today ) / 86400 );
	return $d;
}

/* --- 個別改修1: SNS URL → ブランドアイコン+ラベルのピル ----------------------'''

# ── style.css 追記(冪等マーカー)────────────────────────────────────
CSS_MARKER = "/* === popup 開催情報 再設計 2026-05-23 === */"
CSS_APPEND = CSS_MARKER + '''
/* 上段3カード: 値(大) + 補助(小)。flex 均等・予約有無で2〜3枚でも崩れない。 */
.kpop-popup-hero--3 { display: flex; flex-wrap: wrap; gap: 0.7em; margin: 0 0 0.9em; }
.kpop-popup-hero--3 .kpop-popup-hero-card {
	flex: 1 1 9em; min-width: 9em; display: flex; flex-direction: column;
	gap: 0.18em; padding: 0.85em 0.9em; border-radius: 14px;
}
.kpop-popup-hero-sub { font-size: 0.78em; font-weight: 700; opacity: 0.92; }
/* 特典 強調バー: ピンク主役。--kpop-pink-dark(白上5.87)背景 + 白文字 → AA。 */
.kpop-popup-benefit-bar {
	display: flex; align-items: center; gap: 0.5em; flex-wrap: wrap;
	background: var(--kpop-pink-dark, #C2185B); color: #fff;
	border-radius: 12px; padding: 0.7em 0.95em; margin: 0 0 0.9em;
	font-size: 0.98em; line-height: 1.5;
}
.kpop-popup-benefit-ic { font-size: 1.15em; }
.kpop-popup-benefit-label { font-weight: 800; letter-spacing: 0.03em; flex: 0 0 auto; }
.kpop-popup-benefit-text { font-weight: 600; flex: 1 1 12em; }
/* 住所+地図 統合カード: 住所(日本語+ハングル小)+ iframe を1枠に。peach 系。 */
.kpop-popup-addrmap {
	border-radius: 14px; overflow: hidden; margin: 0 0 0.9em;
	box-shadow: 0 1px 3px rgba(20,20,40,0.06); background: var(--pp-peach, #FFE8D6);
}
.kpop-popup-addrmap-head { display: flex; gap: 0.5em; align-items: flex-start; padding: 0.85em 0.95em; }
.kpop-popup-addrmap-head .kpop-popup-ic { font-size: 1.2em; line-height: 1.3; }
.kpop-popup-addrmap-text { display: flex; flex-direction: column; gap: 0.15em; }
.kpop-popup-addr-ja { color: var(--pp-peach-deep, #8a4b1f); font-weight: 700; }
.kpop-popup-addr-ko { color: var(--pp-peach-deep, #8a4b1f); font-size: 0.85em; opacity: 0.85; }
/* 地図 iframe は住所の下に枠線で区切って同梱。 */
.kpop-popup-addrmap-frame { border-top: 1px solid rgba(20,20,40,0.10); background: #fff; }
.kpop-popup-addrmap-frame iframe { display: block; width: 100%; height: 300px; border: 0; }
@media (max-width: 600px) {
	.kpop-popup-hero--3 .kpop-popup-hero-card { flex: 1 1 100%; }
	.kpop-popup-addrmap-frame iframe { height: 240px; }
}
'''


def patch_file(path: str, edits: list, label: str) -> bool:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    orig = src
    log = []
    for old, new, name in edits:
        if new in src and old not in src:
            log.append(f"  [skip] {name}(既に適用済)")
            continue
        if old not in src:
            print(f"  [FAIL] {name}: アンカー不一致 — 中止({label})")
            return False
        cnt = src.count(old)
        if cnt != 1:
            print(f"  [FAIL] {name}: アンカーが {cnt} 回出現(1回想定)— 中止")
            return False
        src = src.replace(old, new, 1)
        log.append(f"  [ok]   {name}")
    if src == orig:
        print(f"  ({label}: 変更なし=冪等 skip)")
        return True
    print("\n".join(log))
    if DRY_RUN:
        print(f"  [DRY_RUN] {label} は書き換えず(差分のみ確認)")
        return True
    bak = f"{path}.bak.{TS}"
    shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"  backup → {bak}")
    return True


def main() -> int:
    mode = "DRY_RUN(書込なし)" if DRY_RUN else "APPLY(編集)"
    print(f"=== popup 開催情報 再設計 [{mode}] ===")
    print("[functions.php]")
    ok = patch_file(FUNC, [
        (GET_ANCHOR, GET_NEW, "popup_address_ko を $get に追加"),
        (HERO_OLD, HERO_NEW, "上段3カード(期間/エリア/予約)+特典バー"),
        (ROWS_OLD, ROWS_NEW, "リストを 主催/営業時間 に縮約"),
        (MAP_OLD, MAP_NEW, "住所+地図 統合カード(CTA削除)"),
        (HELPER_ANCHOR, HELPER_NEW, "kpop_popup_days_left ヘルパ追加"),
    ], "functions.php")
    if not ok:
        return 1
    print("[style.css]")
    with open(CSS, encoding="utf-8") as f:
        css = f.read()
    if CSS_MARKER in css:
        print("  (style.css: 既に追記済=冪等 skip)")
    elif DRY_RUN:
        print("  [DRY_RUN] style.css に再設計CSSを追記予定(未書込)")
    else:
        shutil.copy2(CSS, f"{CSS}.bak.{TS}")
        with open(CSS, "a", encoding="utf-8") as f:
            f.write("\n" + CSS_APPEND + "\n")
        print(f"  backup → {CSS}.bak.{TS} / CSS 追記済")
    print("=== 完了。functions.php は php -l で必ず構文チェックすること ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
