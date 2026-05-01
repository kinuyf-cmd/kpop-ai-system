"""Discord連携モジュール"""
import os, json, requests
try:
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
except: pass

TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', '0') or 0)
API = 'https://discord.com/api/v10'
HEADERS = {'Authorization': f'Bot {TOKEN}', 'Content-Type': 'application/json'}

def post_to_channel(ch_name, message):
    if not TOKEN or not GUILD_ID:
        return False
    try:
        r = requests.get(f'{API}/guilds/{GUILD_ID}/channels', headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return False
        channels = r.json()
        target = ch_name.lower().replace(' ', '-')
        ch = next((c for c in channels if target in c.get('name', '') or c.get('name', '') in target), None)
        if not ch:
            return False
        r2 = requests.post(f'{API}/channels/{ch["id"]}/messages', headers=HEADERS,
                           json={'content': message[:2000]}, timeout=10)
        return r2.status_code in [200, 201]
    except:
        return False

def post_as_staff(staff_id, message):
    try:
        webhooks = json.load(open('/home/aiuser/kpop-ai-system/config/staff_webhooks.json'))
    except:
        webhooks = {}
    wh = webhooks.get(staff_id)
    if not wh:
        return post_to_channel('💬-全社コミュニケーション', f'[{staff_id}] {message}')
    try:
        return requests.post(wh['url'], json={'content': message[:2000], 'username': wh.get('name', staff_id)},
                             timeout=10).status_code == 204
    except:
        return False

def create_channel(name, category_id=None):
    if not TOKEN or not GUILD_ID:
        return None
    payload = {'name': name, 'type': 0}
    if category_id:
        payload['parent_id'] = str(category_id)
    try:
        r = requests.post(f'{API}/guilds/{GUILD_ID}/channels', headers=HEADERS, json=payload, timeout=10)
        return r.json() if r.status_code in [200, 201] else None
    except:
        return None

def create_category(name):
    if not TOKEN or not GUILD_ID:
        return None
    try:
        r = requests.post(f'{API}/guilds/{GUILD_ID}/channels', headers=HEADERS,
                          json={'name': name, 'type': 4}, timeout=10)
        return r.json() if r.status_code in [200, 201] else None
    except:
        return None

def get_channels():
    if not TOKEN or not GUILD_ID:
        return []
    try:
        r = requests.get(f'{API}/guilds/{GUILD_ID}/channels', headers=HEADERS, timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []


def post_as_staff_in_channel(staff_id, message, channel_name):
    """発言する場所 (channel_name) に応じてwebhookを選択"""
    try:
        webhooks = json.load(open('/home/aiuser/kpop-ai-system/config/staff_webhooks.json'))
    except:
        return False

    # チャネル名→webhookキーのマッピング
    suffix_map = [
        ('役員', 'exec'), ('経営指標', 'board'), ('board', 'board'),
        ('緊急', 'alert'), ('alert', 'alert'),
        ('朝会', 'morning'), ('終礼', 'morning'),
        ('全社', 'all'),
    ]
    for keyword, suffix in suffix_map:
        if keyword in channel_name.lower():
            key = f'{staff_id}-{suffix}'
            wh = webhooks.get(key)
            if wh:
                try:
                    r = requests.post(wh['url'],
                                      json={'content': message[:2000], 'username': wh.get('name', staff_id)},
                                      timeout=10)
                    if r.status_code == 204:
                        return True
                except:
                    pass

    # デフォルト: 部署webhook
    return post_as_staff(staff_id, message)
