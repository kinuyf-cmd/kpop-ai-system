# X(Twitter)投稿自動化 — 依存マップと整理状況 v1(2026-05-26)

オーナー依頼「X投稿の自動化の整理」で実施した現状把握・安全化と、残タスクの記録。
※ コードを大きく変える整理は **認証復旧後に実投稿で検証しながら**行う(下記「残タスク」)。

## 1. いちばん大事な現状

- **X 投稿は 2026-05-21 以降 全件 HTTP 401(Unauthorized)で失敗**。成功記録 0 件。
- 原因は `~/.x_credentials` の失効(or 権限不足)。**認証復旧はオーナー作業**(§5)。
- 5 日間誰も気づけなかった → 連続失敗の Discord 通知を追加して可観測化済み(§4)。

## 2. X 投稿の真の全体像(実コードで確定。Explore 初版マップの誤りを訂正済み)

X API を叩く最終地点は **`google_metrics/post_to_x.py` ただ1つ**(OAuth1.0a → `POST /2/tweets`)。
そこへ至る経路は大きく3系統:

```
【系統A: 会話起点 text-only】 ★cron稼働中(だが401)
  cron 7/17/21時(2026-05-26 一時停止中)
    → lib/x_conversation_starter.py --post
        → subprocess → google_metrics/post_to_x.py → X API

【系統B: 記事誘導(フック→URLリプライ 2段)】 ★queue消化cronが未登録=動いていない
  記事公開 → lib/unified_publisher.py
    → lib/x_poster.py(enqueue) → config/x_post_queue.json(44件滞留)
        → [本来] pipeline/x_scheduled_poster.py を cron で定期消化するはず
           ……が crontab に未登録。これが滞留の主因。
        → x_poster.post_hook_and_reply() → post_to_x.py → X API

【系統C: シェル統合パイプライン】 ★Explore初版マップが見落としていた主要経路
  kpop_pipeline.sh / kpop_chart_pipeline.sh / kpop_strategy_pipeline.sh /
  post_audit.sh / lib/{audit_helpers,auto_rewriter,post_watchdog,x_post_templates}.py
    → google_metrics/post_to_x.sh(24KB。x_pre_score で採点 → 合格のみ投稿)
        → google_metrics/post_to_x.py → X API

【系統D: 返信運用】 owner承認フロー。モック中心・未本番化
  lib/x_engagement_responder.py → owner_decision_queue → 承認後 post_to_x.py
```

### Explore 初版マップの誤り(再調査で訂正)
1. 「`x_pre_score.py` は未統合」→ **誤り**。`post_to_x.sh`(3箇所)・`kpop_pipeline.sh` で
   実際に使われている(投稿前 80 点ゲート)。
2. 「`post_to_x.sh` は登場しない」→ **誤り**。8 ファイルから呼ばれる主要経路。
   `.py` だけ追うと全体像を見誤る。
3. 「`post_tweet`(旧)は deprecated 化候補」→ `lib/unified_publisher.py:674` が現役で使用中。
   消すには呼び出し側の改修が要る(今は触らない)。

## 3. ファイル一覧と役割

| ファイル | 役割 | 状態 |
|---|---|---|
| `google_metrics/post_to_x.py` | **X API 最終実行点**(OAuth1.0a) | 現役・401中 |
| `google_metrics/post_to_x.sh` | 採点付き投稿ラッパー(系統C) | 現役 |
| `lib/x_poster.py` | 投稿ラッパー(レート制限/類似検知/2段投稿) | 現役(系統B) |
| `lib/x_post_templates.py` | 本文テンプレ v13.0 + `sanitize_tweet` | 現役 |
| `lib/x_pre_score.py` | 投稿前 100 点採点(80 点ゲート) | 現役(系統C) |
| `lib/x_post_url_validator.py` | URL/OGP 事前検証 | 現役 |
| `lib/x_conversation_starter.py` | 会話起点 text-only 生成・投稿(系統A) | 現役・cron停止中 |
| `lib/x_engagement_responder.py` | 返信運用(owner承認) | モック・未本番 |
| `lib/x_post_audit.py` | 投稿後監査(read-only) | 現役 |
| `pipeline/x_scheduled_poster.py` | queue 消化スケジューラ(系統B本命) | **cron未登録** |
| `config/x_post_queue.json` | 投稿待ちキュー | 44件滞留 |
| `lib/x_boost_selector.py` | (存在しない。`sanitize_tweet` は templates に内蔵) | 不在 |

## 4. 実施済みの整理(安全な範囲)

- **空振り cron 停止**: 7/17/21時の `x_conversation_starter --post` 3本をコメント化で停止
  (認証復旧後に `#` を外す)。crontab は `~/.kpop_recovery/crontab_backups/` にバックアップ。
- **連続失敗の Discord 通知**: `x_conversation_starter.py` に追加。直近3件連続 `post_fail` で
  `DISCORD_WEBHOOK_URGENT_ERRORS` に1度だけ通知(sentinel 抑制、成功で解除)。
  実通知テスト済み。**User-Agent 必須**(既定 urllib は Cloudflare 403/1010 で弾かれる)。
- **ログ整理**: 401 が 302 行溜まった `x_posting_log.cron` を gzip アーカイブ後に空に。
- **誤解コメント修正**: `x_post_templates.sanitize_tweet` の「x_boost_selector 由来」注記を訂正。

## 5. 認証復旧手順(オーナー作業・必須)

1. X Developer Portal でアプリを開く
2. 権限が **Read and Write** か確認(Read-only だと 401/403)
3. **Keys and tokens** で再生成: API Key/Secret, Access Token/Secret
   (権限変更後は Access Token を必ず再生成。古いトークンは旧権限のまま)
4. `~/.x_credentials`(JSON 4キー)を更新し `chmod 600` 維持
5. 確認: 1本だけ実投稿テスト → cron の `#` を外して再開

## 6. 残タスク(認証復旧後に、実投稿で検証しながら)

- **B-1**: `pipeline/x_scheduled_poster.py` を cron 登録(queue 44件の消化を稼働)。
  登録前に滞留 queue の TTL/上限/古いエントリを整理。
- **B-2**: `post_tweet`(旧・単発URL同梱)を `post_hook_and_reply`(新・2段)へ寄せる。
  `unified_publisher.py:674` の呼び出しを移行してから旧経路を deprecated 化。
- **B-3**: OGP 検証(`x_post_url_validator` と `x_poster` 内簡易版)・WP status 検証
  (3箇所)を共通関数化。
- **B-4**: `x_engagement_responder` の本番化(owner承認フロー)。
- いずれも「実投稿で前後比較できる」状態(=認証復旧後)で行うのが安全。
