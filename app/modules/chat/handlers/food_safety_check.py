from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.handlers.common import (
    IntentHandlerResult,
    build_structured_result,
    resolve_food_candidate,
)
from app.modules.foods.models import Tag
from app.modules.search.safety import detect_allergy_text_matches
from app.modules.search.service import (
    MEDICAL_ADVICE_ALIAS_MAP,
    MEDICAL_ADVICE_RULES,
    canonicalize_health_tag,
    canonicalize_soft_tags,
    get_food_scoring_tags,
    matched_canonical_tags,
)
from app.modules.users.models import UserHealthProfile


def _food_has_excluded_ingredient(food, excluded_ingredients: list[str]) -> bool:
    ingredients_text = " ".join(food.core_ingredients or []).lower()
    return any(ingredient.lower() in ingredients_text for ingredient in excluded_ingredients or [])


def _collect_rule_warnings(food, health_tags: list[str]) -> list[str]:
    food_tags = set(get_food_scoring_tags(food))
    food_ingredients = set(food.core_ingredients or [])
    warnings: list[str] = []
    for symptom in health_tags:
        rule = MEDICAL_ADVICE_RULES.get(symptom) or MEDICAL_ADVICE_RULES.get(
            MEDICAL_ADVICE_ALIAS_MAP.get(symptom, "")
        )
        if not rule:
            continue
        for cond in rule.get("conditional_warnings", []):
            trigger_type = cond.get("trigger_type")
            trigger_value = cond.get("trigger_value")
            if trigger_type == "soft_tag" and trigger_value in food_tags:
                warnings.append(cond["warning_text"])
            elif trigger_type == "ingredient" and trigger_value in food_ingredients:
                warnings.append(cond["warning_text"])
    deduped: list[str] = []
    for warning in warnings:
        if warning not in deduped:
            deduped.append(warning)
    return deduped


async def handle_food_safety_check(
    *,
    raw_query: str,
    db: AsyncSession,
    profile: UserHealthProfile | None,
    last_food_results: list[dict] | None,
    food_name: str | None,
    target_reference: str | None,
    health_topic: str | None = None,
) -> IntentHandlerResult:
    food, referenced_item, resolved_name = await resolve_food_candidate(
        db,
        food_name=food_name,
        target_reference=target_reference,
        last_food_results=last_food_results,
    )

    if food is None:
        unresolved_name = resolved_name or food_name or "món này"
        content = (
            f"Mình chưa có dữ liệu chuẩn cho {unresolved_name} trong thư viện món ăn, nên chưa thể kết luận món này "
            "an toàn hay không an toàn cho hồ sơ của bạn. Nếu bạn gửi rõ thành phần, tên quán, menu hoặc chọn một món "
            "đã có trong danh sách hệ thống, mình sẽ kiểm tra sát hơn."
        )
        return IntentHandlerResult(
            intent="food_safety_check",
            content=content,
            structured_result=build_structured_result(
                "food_safety_check",
                {
                    "status": "unverified",
                    "food_name": unresolved_name,
                    "recommendation": "unknown",
                    "requires_more_info": True,
                },
            ),
        )

    profile_health_tags = []
    if profile is not None:
        profile_health_tags.extend(profile.health_conditions or [])
        profile_health_tags.extend(profile.allergies or [])
    if health_topic:
        profile_health_tags.append(health_topic)
    health_tags = list(dict.fromkeys(canonicalize_health_tag(tag) for tag in profile_health_tags if tag))

    if not health_tags:
        content = (
            f"Mình chưa thấy hồ sơ bệnh lý hoặc dị ứng nào để đối chiếu riêng cho {food.name}. "
            "Về phía dữ liệu món, mình chưa thấy cờ cảnh báo đặc biệt, nhưng bạn vẫn nên kiểm tra thành phần thực tế "
            "và nguy cơ dùng chung dụng cụ nếu quán chế biến nhiều loại thực phẩm."
        )
        return IntentHandlerResult(
            intent="food_safety_check",
            content=content,
            structured_result=build_structured_result(
                "food_safety_check",
                {
                    "status": "resolved",
                    "food_id": str(food.id),
                    "food_name": food.name,
                    "recommendation": "prefer",
                    "reasons": ["Chưa có hồ sơ sức khỏe cần cảnh báo riêng."],
                    "cross_contamination_warning": None,
                    "requires_more_info": False,
                },
            ),
        )

    tag_rows = (await db.execute(select(Tag).where(Tag.name.in_(health_tags)))).scalars().all()
    allergy_constraints: list[str] = []
    allergy_exclude_ings: list[str] = []
    medical_exclude_tags: list[str] = []
    medical_prefer_tags: list[str] = []
    medical_exclude_ings: list[str] = []

    for tag in tag_rows:
        if tag.tag_type == "ALLERGY":
            allergy_constraints.append(tag.name)
            allergy_exclude_ings.extend(tag.exclude_ingredient or [])
        else:
            medical_exclude_tags.extend(canonicalize_soft_tags(tag.exclude_soft_tag or []))
        medical_prefer_tags.extend(canonicalize_soft_tags(tag.prefer_soft_tag or []))
        medical_exclude_ings.extend(tag.exclude_ingredient or [])

    allergy_matches = detect_allergy_text_matches(food, allergy_constraints, allergy_exclude_ings)
    matched_medical_avoid_tags = matched_canonical_tags(
        get_food_scoring_tags(food),
        medical_exclude_tags,
    )
    has_medical_excluded_ingredient = _food_has_excluded_ingredient(food, medical_exclude_ings)
    matched_medical_prefer_tags = matched_canonical_tags(
        get_food_scoring_tags(food),
        medical_prefer_tags,
    )
    warnings = _collect_rule_warnings(food, health_tags)

    recommendation = "prefer"
    reasons: list[str] = []
    if allergy_matches:
        recommendation = "avoid"
        reasons.append(
            f"Món có tín hiệu trùng với nhóm dị ứng của bạn: {', '.join(match['phrase'] for match in allergy_matches[:3])}."
        )
    elif matched_medical_avoid_tags or has_medical_excluded_ingredient or warnings:
        recommendation = "caution"
        if matched_medical_avoid_tags:
            reasons.append(f"Món có đặc điểm cần lưu ý: {', '.join(matched_medical_avoid_tags[:3])}.")
        if has_medical_excluded_ingredient:
            reasons.append("Món có thành phần nằm trong nhóm nguyên liệu nên hạn chế theo hồ sơ sức khỏe.")
    elif matched_medical_prefer_tags:
        reasons.append(f"Món đang khớp các tín hiệu tương đối tốt như {', '.join(matched_medical_prefer_tags[:3])}.")
    else:
        reasons.append("Mình chưa thấy tín hiệu cảnh báo trực tiếp nào từ rules hiện có.")

    cross_warning = warnings[0] if warnings else None
    if recommendation == "avoid":
        content = (
            f"Với hồ sơ hiện tại của bạn, {food.name} không phải lựa chọn an toàn để ưu tiên. "
            f"{reasons[0]}{f' Ngoài ra còn có lưu ý: {cross_warning}' if cross_warning else ''}"
        )
    elif recommendation == "caution":
        content = (
            f"{food.name} vẫn có thể cân nhắc, nhưng không phải lựa chọn tối ưu nếu bạn muốn ăn thật an toàn. "
            f"{' '.join(reasons[:2])}{f' Bạn cũng nên lưu ý thêm: {cross_warning}' if cross_warning else ''}"
        )
    else:
        content = (
            f"Trong dữ liệu hiện có, {food.name} là lựa chọn mình nghiêng về hướng nên ưu tiên hơn cho hồ sơ của bạn. "
            f"{reasons[0]}{f' Dù vậy vẫn nên hỏi quán thêm về nền nước dùng hoặc cách chế biến thực tế.' if cross_warning else ''}"
        )

    return IntentHandlerResult(
        intent="food_safety_check",
        content=content,
        structured_result=build_structured_result(
            "food_safety_check",
            {
                "status": "resolved",
                "food_id": str(food.id),
                "food_name": food.name,
                "referenced_food_name": referenced_item.get("name") if referenced_item else None,
                "recommendation": recommendation,
                "reasons": reasons,
                "cross_contamination_warning": cross_warning,
                "requires_more_info": False,
            },
        ),
    )

