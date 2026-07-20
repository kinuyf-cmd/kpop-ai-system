---
name: signal-audit
description: KPOP JOURNAL・補助金AIステーションの不要トラッカー・分析タグ・スクリプトを検出し除去判定するスキル。GA4等の必要機能は維持しつつ不要なシグナル収集を除去し、プライバシー保護と表示速度を改善。「シグナル除去」「不要トラッカー検出」「分析タグ確認」「プライバシー監査」「サイトを軽くしたい」といった問い合わせ時に必ず使用。100点計画 B項目の達成に必須。
---

# Signal Audit

## 1. 目的

サイトに紛れ込んだ不要なトラッカー・分析タグ・外部スクリプトを検出し、
除去する。プライバシー保護・表示速度向上・100点計画 B項目達成が狙い。
必要な計測(GA4 等)は維持し、不要なものだけを落とす。

## 2. 検出対象

- Google Analytics の重複・旧式埋め込み(複数形式)
- Facebook Pixel / Twitter conversion tracking
- サードパーティ広告タグ
- 不要な inline script
- 不要な外部 JS/CSS リソース

## 3. ホワイトリスト(維持するもの)

- GA4(現在使用中の計測)
- AdSense(将来必要)
- Search Console verification
- 必須 WordPress プラグインのスクリプト

ホワイトリスト上のものは検出されても削除しない。

## 4. 検出方法

- HTML 解析(`curl` + `grep`)
- ブラウザ開発者ツールの Network タブ
- Lighthouse の「third-party」セクション
- PageSpeed Insights

## 5. 安全削除フロー

1. バックアップを取得する
2. 1つずつ削除する(まとめて消さない)
3. 動作確認(HTTP 200、Lighthouse の前後比較)
4. 失敗したらロールバック

## 6. 削除が困難な場合

- WordPress プラグイン由来 → プラグインの無効化/削除
- テーマ由来 → 子テーマ `generatepress-kpop` で上書き
- サーバー設定由来 → nginx / wp-config を確認(**要オーナー承認**)

## 7. 100point-rubric-judge B項目との連動

| B項目 | 基準 |
|---|---|
| B-1 | 不要トラッカー 0(GA4以外)|
| B-2 | 不要プラグイン無効化 |
| B-3 | HTML の不要 inline script 除去 |

## 8. 出力ルール

検出件数 + 削除可否 + 安全削除手順を3行以内で報告。
削除可否は実測(実際に到達確認)に基づく。

ログ: `/home/aiuser/.kpop_recovery/signal_audit_log.jsonl`
