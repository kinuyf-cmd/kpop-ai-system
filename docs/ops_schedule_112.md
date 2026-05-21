# カテゴリ112「プロフィール」クラスター 運用スケジュール

作成日: 2026-04-13

## 対象記事
- 2475: bts-profile-2026 / BTSとは？7人のプロフィールと現在の活動状況【2026年最新】
- 2476: ive-profile-2026 / IVEとは？6人のメンバーと代表曲・人気の理由
- 2477: aespa-profile-2026 / aespaとは？世界観・4人のメンバー・代表曲まとめ
- 2478: newjeans-profile-2026 / NewJeansとは？5人のメンバー・活動状況・代表曲
- 2479: seventeen-profile-2026 / SEVENTEENとは？13人の構成・ユニット・人気の理由
- 2480: blackpink-profile-2026 / BLACKPINKとは？4人のメンバー・ソロ活動・代表曲
- 2481: straykids-profile-2026 / Stray Kidsとは？メンバー・セルフプロデュース・代表曲
- 2482: twice-profile-2026 / TWICEとは？9人のメンバー・日本での人気・代表曲
- 2483: nct-profile-2026 / NCTとは？拡張型グループの構造と派生ユニット・代表曲
- 2484: kpop-4th-gen-2026 / K-POP第4世代とは？代表グループと第3世代との違い
- 2485: kpop-profile-hub-2026 / K-POPアーティストプロフィール完全ガイド【2026年版】（112ハブ）

## 定期確認コマンド

### 2026-04-20（公開7日後）GSCインデックス確認
```bash
cd /home/aiuser/kpop-ai-system
python3 google_metrics/check_gsc_index_profile.py --save
```
→ logs/gsc_index_check_profile.jsonl にベースラインを保存

### 2026-04-27（公開14日後）high-risk記事（BTS/NewJeans）reviewer実行
```bash
cd /home/aiuser/kpop-ai-system
python3 lib/profile_guide_reviewer.py
# next_review_due <= 2026-04-27 の記事が対象（2475 BTS・2478 NewJeans）
```

### 2026-05-13（公開30日後）全件reviewer実行
```bash
cd /home/aiuser/kpop-ai-system
python3 lib/profile_guide_reviewer.py --all
```

### 2026-06-12（公開60日後）low-risk記事（K-POP第4世代）reviewer実行
```bash
cd /home/aiuser/kpop-ai-system
python3 lib/profile_guide_reviewer.py --post-id 2484
```

## CTRデータ取得
- 2026-04-20以降: GSC管理画面 → 検索パフォーマンス → フィルタ: ページ=/カテゴリ112のURL
- logs/profile_guide_ctr.jsonl に手動記入（impressions_7d, clicks_7d, ctr_7d, avg_position_7d等）

```bash
# CTR台帳確認
cat /home/aiuser/kpop-ai-system/logs/profile_guide_ctr.jsonl | python3 -c "
import json,sys
for line in sys.stdin:
    r=json.loads(line)
    print(f\"{r['post_id']} {r['slug']}: imp={r['impressions_7d']} clicks={r['clicks_7d']} ctr={r['ctr_7d']}\")
"
```

## リンク構造確認
```bash
cd /home/aiuser/kpop-ai-system
python3 lib/check_links_profile.py
```

## 111・113との対比表
| 項目 | 111 | 112 | 113 |
|------|-----|-----|-----|
| ハブpost_id | 2401 | 2485 | 2442 |
| ハブslug | kpop-streaming-guide-2026 | kpop-profile-hub-2026 | kpop-beginner-hub-2026 |
| GSCスクリプト | check_gsc_index_streaming.py | check_gsc_index_profile.py | check_gsc_index_beginner.py |
| reviewerスクリプト | lib/streaming_guide_reviewer.py | lib/profile_guide_reviewer.py | lib/beginner_guide_reviewer.py |
| review台帳 | logs/streaming_guide_review.jsonl | logs/profile_guide_review.jsonl | logs/beginner_guide_review.jsonl |
| CTR台帳 | logs/streaming_guide_ctr.jsonl | logs/profile_guide_ctr.jsonl | logs/beginner_guide_ctr.jsonl |
| GSCベースライン | logs/gsc_index_check.jsonl | logs/gsc_index_check_profile.jsonl | logs/gsc_index_check_beginner.jsonl |
| リンク検証 | — | lib/check_links_profile.py | lib/check_links_beginner.py |

## リスク別next_review_due一覧
| post_id | slug | risk_level | next_review_due |
|---------|------|------------|-----------------|
| 2475 | bts-profile-2026 | high | 2026-04-27 |
| 2476 | ive-profile-2026 | medium | 2026-05-13 |
| 2477 | aespa-profile-2026 | medium | 2026-05-13 |
| 2478 | newjeans-profile-2026 | high | 2026-04-27 |
| 2479 | seventeen-profile-2026 | medium | 2026-05-13 |
| 2480 | blackpink-profile-2026 | medium | 2026-05-13 |
| 2481 | straykids-profile-2026 | medium | 2026-05-13 |
| 2482 | twice-profile-2026 | medium | 2026-05-13 |
| 2483 | nct-profile-2026 | medium | 2026-05-13 |
| 2484 | kpop-4th-gen-2026 | low | 2026-06-12 |
| 2485 | kpop-profile-hub-2026 | medium | 2026-05-13 |

## 注意
- 既存cronは /home/aiuser/kpop-ai-system/cron/ 配下。上書き禁止。
- BTS(2475)・NewJeans(2478)は活動状況が流動的なため2週間ごとの監査を徹底する
- NewJeansの完全体活動・BTS WORLD TOUR名の断言表現は特に注意（reviewer自動検出あり）
