# M-final 救出記事 取り込み検証レポート (2026-05-22 Day13)

## 結論
**全49件(stg不在の救出記事)の取り込みは現実性「高」。一括取り込み GO 推奨。**

## 取り込み方式
- **取り込み元**: 本番静的HTML `/var/www/kpopjournal_site/<slug>/index.html`(完成形・本文/メタ/H2完備)
- **投入先**: stg WP `/var/www/wp_stg`、wp-cli(DB直結、認証ヘッダ不要)、status=draft
- **スクリプト**: `/home/aiuser/.kpop_recovery/import_recovered_to_stg.py`(--dry-run / --apply)

## サンプル3件 dry-run 結果(抽出成功)
| slug | title | cat | 本文 | H2 | meta |
|---|---|---|---|---|---|
| bts-arirang-billboard-200-2weeks-no1 | 641K→187K…BTS『ARIRANG』Billboard 200連覇 | chart | 9353字 | 12 | 110字 |
| aespa-2026-20260409 | aespa「Whiplash」ワールドツアー2026東京公演 | news | 2217字 | 6 | 110字 |
| newjeans-ador-2026-4-5-20260410 | NewJeans対ADOR訴訟2026年4月最新 | news | 1837字 | 6 | 110字 |

## 全件抽出可否(本番静的59件)
- **抽出OK(本文300字+): 58件**
- 本文不足: 0件
- 異常slug(正規化要): 1件のみ(`13-20260413` → SLUG_OVERRIDE 対応済)
- スキップ: 1件(assets等)

## 取り込み内容(各記事)
- 本文HTML(article内、h1重複除去済)
- タイトル(サイト名サフィックス除去)
- meta description(110字、本番HTMLから)
- カテゴリ(CSV由来 news/chart/guide/comeback/beauty/live → stg カテゴリにマッピング)
- slug(異常slugは正規化)
- 公開日(CSV posted_at 保持)
- 重複回避(stg既存34件とタイトル照合してスキップ)

## 想定問題と対処
| 問題 | 対処 |
|---|---|
| 異常slug(SEO不適) | SLUG_OVERRIDE で正規化(現状1件) |
| サムネがカテゴリ汎用(analysis.png等) | 取り込み時はそのまま。個別サムネは本番化後に改善可(優先度低) |
| stg既存34件との重複 | --apply 時にタイトル正規化照合でスキップ(実装済) |
| カテゴリがstgに存在しない場合 | wp-cli が用語自動作成 or 要事前確認 |

## 実行手順(sudo=オーナー対話実行)
```bash
# 1. サンプル3件で実投入テスト
cd /home/aiuser/.kpop_recovery
sudo python3 import_recovered_to_stg.py --apply --slugs "bts-arirang-billboard-200-2weeks-no1,aespa-2026-20260409,newjeans-ador-2026-4-5-20260410"
# 2. DB検証(本文/カテゴリ/メタ)後、全件
sudo python3 import_recovered_to_stg.py --apply
```

## 取り込み後の構成
stg既存34(publish) + 速報4(draft) + 救出49(draft) ≒ 87記事 + Idol Wiki 123 + 固定ページ5 + イベント1
→ Day14 本番化で全公開。
