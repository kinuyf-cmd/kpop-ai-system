#!/usr/bin/env python3
"""既存 audit_feedback.jsonl からエージェント別教訓を初期投入"""
import json, os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
FEEDBACK_LOG = '/home/aiuser/kpop-ai-system/logs/audit_feedback.jsonl'
LESSONS_DIR = '/home/aiuser/kpop-ai-system/docs/agent_lessons'

# 既知のエージェント名とその投稿パターン
AGENT_KEYWORDS = {
    'feature_article_writer': ['聖地巡礼', 'モデルコース', '推し活', '推しメイク', '韓国ドラマ',
                               'カラコン', '韓国カフェ', 'ファンチャント', 'お土産', 'ライトスティック',
                               '行き方', 'ガイド', 'まとめ'],
    'breaking_news_writer': ['速報', 'BREAKING', '【速報】', '【韓国メディア速報】'],
    'popup_writer': ['ポップアップ', 'popup'],
    'beauty_writer': ['ビューティー', 'スキンケア', 'コスメ', '美肌'],
    'chart_analyst': ['チャート', 'ランキング', 'Billboard', 'Melon'],
    'trend_reporter': ['トレンド', '話題', '注目'],
}


def detect_agent(title, pipeline=None):
    if pipeline == 'popup':
        return 'popup_writer'
    text = title.lower()
    for agent, keywords in AGENT_KEYWORDS.items():
        if any(k.lower() in text for k in keywords):
            return agent
    return 'unknown'


def main():
    if not os.path.exists(FEEDBACK_LOG):
        print(f"  {FEEDBACK_LOG} not found")
        return

    entries = []
    with open(FEEDBACK_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except:
                pass

    print(f"audit_feedback.jsonl: {len(entries)}件")

    # Aggregate by agent
    agent_data = defaultdict(lambda: {'issue_counts': defaultdict(int), 'fix_counts': defaultdict(int), 'total': 0})

    for e in entries:
        title = e.get('title', '')
        pipeline = e.get('pipeline', '')
        agent = detect_agent(title, pipeline)

        agent_data[agent]['total'] += 1
        for iss in e.get('issues', []):
            if isinstance(iss, str):
                agent_data[agent]['issue_counts'][iss] += 1
        for fix in e.get('fixes', []):
            if isinstance(fix, str):
                agent_data[agent]['fix_counts'][fix[:50]] += 1

    os.makedirs(LESSONS_DIR, exist_ok=True)
    ts = datetime.now(JST).strftime('%Y-%m-%d %H:%M')

    for agent, data in sorted(agent_data.items()):
        fp = os.path.join(LESSONS_DIR, f'{agent}.md')
        lines = [f'# {agent} 品質ログ\n']
        lines.append(f'\n## 初期投入 ({ts}) — audit_feedback.jsonl {data["total"]}件から集計\n')

        if data['issue_counts']:
            lines.append('\n### 頻出issue (Top10)\n')
            for iss, cnt in sorted(data['issue_counts'].items(), key=lambda x: -x[1])[:10]:
                lines.append(f'- {iss}: {cnt}件\n')

        if data['fix_counts']:
            lines.append('\n### 適用fix (Top10)\n')
            for fix, cnt in sorted(data['fix_counts'].items(), key=lambda x: -x[1])[:10]:
                lines.append(f'- {fix}: {cnt}件\n')

        lines.append(f'\n### 教訓\n')
        top_issues = sorted(data['issue_counts'].items(), key=lambda x: -x[1])[:3]
        for iss, cnt in top_issues:
            lines.append(f'- **{iss}** が{cnt}回検出 → 生成プロンプトの該当箇所を重点チェック\n')

        with open(fp, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"  {agent}.md: {len(lines)}行")

    print(f"\n生成完了: {len(agent_data)}エージェント → {LESSONS_DIR}")


if __name__ == '__main__':
    main()
