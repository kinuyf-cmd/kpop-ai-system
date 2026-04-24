# PIXTA API 統合提案書
**日時**: 2026-04-23
**ステータス**: 調査完了 — 最終判断はオーナーに委ねる
**結論**: PIXTA APIは法人営業ベース（即時導入不可）。代替として Unsplash/Pexels 即時有効化を推奨

---

## 1. 背景・課題

### 現状のサムネソース解決能力

| ソース | concrete記事 | abstract記事 | 稼働状況 |
|--------|-------------|-------------|---------|
| YouTube MV thumbnail | 対応（アーティスト名マッチ） | 非対応 | **稼働中** (5件キャッシュ) |
| Wikimedia Commons | 対応（アーティスト名マッチ） | 非対応 | **稼働中** (23件キャッシュ) |
| Unsplash | 対応（ジャンル検索） | 対応（ジャンル検索） | **停止** (APIキー未設定) |
| Fallback cache | 対応（キャッシュ済み画像） | 非対応 | 稼働中 |
| AI prompt | プロンプト生成のみ | プロンプト生成のみ | 画像生成なし |

### 具体的な問題
- **抽象記事（声帯ケア、振付師、ファッション分析etc）でサムネ解決率 0%**
  - Phase 9.5 A-2 で 3938, 3932 がSKIPした直接原因
- DALL-E 3等のAI画像生成はプロンプトのみ保存、実行パスなし
- Unsplashはアジア系/K-POP系の画像が極めて少ない

---

## 2. PIXTA API 概要

*（調査結果反映予定 — 以下は既知情報ベースの設計）*

### PIXTAの利点（K-POPメディア向け）
- 日本最大級のストックフォト（7,000万点+）
- **日本語タグ完全対応**（他社は英語のみ）
- **アジア人モデル・日本の日常風景が圧倒的に充実**
- 商用利用・Web掲載・SNS投稿が標準ライセンスに含まれる
- 業種別・シーン別の細かいタグ体系

### Unsplash/Pexelsとの比較

| 項目 | Unsplash | Pexels | PIXTA |
|------|----------|--------|-------|
| 日本語検索 | 不可 | 不可 | **対応** |
| アジア人モデル | 少 | 少 | **豊富** |
| K-POP関連 | ほぼなし | ほぼなし | 韓国カテゴリあり |
| 商用利用 | 無料 | 無料 | **有料** |
| 品質管理 | ユーザー投稿 | ユーザー投稿 | **審査済み** |
| API日本語タグ | なし | なし | **あり** |

---

## 3. 統合設計

### 3-1. resolver優先順位（PIXTA統合後）

```
concrete記事 (アーティスト特定可):
  1. YouTube MV thumbnail     ← 変更なし
  2. Wikimedia Commons         ← 変更なし
  3. Fallback cache            ← 順位UP（無料ソースを先に消費）
  4. PIXTA API search          ← NEW
  5. AI prompt (最終手段)      ← 変更なし

abstract記事 (汎用トピック):
  1. PIXTA API search          ← NEW（最大の改善点）
  2. Unsplash (バックアップ)   ← 無料枠を2番目に
  3. AI prompt (最終手段)      ← 変更なし
```

### 3-2. キャッシュ戦略

```
assets/
  artist_cache/          ← 既存（YouTube/Wikimedia/Unsplash）
    index.json
    yt_*.jpg
    wiki_*.jpg
  pixta_cache/           ← NEW
    index.json           ← {query_hash: {pixta_id, path, license, expires_at}}
    pixta_{id}_{hash}.jpg
```

- **キャッシュキー**: 検索クエリのSHA256ハッシュ
- **TTL**: 30日（PIXTAの利用規約に準拠）
- **重複回避**: 同一pixta_idは再ダウンロードしない

### 3-3. resolve_pixta() 関数設計

```python
def resolve_pixta(query: str, orientation: str = "landscape") -> dict | None:
    """
    Search PIXTA API for a stock photo matching the query.
    
    Requires: PIXTA_API_KEY environment variable
    
    Args:
        query: Search terms (Japanese OK)
        orientation: "landscape" (1200x630 thumbnail用)
    
    Returns:
        {
            "image_path": "/path/to/cached/pixta_12345_abc.jpg",
            "source": "pixta",
            "source_url": "https://pixta.jp/photo/12345",
            "license": "PIXTA Standard License",
            "attribution": "PIXTA ID: 12345",
            "pixta_id": "12345",
        }
    """
```

### 3-4. Claude Haiku タグ生成プロンプト

記事タイトル/本文 → PIXTAに最適な英語+日本語検索タグを生成。

```python
PIXTA_TAG_SYSTEM_PROMPT = """あなたはストックフォト検索の専門家です。
記事のタイトルと本文から、PIXTAで最適な写真を見つけるための検索タグを生成してください。

ルール:
1. 日本語タグと英語タグを両方生成（PIXTAは両方対応）
2. 抽象的すぎるタグは避け、具体的なシーン・被写体を指定
3. K-POP/韓国エンタメ記事の場合、「韓国」「ソウル」等の地域タグを追加
4. 人物が必要な場合、年齢層・性別・シチュエーションを明示
5. 横向き（landscape）のサムネに適した構図を意識

出力形式（JSON）:
{
  "primary_query": "メイン検索クエリ（日本語、最も重要な2-3語）",
  "secondary_query": "英語での検索クエリ",
  "tags_ja": ["日本語タグ1", "タグ2", ...],
  "tags_en": ["english tag1", "tag2", ...],
  "preferred_style": "documentary|portrait|landscape|abstract|closeup",
  "requires_person": true/false,
  "age_range": "20s-30s" or null,
  "mood": "energetic|calm|professional|dramatic|warm"
}"""

PIXTA_TAG_USER_TEMPLATE = """以下の記事にマッチするPIXTA検索タグを生成してください:

タイトル: {title}
本文冒頭: {body_excerpt}
ジャンル: {genre}
"""
```

#### タグ生成例

| 記事タイトル | primary_query | tags_ja | preferred_style |
|-------------|--------------|---------|----------------|
| なぜ喉を壊さない？K-POPアイドル声帯ケア極意 | ボイストレーニング マイク | ["歌手", "マイク", "スタジオ", "レコーディング", "練習"] | documentary |
| K-POP振付師フォーメーション設計の全真実 | ダンス 練習室 | ["ダンサー", "練習室", "鏡", "振付", "グループ"] | documentary |
| 声優 補助金の全ガイド | 声優 スタジオ 録音 | ["声優", "マイク", "スタジオ", "収録", "プロフェッショナル"] | professional |

---

## 4. A/Bテスト案

### テスト設計

| グループ | サムネソース | 対象記事 |
|---------|------------|---------|
| A (PIXTA) | PIXTA API検索 | 抽象記事5件（次回公開分） |
| B (現行) | 現行resolver（YouTube/Wiki/gradient fallback） | 抽象記事5件（次回公開分） |

### 評価指標

| 指標 | 測定方法 | 期間 |
|------|---------|------|
| Vision validation score | thumbnail_vision_validator.py | 即時 |
| テキスト混入率 | OCR check (score内) | 即時 |
| 実写真率 | source metadata | 即時 |
| CTR (Google Search Console) | GSC API | 7日後 |
| OGP SNSクリック率 | X analytics | 3日後 |

### テスト手順

1. 次の10記事（抽象トピック）をランダムにA/Bに振り分け
2. A群: `THUMB_SOURCE_OVERRIDE=pixta` 環境変数で強制PIXTA
3. B群: 通常フロー
4. 7日後にCTR比較 → オーナーに結果提示

### コスト見積もり

| 項目 | 単価 | A/Bテスト5件 | 月間100件 |
|------|------|-------------|----------|
| PIXTA API検索 | 無料 (検索のみ) | ¥0 | ¥0 |
| PIXTA画像DL (Sサイズ) | ~¥500/枚 | ~¥2,500 | ~¥50,000 |
| PIXTA画像DL (Mサイズ) | ~¥1,500/枚 | ~¥7,500 | ~¥150,000 |
| PIXTA定額プラン (月10枚) | ~¥6,380/月 | - | ¥6,380 |
| PIXTA定額プラン (月100枚) | ~¥16,500/月 | - | ¥16,500 |
| Claude Haiku タグ生成 | ~$0.001/回 | ~$0.005 | ~$0.10 |

*（正式料金はAPI調査結果で更新）*

### 推奨: 定額プラン月100枚 (¥16,500/月)
- 1記事1枚 × 月30記事 = 月30枚（余裕あり）
- キャッシュヒットで実使用量はさらに減少
- Unsplash(無料)は引き続きバックアップとして維持

---

## 5. 実装ロードマップ（オーナー承認後）

| Phase | 内容 | 工数 |
|-------|------|------|
| 5-1 | PIXTA API契約・キー取得 | オーナー作業 |
| 5-2 | `resolve_pixta()` 実装 + キャッシュ層 | 2時間 |
| 5-3 | Claude Haiku タグ生成 integration | 1時間 |
| 5-4 | `thumbnail_source_resolver.py` 優先順位変更 | 30分 |
| 5-5 | A/Bテスト実行 (5件 × 2グループ) | 1日 |
| 5-6 | CTR比較・レポート | 7日後 |

---

## 6. リスク

| リスク | 対策 |
|--------|------|
| PIXTA API が公開APIを提供していない | Unsplash復活 + Pexels追加で代替 |
| 月額コストがROIに見合わない | 無料枠(Unsplash/Pexels)を先に有効化、PIXTAは必要時のみ |
| 検索精度が低い（タグミスマッチ） | Claude Haikuのタグ生成で高品質クエリを保証 |
| ライセンス違反 | source_url/license/attribution をメタデータに必ず記録（既存の _log_source 活用） |

---

**最終判断はオーナーに委ねます。**
v6の現行実装は中断しておらず、本提案は並行調査のみです。
