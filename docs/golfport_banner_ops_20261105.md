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

## 2. GOLF PORT 側への共有(2026-11-05 18:4x 送信済み・文案は下記の要旨)
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

## 6. 追加裁定(2026-11-05 夜)の記録
### 6-1. GOLF PORTへの共有 — 送信結果
- 送信先: セッション「5e マーケ、広告」(GOLF PORT計測担当)。送信成功(msg_id 4366d448…)、同セッションから返信あり。
- 伝えた内容: 3系統の公開状況と utm_content、GA4受信確認の状況(dataLayer発火=確認済み/GA4受信=未確認、11/6・11/7に確認)、GOLF PORT側で必要な流入データ、ロゴ・ブランド統一の確認依頼。
- 返信の要点(5e): UTM4値・utm_content3種・遷移先・無料表現なしは GOLF PORT 側の仕様どおりで問題なし。1週間の取得確認は GOLF PORT 側(GA4 参照元/メディア・キャンペーン・utm_content)で実施し T1 経由で返す。11/12・11/19 の数値の出し方は T1 が決める。GA4の「初回記録」イベントはまだ無く(PR準備中)、入るまでは GOLF PORT 側 DB で数える。登録/初回記録は**バナー由来と証明できる分(解析同意あり)だけ**。同意前に登録まで進んだ分は DB に流入元が残らない(レポートの突き合わせ注意に反映済み)。
- **ロゴ・ブランドカラー・禁止表現の可否は 5e の判断外 → GOLF PORT オーナー(T1経由)の回答待ち。確認が取れるまで本番に反映しない。**

### 6-2. ブランド実測(公開中の golfport.top を 2026-11-05 に計測)
- ヘッダーのロゴ: `/logo.png`(ブルーのワードマーク+円環エンブレム。リポジトリの public/logo.png と同一)
- `/record` の主CTA「無料で記録をはじめる」: 背景 **#2563eb**・白文字。トップの検索系CTAは #fec94b(イエロー)・文字 #1e293b。
- 現バナー(グリーン #1d6b3f)はブランドと不一致。**提案: ロゴ=正式ロゴ、CTA=#2563eb、薄い青背景(#f5f8ff)、文字=#1e293b/#475569**(`/record` とCTA色が連続する)。コピーとUTMは変更しない。
- プレビュー(本番未反映): scratchpad の brand_pc.png / brand_mobile.png(現行 vs 提案・PC/スマホ/1:1)。ロゴは 480px WebP 約23KB(data URI埋め込み前提。php-fpmは/home不可・ラッパーは直下php/cssのみ)。実装時の調整: 1:1ではロゴを大きく(約40px)して余白を埋める。
- 実在しないアプリ画面をGOLF PORTの実画面として載せない(イラスト・ロゴ・テキストのみ)。

### 6-3. 受領した別案(グリーン基調の300×300 / 300×600 / 728×90)について
- 現行ブランド(ブルー)と色が不一致。ワードマークも正式ロゴ(セリフ体+エンブレム)と別物で、**どれが正式かの確認が必要**。
- 文字が画像に焼き込まれており、スマホ可読性・altでの伝達・文言修正の容易性の面で、HTML/CSS実装(現行方式)より不利。300×600・728×90 は現レイアウトに該当枠が無い。728×90 のコピーは承認済みと異なる(「ラウンド・練習・写真の記録」)。300×300 に「運営関連サービス」表示が無い。
- チャット貼付のためファイルとして受け取れていない。使う場合は元ファイルと利用条件の確認が必要。

### 6-4. AdSense・A8
- **AdSense: 再認証が必要な状態として記録**(`google_metrics/adsense_token.json` が 2026-08-29 から0バイト)。オーナー操作なしにOAuth認証・秘密情報の変更は行わない。再認証は保留(owner裁定)。収益は未計測。
- **A8: 収益は取得できず未計測**(管理画面のみ)。

### 6-5. cron(登録済み・4本)の動作確認方法
11/6・11/7・11/12・11/19 の各 10:30 に、実行ログ `~/.kpop_recovery/golfport_banner_report.cron.log` と生成ファイル `reports/golfport_banner/<日付>_*.md` の両方で確認する(ファイルのサイズ・更新時刻・[A]の表示数が0でないか)。失敗時は手動で `tools/golfport_banner_report.py` を実行する。

### 6-6. GOLF PORT側の決定(5e・2026-11-05 夜)
1. **11/12(7日)・11/19(14日)の数値はGOLF PORT側が出す(取りまとめ=5e)**。件数のみ: GA4セッション(kpopjournal/house_banner・utm_content別)、新規登録(流入元がkpopjournal)、初回記録。個人に結びつく情報は出さない。**件数1〜2は「3件未満」と表記**。解析同意があった分だけで、実数より少ない。→ 当方のレポートも同じ秘匿ルールに統一(`small()`)。DB集計は「全体の参考値/下限値」として併記し、GOLF PORT側の数値を正とする。
2. **正式ロゴ・ブランドカラーは使用可。条件2つ**: (a) 変形・色の変更をしない(縮尺のみ・縦横比固定・単色化/反転/ぼかし/回転/トリミング/影付けも不可)。(b) 使った版を一度GOLF PORT側に見せて確認を取る。ファイルの置き場所・正式カラー値は GOLF PORT デザイン担当(be)が保持。5eが be に依頼し、判明次第こちらへ連絡する(待ち)。
   - 当方のプレビューは `public/logo.png` を縮小しただけ(色変更なし)だが、**正式な配布版ではない**。CTA色 #2563eb は公開サイトの実測値であり、be の正式値で置換する。
3. **載せてはいけない表現**: 効果の言い切り(必ず上達・100切り保証等)、「完全無料」「すべて無料」、最上級(No.1・日本一等)、コーチ/利用者の実名・写真、料金・返金の数字。新しい文言は GOLF PORT 側の法務確認後。現行コピー(「ゴルフの思い出、ひとつに。/ラウンド・練習・写真を記録して振り返る。/GOLF PORTを見てみる」)は該当しない。
4. **本番反映はロゴ版の確認が済むまで待つ(方針どおり)**。

### 6-7. 次の一手(待ち→実装の順)
- be から正式アセット/色値が届く → それで提案版を作り直し(変形なし)→ GOLF PORT側(5e経由)に版を見せて確認 → OKなら本番反映(WPオプションではなくテーマのデプロイが必要。デプロイ前の差分監査・PR更新・枠別停止手順は従来どおり)。
- 色変更後は同一枠で前後を混ぜずに比較する(必要なら `utm_content` を `article_footer_a` 等で分ける。その場合も固定4パラメータ・utm_content形式[a-z0-9_]≤40字を守り、GOLF PORT側へ事前連絡)。
