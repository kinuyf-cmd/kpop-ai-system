# パフォーマンス磨き込み(本番 www.kpopjournal.tokyo)

2026-05-25 本番実測(Lighthouse 12.8.2, モバイル):

| ページ | Perf | A11y | BestPractices | SEO |
|---|---|---|---|---|
| homepage | 78 | **100** | 61 | **100** |
| 記事 | 73 | **100** | 79 | **100** |

**a11y・SEO は満点**。Perf / BestPractices の下落は **ほぼ全て広告・計測 third-party**
(Google Ads/DoubleClick・GTM・FundingChoices で TBT の約 770ms、BP の deprecated unload・
3rd-party cookie も全て広告由来)。これは収益インフラ(J項目)なので**触らない**。

ここで改善するのは **自社資産のみ**(安全・収益無影響):

## 実行(owner、www-data)

```bash
# 1) uploads 配下の PNG/JPG に WebP 併設版を生成(原本は無変更・冪等)
#    本番home実測: 373KiB節約、全home画像で66%/約2MB削減
sudo -u www-data bash tools/perf/webp_convert.sh /var/www/wp_stg/wp-content/uploads

# 2) nginx に WebP透過配信 + 長期キャッシュを取り込む(owner=root)
#    webp_nginx.conf の map を http{}、location群を server{} へ。確認後:
sudo nginx -t && sudo systemctl reload nginx

# 3) 子テーマ CSS を minify(本番実測 128KB→65KB、.bak保存・ヘッダ保持・冪等)
sudo -u www-data python3 tools/perf/minify_theme_css.py \
  /var/www/wp_stg/wp-content/themes/generatepress-kpop/style.css
```

## 期待効果(自社分のみ。広告分は対象外)

- modern-image-formats 373KiB + offscreen/responsive 〜750KiB → WebP透過配信で解消
- uses-long-cache-ttl(49 resources)/ cache-insight 1262KiB → 365d immutable で解消
- unminified-css 16KiB(実体は128→65KB)→ minify で解消

Perf は ad JS の TBT が残るため 90 到達は広告制約で頭打ちだが、**自社起因の減点は一掃**でき、
LCP/転送量/実ユーザー体感が改善する。a11y 100 / SEO 100 は維持。

## やらないこと(意図的)

- 広告・計測 JS の defer/削除(収益タイミングに影響・要A/B)。
- unused-css の機械削除(Lighthouse未巡回ページのスタイル破壊リスク)。minify のみに留める。
