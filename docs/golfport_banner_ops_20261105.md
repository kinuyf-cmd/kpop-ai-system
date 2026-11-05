# GOLF PORT 自社バナー 公開後運用メモ(2026-11-05)

## 1. 現在の掲載(2026-11-05 公開)
| 設置場所 | utm_content | 対象 | 公開日時(JST) |
|---|---|---|---|
| kdrama記事末尾 | article_footer | kdrama 36本 | 11/5 18:11 |
| トップ右サイドバー(旧PORT=A8 top_fixed の置換・1:1) | top_sidebar | トップのみ | 11/5 18:20 |
| 大型イベント特設ページ | event_page | 記事ID 4826(MAMA)/21866(KGMA)/23381(MMA)/23390(AAA) | 11/5 18:23 |

- 遷移先: `https://golfport.top/record?utm_source=kpopjournal&utm_medium=house_banner&utm_campaign=golf_record_202611&utm_content=<設置場所>`(固定4パラメータのみ)
- 本番テーマ=PR #1 head(base=rebuild-20260521)と一致。実装: `themes/generatepress-kpop/golfport-house-banner.php`
- 停止: WPオプション `kpop_golfport_banner`。全停止 `{"enabled":false}`、枠別は `top_sidebar` / `article_footer` / `event_page` を false。トップを止めると旧PORT広告が戻る。
  `sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh option update kpop_golfport_banner '<json>' --format=json`

## 2. GOLF PORT 側への共有文案(未送信・オーナー確認後に送る)
> K-POP JOURNALでのGOLF PORT自社バナーを、2026-11-05(18:11〜18:23 JST)に3か所で公開しました。
> 遷移先は確定仕様どおり `https://golfport.top/record` で、UTMは固定4パラメータのみです。
> - 記事末尾(kdrama36本): `utm_content=article_footer`
> - トップ右サイドバー: `utm_content=top_sidebar`
> - 大型イベントページ(MAMA/KGMA/MMA/AAAの特設4本): `utm_content=event_page`
> 共通: `utm_source=kpopjournal` `utm_medium=house_banner` `utm_campaign=golf_record_202611`。
> 通常のリンクで、短縮・中継・リダイレクト・utm_termは使っていません。文言は「ゴルフの思い出、ひとつに。/ラウンド・練習・写真を記録して振り返る。/GOLF PORTを見てみる」で、「無料」等の表現は使っていません。
> お願い: (1) 最初の1週間、GA4で「kpopjournal / house_banner / golf_record_202611」と utm_content 3種が取得できているかのご確認。(2) 訪問・新規登録・初回記録(ラウンド/練習/思い出)の参照元別の数値を11/12と11/19にご共有ください。
> 注意: GOLF PORT側は解析Cookie許可者のみUTMを記録するため、バナー経由の登録は実数より少なく出ます。Unassignedのデフォルトチャネルでは判断しません。

## 3. ブランド整合性(正式ロゴとの差分と改善案)
正式ロゴ(`golf-lesson-navi/public/logo.png`・`icon.png`)との差:
| 項目 | 正式 | 現バナー |
|---|---|---|
| 色 | ロイヤルブルー 約#1a47e8 + ネイビー(アイコン背景 #4b56fc→#131762) | グリーン #1d6b3f / 薄緑 |
| ワードマーク | セリフ体「GOLF PORT」 | ゴシック太字テキスト |
| エンブレム | 円環+ピンフラッグ+ボール+波の船着き場 | 簡易な旗とグリーンのイラスト(赤旗) |

改善案(未実装。正式素材の掲載可否とGOLF PORT側の承認が前提):
1. **最小**: 色だけ合わせる(CTA/ブランド文字 #1d6b3f→#1a47e8、薄緑背景→薄青)。CSSのみ・影響範囲は `.kpop-ghb*`。
2. **推奨**: アイコン(icon.png 512px)を128px程度のWebP(数KB)に縮小し、SVGイラストと置換。テーマ配信ラッパーは直下のphp/cssのみ配置可・php-fpmは/homeを読めないため、画像は data URI で php に埋め込む(or WPメディア登録)。正式ワードマークはロゴ画像(横長)で「GOLF PORT」テキストと置換。
3. 読者(K-POP)には青系が既存のサイト色とも衝突しにくい。ただし色変更は GOLF PORT の同意が前提で、A/Bで差を測るなら同一枠に混ぜずに期間を分ける(utm_content は `article_footer_a` 等)。
変更しても遷移先URL・UTM・キャンペーン名は変えない(GOLF PORT への事前連絡なしに変更禁止)。

## 4. 計測データ源と限界(混ぜない)
| データ源 | 取れるもの | 限界 |
|---|---|---|
| K-POP JOURNAL の GA4 | house_banner_view/click(pagePath・デバイス別)、対象ページPV | 確定に24〜48h。placement は pagePath から判定(banner_content はカスタムディメンション未登録)。dataLayer発火=送信ではない。GA4受信は11/6に確認 |
| GA4の広告イベント | ad_impression / ad_click(プロキシ) | AdSense収益ではない |
| AdSense 収益 | **未計測** | `google_metrics/adsense_token.json` が 2026-08-29 から0バイト。再認証はownerのOAuth操作 |
| A8(PORT含む) | **未計測** | APIなし。A8管理画面のみ。GA4 affiliate_click はA8以外も含みPORT単体不可 |
| GOLF PORT dump(毎日03:00 JST) | 登録時の流入記録(AttributionSnapshot)、登録後の初回ラウンド/練習/単体メモリー(集計のみ) | 訪問・セッションは無い。UTMは解析Cookie許可者のみ。最大約24h遅れ |
| GOLF PORT の GA4 | 参照元/メディア、セッション、新規登録 | このサーバーから未接続 → GOLF PORT側から提供してもらう |

## 5. スケジュール(crontab登録済・年ガード付き・出力 reports/golfport_banner/)
- 11/6 10:30 受信確認(`20261106_day1_reception.md`)、11/7 10:30 再確認(GA4確定待ち)
- 11/12 10:30 7日間(2026-11-05〜11-11)、11/19 10:30 14日間(11-05〜11-18)
- 手動: `venv_kpi/bin/python tools/golfport_banner_report.py --start 2026-11-05 --end <日付>`
- 評価の主軸は表示数・CTRでなく GOLF PORT での登録→初回記録。表示母数が小さいうちは失敗と断定しない。
- news拡大・バナー変更・広告枠追加は実績確認後に提案(news全体はowner裁定)。
