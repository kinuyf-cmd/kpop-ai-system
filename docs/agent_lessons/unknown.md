## ★★★ 最重要警告 ★★★

**1. ソースなし記事の公開は絶対禁止** → fact_checker BLOCK
**2. TITLE: プレフィックスの本文混入禁止** → text_sanitizer で自動除去
**3. ハングルをDALL-Eプロンプトに渡さない** → 豆腐文字化する
**4. 既存MV画像のある記事でサムネ再生成しない** → thumbnail_guard でBLOCK
**5. popup記事はサムネ/監査の対象漏れに注意** → 別CPTで見落としやすい
**6. 新品質基準は既存記事にも遡及適用** → 旧記事の放置禁止

違反時: draft化 + X投稿削除 + 担当社員への警告

---

# unknown 品質ログ

## 初期投入 (2026-04-26 13:02) — audit_feedback.jsonl 64件から集計

### 頻出issue (Top10)
- OG画像が未設定: 7件
- canonical が正しくない: https://www.kpopjournal.tokyo X投稿スキップ: 記事ステータス=draft — publish昇格後に手動再試行が必要: 6件
- メタ説明が本文冒頭の流用（独立したメタ説明を設定推奨）: 2件
- X投稿スキップ(score=66.0): 2件
- 文字数超過(292文字) -5: 2件
- K-POP関連ワード(KPOP) +3（アーティスト名代替）: 2件
- サムネイルテキストと記事タイトルが不一致: 1件
- カテゴリ誤混入:BTSキーワード単文字マッチ('v','rm','jin')が他グループ記事に誤検知: 1件
- ALTテキスト空:アップロード後のALT設定PATCHが未実装: 1件
- スラッグ__trashed:validate_post.pyに検出ロジックなし: 1件

### 適用fix (Top10)
- GSCインデックス登録送信: 15件
- アイキャッチaltテキストを自動設定 GSCインデックス登録送信: 7件
- タグを自動生成して設定: [91] GSCインデックス登録送信: 7件
- タグを自動生成して設定: [91] アイキャッチaltテキストを自動設定 サムネイル再生成・差し替え: 4件
- タグを自動生成して設定: [91] GSCインデックス登録を再送信: 2件
- タグを自動生成して設定: [91] アイキャッチaltテキストを自動設定 GSCインデックス登録送信: 2件
- サムネイル差し替え(thumbnail-13→2147): 1件
- タグ追加(ガールズグループ・5世代K-POP): 1件
- メタ説明を自動生成して設定 誤アーティストカテゴリを除去: [18, 43, 2] → [18, 2: 1件
- カテゴリルールにword boundary check追加: 1件

### 教訓
- **OG画像が未設定** が7回検出 → 生成プロンプトの該当箇所を重点チェック
- **canonical が正しくない: https://www.kpopjournal.tokyo X投稿スキップ: 記事ステータス=draft — publish昇格後に手動再試行が必要** が6回検出 → 生成プロンプトの該当箇所を重点チェック
- **メタ説明が本文冒頭の流用（独立したメタ説明を設定推奨）** が2回検出 → 生成プロンプトの該当箇所を重点チェック
- [2026-04-26|error_pattern_analysis] slug_encoded: 日本語slugは禁止。英数kebab-case 20-50字
- [2026-04-26|error_pattern_analysis] meta_desc_short: メタ説明は80-160字。excerpt自動生成ではなく独立した要約を設定
- [2026-04-26|error_pattern_analysis] unclosed_p/h2: HTMLタグの開閉数一致を確認してから出力
- [2026-04-26|r1_top11_30] meta_desc_long: 160字超過時は末尾…で切る
- [2026-04-26|r1_top11_30] title_long: 42字超過はタイトル最適化やり直し
- [2026-04-26|r1_top11_30] unclosed tags: HTML開閉タグ数の一致を出力前に検証する
- [2026-04-26|operational] 教訓#31: 部門単位の監視だけでは不十分。個別社員レベルで稼働・成長・エラーを評価する人事部が必要
- [2026-04-26|itzy_factcheck_incident] 教訓#35: ファクトチェック工程なしでGPT単独生成した記事は「2024年の情報を2026年最新として公開」する事故が起きる。unified_publisherにBLOCKゲート追加済
- [2026-04-26|itzy_incident_mandatory] HARD_FAIL: ソースなしでGPT単独生成した記事は公開禁止。fact_checker.pyがBLOCKする。違反時は記事draft化+X投稿削除+担当社員への警告が自動実行される (4/27 ITZY事故)
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
- [2026-04-26|security-guidance-skill] .envファイルへのkey追加時は前後の改行を必ず確認。行末改行欠落でkey結合バグが発生する (教訓#33)
- [2026-04-26|security-guidance-skill] .envファイルはgit管理外(.gitignore)を確認。API keyがcommitされないこと
- [2026-04-26|security-guidance-skill] credentials/tokenは伏字表示 (先頭15文字...末尾8文字)。ログに全文を出力しない
