"""cron登録状況とpipeline_registryの差分監査 + 自動修復"""
import json, subprocess, re, os, sys, time

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

REGISTRY = 'config/pipeline_registry.json'


def audit():
    reg = json.load(open(REGISTRY))
    crontab = subprocess.check_output(['crontab', '-l']).decode()
    cron_lines = [l for l in crontab.split('\n') if l.strip() and not l.strip().startswith('#')]
    now = time.time()

    issues = {'missing_cron': [], 'no_log': [], 'silent': []}

    for name, info in reg['pipelines'].items():
        # cron存在確認 (module名 → pipeline名 → aliases の順で照合)
        module = info.get('module', '')
        aliases = info.get('aliases', [])
        found = any(
            (module and module in l)
            or name in l
            or any(a in l for a in aliases)
            for l in cron_lines
        )
        if not found:
            issues['missing_cron'].append({
                'pipeline': name,
                'expected_cron': info['cron'],
                'category': info['category'],
            })

        # ログ存在確認
        log_path = info['log']
        if not os.path.exists(log_path):
            issues['no_log'].append({'pipeline': name, 'log': log_path, 'category': info['category']})
        else:
            elapsed_min = (now - os.path.getmtime(log_path)) / 60
            if elapsed_min > info['max_silence_min']:
                issues['silent'].append({
                    'pipeline': name,
                    'silent_min': int(elapsed_min),
                    'max_min': info['max_silence_min'],
                    'category': info['category'],
                })

    return issues


def auto_fix_cron(issues):
    """missing_cronを自動修復"""
    if not issues['missing_cron']:
        print('全pipelineがcron登録済み')
        return 0

    reg = json.load(open(REGISTRY))
    crontab = subprocess.check_output(['crontab', '-l']).decode()
    new_lines = []

    for item in issues['missing_cron']:
        name = item['pipeline']
        info = reg['pipelines'][name]
        run_cmd = info.get('run_cmd', f"python3 -m {info['module']}")
        entry = f"{info['cron']} cd /home/aiuser/kpop-ai-system && {run_cmd} >> {info['log']} 2>&1"
        new_lines.append(entry)
        print(f'  追加: {name} ({info["cron"]})')

    new_crontab = crontab.rstrip() + '\n' + '\n'.join(new_lines) + '\n'
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cron', delete=False) as f:
        f.write(new_crontab)
        tmp = f.name
    subprocess.run(['crontab', tmp], check=True)
    os.unlink(tmp)
    print(f'\n{len(new_lines)}件のcron自動登録完了')
    return len(new_lines)


if __name__ == '__main__':
    iss = audit()

    print(f'=== cron_audit 結果 ===')
    print(f'cron未登録: {len(iss["missing_cron"])}件')
    for p in iss['missing_cron']:
        print(f'  [{p["category"]}] {p["pipeline"]} -> {p["expected_cron"]}')

    print(f'\nログ不在: {len(iss["no_log"])}件')
    for p in iss['no_log']:
        print(f'  [{p["category"]}] {p["pipeline"]} ({p["log"]})')

    print(f'\n沈黙中: {len(iss["silent"])}件')
    for p in iss['silent']:
        print(f'  [{p["category"]}] {p["pipeline"]} {p["silent_min"]}分 (閾値{p["max_min"]}分)')

    # --fix オプションで自動修復
    if '--fix' in sys.argv:
        print('\n=== 自動修復 ===')
        auto_fix_cron(iss)
