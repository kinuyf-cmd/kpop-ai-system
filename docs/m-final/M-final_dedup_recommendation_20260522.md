# M-final 重複整理 推奨リスト (2026-05-22 Day13)

全本番59記事のタイトル/本文類似スキャン結果。取り込み前に整理する。

## カテゴリ1: 完全重複(本文100%一致)→ 除外確定推奨

**TWICEサナ「7スキン法」記事が3つ存在(全て同一本文4119字・同日付2026-04-06)**
| slug | 判定 |
|---|---|
| `twice-sana-7-skin-method-glass-skin-korean-idol-cosmetics-20` | ✅ **残す**(slugとタイトル一致の正規版) |
| `twice-sana-7-skin-method-glass-skin-korean-idol-cosmetics-20-2` | ❌ 除外(重複コピー、slug末尾-2) |
| `bts-aespa-worn-brands-kpop-fashion-trends-spring-2026` | ❌ 除外(slug=ファッションだが中身はサナ7スキン法=救出時の取り違え) |

→ **2件除外**

## カテゴリ2: SEOカニバリ(同テーマ過剰)→ 要オーナー判断

**スウパ3 ABEMA視聴方法が4記事(本文は各1670-2337字、内容近接)**
| slug | 字数 | 日付 |
|---|---|---|
| `swf3-where-to-watch-abema-premium-full-episodes-2026` | 2337 | 04-05 |
| `swf3-street-woman-fighter-3-abema-how-to-watch-2026` | 1899 | 04-06 |
| `swf3-street-woman-fighter-3-free-streaming-guide-2026` | 1800 | 04-06 |
| `swf3-abema-free-streaming-guide-april-2026` | 1670 | 04-06 |

→ 推奨: 最長・最古(網羅性高)の `where-to-watch...full-episodes`(2337字)を残し、**他3件は除外 or 1本に統合**。同一検索意図で4記事はGoogleにカニバリ評価される。

**ガラス肌スキンケアが2記事**
- `pop-2026-20260410`(ガラス肌スキンケア最新版) / `pop-7-20260410`(7ステップ) → 切り口違うが要確認

**聖地巡礼/ポップアップガイドが2記事**
- `2026-pop-20260409` / `seoul-kpop-pilgrimage-guide-spring-2026...` → 後者がslug適正

## カテゴリ3: 同トピック別アングル(重複でない=両方残す可)

**ARIRANG「3週連続1位」2記事(本文類似0.1=別記事)**
- `bts-641-000-3-1-20260413`(3426字、数字解説) / `bts-arirang-3-1-20260413`(3266字、解説調)
- 切り口が異なり本文も別。SEOカニバリ懸念はあるが重複ではない → 両方残すも可

## 推奨まとめ
- **確定除外2件**(TWICEサナ完全重複): `...-20-2`, `bts-aespa-worn-brands...`
- **要判断**: スウパ3 4→1〜2件(推奨3件除外)、ガラス肌2件、聖地巡礼2件
- 最小除外(完全重複のみ): 51 → 49件取り込み
- 推奨除外(カニバリ整理含む): 51 → 約45件取り込み

取り込みは DRAFT なので、迷う場合は全部取り込んで stg 上で目視整理 → trash も可。
