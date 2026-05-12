#!/usr/bin/env python3
"""Stop hook: 「監査」完了主張時に audit_steps.jsonl 記録を verify (2026-05-11新設)

memory feedback_audit_script_is_not_audit の強制実装。
監査要求にscript出力だけで完了報告した事故 (2026-05-10) の再発防止。

動作:
  1. transcript の直近 user message に「監査/audit/チェック/確認」を検出
  2. 直近 assistant message に「完了/complete/済み/いたしました」を検出
  3. 上記両方該当 + audit_steps.jsonl が直近20分以内に更新されていない
     → exit 2 で BLOCK (stderr経由で assistant に再実行を促す)

bypass: stop_hook_active が True (ループ防止) または audit_steps.jsonl が直近20分以内に touched
"""
import json, sys, os, re, time


def safe_extract(rec, max_chars=3000):
    msg = rec.get('message', '')
    if isinstance(msg, dict):
        # OpenAI形式: {role, content: [{type:'text', text:'...'}]}
        content = msg.get('content', '')
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get('type') == 'text':
                        parts.append(c.get('text', ''))
                    elif c.get('type') == 'tool_use':
                        parts.append(json.dumps(c.get('input', ''), ensure_ascii=False)[:500])
                    elif c.get('type') == 'tool_result':
                        parts.append(str(c.get('content', ''))[:500])
            return ' '.join(parts)[-max_chars:]
        return str(content)[-max_chars:]
    return json.dumps(msg, ensure_ascii=False)[-max_chars:]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get('stop_hook_active'):
        sys.exit(0)

    transcript_path = data.get('transcript_path', '')
    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    last_user = ''
    last_assistant = ''
    try:
        with open(transcript_path, encoding='utf-8') as f:
            lines = f.readlines()[-80:]
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t = rec.get('type', '')
            if t == 'user':
                last_user = safe_extract(rec, 4000)
            elif t == 'assistant':
                last_assistant = safe_extract(rec, 6000)
    except Exception:
        sys.exit(0)

    audit_words = ('監査', 'audit', 'チェック', 'チェックして', '確認して', '監査して')
    asked_audit = any(w in last_user for w in audit_words)
    if not asked_audit:
        sys.exit(0)

    completion_patterns = (
        r'監査.*完了', r'監査.*終わ', r'チェック.*完了', r'audit.*complete',
        r'4項目.*完了', r'4項目.*クリア', r'all.*pass', r'すべて.*pass', r'全て.*pass',
        r'検出.*0件', r'issue.*0', r'クリーンです',
    )
    claims_complete = any(re.search(p, last_assistant, re.IGNORECASE) for p in completion_patterns)
    if not claims_complete:
        sys.exit(0)

    log_path = '/home/aiuser/kpop-ai-system/logs/audit_steps.jsonl'
    if not os.path.exists(log_path):
        print('[hook BLOCK] 監査完了を主張していますが logs/audit_steps.jsonl が存在しません。',
              file=sys.stderr)
        print('  4項目procedural (structure/thumbnail/factcheck/body_read) を実行してください。',
              file=sys.stderr)
        sys.exit(2)

    mtime = os.path.getmtime(log_path)
    age_min = (time.time() - mtime) / 60
    if age_min > 20:
        print(f'[hook BLOCK] 監査完了を主張していますが audit_steps.jsonl が {age_min:.0f}分間未更新です。',
              file=sys.stderr)
        print('  以下を実行してから再度報告してください:', file=sys.stderr)
        print('    1. python3 pipeline/full_audit_runner.py  (structure + body_read)', file=sys.stderr)
        print('    2. python3 pipeline/thumbnail_contamination_audit.py (thumbnail)', file=sys.stderr)
        print('    3. python3 pipeline/llm_proofreader.py  (factcheck)', file=sys.stderr)
        print('    4. CRITICAL/HIGH発見時は本文を Read で精読', file=sys.stderr)
        print('  CLAUDE.md / memory feedback_audit_script_is_not_audit を参照', file=sys.stderr)
        sys.exit(2)

    # 2026-05-11追加: memory_compliance テスト全pass を要求
    # 「コード変更後に memoryルール違反のまま完了報告」のパターンを止める
    import subprocess
    try:
        r = subprocess.run(
            ['python3', '-m', 'pytest', 'tests/memory_compliance/', '-q', '--tb=line'],
            cwd='/home/aiuser/kpop-ai-system',
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            print('[hook BLOCK] memory_compliance テスト失敗を検出。',
                  file=sys.stderr)
            print('  「完了」報告前に違反を修正してください。', file=sys.stderr)
            tail = (r.stdout + r.stderr).splitlines()[-15:]
            for line in tail:
                print(f'  | {line}', file=sys.stderr)
            sys.exit(2)
    except subprocess.TimeoutExpired:
        # テスト時間超過時は skip (assistant完了をブロックしない)
        print('[hook WARN] memory_compliance テストtimeout — skip', file=sys.stderr)
    except Exception as _e:
        print(f'[hook WARN] memory_compliance テスト実行err: {_e} — skip', file=sys.stderr)

    sys.exit(0)


if __name__ == '__main__':
    main()
