# Trend Collector 診断レポート — 2026-04-23

## 1. 現在の監視ソース一覧

### trend_collector.py (Phase 8) — データ収集層

| Source | Status | 実動状況 |
|--------|--------|----------|
| RSS: Soompi | enabled | フィード取得可能（英語、K-Pop/K-Drama） |
| RSS: Koreaboo | enabled | フィード取得可能（英語） |
| RSS: AllKPop | enabled | フィード取得可能（英語） |
| RSS: KpopStarz | enabled | フィード取得可能（英語） |
| RSS: Natalie Music (JP) | enabled | フィード取得可能（日本語、music全般） |
| X (Twitter) API v2 | enabled | **実質停止** — bearer_token 未設定（後述） |
| YouTube Data API v3 | enabled | **実質停止** — YOUTUBE_API_KEY 未設定 |
| GSC Rising Queries | enabled | trend_predictor.py出力を読み取り（delegated） |

### trend_predictor.py (Phase 4) — スコアリング・注入層

| Source | Status | 実動状況 |
|--------|--------|----------|
| GSC Rising Queries | active | service_account.json経由で直接API呼出 |
| X (Twitter) Trends | active | `claude --no-session-persistence`でWebSearch依存 |
| Google Trends | active | `claude --no-session-persistence`でWebSearch依存 |

### competitor_monitor.py — 競合監視（別系統）

| Source | Status | 実動状況 |
|--------|--------|----------|
| kstyle.com | HTML scrape | 30分間隔で監視中 |
| daebak.tokyo | RSS | 30分間隔で監視中 |

### cron 実行スケジュール

- `05:35` — trend_predictor.py（Phase 4 pipeline経由）
- `06:30` — trend_collector.py（Phase 8）
- `毎30分 6-21時` — competitor_monitor.py

---

## 2. 過去7日間の HYBE/BTS/BIGBANG/ARIRANG 検出カウント

### trend_predictions.jsonl（trend_predictor.py出力）

| 日付 | 総予測数 | GSC Rising | X Trends | Google Trends | HYBE/BTS/BIGBANG/ARIRANG検出 |
|------|---------|------------|----------|---------------|------|
| 04-17 | 0 | 0 | 0 | 0 | **0** |
| 04-18 | 0 | 0 | 0 | 0 | **0** |
| 04-19 | 0 | 0 | 0 | 0 | **0** |
| 04-20 | 0 | 0 | 0 | 0 | **0** |
| 04-21 | 4 | 4 | 0 | 0 | **2** (bts 仲良し 相関図, ジミン 熱愛 認める) |
| 04-22 | 0 | 0 | 0 | 0 | **0** |
| 04-23 | 0 | 0 | 0 | 0 | **0** |

**7日間合計: 2件のみ（4/21のGSC経由のみ）。X/Google Trends経由は7日間ゼロ。**

### data/trend_signals.jsonl（trend_collector.py出力）

**0行 — ファイルは空。trend_collector.pyの出力が一度も書き込まれていない。**

### trend_collector.log

**ファイル自体が存在しない。trend_collector.pyが一度も正常実行されていない可能性が高い。**

---

## 3. 検出漏れ・非公開の原因分析

### 原因 A: trend_collector.py が実質的に全ソース停止状態

1. **X (Twitter) API: bearer_token 未設定**
   - `~/.x_credentials`にはOAuth 1.0a keys (`api_key`, `api_secret`, `access_token`, `access_token_secret`) のみ存在
   - trend_collector.pyが必要とする`bearer_token`が未設定のため、`collect_x_trends()`は毎回「graceful skip」
   - API v2のRecent Search endpointにはBearer Tokenが必須

2. **YouTube API: YOUTUBE_API_KEY 未設定**
   - 環境変数`YOUTUBE_API_KEY`が設定されていない
   - `collect_youtube()`は毎回「graceful skip」

3. **RSS: 動作可能だが、ログファイルが存在しない**
   - trend_collector.logが存在しないため、RSSが実際に動いたかも不明
   - cronでは`>> logs/trend_collector.log`に出力指定あるが、相対パスで書かれており `cd ~/kpop-ai-system` の後に実行されるため問題ないはず
   - ただし**出力ファイル（data/trend_signals.jsonl）が空**であることから、RSS収集も何らかの理由で0件（フィード取得エラーか、キーワードマッチ0件の可能性）

### 原因 B: キーワードリストの致命的欠落

`_extract_kpop_keywords()`はRSS記事タイトルからK-POPキーワードを抽出するが、以下の重要キーワードが**完全に欠落**:

**欠落している企業・レーベル名:**
- HYBE, BIGHIT, YG Entertainment, SM Entertainment, JYP Entertainment, Starship, Pledis, KOZ

**欠落している業界用語:**
- ARIRANG（番組名/アルバム名）, Weverse, 東京ドーム, ドーム公演, ワールドツアー
- 活動再開, 完全体, ソロデビュー, ソロ活動, ファンクラブ

**欠落している新世代アーティスト:**
- ILLIT, KATSEYE, ZEROBASEONE (ZB1), BOYNEXTDOOR, xikers, PLAVE, TWS, KISS OF LIFE

**欠落している日本語表記バリエーション:**
- ストレイキッズ, セブンティーン, トゥワイス, ニュージーンズ, ルセラフィム
- 房時赫, パン・シヒョク（HYBE代表）

### 原因 C: trend_predictor.py のシグナル収集がほぼ全滅

7日間のうち6日で**3ソース全て0件**。原因:
- **GSC Rising**: サイトのインプレッション規模が小さく、急上昇クエリが閾値（impressions >= 20, growth >= 2.0x）を超えない日が多い
- **X Trends / Google Trends**: `claude --no-session-persistence -p`による外部情報取得に依存。Claude CLIのWebSearch能力に完全依存しており、レスポンスがJSON配列でない場合は0件になる。**成功率が極めて低い**

### 原因 D: trend_collector.py と trend_predictor.py の連携不全

- trend_collector.pyはdata/trend_signals.jsonlに書き込む
- trend_predictor.pyはdata/trend_signals.jsonlを**読まない**（独自にGSC/X/GTを収集する独立系統）
- trend_collector.pyの出力を活用するパスが事実上存在しない（GSC rising readerのみが唯一の接点だが、trend_predictor.pyの出力を逆読みするだけ）

### 原因 E: RSSフィードのキーワードフィルタが厳しすぎる

- RSS記事は`_extract_kpop_keywords()`でK-POPキーワードが**1つも見つからなければ完全スキップ**
- 「HYBE経営陣刷新」「K-POP事務所の上場」等の業界ニュースは、アーティスト名が含まれない限り全て破棄される

---

## 4. 欠落している重要ソース

### 日本語メディア（日本向けK-POP情報の主力）
| ソース | 重要度 | RSS | 備考 |
|--------|--------|-----|------|
| **Kstyle** | 最重要 | なし（HTML scrape必要） | competitor_monitorでは監視中だがtrend_collectorに未統合 |
| **Wowkorea** (wowkorea.jp) | 高 | RSS有 | 韓流総合、速報性高い |
| **ORICON NEWS K-POP** | 高 | RSS有 | チャート・来日公演情報 |
| **modelpress K-POP** | 高 | RSS有 | エンタメ+ファッション |
| **Billboard Japan** | 高 | RSS有 | チャート権威 |
| **Kpopmonster** | 中 | RSS有 | 日本語K-POP専門 |

### 韓国語メディア（一次ソース）
| ソース | 重要度 | RSS | 備考 |
|--------|--------|-----|------|
| **Yonhap (聯合ニュース)** | 最重要 | RSS有 | 韓国通信社、速報性最高 |
| **中央日報 (日本語版)** | 高 | RSS有 | 韓国大手メディア日本語版 |
| **朝鮮日報 (日本語版)** | 高 | RSS有 | 同上 |
| **Sports Seoul** | 中 | RSS有 | 芸能専門 |
| **Dispatch** | 中 | なし | スクープ系（HTML） |

### 公式プラットフォーム
| ソース | 重要度 | 方式 | 備考 |
|--------|--------|------|------|
| **Weverse Magazine** | 高 | RSS/HTML | HYBE系公式コンテンツ |
| **Melon Magazine** | 中 | HTML | 韓国最大音楽プラットフォーム |

---

## 5. 推奨修正事項

### P0（即時対応 — 1日以内）

#### 5-1. X (Twitter) bearer_token の設定
- `~/.x_credentials`に`bearer_token`フィールドを追加
- Twitter Developer Portalでbearer_tokenを発行し設定
- **なければtrend_collector.pyのX収集は永久に停止のまま**

#### 5-2. _KPOP_ARTISTS / _KPOP_TERMS のキーワード拡充
```python
# 追加すべきアーティスト
"ILLIT", "KATSEYE", "ZEROBASEONE", "ZB1", "BOYNEXTDOOR",
"xikers", "PLAVE", "TWS", "KISS OF LIFE", "tripleS",
"FIFTY FIFTY", "Billlie", "Kep1er",

# 追加すべき企業・レーベル
"HYBE", "BIGHIT", "YG", "SM Entertainment", "JYP",
"Starship", "Pledis", "KOZ", "ADOR", "Source Music",

# 追加すべき業界用語
"ARIRANG", "Weverse", "東京ドーム", "ドーム", "ワールドツアー",
"活動再開", "完全体", "ソロデビュー", "ソロ活動",
"Melon", "Bugs", "Genie", "Hanteo", "Circle Chart",
"Coachella", "フェス", "来日", "日本公演",

# 日本語表記バリエーション
"ストレイキッズ", "セブンティーン", "ニュージーンズ", "ルセラフィム",
"エスパ", "アイヴ", "イルリット", "房時赫", "パン・シヒョク",
```

#### 5-3. trend_collector.py の実行確認・ログ出力修復
- cronの実行ログを確認し、実際にRSSフィードが取得できているかテスト
- `python3 lib/trend_collector.py --dry-run` で動作確認

### P1（短期対応 — 1週間以内）

#### 5-4. 日本語メディアRSSの追加（trend_sources.json）
```json
{"id": "wowkorea", "name": "Wowkorea", "url": "https://www.wowkorea.jp/rss/news.xml", "language": "ja", "priority": "high"},
{"id": "oricon_kpop", "name": "ORICON NEWS", "url": "https://www.oricon.co.jp/news/rss/", "language": "ja", "priority": "high"},
{"id": "modelpress_kpop", "name": "modelpress", "url": "https://mdpr.jp/rss/", "language": "ja", "priority": "medium"},
{"id": "billboard_japan", "name": "Billboard Japan", "url": "https://www.billboard-japan.com/feed", "language": "ja", "priority": "high"}
```

#### 5-5. 韓国主要メディアRSSの追加
```json
{"id": "yonhap_jp", "name": "聯合ニュース日本語版", "url": "https://jp.yna.co.kr/RSS/culture.xml", "language": "ja", "priority": "high"},
{"id": "chosun_jp", "name": "朝鮮日報日本語版", "url": "https://www.chosunonline.com/site/data/rss/rss.xml", "language": "ja", "priority": "medium"},
{"id": "joongang_jp", "name": "中央日報日本語版", "url": "https://japanese.joins.com/rss/joins_culture_list.xml", "language": "ja", "priority": "medium"}
```

#### 5-6. competitor_monitor.py の検出結果をtrend_collectorに統合
- competitor_monitor.pyが検出した記事をdata/trend_signals.jsonlにも追記するか、trend_predictor.pyが competitor_article_queue.jsonl を読むパスを追加

#### 5-7. キーワードフィルタの緩和
- 現在: K-POPキーワードが1つもなければ完全スキップ
- 改善案: 韓国メディアソースからのRSSは、K-POPカテゴリなら無条件通過させるフィルタモードを追加

### P2（中期対応 — Phase 10 Track S設計基盤）

#### 5-8. trend_predictor.py のClaude CLI依存脱却
- `claude --no-session-persistence`経由のWebSearchは成功率が低い（7日間で1/7日のみ成功）
- 代替案: Google Trends RSS、Twitter API v2直接呼出、NewsAPI等の確実なAPIに移行

#### 5-9. 編集会議（edit_council）エージェントの新設
- trend_collectorの検出結果を人間判断に近い優先度で仕分けるエージェント
- 「速報」「解説記事向き」「コラム向き」「スキップ」の4段階分類
- auto_directivesへの注入前に編集判断を挟む

#### 5-10. 収集頻度の最適化
- 現在: 1日1回（06:30）のみ
- 推奨: 速報系ソース（Yonhap, allkpop）は2-3時間おき、解説系は1日1回
- cron追加: `0 9,12,15,18 * * * python3 lib/trend_collector.py --source rss`

---

## 6. Phase 10 Track S 設計基盤

### 目標: 「主要K-POPニュースの見逃しゼロ」

#### アーキテクチャ案

```
[Source Layer]
  RSS feeds (15+ sources) ──┐
  X API v2 (bearer_token) ──┤
  YouTube API v3 ───────────┤
  GSC Rising Queries ───────┤
  competitor_monitor output ─┘
           │
           ▼
[Collector Layer] trend_collector.py
  - 拡張キーワードDB (config/trend_keywords.json)
  - ソースごとの信頼度重み付け
  - 重複排除 (URL + タイトル類似度)
           │
           ▼
[Scoring Layer] trend_predictor.py
  - multi-signal buzz score
  - artist_master.json 連携（所属事務所→関連記事紐付け）
  - 既存記事との重複チェック
           │
           ▼
[Editorial Layer] edit_council (新設)
  - 速報 / 解説 / コラム / スキップ の分類
  - カテゴリ・担当エージェント自動割当
  - 安全フィルタ（skip_keywords連携）
           │
           ▼
[Execution Layer]
  - auto_directives.json 注入
  - パイプライン自動起動（速報記事は即時）
  - Discord通知
```

#### trend_keywords.json（新設提案）
- artist_master.json から自動同期するアーティスト名リスト
- 事務所名、番組名、イベント名、会場名の辞書
- 日本語/韓国語/英語の表記ゆれマッピング
- trend_collector.py の `_extract_kpop_keywords()` はこのJSONを参照

#### 収集タイムライン案
- `05:30` — trend_predictor.py（GSC + Claude WebSearch）
- `06:00` — trend_collector.py 第1回（全ソースRSS + X API）
- `09:00, 12:00, 15:00, 18:00` — trend_collector.py 追加回（RSS のみ）
- `毎30分` — competitor_monitor.py（既存）
- `21:00` — 日次トレンドサマリー生成 + Discord送信

---

## 付録: 検証コマンド

```bash
# trend_collector.py の動作テスト
cd ~/kpop-ai-system && python3 lib/trend_collector.py --dry-run

# X credentials の確認
python3 -c "import json; d=json.load(open('$HOME/.x_credentials')); print('bearer_token' in d)"

# YouTube API Key の確認
echo "${YOUTUBE_API_KEY:-NOT_SET}"

# trend_signals.jsonl の内容確認
wc -l data/trend_signals.jsonl
tail -5 data/trend_signals.jsonl

# trend_predictions.jsonl の最新レコード
tail -1 logs/trend_predictions.jsonl | python3 -m json.tool
```
