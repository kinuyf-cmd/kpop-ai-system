---
name: x-posting-rules
description: KPOP JOURNAL の X(旧Twitter)投稿ルール + 自動投稿スキル。X アルゴリズム最新仕様(2026/5/15 GitHub 公開)準拠で text-first 設計、conversation 起点投稿、active engagement フロー、Premium 4x boost を統合。「X投稿」「Twitter投稿」「SNS配信」「ツイート」「自動投稿」「ハッシュタグ」「会話起点」「リプライ運用」といった問い合わせ時に必ず使用。100点計画 Q項目の達成に必須。
---

# X Posting Rules

## 1. 目的

X(旧 Twitter)経由の SNS 流入を最大化する。X アルゴリズム最新仕様
(2026/5/15 更新、github.com/xai-org/x-algorithm)に準拠した
text-first 設計で、エンゲージメント単価の高い投稿フォーマットに統一する。
100点計画 Q項目の達成が狙い。

## 2. X アルゴリズム最新仕様(2026/5/15 更新)

### 2-1. ランキング weight(like=0.5 基準。2026-05-26 実値に更新)
GitHub公開アルゴ + 解説の集計値。**旧版の「返信=150/RT=20/like=1」は誤り**だった。
- **返信に著者が返信** = **+75**(like の約150倍相当=最重要、最大の boost)
- **直接返信** = **+13.5**(like の約27倍)
- **プロフィール訪問+エンゲージ** = **+12**
- **リンク2分以上閲覧** = **+10〜11**(記事誘導の価値=リンククリックは高い)
- **ブックマーク** = **+10**
- 引用 = +5(賛否含む)
- **リツイート** = **+1**(like の約2倍。旧版20は誤り)
- **like** = **+0.5**(基準)
- 動画50%視聴 = +0.005(ほぼ無視)
- **ミュート/ブロック/「表示を減らす」** = **−74**(強ネガティブ)
- **報告(report)** = **−369**(破滅的)

### 2-1b. 時間減衰(最重要・実運用に直結)
- **最初の15〜30分が勝負**(15分で10返信を得るとバイラル増幅カスケード)
- 6時間で可視性スコア約半減、24時間後はほぼ0
- → 投稿直後の返信対応(engagement watch +10/30/60分)が拡散を左右する

### 2-2. Premium account 算法上の優位
- in-network(フォロワー)投稿 = **4x boost**
- out-of-network(非フォロワー)投稿 = **2x boost**
- 平均リーチ 6-10倍(中規模アカウント)

### 2-3. text-first / フォーマット別(実値に更新)
- **text-only は返信/imp 率が最高**(エンゲージ率トップ)
- **スレッドは単発比 +40〜60% imp**(記事誘導はフック→要点→URLの3段スレッド推奨)
- 画像は text 比 2倍の imp 乗数(ただし返信率は text-only が上)
- **非Premium の本文 URL は中央値エンゲージ0まで悪化**(本文URL厳禁、URLは最終リプライ段のみ)
- Grok センチメント分析、ポジティブ寄りのみ拡散

### 2-4. 4 コンポーネント
- **Home Mixer**: フィード合成・オーケストレーション
- **Thunder**: in-network ポストのインメモリ格納
- **Phoenix**: **Grokベースの ranker**(19アクションの確率予測。検索/トレンドだけでない)
- **Candidate Pipeline**: in-network / out-of-network 両 retrieval の候補生成

## 3. 投稿フォーマット(text-first 設計)

### 3-1. 本文構造
- **120-180字推奨**(140字未満より 120-180 字の中規模本文が伸びる)
- **URL は本文に含めない**(suppression 回避、別途リプライで添付)
- フック → 感情行 → コメント誘導 の 3 行構造(v13.0 既存設計を継承)
- 改行 2回まで(過剰改行は readability 低下)

### 3-2. ハッシュタグルール
- **最大 3 個まで**(4個以上は spam 判定リスク)
- 必須: `#KPOP`
- アーティスト名: `#BTS` `#BLACKPINK` 等
- トレンド連動: 該当アーティストがトレンド入り時のみ追加

### 3-3. 投稿例(text-only、URL なし)
```
速報、BTS が音源チャート1位を獲得 🎵
レコード会社の戦略変化を示唆していて、業界全体が注目している

あなたはこの転換、どう見ますか? #KPOP #BTS
```
↑ 本文 122字、ハッシュタグ 2 個、URL なし、コメント誘導あり

## 4. URL 添付ポリシー(suppression 回避)

### 4-1. 推奨パターン(text-first + リプライで URL)
1. 元ツイート: text-only(URL なし、120-180字)
2. 元ツイートへの **セルフリプライ**: URL のみ + 短い説明
3. 1時間経過後にエンゲージメント測定

### 4-2. ABテスト(オプション、Q 採点後実施)
- パターン A: 元ツイート(text-only)+ セルフリプライで URL
- パターン B: 元ツイート(text-only)+ 別投稿で URL(時差15分、Q-4 メトリクスで比較)
- 1週間運用で勝ちパターンに固定

## 5. conversation 起点フォーマット集(K-POP 特化、8案)

返信に返信 = like 150個分 = 最重要 weight。
ゆえに「コメント誘発する投稿」が最も伸びる。
以下 8 種類を K-POP 特化テンプレとしてデータ化:

| ID | テンプレ | 例 | カテゴリ |
|---|---|---|---|
| C-1 | あなたの推しグループは? | 「3世代と4世代、どっち推しですか?」 | 意見集約 |
| C-2 | 新曲評価分かれ | 「新曲の評価、賛否分かれてますね、皆さんは?」 | 対立喚起 |
| C-3 | 世代比較 | 「BTS と新人グループ、音楽性どっち好み?」 | 世代論 |
| C-4 | 世界進出戦略 | 「BTS と BLACKPINK、世界進出の戦略違いますね」 | 分析 |
| C-5 | カムバ期待 | 「カムバ予定のあのグループ、楽しみですか?」 | 期待感 |
| C-6 | ファン層変化 | 「ファン層の年齢構成、変わってきてますね」 | 社会論 |
| C-7 | チャート分析 | 「韓国チャート vs グローバルチャート、傾向違う」 | データ分析 |
| C-8 | MV視聴行動 | 「あの MV、何回見ました?」 | 視聴行動 |

実装は `lib/x_conversation_starter.py` のテンプレ JSON で管理(LLM 失敗時のフォールバック)。

### 5b. ペルソナ LLM 生成(2026-05-26 〜 標準。テンプレ使い回しの根治)

**背景:** 上記 8 テンプレ×2 パターンを `{artist}` 差し替えで再利用していたため、
「AI 感丸出し」「同じコメントの使い回し」(例: 同じ MV 文をアーティスト名だけ変えて
2 時間で再投稿)が発生。オーナー指示で **投稿1件ごとに LLM で毎回生成**する方式へ移行。

**方針:**
- 「K-POP 好きな等身大ライター」を **複数の声(ペルソナ)で使い分ける**。1人の人間が
  日々違う気分でつぶやく感を出す。声色は `lib/x_persona_voice.py` の `PERSONAS`:
  - `oshi` 感情ダダ漏れオタク / `kosen` 落ち着いた古参 / `light` ライト層 / `yuru` ゆる自虐
- 会話起点(URL なし純つぶやき)・記事フックの双方で `generate_persona_post()` を使用。
- **テンプレ使い回し禁止**: 毎回ちがう語彙・構文・切り口。固定の「型」を作らない。
- **Anti-repeat**: 直近 `logs/x_posts.jsonl` 本文をプロンプトに渡し被りを禁止、
  生成後も先頭一致/禁止語を検出したら 1 回再生成 → なお駄目ならテンプレ退避。
- **禁止語**(`x_persona_voice.FORBIDDEN`): 旧テンプレ語「何回見ましたか」「賛否分かれ」、
  engagement bait「どう思う?」「教えてください」、煽り「衝撃の事実」、meta「本記事では」等。
- **純つぶやき混在**: 記事 URL を一切持たない日常つぶやきも投げ、宣伝臭を薄める。
- **ハルシネーション防止**: 記事フックは本文抜粋に基づく感想に留め、ソースに無い
  固有名詞・数値を創作しない。会話は意見・感想ベースで事実断定しない。

**有効化:** 環境変数 `X_PERSONA_LLM=1`(+ `OPENAI_API_KEY`)。未設定/失敗時は
従来テンプレ/タイトルへ自動フォールバック(投稿は止めない)。gpt-4o-mini、コストは
`logs/x_tweet_llm.jsonl` に計上。**本番反映前にサンプルをオーナー確認**してから `.env` 有効化。

**注意(ハッシュタグ):** アーティスト名タグは `lib/x_post_templates.build_hashtags` に統一
(スペース除去)。テンプレの `#{artist}` がスペースを残す `#Stray Kids` 事故は両経路で修正済み。

## 6. active engagement フロー

X アルゴリズム上「返信に著者が返信 = like 150 個分」のため、
投稿後の能動的な engagement が拡散を左右する。

### 6-1. モニタリング
- 投稿後 **10分 / 30分 / 60分** で返信モニタリング(`lib/x_engagement_responder.py`)
- インプレッション・エンゲージメント数を 10 分毎に取得
- 目標値(Premium 想定 1000 imp / 1時間)未達なら Discord 通知

### 6-2. 返信運用(オーナー承認フロー)
1. 返信検出 → Claude API で **返信候補 3 案生成**
2. owner-decision-queue に X-REPLY-{timestamp}.json として投入
3. Discord 通知(候補3案表示、承認 ID で返信)
4. オーナー承認後、X API で返信投稿(投稿ログを sanitize_log.jsonl 形式で記録)

### 6-3. 自動応答の禁止
- 著者の文体・判断を AI 単独に委ねない(オーナー方針継続)
- 「正確性最優先、ハルシネーション最小化」厳守
- 自動投稿は元本文のみ、返信はオーナー承認後に限る

## 7. 投稿時刻(3回/日)

- 朝 **7:00**(出勤前、in-network ピーク)
- 夕方 **17:00**(帰宅時間、暖簾投稿)
- 夜 **21:00**(就寝前、エンゲージメント率高)
- 速報は即時(Premium で 4x boost が活きる)

## 8. 自動投稿スクリプト

### 8-1. 既存資産
- `google_metrics/post_to_x.py`: OAuth 1.0a 投稿(投稿そのもの)
- `lib/x_post_templates.py`: v13.0 4ジャンル + フック構造(本文生成)
- `lib/x_pre_score.py`: 100点プレフライト採点(80点以上のみ投稿)
- `lib/x_post_audit.py`: 投稿後監査

### 8-2. M10 新規追加
- `lib/x_conversation_starter.py`: §5 の8会話フォーマットから text-only 投稿を生成
- `lib/x_engagement_responder.py`: §6 active engagement フロー(返信候補生成・owner_queue 投入)

### 8-3. 認証情報
- `~/.x_credentials`(JSON、permissions 600)
- Premium account 取得後、同ファイルに追記(`premium: true` フラグ)

## 9. Communities 投稿(Day 9 以降)

K-POP コミュニティ参加 → 既存 X 投稿パイプラインに community_id パラメータ追加。
各コミュニティの投稿規約に応じた条件分岐。Day 9 朝の Premium 取得後に着手。

## 10. 投稿頻度ルール

- 1日最大 5 投稿(過剰投稿で algo 抑制)
- 同じアーティストの連続投稿を避ける
- 自社サイトリンクが投稿の過半を超えない(spam 判定回避)
- conversation 起点 / 速報 / 記事誘導 のバランス: 5:3:2 推奨

## 11. センチメント配慮(Grok ポジティブ拡散)

- 炎上・批判系の投稿は **ポジティブ転換** してから投稿
- 例: 「あの炎上事件、酷い」→「あの件、議論が活発で K-POP コミュニティの成熟を示している」
- 否定形より肯定形(「○○ない」→「○○ある」)
- ネガティブワード自動検知 + 言い換え候補は `lib/x_pre_score.py` に追加予定

## 12. 100point-rubric-judge Q項目との連動

| Q項目 | 基準 | 判定方法 |
|---|---|---|
| Q-1 | x-posting-rules skill 完成 | スキル存在 + X アルゴリズム最新仕様反映 |
| Q-2 | 自動投稿動作 | conversation_starter / templates の dry-run + テスト投稿 |
| Q-3 | 投稿時刻 3回/日 | crontab 0 7,17,21 * * * 設定確認 |

## 13. 安全設計

- 誤投稿防止に `--dry-run` モードを設ける
- 投稿前にコンテンツ確認(センシティブワード検出、`lib/x_pre_score.py`)
- X API のレート制限を遵守する
- 投稿は削除可能な状態を維持する(`delete_x_post.sh` 既存)
- 返信は必ずオーナー承認(自動返信禁止)
- API key は ~/.x_credentials のみ、ログ・コードに残さない

ログ: `~/.kpop_recovery/x_posting_log.jsonl`

## 14. M-final 申し送り(本番化前)

1. Premium $8/月 取得 → ~/.x_credentials に `premium: true` 追記
2. X Developer API access 申請完了(Basic でも投稿可能)
3. Communities 参加完了 → community_id を ~/.x_communities.json に登録
4. 本番1ヶ月運用後、Q 採点見直し(累計実測根拠):
   - エンゲージメント率(目標 5%+)
   - リーチ数(Premium 4x boost 検証)
   - 返信 → 著者返信 → エンゲージメント連鎖の効果測定
5. URL 添付ポリシー ABテスト勝ちパターン固定
6. センチメント NG ワード辞書拡充

## 15. M10 ABテスト(2026-05-28〜)

直近5投稿の実測で imp 平均 5.4 と低迷、原因切り分けのためA/B並走を開始。

### 設計
- **variant A(現行)**: LLMペルソナ(8人架空ライター、感情的独り言、絵文字署名「💐ももか💐」等、ハッシュタグ3個)
- **variant B(新)**: Pop Crave型 faceless aggregator(`_llm_tweet_body` 流用、中立速報、数値・固有名詞、署名なし、ハッシュタグ2個 #KPOPJOURNAL #KPOP)
- **割当**: `pipeline/x_scheduled_poster.py` で `post_id % 2 == 0 → A / else B` 交互
- **ログ**: `logs/x_ab_log.jsonl`(ts/tweet_id/variant/post_id/title/genre/mode)
- **集計**: `venv_kpi/bin/python tools/x_ab_summary.py --since 72h`
- **判定窓**: 72h 投稿数 各variant 10件以上で imp/エンゲージ率の差を比較。差が明確ならskill方針更新+勝者で固定

### 画像同梱(2026-05-28〜、両variant共通)
- v1.1 media/upload 実装(`google_metrics/post_to_x.upload_media`)、`post_tweet(..., media_ids=[...])` で添付
- WP featured_media→large/medium_largeサイズ優先→bytes取得→upload→tweet
- featured_media未設定の記事は text-only にフォールバック(致命にしない)
- ABの公平性: 両variantとも画像同梱条件で比較

### 関連
- 実装: `lib/x_poster.py`(variant引数, _fetch_and_upload_featured), `google_metrics/post_to_x.py`(upload_media)
- 集計: `tools/x_ab_summary.py`
