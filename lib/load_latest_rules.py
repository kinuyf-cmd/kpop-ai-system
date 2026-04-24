"""各AIスタッフ用: latest_rules.json を読んでプロンプトに注入するヘルパー"""
import json, os

RULES_PATH = '/home/aiuser/kpop-ai-system/config/latest_rules.json'


def load_rules() -> dict:
    if not os.path.exists(RULES_PATH):
        return {}
    try:
        return json.load(open(RULES_PATH, encoding='utf-8'))
    except Exception:
        return {}


def build_system_prompt_injection() -> str:
    """AIスタッフ用システムプロンプトに挿入する教訓+ルール"""
    r = load_rules()
    if not r:
        return ""

    parts = [
        "\n## 【重要】現行の記事投稿ルール (version: " + r.get('version', '?') + ")",
        "",
        "### 記事タイプ比率 (必須)",
        f"- NEWS: {int(r['article_type_ratio']['NEWS']*100)}% / GUIDE: {int(r['article_type_ratio']['GUIDE']*100)}% / FEATURE: {int(r['article_type_ratio']['FEATURE']*100)}%以下",
        f"- FEATURE週{r['article_type_ratio']['FEATURE_weekly_max']}本上限",
        "",
        "### 禁止タイトルパターン (HARD_FAIL)",
        ", ".join(r.get('banned_title_patterns', [])),
        "",
        "### 禁止事項 (AI社員への指示)",
    ]
    for item in r.get('forbidden_actions_for_ai_staff', []):
        parts.append(f"- {item}")

    parts.append("")
    parts.append("### 累積教訓")
    for item in r.get('lessons_learned', []):
        parts.append(f"- {item}")

    return "\n".join(parts)


if __name__ == '__main__':
    print(build_system_prompt_injection())
