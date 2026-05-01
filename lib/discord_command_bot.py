#!/usr/bin/env python3
"""
discord_command_bot.py — Discord経由でClaude Codeに指示を送るBot

使い方 (Discordチャンネル内):
  kpop 今日の監査結果を教えて
  kpop 記事6065を監査して
  kpop ポップアップ記事を3本生成して
  !status                          ... Botの状態確認
  !help                            ... コマンド一覧

セキュリティ:
  DISCORD_OWNER_ID に設定したユーザーのみ実行可能。
  全コマンドを logs/discord_commands.jsonl にログ記録。

起動:
  python3 lib/discord_command_bot.py
  systemctl --user start kpop-discord-bot  (systemd)
"""
import asyncio
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import Intents
from dotenv import load_dotenv

BASE = Path('/home/aiuser/kpop-ai-system')
load_dotenv(BASE / '.env')

TOKEN = os.getenv('DISCORD_BOT_TOKEN', '')
OWNER_ID = int(os.getenv('DISCORD_OWNER_ID', '0') or '0')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', '0') or '0')

COMMAND_LOG = BASE / 'logs' / 'discord_commands.jsonl'
JST = timezone(timedelta(hours=9))

# Claude CLI 実行設定
CLAUDE_BIN = '/usr/bin/claude'
CLAUDE_TIMEOUT = 300  # 5分
CLAUDE_CWD = str(BASE)

# Discord メッセージ上限
MAX_MSG_LEN = 1900

intents = Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 同時実行制御: 1つずつ
_running = False


def log_command(user_id: int, user_name: str, command: str,
                result: str, duration: float = 0):
    """コマンドログを記録"""
    COMMAND_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        'timestamp': datetime.now(JST).isoformat(),
        'user_id': user_id,
        'user_name': user_name,
        'command': command[:500],
        'result': result[:200],
        'duration_sec': round(duration, 1),
    }
    with open(COMMAND_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def truncate_output(text: str) -> str:
    """Discord用に出力を切り詰める"""
    if len(text) <= MAX_MSG_LEN:
        return text
    # 先頭と末尾を残す
    head = text[:900]
    tail = text[-900:]
    return f"{head}\n\n... (省略: {len(text)}文字) ...\n\n{tail}"


async def run_claude(instruction: str) -> tuple[str, float]:
    """Claude CLIを非同期で実行"""
    env = os.environ.copy()
    env['ANTHROPIC_MODEL'] = os.getenv('ANTHROPIC_MODEL', '')

    start = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN, '-p', instruction,
            '--output-format', 'text',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=CLAUDE_CWD,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=CLAUDE_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = asyncio.get_event_loop().time() - start
            return f"タイムアウト ({CLAUDE_TIMEOUT}秒超過)", elapsed

        elapsed = asyncio.get_event_loop().time() - start
        output = stdout.decode('utf-8', errors='replace').strip()
        err = stderr.decode('utf-8', errors='replace').strip()

        if proc.returncode != 0 and not output:
            return f"エラー (code {proc.returncode}): {err[:500]}", elapsed

        # stderr にも有用な情報がある場合がある
        if err and not output:
            output = err

        return output or "(出力なし)", elapsed

    except Exception as e:
        elapsed = asyncio.get_event_loop().time() - start
        return f"実行エラー: {e}", elapsed


@client.event
async def on_ready():
    print(f"Bot起動: {client.user} (ID: {client.user.id})")
    print(f"Owner ID: {OWNER_ID}")
    print(f"Guild ID: {GUILD_ID}")
    print(f"Claude: {CLAUDE_BIN}")
    print("---")


@client.event
async def on_message(message: discord.Message):
    global _running

    # Bot自身のメッセージは無視
    if message.author == client.user:
        return

    content = message.content.strip()

    # --- !help ---
    if content.lower() == '!help':
        help_text = (
            "**K-POP AI System Bot**\n"
            "```\n"
            "kpop <指示>     ... Claude Codeに指示を送る\n"
            "!status         ... Bot状態を確認\n"
            "!help           ... このヘルプ\n"
            "```\n"
            "例: `kpop 今日公開した記事を一覧して`\n"
            "例: `kpop 総合監査を実行して`\n"
            "例: `kpop 記事6065のエラーを修正して`"
        )
        await message.channel.send(help_text)
        return

    # --- !status ---
    if content.lower() == '!status':
        now = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        status = "実行中" if _running else "待機中"
        await message.channel.send(
            f"```\nBot: {status}\n時刻: {now}\nOwner: {OWNER_ID}\n```"
        )
        return

    # --- kpop <指示> ---
    if content.lower().startswith('kpop '):
        instruction = content[5:].strip()
        if not instruction:
            await message.channel.send("指示を入力してください。例: `kpop 今日の監査結果`")
            return

        # オーナーチェック
        if OWNER_ID and message.author.id != OWNER_ID:
            await message.channel.send("このコマンドはオーナーのみ使用できます。")
            log_command(message.author.id, str(message.author),
                        instruction, "denied_not_owner")
            return

        # 同時実行チェック
        if _running:
            await message.channel.send("別のコマンドを実行中です。完了までお待ちください。")
            return

        _running = True
        await message.channel.send(f"実行中... `{instruction[:80]}`")

        try:
            output, elapsed = await run_claude(instruction)
            truncated = truncate_output(output)

            # 結果をコードブロックで返す
            response = f"**完了** ({elapsed:.1f}秒)\n```\n{truncated}\n```"
            if len(response) > 2000:
                # さらに切り詰め
                response = f"**完了** ({elapsed:.1f}秒)\n```\n{truncated[:1800]}\n```"

            await message.channel.send(response)
            log_command(message.author.id, str(message.author),
                        instruction, "success", elapsed)
        except Exception as e:
            await message.channel.send(f"Bot内部エラー: {e}")
            log_command(message.author.id, str(message.author),
                        instruction, f"bot_error: {e}")
        finally:
            _running = False


def main():
    if not TOKEN:
        print("DISCORD_BOT_TOKEN が .env に設定されていません")
        sys.exit(1)

    if not OWNER_ID:
        print("警告: DISCORD_OWNER_ID 未設定 — 全ユーザーからのコマンドを拒否します")
        print("  .env に DISCORD_OWNER_ID=あなたのDiscordユーザーID を追加してください")

    print(f"K-POP AI Discord Command Bot 起動中...")
    client.run(TOKEN)


if __name__ == '__main__':
    main()
