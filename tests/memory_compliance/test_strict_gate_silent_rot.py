"""
memory: feedback_strict_gate_silent_rot.md
規定: 「厳格化変更は手動キュレーション+0件アラート+UI警告 3点セットで導入」
"""
import os, glob


def test_alert_or_notification_path_exists():
    """0件アラート系の存在 (Discord/Slack webhook含む)"""
    found = False
    keywords = ('DISCORD_WEBHOOK', 'send_discord', 'slack_alert', 'zero_count_alert',
                '0件', 'webhook', 'post_to_discord')
    for base in ('/home/aiuser/kpop-ai-system/lib', '/home/aiuser/kpop-ai-system/pipeline'):
        for p in glob.glob(f'{base}/**/*.py', recursive=True):
            try:
                text = open(p, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            if any(k in text for k in keywords):
                found = True
                break
        if found:
            break
    assert found, "0件alert/通知パスが見つからない"
