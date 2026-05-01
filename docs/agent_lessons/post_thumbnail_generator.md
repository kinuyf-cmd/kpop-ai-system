## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → thumbnail_guard でBLOCK
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい
**6. 新品質基準は既存記事にも遡及適用** → 旧記事の放置禁止

違反時: draft化 + X投稿削除 + 担当社員への警告

---

# post_thumbnail_generator 品質ログ

- [2026-04-26|crisis_recovery] HARD_FAIL: kpop-thumbnail v6 (make_thumbnail_v6.py + compose_v6 + 実写真優先 + テキストゼロ + 1200x675) を必ず使用。PIL直描画・DALL-E生出力の直接アップロード禁止。生成後に必ず1200x675サイズ検証を行う (4/27 ダササムネ事故)
- [2026-04-26|crisis_recovery] 生成後検証: 1200x675解像度確認、ファイル名に v6_kpop_thumb プレフィックス必須、alt_text設定必須
- [2026-04-26|design_decision] YouTube公式サムネは latest/popular モードを記事種別で使い分け。channel_idはAPI初回検索でjsonキャッシュ
- [2026-04-26|3bug_incident_0427] HARD_FAIL: GPT出力に「TITLE:」「Title:」プレフィックスが残る場合がある。parse処理を信用せず、text_sanitizer.strip_template_labels()を必ず本文+タイトル両方に適用。GPTの出力フォーマットは不安定な前提で設計する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: ハングル/特殊文字を含むタイトルをDALL-Eプロンプトに渡すと豆腐文字化する。make_thumbnail_v6のプロンプトは英語で構成し、タイトル文字を画像に含めない(TEXT ZERO原則)。popup記事は別CPTのためサムネ一括再生成の対象から漏れやすい — 明示的にpopup CPTもスキャン対象に含める
- [2026-04-26|3bug_incident_0427] HARD_FAIL: 既にYouTube MV画像が設定済みの記事を再生成するとDALL-E fallbackが発動し、MV画像を上書きする。regenerate_for_post()に「既存v6 MV画像があればスキップ」保護を追加済。記事修正時のサムネ再生成は不要な場合がある — 本文修正のみならサムネは触らない
- [2026-04-26|itzy_3rd_overwrite] HARD_FAIL: generate_and_attach (cron経路) にもMV画像保護が必須。regenerate_for_postだけでなく全経路に保護を入れること。ファイル名に v6_mv_ または v6_kpop_thumb (dalleを含まない) があればスキップ
- [2026-04-26|thumbnail_guard_mandatory] HARD_FAIL: サムネ(featured_media)の更新は必ず lib/thumbnail_guard.safe_update_featured_media() を経由すること。直接WP APIでfeatured_mediaを書き換えるコードは禁止。MV画像は自動保護される (教訓#40 ITZY 3回上書き事故)
- [2026-04-26|h2h_retroactive_audit] HARD_FAIL: 新品質基準を導入したら、既存記事への「遡及監査」も必ず実行。新基準=今後の記事のみ、は不十分 (Hearts2Hearts事案 4/27)
- [2026-04-26|h2h_retroactive_audit] 公開直後にサムネ+OGP+ソース の3点セットが揃っていることを確認してからX投稿する。1つでも欠けていたらX投稿を保留
- [2026-04-26|h2h_retroactive_audit] unified_publisher以外の経路（直接WP API投稿、Claude手動投稿等）で作成された記事は fact_checker ゲートを通っていない。cron監査で遡及チェック必須
- [2026-04-26|ogp_artist_mismatch] HARD_FAIL: YouTube API検索(_resolve_channel_id)は未登録アーティストに対し無関係なチャンネル(BTS/BLACKPINK)を返す。aespa記事にBTS画像が設定される事故が4件発生。対策: (1) API検索フォールバック廃止→official_accounts.json登録済みチャンネルのみ使用 (2) resolve()でattribution/アーティスト名不一致をBLOCK (3) full_audit_engineにcheck_ogp_image_relevance追加 (4) error_patterns.json登録
- [2026-04-26|ogp_artist_mismatch] 新アーティストのサムネを正しく生成するには、先にconfig/official_accounts.jsonにchannel_idを登録すること。未登録の場合はWikimedia→Unsplash→DALL-Eの順でフォールバックし、誤アーティスト画像は使われない
