"""Scoring và rerank cho danh sách món ứng viên.

Module này suy luận vai trò món, cộng/trừ điểm theo user/medical tags, xử lý
preference conflict và deduplicate top results. Các weight hiện tại được giữ
nguyên để refactor không làm đổi behavior search.
"""

from __future__ import annotations

from app.modules.foods.models import Food
from app.modules.search.common import (
    MAX_MEDICAL_TAG_BONUS,
    MAX_TAG_BONUS,
    MAX_TAG_PENALTY,
    MAX_USER_CONTEXT_BONUS,
    MAX_USER_SOFT_TASTE_BONUS,
    MEAL_ROLE_ADJUSTMENTS,
    MEDICAL_AVOID_TAG_PENALTY,
    MEDICAL_PREFER_TAG_BONUS,
    PREFERENCE_CONFLICT_PAIRS,
    PRIMARY_MEAL_ROLES,
    USER_AVOID_TAG_PENALTY,
    USER_MEAL_CONTEXT_BONUS,
    USER_OCCASION_CONTEXT_BONUS,
    USER_SOFT_TAG_BONUS,
    USER_TASTE_BONUS,
    _has_any_phrase,
    _normalize_search_text,
    _phrase_in_text,
    canonicalize_soft_tags,
    get_food_scoring_tags,
    matched_canonical_tags,
    split_food_category_tags,
    _food_has_any_ingredient_key,
)


def infer_serving_role(food: Food) -> str:
    """
    Suy luận vai trò món trong bữa ăn bằng rule runtime.

    Đây là nhãn dẫn xuất để rerank bữa trưa/tối, không phải dữ liệu cố định
    trong DB. Thứ tự rule có chủ ý: salad cần thắng "Ăn vặt", còn các món
    bún/phở/cơm/trộn đủ no cần thắng tag "Gỏi / Nộm / Trộn".
    """
    name_text = _normalize_search_text(food.name)
    soft_tags = set(food.soft_tags or [])
    occasion_context = set(food.occasion_context or [])

    one_dish_keywords = [
        "mì quảng", "mỳ quảng", "bún", "phở", "miến", "hủ tiếu", "mì", "mỳ",
        "pasta", "spaghetti", "bánh canh", "bánh đa cua", "cao lầu", "cơm",
        "xôi", "cháo", "bánh mì", "sandwich", "pizza", "taco", "kebab",
        "burger", "sushi", "ramen", "udon", "bánh cuốn", "bánh xèo",
        "bánh giò", "bánh chưng", "bánh gói", "bánh ướt", "bánh hỏi",
        "bún đậu", "bún chả", "hoành thánh nước", "lẩu", "poke bowl",
    ]
    dessert_keywords = [
        "chè", "kem", "mousse", "brownie", "lava", "tart", "waffle",
        "crepe sầu riêng", "rau câu", "sữa chua", "bánh flan", "flan",
        "pudding", "trà sữa", "milo dầm", "bingsu", "panna cotta",
        "tiramisu", "cheesecake",
    ]
    snack_keywords = [
        "bánh tráng", "bánh bột lọc", "bánh bèo", "bánh nậm", "bánh ram",
        "ram cuốn", "nem chua", "chả giò", "khoai tây chiên",
        "hoành thánh chiên", "bò bía",
    ]
    side_soup_keywords = ["canh", "súp", "soup"]
    side_vegetable_keywords = [
        "salad", "rau", "đậu bắp", "bông cải", "dưa leo", "gỏi rong biển",
    ]
    main_dish_keywords = [
        "kho", "rim", "nướng", "hấp", "chiên", "xào", "rang", "sốt", "hầm",
        "áp chảo", "bò lúc lắc", "thịt", "cá", "gà", "vịt", "tôm", "mực",
        "ếch", "đậu hũ", "đậu phụ", "trứng", "sườn", "bò", "heo",
    ]

    is_one_dish = _has_any_phrase(name_text, one_dish_keywords)
    if (
        not is_one_dish
        and (
            _has_any_phrase(name_text, dessert_keywords)
            or "Tráng miệng" in occasion_context
            or "Bánh ngọt" in soft_tags
        )
    ):
        return "snack_dessert"

    if _phrase_in_text(name_text, "salad"):
        return "side_vegetable"

    if (
        not is_one_dish
        and (
            "Ăn vặt" in occasion_context
            or _has_any_phrase(name_text, snack_keywords)
        )
    ):
        return "snack_dessert"

    if is_one_dish or ("Ăn no" in occasion_context and "Giàu tinh bột" in soft_tags):
        return "one_dish_meal"

    if _has_any_phrase(name_text, side_soup_keywords) or "Súp" in soft_tags:
        return "side_soup"

    if (
        _has_any_phrase(name_text, side_vegetable_keywords)
        or (
            "Gỏi / Nộm / Trộn" in soft_tags
            and "Ăn no" not in occasion_context
            # Gỏi có nguyên liệu chính (cá, tôm, thịt...) là main_dish, không phải side_vegetable
            and not _has_any_phrase(name_text, main_dish_keywords)
        )
    ):
        return "side_vegetable"

    if "Ăn no" in occasion_context or _has_any_phrase(name_text, main_dish_keywords):
        return "main_dish"

    return "unknown"

def is_main_meal_request(query: str, user_include_tags: list[str]) -> bool:
    """Xác định query có đang hỏi bữa trưa/tối/bữa chính không."""
    query_text = _normalize_search_text(query)
    explicit_main_phrases = [
        "ăn trưa", "bữa trưa", "cơm trưa", "trưa nay ăn",
        "ăn tối", "bữa tối", "cơm tối", "tối nay ăn", "bữa chính",
    ]
    snack_phrases = [
        "ăn vặt", "tráng miệng", "ăn xế", "ăn chiều", "buổi xế",
        "xế chiều", "món nhẹ",
    ]

    explicit_main = _has_any_phrase(query_text, explicit_main_phrases)
    explicit_snack = _has_any_phrase(query_text, snack_phrases)
    canonical_tags = set(canonicalize_soft_tags(user_include_tags))
    tag_main = bool({"Ăn trưa", "Ăn tối"}.intersection(canonical_tags))
    tag_snack = bool({"Ăn vặt", "Tráng miệng", "Ăn chiều / xế"}.intersection(canonical_tags))

    if (explicit_snack or tag_snack) and not explicit_main:
        return False
    return explicit_main or tag_main

def has_explicit_side_or_snack_request(
    query: str,
    user_include_dishes: list[str],
    user_include_tags: list[str],
) -> bool:
    """True khi user gọi đích danh món phụ/snack, để không phạt sai intent."""
    combined_text = _normalize_search_text(
        " ".join([query] + (user_include_dishes or []))
    )
    explicit_phrases = [
        "salad", "canh", "súp", "soup", "rau", "gỏi", "chè", "kem", "bánh",
        "ăn vặt", "tráng miệng",
    ]
    canonical_tags = set(canonicalize_soft_tags(user_include_tags))
    explicit_tags = {
        "Ăn vặt", "Tráng miệng", "Gỏi / Nộm / Trộn", "Súp",
    }
    return _has_any_phrase(combined_text, explicit_phrases) or bool(
        explicit_tags.intersection(canonical_tags)
    )

def get_meal_role_adjustment(
    serving_role: str,
    main_meal_request: bool,
    explicit_side_or_snack_request: bool,
) -> float:
    """Tính điểm cộng/trừ vai trò món ăn cho truy vấn bữa chính."""
    if not main_meal_request:
        return 0.0

    adjustment = MEAL_ROLE_ADJUSTMENTS.get(serving_role, MEAL_ROLE_ADJUSTMENTS["unknown"])
    if explicit_side_or_snack_request and adjustment < 0:
        return 0.0
    return adjustment

def build_explicit_preference_conflict_notes(
    user_include_tags: list[str],
    medical_prefer_tags: list[str],
    top5: list[tuple],
    scored: list[tuple],
) -> tuple[list[str], dict, list[dict]]:
    """
    Minh bạch khi top results không khớp hoàn toàn sở thích rõ ràng của user.

    Đây không phải hard filter, nên hệ thống không loại ngay món trái sở thích;
    thay vào đó ghi note và gắn conflict vào từng món để response giải thích.
    """
    canonical_user_include = set(canonicalize_soft_tags(user_include_tags))
    if not canonical_user_include:
        return [], {}, []

    medical_prefer_set = set(canonicalize_soft_tags(medical_prefer_tags))
    notes: list[str] = []
    conflict_by_food_id: dict = {}
    summaries: list[dict] = []

    for requested_tag, returned_tag in PREFERENCE_CONFLICT_PAIRS:
        if requested_tag not in canonical_user_include:
            continue

        conflicting_top_foods = [
            food for food, *_ in top5
            if returned_tag in set(get_food_scoring_tags(food))
        ]
        if not conflicting_top_foods:
            continue

        requested_candidate_count = sum(
            1 for food, *_ in scored
            if requested_tag in set(get_food_scoring_tags(food))
        )
        requested_top_count = sum(
            1 for food, *_ in top5
            if requested_tag in set(get_food_scoring_tags(food))
        )
        conflict_names = ", ".join(food.name for food in conflicting_top_foods[:3])
        medical_signal_text = (
            f" Rule sức khỏe hiện tại cũng ưu tiên {returned_tag}."
            if returned_tag in medical_prefer_set
            else ""
        )

        if requested_candidate_count == 0:
            note = (
                f"Không tìm thấy món có tag {requested_tag} đủ điều kiện sau khi lọc sức khỏe "
                f"và ngữ cảnh, nên hệ thống đề xuất thêm món có tag {returned_tag} "
                f"({conflict_names}) như lựa chọn thay thế."
                f"{medical_signal_text}"
            )
        else:
            note = (
                f"Hệ thống đã nhận yêu cầu {requested_tag} và có {requested_candidate_count} "
                f"ứng viên phù hợp ({requested_top_count} món vào top 5), nhưng vẫn giữ một số "
                f"món có tag {returned_tag} ({conflict_names}) vì sau khi lọc sức khỏe/ngữ cảnh "
                "chúng có điểm phù hợp cao hơn."
                f"{medical_signal_text}"
            )

        notes.append(note)
        summaries.append({
            "requested_tag": requested_tag,
            "returned_conflict_tag": returned_tag,
            "requested_candidate_count": requested_candidate_count,
            "requested_top_count": requested_top_count,
            "conflicting_foods": [food.name for food in conflicting_top_foods],
            "medical_prefer_conflict_tag": returned_tag in medical_prefer_set,
            "note": note,
        })
        for food in conflicting_top_foods:
            conflict_by_food_id.setdefault(food.id, []).append({
                "requested_tag": requested_tag,
                "returned_conflict_tag": returned_tag,
                "note": note,
            })

    return notes, conflict_by_food_id, summaries

def collect_ingredient_priority_food_ids(
    foods: list[Food],
    include_keys: list[str],
    main_meal_request: bool = False,
    require_primary_role: bool = False,
) -> set:
    """
    Đánh dấu món khớp nguyên liệu user muốn.

    Nguyên liệu include không nên làm rớt sạch candidate an toàn. Thay vào đó,
    món khớp nguyên liệu sẽ được xếp trong nhóm ưu tiên khi lấy top kết quả.
    """
    if not include_keys:
        return set()

    matched_foods = []
    for food in foods:
        if not _food_has_any_ingredient_key(food, include_keys):
            continue
        if require_primary_role and infer_serving_role(food) not in PRIMARY_MEAL_ROLES:
            continue
        matched_foods.append(food)

    primary_note = " trong vai trò món chính" if require_primary_role else ""
    print(
        f"🧭 [INGREDIENT PRIORITY] Có {len(matched_foods)}/{len(foods)} món "
        f"khớp ingredient keys user muốn{primary_note}: {include_keys}"
    )
    return {food.id for food in matched_foods}

def calculate_tag_adjusted_similarity(
    food: Food,
    base_similarity: float,
    user_prefer_tags: list[str],
    medical_prefer_tags: list[str],
    user_avoid_tags: list[str],
    medical_avoid_tags: list[str],
) -> tuple[float, dict]:
    """
    Rerank mềm (tính điểm lại) bằng tag/category:
    - Tag hợp nhu cầu/y khoa: cộng điểm nhẹ.
    - Tag nên tránh: trừ điểm, không loại món ngay.
    Hard filter (lọc cứng) vẫn dành cho nguyên liệu/món bị cấm rõ ràng ở bước trước.
    """
    food_tags = get_food_scoring_tags(food)
    
    # Tìm các tag trùng khớp
    matched_user_prefer = matched_canonical_tags(food_tags, user_prefer_tags)
    matched_medical_prefer = matched_canonical_tags(food_tags, medical_prefer_tags)
    matched_user_avoid = matched_canonical_tags(food_tags, user_avoid_tags)
    matched_medical_avoid = matched_canonical_tags(food_tags, medical_avoid_tags)

    # Tính toán điểm cộng
    grouped_user_prefer = split_food_category_tags(matched_user_prefer)
    user_soft_taste_bonus_raw = (
        len(grouped_user_prefer["soft_tags"]) * USER_SOFT_TAG_BONUS +
        len(grouped_user_prefer["taste_profile"]) * USER_TASTE_BONUS
    )
    user_context_bonus_raw = (
        len(grouped_user_prefer["meal_context"]) * USER_MEAL_CONTEXT_BONUS +
        len(grouped_user_prefer["occasion_context"]) * USER_OCCASION_CONTEXT_BONUS
    )
    medical_prefer_bonus_raw = len(matched_medical_prefer) * MEDICAL_PREFER_TAG_BONUS

    # Giới hạn điểm cộng tối đa (Caps)
    user_soft_taste_bonus = min(MAX_USER_SOFT_TASTE_BONUS, user_soft_taste_bonus_raw)
    user_context_bonus = min(MAX_USER_CONTEXT_BONUS, user_context_bonus_raw)
    medical_prefer_bonus = min(MAX_MEDICAL_TAG_BONUS, medical_prefer_bonus_raw)

    tag_bonus = min(
        MAX_TAG_BONUS,
        user_soft_taste_bonus + user_context_bonus + medical_prefer_bonus,
    )
    
    # Tính toán điểm trừ (Caps)
    tag_penalty = min(
        MAX_TAG_PENALTY,
        len(matched_user_avoid) * USER_AVOID_TAG_PENALTY +
        len(matched_medical_avoid) * MEDICAL_AVOID_TAG_PENALTY,
    )
    
    # Tính điểm Similarity sau khi điều chỉnh
    adjusted_similarity = max(0.0, min(1.0, base_similarity + tag_bonus - tag_penalty))

    return adjusted_similarity, {
        "base_similarity": base_similarity,
        "tag_bonus": tag_bonus,
        "user_soft_taste_bonus": user_soft_taste_bonus,
        "user_context_bonus": user_context_bonus,
        "medical_prefer_bonus": medical_prefer_bonus,
        "tag_penalty": tag_penalty,
        "matched_prefer_tags": matched_user_prefer + matched_medical_prefer,
        "matched_user_prefer_tags": matched_user_prefer,
        "matched_medical_prefer_tags": matched_medical_prefer,
        "matched_avoid_tags": matched_user_avoid + matched_medical_avoid,
    }

def _deduplicate_results(scored_list: list, top_k: int) -> list:
    """
    Loại trùng lặp trong danh sách đã xếp hạng trước khi cắt top_k.

    Chiến lược:
    - Chuẩn hóa tên món: lowercase, bỏ khoảng trắng thừa, cắt bỏ phần trong ngoặc "(...)".
    - Giới hạn tối đa 2 biến thể cùng base name (ví dụ: "Mì Quảng chay" và
      "Mì Quảng trộn chay" đều pass, nhưng thêm "Mì Quảng Chay" thứ 3 thì bị bỏ).
    - Dừng khi đủ top_k món unique.

    Lý do giới hạn 2 thay vì 1: cho phép 1 biến thể nước + 1 biến thể khô của
    cùng món (ví dụ: Mì Quảng thường + Mì Quảng trộn) để tăng tính đa dạng
    mà không bị trùng lặp hoàn toàn.
    """
    seen: dict[str, int] = {}
    unique = []
    for item in scored_list:
        food = item[0]
        name_key = food.name.strip().lower()
        # Lấy base name: bỏ phần "(..." ở cuối (vd: "Mì Quảng (chay)" → "mì quảng")
        base = name_key.split("(")[0].strip()
        count = seen.get(base, 0)
        if count < 2:
            seen[base] = count + 1
            unique.append(item)
        if len(unique) >= top_k:
            break
    return unique

