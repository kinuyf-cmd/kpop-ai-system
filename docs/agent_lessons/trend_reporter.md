## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → DALL-E上書き事故
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい

違反時: draft化 + X投稿削除 + 担当社員への警告

---

# trend_reporter 品質ログ

## 初期投入 (2026-04-26 13:02) — audit_feedback.jsonl 3件から集計

### 頻出issue (Top10)
- X投稿スキップ(score=78.8): 1件
- 最類似勝ちタイトル: 「K-POPアイドルの美肌ルーティン徹底解剖！…」(overlap=0.20): 1件
- OG画像が未設定: 1件

### 適用fix (Top10)
- タグを自動生成して設定: [91] GSCインデックス登録を再送信: 1件
- GSCインデックス登録送信: 1件

### 教訓
- **X投稿スキップ(score=78.8)** が1回検出 → 生成プロンプトの該当箇所を重点チェック
- **最類似勝ちタイトル: 「K-POPアイドルの美肌ルーティン徹底解剖！…」(overlap=0.20)** が1回検出 → 生成プロンプトの該当箇所を重点チェック
- **OG画像が未設定** が1回検出 → 生成プロンプトの該当箇所を重点チェック
- [2026-04-26|itzy_incident_mandatory] HARD_FAIL: ソースなしでGPT単独生成した記事は公開禁止。fact_checker.pyがBLOCKする。違反時は記事draft化+X投稿削除+担当社員への警告が自動実行される (4/27 ITZY事故)
- [2026-04-26|3bug_incident_0427] HARD_FAIL: GPT出力に「TITLE:」「Title:」プレフィックスが残る場合がある。parse処理を信用せず、text_sanitizer.strip_template_labels()を必ず本文+タイトル両方に適用。GPTの出力フォーマットは不安定な前提で設計する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: ハングル/特殊文字を含むタイトルをDALL-Eプロンプトに渡すと豆腐文字化する。make_thumbnail_v6のプロンプトは英語で構成し、タイトル文字を画像に含めない(TEXT ZERO原則)。popup記事は別CPTのためサムネ一括再生成の対象から漏れやすい — 明示的にpopup CPTもスキャン対象に含める
- [2026-04-26|3bug_incident_0427] HARD_FAIL: 既にYouTube MV画像が設定済みの記事を再生成するとDALL-E fallbackが発動し、MV画像を上書きする。regenerate_for_post()に「既存v6 MV画像があればスキップ」保護を追加済。記事修正時のサムネ再生成は不要な場合がある — 本文修正のみならサムネは触らない
