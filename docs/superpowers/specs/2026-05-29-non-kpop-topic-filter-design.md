# 非K-POPトピック除外フィルタ 設計書

- 日付: 2026-05-29
- 対象: KPOP JOURNAL 速報引用記事の自動生成パイプライン
- 起票: x-issue-31-cast-controversy / che-juni-starbucks-emotion 記事の監査

## 背景・問題

XPORTSNEWS の「엑's 이슈 (X's Issue, cate_sub=3001)」セクションは、
K-POP芸能人だけでなく以下の **サイト主題と無関係なコンテンツを混在** して掲載する:

- 婚活/恋愛リアリティ番組『나는 SOLO / 私はソロ』の **一般人出演者** の人間関係トラブル
- 故人・俳優など **非アイドル芸能人** の私生活ゴシップ・政治論争

`lib/collectors/korean_base.py:is_kpop_related()` は K-POPキーワードの
substring/単語境界マッチのみで判定し、「一般人出演」「政治」「非アイドル」を
区別しないため、これらが記事化を通過していた。

実害(本番公開→監査でdraft化):
- ID 4802 「エックスのイシュー 31期出演者の論争続く」(『나는 SOLO』一般人)
- ID 4798 「チェ・ジュニ、スタバ写真で心情吐露」(故女優の娘の政治論争)
- ID 3158 「31期メンバー団体飲み会…」(同上、同根)

関連メモリ: event-misclassification-ambiguous-artist /
feedback_guard_false_positives / factcheck-on-raw-body-before-injection

## 方針

二重防御 + キーワードベース。

- 収集口(collector)で早期に signal を捨て、無駄な LLM 生成コストを節約
- pre_publish_gate で BLOCK し、他ソース経由のすり抜けも捕捉

判定ロジックは新規モジュール `lib/kpop_topic_filter.py` に集約し、
両経路から呼ぶ(誤検知調整を1箇所に)。

## アーキテクチャ

```
config/ng_topics.json  ──┐
                         ├─→ lib/kpop_topic_filter.py
                         │     classify_non_kpop_topic(text) -> reason:str | None
   ┌─────────────────────┴──────────────────────┐
   │                                            │
xportsnews_collector.collect()        pre_publish_gate(...)
  is_kpop_related通過後に              kind in (news/breaking) かつ
  classify_... が非Noneなら除外         structural_only=False のとき
                                       non_kpop_topic を BLOCK
```

## config/ng_topics.json

```json
{
  "reality_show_civilian": ["나는 솔로", "나는 SOLO", "나솔", "私はソロ", "환승연애", "하트시그널", "솔로지옥", "짝짓기 예능", "일반인 출연"],
  "politics": ["좌파", "우파", "정치 성향", "대선", "탄핵", "5·18", "5.18", "좌파 없는 나라"],
  "non_idol_celebrity_gossip": []
}
```

- `non_idol_celebrity_gossip` は誤爆リスクが高いため初期は空。運用で必要時に追加。
- 各語は korean_base.py の部分一致規則(ハングルは直前hangul排除、ASCIIは語境界)を踏襲して照合。

## 判定関数 classify_non_kpop_topic(text)

返り値: NGなら理由カテゴリ名(str)、問題なければ None。

安全装置(誤ブロック防止):
- `is_kpop_related(text)` の **固有アーティスト名マッチ(proper_artist_matches)** が
  存在する場合、`politics` / `non_idol_celebrity_gossip` カテゴリの NG はキャンセルする。
  → 「BTS V が政治発言で論争」のような正当な K-POP 記事を守る。
- `reality_show_civilian` は番組名固有名詞のため、単独ヒットで無条件 NG
  (K-POPアイドルが『나는 솔로』に出ることは事実上ない)。

## ゲート統合

- `pre_publish_gate` は2パス(注入前=内容/注入後=構造、structural_only フラグ)。
- NGトピックは **内容チェック** → `structural_only=True` のパスではスキップ。
- `kind in ('news', 'breaking')` のときのみ判定(feature/popup/独自記事は対象外)。
- `BLOCK_TYPES` に `'non_kpop_topic'` を追加。

## テスト(TDD)

`tests/test_kpop_topic_filter.py`:
1. 『나는 SOLO』婚活番組タイトル → NG (reality_show_civilian)
2. 「좌파 없는 나라」政治 → NG (politics)
3. 「BTSのV、コンサートで結婚発言し話題に」→ None (誤爆ゼロ)
4. 通常カムバック速報 → None
5. K-POPアーティスト名 + 政治語共在 → None (安全装置)
6. pre_publish_gate 結合: 『나는 SOLO』本文 → verdict BLOCK / 正当記事 → 非BLOCK

## 影響範囲

- 新規: `lib/kpop_topic_filter.py`, `config/ng_topics.json`, `tests/test_kpop_topic_filter.py`
- 変更: `lib/collectors/xportsnews_collector.py`, `lib/pre_publish_gate.py`
- 既存の公開済み正当記事タイトルで誤爆ゼロを実測してから push。
</content>
</invoke>
