# SEO 計測ツール

| ファイル | 役割 |
|---|---|
| `gsc_inspect_h2.py` | 100点計画 H-2「GSC警告0」を Google Search Console **URL Inspection API** で実測。service account(`google_metrics/service_account.json`)を JWT で `webmasters.readonly` トークンに交換(googleapiclient不要、lib/gsc_indexing.py と同方式)。各URLの verdict / coverageState / robotsTxtState / indexingState / pageFetchState を取得し、インデックス阻害の実害警告(noindex/robots block/fetch失敗)と未クロール(timing)を区別する。証跡: `data/gsc_h2_inspection.json`。 |

```bash
python3 tools/seo/gsc_inspect_h2.py            # 既定サンプルURL
python3 tools/seo/gsc_inspect_h2.py --url URL  # 単一URL
```
