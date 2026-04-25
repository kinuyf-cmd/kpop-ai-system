# 速報2段階公開+翻訳K-POP特化 2026-04-28

## 仕様 (オーナー確定 2026-04-28)
- 速報最低150字 (旧200)
- Stage 2加筆: 2時間後、目標600字
- 翻訳Lv1 (K-POP専門プロンプト、コスト同額)

## S1: lib/unified_publisher.py
- `is_breaking=False` 引数追加
- 品質ゲート: `_min_len = 150 if is_breaking else 200`
- syntax OK

## S2: pipeline/breaking_news_detector.py
- `unified_publish()` に `is_breaking=True` 追加
- `_mark_breaking_stage(post_id, 1)` で WP custom field 記録
- syntax OK

## S3: pipeline/rewrite_worker.py
- `find_breaking_stage1_to_upgrade()`: 2時間経過 Stage 1 速報を WP REST API で検索
- `upgrade_breaking_to_stage2()`: GPT-4o-mini で 600字以上に加筆 → stage=2 に更新
- main() 先頭で Stage 1→2 加筆処理を実行 (最大5件/回)
- syntax OK

## S4: lib/korean_translator.py
- K-POP専門翻訳プロンプト適用
- アーティスト名マッピング (뉴진스→NewJeans, 에스파→aespa 等)
- 専門用語統一 (컴백→カムバック, 발매→リリース 等)
- 文末バリエーション指示
- syntax OK

## テスト結果

### 翻訳精度テスト
```
원문: 뉴진스 민지가 새 솔로곡으로 컴백을 알렸다. 6월 15일 발매 예정이다.
訳文: NewJeansのミンジが新しいソロ曲でカムバックすることを発表した。リリースは6月15日の予定だ。

원문: 방탄소년단 진이 솔로 활동에 나서며 음악방송에 출연한다고 밝혔다.
訳文: BTSのジンがソロ活動を開始し、音楽番組に出演すると発表した。

원문: 에스파가 새 미니앨범으로 차트 1위를 차지하며 글로벌 팬덤의 강세를 입증했다.
訳文: aespaが新しいミニアルバムでチャート1位を獲得し、グローバルファンダムの強さを証明した。
```

### breaking_news_detector dry-run
- 正常動作 (対象0件)

### WP Stage 1 検索テスト
- Stage 1 posts found: 10 (既存のstage=1メタを持つ投稿)
- 加筆スキップ (既に500字以上のため正常スキップ)
