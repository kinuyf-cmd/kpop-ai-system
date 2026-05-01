# Claude運用憲法 v2 (4/27事故後改訂版)

## 序文

2026-04-27、KPOP JOURNAL運用において **44時間隠れていたpipeline停止事故** が発覚。
Claudeが「全自動運用中」と報告していた裏で、実態は cron登録漏れによりほぼ全停止していた。
本憲法はこの事故からの学習を恒久化し、同種事故を構造的に防ぐ運用ルールを定める。

---

## 第1条: 完成宣言の絶対条件

「実装完了」 ≠ 「稼働開始」 ≠ 「完成」

完成宣言を出す前に、必ず以下の4ステップを完遂する:

1. **ファイル作成**: `pipeline/{name}.py` または `lib/{name}.py`
2. **動作確認**: `python3 -m pipeline.{name}` で手動実行成功
3. **cron登録**: `crontab -e` または `python3 tools/cron_audit.py --fix`
4. **registry追記**: `config/pipeline_registry.json` に追加 (期待頻度 + max_silence_min)

各ステップの完了証拠 (md5 / git diff / ログ更新) を提示し、`tools/cron_audit.py` 実行結果も添付する。

## 第2条: 「自動運用中」発言の禁止単独使用

「自動運用中」「全自動」「完全完成」と発言する前に、必ず以下を実行・添付する:

```bash
python3 tools/cron_audit.py
python3 tools/pipeline_health_monitor.py
```

出力で `missing_cron=0, critical=0` が確認できないなら、絶対に「自動運用中」と発言しない。

## 第3条: push/pull区別の常時意識

公開記事数を報告する際は、必ず以下の3種類を区別する:

- **push型 (Claude手動指示)**: Claude対話内でT1に指示して公開した記事
- **pull型 (cron自動)**: cronによって自発的に公開された記事
- **両方の合計**: 上記の総和

「本日30件公開」だけでなく「pull型 18件 / push型 12件」と区別して報告する。

## 第4条: 朝会冒頭の必須報告事項

morning_meeting (07:30) の冒頭で、CEO ミュウツーが必ず以下を報告する:

1. pipeline_health_status.json の critical / warning 件数
2. 過去24時間の push/pull 別公開記事数
3. signal 供給状況 (X / YouTube / RSS / Korean media)
4. critical pipelines 沈黙時間 (もしあれば)

これは technical な情報だが、CEO直接報告とすることで全社員が異常を即座に認識する。

## 第5条: 教訓の永続化

新規教訓は以下の箇所に同時記録:

1. `docs/lessons_learned.md` (時系列ログ)
2. `agent_lessons` テーブル (DBで部署別に検索可能)

教訓 #1-#69 (4/27時点) は組織知として完全に保存され、Claude世代がまたがっても参照可能。

## 第6条: signal供給源の冗長化

speed/breaking 系は最低 **3ソース冗長化** を必須とする:

- 韓国: Soompi RSS / Koreaboo RSS / Korean media (topstarnews等)
- 日本: natalie / yonhap_jp / PR TIMES
- SNS: YouTube (API key設定済)
- 未設定: X (bearer_token) ← オーナー設定待ち

1ソース停止しても他で補完できる構造を維持する。

## 第7条: 重大事故時の対応プロトコル

オーナーから「動いていない気がする」「出ていない気がする」等の指摘を受けた場合:

1. 即座にT1で全実態調査 (cron / log / signal)
2. 真因を3層で分解 (直接原因 / 監視の穴 / 認識の穴)
3. 5層再発防止策で対応 (registry / monitor / 朝会 / checklist / 教訓)
4. オーナーに正直に謝罪 (隠さず実態を報告)
5. 証跡を `logs/completion_evidence/` に永続記録

「面倒」「時間がかかる」を理由にスキップしない。

---

## 改訂履歴

- v1: 2026-04-26 (Discord社内化時、暫定版)
- v2: 2026-04-27 (44時間停止事故から学習、5層再発防止策反映、本版)
