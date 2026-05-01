## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → thumbnail_guard でBLOCK
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい
**6. 新品質基準は既存記事にも遡及適用** → 旧記事の放置禁止
**7. slugは必ずASCII英数字+ハイフン** → 日本語slug禁止、generate_slug()失敗時もフォールバックで保証
**8. 重複タイトルの記事を作らない** → WPがslugに-2を付けて黙って受理するため気づきにくい
**9. 記事最低文字数800字** → 速報含め全記事800字以上。GPTプロンプトは800-1200字指示
**10. 架空店舗の捏造は絶対禁止** → LLMは実在しない店名を生成する。カフェ/レストラン/ショップの「○選」記事は生成禁止。店舗紹介は必ず「店名・住所・営業時間・最寄駅」の4点セット必須。不明なら記事に含めない → pre_publish_gate でBLOCK

違反時: draft化 + X投稿削除 + 担当社員への警告

---
### 日付混同防止 (2026-04-29追加 — 事故発生)
- **事故**: ミンジ誕生日記事で「4月29日、特別な日がやってきました」と記載。実際の誕生日は5月7日。LLMがプロンプトの現在日付（today is 2026-04-29）を記事内容の「特別な日」と混同した
- **対策**: 誕生日・イベント開催日などの具体的日付を含む記事では、LLMプロンプトに正確な日付を明示的に渡すこと。「現在日付」と「記事の対象日付」は別物であることをプロンプトに注記
- **ルール**: 誕生日記事は公式プロフィールで生年月日を裏取りしてからタイトル・本文に反映。「今日は〇〇の誕生日」と書く場合は当日公開のみ許可

# feature_article_writer 品質ログ

## 初期投入 (2026-04-26 13:02) — audit_feedback.jsonl 16件から集計

### 頻出issue (Top10)
- OG画像が未設定: 2件
- BTSカテゴリが誤設定: 1件
- ALTテキストが空: 1件
- メタ説明が本文冒頭の流用: 1件
- 重複メタタグ: canonical 重複メタタグ: og:title: 1件
- X投稿PRE_SCOREが低い: 79.8（閾値80未満）: 1件
- サムネ再生成後alt空: media=4250: 1件

### 適用fix (Top10)
- GSCインデックス登録送信: 3件
- タグを自動生成して設定: [91] アイキャッチaltテキストを自動設定 GSCインデックス登録送信: 2件
- タグを自動生成して設定: [91] GSCインデックス登録送信: 2件
- 誤アーティストカテゴリを除去: 1件
- altテキスト自動設定: 1件
- メタ説明を独立設定: 1件
- タグを自動生成して設定: [91] GSCインデックス登録を再送信: 1件
- 本文補強: 1527 → 2989文字 メタ説明を自動生成して設定 タグを自動生成して設定: [91: 1件
- タグを自動生成して設定: [91] アイキャッチaltテキストを自動設定: 1件
- スラッグを修正: babymonster-3-rd-15-6-20260414 → babymons: 1件

### 教訓
- **OG画像が未設定** が2回検出 → 生成プロンプトの該当箇所を重点チェック
- **BTSカテゴリが誤設定** が1回検出 → 生成プロンプトの該当箇所を重点チェック
- **ALTテキストが空** が1回検出 → 生成プロンプトの該当箇所を重点チェック
- [2026-04-26|error_pattern_analysis] text_casual_question (9件): 「いかがでしょうか」「いかがだろうか」は禁止。代替: 「ぜひチェックしてほしい」「注目だ」
- [2026-04-26|error_pattern_analysis] content_short (6件): 本文は1200字以上必須。800字未満は品質不合格
- [2026-04-26|error_pattern_analysis] text_repeated_char: 同一文字5回以上連続 (!!!!! 等) は禁止
- [2026-04-26|r1_top11_30] meta_descriptionは80-160字で生成。短すぎ/長すぎは自動truncateされる
- [2026-04-26|r1_top11_30] タイトルは42字以内。超過分は…で省略される
- [2026-04-26|r1_top11_30] <p>タグは必ず閉じる。閉じ忘れはauditでhigh扱い
- [2026-04-26|r1_top11_30] 日本語比率30%以上を厳守、英語のみの段落を作らない
- [2026-04-26|translation_lv2] アーティスト名は初出時のみ韓国語併記、以降は英語表記のみ
- [2026-04-26|translation_lv2] 楽曲名: 英語=引用符、日本語=鉤括弧、韓国語=初出時のみ括弧併記
- [2026-04-26|translation_lv2] 文末は連続3文以上同じ語尾禁止、分散させる
- [2026-04-26|translation_lv2] 年度は半角4桁、順位は半角数字
- [2026-04-26|auto_audit] 4/27監査: no_gsc_indexing が4件検出。生成時に必ず回避すること
- [2026-04-26|auto_audit] 4/27監査: slug_encoded が3件検出。生成時に必ず回避すること
- [2026-04-26|auto_audit] 4/27監査: content_short が1件検出。生成時に必ず回避すること
- [2026-04-26|auto_audit_4_27] 4/27監査: slug_encoded を記事ID 1725 で検出。次回生成時に同パターンを回避
- [2026-04-26|auto_audit_4_27] 4/27監査: no_gsc_indexing を記事ID 4522 で検出。次回生成時に同パターンを回避
- [2026-04-26|auto_audit_4_27] 4/27監査: no_gsc_indexing を記事ID 4521 で検出。次回生成時に同パターンを回避
- [2026-04-26|auto_audit_4_27] 4/27監査: no_gsc_indexing を記事ID 4392 で検出。次回生成時に同パターンを回避
- [2026-04-26|auto_audit_4_27] 4/27監査: no_gsc_indexing を記事ID 4391 で検出。次回生成時に同パターンを回避
- [2026-04-26|lapras_case] import検証は単発テストで確認必須。cronログ上は正常に見えても例外で停止している場合がある (ラプラス事案)
- [2026-04-26|audit_6h] 6h監査: slug_encoded ID4695
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4695
- [2026-04-26|audit_6h] 6h監査: slug_encoded ID4694
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4694
- [2026-04-26|audit_6h] 6h監査: slug_encoded ID4693
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4693
- [2026-04-26|audit_6h] 6h監査: slug_encoded ID4692
- [2026-04-26|audit_6h] 6h監査: no_thumbnail ID4692
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4692
- [2026-04-26|audit_6h] 6h監査: slug_encoded ID4691
- [2026-04-26|audit_6h] 6h監査: no_thumbnail ID4691
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4691
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID1725
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID1728
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID2954
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID3143
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID3911
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4027
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4037
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4123
- [2026-04-26|audit_6h] 6h監査: no_gsc_indexing ID4265
- [2026-04-26|itzy_factcheck_incident] GPTの学習データは最大2年古い。「最新」「2026年」を含む記事は必ず実ソースURL必須。fact_checker.check_article()がpre-publishゲートで検証する
- [2026-04-26|itzy_incident_mandatory] HARD_FAIL: ソースなしでGPT単独生成した記事は公開禁止。fact_checker.pyがBLOCKする。違反時は記事draft化+X投稿削除+担当社員への警告が自動実行される (4/27 ITZY事故)
- [2026-04-26|itzy_incident_mandatory] 記事をdraft化した場合、紐づくX投稿も即時削除すること。x_posts.jsonlからtweet_idを取得し、X API DELETE /2/tweets/{id} で削除する
- [2026-04-26|title_leak_incident] GPT出力の1行目「TITLE: xxx」は除去必須。text_sanitizerで自動除去されるが、GPTプロンプトでも「TITLE:ラベルを本文に含めない」と明記すること
- [2026-04-26|3bug_incident_0427] HARD_FAIL: GPT出力に「TITLE:」「Title:」プレフィックスが残る場合がある。parse処理を信用せず、text_sanitizer.strip_template_labels()を必ず本文+タイトル両方に適用。GPTの出力フォーマットは不安定な前提で設計する
- [2026-04-26|3bug_incident_0427] HARD_FAIL: ハングル/特殊文字を含むタイトルをDALL-Eプロンプトに渡すと豆腐文字化する。make_thumbnail_v6のプロンプトは英語で構成し、タイトル文字を画像に含めない(TEXT ZERO原則)。popup記事は別CPTのためサムネ一括再生成の対象から漏れやすい — 明示的にpopup CPTもスキャン対象に含める
- [2026-04-26|3bug_incident_0427] HARD_FAIL: 既にYouTube MV画像が設定済みの記事を再生成するとDALL-E fallbackが発動し、MV画像を上書きする。regenerate_for_post()に「既存v6 MV画像があればスキップ」保護を追加済。記事修正時のサムネ再生成は不要な場合がある — 本文修正のみならサムネは触らない
- [2026-04-26|ogp_incident_0427] HARD_FAIL: popup詳細ページにgenerateMetadataが未実装だったため、全popup記事のOGP画像がog-default.pngになっていた。新規ページ作成時は必ず generateMetadata で og:image を featured_media の source_url から設定すること。_embed=true で取得した _embedded["wp:featuredmedia"][0].source_url を参照
- [2026-04-26|thumbnail_guard_mandatory] HARD_FAIL: サムネ(featured_media)の更新は必ず lib/thumbnail_guard.safe_update_featured_media() を経由すること。直接WP APIでfeatured_mediaを書き換えるコードは禁止。MV画像は自動保護される (教訓#40 ITZY 3回上書き事故)
- [2026-04-26|h2h_retroactive_audit] HARD_FAIL: 新品質基準を導入したら、既存記事への「遡及監査」も必ず実行。新基準=今後の記事のみ、は不十分 (Hearts2Hearts事案 4/27)
- [2026-04-26|h2h_retroactive_audit] 公開直後にサムネ+OGP+ソース の3点セットが揃っていることを確認してからX投稿する。1つでも欠けていたらX投稿を保留
- [2026-04-26|h2h_retroactive_audit] unified_publisher以外の経路（直接WP API投稿、Claude手動投稿等）で作成された記事は fact_checker ゲートを通っていない。cron監査で遡及チェック必須
- [2026-04-26|category_miss_incident] HARD_FAIL: 記事作成時にアーティストカテゴリを必ず設定する。ニュースカテゴリ(id=2)のみだと /artists/ のアーティストページに表示されない。parent=26(idol)の子カテゴリIDをWPで確認して設定 (4/27 ITZY/TWICE/BIGBANG カテゴリ漏れ)
- [2026-04-26|category_prevention] HARD_FAIL: 記事公開時にアーティストカテゴリを必ず設定。lib/auto_category.py の ensure_artist_categories() が自動検出+設定する。unified_publisher と post_audit_feedback_loop の両方に組込済。手動投稿時も必ずアーティスト名に対応するWPカテゴリ(parent=26)を設定すること (教訓#43)
- [2026-04-26|frontend-design-skill] UIデザイン: generic AI aesthetics を回避する。明確なコンセプト方向性を選び、一貫して実行する (frontend-design skill)
- [2026-04-26|frontend-design-skill] タイポグラフィ: system-ui/sans-serif のデフォルトフォントを避ける。コンセプトに合った特徴的なフォントを選ぶ
- [2026-04-26|frontend-design-skill] カラー: CSS変数で一貫したテーマ。K-POP JOURNALはcoral(#FF4E6B)/ink(#0D0D0F)/line(#E8E8EA)が基本
- [2026-04-26|frontend-design-skill] モーション: hover/transition は意図を持って。過剰なアニメーションより、micro-interactionの品質
- [2026-04-26|frontend-design-skill] レイアウト: 予想通りのグリッドだけでなく、非対称/重なり/対角線フローも検討する
