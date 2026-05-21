# KPOP Journal AI Company — 運営ランブック v1.0
**作成: 2026-04-09 / 担当: ポリゴンZ (SRE)**

---

## 組織憲法：全エージェントが守るべき行動原則

```
かけふまわす
  か = 稼ぐ（収益最大化）
  け = 削る（無駄排除）
  ふ = 防ぐ（誤投稿・品質低下を防ぐ）
  ま = 回す（計測→分析→改善のループを止めない）

行動原則
  1. 自立して動け — 人間に確認せず判断し実行する
  2. 止めるな — パイプラインは24時間止まらない
  3. 計測しろ — 数字なき改善は惰性
  4. 壊れたものを出すな — 品質基準未満はアルセウスが止める
  5. 同じミスを繰り返すな — watchdogが検知し自動修復する
```

---

## 日次オペレーションスケジュール

| 時刻 | 担当 | アクション |
|------|------|----------|
| 06:00 | cron | Google Analytics/GSCメトリクス取得 |
| 07:00 | cron | kpop_pipeline.sh（速報記事） |
| 07:30 (月) | cron | チャートランキング記事 |
| 09:00 | ミュウツー(CFO) | CEO Morning Brief → Discord送信 |
| 10:00 | cron | 前日記事の初動パフォーマンス計測 |
| 11:00 | cron | kpop_pipeline.sh（美容・コスメ記事） |
| 12:00 | cron | kpop_strategy_pipeline.sh（資産記事） |
| 15:00 | cron | kpop_pipeline.sh（旅行・ライフスタイル記事） |
| 18:00 | cron | kpop_pipeline.sh（ファッション記事） |
| 21:00 | AI全エージェント | 日次運営会議 → Discord送信 |
| 毎時0・30分 | ポリゴンZ | watchdog監査・自動修復 |

---

## 日次運営会議フロー（21:00）

```
Section 1: 情報収集
  バタフリー → 今日のK-POPトレンド5件（WebSearch）
  ラプラス   → SEOキーワード戦略
  ミミッキュ → 競合分析・差別化
  ジラーチ   → 未来バズ予測

Section 2: 編集長決定
  ミュウツー → 全レポート統合 → 明日の方針・各エージェントへの指示

Section 3: 制作指示分配
  デオキシス → 速報記事制作（ミュウツー指示に従う）
  メタモン   → CTRリライト（デオキシス記事を改善）
  ニャース   → 収益導線設計（ジャンル別アフィリエイト・CTA配置）

Section 4: SRE監査
  ポリゴンZ → パイプライン稼働状況・自動修復実績・未解決問題報告

Section 5: 品質最終審査
  アルセウス → 全エージェント採点（100点満点）・投稿判定・改善命令

Section 6: パフォーマンス分析
  ポリゴン → 今週のKPIトレンド・ボトルネック・ルギアへのインプット

→ Discord #daily-ceo-report に送信
```

---

## 各エージェントの役割・責任・KPI

### 経営層
| エージェント | 役割 | KPI |
|------------|------|-----|
| アルセウス (arceus) | CEO・全体監督・最終品質承認 | 投稿承認精度 > 95%、品質スコア80点以上の記事のみ公開 |
| ミュウツー (mewtwo) | 編集長・CFO・戦略統括 | 日次方針の具体性、コスト管理、明日テーマの適切さ |

### 記事制作部
| エージェント | 役割 | KPI |
|------------|------|-----|
| デオキシス (deoxys_kpop) | 速報記事ライター | HTML品質、タイトルCTR予測、文字数2000字以上 |
| メタモン (metamon_kpop) | CTRリライト担当 | タイトル3案生成、CTR改善率 > 10% |
| フシギバナ (venusaur) | SEO記事設計 | H2見出し構成、キーワード密度 |
| ジラーチ (jirachi_kpop) | ファクトチェック | 時制誤り・事実誤認ゼロ |

### マーケティング・分析部
| エージェント | 役割 | KPI |
|------------|------|-----|
| バタフリー (butterfree) | トレンド情報収集 | 毎日5件以上の有効ネタ供給 |
| ラプラス (lapras) | SEOキーワード戦略 | 月次検索流入前月比 > +5% |
| ミミッキュ (mimikyu) | 競合分析 | 差別化角度の具体性 |
| ジラーチ (jirachi_kpop) | 未来バズ予測 | 予測的中率（月次評価） |
| ペルシアン (persian) | X投稿最適化 | IMP・エンゲージメント率 |
| ソーナンス (wobbuffet) | 読者ニーズ分析 | 記事滞在時間・回遊率 |

### 収益化部
| エージェント | 役割 | KPI |
|------------|------|-----|
| ニャース (meowth) | アフィリエイト・収益導線設計 | RPM > 500円、CVR > 1% |
| カビゴン (snorlax) | レビュー・比較記事 | CVR > 1.5%、クリック率 > 3% |
| フリーザー (articuno) | SNSバズコンテンツ | シェア数 > 10RT/記事 |

### インフラ・SRE部
| エージェント | 役割 | KPI |
|------------|------|-----|
| ポリゴンZ (porygon_z) | 全パイプライン監視・自動修復 | 稼働率 >= 95%、障害→修復 <= 30分 |

### 改善・戦略部
| エージェント | 役割 | KPI |
|------------|------|-----|
| ポリゴン (porygon) | 週次パフォーマンス分析 | 改善提案の具体性・採用率 |
| ルギア (lugia) | 中長期戦略・来週方針 | 戦略の一貫性・収益貢献 |

---

## 自動修復3種（watchdog）

| トリガー | 修復アクション |
|---------|--------------|
| フェイルセーフ誤発動（X投稿履歴 < 3件） | x_failsafe.jsonl に解除ログ追記 |
| パイプラインログが4時間以上更新なし（活動時間内） | パイプラインを自動再起動 |
| title_performance.jsonlに同一post_idが重複3件以上 | 重複レコードを自動削除 |

---

## 品質チェックフロー（記事1本）

```
1. デオキシスが記事生成
2. メタモンがCTRリライト・タイトル3案
3. ジラーチがファクトチェック
4. post_guard.py が自動検査（タイトルなし/質問文/HTML破損/文字数不足/英字比率超過 → BLOCK）
5. arceus_scoring.py がスコア採点（50点満点、45点以上で合格）
6. アルセウスが最終承認（投稿OK/要修正/投稿停止を判定）
7. WordPress投稿 → サムネイル生成 → X投稿 → SEOインデックス申請
```

---

## サムネイルジャンル判定ルール（v3.2）

| テーマキーワード | ジャンル | デザイン |
|--------------|--------|--------|
| 旅行/ソウル/カフェ/聖地巡礼/ポップアップ | travel | 緑テーマ・SEOUL文字・グラデ背景 |
| ファッション/着用/ブランド/即完売/コーデ | fashion | 紫テーマ・FASHION文字・グラデ背景 |
| コスメ/スキンケア/美容/ガラス肌 | beauty | 白ピンク・BEAUTY文字・グラデ背景 |
| カムバック/新曲/デビュー | comeback | 紫青ネオン |
| チャート/ランキング/Billboard/1位 | chart | 黒ゴールド |
| ライブ/コンサート/ツアー/来日 | live | オレンジピンク |
| 速報/緊急/判明/電撃/炎上 | breaking | 赤黒・ストライプ |

**travel/fashion/beautyはwikimedia画像不使用**（無関係画像防止）

---

## 月次KPI目標

| 指標 | 現状 | 目標（3ヶ月） |
|------|------|------------|
| 月間PV | 計測中 | 10,000 PV |
| 平均CTR | 計測中 | 3%以上 |
| AdSense RPM | 計測中 | 500円以上 |
| 月間収益 | 計測中 | 30,000円 |
| 記事投稿数 | 〜5本/日 | 4〜6本/日（安定） |
| X投稿成功率 | 計測中 | 90%以上 |
| パイプライン稼働率 | 計測中 | 95%以上 |

---

*このランブックはポリゴンZ（SRE）が管理する。問題発生時はwatchdog → Discord #urgent_errors に自動通知される。*

---

## カニバリゼーション標準対応フロー (v1.0 — 2026-04-10)

### カニバリとは
同一クエリに対して自サイトの複数URLがGoogle検索に出現し、流入を食い合う状態。
症状: 同クエリで2記事ともCTR低下・順位が不安定に揺れる。

---

### STEP 1: 検知

**自動検知（週次 weekly_review.sh）**
```
detect_noindex_candidates.sh が同一キーワードで複数記事を検出
→ logs/cannibal_candidates.log に記録
→ Discord #seo_alerts に通知
```

**手動確認（GSC）**
```
1. GSC → 検索パフォーマンス → 「クエリ」タブ
2. 問題クエリを選択 → 「ページ」タブに切り替え
3. 同クエリに2URL以上が表示 → カニバリ確定
```

---

### STEP 2: 判定（統合 or 差別化）

| 条件 | 判断 |
|------|------|
| 記事AとBの内容が70%以上重複 | **統合** → 上位URLに全コンテンツを集約 |
| 記事AとBが検索意図レベルで違う | **差別化** → タイトル・H2構成を見直し |
| 一方が明らかに古い/薄い | **統合** → 古い方を301リダイレクト後にnoindex |
| 両方とも独自情報がある | **差別化** → 内部リンクで補完関係を明示 |

**判定ルール（迷ったら統合を選ぶ）**:
- 主要クエリが3語以上一致 → 統合
- 表示回数の少ない方が上位記事の1/3未満 → 統合

---

### STEP 3-A: 統合（メインフロー）

```bash
# 1. 残すURL（新）と消すURL（旧）を決定
#    原則: 表示回数・流入・コンテンツ量が多い方を「新」に残す

# 2. 新URLに旧記事のコンテンツ・内部リンクを移植
#    WordPressで旧記事の本文を新記事に追記し更新

# 3. .htaccess に301を追加
echo 'Redirect 301 /旧スラッグ/ https://ドメイン/新スラッグ/' >> /var/www/html/.htaccess

# 4. 旧URLにnoindexタグを追加（301後も念のため）
#    WordPress管理画面 or Yoast: robots → noindex

# 5. GSCでインデックス再通知
bash google_metrics/request_index.sh "https://ドメイン/新スラッグ/"

# 6. GSC削除ツールで旧URLのキャッシュを申請
#    GSC → 削除 → 一時的な削除 → 旧URL入力
```

---

### STEP 3-B: 差別化（サブフロー）

```bash
# 1. 記事Aのターゲットクエリを「情報クエリ」に絞る
#    例: 「BTS とは」「BTS 歴史」

# 2. 記事Bのターゲットクエリを「トランザクションクエリ」に絞る
#    例: 「BTS アルバム 最新」「BTS グッズ 買い方」

# 3. タイトル・descriptionをそれぞれ書き換え
bash google_metrics/update_titles_and_meta.sh POST_ID_A "新タイトルA"
bash google_metrics/update_titles_and_meta.sh POST_ID_B "新タイトルB"

# 4. A→Bへの内部リンクを追加（補完関係を明示）
bash google_metrics/add_internal_links.sh POST_ID_A POST_ID_B

# 5. GSCで両URLを再通知
bash google_metrics/request_index.sh "https://ドメイン/記事A/"
bash google_metrics/request_index.sh "https://ドメイン/記事B/"
```

---

### STEP 4: 経過監視

統合・差別化ともに以下のKPIを確認する。

| タイミング | 確認項目 | 合格基準 |
|----------|---------|---------|
| 対応翌日 | GSCで新URLがインデックス登録済みか | 登録済み |
| 7日後 | 旧URLの流入が統合前の30%以下か | 30%以下 |
| 14日後 | 新URLの表示回数が統合前の合計の80%以上か | 80%以上 |
| 30日後 | 対象クエリで旧URLが消えているか / CTR改善 | 旧URL消滅・CTR +5%以上 |

---

### STEP 5: 記録と再発防止

```bash
# logs/cannibal_resolved.log に記録
echo "$(date '+%Y-%m-%d') 統合: /旧URL/ → /新URL/ (2214統合対応)" \
  >> logs/cannibal_resolved.log

# 新規記事作成時の確認を generate_similar_articles.sh に組み込み済み
# → 同クエリの既存記事がある場合は警告を出力する
```

**再発防止チェックリスト（新規記事作成前）**
- [ ] GSCで同クエリに既存記事がないか検索
- [ ] `generate_similar_articles.sh` で類似記事リストを確認
- [ ] ターゲットクエリが既存記事と3語以上一致しないか確認
- [ ] 一致する場合は「差別化 or 統合」を先に判断してから記事作成

---

## エージェント管理台帳（2026-04-11 整理完了）

### 本番使用中エージェント（cron自動実行パイプラインに組み込み済み）

| エージェント | ファイル | 使用パイプライン | 役割 |
|------------|---------|--------------|------|
| deoxys_kpop | agents/deoxys_kpop.md | kpop_pipeline.sh | SEO記事本文生成 |
| metamon_kpop | agents/metamon_kpop.md | kpop_pipeline.sh | メタ情報・タイトル生成 |
| eevee | agents/eevee.md | kpop_pipeline.sh | 記事品質チェック |
| jirachi_kpop | agents/jirachi_kpop.md | kpop_pipeline.sh / kpop_strategy_pipeline.sh | アイキャッチ画像生成 |
| arceus | agents/arceus.md | kpop_pipeline.sh / kpop_strategy_pipeline.sh | ファクトチェック・公開判断 |
| butterfree | agents/butterfree.md | kpop_strategy_pipeline.sh | 戦略記事トレンド収集 |
| lapras | agents/lapras.md | kpop_strategy_pipeline.sh | 戦略記事構成設計 |
| mimikyu | agents/mimikyu.md | kpop_strategy_pipeline.sh | 戦略記事本文生成 |
| wobbuffet | agents/wobbuffet.md | kpop_strategy_pipeline.sh | 戦略記事SEO最適化 |
| venusaur | agents/venusaur.md | kpop_strategy_pipeline.sh | 戦略記事品質チェック |
| alakazam_kpop | agents/alakazam_kpop.md | kpop_strategy_pipeline.sh | 戦略記事メタ生成 |
| gengar | agents/gengar.md | kpop_strategy_pipeline.sh | 戦略記事競合分析 |
| dragonite | agents/dragonite.md | kpop_strategy_pipeline.sh | 戦略記事内部リンク |
| persian | agents/persian.md | kpop_strategy_pipeline.sh | 戦略記事X投稿 |
| zapdos | agents/zapdos.md | kpop_chart_pipeline.sh | チャート記事生成 |
| kairyu_kpop | agents/kairyu_kpop.md | hub_article_post.sh | ハブ記事生成 |

### 手動専用エージェント（cron未接続・手動呼び出しのみ）

| エージェント | ファイル | STATUS | 用途 |
|------------|---------|--------|------|
| articuno | agents/articuno.md | MANUAL_ONLY | SNSバズ記事の手動依頼時に使用。cron接続禁止。 |

### 代替済み・停止扱いエージェント（DO_NOT_WIRE_IN_PRODUCTION: true）

| エージェント | ファイル | REPLACED_BY | 備考 |
|------------|---------|-------------|------|
| pidgeot | agents/pidgeot.md | kpop_pipeline.sh (deoxys_kpop) | SEO記事生成はdeoxys_kpopが代替済み |
| digitool | agents/digitool.md | post_to_wp.py | WordPress投稿はスクリプトが代替済み |
| chansey | agents/chansey.md | cron + kpop_master_scheduler.sh | タスク管理はcronが代替済み |
| regigigas_kpop | agents/regigigas_kpop.md | kpop_pipeline.sh (直接書き込み) | アーカイブはパイプラインが直接実行 |
| mewtwo_kpop | agents/mewtwo_kpop.md | kpop_master_scheduler.sh | コンテンツ戦略はスケジューラーが代替済み |

### 削除候補（将来の整理対象）

以下のファイルは現時点では削除せず、冒頭コメントで状態を明示している。
次回メジャー整理時（運用安定確認後）に削除を検討すること。

- `agents/pidgeot.md`
- `agents/digitool.md`
- `agents/chansey.md`
- `agents/regigigas_kpop.md`
- `agents/mewtwo_kpop.md`

### 「完全自律運用」判定

**判定: 条件付き達成**

| 条件 | 状態 |
|------|------|
| cronによる自動実行（8スロット/日） | 達成 |
| post_audit.sh による自律修正（最大3ループ） | 達成 |
| エージェント誤接続リスクの排除 | 達成（未使用エージェントにDO_NOT_WIRE_IN_PRODUCTION明記） |
| kpop_master_scheduler.sh のcron接続 | 未実施（二重投稿リスクのため意図的に保留） |
| 削除候補ファイルの物理削除 | 未実施（安全のため保留） |

運用上の自動化は完結している。`kpop_master_scheduler.sh` のcron接続と削除候補ファイルの物理削除は
既存cron構成との整合性確認後に別フェーズで実施する。


---

## 削除判定表（2026-04-11 実検索 → 物理削除済み）

### 検索スコープ
`/home/aiuser/kpop-ai-system/` 配下の `.sh`, `.py`, `.md`, `.txt`, `.json` 全ファイル（`.venv` 除外）

### 判定結果

| エージェント | 参照ファイル | 参照の種類 | 実行経路に乗るか | 最終判定 |
|------------|------------|-----------|--------------|---------|
| pidgeot | operations_runbook_v1.0.md のみ | ドキュメント（本台帳のみ） | No | **削除済み（2026-04-11）** |
| digitool | operations_runbook_v1.0.md のみ | ドキュメント（本台帳のみ） | No | **削除済み（2026-04-11）** |
| chansey | operations_runbook_v1.0.md のみ | ドキュメント（本台帳のみ） | No | **削除済み（2026-04-11）** |
| regigigas_kpop | operations_runbook_v1.0.md, pixel_viewer.py | runbook=台帳; pixel_viewer=AGENT_NAMES翻訳マップ → エントリ削除済み | No | **削除済み（2026-04-11）** |
| mewtwo_kpop | operations_runbook_v1.0.md, lib/claude_retry.py | runbook=台帳; claude_retry.py docstring → arceus に置換済み | No | **削除済み（2026-04-11）** |

### 参照詳細

**regigigas_kpop / pixel_viewer.py (line 49)**
```python
AGENT_NAMES = {
    ...
    "persian": "ペルシアン",   "regigigas": "レジギガス",
    ...
}
```
→ ログ表示用の翻訳辞書。`--agent regigigas` を呼び出すコードではない。
→ 物理削除後もpixel_viewerの動作に影響なし（ログに"regigigas"が現れなくなるだけ）。

**mewtwo_kpop / lib/claude_retry.py (line 8)**
```python
"""
Usage:
  from claude_retry import claude_run
  result = claude_run(prompt, agent="mewtwo_kpop", max_retries=3)
"""
```
→ docstringのUsage例。実行コードではない。実際の呼び出し側(rewrite_losers.py)はagent=未指定。
→ 物理削除後もclaude_retry.pyの動作に影響なし。

### 削除推奨順序

削除しても他ファイルへの影響がゼロである順に並べる。

1. **pidgeot.md** — 参照ゼロ（runbook自己参照のみ）
2. **digitool.md** — 参照ゼロ（runbook自己参照のみ）
3. **chansey.md** — 参照ゼロ（runbook自己参照のみ）
4. **mewtwo_kpop.md** — docstringサンプルのみ（claude_retry.py動作に影響なし）
5. **regigigas_kpop.md** — 翻訳マップのみ（pixel_viewer.py動作に影響なし）

※ pixel_viewer.py の AGENT_NAMES から "regigigas" エントリを削除するかは
  削除フェーズで合わせて判断すること（ログ表示の整合性）。

### 削除前チェックリスト（実行時に確認）

- [ ] `grep -r "pidgeot\|digitool\|chansey\|regigigas\|mewtwo_kpop" ~/kpop-ai-system --include="*.sh" -l` → 0件
- [ ] cronに `--agent pidgeot` 等の記述がないこと: `crontab -l | grep -E "pidgeot|digitool|chansey|regigigas|mewtwo_kpop"` → 0件
- [ ] 削除後に `kpop_pipeline.sh` / `kpop_strategy_pipeline.sh` のドライランが通ること


---

## 現役エージェント接続表（2026-04-11 実検索ベース）

### 検索スコープ
`--agent <name>` の実呼び出し箇所を全 `.sh`/`.py` から集計（`.venv`/`.bak` 除外）

### エージェント別 接続・分類表

| エージェント | 実呼び出し数 | 呼び出し元スクリプト | 役割 | 分類 | 統合候補 | 最小運用で残すか |
|------------|-----------|------------------|------|------|---------|--------------|
| deoxys_kpop | 9 | kpop_pipeline, kpop_strategy_pipeline, pipeline_with_trends, generate_similar_articles, timed_pipeline, agent_council, run_ai_meeting | SEO記事本文生成（breaking/strategy共通） | ACTIVE_RUNTIME | No | **Yes（コア）** |
| metamon_kpop | 3 | kpop_pipeline, kpop_strategy_pipeline, run_ai_meeting | メタ情報・タイトル生成 | ACTIVE_RUNTIME | No | **Yes** |
| eevee | 3 | kpop_pipeline, kpop_strategy_pipeline, agent_council | 記事品質チェック | ACTIVE_RUNTIME | No | **Yes** |
| jirachi_kpop | 4 | kpop_pipeline, kpop_strategy_pipeline, run_ai_meeting | アイキャッチ画像生成・ファクトチェック補助 | ACTIVE_RUNTIME | No | **Yes** |
| arceus | 4 | kpop_pipeline, kpop_strategy_pipeline, agent_council, run_ai_meeting | 最終公開判断（ゲートキーパー） | ACTIVE_RUNTIME | No | **Yes（コア）** |
| butterfree | 3 | kpop_strategy_pipeline, run_ai_meeting | 戦略記事トレンド収集 | ACTIVE_RUNTIME | laprasと役割近接 | Yes |
| lapras | 4 | kpop_strategy_pipeline, agent_council, run_ai_meeting | 戦略記事構成設計 | ACTIVE_RUNTIME | No | **Yes** |
| mimikyu | 4 | kpop_strategy_pipeline, agent_council, run_ai_meeting | 戦略記事本文生成 | ACTIVE_RUNTIME | No | **Yes** |
| wobbuffet | 1 | kpop_strategy_pipeline のみ | 戦略記事SEO最適化 | ACTIVE_RUNTIME | No | Yes |
| venusaur | 1 | kpop_strategy_pipeline のみ | 戦略記事品質チェック | ACTIVE_RUNTIME | eeveeと役割近接 | **REDUNDANT_CANDIDATE** |
| alakazam_kpop | 2 | kpop_strategy_pipeline, kpop_chart_pipeline | メタ情報生成（strategy/chart共通） | ACTIVE_RUNTIME | metamon_kpopと役割近接 | **REDUNDANT_CANDIDATE** |
| gengar | 2 | kpop_strategy_pipeline, agent_council | 競合分析・差別化 | ACTIVE_SUPPORT | No | Yes |
| dragonite | **0** | **なし（名前マップのみ）** | 内部リンク担当（想定）→ 実際はadd_internal_links.shが代替 | **REDUNDANT_CANDIDATE** | kairyu_kpopが内部リンク担当 | **No（未使用）** |
| kairyu_kpop | 1 | kpop_strategy_pipeline | 内部リンク挿入 | ACTIVE_RUNTIME | No | Yes |
| persian | 3 | kpop_strategy_pipeline, kpop_chart_pipeline, agent_council | X投稿生成 | ACTIVE_RUNTIME | No | **Yes** |
| zapdos | 1 | kpop_chart_pipeline のみ | チャート記事生成 | ACTIVE_RUNTIME | No | Yes（月1回） |

### 実行経路図

```
【cron 毎日】
  07:00 / 08:00 / 13:00 / 15:00 / 17:00 / 18:00 / 19:00
    └─ kpop_pipeline.sh
         deoxys_kpop → metamon_kpop → eevee → jirachi_kpop → arceus → [WordPress投稿]

  12:00
    └─ kpop_strategy_pipeline.sh
         butterfree → lapras → mimikyu → wobbuffet → jirachi_kpop → venusaur
         → mewtwo → deoxys_kpop → metamon_kpop → eevee → alakazam_kpop
         → gengar → kairyu_kpop → arceus → [WordPress投稿] → persian

  毎週月曜 07:30
    └─ kpop_chart_pipeline.sh
         zapdos → alakazam_kpop → [WordPress投稿] → persian

【cron 毎日 21:00】
    └─ run_ai_meeting.sh
         butterfree / lapras / mimikyu / jirachi_kpop / mewtwo / deoxys_kpop
         / metamon_kpop / arceus / porygon / porygon_z（SUPPORT系）

【cron 毎日 06:05】
    └─ auto_repair.sh → post_audit.sh（エージェント呼び出しなし・スクリプト自律修復）

【手動】
    └─ agent_council.sh
         deoxys_kpop / eevee / lapras / mimikyu / gengar / arceus / persian
```

### 重複役割の洗い出し

| 重複ペア | 役割の重複点 | 判定 |
|---------|-----------|------|
| venusaur ↔ eevee | どちらも記事品質チェック担当。venusaurはstrategy専用、eeveeは両pipeline | REDUNDANT_CANDIDATE: venusaur |
| alakazam_kpop ↔ metamon_kpop | どちらもメタ情報・タイトル生成。alakazamはstrategy/chart専用 | 役割分担は一応あり（pipeline別）|
| dragonite ↔ kairyu_kpop | 内部リンク担当が重複想定。dragoniteへの--agent呼び出しがゼロ | REDUNDANT_CANDIDATE: dragonite |
| butterfree ↔ deoxys_kpop | トレンド収集 vs 記事生成。役割は連続しており重複ではない | 重複なし |

### 重要発見: dragonite は事実上の未使用エージェント

`--agent dragonite` への呼び出しが **システム全体でゼロ件**。
- `kpop_strategy_pipeline.sh` の名前マップ（表示用辞書）にのみ登場
- 内部リンク挿入は `add_internal_links.sh`（スクリプト）と `kairyu_kpop` が担当
- `agents/dragonite.md` は存在するが、実行されたことがない状態

### 最小運用構成案（今回は削除・統合しない）

最小化した場合に削除・統合を検討できるもの:

1. **dragonite** — 呼び出しゼロ。前フェーズの「削除候補5体」と同様の状態。次フェーズで削除判定対象
2. **venusaur** — eeveeで代替可能。strategy_pipelineの品質チェックをeeveeに統合できる
3. **alakazam_kpop** — metamon_kpopとの役割整理次第で統合候補

現行16体のうち実質稼働しているのは **15体**（dragoniteを除く）。


---

## dragonite 削除判定（2026-04-11 実検索ベース）

### 検索スコープ
`.sh` / `.py` / `.md` / `.json` / `.txt` 全ファイル（`.venv` / `.bak` / `operations_runbook` 除外）

### 参照の分類

| 参照ファイル | 参照箇所 | 参照の種類 | 実行経路に乗るか |
|------------|---------|-----------|--------------|
| `kpop_strategy_pipeline.sh:36` | `["カイリュー"]="dragonite"` | 表示名辞書（Bashの連想配列） | **No**（ログ表示用。`--agent dragonite` 呼び出しなし） |
| `pixel_viewer.py:48` | `"dragonite": "カイリュー"` | AGENT_NAMES翻訳辞書 | **No**（ログ表示用） |

- `--agent dragonite` への呼び出し: **システム全体でゼロ件**
- crontab: **ゼロ件**
- `agents/dragonite.md`: **ファイル自体が存在しない**（すでに削除済み）

### agents/dragonite.md の存在確認

```
$ ls /home/aiuser/kpop-ai-system/agents/ | grep dragon
（出力なし）
```

**`agents/dragonite.md` はすでに存在しない。** 前フェーズ（5体削除）の対象外だったが、
ファイルがない状態であるため「物理削除」は不要。残作業は参照のクリーンアップのみ。

### kairyu_kpop との役割差分

| 観点 | dragonite | kairyu_kpop |
|-----|-----------|-------------|
| agents/ファイル | **存在しない** | `agents/kairyu_kpop.md`（存在） |
| `--agent` 呼び出し | **ゼロ件** | `kpop_strategy_pipeline.sh:520`（実稼働） |
| 担当役割 | 内部リンク挿入（想定）| CVR・回遊導線（CTA挿入・関連記事誘導・SNSシェア促進・H2強化） |
| 実行結果 | なし | `reports/13_final.md` を生成（pipeline本流） |

→ kairyu_kpop は dragonite の「内部リンク」とは別に、CVR最適化という独自役割を担っている。
→ dragoniteは役割定義ファイル自体がなく、代替の必要性もない。

### 最終判定

**DELETE_OK** — ただし agents/dragonite.md はすでに存在しない。

残クリーンアップ対象（次フェーズで実施）:
1. `kpop_strategy_pipeline.sh:36` — 表示名辞書から `["カイリュー"]="dragonite"` を削除
2. `pixel_viewer.py:48` — `AGENT_NAMES` から `"dragonite": "カイリュー"` を削除

これらはログ表示用エントリのみであり、削除しても実行動作に影響なし。


---

## dragonite 完全削除完了（2026-04-11）

### 実施内容

| 対象 | 操作 | 削除内容 |
|-----|------|---------|
| `agents/dragonite.md` | 確認 | すでに不在（前フェーズ以前に削除済み） |
| `kpop_strategy_pipeline.sh:36` | 削除済み | `["カイリュー"]="dragonite"` エントリ除去 |
| `pixel_viewer.py:48` | 削除済み | `"dragonite": "カイリュー"` エントリ除去 |

### 削除後の残参照検索結果

| スコープ | 結果 |
|---------|------|
| .sh（.venv/.bak除外） | **ZERO** |
| .py（.venv除外） | **ZERO** |
| .json | **ZERO** |
| .md（runbook除く） | **ZERO** |
| crontab | **ZERO** |

### 最終状態

- **FILE**: absent（`agents/dragonite.md` 不在）
- **CODE REFERENCES**: zero（`--agent dragonite` 呼び出しゼロ、辞書エントリも削除済み）
- **DOC REFERENCES**: runbook管理記録のみ（本台帳内の経緯記録として保持）

### 結論

dragonite は完全削除完了。runbook以外でのdragonite文字列はゼロ。

---

## 統合判定表（2026-04-11 実検索ベース）

### venusaur ↔ eevee 統合判定

#### 実参照
| スクリプト | 呼び出し箇所 | 役割 |
|----------|------------|------|
| `kpop_strategy_pipeline.sh:315` | `--agent venusaur` | PHASE2 [6/15] SEO記事構成設計（見出し設計図の生成） |
| `kpop_strategy_pipeline.sh:442` | `--agent eevee` | [10/15] タイトルA/B最終選定（5案生成→CTR/SEO/感情3軸評価） |
| `kpop_pipeline.sh:643` | `--agent eevee` | タイトルA/B生成（breaking pipeline） |
| `lib/auto_improve.py:91` | `venusaur` | 自動改善フィードバック記録対象 |

#### 役割差分（コードベース実態）

| 観点 | venusaur | eevee |
|-----|----------|-------|
| 入力 | lapras(SEO KW) + mimikyu(競合分析) + wobbuffet(読者ニーズ) | metamon_kpop出力の完成記事 |
| 出力 | 記事設計図（H2構成表・KW配置・引き継ぎメモ） | タイトル5案 + 採用タイトル確定 + 記事本文そのまま |
| タイミング | PHASE2冒頭（記事を書く前の設計） | 記事完成後（タイトル最終確定） |
| パイプライン | kpop_strategy_pipeline のみ | kpop_pipeline + kpop_strategy_pipeline |
| 代替モデル | claude-sonnet（デフォルト） | claude-sonnet（デフォルト） |

#### 統合リスク評価

**venusaur は eevee と役割が根本的に異なる。**
- venusaur: 記事「設計」専門（構成・見出し・KW配置の設計図作成）→ deoxysが記事を書く前の入力
- eevee: 記事「タイトル選定」専門（完成記事のタイトルを最終確定）→ 記事完成後の後処理

統合した場合に失われる機能:
- venusaur を削除すると `reports/6_structure.md` が生成されず、deoxys_kpopへの「見出し構成引き継ぎメモ」が消える
- strategy_pipelineの記事品質（構成の論理性・KW配置精度）が低下するリスク

#### 最終判定: **KEEP_ACTIVE**

venusaur は eevee の代替ではなく、異なるフェーズで異なる役割を持つ独立エージェント。
統合は不適切。最小運用でも残すべき。

---

### alakazam_kpop ↔ metamon_kpop 統合判定

#### 実参照
| スクリプト | 呼び出し箇所 | 役割 |
|----------|------------|------|
| `kpop_strategy_pipeline.sh:459` | `--agent alakazam_kpop` | [11/15] ファクトチェック（日付・時制・事実確認） |
| `kpop_chart_pipeline.sh:164` | `--agent alakazam_kpop` | [2/4] チャート記事ファクトチェック（順位・数字・時制） |
| `kpop_strategy_pipeline.sh:416` | `--agent metamon_kpop` | [9/15] CTRリライト（タイトル強化・H2感情改善・冒頭フック） |
| `kpop_pipeline.sh:540` | `--agent metamon_kpop` | タイトルリライト・記事最適化（breaking pipeline） |
| `lib/retry_handler.py:197` | フォールバックマップ | `jirachi_kpop` 失敗時のフォールバック先に `alakazam_kpop` |
| `agents/eevee.md:80,93` | 参照記述 | eevee定義内でakakazamの後続処理として言及 |

#### 役割差分（コードベース実態）

| 観点 | alakazam_kpop | metamon_kpop |
|-----|--------------|-------------|
| 入力 | eevee出力の完成記事（タイトル確定済み） | deoxys_kpop出力の生記事 |
| 出力 | ファクト修正済み記事（内容変更最小限） | CTRリライト済み記事（タイトル・冒頭・H2強化） |
| 目的 | 「嘘・誤解・誇張・時制ミス」の除去 | CTR/SEO最大化のための表現改善 |
| モデル | `claude-haiku-4-5-20251001`（定義ファイルで明示） | デフォルト（sonnet） |
| フォールバック | jirachi_kpopの代替として機能 | deoxys_kpopと相互フォールバック |
| pipeline配置 | step11（後処理） | step9（中間処理） |

#### 統合リスク評価

**alakazam_kpop は metamon_kpop と役割が異なる。ただし近接している部分がある。**

共通点: どちらも記事テキストを受け取り、修正済みテキストを返す
差異:
- alakazam_kpop: 事実の「正確さ」を担保（ファクトチェック）→ Haiku使用で軽量・高速
- metamon_kpop: 記事の「魅力度」を向上（CTR最適化）→ Sonnetで高品質リライト

統合した場合に失われる機能:
- alakazam_kpop の Haiku指定が消え、コスト増加
- `retry_handler.py` の `FALLBACK_MAP` が壊れる（`jirachi_kpop` の fallback 先が消える）
- chart_pipelineでのファクトチェックステップが消える

#### 最終判定: **MERGE_CANDIDATE**

役割は「別フェーズ・別目的」だが、pipeline上の距離（step9→step11）とテキスト変換という共通構造から統合の議論余地はある。ただし：
1. フォールバックマップへの影響
2. Haikuモデル指定（コスト最適化の意図）
3. chart_pipelineでの独立利用

の3点があり、**現時点では統合メリットよりリスクが上回る**。

---

### 最小運用構成への結論

| エージェント | 判定 | 最小運用で残すか |
|------------|------|--------------|
| venusaur | **KEEP_ACTIVE** | **Yes** — eeveeとは全く別役割（設計 vs タイトル選定） |
| alakazam_kpop | **MERGE_CANDIDATE** | **Yes（現時点）** — フォールバックマップ・Haiku最適化・chart独立利用の3点があり統合は時期尚早 |


---

## 責務固定表 (Role Assignment Table) — 2026-04-11 確定版

> **目的**: 役割の重複を防ぎ、保守コストを下げる。  
> 以下の分類と記述が唯一の正典。変更はこのセクションを更新してから agents/*.md に反映すること。

---

### ROLE_CLASS 定義

| クラス | 意味 |
|--------|------|
| CORE | 最小運用構成に必須。欠けるとパイプラインが壊れる |
| SUPPORT | CORのパイプラインを強化する。欠けると品質低下するが動作継続可能 |
| MANUAL_ONLY | cronパイプラインに組み込まれていない。手動呼び出し専用 |
| MERGE_CANDIDATE | 他エージェントとの統合が将来的に検討対象。現時点は独立維持 |

---

### 責務固定表（全16エージェント）

#### 1. deoxys_kpop
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | K-POP速報・戦略記事のHTML本文生成（ゼロから書く唯一のライター） |
| 副責務 | なし（WebSearch取材のみ） |
| 呼び出し元 | kpop_pipeline.sh（step1,2）、kpop_strategy_pipeline.sh（step8）、google_metrics/pipeline_with_trends.sh、generate_similar_articles.sh、timed_pipeline.sh |
| 前工程 | breaking: なし / strategy: mewtwo |
| 後工程 | metamon_kpop |
| 代替候補 | metamon_kpop（retry_handler.py FALLBACK_MAP） |
| 代替可否 | 緊急フォールバックのみ可。metamonはリライト専門のため、ゼロ生成品質は低下する |
| 重複防止ルール | 「記事をゼロ生成する」役割はdeoxys_kpop のみ。venusaur（構成設計）・metamon（リライト）・zapdos（チャート記事）と混同しない |
| 最小運用で残すか | **Yes** |

#### 2. metamon_kpop
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | deoxys生成記事のSEOリライト・タイトル3案生成・CTR最適化 |
| 副責務 | なし |
| 呼び出し元 | kpop_pipeline.sh（step2）、kpop_strategy_pipeline.sh（step9） |
| 前工程 | deoxys_kpop |
| 後工程 | eevee（breaking）/ alakazam_kpop（strategy） |
| 代替候補 | deoxys_kpop（FALLBACK_MAP） |
| 代替可否 | 緊急のみ。deoxysはSEOリライト専門ではなく品質低下する |
| 重複防止ルール | 「既存記事をリライトしてCTRを上げる」役割はmetamon_kpop のみ。deoxys（ゼロ生成）・eevee（タイトル選定）と役割が連続するが別担当 |
| 最小運用で残すか | **Yes** |

#### 3. eevee
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | metamon生成タイトル複数案からCTR・SEO・ファン感情3軸で最終タイトル1案を選定 |
| 副責務 | なし |
| 呼び出し元 | kpop_pipeline.sh（breaking=step2.5）、kpop_strategy_pipeline.sh（strategy=step10） |
| 前工程 | metamon_kpop（両パイプライン共通） |
| 後工程 | jirachi_kpop（breaking）/ alakazam_kpop（strategy） |
| 代替候補 | なし（FALLBACK_MAP未設定） |
| 代替可否 | 不可。タイトル選定ロジックはeeveeに集約 |
| 重複防止ルール | 「タイトル最終選定」はeevee のみ。metamon（タイトル生成）と混同しない。chart pipeline には混入しない |
| 最小運用で残すか | **Yes**（breaking・strategy 両パイプライン共用） |
| ※備考 | 2026-04-11 実装確認: breaking では `claude -p`（--agent なし）でタイトルB生成、strategy では `--agent eevee` でタイトル5案評価・最終選定。役割は同一（タイトル選定）だが呼び出し方が異なる |

#### 4. jirachi_kpop
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | 記事のファクトチェック・時制整合・一次ソース未確認時のFACT_CHECK_FAIL出力 |
| 副責務 | breaking pipelineでの架空情報検出ゲート |
| 呼び出し元 | kpop_pipeline.sh（step3）、kpop_strategy_pipeline.sh（step5） |
| 前工程 | eevee（breaking）/ wobbuffet（strategy） |
| 後工程 | arceus |
| 代替候補 | alakazam_kpop（FALLBACK_MAP） |
| 代替可否 | 部分的に可。ただしFACT_CHECK_FAILゲートはjirachiに組み込まれた固有ロジック |
| 重複防止ルール | 「FACT_CHECK_FAIL を出力してパイプラインを止める」役割はjirachi_kpop のみ。alakazam（ファクト修正のみ）とは異なる |
| 最小運用で残すか | **Yes** |

#### 5. arceus
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | 全エージェント出力を採点し「✅ 投稿承認 / ❌ 投稿却下」の2択で最終投稿判定 |
| 副責務 | 架空情報・プロンプトインジェクション検出による即時却下 |
| 呼び出し元 | kpop_pipeline.sh（step4）、kpop_strategy_pipeline.sh（step14） |
| 前工程 | jirachi_kpop（breaking）/ gengar（strategy） |
| 後工程 | wordpress_post |
| 代替候補 | なし |
| 代替可否 | 不可。最終承認は arceus 以外禁止 |
| 重複防止ルール | 「投稿承認/却下の最終判定」は arceus のみ。gengar（監査レポート）は判定を出さない。2エージェントに最終判定を持たせない |
| 最小運用で残すか | **Yes** |

#### 6. butterfree
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | WebSearchでK-POPトレンド・速報・チャート動向を収集し優先度スコア付きレポート生成 |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step1） |
| 前工程 | なし（strategy pipeline起点） |
| 後工程 | lapras |
| 代替候補 | なし |
| 代替可否 | 不可。WebSearch取材の起点 |
| 重複防止ルール | 「トレンド情報収集」はbutterfree のみ。deoxys（記事生成時のWebSearch取材）と混同しない。buttefreeは戦略情報収集、deoxysは記事取材 |
| 最小運用で残すか | **Yes** |

#### 7. lapras
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | バタフリーレポートからSEOキーワード戦略を設計（メインKW・サブKW・ロングテール・ブルーオーシャン） |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step2） |
| 前工程 | butterfree |
| 後工程 | mimikyu |
| 代替候補 | なし |
| 代替可否 | 不可。SEOキーワード戦略設計はlaprasのみ |
| 重複防止ルール | 「キーワード設計」はlapras のみ。venusaur（キーワードを使った記事構成設計）と役割が連続するが別担当 |
| 最小運用で残すか | **Yes** |

#### 8. mimikyu
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | laprasキーワードでGoogle競合記事を実際にWebSearch調査し、差別化ポイント3点と推奨構成案を生成 |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step3） |
| 前工程 | lapras |
| 後工程 | wobbuffet |
| 代替候補 | なし |
| 代替可否 | 不可。競合調査はWebSearch必須、mimikyu専任 |
| 重複防止ルール | 「競合記事のWebSearch調査」はmimikyu のみ。butterfree（トレンド収集）とは目的が異なる（競合 vs トレンド） |
| 最小運用で残すか | **Yes** |

#### 9. wobbuffet
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | SUPPORT |
| 主責務 | K-POPファンの行動心理・情報ニーズを分析し記事切り口とdeoxysへの推奨メモを生成 |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step4） |
| 前工程 | mimikyu |
| 後工程 | jirachi_kpop |
| 代替候補 | なし（FALLBACK_MAP未設定） |
| 代替可否 | 欠けても他ステップは動くが、deoxysへの読者心理インプットが消える |
| 重複防止ルール | 「読者ニーズ分析」はwobbuffet のみ。mimikyu（競合分析）・lapras（SEO分析）と視点が異なる |
| 最小運用で残すか | **Yes**（strategyパイプライン品質の要） |

#### 10. venusaur
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | lapras・mimikyu・wobbuffetの情報を統合してdeoxysが書く記事の設計図（H2構成・KW配置・文字数配分）を生成 |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step6） |
| 前工程 | mewtwo（step5統合後） |
| 後工程 | deoxys_kpop |
| 代替候補 | なし |
| 代替可否 | 不可。記事設計図はvenusaur専任 |
| 重複防止ルール | 「記事の設計図を作る」はvenusaur のみ。eevee（タイトル選定）・lapras（KW設計）と連携するが別担当。deoxysに設計図を渡すという唯一の役割 |
| 最小運用で残すか | **Yes** |

#### 11. alakazam_kpop
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | MERGE_CANDIDATE |
| 主責務 | 記事の日付・時制・固有名詞・誇張表現を修正するファクトチェック（修正出力型） |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step10）、kpop_chart_pipeline.sh（step2） |
| 前工程 | metamon_kpop（strategy）/ zapdos（chart） |
| 後工程 | gengar（strategy）/ 投稿（chart） |
| 代替候補 | jirachi_kpop |
| 代替可否 | 部分的に可。jirachiはFAIL出力型、alakazamは修正出力型で目的が異なる |
| 重複防止ルール | jirachi_kpop（ファクトチェックFAIL判定）とakazam_kpop（ファクト修正して続行）は役割が補完的で重複ではない。統合した場合はfallback先が消えretry_handler.pyが壊れる |
| 最小運用で残すか | **Yes（現時点）** — フォールバックマップ・Haiku軽量化・chart独立利用の3点あり統合は時期尚早 |

#### 12. gengar
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | 投稿直前の最終SEO・品質・リスク監査（投稿OK/要確認/停止の3択判定） |
| 副責務 | 修正可能な問題は自分で修正して完成記事を出力 |
| 呼び出し元 | kpop_strategy_pipeline.sh（step11） |
| 前工程 | alakazam_kpop |
| 後工程 | kairyu_kpop |
| 代替候補 | なし |
| 代替可否 | 不可。SEO・品質・リスクの3観点監査はgengar専任 |
| 重複防止ルール | 「arceus前の品質監査レポート生成」はgengar のみ。arceus（最終投稿判定）とは役割が異なる。gengarは「改善して出力」、arceusは「承認/却下」 |
| 最小運用で残すか | **Yes** |

#### 13. kairyu_kpop
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | SUPPORT |
| 主責務 | ファクトチェック済み完成記事にCTA・関連記事誘導・SNSシェア促進を追加してCVR・回遊率を向上 |
| 副責務 | H2見出しの感情強化 |
| 呼び出し元 | kpop_strategy_pipeline.sh（step13） |
| 前工程 | gengar |
| 後工程 | arceus |
| 代替候補 | なし |
| 代替可否 | 欠けても記事は投稿されるが収益導線が消える |
| 重複防止ルール | 「CTA・回遊導線の追加」はkairyu_kpop のみ。gengar（品質監査）・arceus（最終判定）と混同しない |
| 最小運用で残すか | **Yes**（収益直結） |

#### 14. persian
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | SUPPORT |
| 主責務 | 投稿記事のX(Twitter)投稿文3パターン・ハッシュタグ・タイミングを設計 |
| 副責務 | なし |
| 呼び出し元 | kpop_strategy_pipeline.sh（step15）、kpop_chart_pipeline.sh（step4） |
| 前工程 | 投稿完了後（post_id・URL取得後） |
| 後工程 | post_to_x.sh（実際の投稿） |
| 代替候補 | なし（FALLBACK_MAP: 空リスト = 失敗許容） |
| 代替可否 | 失敗許容設計。欠けてもX投稿がスキップされるだけで記事は公開済み |
| 重複防止ルール | 「X投稿文の設計」はpersian のみ。post_to_x.sh（実行スクリプト）とは役割が分離されている |
| 最小運用で残すか | **Yes** |

#### 15. zapdos
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | CORE |
| 主責務 | Billboard・Melon・OiconチャートをWebSearchで取得しランキング記事をHTML生成 |
| 副責務 | なし |
| 呼び出し元 | kpop_chart_pipeline.sh（step1）のみ |
| 前工程 | なし（chart pipeline起点） |
| 後工程 | alakazam_kpop |
| 代替候補 | deoxys_kpop（FALLBACK_MAP） |
| 代替可否 | 緊急フォールバックのみ可。deoxysはチャートデータ構造化が専門でないため品質低下 |
| 重複防止ルール | 「チャートランキング記事の生成」はzapdos のみ。deoxys（速報/戦略記事）とジャンルが異なる |
| 最小運用で残すか | **Yes**（chart_pipelineの唯一の記事生成役） |

#### 16. articuno（フリーザー）
| 項目 | 内容 |
|------|------|
| ROLE_CLASS | MANUAL_ONLY |
| 主責務 | SNSバズコンテンツ（感情共感型・驚き発見型・比較議論型・まとめ保存型）の記事設計と生成 |
| 副責務 | なし |
| 呼び出し元 | **なし**（どのcronパイプラインにも組み込まれていない） |
| 前工程 | 手動指示のみ |
| 後工程 | persian（手動） |
| 代替候補 | deoxys_kpop（バズコンテンツ限定） |
| 代替可否 | 部分的に可。ただしarticunoは感情共感型・比較型など専用バズパターンを持つ |
| 重複防止ルール | cronパイプラインに追加しない。SNSバズ記事の手動発注専用。deoxys（速報）・zapdos（チャート）とは目的が異なる |
| 最小運用で残すか | **Yes（MANUAL_ONLY扱いで維持）** |

---

### 重複禁止マトリクス

以下の組み合わせで同じ役割を持つエージェントを追加・新設してはならない。

| 禁止される重複 | 独占エージェント | 理由 |
|--------------|--------------|------|
| 記事ゼロ生成 | deoxys_kpop | metamon/venusaur/zapdosは生成しない |
| 最終投稿承認/却下 | arceus | 2エージェントに判定権を持たせない |
| K-POPトレンド収集（WebSearch） | butterfree | deoxysの記事取材とは別物 |
| 競合記事WebSearch調査 | mimikyu | buttefreeのトレンド収集と混同しない |
| 記事設計図生成 | venusaur | eeveeのタイトル選定と混同しない |
| タイトル最終選定（breaking・strategy共通） | eevee | metamonが生成、eeveeが決定。chart には混入しない |
| FACT_CHECK_FAIL出力 | jirachi_kpop | alakazamは修正出力型 |
| CTA・回遊導線追加 | kairyu_kpop | gengar/arceusと混同しない |
| チャートランキング記事生成 | zapdos | deoxysと役割分担 |
| SNSバズ記事（手動） | articuno | cronに組み込まない |

---

### フォールバック制約（retry_handler.py と連動）

```
# この組み合わせを変更する前に必ずretry_handler.pyのFALLBAK_MAPを確認すること
FALLBACK_MAP = {
    "deoxys_kpop":  ["metamon_kpop"],   # 緊急のみ。品質低下を許容して投稿を維持
    "metamon_kpop": ["deoxys_kpop"],    # 緊急のみ
    "jirachi_kpop": ["alakazam_kpop"],  # FAILゲートが消えるが続行可
    "zapdos":       ["deoxys_kpop"],    # チャート記事フォールバック
    "persian":      [],                 # 失敗許容。X投稿スキップで記事は公開済み
}
# 注意: arceusのフォールバックは設定しない（最終判定は単一エージェントであるべき）
# 注意: alakazam_kpopを削除するとjirachi_kpopのフォールバック先が消える
# 注意: eeveeのフォールバックは設定しない（breaking・strategy共用だが、失敗時はmetamonの出力タイトルをそのまま使う設計）
```

---

### パイプライン別エージェント使用表（確定版）

| エージェント | breaking | strategy | chart |
|------------|:--------:|:--------:|:-----:|
| butterfree | - | step1 | - |
| lapras | - | step2 | - |
| mimikyu | - | step3 | - |
| wobbuffet | - | step4 | - |
| jirachi_kpop | - | step5 | - |
| venusaur | - | step6 | - |
| mewtwo | - | step7 | - |
| deoxys_kpop | step1,2 | step8 | - |
| metamon_kpop | step2 | step9 | - |
| eevee | step2.5 | step10 | - |
| alakazam_kpop | - | step10 | step2 |
| gengar | - | step11 | - |
| kairyu_kpop | - | step13 | - |
| arceus | step4 | step14 | - |
| persian | - | step15 | step4 |
| zapdos | - | - | step1 |
| articuno | MANUAL | MANUAL | MANUAL |


---

## 責務逸脱チェック仕様 — 2026-04-11 確定版

> **スクリプト**: `lib/audit_agent_roles.py`  
> **実行方法**: `python3 lib/audit_agent_roles.py`  
> **Exit code**: 0=全OK / 1=NG1件以上  
> **cron接続**: 現時点では未接続（手動実行のみ）

### 検査項目一覧

| ID | 検査内容 | NG時の意味 |
|----|---------|----------|
| C01 | breaking pipeline の WebSearch付き生成エージェントが deoxys_kpop のみか | ゼロ生成役が増殖している |
| C02 | strategy pipeline の WebSearch付き生成エージェントが deoxys_kpop・butterfree・mimikyu のみか | 調査外エージェントが生成に混入 |
| C03 | chart pipeline の WebSearch付き生成エージェントが zapdos のみか | chart生成役が変更されている |
| C04 | eevee が許可外パイプライン（chart等）で呼ばれていないか | breaking・strategy以外へ越境している |
| C05 | articuno が cron接続ファイルで呼ばれていないか | MANUAL_ONLYエージェントがcronに混入 |
| C06 | FALLBACK_MAP に arceus のフォールバックが設定されていないか | 最終判定権が複数に分散するリスク |
| C07 | jirachi_kpop のフォールバック先に alakazam_kpop が含まれているか | フォールバックチェーンが壊れている |
| C08 | strategy pipeline で venusaur が呼ばれているか | 設計図生成ステップが欠落している |
| C09 | arceus が breaking・strategy の最終ステップで呼ばれているか | 最終承認ゲートが消えている |
| C10 | zapdos が chart 以外で呼ばれていないか | チャート専用エージェントが越境している |
| C11 | 全16エージェントの agents/*.md に ROLE_CLASS が記述されているか | 新エージェント追加時に定義が漏れている |
| C12 | articuno.md に ROLE_CLASS: MANUAL_ONLY が記述されているか | MANUAL_ONLYラベルが消えている |
| C13 | crontab が articuno を直接参照していないか | MANUAL_ONLYエージェントがcron登録された |
| C14 | FALLBACK_MAP の必須エントリが揃っているか | フォールバック設定が意図せず削除された |
| C15 | 未登録エージェントが WebSearch付きで呼ばれていないか（WARN） | 新エージェントが無断で生成ステップに追加された |

### 初回実行結果（2026-04-11 / 初版）

```
結果: OK=14  NG=1  WARN=0  ← 初版時点の記録

❌ [C04] eevee が strategy pipeline の 442 行目で呼ばれている（当時の判定）
    原因: 責務固定表の記述が「breaking専用」となっていたが、
          実装確認の結果 strategy での使用も主責務（タイトル最終選定）と一致。
    解消: 責務固定表・agents/eevee.md・チェックロジックを実態に合わせて修正。
```

### C04 解消記録（2026-04-11）

- **解消方法**: 実装確認の結果、定義側が誤りと判明 → 責務固定表を修正
- **実装確認結果**:
  - breaking pipeline: step2.5 で `claude -p`（`--agent` なし）でタイトルB生成
  - strategy pipeline: step10 で `--agent eevee` でタイトル5案評価・最終選定
  - → 両パイプラインとも「タイトル選定」という同一責務で正当使用
- **修正ファイル**:
  - `agents/eevee.md`: PIPELINE_POSITION を `breaking=step2.5 / strategy=step10` に更新
  - `lib/audit_agent_roles.py`: C04 チェックを「chart 等への越境禁止」に変更
  - `docs/operations_runbook_v1.0.md`: 責務固定表 eevee 行・パイプライン使用表を更新
  - `lib/retry_handler.py`: コメントを実態に合わせて更新

### 本番運用接続（2026-04-11 完了・bash -n 通過済み・実行テスト済み・可観測性強化済み）

**接続先**: `improvement_engine.sh` の STEP7.5 として組み込み済み。

```
実行タイミング: 毎日 21:00 JST（cron: 0 21 * * *）
               improvement_engine.sh が呼ぶ STEP7.5 として実行
実行コマンド:  python3 lib/audit_agent_roles.py
ログ保存先1:  logs/role_audit.log（audit専用・日付ヘッダ付き追記）
ログ保存先2:  logs/improvement_engine.log（他STEPと統合ログ）
```

**失敗時の扱い**:
- Exit code 1（NG検出）→ `ERRORS` 配列に追記。改善エンジンは継続実行。パイプラインは止まらない
- NG件数は STEP8 の Discord サマリーに `⚠️ 責務逸脱チェック: NG N件` として含まれる
- 詳細は `logs/role_audit.log` を参照すること

**Exit code の意味**:
| Exit code | 意味 | 対応 |
|-----------|------|------|
| 0 | 全15チェック OK — 責務逸脱なし | 対応不要 |
| 1 | NG 1件以上 — 責務逸脱を検出 | `logs/role_audit.log` を確認し、責務固定表と実装の乖離を修正すること |

**既存cronとの衝突**:
- `improvement_engine.sh` 内部で順次実行のため二重実行なし
- `post_watchdog.py`（毎30分）とは目的・対象が異なる（投稿監視 vs 責務定義監視）
- 独立した cron 行は追加していない

**ログ確認コマンド**:
```bash
# 最新の audit 結果を確認
tail -50 logs/role_audit.log

# NG件数のみ確認
grep -c "^❌" logs/role_audit.log

# 全実行履歴のサマリーのみ（OK/NG/WARN の推移）
grep "結果:" logs/role_audit.log

# improvement_engine.log に記録された1行サマリー履歴
grep "\[role_audit\]" logs/improvement_engine.log

# 前回比較スナップショットを確認
cat logs/role_audit_snapshot.json
```

---

### role audit 障害時の調査手順

#### まず確認するログ

```bash
# 1. improvement_engine.log の1行サマリーで何がNGか把握
grep "\[role_audit\]" logs/improvement_engine.log | tail -10

# 2. role_audit.log で最新実行のフルレポートを確認
#    （最後の "====" ブロックを探す）
tail -80 logs/role_audit.log

# 3. 前回比較スナップショットで「いつ壊れたか」を特定
cat logs/role_audit_snapshot.json
# → timestamp フィールドが直近で NG になった時刻
```

#### 推移の追跡

```bash
# 全実行の OK/NG/WARN 推移を一覧表示
grep -E "結果:|audit_agent_roles 実行:" logs/role_audit.log | paste - -

# 差分情報（新規NG・解消NG）を抽出
grep "前回比較\|前回(" logs/role_audit.log | tail -20
```

#### 想定される壊れ方と対応

| チェック | よくある壊れ方 | 確認箇所 |
|----------|---------------|---------|
| C01/C02 NG | 新エージェントをゼロ生成ステップに追加した | `kpop_pipeline.sh` / `kpop_strategy_pipeline.sh` の `--allowedTools WebSearch` 行 |
| C03 NG | chart pipeline に zapdos 以外を追加した | `kpop_chart_pipeline.sh` |
| C04 NG | eevee を chart 等に誤投入した | `kpop_chart_pipeline.sh` / `hub_article_post.sh` |
| C06 NG | arceus のフォールバックを誰かが追加した | `lib/retry_handler.py` FALLBACK_MAP |
| C07 NG | alakazam_kpop を削除・改名した | `lib/retry_handler.py` FALLBACK_MAP + `agents/alakazam_kpop.md` |
| C09 NG | arceus が breaking/strategy から外れた | `kpop_pipeline.sh` / `kpop_strategy_pipeline.sh` の最終承認ステップ |
| C11 NG | 新エージェントを追加したが ROLE_CLASS を書き忘れた | `agents/<新エージェント>.md` |
| C14 NG | FALLBACK_MAP の必須エントリを削除した | `lib/retry_handler.py` FALLBACK_MAP |
| C15 WARN | 新エージェントが WebSearch付きで呼ばれている | 責務固定表への登録が必要か検討 |

#### 復旧の基本手順

1. **NGの特定**: `grep "\[role_audit\]" logs/improvement_engine.log | tail -5` で NG チェックID を確認
2. **原因調査**: 上記テーブルの「確認箇所」を `grep` で調べる
3. **修正**: 定義（`agents/*.md` / `lib/retry_handler.py`）か実装（パイプライン `*.sh`）のどちらが間違っているかを判断して修正
4. **再確認**: `python3 lib/audit_agent_roles.py` を手動実行して Exit 0 になることを確認
5. **スナップショット**: 次の `improvement_engine` 実行時に自動更新される

> **原則**: 実装を見てから定義を直す。定義だけ見て実装を壊さないこと。

---

## 自律改善ループ 全体設計（2026-04-11 更新）

### 自動修復ポリシー表

| NG種別 | 分類 | 修復方法 | 実装場所 |
|--------|------|---------|---------|
| スラッグ不正 | AUTO_FIX_SAFE | 自動再生成（slug_generator.py）→ WP API PATCH | post_audit.sh [0] |
| HTML文字数不足 | AUTO_FIX_SAFE | コンテンツパディング自動補完 | post_audit.sh [1] |
| タグ未設定 | AUTO_FIX_SAFE | カテゴリから自動生成 | post_audit.sh [5] |
| メタ説明不備 | AUTO_FIX_SAFE | 本文から自動生成 | post_audit.sh [3] |
| サムネ未設定 | AUTO_FIX_SAFE | make_thumbnail.py で生成 → WP API PATCH | post_audit.sh [6] |
| X投稿未成功 | AUTO_FIX_LIMITED | スコア80以上なら自動再試行（1回のみ） | post_audit.sh [7] |
| X投稿v12.0フォーマット違反（投稿済み） | HUMAN_REVIEW_ONLY | 投稿済みなら警告ログのみ・再投稿しない（重複投稿防止と干渉するため）。次回から改善はエージェント指令で対応 | post_audit.sh [7b]（2026-04-11修正） |
| X投稿v12.0フォーマット違反（未投稿） | AUTO_FIX_LIMITED | 未投稿の場合のみ再生成・再投稿を試みる | post_audit.sh [7b][⑤] |
| タイトルSEO（K-POPキーワードなし） | AUTO_FIX_SAFE | K-POPプレフィクス付与 → WP API PATCH（2026-04-11追加） | post_audit.sh [2b] |
| サムネジャンル不一致 | HUMAN_REVIEW_ONLY | 検知のみ。手動でmake_thumbnail.py再実行 | post_watchdog.py check_thumbnail_genre_mismatch |
| draft記事X投稿事故 | HUMAN_REVIEW_ONLY | 検知・Discord通知のみ。手動でWP publish昇格か X投稿削除 | post_watchdog.py check_draft_x_posted |
| pipeline外WP公開記事（直近48h） | HUMAN_REVIEW_ONLY | 検知・Discord通知のみ。自動修復なし。WordPressで記事確認・必要ならpipeline.jsonlに記録 | post_watchdog.py check_pipeline_external_wp_posts（2026-04-11追加）確認: `python3 lib/post_watchdog.py --check external_wp` |
| タイトル弱い | AUTO_FIX_LIMITED | eevee/metamonがA/Bタイトル生成。スコア不足なら再生成 | kpop_pipeline.sh step2.5/10 |
| ターゲット層不一致 | HUMAN_REVIEW_ONLY | arceus最終承認段階で却下。改善はプロンプト見直し | agents/*.md ROLE_CLASS |
| SEO弱い | AUTO_FIX_LIMITED | laprasがKW最適化・venusaurがH2設計 | kpop_strategy_pipeline.sh |
| CTA弱い | AUTO_FIX_LIMITED | meowth/wobbuffetがCTA・感情フレーズ設計 | kpop_pipeline.sh |
| イベント記事魅力不足 | HUMAN_REVIEW_ONLY | 検知なし。プロンプト・エージェント指令で改善 | agents/deoxys_kpop.md |
| テーマ幅不足 | AUTO_FIX_LIMITED | cron 15:00(lifestyle)・18:00(fashion)パイプライン | kpop_master_scheduler.sh |
| トレンド捕捉漏れ | AUTO_FIX_LIMITED | butterfree/mimikyu/jirachiが毎日会議で補足 | ai_company/run_ai_meeting.sh |
| 会議体未接続 | AUTO_FIX_LIMITED | STEP5.5でmewtwo_decision.mdをimprovement_engineに接続 | improvement_engine.sh |
| Discord可読性不良 | AUTO_FIX_SAFE | STEP8を重要度順・NG優先フォーマットに変更済み | improvement_engine.sh |

### draft記事X投稿事故の防止

**多重防御設計（2026-04-11 実装）:**

1. **pipeline レベル**: Arceus却下 → `archive_and_exit 1` → X投稿ステップに到達しない
2. **DRAFT GUARD 2（X投稿直前）**: kpop_pipeline.sh [5]・kpop_strategy_pipeline.sh [15.1] の直前でWP APIを叩いてstatus確認。`publish`以外なら`X_STATUS="スキップ(DRAFT_GUARD)"`で即スキップ（X投稿コードブロックごとスキップ）
3. **post_audit.sh [7] 冒頭 DRAFT GUARD**: `STATUS != publish` なら `_X7_SKIP=1` でX投稿再試行をスキップ
4. **post_watchdog.py `check_draft_x_posted`**: 24時間以内の kpi_posts.jsonl から「X投稿済み + draft/pending」を逆監査 → Discord urgentへ通知

**手動確認コマンド:**
```bash
python3 lib/post_watchdog.py --dry-run --check draft_x_guard
```

### 会議体（run_ai_meeting.sh）の接続状態

| 会議体 | 実行時刻 | 出力先 | improvement_engineへの接続 |
|--------|---------|--------|--------------------------|
| AI日次会議 (butterfree/lapras/mimikyu/jirachi) | 21:00 JST | `~/ai_company/reports/` | STEP5.5 で mewtwo_decision.md を取り込み |
| Porygon分析 / SRE | 21:00 JST | `~/ai_company/reports/` | STEP5.5 で取り込み |
| CEO朝次ブリーフ | 09:00 JST | `logs/morning_brief.log` | 接続なし（参照用） |
| 週次改善 (kpop_weekly_review.sh) | 月曜 06:30 | `~/weekly_reviews/` | STEP7（月曜のみ）で間接参照 |

**解決済み（2026-04-11）**: cron時刻をずらすことで競合を解消。`run_ai_meeting.sh` = 21:00、`improvement_engine.sh` = 21:30。30分のマージンにより当日会議レポートを確実に取り込める。

### ターゲット層適合性の担保箇所

| ターゲット | 担当エージェント | 実装箇所 |
|-----------|----------------|---------|
| KPOPファン・推し活 | deoxys_kpop (文体)、eevee (タイトルファン感情軸) | agents/deoxys_kpop.md、agents/eevee.md |
| 韓国好き (旅行・カフェ・観光) | lifestyle pipeline (15:00 cron) | kpop_pipeline.sh themed args |
| 美容・コスメ興味層 | beauty pipeline、meowth (CTA) | kpop_pipeline.sh beauty args |
| ファッション興味層 | fashion pipeline (18:00 cron) | kpop_pipeline.sh fashion args |
| イベント・ポップアップ | breaking pipeline + arceus審査 | kpop_pipeline.sh |
| SNSトレンド敏感層 | butterfree (トレンドスカウト)、persian (X文体) | agents/butterfree.md、agents/persian.md |

**テーマ拡張状況（2026-04-11 更新）:**

| テーマ | 実装方式 | スロット | 担当 |
|--------|---------|---------|------|
| 韓国ドラマ / Netflixドラマ | kpop_pipeline + FOCUS指定（drama） | 20時（3日に1回） | deoxys_kpop |
| 韓国映画 | kpop_pipeline + FOCUS指定（movie） | 20時（3日に1回） | deoxys_kpop |
| 芸能ゴシップ | kpop_pipeline + FOCUS指定（gossip） | 20時（3日に1回） | deoxys_kpop |
| 韓国旅行・カフェ | kpop_pipeline + FOCUS指定（lifestyle） | 15時 | deoxys_kpop |

**実装方式**: pipeline複製・agent追加なし。kpop_master_scheduler.shの `determine_content()` がcontent_typeとFOCUSを切り替えることで分岐。既存deoxys_kpopがテーマに応じた記事を生成。

### gossip記事の公開条件（2026-04-11 厳格化）

gossip（熱愛・炎上・脱退・移籍）は他テーマより一次ソース基準が厳しい。以下を全て満たさなければ publish しない。

**公開に必要な条件（AまたはBの少なくとも一方）:**
- A. 公式発表・公式SNS（Weverse/X/Instagram）・公式声明・所属事務所コメントへの言及
- B. 信頼できる韓国メディア（NAVER/ニュース1/朝鮮日報芸能面/Dispatch/Soompi等）2件以上の報道

**自動停止条件（以下のいずれかで止まる）:**

| 段階 | 停止条件 | 停止フラグ | ログ |
|------|---------|----------|------|
| 記事生成（scheduler） | 公式ソースなし・信頼メディア不足 | `GOSSIP_SOURCE_FAIL` | `logs/gossip_source_guard.log` |
| 記事生成（scheduler） | WebSearch一次ソース未確認 | `DEOXYS_SOURCE_FAIL` | `logs/gossip_source_guard.log` |
| pipeline内 | 憶測語検出（関係者によると/噂等） | `GOSSIP_SOURCE_GUARD` → archive_and_exit | `logs/gossip_source_guard.log` + `logs/pipeline.jsonl` |
| post_audit [4.5] | 投稿後の本文ソースチェックNG | `ISSUES`追加 → 3回失敗でdraft化 | `logs/gossip_source_guard.log` + Discord urgent_errors |

**人手確認が必要なケース:**
- post_audit [4.5] でNGが出てdraft化された gossip記事（WP管理画面で内容確認の上、手動publishまたは削除）
- gossip_source_guard.log に GOSSIP_SOURCE_WEAK が記録された場合

**絶対禁止（記事に含めてはいけない表現）:**
- 「関係者によると」「ネットで話題」「噂によると」「匿名ソースによると」
- 確認されていない人物コメントの直接引用
- 公式否定情報を事実として記載

**監査チェック:**
- `audit_agent_roles.py C18`: gossip_source_guard の実装が pipeline・post_audit の両方に存在するか
- `logs/gossip_source_guard.log`: 停止理由の詳細記録

**手動確認コマンド:**
```bash
# gossip停止ログ確認
tail -20 logs/gossip_source_guard.log
# pipeline.jsonlのgossip_source_guardエントリ確認
grep "gossip_source_guard" logs/pipeline.jsonl | tail -10
# カテゴリ14の記事一覧（WP API）
curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?categories=14&per_page=5&status=publish" -K ~/.wp_auth | python3 -c "import json,sys; [print(p['title']['rendered']) for p in json.load(sys.stdin)]"
```

### gossip_source_guard 実運用評価（2026-04-11 検証済み）

**実装状態**: 実装完了・本番実行待ち（gossipスロット=20時/3日ローテーション、初回実行は翌日以降）

**コード検証結果（過去20件のアーカイブで確認）:**

| 確認項目 | 結果 |
|---------|------|
| 憶測語パターンの通常記事誤検知 | **0/20件** — 誤検知なし |
| 情報元セクション検出（旧パターン） | 1件でHTML構造由来の誤NG（`<strong>情報元</strong>：` がマッチしなかった）|
| 情報元セクション検出（修正後パターン） | **全件正常** — HTMLタグ除去後にチェックするよう修正済み |
| カテゴリ14以外での[4.5]起動 | **なし** — カテゴリ14識別は正確に動作 |
| 通常breaking記事への副作用 | **なし** — GOSSIP_MODE=0では全ての追加チェックがスキップ |

**修正した内容（2026-04-11）:**
- `post_audit.sh [4.5]` の情報元セクション正規表現バグを修正
  - 旧: `.{0,5}[：:【]` — `<strong>情報元</strong>：` のようなHTMLタグが間に入ると失敗
  - 新: HTMLタグをre.subで除去してから `(情報元|出典|参照|引用|参考)` で検索

**残っている限界:**
- gossipプロンプトのソース条件はLLMに依存するため100%保証ではない（post_audit [4.5]が二重防御）
- 憶測語パターンは現在9パターン。「内部情報では」「業界関係者の話では」等の迂回表現は検出しない
- カテゴリ14依存のため、カテゴリが誤分類（例: 訴訟記事がカテゴリ9に入る等）した場合は[4.5]が動かない
- グッズ・交通・フード専用エージェントなし（breaking速報で部分カバーのみ）
- サブカル・アニメコラボ系なし

### gossip_source_guard 観測強化（2026-04-11 追加）

**improvement_engine.sh に STEP4.6 追加済み（毎日 21:30 JST に実行）:**

```
STEP4.6: gossip_source_guard 集計
  - gossip_source_guard.log の累計 / 今日 / 直近7日の停止件数を集計
  - 停止理由の内訳（6分類）を表示
  - STEP8 Discord に「今日の停止件数」と内訳を表示
```

**停止理由の6分類（logs/gossip_source_guard.log に記録される）:**

| 分類キーワード | 発生段階 | 意味 |
|---|---|---|
| `GOSSIP_SOURCE_FAIL` | scheduler（生成時） | 公式ソースなし or 信頼メディア1件以下 |
| `DEOXYS_SOURCE_FAIL` | scheduler（生成時） | WebSearch一次ソース未確認 |
| `憶測語検出` | pipeline（prebuilt処理時） | 関係者によると/噂によると等 |
| `GOSSIP_SOURCE_WEAK` | post_audit [4.5] | 投稿後に公式ソース不足を検出 |
| `GOSSIP_SPECULATION` | post_audit [4.5] | 投稿後に憶測語を検出 |
| `情報元セクションなし` | post_audit [4.5] | 情報元セクションが本文にない |

**次に見るべきログ（本番データが溜まったら）:**
```bash
# 停止内訳確認
tail -50 logs/gossip_source_guard.log
# pipeline.jsonlのgossip_source_guardエントリ
grep "gossip_source_guard" logs/pipeline.jsonl | tail -20
# 今日の停止件数（improvement_engine集計）
grep "gossip停止" logs/improvement_engine.log | tail -5
```

**憶測語パターン追加の判断基準（本番データ蓄積後）:**
- `憶測語検出` が0件かつ GOSSIP_SOURCE_WEAK が多い → ソース要件（メディア2件）が厳しすぎる可能性
- `GOSSIP_SOURCE_FAIL` が多い → プロンプト条件が有効に機能している（正常）
- 憶測語が通過してpost_audit [4.5]でも止まらない事例が出たら → パターン追加（「業界関係者の話では」等）

**現在の状態（2026-04-11時点）:**
- gossip_source_guard.log: **まだ本番実行なし**（gossipスロット=20時/3日ローテーション、初回は翌日以降）
- 過去20件のアーカイブ検証: 通常記事への誤検知ゼロ確認済み
- 断定できない点: 憶測語迂回表現の実発生頻度、ソース要件の適切な厳しさ

**再レビュー確認（2026-04-11 第2回）: 未観測継続中 — 本番データ待ち**
- 確認日: 2026-04-11（gossipスロット日 day%3==2、20時スロット未実行）
- gossip_source_guard.log / pipeline.jsonl / improvement_engine.log / post_audit.log: 全て実データなし
- 実装・構文・audit は正常（bash -n PASS / py_compile PASS / OK=18 NG=0 WARN=0）
- 次回レビュー条件: gossip スロット初回実行後（最短: 本日20時 JST）

**次にやるべき最小改善（本番データ蓄積後）:**
1. gossip_source_guard.log に初回データが溜まったら、GOSSIP_SOURCE_FAIL/GOSSIP_SOURCE_WEAK/憶測語の比率を確認
2. 憶測語パターンの迂回表現（「業界関係者の話では」等）を追加するか実データで判断
3. GOSSIP_SOURCE_WEAK と実際の記事品質の相関を確認し、ソース要件（メディア2件）の厳しさを調整


---

## gardevoir_hook_critic — 刺さり品質ゲート

### 概要

「技術的に正しい記事」を「読みたくなる記事」かどうか判定するゲートエージェント。
SEO・ファクト・フォーマットが全て通過していても、読者の感情を動かさない記事を止める唯一の責務。

### パイプライン配置

| パイプライン | ステップ | 直前 | 直後 |
|------------|---------|------|------|
| breaking (kpop_pipeline.sh) | 3.5 | jirachi_kpop (step 3) | arceus (step 4) |
| strategy (kpop_strategy_pipeline.sh) | 13.5 | kairyu_kpop (step 13) | arceus (step 14) |

### VERDICT 定義

| VERDICT | スコア | 意味 | パイプライン動作 |
|---------|-------|------|----------------|
| PASS | 80〜100 | 刺さる。公開可 | arceus へ進む |
| SOFT_RETRY | 65〜79 | 惜しい。修正で改善可能 | metamon/deoxys(breaking) または metamon/kairyu(strategy) に差し戻し（最大2回） |
| HARD_FAIL | 0〜64 | 刺さらない。公開禁止 | archive_and_exit 1（arceus は呼ばれない） |

### スコア計算式

```
SCORE = (HOOK_SCORE × 0.20) + (TITLE_SCORE × 0.25) + (AUDIENCE_FIT × 0.20)
      + (SHAREABILITY × 0.15) + (EMOTIONAL_PULL × 0.10) + (CATEGORY_FIT × 0.10)
```

CTA_SCORE は加点要素（+5点まで）。

### 自動差し戻しループ（SOFT_RETRY）

```
gardevoir → SOFT_RETRY
  → metamon_kpop（タイトル再生成）
  → deoxys_kpop（breaking: 冒頭リライト）/ kairyu_kpop（strategy: CTA・H2改善）
  → gardevoir 再採点
  → SOFT_RETRY × 2回超過 → HARD_FAIL扱いで archive_and_exit 1
```

最大リトライ: 2回。3回目は自動的に HARD_FAIL として停止。

### 公開禁止条件

以下のいずれかの場合、`archive_and_exit 1` が実行され arceus は呼ばれない:
- VERDICT が `HARD_FAIL`（SCORE 0〜64）
- SOFT_RETRY が 2 回に達してもスコアが 65 未満

### ログ

| ファイル | 内容 |
|---------|------|
| `logs/gardevoir_hook.jsonl` | 全verdict（PASS/SOFT_RETRY/HARD_FAIL）を1行JSONで記録 |
| `logs/pipeline.jsonl` | log_step "gardevoir_hook_critic" として記録 |

#### gardevoir_hook.jsonl フィールド仕様（2026-04-12改訂）

全エントリ（PASS / SOFT_RETRY / HARD_FAIL 問わず）に以下を記録する:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `ts` | string (ISO8601) | 記録タイムスタンプ（UTC） |
| `run_id` | string | パイプライン実行ID（`YYYYMMDD_HHMMSS`形式） |
| `pipeline` | string | `"strategy"` または `"breaking"` |
| `agent` | string | 常に `"gardevoir_hook_critic"` |
| `score` | int | 採点スコア（0〜100） |
| `verdict` | string | `PASS` / `SOFT_RETRY` / `HARD_FAIL` / `ERROR` |
| `retry` | int | リトライ回数（0〜2） |
| `must_fix` | string | VERDICT が SOFT_RETRY / HARD_FAIL 時の改善必須点 |
| `title` | string | 採点対象記事タイトル |
| `category` | string | 記事カテゴリ |

#### SCOREパース仕様（2026-04-12改訂）

strategy / breaking の両パイプラインで以下7フォーマットに対応済み:

| パターン | 例 |
|---------|---|
| 1 | `SCORE: 89` （同一行に数字） |
| 2 | `SCORE: 89/100` （同一行に /100 付き） |
| 3 | `TOTAL: 81/100` （TOTAL行） |
| 4 | `SCORE:\n総合: 81/100` （直後行） |
| 5 | `SCORE:\n- 総合スコア: 87/100` （任意行・距離制限なし） |
| 6 | `総合スコア: 87/100` （任意行） |
| 7 | `総合: 87` （任意行） |

#### VERDICTフォールバック仕様（2026-04-12追加）

gardevoir出力に `VERDICT:` 行が存在しない場合、スコアから自動推定する:

| スコア | 推定VERDICT |
|-------|------------|
| 80 以上 | PASS |
| 65〜79 | SOFT_RETRY |
| 64 以下 | HARD_FAIL |

スコアも取得できない場合のみ `ERROR` となり、`hard_fail` で停止する。

### Discord 通知

HARD_FAIL 発生時に `urgent_errors` チャンネルへ以下を通知:
```
🛑 刺さり品質HARD_FAIL — 公開停止
Score: XX / RETRY: N回
Title: <タイトル>
MUST_FIX: <改善必須点>
```

### 責務固定表（重複禁止）

| エージェント | 責務 | gardevoir との違い |
|------------|------|--------------------|
| eevee | タイトルA/B選定（CTR・SEO・感情3軸比較） | タイトル生成・選定はしない。eevee確定後のタイトルを採点対象にする |
| gengar | SEO・コンテンツ品質・リスク技術監査 | 「情報は正しいが退屈」を捕捉する感情・体験監査役 |
| arceus | 全エージェント統括・最終承認/却下 | gardevoir は arceus への入力として刺さりスコアを提供。最終承認権は arceus |

### フォールバック

**なし（フォールバック代替禁止）。** `retry_handler.py` の FALLBACK_MAP に登録しないこと。刺さり判定は他のエージェントで代替できない責務であるため、失敗時はERROR扱いで継続しない。

### 「技術OKでも刺さらなければ公開しない」運用原則

ファクト・SEO・フォーマットが全て合格した記事でも、以下の状態では読者に届かない:
- タイトルがクリックされない（情報羅列型）
- 冒頭3行で離脱される（「〜について解説します」型）
- SNSで保存・共有されない（感情を動かさない）

これらを止めるのが gardevoir_hook_critic の唯一の役割。arceus が承認する記事は、技術・ファクト・刺さり の3軸が全て揃ったものだけとなる。

### 止まる記事の具体例

| パターン | VERDICT | 理由 |
|---------|---------|------|
| 「BTS 新曲リリースについてまとめました」 | HARD_FAIL | タイトルに感情・数字なし。冒頭が他人事 |
| 「ガラス肌の作り方。韓国コスメが人気です」 | SOFT_RETRY | 商品名・手順なし。「人気です」で終わる |
| 「【2024年版】BTS ジョングク 7つのセルフケア術」 | PASS | 数字あり、推し目線、手順が想像できる |


---

## エージェント責務固定表（全26エージェント）

最終確定: 2026-04-11。実装（パイプラインコード）を正として定義と照合済み。

### 分類定義

| ROLE_CLASS | 意味 |
|-----------|------|
| CORE | パイプライン正常動作に必須。欠けると記事が出力されないか品質が著しく低下する |
| SUPPORT | 欠けても記事は公開できるが、品質・収益・拡散に影響する |
| MERGE_CANDIDATE | 別エージェントと統合・整理の候補。現時点は維持するが中長期で整理対象 |
| MANUAL_ONLY | cronパイプラインに組み込まない。手動発注専用 |

---

### 全エージェント一覧表（26体）

#### A. kpop 記事パイプライン（breaking / strategy / chart）

| # | エージェント | ROLE_CLASS | パイプライン配置 | 主責務 | 前工程→後工程 | フォールバック可否 |
|---|-------------|-----------|----------------|--------|------------|----------------|
| 1 | mewtwo | CORE | breaking=step0 / strategy=step7 | 全レポート統合・記事テーマ意思決定（編集長） | [breaking]なし→deoxys / [strategy]venusaur→deoxys | 不可（テーマ指定モードはskip可） |
| 2 | deoxys_kpop | CORE | breaking=step1 / strategy=step8 | 記事HTML本文ゼロ生成（WebSearch付き） | mewtwo→metamon | 緊急時のみ metamon_kpop で代替（品質低下許容） |
| 3 | metamon_kpop | CORE | breaking=step2 / strategy=step9 | deoxys生成記事のSEOリライト・タイトル3案生成 | deoxys→eevee | 緊急時のみ deoxys_kpop で代替 |
| 4 | eevee | CORE | breaking=step2.5 / strategy=step10 | タイトル複数案からCTR・SEO・感情3軸で最終1案選定 | metamon→jirachi(breaking)/alakazam_kpop(strategy) | 不可（失敗時はmetamon出力タイトルをそのまま使用） |
| 5 | jirachi_kpop | CORE | breaking=step3 / strategy=step5（並列） | **breaking**: ファクトチェック・時制整合・FAIL出力で停止（止める型） / **strategy**: 72hバズ予測・時事リスク評価（reports/5_future.md） | [breaking]eevee→gardevoir / [strategy]並列→mewtwo | breaking失敗時: alakazam_kpop がフォールバック（FAILゲートは消える） |
| 6 | gardevoir_hook_critic | CORE | breaking=step3.5 / strategy=step13.5 | 刺さり品質ゲート（SCORE採点・PASS/SOFT_RETRY/HARD_FAIL判定） | [breaking]jirachi→arceus / [strategy]kairyu→arceus | 不可（刺さり判定は代替不可能） |
| 7 | arceus | CORE | breaking=step4 / strategy=step14 | 全エージェント採点・「✅投稿承認 / ❌投稿却下」2択最終判定 | gardevoir→投稿処理 | 不可（最終判定は単一エージェントであるべき） |
| 8 | butterfree | CORE | strategy=step1のみ | WebSearchでK-POPトレンド収集・優先度スコア付きレポート生成 | なし（起点）→lapras | 不可（代替するとトレンド情報ゼロになる） |
| 9 | lapras | CORE | strategy=step2のみ | butterfreeレポートからSEOキーワード戦略設計 | butterfree→mimikyu | なし |
| 10 | mimikyu | CORE | strategy=step3のみ | laprasキーワードで競合記事WebSearch調査・差別化ポイント設計 | lapras→wobbuffet/jirachi（並列） | なし |
| 11 | wobbuffet | SUPPORT | strategy=step4（並列） | K-POPファン行動心理・読者ニーズ4層分析 | mimikyu→venusaur | なし（欠けると読者心理インプットが消えるが動作継続） |
| 12 | venusaur | CORE | strategy=step6のみ | lapras/mimikyu/wobbuffetを統合してdeoxysへの記事設計図（H2構成・KW配置）を生成 | wobbuffet/jirachi→mewtwo | なし |
| 13 | alakazam_kpop | MERGE_CANDIDATE | strategy=step11 / chart=step2 | 記事の日付・時制・固有名詞・誇張を修正して完成記事出力（修正して続行する型） | [strategy]eevee→gengar / [chart]zapdos→(arceus相当) | jirachi_kpop のフォールバック先（削除禁止） |
| 14 | gengar | CORE | strategy=step12のみ | SEO・品質・リスク3観点最終監査。修正可能問題は自分で修正 | alakazam_kpop→kairyu | なし |
| 15 | kairyu_kpop | SUPPORT | strategy=step13のみ | CTA・関連記事誘導・SNSシェア促進を追加してCVR・回遊率向上 | gengar→gardevoir | なし（欠けても記事は公開されるが収益導線が消える） |
| 16 | persian | SUPPORT | strategy=step15 / chart=step4 | X投稿文3パターン・ハッシュタグ・タイミング設計 | arceus→X投稿 | なし（失敗許容。FALLBACK_MAP: []） |
| 17 | zapdos | CORE | chart=step1のみ | Billboard/Melon/OriconチャートWebSearch取得・ランキング記事HTML生成 | なし（chart起点）→alakazam_kpop | 緊急時のみ deoxys_kpop で代替（品質低下あり） |
| 18 | beautywriter | CORE | kpop_pipeline=step1相当（master_schedulerのbeautyタイプ時） | 韓国コスメ・美容記事のゼロ生成（deoxys_kpopの美容特化版） | mewtwo→metamon | なし（未実装。失敗時はエラー終了） |
| 19 | mewtwo_popup | CORE | kpop_pipeline=step1相当（master_schedulerのイベントトレンド検出時） | ポップアップ・イベント・来日記事のゼロ生成（deoxys_kpopのイベント特化版） | mewtwo→metamon | なし |
| 20 | articuno | MANUAL_ONLY | なし（cronパイプライン未接続） | SNSバズコンテンツ（感情共感型・驚き発見型）の記事設計・生成 | 手動発注のみ | なし |

#### B. 週次レビュー・改善サイクル（kpop_weekly_review.sh）

| # | エージェント | ROLE_CLASS | パイプライン配置 | 主責務 | 前工程→後工程 | フォールバック可否 |
|---|-------------|-----------|----------------|--------|------------|----------------|
| 21 | porygon | SUPPORT | weekly_review=step1 | 週次パイプライン成功率・記事テーマ偏り・停止原因・PVトレンドを数値分析してルギアへレポート | なし→lugia | なし（週次バッチ。失敗時はスキップ） |
| 22 | lugia | SUPPORT | weekly_review=step2 | porygonのデータ分析を受け来週の戦略（重点テーマ・改善エージェント・やめること）を決定 | porygon→(自律改善エンジン) | なし（週次バッチ。失敗時はスキップ） |

#### C. ai_company 専用（日次会議・インフラ監視）

| # | エージェント | ROLE_CLASS | パイプライン配置 | 主責務 | 前工程→後工程 | フォールバック可否 |
|---|-------------|-----------|----------------|--------|------------|----------------|
| 23 | meowth | SUPPORT | ai_company日次会議（agent_council.sh / run_ai_meeting.sh） | 収益導線・マネタイズ方針の評価・提案（kpop記事パイプライン直接接続なし） | 合議体→arceus | なし |
| 24 | porygon_z | SUPPORT | ai_company（auto_repair.sh / run_ai_meeting.sh） | インフラ監視・障害根本原因分析・自動修復・再発防止策提案 | 障害検知→修復 | なし |

#### D. 未接続（定義のみ存在・cronパイプライン呼び出し実績なし）

| # | エージェント | ROLE_CLASS | 状態 | 重複する実働エージェント |
|---|-------------|-----------|------|---------------------|
| 25 | alakazam | MANUAL_ONLY | 呼び出し実績なし | eevee / metamon_kpop（タイトル生成・選定が重複） |
| 26 | mewtwo_cosme | MANUAL_ONLY | 呼び出し実績なし | beautywriter（美容記事生成が重複） |
| 27 | popupwriter | MANUAL_ONLY | 呼び出し実績なし | mewtwo_popup（イベント記事生成が重複） |
| 28 | snorlax | MANUAL_ONLY | 呼び出し実績なし（docs/runbookで言及のみ） | deoxys_kpop（レビュー・比較記事は未接続） |

---

### 重複禁止ルール一覧

| 責務 | 担当 | 重複禁止理由 |
|------|------|------------|
| 記事本文ゼロ生成 | deoxys_kpop / zapdos | zapdosはチャート専用、deoxysは速報・戦略記事専用。交差禁止 |
| タイトル生成 | metamon_kpop | eeveeはタイトル「選定」のみ。タイトル生成はmetamonの責務 |
| タイトル最終選定 | eevee | metamonが生成した複数案から1案を選ぶのがeeveeの唯一の責務 |
| ファクトチェック（止める型） | jirachi_kpop | FAILを出してパイプラインを止める権限はjirachiのみ |
| ファクトチェック（修正・続行型） | alakazam_kpop | 修正して出力し続けるのがalakzamの責務。jirachiと重複させない |
| 刺さり品質判定 | gardevoir_hook_critic | 感情・体験面の採点はgardevoir専任。代替不可 |
| SEO/品質/リスク技術監査 | gengar | gardevoir_hook_criticとの違い：「情報が正しいか」vs「読みたいか」 |
| 最終投稿承認/却下 | arceus | 2択判定は arceus のみ。gengar・gardevoir は判定を「出さない」 |
| 戦略統合・テーマ意思決定 | mewtwo | butterfree等は情報収集役。mewtwoが最終テーマを決定する |
| CVR・回遊導線 | kairyu_kpop | gengarやarceus との役割分離済み。記事事実を変えない |
| SNS投稿文設計 | persian | post_to_x.sh（実投稿実行）とは分離済み |

---

### フォールバック可否まとめ

| エージェント | フォールバック先 | 備考 |
|-------------|---------------|------|
| deoxys_kpop | metamon_kpop | 緊急のみ・品質低下許容 |
| metamon_kpop | deoxys_kpop | 緊急のみ |
| jirachi_kpop | alakazam_kpop | FAILゲートが消えるが続行可。alakazam削除禁止 |
| zapdos | deoxys_kpop | 品質低下あり |
| persian | （なし・失敗許容） | 記事は既に公開済みのため |
| eevee | （なし） | 失敗時はmetamon出力タイトルをそのまま使用 |
| arceus | **絶対禁止** | 最終判定は単一エージェントであるべき |
| gardevoir_hook_critic | **絶対禁止** | 刺さり判定は代替不可能な責務 |
| mewtwo | **不可**（テーマ指定モードはskip） | 編集長判断は代替不可 |
| butterfree/lapras/mimikyu/venusaur/gengar/kairyu | なし | 欠けると品質低下するが独自の代替なし |

---

### 実装と定義の不一致（修正済み一覧）

| エージェント | 不一致内容 | 修正 |
|------------|----------|------|
| mewtwo | ROLE_CLASS等frontmatter5項目が欠落 | 今回追加済み |
| alakazam_kpop | PIPELINE_POSITION=strategy=step10 だが実装は [11/15] | strategy=step11 に修正済み |
| jirachi_kpop | PRIMARY_RESPONSIBILITYが「ファクトチェック」のみでstrategy役割（リスク予測）が未記載 | 両役割を明記するよう修正済み |
| beautywriter / mewtwo_popup / porygon / lugia / meowth / porygon_z | frontmatter5項目が完全欠落 | 今回追加済み |
| alakazam / mewtwo_cosme / popupwriter / snorlax | frontmatter5項目が欠落、かつ実呼び出し実績なし | MANUAL_ONLYとして定義、重複する実働エージェントを明記済み |

### 最小運用で残すべきエージェント

**最小構成（これだけで記事を1本出せる）:**
- mewtwo（テーマ判断） → deoxys_kpop（生成） → metamon_kpop（リライト） → eevee（タイトル） → jirachi_kpop（ファクト） → gardevoir_hook_critic（刺さり） → arceus（承認）

**削除してはいけないエージェント:**
- alakazam_kpop: jirachi_kpopのフォールバック先。削除するとbreaking全体のフォールバックが消える

**将来の整理候補:**
- alakazam_kpop: jirachiとの統合検討（MERGE_CANDIDATE）。ただしflのFAIL型と修正継続型の役割差は意図的なので慎重に

---

## X投稿品質判定の責務分担（Item 4）

X投稿に関わるコンポーネントの責務を明確に分離する。重複判定・再投稿ループを防ぐことが目的。

### 責務マップ

| コンポーネント | 責務 | やらないこと |
|-------------|------|------------|
| **persian** (agents/persian.md) | X投稿文の生成・フォーマット設計（v12.0準拠） | 実際の投稿実行・投稿済み判定 |
| **post_to_x.sh** | Xへの実際の投稿実行・X_SUCCESS フラグ記録 | 品質判定・フォーマット検証 |
| **post_audit.sh [7]** | X投稿未成功の自動再試行（スコア80以上かつ未投稿のみ・1回限り） | 投稿済み記事への再投稿 |
| **post_audit.sh [7b]** | v12.0フォーマット違反の検出と処理 | — |
| **post_audit.sh [⑤] X_SUCCESS guard** | 投稿済み（X_SUCCESS=1）記事への再投稿を絶対防止 | — |

### 判定フロー（未投稿 vs 投稿済み）

```
X投稿必要？ → post_audit [7] が判定
  ├─ X_SUCCESS=1（投稿済み）→ 再投稿しない（[⑤]ガード）
  ├─ STATUS != publish（draft）→ _X7_SKIP=1 でスキップ
  └─ X_SUCCESS=0 かつ publish → スコア確認
       ├─ SCORE < 80 → 再試行しない（品質不足）
       └─ SCORE >= 80 → post_to_x.sh を1回だけ呼ぶ

v12.0フォーマット違反 → post_audit [7b] が判定
  ├─ 投稿済み（X_SUCCESS=1）→ 警告ログのみ・再投稿しない（重複投稿禁止）
  └─ 未投稿 → 再生成・再投稿を試みる（[7b][⑤]）
```

> **[2256型仕様確定 2026-04-11実ログ]** 投稿済みX記事のv12.0違反はISSUESに追加しない。再投稿しない。draft化原因にしない。警告ログのみ記録。（post_audit.log 07:03 ID=2272 で3ループ連続確認済み）

---

### 【バグ修正記録】post_audit [7b] silent exit（2026-04-12 特定・修正）

**症状:** post_audit.log に `--- [7b] X投稿品質監査 ---` が記録された後、[8]以降のログが一切出ない。[7b]内部のalogも出ない。

**根本原因:**
1. post_audit.sh は `set -euo pipefail`（line 29）で動作する
2. [0] のスラッグ修正（`slug_generator.py` → WP API PATCH）が成功すると、line 189 で `POST_URL` が新URLに更新される
3. `x_post.log` には X投稿時（[0]実行前）の**旧URL**が記録されている
4. [7b] 冒頭 line 1159: `_X_URL_LINE=$(grep -nF "$POST_URL" logs/x_post.log | head -1 | cut -d: -f1)` が新URLを検索 → grep が no-match で exit 1
5. `set -o pipefail` により pipeline exit code = 1 → `set -e` がスクリプトを silent exit させる
6. fallback（タイトル先頭30文字でのgrep、line 1169-1171）に到達する前に終了するため、[7b]内部alogも[8]以降も出力されない

**修正内容（最小差分）:**
```bash
# 修正前（post_audit.sh line 1159）:
_X_URL_LINE=$(grep -nF "$POST_URL" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | head -1 | cut -d: -f1)

# 修正後:
_X_URL_LINE=$(grep -nF "$POST_URL" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | head -1 | cut -d: -f1 || true)
```
`|| true` により grep no-match の exit 1 を吸収。既存のタイトル先頭30文字fallback（line 1169-1171）がX投稿ログを正常に取得できる。

**再現確認:** `bash post_audit.sh 2286 "https://www.kpopjournal.tokyo/aespa-day2-20-3-4-gg-2026/" ...` で [7b]→[8]→[9]→[10]→[11] 到達を確認（2026-04-12）。

**影響範囲:** スラッグが修正される記事（`NG_DATE_IN_SLUG` 等）ではほぼ毎回発生していた。slug修正なし記事は旧URL=現URLのため影響なし。

**因果連鎖:** この silent exit が [8]-[13] 全体（GSC登録・ファクトチェック確認・内部リンクチェック・[11b] href="#"除去など）を未到達にしていた主因。[7b] 修正により [11b] への到達経路が復旧した（[11b] 本番発火はまだ未観測）。

---

### 「再投稿しない」原則

投稿済みX記事への再投稿は以下の理由で絶対禁止：
1. X（Twitter）の重複投稿ルール違反になりうる
2. フォロワーへのスパム扱いとなり信頼を損なう
3. 同じ記事URLが複数回流れると SEO・クリック分散が起きる

**投稿済み記事のフォーマット違反は「次回から改善」でエージェント指令に落とすだけ。**

---

## LLM判定 vs Shell/Python判定の棚卸し（Item 5）

LLMに任せなくていい決定論的チェックを整理し、コスト・速度・信頼性を改善する。

### 現在の判定分類表

| チェック内容 | 現在の担当 | 移行先候補 | 移行状況 |
|------------|---------|-----------|---------|
| タイトル文字数（24〜38文字） | post_audit Shell grep | **実装済み** (Shell) | ✅ 完了 |
| 本文テキスト文字数（≥800文字） | post_audit Shell python3 | **実装済み** (Shell/python3) | ✅ 完了 |
| K-POPキーワード有無（タイトル） | 【旧: LLM】 | **実装済み** (Shell: pre_arceus_guard [3.9]) | ✅ 2026-04-11追加 |
| K-POPキーワード無し→プレフィクス付与 | 【旧: LLM】 | **実装済み** (post_audit [2b] Shell) | ✅ 2026-04-11追加 |
| 憶測語パターン検出（gossip） | post_audit python3 re | **実装済み** (Python regex) | ✅ 完了 |
| 情報元セクション存在チェック | post_audit python3 re | **実装済み** (Python regex) | ✅ 完了 |
| スラッグ文字種チェック | post_audit Shell | **実装済み** (Shell) | ✅ 完了 |
| HTML文字数チェック | post_audit Shell | **実装済み** (Shell) | ✅ 完了 |
| WPステータス (publish/draft) | post_audit Shell WP API | **実装済み** (Shell curl + jq) | ✅ 完了 |
| X投稿済みフラグ (X_SUCCESS) | post_audit Shell | **実装済み** (Shell grep) | ✅ 完了 |
| pipeline外WP公開記事の検出 | 【旧: 手動】 | **実装済み** (Python: post_watchdog.py) | ✅ 2026-04-11追加 |
| エージェント役割逸脱チェック | **audit_agent_roles.py** | Python (決定論的ルール) | ✅ 完了 |
| タイトル品質スコア（CTR/SEO/感情） | **LLM (eevee)** | 移行不可（創造的判断） | — LLM確定 |
| 刺さり品質スコア（感情・フック） | **LLM (gardevoir)** | 移行不可（感情判定） | — LLM確定 |
| 記事内容のファクトチェック | **LLM (jirachi)** | 移行不可（意味理解が必要） | — LLM確定 |
| arceus最終承認 | **LLM (arceus)** | 部分移行済み（pre_arceus_guard でハードガード） | 一部Shell化 |
| gossip一次ソース確認 | **LLM (deoxys/scheduler)** | 移行不可（URLコンテンツ解釈が必要） | — LLM確定 |

### 今後の移行候補（未実装）

| チェック内容 | 移行先候補 | 期待効果 |
|------------|-----------|---------|
| サムネジャンル一致（簡易版: ファイル名でジャンル推定） | Shell/Python filename check | arceus呼び出し前に弾ける |
| 重複記事タイトル検出（既投稿タイトルとの類似度） | Python difflib or hash check | LLM重複確認を削減 |
| HTML構造チェック（h1/h2の存在・img altなど） | Python html.parser | gengar呼び出し前に弾ける |

**移行判断基準:** 「正解が一意に決まる判定」はShell/Pythonへ。「文脈・意味・感情の判断」はLLMへ。

---

## 実装状態の分類定義（Item 7）

修正・追加した機能の実用状態を4段階で管理する。

### 状態定義

| 状態 | 意味 |
|------|------|
| **実装済み** | コードが存在し、構文チェック(bash -n / py_compile)通過 |
| **syntax checked** | `bash -n` / `python3 -m py_compile` で文法エラーなし確認済み |
| **dry-run verified** | `--dry-run` または手動テストで動作確認済み。本番データなし |
| **再現確認済み** | 本番相当の条件で問題を再現し修正を確認済み。本番cron経路での観測は未実施 |
| **本番観測済み** | 実パイプライン実行時のログ/出力で効果を確認済み |

### 主要機能の実装状態一覧（2026-04-12 更新）

#### 実装済み・本番観測済み

| 機能 | 実装場所 | 観測根拠 |
|------|---------|---------|
| X_SUCCESS guard [⑤] | post_audit.sh | 2256型再発ゼロで効果確認済み |
| Arceus却下検出修正 | post_audit.sh | 2256型修正後、過剰却下ループ解消確認済み |
| gardevoir HARD_FAIL時の詳細JSONL記録 | 両パイプライン | logs/gardevoir_hook.jsonl に run_id 付きエントリ確認済み（HARD_FAILのみ） |
| post_audit [2b] K-POPプレフィクス付与 | post_audit.sh | post_audit.log 2026-04-12 17:55:07 に `[2b] Hearts2Hearts タイトルK-POPキーワードなし → 追記` 記録確認済み |
| post_audit [7b] silent exit 修正 | post_audit.sh | ID=2310（2026-04-12 19:49）: slug修正あり記事（`hearts2hearts-11-ive-4-2026-pop-20260412` → `hearts2hearts-rude-11-ive-4-kpop-2026`）で `--- [7b] X投稿品質監査 ---` → `ℹ️ X投稿スコア: PRE_SCORE: 81.0/100` → `--- [8]` 以降継続を本番cronログで確認 |
| improvement_engine User-Agent 追加 | improvement_engine.sh | 2026-04-12 21:30 cron run: `Discord通知完了` 記録あり・同run内 `HTTP Error 403` なし（本番Discord到達確認） |
| gardevoir SCOREパース多フォーマット対応 | kpop_strategy_pipeline.sh / kpop_pipeline.sh | pipeline.jsonlに `score=81/88/88/82/91` 等の実数値確認（2026-04-12 複数run） |
| gardevoir_hook.jsonl 全verdict に run_id 追加（PASS/SOFT_RETRY含む） | 両パイプライン | PASSエントリに `"run_id": "20260412_180031"` 等フィールドあり（gardevoir_hook.jsonl確認済み） |
| post_watchdog 通知クールダウン 24h | lib/post_watchdog.py | `logs/watchdog_notif_cooldown.json` 生成・`recurring_error_patterns` / `pipeline_external_wp_post` エントリあり（2026-04-11確認） |
| post_watchdog external_wp検知 | lib/post_watchdog.py | `watchdog_alerts.jsonl` に `pipeline_external_wp_post` エントリ複数確認（2026-04-12: post_id=2234/2241/2249 を実データで検知・Discord通知済み） |

#### 実装済み・再現確認済み（本番cron経路での観測は未実施）

| 機能 | 実装場所 | 状態 | 昇格条件 |
|------|---------|------|---------|
| improvement_engine 品質比率集計 | improvement_engine.sh | **再現確認済み** | Pythonスクリプト単体で今日データから正常出力確認。syntax error 修正済み（2026-04-12）。修正後のcron runは次回21:30待ち。昇格条件: Discord通知に `📊 品質比率:` 行が表示され `[[: 0\n0: syntax error` が消滅 |

#### 実装済み・本番未観測（次回run以降に観測予定）

| 機能 | 実装場所 | 状態 | 昇格条件・未発火理由 |
|------|---------|------|---------|
| arceus前ハードガード [3.9] | kpop_pipeline.sh | **syntax checked** | pipeline.jsonlに `✅ GUARD:` 記録、または7日間誤検知ゼロ |
| arceus前ハードガード [13.9] | kpop_strategy_pipeline.sh | **syntax checked** | 同上 |
| gossip_source_guard | kpop_pipeline.sh / post_audit.sh | **dry-run verified** | gossip_source_guard.logなし（カテゴリ14のgossip記事が未実行）。初回実行で昇格 |
| post_audit [11b] href="#" 除去 | post_audit.sh | **本番到達済み** | 到達経路復旧済み・コード正常。未発火理由: 処理済み全記事にhref="#"なし（正常）。kairyu生成記事にhref="#"が含まれた時に初発火 |
| gardevoir VERDICTフォールバック（breaking側） | kpop_pipeline.sh | **syntax checked** | VERDICT行欠落時のみ発火。条件依存のためC維持 |
| kairyu_kpop.md href="#" 禁止明記 | agents/kairyu_kpop.md | **実装済み** | 次回kairyu実行記事にhref="#"が出なくなることを確認 |
| kpop_words リスト強化（Coachella等） | 両パイプライン | **実装済み** | Coachella等キーワードの記事が投稿停止されなくなる |

#### 要手動対応（自動解決不可）

| 案件 | 発生日 | 状態 | 対応内容 |
|------|------|------|---------|
| POST_ID=2272 draft化 | 2026-04-11 | ❌ **未復旧** | タイトルに「K-POP」等SEOキーワードを手動追加してpublish。自動修正ループ3回失敗のため自動解決不可。WordPress管理画面から直接編集すること。 |

#### 中長期改善候補（Phase 6）

| 項目 | 優先度 | 備考 |
|------|-------|------|
| 勝ち記事の横展開・再生成 | 高 | CTR/PV上位記事の関連記事自動生成 |
| 内部リンク3本以上自動挿入 | 中 | 現状はkairyu任せ |
| A/Bテスト用2パターンサムネ生成 | 中 | 現状は1パターン固定 |
| gardevoir_hook.jsonl の旧エントリrun_id遡及補完 | 低 | 修正前エントリはタイムスタンプ+pipeline.jsonl突合で代替可 |
| kpop_words breaking/strategy の統一（Girls Generation欠落） | 低 | strategy側にGirls Generationが未追加 |
| post_log.json再構築 | 低 | 記事LTVランキング自動アクションの前提 |

### 「本番観測済み」昇格の条件

上記「実装済み・本番未観測」テーブルの「昇格条件」列を参照。条件を満たしたら本表を更新すること。

