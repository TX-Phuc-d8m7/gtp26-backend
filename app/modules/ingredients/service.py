"""Shared ingredient key generation for seed, search, and admin workflows.

This module keeps the reviewed baseline alias rules usable by backend code and
adds a DB override layer for admin-managed aliases.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.generate_ingredient_key_preview import (
    ALIAS_RULES,
    alias_matches,
    dedupe_keep_order,
    make_rule,
    normalize_base_key,
)

FAMILY_FILTER_GROUP_KEYS = {
    "group:thit_bo",
    "group:thit_heo",
    "group:thit_ga",
    "group:thit_vit",
}


def normalize_alias_key(alias: str) -> str:
    """Create the stored machine key for an admin alias."""
    return normalize_base_key(alias)


def override_to_rule(override) -> dict | None:
    """Convert an enabled IngredientAliasOverride row/object into an alias rule."""
    if not getattr(override, "enabled", False):
        return None

    alias = (getattr(override, "alias", "") or "").strip()
    canonical_key = (getattr(override, "canonical_key", "") or "").strip()
    if not alias or not canonical_key:
        return None

    return make_rule(
        canonical_key=canonical_key,
        aliases=[alias],
        group_keys=list(getattr(override, "group_keys", []) or []),
        notes=getattr(override, "notes", "") or "",
    )


def build_override_rules(overrides: Sequence) -> list[dict]:
    """Build alias rules from enabled DB override rows."""
    rules: list[dict] = []
    for override in overrides or []:
        rule = override_to_rule(override)
        if rule:
            rules.append(rule)
    return rules


async def load_enabled_alias_override_rules(db: AsyncSession) -> list[dict]:
    """Load enabled admin alias overrides from the database as alias rules."""
    from app.models import IngredientAliasOverride

    result = await db.execute(
        select(IngredientAliasOverride).where(IngredientAliasOverride.enabled.is_(True))
    )
    return build_override_rules(result.scalars().all())


def all_alias_rules(extra_rules: Sequence[dict] | None = None) -> list[dict]:
    """Return baseline rules plus optional admin override rules."""
    return list(ALIAS_RULES) + list(extra_rules or [])


def generate_ingredient_keys_with_rules(
    ingredient: str,
    *,
    extra_rules: Sequence[dict] | None = None,
) -> tuple[list[str], list[str]]:
    """Generate base/canon/group keys for one ingredient using baseline + overrides."""
    base_key = normalize_base_key(ingredient)
    keys = [f"base:{base_key}"] if base_key else []
    matched_rules: list[str] = []

    for rule in all_alias_rules(extra_rules):
        if alias_matches(ingredient, base_key, rule):
            keys.append(rule["canonical_key"])
            keys.extend(rule.get("group_keys", []) or [])
            matched_rules.append(rule["canonical_key"])

    return dedupe_keep_order(keys), dedupe_keep_order(matched_rules)

def _rule_with_single_alias(rule: dict, alias: str) -> dict:
    return {
        **rule,
        "aliases": [alias],
        "alias_keys": [normalize_base_key(alias)],
    }


def _matched_filter_candidates(
    ingredient: str,
    *,
    extra_rules: Sequence[dict] | None = None,
) -> list[dict]:
    """
    Return canonical matches with alias specificity for filter generation.

    Food identity may keep broad + specific keys, but filters should prefer the
    most specific alias. Example: "mam tom" should filter by canon:mam_tom,
    not by canon:tom, unless another rule explicitly asks for "tom".
    """
    base_key = normalize_base_key(ingredient)
    matches: list[dict] = []

    for rule in all_alias_rules(extra_rules):
        for alias in rule.get("aliases", []) or []:
            single_alias_rule = _rule_with_single_alias(rule, alias)
            if not alias_matches(ingredient, base_key, single_alias_rule):
                continue
            alias_key = normalize_base_key(alias)
            matches.append({
                "canonical_key": rule["canonical_key"],
                "group_keys": list(rule.get("group_keys", []) or []),
                "specificity": len(alias_key.split("_")) if alias_key else 0,
            })

    return matches


def generate_core_ingredient_keys(
    core_ingredients: Iterable[str],
    *,
    extra_rules: Sequence[dict] | None = None,
) -> list[str]:
    """Generate de-duplicated keys for a food's core ingredients."""
    all_keys: list[str] = []
    for ingredient in core_ingredients or []:
        ingredient_keys, _ = generate_ingredient_keys_with_rules(
            ingredient,
            extra_rules=extra_rules,
        )
        all_keys.extend(ingredient_keys)
    return dedupe_keep_order(all_keys)


def generate_filter_keys(
    ingredients: Iterable[str],
    *,
    extra_rules: Sequence[dict] | None = None,
    include_groups: bool = False,
) -> list[str]:
    """
    Convert user/rule ingredients to keys for filtering.

    Prefer canonical keys over broad group keys to avoid over-filtering. If an
    ingredient has no canon match, keep its base key as a safe exact fallback.
    """
    filter_keys: list[str] = []
    for ingredient in ingredients or []:
        matches = _matched_filter_candidates(
            ingredient,
            extra_rules=extra_rules,
        )
        if matches:
            max_specificity = max(match["specificity"] for match in matches)
            specific_matches = [
                match for match in matches
                if match["specificity"] == max_specificity
            ]
            canonical_keys = [match["canonical_key"] for match in specific_matches]
            group_keys = [
                group_key
                for match in specific_matches
                for group_key in match["group_keys"]
            ]
            safe_group_keys = [key for key in group_keys if key in FAMILY_FILTER_GROUP_KEYS]

            filter_keys.extend(canonical_keys)
            if include_groups:
                filter_keys.extend(group_keys)
            else:
                filter_keys.extend(safe_group_keys)
        else:
            base_key = normalize_base_key(ingredient)
            if base_key:
                filter_keys.append(f"base:{base_key}")

    return dedupe_keep_order(filter_keys)


def has_any_ingredient_key(food_keys: Iterable[str], target_keys: Iterable[str]) -> bool:
    """Check if a food key list overlaps with target filter keys."""
    return bool(set(food_keys or []).intersection(set(target_keys or [])))
