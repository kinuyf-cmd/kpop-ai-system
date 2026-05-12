"""KPI analyzer — Files API + Code execution tool (2026-05-10)

x_kpi.jsonlをFiles API経由でAnthropicにupload、code_execution toolで
Claude側Pythonサンドボックス内でトレンド分析を実行。

機能:
- followers/impressions/engagement_rate の時系列トレンド
- 旧テンプレ vs 新テンプレ (5/10朝以降) のengagement比較
- best_tweet パターン分析
- chart生成 (matplotlib) → /home/aiuser/kpop-ai-system/reports/

Usage:
    from lib.kpi_analyzer import analyze_x_kpi
    r = analyze_x_kpi(days=14)
    # r: {'summary': str, 'insights': [...], 'charts': [...]}
"""
from __future__ import annotations
import os
import json
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

KPI_LOG = Path('/home/aiuser/kpop-ai-system/logs/x_kpi.jsonl')
REPORTS_DIR = Path('/home/aiuser/kpop-ai-system/reports/kpi_analyzer')
LOG_PATH = Path('/home/aiuser/kpop-ai-system/logs/kpi_analyzer.jsonl')

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def analyze_x_kpi(days: int = 14, focus: str = 'engagement_trend') -> dict:
    """x_kpi.jsonlをFiles APIでupload→code_execution toolで分析

    focus:
        'engagement_trend' — followers/imp/likes時系列
        'template_comparison' — 旧テンプレvs新テンプレ (5/10朝以降)
        'best_tweet_pattern' — best_tweet分析
    """
    if not KPI_LOG.exists():
        return {'error': 'KPI log not found', 'summary': ''}

    client = _get_client()

    try:
        # 1. KPI data を Files API にアップロード
        with open(KPI_LOG, 'rb') as f:
            uploaded = client.beta.files.upload(
                file=('x_kpi.jsonl', f, 'application/jsonl'),
            )
        file_id = uploaded.id

        # 2. focus別のプロンプト
        prompts = {
            'engagement_trend': (
                f"x_kpi.jsonlは1行=1JSON record形式です。最新{days}日を分析。\n\n"
                "## 1ステップで完結させる:\n"
                "```python\n"
                "import json, pandas as pd, matplotlib.pyplot as plt\n"
                "rows = [json.loads(l) for l in open('/tmp/inputs/x_kpi.jsonl') if l.strip()]\n"
                "df = pd.DataFrame(rows)\n"
                "df['ts'] = pd.to_datetime(df['ts'])\n"
                "# 直近N日filter\n"
                "df = df.sort_values('ts').tail(N*2)  # 1日2回観測想定\n"
                "# Compute trend stats\n"
                "# Generate chart at /tmp/kpi_trend.png\n"
                "# print('=== ANALYSIS RESULT ===') 以降を 1500字以内で\n"
                "```\n\n"
                "**raw data は絶対 print しない**。最後に '=== ANALYSIS RESULT ===' で始まる"
                "サマリだけを print してください (followers純増 / imp推移 / 主要観察3点 / 推奨アクション1点)。"
            ),
            'template_comparison': (
                "x_kpi.jsonlを2026-05-10朝(commit 3b28714の刷新時刻)で前後分割し、\n"
                "旧テンプレ (5/10より前) vs 新テンプレ (5/10以降) の以下を比較:\n"
                "1. total_impressions の平均・中央値\n"
                "2. engagement_rate の平均\n"
                "3. best_tweet impressions の最大\n"
                "4. 統計的有意差 (t-test, sample size 小さければ参考程度)\n\n"
                "結論: 新テンプレで impressions が改善したか? 数値で示してください。"
            ),
            'best_tweet_pattern': (
                "best_tweet.text を全件分析し、impressions の高い tweet の共通パターンを抽出:\n"
                "1. 1行目 (hook) の頻出パターン\n"
                "2. ハッシュタグの傾向\n"
                "3. アーティスト名の出現頻度\n"
                "4. impressions上位5件の特徴\n\n"
                "勝ちパターン3-5個を箇条書き。"
            ),
        }
        user_prompt = prompts.get(focus, prompts['engagement_trend'])

        # 2026-05-12 (Phase 6): cost guard
        try:
            from lib.anthropic_cost_guard import guard_before_call
            if not guard_before_call('kpi_analyzer'):
                return {'text': '[cost_guard_skip]', 'charts': [], 'code_runs': 0}
        except ImportError:
            pass

        # 3. Claude code_execution で分析
        response = client.beta.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4000,
            tools=[{
                "type": "code_execution_20260120",
                "name": "code_execution",
            }],
            betas=["files-api-2025-04-14"],
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "container_upload", "file_id": file_id},
                ],
            }],
        )
        try:
            from lib.anthropic_cost_guard import log_usage
            log_usage('kpi_analyzer', model='claude-sonnet-4-6', usage=response.usage)
        except Exception:
            pass

        # 4. 結果抽出 — text + 全bash出力 + 生成file
        text_parts = []
        stdout_parts = []
        code_runs = 0
        chart_files = []
        for block in response.content:
            if block.type == 'text':
                text_parts.append(block.text)
            elif block.type == 'server_tool_use':
                code_runs += 1
            elif block.type == 'bash_code_execution_tool_result':
                content = getattr(block, 'content', None)
                if content:
                    if hasattr(content, 'stdout') and content.stdout:
                        # ANALYSIS RESULTマーカーがあればその部分を優先抽出、なければ末尾4000字
                        s = content.stdout
                        if 'ANALYSIS RESULT' in s:
                            idx = s.find('ANALYSIS RESULT')
                            stdout_parts.append(s[idx:idx+3500])
                        else:
                            stdout_parts.append(s[-4000:])
                    if hasattr(content, 'content') and content.content:
                        for item in content.content:
                            if hasattr(item, 'file_id'):
                                chart_files.append(item.file_id)

        # text + bash stdout を合体
        full_text = '\n'.join(text_parts)
        if stdout_parts:
            full_text += '\n\n--- code execution output ---\n' + '\n'.join(stdout_parts)

        # 5. ログ
        _log({
            'focus': focus,
            'days': days,
            'code_runs': code_runs,
            'chart_count': len(chart_files),
            'text_length': len(full_text),
            'usage': {
                'input': response.usage.input_tokens,
                'output': response.usage.output_tokens,
            },
        })

        # 6. Chart download (もしあれば)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for cf_id in chart_files:
            try:
                meta = client.beta.files.retrieve_metadata(cf_id)
                local_path = REPORTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M')}_{focus}_{meta.filename}"
                content = client.beta.files.download(cf_id)
                content.write_to_file(str(local_path))
                downloaded.append(str(local_path))
            except Exception as e:
                pass

        # 7. 元ファイルcleanup
        try:
            client.beta.files.delete(file_id)
        except Exception:
            pass

        return {
            'focus': focus,
            'summary': full_text,
            'code_runs': code_runs,
            'charts': downloaded,
        }

    except Exception as e:
        return {'error': f'{type(e).__name__}: {str(e)[:200]}', 'summary': ''}


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**entry, 'ts': datetime.now().isoformat()}, ensure_ascii=False) + '\n')
    except OSError:
        pass


if __name__ == '__main__':
    import sys
    focus = sys.argv[1] if len(sys.argv) > 1 else 'engagement_trend'
    r = analyze_x_kpi(focus=focus)
    print(json.dumps({
        'focus': r.get('focus'),
        'summary_excerpt': r.get('summary', '')[:1000],
        'code_runs': r.get('code_runs'),
        'charts': r.get('charts', []),
        'error': r.get('error'),
    }, ensure_ascii=False, indent=2))
