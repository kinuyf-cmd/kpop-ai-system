#!/usr/bin/env python3
"""
article_topic_classifier.py — Classify K-POP articles as concrete or abstract.

Concrete = about a specific artist, group, brand, place, or event.
Abstract = general topic (trends, guides, how-tos, culture, etc.).

Usage:
  python3 lib/article_topic_classifier.py --title "BTSのV、新曲MVが1億回再生突破"
"""

import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "concrete_vs_abstract.json"


def _load_config() -> dict:
    """Load concrete_vs_abstract.json."""
    if not CONFIG_PATH.exists():
        sys.stderr.write(f"[classifier] config not found: {CONFIG_PATH}\n")
        return {"concrete_triggers": {}, "abstract_triggers": []}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def classify(title: str, body: str = "") -> dict:
    """
    Classify an article as concrete or abstract.

    Args:
        title: Article title (required)
        body: Article body text (optional, improves accuracy)

    Returns:
        {
            "type": "concrete" | "abstract",
            "subjects": [...found concrete names...],
            "triggers_found": [...matched trigger strings...],
            "confidence": float (0.0 - 1.0)
        }
    """
    config = _load_config()
    text = f"{title} {body}".strip()
    text_lower = text.lower()

    concrete_triggers = config.get("concrete_triggers", {})
    abstract_triggers = config.get("abstract_triggers", [])

    subjects = []
    concrete_found = []
    abstract_found = []

    # Scan for concrete triggers across all categories
    for category, triggers in concrete_triggers.items():
        for trigger in triggers:
            # Case-insensitive match for ASCII, exact match for Japanese
            if trigger.isascii():
                pattern = re.compile(re.escape(trigger), re.IGNORECASE)
                if pattern.search(text):
                    concrete_found.append(trigger)
                    if category in ("artists", "members"):
                        subjects.append(trigger)
            else:
                if trigger in text:
                    concrete_found.append(trigger)
                    if category in ("artists", "members"):
                        subjects.append(trigger)

    # Scan for abstract triggers
    for trigger in abstract_triggers:
        if trigger in text:
            abstract_found.append(trigger)

    # Deduplicate
    subjects = list(dict.fromkeys(subjects))
    concrete_found = list(dict.fromkeys(concrete_found))
    abstract_found = list(dict.fromkeys(abstract_found))

    # Decision logic
    if concrete_found:
        # Concrete wins if any concrete trigger found
        article_type = "concrete"
        # Confidence based on number and type of matches
        base_conf = 0.7
        if len(concrete_found) >= 3:
            base_conf = 0.95
        elif len(concrete_found) >= 2:
            base_conf = 0.85
        elif subjects:
            base_conf = 0.80
        # Title match is stronger than body-only match
        title_matches = sum(1 for t in concrete_found if t.lower() in title.lower() or t in title)
        if title_matches > 0:
            base_conf = min(1.0, base_conf + 0.1)
        confidence = base_conf
        triggers_found = concrete_found
    elif abstract_found:
        article_type = "abstract"
        base_conf = 0.6
        if len(abstract_found) >= 3:
            base_conf = 0.85
        elif len(abstract_found) >= 2:
            base_conf = 0.75
        confidence = base_conf
        triggers_found = abstract_found
    else:
        # Default to concrete (safer for K-POP site)
        article_type = "concrete"
        confidence = 0.4
        triggers_found = []

    return {
        "type": article_type,
        "subjects": subjects,
        "triggers_found": triggers_found,
        "confidence": confidence,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Article Topic Classifier")
    parser.add_argument("--title", required=True, help="Article title")
    parser.add_argument("--body", default="", help="Article body (optional)")
    args = parser.parse_args()

    result = classify(args.title, args.body)
    print(json.dumps(result, ensure_ascii=False, indent=2))
