---
name: ui-polish
description: WordPress・Webサイトの既存UIを100点完成度まで磨き上げる**ゲートスキル**。Lighthouse・元サイト一致度・モバイル動作・アクセシビリティの4軸を**Lighthouse + Pa11y 両方**で客観計測し、**実測ベース**でCSS・レイアウト・タイポグラフィの修正タスクを生成する。「UIを磨きたい」「Lighthouseスコアを上げたい」「Pa11y違反を直したい」「a11y改善」「100点を目指す」「元サイトに近づけたい」「サイトをブラッシュアップ」「コントラスト問題」「モバイル動作改善」といった問い合わせ時に必ず使用。**推測ではなく実測で主犯特定**→修正→再計測のループ。frontend-design・design:design-critique・design:accessibility-review は連携先(役割分担明示)。
---

# UI Polish

## 1. 目的

「動いている UI」を「100点動いている UI」に引き上げる。担当者の主観
(「いい感じ」)ではなく、**4軸の客観評価**で完成度を判定する。
各軸のスコアは [[100point-rubric-judge]] の A項目(UI磨き・4点満点)に
投入し、ルーブリック判定とつなげる。

## 2. 100点判定 4軸

### 軸1: Lighthouse スコア(自動測定)

| カテゴリ | 100点 | 95点 | 90点 |
|---|---|---|---|
| Performance | 95+ | 90+ | 85+ |
| Accessibility | 100 | 95+ | 90+ |
| Best Practices | 100 | 95+ | 90+ |
| SEO | 100 | 95+ | 90+ |

### 軸2: 元サイト一致度(視覚比較)
元サイトのスクリーンショットと現状を比較。ヘッダー・ナビ・配色・
フォント・レイアウトの主要要素一致率が **80%以上で 100点**。

### 軸3: モバイル動作(実機/エミュレーション検証)
- タッチ操作がスムーズ
- ハンバーガーメニューが動作
- 横スクロールの不具合なし
- フォントサイズの可読性
- 速報バーがレスポンシブ

### 軸4: アクセシビリティ(WCAG 2.1 AA)
`design:accessibility-review` で監査。color contrast 4.5:1 以上 /
alt 属性完備 / キーボード操作可能 / ARIA ラベル適切。

## 3. KPOP JOURNAL 特化ルール

### 配色(変更不可)
- メインピンク `#E91E63` / ダークピンク `#C2185B` / 薄ピンク `#FCE4EC`
- テキスト `#2B2B32` / グレー `#b8889a`

### レイアウト
- コンテナ幅 1200px / サイドバー 右側・幅30%
- 速報バー: ヘッダー直下・固定 40px
- 記事カードグリッド: PC 3列 / モバイル 1列

### タイポグラフィ
- 見出し Noto Sans JP Bold / 本文 Noto Sans JP Regular
- 行間 1.7 / 本文 16px / 見出し 20-32px

## 4. 改善優先順位ルール

影響度 × 工数 のマトリクスで優先順位を決める:
- 高影響 × 低工数 → 即実装(優先1)
- 高影響 × 高工数 → 計画実装(優先2)
- 低影響 × 低工数 → ついで対応(優先3)
- 低影響 × 高工数 → 後回し or 廃案

KPOP JOURNAL の重点ポイント(影響度の高い順):
1. ヘッダー(常時表示・第一印象)
2. 速報バー(動的・ブランド体験)
3. 記事カード(コンテンツの顔)
4. 個別記事ページ(SEO + 滞在時間)
5. サイドバー(導線)
6. フッター(信頼性)
7. モバイル全般(トラフィックの過半)

## 5. frontend-design との分担

- **frontend-design**: 新規UIの創造的設計・ブランド表現・
  アニメーション・革新的レイアウト。
- **ui-polish(本スキル)**: 既存UIの改善・磨き・4軸客観評価・
  パフォーマンス最適化・アクセシビリティ準拠・レスポンシブ完成。

連携フロー: frontend-design で草案 → ui-polish で4軸評価 →
不足点を frontend-design に戻す → 反復で100点へ。

## 6. 子テーマ CSS との連動

実装先は GeneratePress 子テーマ `generatepress-kpop`:
- 配色変数: `style.css` の `:root` セクション(1元管理)
- レイアウト・機能別CSS: `style.css` の各セクション末尾に追加

影響範囲の管理:
- 既存セレクタを変更する前に `grep` で使用箇所を確認する。
- **速報バー CSS には触らない**(独立して維持)。
- 配色は `:root` の変数のみで管理し、ハードコードを増やさない。

## 7. 検証コマンド(実装後)

### いますぐ使える(導入済みスキル)
- 軸4 アクセシビリティ: `design:accessibility-review` で監査。
- 軸3 モバイル動作: `webapp-testing`(Playwright)で実機検証・
  スクリーンショット取得。

### 要セットアップ(未導入 — 使う前に導入が必要)
```bash
# Lighthouse(軸1)— 未インストール
npm install -g lighthouse
lighthouse https://stg.kpopjournal.tokyo/ --output html \
  --output-path /tmp/lighthouse_report.html --chrome-flags="--headless"

# Pa11y(軸4 補助)— 未インストール
npm install -g pa11y
pa11y https://stg.kpopjournal.tokyo/ --standard WCAG2AA --reporter cli
```

### 未実装(将来作成するヘルパスクリプト)
- 視覚比較 `visual_compare.py` — 軸2。元スクショとの差分。**未作成**。
- モバイル検証 `mobile_test.py` — 軸3。複数デバイス。**未作成**。
- 当面、軸2 は `webapp-testing` のスクリーンショットを
  `original_screenshots/` と目視比較し、軸3 は `webapp-testing` の
  デバイスエミュレーションで代替する。

> 注: ステージングは Basic認証下にあるため、外部ツール実行時は
> 認証情報の受け渡しが必要。

## 8. 改善タスク生成フォーマット(JSON)

```json
{
  "task_id": "ui-polish-001",
  "page": "/",
  "axis": "lighthouse_performance",
  "current_score": 85,
  "target_score": 95,
  "gap_analysis": ["LCP 3.2s (target <2.5s)", "画像 lazy loading 未実装"],
  "actions": [
    {
      "priority": 1,
      "description": "ヒーロー画像に loading='eager' + fetchpriority='high'",
      "files": ["子テーマ functions.php"],
      "estimated_time": "30min"
    }
  ]
}
```

## 9. 100点達成プロセス(4 Phase)

- **Phase 1 現状計測(約15分)**: Lighthouse 全カテゴリ / アクセシビリティ /
  視覚比較 / モバイルエミュレーションを実行し、4軸の現状スコアを記録。
- **Phase 2 ギャップ分析(約15分)**: 各軸の目標との差を数値化し、
  改善タスクを §4 の優先順位で並べ、工数を算出。
- **Phase 3 実装(可変)**: 高優先タスクから順次。各タスク完了後に
  該当軸を**再計測**してスコアを更新する。
- **Phase 4 100点判定(約10分)**: 全4軸を再計測 → [[100point-rubric-judge]]
  を呼び、A項目に投入 → 達成なら100点宣言、未達なら次ループへ。

## 10. 100point-rubric-judge との連動

A項目(UI磨き・4点満点)への対応:

| A項目 | 基準 | 充足条件 |
|---|---|---|
| A-1 | 元サイト一致度 80%+ | 軸2 達成で 1点 |
| A-2 | Lighthouse Performance 90+ | 軸1 達成で 1点 |
| A-3 | Lighthouse Accessibility 95+ | 軸1 + 軸4 達成で 1点 |
| A-4 | モバイル動作完璧 | 軸3 達成で 1点 |

軸4(WCAG アクセシビリティ)は独立した点を持たず、A-3 に統合する
(Lighthouse Accessibility と WCAG 監査は同じ「アクセシビリティ」軸の
自動測定と詳細監査であり、両者そろって A-3 を満たすと判定する)。

## 11. 出力ルール

- 報告は **4軸スコア + 主要ギャップ + 次の改善タスク3件** のみ。
- Lighthouse の詳細レポートは要求されたときだけ出す。
- 推定スコアと実測スコアを区別する。計測前のスコアは「(推定)」と
  明記し、Phase 1/4 では必ず実測する。
- 4軸が未計測のまま「100点」と宣言しない。
