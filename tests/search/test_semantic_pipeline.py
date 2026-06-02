from types import SimpleNamespace


def make_food(**overrides):
    base = {
        "id": "food-1",
        "name": "Pho bo",
        "description": "A beef noodle soup",
        "img_url": None,
        "core_ingredients": ["thit bo", "banh pho"],
        "raw_ingredients": ["thit bo 200g", "banh pho 300g"],
        "raw_instructions": "Cook and serve.",
        "core_ingredient_keys": ["canon:thit_bo", "group:thit_bo"],
        "soft_tags": ["Mon nuoc"],
        "taste_profile": ["Thanh dam"],
        "meal_context": ["An trua"],
        "occasion_context": ["An no"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_critical_safety_rejects_only_medical_ingredient_keys():
    from app.modules.search.pipeline.safety import (
        CriticalSafetyRules,
        evaluate_critical_safety,
    )

    food = make_food(core_ingredient_keys=["canon:tom", "group:hai_san"])
    rules = CriticalSafetyRules(
        health_constraints=["Gout"],
        excluded_ingredient_keys=["group:hai_san"],
        critical_exclude_tags=[],
        allergy_constraints=[],
        allergy_exclude_ingredients=[],
    )

    decision = evaluate_critical_safety(food, rules)

    assert decision.reject is True
    assert decision.reason == "critical_ingredient_key_overlap"
    assert decision.matched_values == ["group:hai_san"]


def test_user_dislikes_are_penalties_not_safety_rejections():
    from app.modules.search.pipeline.safety import (
        CriticalSafetyRules,
        evaluate_critical_safety,
    )
    from app.modules.search.pipeline.scoring import ExtractedIntent, score_candidate
    from app.modules.search.pipeline.types import RetrievedFood

    food = make_food(core_ingredient_keys=["canon:hanh_tay"])
    rules = CriticalSafetyRules(
        health_constraints=[],
        excluded_ingredient_keys=[],
        critical_exclude_tags=[],
        allergy_constraints=[],
        allergy_exclude_ingredients=[],
    )
    intent = ExtractedIntent(
        disliked_ingredient_keys=["canon:hanh_tay"],
    )

    decision = evaluate_critical_safety(food, rules)
    scored = score_candidate(RetrievedFood(food=food, semantic_score=0.82), intent)

    assert decision.reject is False
    assert scored.final_score < 0.82
    assert "disliked_ingredient_penalty" in scored.reason_signals


def test_context_match_boosts_score_without_deleting_candidate():
    from app.modules.search.pipeline.scoring import ExtractedIntent, score_candidate
    from app.modules.search.pipeline.types import RetrievedFood

    food = make_food(meal_context=["An toi"], occasion_context=["An no"])
    intent = ExtractedIntent(meal_context=["An toi"], occasion_context=["An no"])

    scored = score_candidate(RetrievedFood(food=food, semantic_score=0.70), intent)

    assert scored.final_score > 0.70
    assert "meal_context_match" in scored.reason_signals
    assert "occasion_context_match" in scored.reason_signals


def test_ranked_results_are_sorted_by_final_score():
    from app.modules.search.pipeline.scoring import ExtractedIntent, rank_candidates
    from app.modules.search.pipeline.types import RetrievedFood

    weak_context_match = make_food(id="food-low", meal_context=["An toi"])
    strong_semantic = make_food(id="food-high", meal_context=[])

    ranked = rank_candidates(
        [
            RetrievedFood(food=weak_context_match, semantic_score=0.65),
            RetrievedFood(food=strong_semantic, semantic_score=0.83),
        ],
        ExtractedIntent(meal_context=["An toi"]),
        limit=2,
    )

    assert [item.food.id for item in ranked] == ["food-high", "food-low"]


def test_explanation_prompt_forbids_result_mutation():
    from app.modules.search.pipeline.explanation import build_generation_guardrails

    guardrails = build_generation_guardrails()

    assert "Do not add foods" in guardrails
    assert "Do not remove foods" in guardrails
    assert "Do not reorder foods" in guardrails
