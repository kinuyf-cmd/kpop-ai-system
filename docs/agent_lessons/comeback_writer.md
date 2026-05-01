## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → DALL-E上書き事故
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい

違反時: draft化 + X投稿削除 + 担当社員への警告

---

# comeback_writer 品質ログ

- [2026-04-26|crisis_recovery] 4/27緊急介入: NameError (fetch_category_id) で7回失敗していた。コード修正済。候補0件はシグナル不足であり正常動作
- [2026-04-26|crisis_recovery] 4/27緊急介入: NameError解消確認。候補0件はシグナル不足であり正常動作
- [2026-04-26|itzy_incident_mandatory] HARD_FAIL: ソースなしでGPT単独生成した記事は公開禁止。fact_checker.pyがBLOCKする。違反時は記事draft化+X投稿削除+担当社員への警告が自動実行される (4/27 ITZY事故)
- [2026-04-26|3bug_incident_0427] HARD_FAIL: GPT出力に「TITLE:」「Title:」プレフィックスが残る場合がある。parse処理を信用せず、text_sanitizer.strip_template_labels()を必ず本文+タイトル両方に適用。GPTの出力フォーマットは不安定な前提で設計する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: ハングル/特殊文字を含むタイトルをDALL-Eプロンプトに渡すと豆腐文字化する。make_thumbnail_v6のプロンプトは英語で構成し、タイトル文字を画像に含めない(TEXT ZERO原則)。popup記事は別CPTのためサムネ一括再生成の対象から漏れやすい — 明示的にpopup CPTもスキャン対象に含める
- [2026-04-26|3bug_incident_0427] HARD_FAIL: 既にYouTube MV画像が設定済みの記事を再生成するとDALL-E fallbackが発動し、MV画像を上書きする。regenerate_for_post()に「既存v6 MV画像があればスキップ」保護を追加済。記事修正時のサムネ再生成は不要な場合がある — 本文修正のみならサムネは触らない
- [2026-04-26|category_prevention] HARD_FAIL: 記事公開時にアーティストカテゴリを必ず設定。lib/auto_category.py の ensure_artist_categories() が自動検出+設定する。unified_publisher と post_audit_feedback_loop の両方に組込済。手動投稿時も必ずアーティスト名に対応するWPカテゴリ(parent=26)を設定すること (教訓#43)
