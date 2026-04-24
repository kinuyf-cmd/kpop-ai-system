#!/usr/bin/env python3
"""
model_selector.py — エージェント別モデル自動選択

config/model_tier.json に基づき、エージェント名からClaude CLI の
--model フラグ用のモデルIDを返す。

Usage:
  # シェルスクリプトから:
  MODEL=$(python3 lib/model_selector.py butterfree)
  claude --model "$MODEL" --agent butterfree -p "..."

  # Pythonから:
  from model_selector import get_model
  model = get_model("butterfree")  # → "claude-opus-4-6"

  # コスト見積:
  python3 lib/model_selector.py --report
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config" / "model_tier.json"

# デフォルト: model_tier.json が読めない場合のフォールバック
DEFAULT_MODEL = "claude-sonnet-4-6"


def _load_config() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_model(agent_name: str) -> str:
    """エージェント名からモデルIDを返す"""
    config = _load_config()
    models = config.get("models", {})
    tiers = config.get("agent_tiers", {})

    agent_config = tiers.get(agent_name, {})
    tier = agent_config.get("tier", "sonnet")
    return models.get(tier, DEFAULT_MODEL)


def get_tier(agent_name: str) -> str:
    """エージェント名からティア名(haiku/sonnet/opus)を返す"""
    config = _load_config()
    tiers = config.get("agent_tiers", {})
    return tiers.get(agent_name, {}).get("tier", "sonnet")


def get_all_tiers() -> dict[str, dict]:
    """全エージェントのティア設定を返す"""
    config = _load_config()
    return config.get("agent_tiers", {})


def report():
    """ティア別のエージェント一覧とコスト見積を表示"""
    config = _load_config()
    models = config.get("models", {})
    tiers = config.get("agent_tiers", {})
    costs = config.get("cost_estimate", {})

    by_tier: dict[str, list] = {"haiku": [], "sonnet": [], "opus": []}
    for agent, info in sorted(tiers.items()):
        tier = info.get("tier", "sonnet")
        by_tier.setdefault(tier, []).append((agent, info.get("reason", "")))

    print("═══ モデルティア レポート ═══\n")

    for tier_name in ["haiku", "sonnet", "opus"]:
        agents = by_tier.get(tier_name, [])
        model_id = models.get(tier_name, "?")
        cost = costs.get(tier_name, "?")
        print(f"【{tier_name.upper()}】{model_id}  (コスト比: {cost})")
        for agent, reason in agents:
            print(f"  - {agent}: {reason}")
        print(f"  合計: {len(agents)}エージェント\n")

    # コスト削減効果推定
    haiku_count = len(by_tier.get("haiku", []))
    sonnet_count = len(by_tier.get("sonnet", []))
    opus_count = len(by_tier.get("opus", []))
    total = haiku_count + sonnet_count + opus_count

    # 全Opus時のコスト vs ティア制のコスト
    all_opus_cost = total * 1.0
    tier_cost = (haiku_count * float(costs.get("haiku", 0.04))
                 + sonnet_count * float(costs.get("sonnet", 0.2))
                 + opus_count * float(costs.get("opus", 1.0)))
    saving = round((1 - tier_cost / all_opus_cost) * 100, 1) if all_opus_cost else 0

    print(f"═══ コスト削減効果 ═══")
    print(f"  全Opus時: {all_opus_cost:.1f}（基準）")
    print(f"  ティア制: {tier_cost:.2f}")
    print(f"  削減率: {saving}%")
    print(f"  Haiku={haiku_count} Sonnet={sonnet_count} Opus={opus_count}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <agent_name> | --report", file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--report":
        report()
    else:
        print(get_model(sys.argv[1]))


if __name__ == "__main__":
    main()
