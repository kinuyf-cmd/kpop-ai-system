## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → thumbnail_guard でBLOCK
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい
**6. 新品質基準は既存記事にも遡及適用** → 旧記事の放置禁止

違反時: draft化 + X投稿削除 + 担当社員への警告

---
### スラッグ・品質ゲート (2026-04-29追加)
- slugは必ずASCII英数字+ハイフン。日本語slug/post-NNNN自動slug禁止
- 全記事最低800字。速報も800字以上が必須（GPTプロンプトは800-1200字指示）
- 重複タイトル禁止。WPがslugに-2を付けて黙って受理するので要注意

### タイトルベース重複防止 (2026-04-29追加 — 事故発生)
- **事故**: トイ・ストーリー5ポップアップが異なるURL(PRTIMES + 独自収集)から同一イベントとして2件ずつ公開。URL dedupでは防げなかった
- **対策**: popup_publisher.pyにタイトル先頭40字の重複チェック(seen_titles set)を追加
- **ルール**: 同一イベント名のsignalは最初の1件のみ採用。後続はskip


# popup_writer 品質ログ

- [2026-04-26|r1_top11_30] slug は20-60字英数kebab-case、日本語slug禁止
- [2026-04-26|r1_top11_30] 8項目構造化 (期間/営業時間/住所/概要/予約/特典/SNS/MAP) を全件埋める
- [2026-04-26|translation_lv2] アーティスト名は初出時のみ韓国語併記、以降は英語表記のみ
- [2026-04-26|translation_lv2] 楽曲名: 英語=引用符、日本語=鉤括弧、韓国語=初出時のみ括弧併記
- [2026-04-26|translation_lv2] 文末は連続3文以上同じ語尾禁止、分散させる
- [2026-04-29|audit_fix] popup記事のslugはgenerate_slug()でASCII生成必須。WPデフォルトは日本語URLエンコードされる
- [2026-04-29|audit_fix] popup本文はsanitize_gpt_html()でunclosed_p/文字重複/casual表現を投稿前に除去
- [2026-04-29|audit_fix] 「いかがでしたか」「いかがですか」等のcasual表現は全バリエーション禁止
- [2026-04-26|translation_lv2] 年度は半角4桁、順位は半角数字
- [2026-04-26|auto_audit_4_27] 4/27監査: slug_encoded を記事ID 4330 で検出。次回生成時に同パターンを回避
- [2026-04-26|auto_audit_4_27] 4/27監査: slug_encoded を記事ID 4328 で検出。次回生成時に同パターンを回避
- [2026-04-26|auto_audit_4_27] 4/27監査: content_short を記事ID 4326 で検出。次回生成時に同パターンを回避
- [2026-04-26|lapras_case] import検証は単発テストで確認必須。cronログ上は正常に見えても例外で停止している場合がある (ラプラス事案)
- [2026-04-26|itzy_incident_mandatory] HARD_FAIL: ソースなしでGPT単独生成した記事は公開禁止。fact_checker.pyがBLOCKする。違反時は記事draft化+X投稿削除+担当社員への警告が自動実行される (4/27 ITZY事故)
- [2026-04-26|itzy_incident_mandatory] 記事をdraft化した場合、紐づくX投稿も即時削除すること。x_posts.jsonlからtweet_idを取得し、X API DELETE /2/tweets/{id} で削除する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: GPT出力に「TITLE:」「Title:」プレフィックスが残る場合がある。parse処理を信用せず、text_sanitizer.strip_template_labels()を必ず本文+タイトル両方に適用。GPTの出力フォーマットは不安定な前提で設計する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: ハングル/特殊文字を含むタイトルをDALL-Eプロンプトに渡すと豆腐文字化する。make_thumbnail_v6のプロンプトは英語で構成し、タイトル文字を画像に含めない(TEXT ZERO原則)。popup記事は別CPTのためサムネ一括再生成の対象から漏れやすい — 明示的にpopup CPTもスキャン対象に含める
- [2026-04-26|3bug_incident_0427] HARD_FAIL: 既にYouTube MV画像が設定済みの記事を再生成するとDALL-E fallbackが発動し、MV画像を上書きする。regenerate_for_post()に「既存v6 MV画像があればスキップ」保護を追加済。記事修正時のサムネ再生成は不要な場合がある — 本文修正のみならサムネは触らない
- [2026-04-26|ogp_incident_0427] HARD_FAIL: popup詳細ページにgenerateMetadataが未実装だったため、全popup記事のOGP画像がog-default.pngになっていた。新規ページ作成時は必ず generateMetadata で og:image を featured_media の source_url から設定すること。_embed=true で取得した _embedded["wp:featuredmedia"][0].source_url を参照
- [2026-04-26|thumbnail_guard_mandatory] HARD_FAIL: サムネ(featured_media)の更新は必ず lib/thumbnail_guard.safe_update_featured_media() を経由すること。直接WP APIでfeatured_mediaを書き換えるコードは禁止。MV画像は自動保護される (教訓#40 ITZY 3回上書き事故)
- [2026-04-26|h2h_retroactive_audit] HARD_FAIL: 新品質基準を導入したら、既存記事への「遡及監査」も必ず実行。新基準=今後の記事のみ、は不十分 (Hearts2Hearts事案 4/27)
- [2026-04-26|h2h_retroactive_audit] 公開直後にサムネ+OGP+ソース の3点セットが揃っていることを確認してからX投稿する。1つでも欠けていたらX投稿を保留
- [2026-04-26|h2h_retroactive_audit] unified_publisher以外の経路（直接WP API投稿、Claude手動投稿等）で作成された記事は fact_checker ゲートを通っていない。cron監査で遡及チェック必須
- [2026-04-26|category_prevention] HARD_FAIL: 記事公開時にアーティストカテゴリを必ず設定。lib/auto_category.py の ensure_artist_categories() が自動検出+設定する。unified_publisher と post_audit_feedback_loop の両方に組込済。手動投稿時も必ずアーティスト名に対応するWPカテゴリ(parent=26)を設定すること (教訓#43)
- [2026-04-26|frontend-design-skill] UIデザイン: generic AI aesthetics を回避する。明確なコンセプト方向性を選び、一貫して実行する (frontend-design skill)
- [2026-04-26|frontend-design-skill] タイポグラフィ: system-ui/sans-serif のデフォルトフォントを避ける。コンセプトに合った特徴的なフォントを選ぶ
- [2026-04-26|frontend-design-skill] カラー: CSS変数で一貫したテーマ。K-POP JOURNALはcoral(#FF4E6B)/ink(#0D0D0F)/line(#E8E8EA)が基本
- [2026-04-26|frontend-design-skill] モーション: hover/transition は意図を持って。過剰なアニメーションより、micro-interactionの品質
- [2026-04-26|frontend-design-skill] レイアウト: 予想通りのグリッドだけでなく、非対称/重なり/対角線フローも検討する
