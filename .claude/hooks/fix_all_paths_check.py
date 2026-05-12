#!/usr/bin/env python3
"""Stop hook: 「修正完了」主張時に grep 全経路検査の証跡を verify (2026-05-12新設)

memory feedback_fix_all_paths の強制実装。
「1ファイルだけ修正して完了報告 → 他経路に同パターン残存」事故の再発防止。

動作:
  1. 直近 user message に「修正/fix/直して/なおして」検出
  2. 直近 assistant message に「修正完了/fix完了/直した/done/fixed」検出
  3. 直近 assistant tool_use に Edit/Write が 1回以上ある
  4. Edit/Write の前に grep/rg/find/Grep tool による全経路検査がない
     → exit 2 で BLOCK

skip 条件 (過剰検出回避):
  - Edit/Write が 1ファイルのみ (= 全経路 = 1経路) かつ test_/script で「全経路無関係」っぽい場合
  - stop_hook_active (ループ防止)
  - 直近に Bash grep / Grep tool / rg があれば PASS
"""
import json, sys, os, re


def iter_recent_records(transcript_path, n=120):
    try:
        with open(transcript_path, encoding='utf-8') as f:
            lines = f.readlines()[-n:]
    except Exception:
        return
    for line in lines:
        try:
            yield json.loads(line)
        except Exception:
            continue


def extract_text(rec, max_chars=4000):
    msg = rec.get('message', '')
    if isinstance(msg, dict):
        content = msg.get('content', '')
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'text':
                    parts.append(c.get('text', ''))
            return ' '.join(parts)[-max_chars:]
        return str(content)[-max_chars:]
    return json.dumps(msg, ensure_ascii=False)[-max_chars:]


def iter_tool_uses(rec):
    msg = rec.get('message', '')
    if not isinstance(msg, dict):
        return
    content = msg.get('content', '')
    if not isinstance(content, list):
        return
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'tool_use':
            yield c.get('name', ''), c.get('input', {}) or {}


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
    last_assistant_text = ''
    edit_files = []
    saw_grep = False

    for rec in iter_recent_records(transcript_path, n=120):
        t = rec.get('type', '')
        if t == 'user':
            last_user = extract_text(rec, 4000)
            # 新しい user 入力で edit/grep history をリセット (前ターン分は対象外)
            edit_files = []
            saw_grep = False
        elif t == 'assistant':
            last_assistant_text = extract_text(rec, 6000)
            for name, inp in iter_tool_uses(rec):
                if name in ('Edit', 'Write', 'NotebookEdit'):
                    p = inp.get('file_path') or inp.get('notebook_path') or ''
                    if p:
                        edit_files.append(p)
                elif name in ('Grep',):
                    saw_grep = True
                elif name == 'Bash':
                    cmd = str(inp.get('command', ''))
                    if re.search(r'\b(grep|rg|ripgrep|ag|find\s+.*-name)\b', cmd):
                        saw_grep = True

    fix_request_words = ('修正', 'fix', '直して', 'なおして', '直し', '治して', 'refactor')
    asked_fix = any(w in last_user for w in fix_request_words)
    if not asked_fix:
        sys.exit(0)

    completion_patterns = (
        r'修正.*完了', r'修正.*済', r'fix.*complete', r'fixed', r'直し[まし]た',
        r'なおし[まし]た', r'修正しました', r'対応完了', r'対応しました',
    )
    claims_complete = any(re.search(p, last_assistant_text, re.IGNORECASE) for p in completion_patterns)
    if not claims_complete:
        sys.exit(0)

    if not edit_files:
        # 編集していないなら fix_all_paths の対象外
        sys.exit(0)

    if saw_grep:
        sys.exit(0)

    # 単一ファイル & test/script 系は全経路無関係の可能性 → WARN だけ
    uniq_files = set(edit_files)
    soft_targets_only = all(
        ('/test' in p) or ('/scripts/' in p) or p.endswith(('.md', '.json', '.txt'))
        for p in uniq_files
    )
    if len(uniq_files) == 1 and soft_targets_only:
        sys.exit(0)

    print('[hook BLOCK] 修正完了を主張していますが全経路 grep の証跡がありません。', file=sys.stderr)
    print(f'  編集ファイル: {", ".join(sorted(uniq_files))[:200]}', file=sys.stderr)
    print('  以下のいずれかを実行してから再度報告してください:', file=sys.stderr)
    print('    1. grep / rg で対象シンボルを全コードベースから検索 (Bash か Grep tool)', file=sys.stderr)
    print('    2. 同じパターンが他ファイルに残っていないことを確認', file=sys.stderr)
    print('  memory feedback_fix_all_paths を参照', file=sys.stderr)
    sys.exit(2)


if __name__ == '__main__':
    main()
