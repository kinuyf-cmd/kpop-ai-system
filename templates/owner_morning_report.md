# ☀️ おはようございます — {{date}}

## 5秒サマリ
- 🔴 緊急介入要: {{red_count}}件
- 🟡 非同期確認: {{yellow_count}}件  
- 🟢 自律処理済: {{green_count}}件
- 📈 昨日実績: 記事{{articles_count}}件公開 / {{pv_count}} PV
- ⏰ 今日見込: {{today_planned}}件公開予定

## 🔴 要対応 (あなたの判断が必要)
{{#red_items}}
- [ ] {{description}} — {{reason}}
{{/red_items}}

## 🟡 事後確認 (既に実行済)
{{#yellow_items}}
- {{description}} — {{result}}
{{/yellow_items}}

## 🟢 自律処理完了
{{green_count}}件を自動処理しました。[詳細ログ](logs/autonomy_executions.jsonl)

## 📊 AI組織の健康状態
- 全社成功率: {{success_rate}}%
- アクティブ社員: {{active_agents}}名
- 🟢優秀: {{green_agents}} / 🟡要注意: {{yellow_agents}} / 🔴危険: {{red_agents}}

---
*このレポートはAI組織が自動生成しています。返信不要 — 🔴のみご確認ください。*
