# イベント収集 診断と設計 v1（2026-05-25）

「イベント情報が1件のみ」の原因究明と、チケット販売サイト活用の設計。実装は次段階。

## 1. 現状診断（なぜ tribe_events が1件のみか）

公開イベント = **1件のみ**（ID130 TWICEライブ、出典eplus）。原因は複合的:

| # | 原因 | 実測根拠 |
|---|---|---|
| ① | **e-plus経由が事実上0件** | `popup_event_fetcher` のevent取得が直近0件（popup=kbuzzlabばかり）。sitemap自体は取得OK（34KB/266URL/2秒）だが、URLが `/sf/detail/0000900001` のID羅列で**タイトルからK-POP/イベント判定不可** → 266 detailページを全展開する重い処理 → 90秒タイムアウト → 0件 |
| ② | **韓国ニュース経由は告知に不向き** | `auto_event_article.py` は trend_signals.jsonl（korean_media 75件）からイベント語(콘서트等16件)を拾うが、「コンサートを**終えた**」等の過去報道が多く、未来の告知イベントが少ない。dry-run実測=記事化候補1件のみ |
| ③ | **`auto_event_article.py` が kpop-bot 401 + 週次cron未配線** | WP_USER='kpop-bot'(不在ユーザー)平文ハードコードで投稿401。かつ popup_event_weekly.sh から呼ばれていない孤立コード。→ **認証は .env kpop-publisher に修正済(2026-05-25)** |
| ④ | **チケット販売サイト(ぴあ/e-plus/チケットボード)を実質使えていない** | イベント告知の本丸を収集源にできていない＝最大の機会損失 |

## 2. 収集ソースの取得可否（robots/feed 実測）

規約・robots.txt 遵守が前提（既存方針 citation-only / USER_AGENT明示）。

| ソース | robots/feed | 取得可否 | 性質 |
|---|---|---|---|
| **e-plus** sitemap_daily_kkn.xml | robots で sitemap 公開 | ✅ 可（要バッチ化） | 日本の公演。ID羅列で要detail展開 |
| **PRTIMES** index.rdf | Allow / | ✅ 200（既存） | K-POPイベントのプレスリリース告知 |
| **ぴあ** t.pia.jp | robots 302リダイレクト | ⚠ 要追加調査 | 日本の主要チケット |
| **チケットボード** | robots 取得不可（この環境から） | ⚠ 要追加調査 | 日本の主要チケット |
| **interpark**(韓国) tickets.interpark.com | robots 200 | ✅ 可（要精読） | 韓国公演の一次。NOL改称に注意 |
| **melon ticket**(韓国) | robots 423 | ❌ 拒否 | 使わない |

## 3. 設計方針（実装は次段階）

### 3-1. レーン別の収集源
- **日本公演**: e-plus（sitemap → K-POP判定 → detail精読）+ PRTIMES（RSS、告知プレスリリース）。チケットボード/ぴあは robots 確認後に追加判断。
- **韓国公演**: interpark(NOL) の robots 許可範囲。melon は不可。

### 3-2. e-plus を機能させる修正（①の根治）
- sitemap 266 URL を**全展開しない**。detail ページ取得を「前回未処理の差分のみ」かつ**1回あたり上限N件**にバッチ化し、タイムアウトを防ぐ。
- detail ページの構造化データ（公演名・日時・会場・出演者）から K-POP 判定。アーティスト名辞書(translation_dict.json の person_group)でフィルタ。

### 3-3. 投稿先と品質
- The Events Calendar の `tribe_events` CPT に登録（日時・会場が構造化される）。
- 認証は .env kpop-publisher（kpop-bot 平文は全廃。speedrun/cta で確立済みパターン）。
- **未来の開催イベントのみ**（過去報道は除外）。出典リンク必須（citation）。robots/規約遵守。
- ステマ/アフィリ: イベント記事は travel/concert ジャンルで A8(airtori_hotel/airtori_plus/ikkyu_hotel 等=遠征の宿泊・交通)と相性良。cta_genre_map の event_concert ジャンルが既に該当プログラムを持つ。

## 4. 既に着手した修正
- `pipeline/auto_event_article.py` の認証を kpop-bot 平文 → .env kpop-publisher に修正（401解消）。ただし韓国ニュース経由は告知性が弱いため、これ単体では件数は伸びない。

## 5. 次段階の実装候補（優先順）
1. **e-plus collector のバッチ化修正**（①根治、規約OKの確実な日本ソース）。
2. PRTIMES の event 判定強化（既存だが popup に偏っている）。
3. ぴあ/チケットボードの robots 精査 → 可なら追加。
4. interpark(韓国) の robots 許可範囲で韓国公演収集。
5. 収集 → tribe_events 投稿 → イベントカレンダー表示の一連を週次cron化（popup_event_weekly に event を正式配線）。

> 関連メモリ: [[jp-popup-event-coverage-gap]]（popup全32件韓国・日本popupゼロ・eventは薄い）、
> [[kbuzzlab-popup-dom-contract]]（popup側の実装）、[[breaking-cadence-3h-window-match]]（認証 .env パターン）。
