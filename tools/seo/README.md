# SEO 計測ツール

> **実行は原則 `venv_kpi/bin/python3`**(cron も全て同じ)。`google-api-python-client` 等は
> system python に入っていないため、素の `python3` で叩くと `ModuleNotFoundError: No module named 'google'`
> で落ちる。例外は `gsc_inspect_h2.py`(googleapiclient 不要のため素の python3 でも動く)。

| ファイル | 役割 |
|---|---|
| `gsc_snapshot.py` | GSC実測スナップショット。トレンド(clicks/imp/CTR/pos の前期比)、上位クエリ/ページ、**CTR機会**(pos≤10×imp≥200×ctr<3%)、**1ページ目押し上げ候補**(pos11-20×imp≥300)、急上昇クエリを一覧。SEOチェックの起点。**要 `venv_kpi`**。 |
| `lane_c_faq_blocks.py` | Lane C 押し上げ用の FAQ(可視HTML + FAQPage JSON-LD)を生成し `reports/lane_c_faq_patches/post_<id>_faq.html` へ出力。回答は各記事の本文記述に厳密一致させる(ハルシネ防止)。可視FAQが本文に既存の記事は `JSONLD_ONLY` に登録すると JSON-LD のみ出力し二重掲載を防ぐ。**本番反映は owner が `kpop-wp-rw.sh` で実施**(引数は直接渡し・stdin禁止)。 |
| `gsc_inspect_h2.py` | 100点計画 H-2「GSC警告0」を Google Search Console **URL Inspection API** で実測。service account(`google_metrics/service_account.json`)を JWT で `webmasters.readonly` トークンに交換(googleapiclient不要、lib/gsc_indexing.py と同方式)。各URLの verdict / coverageState / robotsTxtState / indexingState / pageFetchState を取得し、インデックス阻害の実害警告(noindex/robots block/fetch失敗)と未クロール(timing)を区別する。証跡: `data/gsc_h2_inspection.json`。 |

```bash
venv_kpi/bin/python3 tools/seo/gsc_snapshot.py --days 28   # SEO実測(28d窓、既定28)
venv_kpi/bin/python3 tools/seo/gsc_snapshot.py --json      # 機械可読
venv_kpi/bin/python3 tools/seo/lane_c_faq_blocks.py        # FAQパッチ生成(引数なし・全件出力)

python3 tools/seo/gsc_inspect_h2.py            # 既定サンプルURL
python3 tools/seo/gsc_inspect_h2.py --url URL  # 単一URL
```

## 高順位×低CTR を見たときの注意

「メタが悪い」と決めつけて改善に走らないこと。**同条件(国/デバイス)の正常クエリと対比**して
検索意図の不一致でないかを先に切り分ける。実例: ブランド系「k-journal」は pos3.0/CTR0.9% だが
メタは正常で、同じ日本・モバイルの「madein神戸」は pos5.5/CTR19.5%。順位が上なのにクリックされない=
**別物を探す検索**で回収不能だった(2026-07-16)。一方「kpop journal」は pos1.0/CTR33% と正常。
