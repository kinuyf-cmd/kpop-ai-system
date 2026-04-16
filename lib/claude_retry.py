"""
Claude CLI 呼び出しの retry ヘルパー

API 529 overloaded / rate_limit / 一時的失敗を指数バックオフで再試行する。

Usage:
  from claude_retry import claude_run
  result = claude_run(prompt, agent="arceus", max_retries=3)
"""
import re
import subprocess
import sys
import time


RETRYABLE_PATTERNS = [
    r"529",
    r"overloaded_error",
    r"Overloaded",
    r"rate_limit",
    r"rate limit",
    r"500 Internal",
    r"502 Bad Gateway",
    r"503 Service",
    r"504 Gateway",
    r"connection.*reset",
    r"timeout",
]


def is_retryable_error(text):
    if not text:
        return False
    for pat in RETRYABLE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def claude_run(
    prompt,
    agent=None,
    allowed_tools=None,
    max_retries=4,
    initial_wait=10,
    backoff_multiplier=2.0,
    timeout=300,
    no_session_persistence=True,
):
    """Claude CLI を retry付きで呼び出す

    Returns:
        str: stdout content
    Raises:
        RuntimeError: max_retries 超過 or 致命エラー
    """
    cmd = ["claude"]
    if no_session_persistence:
        cmd.append("--no-session-persistence")
    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])
    if agent:
        cmd.extend(["--agent", agent])
    cmd.extend(["-p", prompt])

    last_error = None
    wait = initial_wait

    for attempt in range(1, max_retries + 1):
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = (r.stdout or "").strip()
            stderr = (r.stderr or "").strip()

            # 成功判定: stdout に意味あるテキスト + retryableエラーなし
            if stdout and not is_retryable_error(stdout) and not is_retryable_error(stderr):
                return stdout

            # retryableエラー検出
            error_text = stdout + " " + stderr
            if is_retryable_error(error_text):
                last_error = f"retryable: {error_text[:200]}"
                sys.stderr.write(f"[claude_retry] attempt {attempt}/{max_retries} failed (retryable): {error_text[:100]}\n")
                if attempt < max_retries:
                    sys.stderr.write(f"[claude_retry] waiting {wait}s before retry...\n")
                    time.sleep(wait)
                    wait *= backoff_multiplier
                continue

            # 非retryableエラー or 空応答
            last_error = f"empty/non-retryable: stdout={stdout[:100]}, stderr={stderr[:100]}"
            sys.stderr.write(f"[claude_retry] attempt {attempt} non-retryable: {last_error}\n")
            break

        except subprocess.TimeoutExpired:
            last_error = f"timeout after {timeout}s"
            sys.stderr.write(f"[claude_retry] attempt {attempt}/{max_retries} timeout\n")
            if attempt < max_retries:
                time.sleep(wait)
                wait *= backoff_multiplier
            continue
        except Exception as e:
            last_error = f"exception: {e}"
            sys.stderr.write(f"[claude_retry] attempt {attempt} exception: {e}\n")
            if attempt < max_retries:
                time.sleep(wait)
                wait *= backoff_multiplier
            continue

    raise RuntimeError(f"claude_run failed after {max_retries} attempts: {last_error}")


# CLI テスト
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 claude_retry.py <prompt>")
        sys.exit(1)
    try:
        result = claude_run(sys.argv[1], max_retries=3, initial_wait=5)
        print(result)
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
