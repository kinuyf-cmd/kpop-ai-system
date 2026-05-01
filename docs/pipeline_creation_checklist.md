# Pipeline作成 必須チェックリスト (4/27事故再発防止)

新規pipelineを作成する際は **必ず** 以下の4ステップを完遂すること。
1ステップでも飛ばすと「実装したけど動かない」状態になり、4/27速報pipeline停止事故と同じことが起きる。

## 必須4ステップ

### Step 1: pipelineファイル作成
- `pipeline/{name}.py` または `lib/{name}.py` 作成
- `if __name__ == '__main__':` 実行可能であること
- エラーハンドリング (try/except) 必須

### Step 2: 動作確認 (手動実行)
- `python3 -m pipeline.{name}` で実行
- 想定通り動作することを確認
- ログファイルが生成されることを確認

### Step 3: cron登録 + registry追記
- `crontab -e` または `python3 tools/cron_audit.py --fix` で登録
- **同時に config/pipeline_registry.json に追記** (期待頻度 + max_silence_min + category)
- registryに記載がないとhealth_monitorが検知しない

### Step 4: 監視確認
- 次回cron実行後、ログが更新されることを確認
- `python3 tools/pipeline_health_monitor.py` で対象に入っていることを確認
- `python3 tools/cron_audit.py` でmissing_cron=0を確認

## よくある間違い

- ファイル作成だけしてcron忘れ (4/27事故の直接原因)
- registry更新忘れ → health_monitorが検知できない
- 動作確認なしでcron登録 → エラーログだけ蓄積
- ログパスがregistryと不一致 → 沈黙検知が誤動作

## 即時audit

```bash
# cron漏れ確認
python3 tools/cron_audit.py

# 沈黙確認
python3 tools/pipeline_health_monitor.py

# cron自動修復
python3 tools/cron_audit.py --fix
```
