"""緊急アラート → Discord #🚨-緊急アラート"""
import os, json, glob
from lib.discord_client import post_to_channel

def check_and_alert():
    alerts = []
    for f in sorted(glob.glob('logs/pipeline_alerts.log'))[-1:]:
        try:
            lines = open(f).read().splitlines()[-20:]
            critical = [l for l in lines if 'NameError' in l or 'Traceback' in l]
            if len(critical) > 3:
                alerts.append(f'パイプライン例外 {len(critical)}件')
        except: pass
    if alerts:
        post_to_channel('緊急アラート', '🚨 **緊急**: ' + ', '.join(alerts))
    return alerts

if __name__ == '__main__':
    print(f'Alerts: {check_and_alert()}')
