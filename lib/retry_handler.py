#!/usr/bin/env python3
"""
Retry Handler - 投稿失敗時の自動再試行 + 指数バックオフ + fallbackエージェント
監査本部（バンギラス/ドリュウズ）管轄
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")


class RetryConfig:
    """リトライ設定"""
    WP_API_MAX_RETRIES = 3
    WP_API_BASE_DELAY = 5       # 秒
    WP_API_MAX_DELAY = 60

    CLAUDE_MAX_RETRIES = 2
    CLAUDE_BASE_DELAY = 10
    CLAUDE_MAX_DELAY = 120

    INDEX_API_MAX_RETRIES = 3
    INDEX_API_BASE_DELAY = 3
    INDEX_API_MAX_DELAY = 30

    X_API_MAX_RETRIES = 2
    X_API_BASE_DELAY = 5
    X_API_MAX_DELAY = 30


def exponential_backoff(attempt, base_delay, max_delay, jitter=True):
    """指数バックオフ計算"""
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        import random
        delay = delay * (0.5 + random.random() * 0.5)
    return delay


def retry_wp_post(post_func, *args, **kwargs):
    """WordPress投稿のリトライ"""
    for attempt in range(RetryConfig.WP_API_MAX_RETRIES):
        try:
            result = post_func(*args, **kwargs)

            # ステータスコードチェック
            status = result.get("status_code", 0)
            if status == 201:
                return {"success": True, "attempt": attempt + 1, "data": result}
            elif status == 429:
                # Rate limit - 長めに待つ
                delay = exponential_backoff(attempt, 30, 120)
                _log_retry("wp_api", attempt, f"Rate limited (429), waiting {delay:.0f}s")
                time.sleep(delay)
            elif 500 <= status < 600:
                delay = exponential_backoff(attempt, RetryConfig.WP_API_BASE_DELAY, RetryConfig.WP_API_MAX_DELAY)
                _log_retry("wp_api", attempt, f"Server error ({status}), waiting {delay:.0f}s")
                time.sleep(delay)
            else:
                # 4xx (not 429) はリトライしない
                return {"success": False, "attempt": attempt + 1, "error": f"HTTP {status}", "data": result}

        except Exception as e:
            delay = exponential_backoff(attempt, RetryConfig.WP_API_BASE_DELAY, RetryConfig.WP_API_MAX_DELAY)
            _log_retry("wp_api", attempt, f"Exception: {e}, waiting {delay:.0f}s")
            time.sleep(delay)

    return {"success": False, "attempt": RetryConfig.WP_API_MAX_RETRIES, "error": "Max retries exceeded"}


def retry_claude_agent(agent_name, prompt, output_file, fallback_agents=None):
    """Claude エージェント実行のリトライ + フォールバック"""
    agents_to_try = [agent_name]
    if fallback_agents:
        agents_to_try.extend(fallback_agents)

    for agent in agents_to_try:
        for attempt in range(RetryConfig.CLAUDE_MAX_RETRIES):
            try:
                result = subprocess.run(
                    ["claude", "--dangerously-skip-permissions", "--agent", agent, "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=os.path.expanduser("~"),
                )

                if result.returncode == 0 and result.stdout.strip():
                    # 出力検証
                    output = result.stdout.strip()
                    if _is_valid_agent_output(output):
                        with open(output_file, "w", encoding="utf-8") as f:
                            f.write(output)
                        return {
                            "success": True,
                            "agent": agent,
                            "attempt": attempt + 1,
                            "is_fallback": agent != agent_name,
                        }
                    else:
                        _log_retry("claude", attempt, f"Agent {agent}: invalid output")
                else:
                    _log_retry("claude", attempt, f"Agent {agent}: returncode={result.returncode}")

                delay = exponential_backoff(attempt, RetryConfig.CLAUDE_BASE_DELAY, RetryConfig.CLAUDE_MAX_DELAY)
                time.sleep(delay)

            except subprocess.TimeoutExpired:
                _log_retry("claude", attempt, f"Agent {agent}: timeout")
                delay = exponential_backoff(attempt, RetryConfig.CLAUDE_BASE_DELAY, RetryConfig.CLAUDE_MAX_DELAY)
                time.sleep(delay)
            except Exception as e:
                _log_retry("claude", attempt, f"Agent {agent}: {e}")
                break  # 予期しないエラーはスキップ

        if agent != agents_to_try[-1]:
            _log_retry("claude", 0, f"Falling back from {agent} to next agent")

    return {"success": False, "agent": agent_name, "error": "All agents failed"}


def retry_index_api(index_func, url, *args, **kwargs):
    """Google/Bing インデックスAPIのリトライ"""
    for attempt in range(RetryConfig.INDEX_API_MAX_RETRIES):
        try:
            result = index_func(url, *args, **kwargs)
            if result.get("success", False):
                return {"success": True, "attempt": attempt + 1}

            delay = exponential_backoff(attempt, RetryConfig.INDEX_API_BASE_DELAY, RetryConfig.INDEX_API_MAX_DELAY)
            _log_retry("index_api", attempt, f"Failed for {url}, waiting {delay:.0f}s")
            time.sleep(delay)

        except Exception as e:
            delay = exponential_backoff(attempt, RetryConfig.INDEX_API_BASE_DELAY, RetryConfig.INDEX_API_MAX_DELAY)
            _log_retry("index_api", attempt, f"Exception: {e}")
            time.sleep(delay)

    return {"success": False, "attempt": RetryConfig.INDEX_API_MAX_RETRIES, "error": "Max retries exceeded"}


def retry_x_post(post_func, *args, **kwargs):
    """X/Twitter投稿のリトライ"""
    for attempt in range(RetryConfig.X_API_MAX_RETRIES):
        try:
            result = post_func(*args, **kwargs)
            if result.get("success", False):
                return {"success": True, "attempt": attempt + 1}

            delay = exponential_backoff(attempt, RetryConfig.X_API_BASE_DELAY, RetryConfig.X_API_MAX_DELAY)
            time.sleep(delay)

        except Exception as e:
            delay = exponential_backoff(attempt, RetryConfig.X_API_BASE_DELAY, RetryConfig.X_API_MAX_DELAY)
            _log_retry("x_api", attempt, f"Exception: {e}")
            time.sleep(delay)

    return {"success": False, "attempt": RetryConfig.X_API_MAX_RETRIES, "error": "Max retries exceeded"}


def _is_valid_agent_output(output):
    """エージェント出力の基本検証"""
    if not output or len(output) < 100:
        return False
    ng_phrases = [
        "申し訳ありません", "お手伝いできますか", "AIとして",
        "言語モデル", "できません", "質問があります",
    ]
    if any(phrase in output[:500] for phrase in ng_phrases):
        return False
    return True


def _log_retry(category, attempt, message):
    """リトライログの記録"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "category": category,
        "attempt": attempt + 1,
        "message": message,
    }
    log_file = os.path.join(LOGS_DIR, "retry_log.jsonl")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── フォールバックエージェント設定 ──

FALLBACK_MAP = {
    "deoxys_kpop": ["metamon_kpop"],
    "metamon_kpop": ["deoxys_kpop"],
    "jirachi_kpop": ["alakazam_kpop"],
    "beautywriter": ["deoxys_kpop"],
    "zapdos": ["deoxys_kpop"],
    "persian": [],  # SNS戦略は失敗許容
}


def get_fallback_agents(agent_name):
    """エージェントのフォールバック先を取得"""
    return FALLBACK_MAP.get(agent_name, [])


if __name__ == "__main__":
    print(json.dumps({
        "retry_config": {
            "wp_api": {"max_retries": RetryConfig.WP_API_MAX_RETRIES, "base_delay": RetryConfig.WP_API_BASE_DELAY},
            "claude": {"max_retries": RetryConfig.CLAUDE_MAX_RETRIES, "base_delay": RetryConfig.CLAUDE_BASE_DELAY},
            "index_api": {"max_retries": RetryConfig.INDEX_API_MAX_RETRIES},
            "x_api": {"max_retries": RetryConfig.X_API_MAX_RETRIES},
        },
        "fallback_map": FALLBACK_MAP,
    }, ensure_ascii=False, indent=2))
