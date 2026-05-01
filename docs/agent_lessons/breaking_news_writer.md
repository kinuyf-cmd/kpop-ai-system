## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → thumbnail_guard でBLOCK
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい
**6. 新品質基準は既存記事にも遡及適用** → 旧記事の放置禁止
**7. 実名の匿名化は絶対禁止** → 「AとB」「XさんとYさん」等への置き換え禁止。ソース記載の実名をそのまま使用すること → fact_checker BLOCK
**8. 複数ソース混合時は最重要1件のみ記事化** → 無関係なニュースを1記事に混ぜない。事務所名(SM/YG)のみで同一クラスタに入った記事は特に注意

違反時: draft化 + X投稿削除 + 担当社員への警告

---
### スラッグ・品質ゲート (2026-04-29追加)
- slugは必ずASCII英数字+ハイフン。日本語slug/post-NNNN自動slug禁止
- 全記事最低800字。速報も800字以上が必須（GPTプロンプトは800-1200字指示）
- 重複タイトル禁止。WPがslugに-2を付けて黙って受理するので要注意

### LLM翻訳の主語誤認防止 (2026-04-29追加 — 事故発生)
- **事故**: ソース原文が"Fans announcing pregnancy at concerts"→記事で「アーティストが妊娠発表」と主語を誤訳。完全な虚報になった
- **対策**: fact_checker.pyにcheck_source_content_mismatch()を追加。ソースの主語(fans/idol/company等)と記事の主語が乖離している場合WARN
- **ルール**: 翻訳時はソース原文の主語(who)を最初に確認し、記事の主語と一致させること

### 数値主張の検証必須 (2026-04-29追加 — 事故発生)
- **事故**: JENNIE Dracula Remix「Spotifyで2億回達成」→実際は約1.1億回。ソースのファン投稿を無検証で採用
- **対策**: fact_checker.pyにcheck_numeric_claims()を追加。億/百万/million単位の数値はWARN発火
- **ルール**: 再生回数・売上・ランキング等の具体的数値は必ず公式データ(Spotify Charts, kworb.net等)で裏取り

### HTML二重ラップ防止 (2026-04-29追加)
- **事故**: GPTが`<p>...<h2>...</h2><p>...</p>`形式で出力→`f"<p>{text}</p>"`で二重ラップ→16件のunclosed_p
- **対策**: _wrap_body()ヘルパーでGPT出力にブロック要素が含まれていればラップしない


# breaking_news_writer 品質ログ

## 初期投入 (2026-04-26 13:02) — audit_feedback.jsonl 2件から集計

### 適用fix (Top10)
- 本文補強: 2494 → 3301文字 アイキャッチaltテキストを自動設定 サムネイル再生成・差し: 1件
- スラッグを修正: 0-april-17-kpop-chart-bts-swim-3weeks-kis: 1件

### 監査fix (2026-04-29)
- [audit_fix] 【速報】prefix付加後のタイトルは42字以内で切る（[:50]→[:42]に修正済み）
- [audit_fix] meta_descは80字未満の場合、body[:1000]→[:2000]→固定テンプレートの3段フォールバック
- [audit_fix] 速報記事でもsanitize_gpt_html()適用必須（unclosed_p/AI言及/casual表現を除去）

### 教訓
- [2026-04-26|error_pattern_analysis] 速報は150字以上必須 (Stage 1)。5W1H骨子を漏らさない
- [2026-04-26|r1_top11_30] Stage1の150字制約でも文末は丁寧に終わらせる (途切れ禁止)
- [2026-04-26|translation_lv2] アーティスト名は初出時のみ韓国語併記、以降は英語表記のみ
- [2026-04-26|translation_lv2] 楽曲名: 英語=引用符、日本語=鉤括弧、韓国語=初出時のみ括弧併記
- [2026-04-26|translation_lv2] 文末は連続3文以上同じ語尾禁止、分散させる
- [2026-04-26|translation_lv2] 年度は半角4桁、順位は半角数字
- [2026-04-26|lapras_case] import検証は単発テストで確認必須。cronログ上は正常に見えても例外で停止している場合がある (ラプラス事案)
- [2026-04-26|itzy_factcheck_incident] HARD_FAIL: GPT単独で「最新ニュース」記事を書かせない。必ず実ソース(シグナル/Web検索結果/ニュースURL)を元に執筆。ソースなし記事はfact_checkerがBLOCKする (4/27 ITZY事故)
- [2026-04-26|itzy_incident_mandatory] HARD_FAIL: ソースなしでGPT単独生成した記事は公開禁止。fact_checker.pyがBLOCKする。違反時は記事draft化+X投稿削除+担当社員への警告が自動実行される (4/27 ITZY事故)
- [2026-04-26|itzy_incident_mandatory] 記事をdraft化した場合、紐づくX投稿も即時削除すること。x_posts.jsonlからtweet_idを取得し、X API DELETE /2/tweets/{id} で削除する
- [2026-04-26|title_leak_incident] GPT出力の1行目「TITLE: xxx」は除去必須。parse時にstartswith("TITLE:")で分離すること
- [2026-04-26|3bug_incident_0427] HARD_FAIL: GPT出力に「TITLE:」「Title:」プレフィックスが残る場合がある。parse処理を信用せず、text_sanitizer.strip_template_labels()を必ず本文+タイトル両方に適用。GPTの出力フォーマットは不安定な前提で設計する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: ハングル/特殊文字を含むタイトルをDALL-Eプロンプトに渡すと豆腐文字化する。make_thumbnail_v6のプロンプトは英語で構成し、タイトル文字を画像に含めない(TEXT ZERO原則)。popup記事は別CPTのためサムネ一括再生成の対象から漏れやすい — 明示的にpopup CPTもスキャン対象に含める
- [2026-04-26|3bug_incident_0427] HARD_FAIL: 既にYouTube MV画像が設定済みの記事を再生成するとDALL-E fallbackが発動し、MV画像を上書きする。regenerate_for_post()に「既存v6 MV画像があればスキップ」保護を追加済。記事修正時のサムネ再生成は不要な場合がある — 本文修正のみならサムネは触らない
- [2026-04-26|thumbnail_guard_mandatory] HARD_FAIL: サムネ(featured_media)の更新は必ず lib/thumbnail_guard.safe_update_featured_media() を経由すること。直接WP APIでfeatured_mediaを書き換えるコードは禁止。MV画像は自動保護される (教訓#40 ITZY 3回上書き事故)
- [2026-04-26|h2h_retroactive_audit] HARD_FAIL: 新品質基準を導入したら、既存記事への「遡及監査」も必ず実行。新基準=今後の記事のみ、は不十分 (Hearts2Hearts事案 4/27)
- [2026-04-26|h2h_retroactive_audit] 公開直後にサムネ+OGP+ソース の3点セットが揃っていることを確認してからX投稿する。1つでも欠けていたらX投稿を保留
- [2026-04-26|h2h_retroactive_audit] unified_publisher以外の経路（直接WP API投稿、Claude手動投稿等）で作成された記事は fact_checker ゲートを通っていない。cron監査で遡及チェック必須
- [2026-04-26|category_miss_incident] HARD_FAIL: 記事作成時にアーティストカテゴリを必ず設定。ニュースカテゴリのみはNG
- [2026-04-26|category_prevention] HARD_FAIL: 記事公開時にアーティストカテゴリを必ず設定。lib/auto_category.py の ensure_artist_categories() が自動検出+設定する。unified_publisher と post_audit_feedback_loop の両方に組込済。手動投稿時も必ずアーティスト名に対応するWPカテゴリ(parent=26)を設定すること (教訓#43)
