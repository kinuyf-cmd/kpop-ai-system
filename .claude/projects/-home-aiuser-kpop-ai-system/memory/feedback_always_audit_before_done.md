---
name: 記事公開時は必ず監査を実行
description: 記事をpublishした後、full_auditでissue=0を確認するまで完了と報告しない
type: feedback
---

記事を公開(publish)したら必ず full_audit を実行し、全issueを解消してから完了報告する。

**Why:** 2026-04-28に8本の5月特集記事を公開した際、監査なしで完了報告してしまった。実際にはslug_encoded(HIGH)・no_thumbnail(HIGH)・内部リンク不足(MEDIUM)等が全8本に残っていた。ユーザーに指摘されて初めて監査→修正した。

**How to apply:**
- 記事をWP REST APIでpublish → post_publish_enricher → full_audit の順で必ず実行
- HIGH/MEDIUMが残っていたら即修正し、再監査でissue=0を確認
- issue=0になるまで「完了」と報告しない
- draft→publish変換だけでなく、新規生成・リライト・バッチ公開すべてに適用
