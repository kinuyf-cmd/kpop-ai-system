# MAMA 2026「投票」クエリ獲得:既存ハブへのFAQ schema追加

- 日付: 2026-06-17
- 種別: SEO(Lane C = 既存記事押し上げ)
- 対象クエリ: 「mama 2026 投票」およびその近縁(投票方法/いつから/無料/京セラドーム)

## 背景と前提(Web検索・実機で確定済)

- **MAMA 2026 開催: 2026年11月20日(金)・21日(土)、京セラドーム大阪**(PRTIMES/Mnet公式で裏取り)。
- **投票方法・開始時期は2026年6月時点で未発表**(公式未告知)。→ 投票手順の確定情報はまだ書けない。憶測禁止。
- 自社に既存ハブ記事が存在: `/mama-awards-2026-osaka-guide/`(以下 #4826。post_id は実装時に実機で確認)。
  既にインデックス済み、タイトルに「投票」を含み、`site:` 検索で上位表示。
- #4826 には既に投票セクション(H2「ファン必見:投票が…」)があり、2025方式の説明・2026未発表明記・2025投票ガイドへの内部リンクまで実装済み。**FAQ は無い**。
- GSC機会データの実需要は「mama 2025 投票方法」imp1720。毎年恒例イベントのため2026に再来すると見て先取り([[seo-future-event-hub-articles]] の随時更新ハブ方式)。

## 決定:新規記事は作らない。#4826 に FAQ(可視HTML + FAQPage JSON-LD)を追加する

理由:
- 新規記事は #4826 とカニバリ([[seo-rewrite-over-new-articles-check-existing]])。
- 投票方法が未発表のため新規フル記事は中身が薄い。
- 「mama 2026 投票」の検索意図(いつから?方法は?無料?)は **FAQ 形式が最も合致**し、Google リッチリザルトに乗る([[lane-c-faq-schema-push]]:既存記事の停滞主因は FAQPage 構造化データ不在)。
- 投票セクション本文は既に良好 → 大幅書換えはせず FAQ 追加が主軸(本文書換えは事故歴あり [[demon-hunters-sequel-expansion]])。

## アプローチ:既存ツール `tools/seo/lane_c_faq_blocks.py` を踏襲

このツールは `ARTICLES` dict の `post_id: [(質問, 回答), ...]` から
「可視FAQ HTML + FAQPage JSON-LD」を生成し `reports/lane_c_faq_patches/post_<id>_faq.html` に出力する。
本番反映は owner が `kpop-wp-rw.sh post update <id>`(直接渡し・stdin禁止 [[wp-post-update-stdin-piping-data-loss]])。

実装は `ARTICLES` に #4826 のエントリを1つ追加するだけ。既存4記事と同じ規律
(回答は本文記述 or 確定事実に一致、未確定は断定しない)を踏襲する。

## FAQ 内容(全てハルシネ防止 = 確定事実 or「未発表」明記)

| 質問 | 回答方針 |
|---|---|
| MAMA 2026 の投票はいつから始まりますか? | 2026年6月時点で未発表。例年は本番(11月)の数週間前に告知。発表され次第このページを更新。 |
| MAMA 2026 の投票方法は? | 例年は Mnet Plus アプリ経由のファン投票。2026の詳細は未発表。 |
| MAMA の投票は無料でできますか? | 例年は Mnet Plus アプリで無料投票が可能(投票数はアプリ内アクションで加算)。2026の方式は未確定。 |
| 受賞はファン投票だけで決まりますか? | いいえ。例年はグローバルの音源・再生データとファン投票を組み合わせて決定。 |
| MAMA 2026 はいつ・どこで開催されますか? | 2026年11月20日(金)・21日(土)、京セラドーム大阪(確定)。 |

注: 投票セクション本文に既存の2025ガイド内部リンクがあるため、本文側の追加変更は行わない(FAQ のみ)。

## やらないこと(YAGNI / 安全)

- 投票方法の憶測記述は一切しない(未発表は未発表と書く)。
- 新規記事を作らない。
- 投票セクション本文の大幅書換えをしない(FAQ ブロック追加のみ)。
- post_id を推定で使わない(実装の最初に実機で #4826 の数値IDを確認)。

## 実装手順(概要 — 詳細は writing-plans で)

1. #4826 の実 post_id を確認(`/mama-awards-2026-osaka-guide/` のスラッグから DB/REST で照合)。
2. `tools/seo/lane_c_faq_blocks.py` の `ARTICLES` に `<id>: [上記5 QA]` を追加。
3. ツール実行 → `reports/lane_c_faq_patches/post_<id>_faq.html` 生成。
4. 生成物を目視レビュー(可視FAQ と JSON-LD の整合、回答が事実通りか)。
5. owner が本番反映(関連記事見出しの直前に挿入、`kpop-wp-rw.sh post update`)。
6. 反映後 GSC 再インデックス申請([[always-gsc-submit-after-publish]]:
   `venv_kpi/bin/python3 lib/gsc_indexing.py --url <URL>`)。

## 成功基準

- post_<id>_faq.html が生成され、JSON-LD が Rich Results 妥当(FAQPage)。
- 本番反映後、#4826 が「mama 2026 投票」系クエリで FAQ リッチリザルト対象になる。
- 効果確認は反映の約1週間後に GSC のページ×クエリで imp/CTR を観測。
