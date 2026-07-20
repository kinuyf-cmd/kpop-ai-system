# 投稿後 8フェーズ点検 — 具体コマンド集

SKILL.md [6] の各フェーズで使う実コマンド。`<POST>`=記事ID、`<URL>`=公開URL、
`<ATT>`=アイキャッチ attachment ID を置き換える。WP操作は
`sudo /usr/local/sbin/kpop/kpop-wp-rw.sh`(書込) / `kpop-wp-ro`(読取)。

## Phase 1: 記事表示チェック
```bash
URL="<URL>"
curl -s -o /tmp/page.html -w "HTTP %{http_code}\n" "$URL"
# 事実・表記チェック(票数/順位/提供元/画像提供)
for kw in "<主役>" "<2位>" "<3位>" "<票数>" "画像提供" "提供:"; do
  echo "[$([ $(grep -c "$kw" /tmp/page.html) -gt 0 ] && echo OK || echo NG)] $kw"
done
# H1は改行を挟むので class で確認
grep -oE 'entry-title" itemprop="headline">[^<]*' /tmp/page.html | head -1
```
注意: grep が H1 を取れなくても、HTML改行が原因のことが多い。`entry-title` クラスで再確認する。
実HTMLを必ず見る(コードやDBだけで結論しない)。

## Phase 2: SEO チェック
```bash
P=/tmp/page.html
grep -oE '<meta name="description" content="[^"]*"' $P | sed 's/.*content="//;s/"$//'   # 110-130字
grep -oE '<link rel="canonical" href="[^"]*"' $P                                          # 対象URLを指す
grep -oE 'content="[^"]*noindex[^"]*"' $P || echo "noindexなし(OK)"
grep -oE '<meta property="og:(title|description|image)" content="[^"]*"' $P
```
- slug は変更しない。canonical は対象記事URL。noindex 禁止。
- meta字数: `python3 -c "print(len('...'))"` で正確に数える(目視は誤りやすい)。

## Phase 3: 画像・alt・キャプション
```bash
echo "thumb: $(sudo /usr/local/sbin/kpop/kpop-wp-ro post meta get <POST> _thumbnail_id)"
echo "alt  : $(sudo /usr/local/sbin/kpop/kpop-wp-ro post meta get <ATT> _wp_attachment_image_alt)"
echo "cap  : $(sudo /usr/local/sbin/kpop/kpop-wp-ro post get <ATT> --field=post_excerpt)"
# 重複チェック: ヒーロー画像は1件・本文に同一画像の二重表示が無いこと
grep -c 'kpop-single-hero' /tmp/page.html        # 1 が正常
grep -c 'wp-image-<ATT>'   /tmp/page.html        # 0 が正常(本文に重複figureを入れない)
grep -c '画像提供'         /tmp/page.html        # 1 以上(クレジット残存)
```
- alt 要件語は attachment 側の `_wp_attachment_image_alt` に持たせる(テーマがヒーローの alt を
  タイトルで上書きするため)。
- **同じ画像を本文先頭にも挿入しない**(ヒーローと二重表示になる)。出典は
  `<p class="kpop-image-credit"><small>▲「<企画>」投票結果。画像提供: <提供元></small></p>`
  をリード直後に置いて満たす。

## Phase 4: 内部リンク追加(3-5本)
```bash
# 関連記事候補を探す(主役名/ジャンル/投票 等)
sudo /usr/local/sbin/kpop/kpop-wp-rw.sh db query \
 "SELECT ID,post_title FROM wp_posts WHERE post_status='publish' AND post_type='post' \
  AND ID!=<POST> AND (post_title LIKE '%投票%' OR post_title LIKE '%俳優%') ORDER BY ID DESC LIMIT 25"
# 各記事の本文をバックアップ取得→末尾に非破壊で関連リンク追記→ファイル内容を直接渡して update
```
- 本文は必ずバックアップしてから、末尾に `<p class="kpop-related-link">関連記事: <a href="<URL>">文言</a></p>`
  を追記する全文 update(stdinパイプ禁止)。
- 追加した記事IDとリンク文言をログに残す。被リンクは正規 permalink で curl 確認(`?p=` は0件に見えることがある)。

## Phase 5: GSC 登録
```bash
venv_kpi/bin/python3 lib/gsc_indexing.py --url "<URL>"   # 当日2回目は skipped_dup=正常
# ログ: logs/gsc_resubmit_log.jsonl に {timestamp,url,phase,status,method,note} を追記
# sitemap収録確認
curl -s https://www.kpopjournal.tokyo/sitemap.xml | grep -oE 'https://[^<]+post-sitemap\.xml'
curl -s https://www.kpopjournal.tokyo/post-sitemap.xml | grep -c "<slug>"
```
GSC認証はローカル限定。`google` モジュール不在環境では request_index 系は skip される。

## Phase 6: SNS 文 3案
ニュース型 / ファン共感型 / 投票結果強調型。メイン本文にURLを入れず、URLはリプライへ。
`config/x_post_queue.json` の `queue` 配列に追記(title,url,post_id,genre,artist,priority,
queued_at,x_variant,main_text,reply_text)。HTMLエンティティ・URL混入を assert で検査。

## Phase 7: X 投稿(owner 指示時のみ実投稿)
```bash
python3 -c "import sys;sys.path.insert(0,'google_metrics');from post_to_x import validate_credentials;\
c,e=validate_credentials();print('認証',('OK' if c else 'NG '+';'.join(e)))"
MAIN=$'本文...\n#tag1 #tag2 #tag3'
OUT=$(python3 google_metrics/post_to_x.py "$MAIN"); TID=$(echo "$OUT"|grep -oE 'TWEET_ID=[0-9]+'|cut -d= -f2)
python3 google_metrics/post_to_x.py $'記事はこちら👇\n<URL>' --reply-to "$TID"
```
投稿後 queue に posted=true,tweet_id を記録、未使用案は除去。X の status URL は HTTP 307(ログイン誘導)が正常。

## Phase 8: 最終レポート(9項目)
1.表示 2.SEO 3.画像/alt/キャプション 4.内部リンク 5.GSC 6.SNS3案 7.報告メール本文
8.未対応事項 9.次に打つべき1アクション。
取引先報告メールは templates/partner_outreach/press_release_publish_report.md を使い、送信は owner。
