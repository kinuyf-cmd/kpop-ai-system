# サムネイル命令書

## 基本原則（Phase 9 確定）

### テキストゼロ
- サムネイルにテキストを焼き込まない
- タイトルはWP/OGPタグで表示（ブラウザ・SNS側の責任）
- draw_text / font_load 系関数は v6 で完全撤去

### 実写真優先
- K-POP記事の主役はアーティスト。AI生成画像ではなく実写真を使う
- 固有名詞記事（concrete）: 実写真必須
- 抽象記事（abstract）: AI画像許可（韓国ドキュメンタリー調）

## 画像ソース優先順位

### 1. YouTube公式MVサムネイル
- `config/official_accounts.json` の youtube_video_ids から取得
- maxresdefault.jpg（1280x720）
- 最もアーティストらしい画像が得られる

### 2. Wikimedia Commons
- `assets/artist_cache/index.json` でローカルキャッシュ管理
- CC BY-SA ライセンス
- attribution 記録必須

### 3. Unsplash/Pexels 実写真
- UNSPLASH_ACCESS_KEY 環境変数が必要
- 「kpop {artist}」で検索
- 商用利用OK

### 4. フォールバック実写真（JUDGE_Q1=B）
- 同アーティストの別画像（cache内の別ファイル）
- 同グループメンバー個別画像
- 「見つからない時の代替」を必ず用意

### 5. AI画像生成（abstract記事のみ）
- プロンプト: `config/ai_image_prompt_template.json`
- スタイル: 韓国ドキュメンタリー調
- カメラ: Fujifilm X-T5, 35mm f/1.4, 自然光
- 被写体: 20-30代韓国人、自然な質感、修正なし
- ネガティブ: 完璧な肌、AIアート、スタジオ撮影、グラマーショット

## Vision品質検証（JUDGE_Q2=A）

### スコアリング（0-100点）
| 項目 | 配点 | 内容 |
|------|------|------|
| 画像サイズ | 20点 | 1200x630に近いほど高評価 |
| ファイルサイズ | 20点 | 200KB以上で満点 |
| ファイル名マッチ | 30点 | アーティスト名がファイル名に含まれるか |
| ソース種別 | 30点 | 実写真=30, AI生成=20, gradient=0 |

### 判定基準
- 90点以上: **PASS** — 公開OK
- 80-89点: **RETRY** — 別ソースで再試行（最大3回）
- 80点未満: **HARD_FAIL** — フォールバック実写真に切替、それも不可ならYuta承認キュー

## 出力仕様
- サイズ: 1200 x 630 px（OG image標準）
- フォーマット: JPEG quality=95 / WebP quality=92
- 処理: リサイズ → センタークロップ → コントラスト微調整（1.05x）→ 明度微調整（1.02x）

## 実装ファイル
| ファイル | 役割 |
|---------|------|
| `lib/make_thumbnail_v6.py` | 統合エントリポイント |
| `lib/article_topic_classifier.py` | concrete/abstract 判定 |
| `lib/thumbnail_source_resolver.py` | 画像ソース解決（v2） |
| `lib/thumbnail_compositor.py` | 画像加工（compose_v6） |
| `lib/thumbnail_vision_validator.py` | 品質検証 |
| `config/concrete_vs_abstract.json` | トリガー辞書 |
| `config/ai_image_prompt_template.json` | AIプロンプト |
| `config/official_accounts.json` | 公式アカウントDB |
| `assets/artist_cache/` | ローカル画像キャッシュ |

## 安全装置
- `THUMB_LAYOUT=v5_legacy` 環境変数で旧版に戻せる
- `data/thumbnail_sources.jsonl` に全ソース記録（著作権追跡）
