"""Các lớp lọc candidate foods sau SQL hard filter.

Module này giữ logic lọc thích nghi theo ingredient, tên món, meal_context và
occasion_context. Các truy vấn DB vẫn nằm ở `repository.py`; file này chỉ xử lý
business rule trên danh sách `Food` đã lấy ra.
"""

from __future__ import annotations

from app.modules.foods.models import Food
from app.modules.search.common import (
    ADAPTIVE_INGREDIENT_INCLUDE_KEYS,
    MIN_CONTEXT_FILTER_CANDIDATES,
    PRIMARY_MEAL_ROLES,
    _food_has_any_ingredient_key,
    _normalize_search_text,
    _phrase_in_text,
    canonicalize_soft_tags,
    has_matching_context,
    matched_canonical_tags,
)
from app.modules.search.ranking import infer_serving_role
from app.modules.search.tracing import append_trace_item, food_trace_snapshot


def apply_adaptive_ingredient_include_filter_with_trace(
    foods: list[Food],
    include_keys: list[str],
    requested_ingredients: list[str],
    require_primary_role: bool,
    trace: dict,
) -> tuple[list[Food], bool, int, str]:
    """
    Thu hẹp candidate theo nguyên liệu user muốn sau các lớp safety filter.

    Đây là hard filter thích nghi, hiện chỉ bật cho key cá đã được resolve rõ
    ràng. Nếu không còn món nào khớp sau lọc sức khỏe, bỏ qua để còn trả món
    thay thế an toàn hơn.
    """
    active_keys = [
        key for key in include_keys or []
        if key in ADAPTIVE_INGREDIENT_INCLUDE_KEYS
    ]
    if not foods or not active_keys:
        return foods, False, 0, "none"

    matched_foods = [
        food for food in foods
        if _food_has_any_ingredient_key(food, active_keys)
    ]
    if not matched_foods:
        print(
            f"🐟 [INGREDIENT INCLUDE FILTER] Bỏ qua lọc ingredient keys {active_keys} "
            "vì không còn món nào khớp sau lớp lọc an toàn."
        )
        return foods, False, 0, "none"

    selected_foods = matched_foods
    scope = "any_role"
    if require_primary_role:
        primary_foods = [
            food for food in matched_foods
            if infer_serving_role(food) in PRIMARY_MEAL_ROLES
        ]
        if primary_foods:
            selected_foods = primary_foods
            scope = "primary_role"

    selected_ids = {food.id for food in selected_foods}
    for food in foods:
        if food.id in selected_ids:
            continue
        append_trace_item(trace, "ingredient_include_filtered_out", {
            **food_trace_snapshot(food),
            "stage": "ingredient_include_filter",
            "reason": "missing_requested_ingredient_key",
            "requested_ingredients": requested_ingredients,
            "required_keys": active_keys,
            "core_ingredient_keys": food.core_ingredient_keys or [],
            "scope": scope,
        })

    scope_label = "món chính" if scope == "primary_role" else "mọi vai trò món"
    print(
        f"🐟 [INGREDIENT INCLUDE FILTER] Giữ {len(selected_foods)}/{len(foods)} món "
        f"khớp ingredient keys user muốn ({scope_label}): {active_keys}"
    )
    return selected_foods, True, len(selected_foods), scope

def food_name_matches_any_dish_base(food: Food, requested_dishes: list[str]) -> bool:
    """Kiểm tra tên món có thuộc nhóm món user yêu cầu, ví dụ bún/cơm/phở."""
    normalized_name = _normalize_search_text(food.name)
    return any(_phrase_in_text(normalized_name, dish) for dish in requested_dishes or [])

def apply_adaptive_dish_name_include_filter_with_trace(
    foods: list[Food],
    requested_dishes: list[str],
    trace: dict,
) -> tuple[list[Food], bool, int]:
    """
    Lọc ưu tiên theo nhóm tên món sau safety filter và trước semantic search.

    Chỉ bỏ qua hard-filter khi không có món nào khớp, để hệ thống còn cơ hội
    trả lựa chọn thay thế thay vì rỗng hoàn toàn.
    """
    normalized_requested = []
    for dish in requested_dishes or []:
        canonical = _normalize_search_text(dish)
        if canonical and canonical not in normalized_requested:
            normalized_requested.append(canonical)
    if not foods or not normalized_requested:
        return foods, False, 0

    matched_foods = [
        food for food in foods
        if food_name_matches_any_dish_base(food, normalized_requested)
    ]
    if matched_foods:
        matched_ids = {food.id for food in matched_foods}
        for food in foods:
            if food.id in matched_ids:
                continue
            append_trace_item(trace, "dish_name_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "dish_name_filter",
                "reason": "missing_requested_dish_base",
                "requested_dishes": requested_dishes,
            })
        print(
            f"🍜 [DISH NAME FILTER] Giữ {len(matched_foods)}/{len(foods)} món "
            f"khớp nhóm món user muốn: {requested_dishes}"
        )
        return matched_foods, True, len(matched_foods)

    print(
        f"🍜 [DISH NAME FILTER] Bỏ qua lọc nhóm món {requested_dishes} "
        "vì không còn món nào khớp sau lớp lọc an toàn."
    )
    return foods, False, len(matched_foods)

def apply_adaptive_context_include_filter_with_trace(
    foods: list[Food],
    target_contexts: list[str],
    field_name: str,
    label: str,
    trace: dict,
) -> list[Food]:
    """
    Lọc include theo context và ghi lại các món bị loại vào trace.

    Quy tắc hiện tại: chỉ cần tồn tại ít nhất một món khớp context yêu cầu
    (ví dụ `Ăn sáng`) thì giữ toàn bộ tập món khớp đó. Không còn cơ chế bỏ qua
    filter chỉ vì số candidate khớp ít hơn một ngưỡng tối thiểu.
    """
    contexts = canonicalize_soft_tags(target_contexts)
    if not contexts:
        return foods

    matched_foods = [
        food for food in foods
        if has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    if matched_foods:
        matched_ids = {food.id for food in matched_foods}
        for food in foods:
            if food.id in matched_ids:
                continue
            append_trace_item(trace, "context_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "context_filter",
                "reason": f"missing_required_{label}",
                "required_contexts": contexts,
                "food_contexts": getattr(food, field_name) or [],
            })
        print(
            f"🧭 [CONTEXT FILTER] Giữ {len(matched_foods)}/{len(foods)} món "
            f"có {label}: {contexts}"
        )
        return matched_foods

    print(
        f"🧭 [CONTEXT FILTER] Bỏ qua lọc {label}: {contexts} "
        "vì không còn món nào khớp sau các lớp lọc trước đó."
    )
    return foods

def apply_adaptive_context_exclude_filter_with_trace(
    foods: list[Food],
    target_contexts: list[str],
    field_name: str,
    label: str,
    trace: dict,
) -> list[Food]:
    """Lọc exclude theo context và ghi nhận các món bị loại để tiện audit/debug."""
    contexts = canonicalize_soft_tags(target_contexts)
    if not contexts:
        return foods

    removed_foods = [
        food for food in foods
        if has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    kept_foods = [
        food for food in foods
        if not has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    if len(kept_foods) >= MIN_CONTEXT_FILTER_CANDIDATES:
        for food in removed_foods:
            append_trace_item(trace, "context_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "context_filter",
                "reason": f"excluded_{label}",
                "matched_contexts": matched_canonical_tags(getattr(food, field_name) or [], contexts),
                "excluded_contexts": contexts,
            })
        print(
            f"🧭 [CONTEXT FILTER] Loại {len(foods) - len(kept_foods)} món "
            f"có {label} không muốn: {contexts}"
        )
        return kept_foods

    print(
        f"🧭 [CONTEXT FILTER] Bỏ qua loại {label}: {contexts} "
        f"vì chỉ còn {len(kept_foods)} món (< {MIN_CONTEXT_FILTER_CANDIDATES})."
    )
    return foods
