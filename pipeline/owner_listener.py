"""オーナー発言→該当役員/部門長が独立人格でGPT応答+task assign+担当社員ack"""
import os, json, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
try:
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
except Exception:
    pass
import discord
from openai import OpenAI
from lib.staff_task_manager import assign_task
from lib.discord_client import post_as_staff, post_to_channel
from lib.staff_persona import get_persona_prompt, get_responder_for_message

TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', '0') or 0)
intents = discord.Intents.default()
# message_content intent: Developer Portal で Privileged Gateway Intents を有効にすること
# 未有効の場合 msg.content が空になるが、on_message は発火する
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)
client = OpenAI()

# message_content intent 未有効時の警告フラグ
_intent_warned = False


def load_roster():
    try:
        return json.load(open('config/staff_roster.json', encoding='utf-8'))
    except Exception:
        return {'individual_staff': {}, 'departments': {}}


def find_staff_by_mention(text):
    """オーナー発言から@社員ID or コード名のmention検出"""
    roster = load_roster()
    mentions = []
    for staff_id, info in roster.get('individual_staff', {}).items():
        code = info.get('code_name', '')
        if not code:
            continue
        if f'@{staff_id}' in text or f'@{code}' in text or staff_id in text:
            mentions.append(staff_id)
        elif code in text and len(code) >= 3:
            mentions.append(staff_id)
    return list(set(mentions))


def parse_owner_directive(content):
    if any(k in content for k in ['記事生成', '記事を作', '書いて', '執筆']):
        return 'create_article'
    if any(k in content for k in ['監査', 'チェック', '点検', '確認']):
        return 'audit'
    if any(k in content for k in ['修正', 'fix', '直して', 'rewrite']):
        return 'fix'
    if any(k in content for k in ['公開', '投稿', 'publish', 'post']):
        return 'publish'
    if any(k in content for k in ['報告', 'レポート', 'status', '状況']):
        return 'report'
    if any(k in content for k in ['停止', '停めて', 'stop', 'pause']):
        return 'stop'
    return 'general'


@bot.event
async def on_ready():
    print(f'✓ owner_listener起動 (独立人格版): {bot.user}')
    print(f'  guild_id={GUILD_ID}')
    print(f'  intents.message_content={intents.message_content}')
    print(f'  intents.members={intents.members}')
    guild = bot.get_guild(GUILD_ID)
    if guild:
        print(f'  guild="{guild.name}" members={guild.member_count}')
    else:
        print(f'  WARN: guild {GUILD_ID} not found')


@bot.event
async def on_message(msg):
    global _intent_warned
    if msg.author.bot:
        return
    if msg.guild and msg.guild.id != GUILD_ID:
        return

    content = msg.content.strip()
    # message_content intent 未有効検知: 人間がメッセージを送ったのに content が空
    if not content:
        if not _intent_warned and not msg.attachments and not msg.embeds:
            _intent_warned = True
            print(f'WARN: msg.content が空 (message_content intent未有効の可能性)。'
                  f'author={msg.author}, ch={msg.channel.name}')
        return

    ch_name = msg.channel.name
    responder_id = get_responder_for_message(ch_name, content)
    roster = load_roster()
    responder = roster.get('individual_staff', {}).get(responder_id, {})
    responder_name = responder.get('code_name', 'デオキシス')
    responder_role = responder.get('role_name', 'CEO')

    mentioned = find_staff_by_mention(content)
    directive_type = parse_owner_directive(content)
    mention_info = ''
    if mentioned:
        names = [roster['individual_staff'].get(sid, {}).get('code_name', '')
                 for sid in mentioned[:3]]
        mention_info = f'\nオーナーは {", ".join(n for n in names if n)} を指名しています。'

    # 役員/部門長応答 (persona prompt使用)
    reply = '[応答生成失敗]'
    try:
        persona = get_persona_prompt(responder_id) or ''
        prompt = f"""{persona}

チャネル #{ch_name} でオーナーが以下を発言しました。
{mention_info}
司令種別: {directive_type}

応答ルール (300字以内):
1. 内容を理解、実行可否を判定
2. 実行可能なら担当社員/部門を明示し「○○に指示しました」と宣言
3. 実行不可なら理由
4. 詳細不足なら追加質問

オーナー発言: {content[:1500]}"""
        r = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=500,
        )
        reply = r.choices[0].message.content
        posted = post_as_staff(responder_id, reply)
        if not posted:
            await msg.channel.send(f'**{responder_name} ({responder_role})**: {reply}')
    except Exception as e:
        print(f'役員応答ERR: {e}')

    # 個別社員へのtask assign + GPT受領発言
    if mentioned:
        for sid in mentioned[:5]:
            task_id = assign_task(sid, f'owner_directive_{directive_type}',
                                 meta={'owner_message': content[:500],
                                       'channel': ch_name,
                                       'responder': responder_id})
            s_info = roster.get('individual_staff', {}).get(sid, {})
            s_code = s_info.get('code_name', '')
            try:
                m_persona = get_persona_prompt(sid) or ''
                m_prompt = f"""{m_persona}

{responder_name}({responder_role})から以下のタスクが振り分けられました:
{content[:500]}
タスクID: {task_id}

200字以内で受領コメントを書いてください。テンプレートでなく、自分の専門・性格に基づく独自の応答を。"""
                m_r = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{'role': 'user', 'content': m_prompt}],
                    max_tokens=300,
                )
                ack = m_r.choices[0].message.content
            except Exception:
                ack = (f'承知しました、{responder_name}{responder_role[:3]}。'
                       f'タスク {task_id} 受領、業務開始します。\n— {s_code}')
            post_as_staff(sid, ack)
    elif directive_type != 'general':
        assign_task(responder_id, f'owner_directive_{directive_type}',
                    meta={'owner_message': content[:500], 'channel': ch_name})

    # ログ
    os.makedirs('logs', exist_ok=True)
    with open('logs/owner_directives.log', 'a') as f:
        f.write(json.dumps({
            'time': msg.created_at.isoformat(),
            'channel': ch_name,
            'owner': content[:500],
            'responder': responder_id,
            'directive_type': directive_type,
            'mentioned': mentioned,
            'reply': reply[:300],
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    bot.run(TOKEN)
