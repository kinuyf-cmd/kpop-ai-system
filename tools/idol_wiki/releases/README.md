# ニュース→Idol Wiki releases 継続拡充パイプライン

速報ニュースから「リリース事実」を構造抽出し、多層品質ゲートを通して Idol Wiki
(idol_artist CPT)の releases に冪等追記する。**Idol Wikiは正本=汚染厳禁**のため、
候補キュー方式 + 人間レビューゲートで安全側に倒す設計。

## パイプライン

```
logs/breaking_articles.jsonl
  → extract_releases.py   (G0解決 + G1抽出: LLMでrelease構造化、憶測/非リリース除外)
  → dedup_check.py        (G2重複/G3矛盾: 既存releasesと突合)
  → verify_releases.py    (G4客観照合: Wikipedia年一致、引けなければunverifiable)
  → review_queue.py       (G5人間レビュー: verified→approve/reject)
  → apply_releases.sh     (G6冪等追記: approvedのみ、skip-dup、rw wrapper自動バックアップ)
```

候補キュー: `data/idol_wiki_release_candidates.jsonl`(status遷移)。
冪等marker: `data/processed_breaking.jsonl`(処理済み速報post_id)。
名前解決索引: `data/artist_name_index.json`(`lib/artist_resolver.py --rebuild`で再構築)。

## 使い方(検証手順)

```bash
# 0. 名前解決索引を構築(初回 or idol_artist追加時)
python3 lib/artist_resolver.py --rebuild
python3 lib/artist_resolver.py aespa 에스파 RIIZE   # 解決テスト

# 1. 抽出(dry-run→本番)。venv_kpi 必須(ANTHROPIC_API_KEY)
venv_kpi/bin/python3 tools/idol_wiki/releases/extract_releases.py --artist aespa,RIIZE --dry-run
venv_kpi/bin/python3 tools/idol_wiki/releases/extract_releases.py --artist aespa,RIIZE

# 2. 品質ゲート
venv_kpi/bin/python3 tools/idol_wiki/releases/dedup_check.py
venv_kpi/bin/python3 tools/idol_wiki/releases/verify_releases.py

# 3. 人間レビュー(Claude/owner)
venv_kpi/bin/python3 tools/idol_wiki/releases/review_queue.py --list
venv_kpi/bin/python3 tools/idol_wiki/releases/review_queue.py --show 64   # 既存releasesとのdiff
venv_kpi/bin/python3 tools/idol_wiki/releases/review_queue.py --approve <candidate_id>

# 4. 適用(dry-run→本番)
bash tools/idol_wiki/releases/apply_releases.sh                # dry-run
bash tools/idol_wiki/releases/apply_releases.sh --apply        # 実書込(自動バックアップ)
```

## 品質ゲート(全通過必須)

| ゲート | 内容 |
|---|---|
| G0 解決 | artist_resolver 完全一致のみ。曖昧/未知はdrop(誤pid追記=最悪事故) |
| G1 抽出 | LLMでrelease構造化。憶測語(噂/予定/〜か)・非リリース・年なしはdrop |
| G2 重複 | 既存releasesと正規化タイトル突合、同年同曲drop |
| G3 矛盾 | 同曲が別年で既存→conflict(自動apply禁止) |
| G4 照合 | Wikipedia年一致。引けなければunverifiable(誤報告しない) |
| G5 レビュー | approved以外apply不可。verifiedからのみapprove可 |
| G6 冪等 | rw wrapper(自動バックアップ)・skip-dup・件数N→N+1のみ |

## 検証結果(2026-06-03 aespa/RIIZE)

- 名前解決: aespa/에스파/RIIZE/라이즈 全て正しいpid(64/98)に解決、曖昧0
- 抽出: 速報43件→候補3件(ゴシップ等40件は正しく除外)、コスト$0.056
- ゲート: LEMONADE=既存と重複検出 / 残2件=unverifiable(保守的に人手へ)
- 人間レビュー: 3件とも reject が妥当(重複 / 韓国語表記の実質重複 / D-D-Doneはアルバム収録曲で粒度違い)
- **Idol Wiki汚染ゼロ**(aespa/RIIZE releases件数 無変更)、apply冪等性(skip-dup)実証

教訓: LLM抽出は「タイトル曲か収録曲か」「英題か韓題か」の粒度を誤りうる。
→ G5人間レビューが品質の最後の砦。憶測で書くより unverifiable で人手に委ねる方が正しい。

## 拡大手順(検証合格後)

頻度順に 5→20→123組へ。`--artist`を増やすか空(全件)で実行。
cron自動化は post_publish_hook 連携 or 日次backfill で別タスク化(レビューゲートは維持)。
artist_summaryは別系統(summary_suggest.py=提示のみ、本番書込は更に慎重に)。
