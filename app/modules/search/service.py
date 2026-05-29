"""Search service orchestration và facade tương thích.

`search_food()` là public entrypoint cho router, chat handlers và scripts. File
này điều phối intent, safety, repository, filtering, retrieval, ranking,
explanation và tracing, đồng thời re-export một số symbol cũ để giảm rủi ro vỡ
import sau refactor.
"""

from __future__ import annotations

import json
import time
import uuid

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingredients.service import generate_filter_keys, load_enabled_alias_override_rules
from app.modules.query_logs.service import create_query_log
from app.modules.search.common import (
    EMBEDDING_FALLBACK_RETRIEVAL_NOTE,
    MAX_MEDICAL_CAUTION_INGREDIENT_KEY_PENALTY,
    MEAL_ROLE_ADJUSTMENTS,
    MEDICAL_ADVICE_ALIAS_MAP,
    MEDICAL_CAUTION_INGREDIENT_KEY_PENALTY,
    PREFERENCE_CONFLICT_PAIRS,
    SEARCH_CANDIDATE_LOG_LIMIT,
    SEARCH_DISCLAIMER,
    SEARCH_SCORE_LOG_LIMIT,
    SEARCH_VERBOSE_LOGS,
    SQL_HARD_FILTER_TRACE_LIMIT,
    SUPERVISOR_FALLBACK_WARNING,
    TRACE_LIMIT,
    _food_has_any_ingredient_key,
    canonicalize_health_tag,
    canonicalize_soft_tags,
    client,
    get_food_scoring_tags,
    get_gemini_text_model,
    matched_canonical_tags,
    split_food_category_tags,
    valid_health_tags,
)
from app.modules.search.explanation import (
    MEDICAL_ADVICE_RULES,
    _build_no_result_ai_response,
    _build_no_result_retrieval_note,
    build_food_reason,
    run_post_processing_with_timeout,
)
from app.modules.search.validation import run_final_validation_with_timeout
from app.modules.search.filtering import (
    apply_adaptive_context_exclude_filter_with_trace,
    apply_adaptive_context_include_filter_with_trace,
    apply_adaptive_dish_name_include_filter_with_trace,
    apply_adaptive_ingredient_include_filter_with_trace,
)
from app.modules.search.ranking import (
    build_explicit_preference_conflict_notes,
    calculate_tag_adjusted_similarity,
    collect_ingredient_priority_food_ids,
    get_meal_role_adjustment,
    has_explicit_side_or_snack_request,
    infer_serving_role,
    is_main_meal_request,
    _deduplicate_results,
)
from app.modules.search.repository import (
    list_candidate_foods,
    list_foods_matching_name,
    list_foods_with_ingredient_key_overlap,
)
from app.modules.search.retrieval import (
    build_fallback_query_signals,
    calculate_lexical_fallback_score,
    run_embedding_with_timeout,
)
from app.modules.search.safety import (
    apply_medical_soft_tag_hard_filter_with_trace,
    detect_allergy_text_matches,
    resolve_food_conflicts,
)
from app.modules.search.schemas import AIInsight, FoodResult, SearchResponse
from app.modules.search.tracing import (
    _new_llm_runtime_state,
    append_trace_item,
    build_returned_trace_item,
    build_score_trace_item,
    collect_medical_caution_ingredient_key_matches,
    food_trace_snapshot,
    init_retrieval_trace,
    log_retrieval_trace_for_debug,
    matched_keys,
)
from app.modules.users.models import UserHealthProfile


async def _noop_validation(
    foods: list,
) -> tuple[list, list, dict]:
    """Placeholder trả về khi validation bị bỏ qua (không có symptoms)."""
    return foods, [], {"status": "skipped", "latency_ms": 0, "error_message": None}


async def search_food(
    query: str,
    db: AsyncSession,
    profile: UserHealthProfile | None = None,
    thread_id: uuid.UUID | None = None,
    top_k: int = 5,
    debug: bool = False,
) -> SearchResponse:
    """
    Luồng chạy chính để tìm kiếm món ăn:
    1. Trích xuất ý định (Supervisor Agent).
    2. Build Enriched Query.
    3. Lọc Database (SQL) bằng nguyên liệu cấm.
    4. Rerank kết quả bằng Vector Similarity + Tag Scoring.
    5. Post-Processing tạo phản hồi tư vấn tự nhiên.
    """
    _t_search_start = time.perf_counter()
    llm_runtime = _new_llm_runtime_state()
    retrieval_trace = init_retrieval_trace()

    # --- Bước 1: Chạy luồng bảo vệ và xử lý xung đột ---
    payload = await resolve_food_conflicts(query, db, profile=profile)
    if payload and payload.get("llm_runtime"):
        payload_runtime = payload["llm_runtime"]
        llm_runtime["supervisor_status"] = payload_runtime.get("supervisor_status", "ok")
        llm_runtime["stage_latency_ms"].update(payload_runtime.get("stage_latency_ms", {}))
        if payload_runtime.get("supervisor_error"):
            llm_runtime["supervisor_error"] = payload_runtime["supervisor_error"]
        if payload_runtime.get("fallback_extracted_constraints"):
            llm_runtime["fallback_extracted_constraints"] = payload_runtime["fallback_extracted_constraints"]
        if llm_runtime["supervisor_status"] == "fallback":
            llm_runtime["fallbacks_used"].append("supervisor")
            llm_runtime["user_visible_warning_applied"] = True

    if payload:
        print("\n" + "="*50)
        print("🎯 KẾT QUẢ TỪ AGENT & XỬ LÝ XUNG ĐỘT:")
        print(json.dumps(payload, ensure_ascii=False, indent=4))
        print("="*50 + "\n")
    else:
        print("❌ Payload trả về rỗng (Có lỗi từ LLM)")
    
    # Xử lý fallback nếu LLM báo lỗi
    if not payload:
        return SearchResponse(
            query=query,
            ai_insight=AIInsight(exclude=[], include=[], prefer=[]),
            results=[],
            disclaimer=SEARCH_DISCLAIMER,
        )
    
    # Bóc tách biến từ Payload
    user_exclude_dishes = payload["user_exclude_dishes"]
    symptoms = payload["symptoms"]
    final_e_ings = payload["final_exclude_ings"]
    final_p_ings = payload["final_include_ings"]
    allergy_constraints = payload.get("allergy_constraints", [])
    allergy_e_ings = payload.get("allergy_exclude_ings", [])
    allergy_e_tags = payload.get("allergy_exclude_tags", [])
    disease_e_ings = payload.get("disease_exclude_ings", [])
    medical_e_tags = payload["medical_exclude_tags"]
    medical_p_tags = payload["medical_prefer_tags"]
    medical_p_ings = payload.get("medical_prefer_ings", [])
    safety_e_tags = list(dict.fromkeys(medical_e_tags + allergy_e_tags))

    user_include_tags = payload["user_include_tags"]
    user_exclude_tags = payload["user_exclude_tags"]
    user_include_dishes = payload["user_include_dishes"]
    warning_message = payload["warning_message"]
    
    grouped_user_include_tags = split_food_category_tags(user_include_tags)
    grouped_user_exclude_tags = split_food_category_tags(user_exclude_tags)
    alias_override_rules = await load_enabled_alias_override_rules(db)
    exclude_ingredient_keys = generate_filter_keys(
        final_e_ings,
        extra_rules=alias_override_rules,
    )
    allergy_exclude_ingredient_keys = generate_filter_keys(
        allergy_e_ings,
        extra_rules=alias_override_rules,
    )
    disease_exclude_ingredient_keys = generate_filter_keys(
        disease_e_ings,
        extra_rules=alias_override_rules,
    )
    include_ingredient_keys = generate_filter_keys(
        final_p_ings,
        extra_rules=alias_override_rules,
    )
    retrieval_notes: list[str] = []
    main_meal_request = is_main_meal_request(query, user_include_tags)
    explicit_side_or_snack_request = has_explicit_side_or_snack_request(
        query=query,
        user_include_dishes=user_include_dishes,
        user_include_tags=user_include_tags,
    )
    primary_ingredient_priority_only = (
        main_meal_request and not explicit_side_or_snack_request
    )
    if main_meal_request:
        mode_label = (
            "có yêu cầu món phụ/snack rõ ràng"
            if explicit_side_or_snack_request
            else "ưu tiên món chính/đủ no"
        )
        print(f"🍽️ [MEAL ROLE] Bật rerank bữa chính ({mode_label}).")

    # --- Bước 2: Xây dựng Enriched Query ---
    # Đồng bộ cấu trúc query embedding với text_to_embed của món ăn trong seed_service.py.
    # Tên bệnh vẫn dùng cho rule/warning; query embedding ưu tiên các tiêu chí món ăn.
    enriched_parts = [f"Mô tả: {query}"]

    if user_include_dishes:
        enriched_parts.append(f"Món ăn: {', '.join(user_include_dishes)}")

    # Bổ sung nguyên liệu ưa thích (gộp user + y khoa)
    all_prefer_ings = list(set(final_p_ings + medical_p_ings))
    if all_prefer_ings:
        enriched_parts.append(f"Nguyên liệu chính: {', '.join(all_prefer_ings)}")

    # Bổ sung tag ưu tiên theo đúng các nhóm category đã tách
    combined_prefer_tags = list(set(user_include_tags + medical_p_tags))
    grouped_prefer_tags = split_food_category_tags(combined_prefer_tags)

    if grouped_prefer_tags["soft_tags"]:
        enriched_parts.append(f"Tính chất: {', '.join(grouped_prefer_tags['soft_tags'])}")

    if grouped_prefer_tags["taste_profile"]:
        enriched_parts.append(f"Hồ sơ vị: {', '.join(grouped_prefer_tags['taste_profile'])}")

    if grouped_prefer_tags["meal_context"]:
        enriched_parts.append(f"Bữa ăn phù hợp: {', '.join(grouped_prefer_tags['meal_context'])}")

    if grouped_prefer_tags["occasion_context"]:
        enriched_parts.append(f"Ngữ cảnh sử dụng: {', '.join(grouped_prefer_tags['occasion_context'])}")

    expanded_query = ". ".join(enriched_parts)
    print(f"🔎 ENRICHED QUERY: {expanded_query}")

    # --- Nhúng Vector (Embedding) ---
    query_vector, embedding_runtime = await run_embedding_with_timeout(expanded_query)
    llm_runtime["embedding_status"] = embedding_runtime.get("status", "ok")
    llm_runtime["stage_latency_ms"]["embedding"] = embedding_runtime.get("latency_ms", 0)
    if embedding_runtime.get("error_message"):
        llm_runtime["embedding_error"] = embedding_runtime["error_message"]
    retrieval_mode = "semantic" if query_vector is not None else "lexical_fallback"
    llm_runtime["retrieval_mode"] = retrieval_mode
    if retrieval_mode == "lexical_fallback":
        llm_runtime["fallbacks_used"].append("embedding")
        llm_runtime["user_visible_retrieval_note_applied"] = True
        retrieval_notes.append(EMBEDDING_FALLBACK_RETRIEVAL_NOTE)

    # --- Bước 3: Bộ lọc CSDL (SQL Filter) ---
    # Lọc tập món ăn hợp lệ (loại exclude_ingredients + exclude_dishes)
    # Không dùng cosine_distance trong SQL — vector search sẽ thực hiện in-memory
    if exclude_ingredient_keys:
        for food in await list_foods_with_ingredient_key_overlap(db, exclude_ingredient_keys):
            append_trace_item(retrieval_trace, "hard_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "sql_hard_filter",
                "reason": "ingredient_key_overlap",
                "matched_keys": matched_keys(food.core_ingredient_keys or [], exclude_ingredient_keys),
                "core_ingredient_keys": food.core_ingredient_keys or [],
            }, limit=SQL_HARD_FILTER_TRACE_LIMIT)

    if user_exclude_dishes:
        for dish in user_exclude_dishes:
            for food in await list_foods_matching_name(db, dish):
                append_trace_item(retrieval_trace, "dish_name_filtered_out", {
                    **food_trace_snapshot(food),
                    "stage": "sql_dish_filter",
                    "reason": "excluded_dish_name",
                    "matched_dish": dish,
                })

    filtered_foods = await list_candidate_foods(
        db,
        exclude_ingredient_keys=exclude_ingredient_keys,
        exclude_dishes=user_exclude_dishes,
    )
    candidate_count = len(filtered_foods)
    python_removed_count = 0
    allergy_text_removed_count = 0
    medical_soft_tag_removed_count = 0
    allergy_key_miss_examples: list[dict] = []

    # Lọc mềm bằng Python cho dữ liệu cũ/chưa rebuild đủ core_ingredient_keys.
    if exclude_ingredient_keys:
        before_python_filter = len(filtered_foods)
        python_safe_foods = []
        for food in filtered_foods:
            food_matched_keys = matched_keys(food.core_ingredient_keys or [], exclude_ingredient_keys)
            if food_matched_keys:
                append_trace_item(retrieval_trace, "hard_filtered_out", {
                    **food_trace_snapshot(food),
                    "stage": "python_hard_filter",
                    "reason": "ingredient_key_overlap",
                    "matched_keys": food_matched_keys,
                    "core_ingredient_keys": food.core_ingredient_keys or [],
                })
            else:
                python_safe_foods.append(food)
        filtered_foods = python_safe_foods
        python_removed_count = before_python_filter - len(filtered_foods)
        print(
            f"🛡️ [PYTHON INGREDIENT FILTER] Loại thêm "
            f"{python_removed_count} món bằng core_ingredient_keys: "
            f"{exclude_ingredient_keys}"
        )

    if allergy_constraints:
        before_allergy_text_filter = len(filtered_foods)
        allergy_safe_foods = []
        for food in filtered_foods:
            allergy_text_matches = detect_allergy_text_matches(
                food,
                allergy_constraints,
                allergy_e_ings,
            )
            if not allergy_text_matches:
                allergy_safe_foods.append(food)
                continue

            allergy_text_removed_count += 1
            has_allergy_key = _food_has_any_ingredient_key(
                food,
                allergy_exclude_ingredient_keys,
            )
            matched_pairs = []
            seen_match_keys = set()
            for match in allergy_text_matches:
                match_key = (match.get("allergy"), match.get("phrase"))
                if match_key in seen_match_keys:
                    continue
                seen_match_keys.add(match_key)
                matched_pairs.append(match)
            append_trace_item(retrieval_trace, "allergy_text_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "allergy_text_filter",
                "reason": "allergy_text_match",
                "matches": matched_pairs[:5],
                "core_ingredients": food.core_ingredients or [],
                "core_ingredient_keys": food.core_ingredient_keys or [],
            })

            if not has_allergy_key and len(allergy_key_miss_examples) < 20:
                miss_example = {
                    "food_id": str(food.id),
                    "food_name": food.name,
                    "matches": matched_pairs[:5],
                    "core_ingredients": food.core_ingredients or [],
                    "core_ingredient_keys": food.core_ingredient_keys or [],
                }
                allergy_key_miss_examples.append(miss_example)
                print(
                    "🚨 [ALLERGY_KEY_MISS] "
                    f"{food.name} text-match={matched_pairs[:3]} "
                    f"nhưng core_ingredient_keys không giao allergy keys."
                )
            elif SEARCH_VERBOSE_LOGS:
                print(
                    "🛡️ [ALLERGY TEXT FILTER] "
                    f"Loại {food.name} vì match={matched_pairs[:3]}"
                )

        filtered_foods = allergy_safe_foods
        print(
            f"🛡️ [ALLERGY TEXT FILTER] Loại "
            f"{allergy_text_removed_count}/{before_allergy_text_filter} món "
            "bằng text fallback trên core_ingredients."
        )

    # Hard filter theo soft_tag bị tắt có chủ đích.
    # Hard filter tag chỉ áp dụng cho bệnh Gout với tag "Hải sản".
    # Lý do: Hải sản chứa purine cao → tăng acid uric → kích hoạt cơn Gout cấp.
    # Đây là chống chỉ định tuyệt đối về sinh học, không thể chỉ dùng penalty score
    # vì semantic reranker vẫn có thể kéo món Hải sản lên top nếu tiêu chí khác khớp.
    # Các bệnh lý khác không dùng hard filter tag vì exclude_soft_tag chứa hỗn hợp
    # tag nguy hiểm cao (Nội tạng) lẫn tag "nên tránh" (Nướng, Xào, Đậm đà) —
    # hard filter toàn bộ gây over-filtering, loại quá nhiều món hợp lệ khỏi pool.
    _gout_hard_exclude_tags = ["Hải sản"] if "Gout" in (symptoms or []) else []
    filtered_foods, medical_soft_tag_removed_count = apply_medical_soft_tag_hard_filter_with_trace(
        foods=filtered_foods,
        excluded_tags=_gout_hard_exclude_tags,
        trace=retrieval_trace,
    )

    # Lọc ngữ cảnh (Context filter) 
    context_before_count = len(filtered_foods)
    filtered_foods = apply_adaptive_context_include_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_include_tags["meal_context"],
        field_name="meal_context",
        label="meal_context",
        trace=retrieval_trace,
    )
    filtered_foods = apply_adaptive_context_include_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_include_tags["occasion_context"],
        field_name="occasion_context",
        label="occasion_context",
        trace=retrieval_trace,
    )
    filtered_foods = apply_adaptive_context_exclude_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_exclude_tags["meal_context"],
        field_name="meal_context",
        label="meal_context",
        trace=retrieval_trace,
    )
    filtered_foods = apply_adaptive_context_exclude_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_exclude_tags["occasion_context"],
        field_name="occasion_context",
        label="occasion_context",
        trace=retrieval_trace,
    )
    context_after_count = len(filtered_foods)

    filtered_foods, dish_name_filter_applied, _dish_name_match_count = (
        apply_adaptive_dish_name_include_filter_with_trace(
            foods=filtered_foods,
            requested_dishes=user_include_dishes,
            trace=retrieval_trace,
        )
    )
    if user_include_dishes:
        requested_dishes_text = ", ".join(user_include_dishes)
        if dish_name_filter_applied:
            retrieval_notes.append(
                f"Hệ thống đã ưu tiên lọc theo nhóm tên món người dùng muốn "
                f"({requested_dishes_text}) trước khi semantic search."
            )
        else:
            retrieval_notes.append(
                f"Không tìm thấy món khớp nhóm tên món người dùng muốn "
                f"({requested_dishes_text}) sau lớp lọc an toàn; hệ thống trả lựa chọn thay thế."
            )

    filtered_foods, ingredient_include_filter_applied, _ingredient_include_match_count, ingredient_include_scope = (
        apply_adaptive_ingredient_include_filter_with_trace(
            foods=filtered_foods,
            include_keys=include_ingredient_keys,
            requested_ingredients=final_p_ings,
            require_primary_role=primary_ingredient_priority_only,
            trace=retrieval_trace,
        )
    )
    if ingredient_include_filter_applied and final_p_ings:
        requested_ingredients_text = ", ".join(final_p_ings)
        primary_label = " trong vai trò món chính" if ingredient_include_scope == "primary_role" else ""
        retrieval_notes.append(
            f"Hệ thống đã ưu tiên lọc theo nguyên liệu người dùng muốn{primary_label} "
            f"({requested_ingredients_text}) trước khi semantic search."
        )

    include_ingredient_match_count = sum(
        1 for food in filtered_foods
        if include_ingredient_keys and _food_has_any_ingredient_key(food, include_ingredient_keys)
    )
    ingredient_priority_food_ids = collect_ingredient_priority_food_ids(
        foods=filtered_foods,
        include_keys=include_ingredient_keys,
        main_meal_request=main_meal_request,
        require_primary_role=primary_ingredient_priority_only,
    )
    if include_ingredient_keys and final_p_ings and not ingredient_include_filter_applied:
        requested_ingredients_text = ", ".join(final_p_ings)
        if ingredient_priority_food_ids:
            primary_label = " trong vai trò món chính" if primary_ingredient_priority_only else ""
            retrieval_notes.append(
                f"Các món khớp nguyên liệu người dùng muốn{primary_label} ({requested_ingredients_text}) "
                "đã được xếp ưu tiên trước; nếu chưa đủ top 5 thì bổ sung món an toàn khác."
            )
        elif primary_ingredient_priority_only and include_ingredient_match_count:
            side_match_message = (
                "Có món phụ/canh/salad khớp nguyên liệu người dùng muốn "
                f"({requested_ingredients_text}), nhưng không xem đó là món chính cho bữa trưa/tối; "
                "các món trả về ưu tiên lựa chọn bữa chính an toàn hơn."
            )
            retrieval_notes.append(side_match_message)
            warning_message = f"{warning_message} {side_match_message}" if warning_message else side_match_message
        else:
            no_match_message = (
                "Không tìm thấy món an toàn khớp nguyên liệu người dùng muốn "
                f"({requested_ingredients_text}) sau khi áp dụng bộ lọc bệnh lý/ngữ cảnh; "
                "các món trả về là lựa chọn thay thế an toàn hơn."
            )
            retrieval_notes.append(no_match_message)
            warning_message = f"{warning_message} {no_match_message}" if warning_message else no_match_message

    print(
        f"📦 [BƯỚC 3 - FILTERED CANDIDATES] Còn lại {len(filtered_foods)} món "
        "sau khi lọc nguyên liệu/ngữ cảnh."
    )
    if SEARCH_VERBOSE_LOGS:
        print(f"\n{'='*60}")
        print(
            f"📦 [BƯỚC 3 - FILTERED CANDIDATES] Hiển thị tối đa "
            f"{SEARCH_CANDIDATE_LOG_LIMIT}/{len(filtered_foods)} món:"
        )
        for i, food in enumerate(filtered_foods[:SEARCH_CANDIDATE_LOG_LIMIT], 1):
            print(f"  {i:>3}. {food.name}")
        if len(filtered_foods) > SEARCH_CANDIDATE_LOG_LIMIT:
            print(f"  ... ẩn {len(filtered_foods) - SEARCH_CANDIDATE_LOG_LIMIT} món còn lại")
        print(f"{'='*60}\n")

    # --- Bước 4: In-memory Semantic Search hoặc Lexical Fallback trên tập đã lọc ---
    query_arr = np.array(query_vector, dtype=np.float32) if query_vector is not None else None
    query_norm = np.linalg.norm(query_arr) if query_arr is not None else 0
    fallback_query_signals = build_fallback_query_signals(
        query=query,
        user_include_dishes=user_include_dishes,
        final_include_ings=final_p_ings,
        user_include_tags=user_include_tags,
        medical_prefer_tags=medical_p_tags,
    ) if retrieval_mode == "lexical_fallback" else None

    step_label = "COSINE + TAG RERANK" if retrieval_mode == "semantic" else "LEXICAL FALLBACK + TAG RERANK"
    print(f"🔢 [BƯỚC 4 - {step_label}] Tính điểm {len(filtered_foods)} món.")
    if SEARCH_VERBOSE_LOGS:
        print(f"🔢 [BƯỚC 4 - SCORE DETAIL] Hiển thị tối đa {SEARCH_SCORE_LOG_LIMIT} món.")
    scored = []
    missing_embedding_count = 0
    zero_vector_count = 0
    score_log_count = 0
    
    for food in filtered_foods:
        lexical_details = {}
        if retrieval_mode == "semantic":
            if not food.embedding:
                missing_embedding_count += 1
                append_trace_item(retrieval_trace, "embedding_skipped", {
                    **food_trace_snapshot(food),
                    "stage": "semantic_scoring",
                    "reason": "missing_embedding",
                })
                if SEARCH_VERBOSE_LOGS and score_log_count < SEARCH_SCORE_LOG_LIMIT:
                    print(f"  ⚠️  {food.name}: BỎ QUA (không có embedding)")
                    score_log_count += 1
                continue

            food_arr = np.array(food.embedding.to_list(), dtype=np.float32)
            food_norm = np.linalg.norm(food_arr)
            if food_norm == 0 or query_norm == 0:
                zero_vector_count += 1
                append_trace_item(retrieval_trace, "embedding_skipped", {
                    **food_trace_snapshot(food),
                    "stage": "semantic_scoring",
                    "reason": "zero_vector",
                })
                if SEARCH_VERBOSE_LOGS and score_log_count < SEARCH_SCORE_LOG_LIMIT:
                    print(f"  ⚠️  {food.name}: BỎ QUA (vector = 0)")
                    score_log_count += 1
                continue

            # Cosine similarity = dot(a, b) / (||a|| * ||b||)
            similarity = float(np.dot(query_arr, food_arr) / (query_norm * food_norm))
        else:
            similarity, lexical_details = calculate_lexical_fallback_score(
                food,
                fallback_query_signals or {},
            )
        
        # Điều chỉnh điểm (Rerank) dựa trên Tag thưởng/phạt
        adjusted_similarity, score_details = calculate_tag_adjusted_similarity(
            food=food,
            base_similarity=similarity,
            user_prefer_tags=user_include_tags,
            medical_prefer_tags=medical_p_tags,
            user_avoid_tags=user_exclude_tags,
            medical_avoid_tags=safety_e_tags,
        )
        score_details["retrieval_mode"] = retrieval_mode
        if lexical_details:
            score_details["lexical_signal_breakdown"] = lexical_details
        tag_adjusted_similarity = adjusted_similarity
        serving_role = infer_serving_role(food)
        meal_role_adjustment = get_meal_role_adjustment(
            serving_role=serving_role,
            main_meal_request=main_meal_request,
            explicit_side_or_snack_request=explicit_side_or_snack_request,
        )
        adjusted_similarity = max(
            0.0,
            min(1.0, tag_adjusted_similarity + meal_role_adjustment),
        )
        medical_caution_matches = collect_medical_caution_ingredient_key_matches(
            food=food,
            symptoms=symptoms,
        )
        medical_caution_penalty = min(
            MAX_MEDICAL_CAUTION_INGREDIENT_KEY_PENALTY,
            len(medical_caution_matches) * MEDICAL_CAUTION_INGREDIENT_KEY_PENALTY,
        )
        adjusted_similarity = max(0.0, adjusted_similarity - medical_caution_penalty)
        score_details.update({
            "serving_role": serving_role,
            "meal_role_adjustment": meal_role_adjustment,
            "medical_caution_penalty": medical_caution_penalty,
            "medical_caution_matches": medical_caution_matches,
            "main_meal_request": main_meal_request,
            "explicit_side_or_snack_request": explicit_side_or_snack_request,
        })
        ingredient_priority_match = food.id in ingredient_priority_food_ids
        scored.append((food, adjusted_similarity, score_details, ingredient_priority_match))
        
        # In log chấm điểm
        should_log_score = SEARCH_VERBOSE_LOGS and score_log_count < SEARCH_SCORE_LOG_LIMIT
        if should_log_score:
            score_log_count += 1
            priority_label = " [ưu tiên nguyên liệu]" if ingredient_priority_match else ""
            base_label = "base" if retrieval_mode == "semantic" else "lexical"
            print(
                f"  📊 {food.name}{priority_label} [{serving_role}]: {base_label} {similarity*100:.2f}% "
                f"+{score_details['tag_bonus']*100:.1f} "
                f"-{score_details['tag_penalty']*100:.1f} "
                f"{meal_role_adjustment*100:+.1f} role "
                f"-{medical_caution_penalty*100:.1f} caution "
                f"=> {adjusted_similarity*100:.2f}%"
            )
            if score_details["matched_prefer_tags"] or score_details["matched_avoid_tags"]:
                print(
                    f"       prefer={score_details['matched_prefer_tags']} "
                    f"avoid={score_details['matched_avoid_tags']}"
                )
            if lexical_details:
                print(
                    "       lexical="
                    f"name:{lexical_details['name_score']:.2f} "
                    f"ing:{lexical_details['ingredient_score']:.2f} "
                    f"meal:{lexical_details['meal_context_score']:.2f} "
                    f"tag:{lexical_details['soft_tag_score']:.2f} "
                    f"res:{lexical_details['residual_score']:.2f}"
                )

    scored_count = len(scored)

    # Sắp xếp giảm dần theo điểm đã rerank, lấy top_k (có deduplication)
    if ingredient_priority_food_ids:
        scored.sort(key=lambda x: (x[3], x[1]), reverse=True)
    else:
        scored.sort(key=lambda x: x[1], reverse=True)
    top5 = _deduplicate_results(scored, top_k)

    # --- Kết quả rỗng: giải thích lý do và trả về sớm ---
    if not top5:
        print("⚠️  [ZERO RESULT] Không có món nào sau tất cả bộ lọc — trả phản hồi giải thích.")
        no_result_note = _build_no_result_retrieval_note(
            symptoms=symptoms,
            safety_e_tags=safety_e_tags,
            final_e_ings=final_e_ings,
            candidate_count=candidate_count,
            context_before_count=context_before_count,
            context_after_count=context_after_count,
            scored_count=scored_count,
        )
        retrieval_notes.append(no_result_note)
        no_result_response = _build_no_result_ai_response(
            symptoms=symptoms,
            safety_e_tags=safety_e_tags,
            final_e_ings=final_e_ings,
            candidate_count=candidate_count,
            context_before_count=context_before_count,
            context_after_count=context_after_count,
            scored_count=scored_count,
        )
        ai_insight_zero = AIInsight(
            exclude=safety_e_tags + final_e_ings,
            include=symptoms,
            prefer=user_include_tags + medical_p_tags + final_p_ings + medical_p_ings,
            warning_message=warning_message,
        )
        query_log_id_zero = None
        try:
            query_log_zero = await create_query_log(
                db,
                query=query,
                ai_insight=ai_insight_zero,
                final_exclude_ings=final_e_ings,
                exclude_ingredient_keys=exclude_ingredient_keys,
                user_include_tags=user_include_tags,
                user_exclude_tags=user_exclude_tags,
                candidate_count=candidate_count,
                filtered_count=context_after_count,
                scored_count=scored_count,
                returned_count=0,
                excluded_summary={
                    "hard_filter": {
                        "exclude_ingredient_keys": exclude_ingredient_keys,
                        "candidate_count_after_sql": candidate_count,
                        "python_removed_count": python_removed_count,
                        "allergy_text_removed_count": allergy_text_removed_count,
                        "medical_soft_tag_removed_count": medical_soft_tag_removed_count,
                        "remaining_count_after_python": context_before_count,
                    },
                    "context_filter": {
                        "before_count": context_before_count,
                        "after_count": context_after_count,
                    },
                    "embedding": {
                        "scored_count": scored_count,
                        "missing_embedding_count": missing_embedding_count,
                        "zero_vector_count": zero_vector_count,
                    },
                    "zero_result": True,
                    "llm_runtime": llm_runtime,
                    "retrieval_trace": retrieval_trace,
                },
                retrieval_notes=retrieval_notes,
                top_results=[],
                warning_message=warning_message,
                thread_id=thread_id,
            )
            query_log_id_zero = query_log_zero.id
        except Exception as e:
            print(f"[QUERY LOG] Không thể lưu query log (zero-result): {e}")
            await db.rollback()
        return SearchResponse(
            query=query,
            ai_insight=ai_insight_zero,
            results=[],
            disclaimer=SEARCH_DISCLAIMER,
            query_log_id=query_log_id_zero,
            ai_response=no_result_response,
        )

    preference_conflict_notes, preference_conflicts_by_food_id, preference_conflict_summaries = build_explicit_preference_conflict_notes(
        user_include_tags=user_include_tags,
        medical_prefer_tags=medical_p_tags,
        top5=top5,
        scored=scored,
    )
    if preference_conflict_notes:
        retrieval_notes.extend(preference_conflict_notes)
        for note in preference_conflict_notes:
            print(f"🧭 [PREFERENCE CONFLICT] {note}")
        for food, _, score_details, _ in top5:
            if food.id in preference_conflicts_by_food_id:
                score_details["explicit_preference_conflicts"] = preference_conflicts_by_food_id[food.id]
    for food, adjusted_similarity, score_details, ingredient_priority_match in scored[:TRACE_LIMIT]:
        append_trace_item(
            retrieval_trace,
            "score_breakdown",
            build_score_trace_item(
                food=food,
                final_score=adjusted_similarity,
                score_details=score_details,
                ingredient_priority_match=ingredient_priority_match,
            ),
        )

    print(f"\n{'='*60}")
    print(f"🏆 [BƯỚC 5 - KẾT QUẢ CUỐI] Top {len(top5)}/{top_k} món phù hợp nhất:")
    for rank, (food, adjusted_similarity, score_details, ingredient_priority_match) in enumerate(top5, 1):
        priority_label = " [ưu tiên nguyên liệu]" if ingredient_priority_match else ""
        print(
            f"  #{rank} [{adjusted_similarity*100:.2f}%] {food.name}{priority_label} "
            f"({score_details['retrieval_mode']} {score_details['base_similarity']*100:.2f}%, role {score_details['serving_role']})"
        )
        print(f"       Soft tags: {food.soft_tags}")
        print(f"       Taste: {food.taste_profile} | Meal: {food.meal_context} | Occasion: {food.occasion_context}")
    print(f"{'='*60}\n")

    # --- Bước 6: Map kết quả về Pydantic Schemas ---
    results_list = []
    for food, adjusted_similarity, score_details, ingredient_priority_match in top5:
        match_score = adjusted_similarity * 100
        reason = build_food_reason(
            food=food,
            match_score=match_score,
            score_details=score_details,
            ingredient_priority_match=ingredient_priority_match,
            requested_ingredients=final_p_ings,
        )
        results_list.append(FoodResult(
            id=food.id,
            name=food.name,
            description=food.description,
            img_url=food.img_url,
            core_ingredients=food.core_ingredients,
            soft_tags=food.soft_tags,
            taste_profile=food.taste_profile,
            meal_context=food.meal_context,
            occasion_context=food.occasion_context,
            matchScore=match_score,
            reason=reason,
            dining_context=food.dining_context,
        ))
    returned_count = len(results_list)
    for rank, result in enumerate(results_list, 1):
        append_trace_item(
            retrieval_trace,
            "returned",
            build_returned_trace_item(rank, result),
        )

    # --- Bước 7: Final Validation → Post-processing ---
    #
    # final_validation_agent: validate từng món theo health constraints,
    #                         xác định PASS / WARN / REJECT, loại REJECT
    #                         và viết reason ngắn cho từng card món ăn.
    # post_processing_agent : là nơi DUY NHẤT sinh ai_response cuối cùng,
    #                         dựa trên danh sách món đã qua validation.
    #
    # Lưu ý: validation được phép ghi reason từng card, nhưng không được viết
    # ai_response. Post-processing là nơi duy nhất viết response tổng quan.

    # Chuẩn bị tham số cho validation
    _medical_e_tags_for_validation = list(medical_e_tags) if symptoms else []
    _medical_e_ings_for_validation = list(final_e_ings) if symptoms else []

    validated_foods, rejected_foods_info, validation_runtime = (
        await run_final_validation_with_timeout(
            user_query=query,
            symptoms=symptoms,
            forbidden_tags=_medical_e_tags_for_validation,
            forbidden_ingredients=_medical_e_ings_for_validation,
            top_foods=results_list,
        )
        if symptoms
        else await _noop_validation(results_list)
    )

    # Ghi runtime validation
    llm_runtime["validation_status"] = validation_runtime.get("status", "ok")
    llm_runtime["stage_latency_ms"]["validation"] = validation_runtime.get("latency_ms", 0)
    if validation_runtime.get("error_message"):
        llm_runtime["validation_error"] = validation_runtime["error_message"]
    if validation_runtime.get("status") == "fallback":
        llm_runtime["fallbacks_used"].append("validation")

    # Áp dụng validation vào danh sách món trước khi sinh ai_response.
    validation_applied = validation_runtime.get("status") == "ok"
    if validation_applied:
        results_list = validated_foods
        returned_count = len(results_list)
    if rejected_foods_info:
        print(
            f"🚫 [VALIDATION] Loại {len(rejected_foods_info)} món: "
            + ", ".join(f['name'] for f in rejected_foods_info)
        )

    ai_response_text, _food_reasons_map, post_processing_runtime = await run_post_processing_with_timeout(
        query,
        symptoms,
        results_list,
        retrieval_notes,
    )

    # Ghi runtime post_processing
    llm_runtime["post_processing_status"] = post_processing_runtime.get("status", "ok")
    llm_runtime["stage_latency_ms"]["post_processing"] = post_processing_runtime.get("latency_ms", 0)
    if post_processing_runtime.get("error_message"):
        llm_runtime["post_processing_error"] = post_processing_runtime["error_message"]
    if post_processing_runtime.get("status") == "fallback":
        llm_runtime["fallbacks_used"].append("post_processing")

    # --- Áp dụng LLM food_reasons từ post_processing (có điều kiện) ---
    # Case A: không symptoms → apply
    # Case B: symptoms + validation OK → KHÔNG apply (validation đã viết reason)
    # Case C: symptoms + validation fallback → apply (có medical warnings)
    _should_apply_post_reasons = (not symptoms) or (not validation_applied)
    if _should_apply_post_reasons and _food_reasons_map:
        updated_results: list[FoodResult] = []
        for food_result in results_list:
            post_reason = _food_reasons_map.get(food_result.name.lower())
            if post_reason:
                updated_results.append(food_result.model_copy(update={"reason": post_reason}))
            else:
                updated_results.append(food_result)  # giữ deterministic reason làm fallback
        results_list = updated_results
        print(f"[POST-PROCESSING] Đã apply LLM reasons cho {sum(1 for r in results_list if r.reason)} / {len(results_list)} món.")

    ai_insight = AIInsight(
        exclude=safety_e_tags + final_e_ings,
        include=symptoms, # Trả về list bệnh lý để UI dễ hiển thị Warning
        prefer=user_include_tags + medical_p_tags + final_p_ings + medical_p_ings,
        warning_message=warning_message
    )
    excluded_summary = {
        "hard_filter": {
            "exclude_ingredient_keys": exclude_ingredient_keys,
            "allergy_constraints": allergy_constraints,
            "allergy_exclude_tags": allergy_e_tags,
            "allergy_exclude_ingredient_keys": allergy_exclude_ingredient_keys,
            "disease_exclude_ingredient_keys": disease_exclude_ingredient_keys,
            "user_exclude_dishes": user_exclude_dishes,
            "candidate_count_after_sql": candidate_count,
            "python_removed_count": python_removed_count,
            "allergy_text_removed_count": allergy_text_removed_count,
            "medical_soft_tag_removed_count": medical_soft_tag_removed_count,
            "allergy_key_miss_examples": allergy_key_miss_examples,
            "remaining_count_after_python": context_before_count,
        },
        "context_filter": {
            "include_meal_context": grouped_user_include_tags["meal_context"],
            "include_occasion_context": grouped_user_include_tags["occasion_context"],
            "exclude_meal_context": grouped_user_exclude_tags["meal_context"],
            "exclude_occasion_context": grouped_user_exclude_tags["occasion_context"],
            "before_count": context_before_count,
            "after_count": context_after_count,
        },
        "ingredient_priority": {
            "include_ingredient_keys": include_ingredient_keys,
            "candidate_match_count": include_ingredient_match_count,
            "matched_count": len(ingredient_priority_food_ids),
            "primary_ingredient_priority_only": primary_ingredient_priority_only,
        },
        "meal_role_rerank": {
            "enabled": main_meal_request,
            "explicit_side_or_snack_request": explicit_side_or_snack_request,
            "role_adjustments": MEAL_ROLE_ADJUSTMENTS,
            "primary_ingredient_priority_only": primary_ingredient_priority_only,
        },
        "preference_conflict": {
            "enabled": bool(preference_conflict_summaries),
            "pairs_checked": [
                {"requested_tag": requested, "returned_conflict_tag": returned}
                for requested, returned in PREFERENCE_CONFLICT_PAIRS
            ],
            "conflicts": preference_conflict_summaries,
        },
        "embedding": {
            "retrieval_mode": retrieval_mode,
            "missing_embedding_count": missing_embedding_count,
            "zero_vector_count": zero_vector_count,
            "scored_count": scored_count,
        },
        "final_validation": {
            "status": validation_runtime.get("status", "ok"),
            "applied": validation_applied,
            "rejected_foods": rejected_foods_info,
            "latency_ms": validation_runtime.get("latency_ms", 0),
        },
        "llm_runtime": llm_runtime,
        "retrieval_trace": retrieval_trace,
    }
    query_log_id = None
    try:
        query_log = await create_query_log(
            db,
            query=query,
            ai_insight=ai_insight,
            final_exclude_ings=final_e_ings,
            exclude_ingredient_keys=exclude_ingredient_keys,
            user_include_tags=user_include_tags,
            user_exclude_tags=user_exclude_tags,
            candidate_count=candidate_count,
            filtered_count=context_after_count,
            scored_count=scored_count,
            returned_count=returned_count,
            excluded_summary=excluded_summary,
            retrieval_notes=retrieval_notes,
            top_results=results_list,
            warning_message=warning_message,
            thread_id=thread_id,
        )
        query_log_id = query_log.id
    except Exception as e:
        print(f"[QUERY LOG] Không thể lưu query log: {e}")
        await db.rollback()

    log_retrieval_trace_for_debug(retrieval_trace, enabled=debug)

    # --- Timing summary cho search_food ---
    _t_search_total = round((time.perf_counter() - _t_search_start) * 1000)
    _stage = llm_runtime.get("stage_latency_ms", {})
    _supervisor_ms  = _stage.get("supervisor", 0)
    _embedding_ms   = _stage.get("embedding", 0)
    _postproc_ms    = _stage.get("post_processing", 0)
    _other_ms       = _t_search_total - _supervisor_ms - _embedding_ms - _postproc_ms
    print(
        f"⏱️ [SEARCH TIMING] "
        f"supervisor={_supervisor_ms}ms | "
        f"embedding={_embedding_ms}ms | "
        f"post_processing={_postproc_ms}ms | "
        f"other(DB+scoring)={_other_ms}ms | "
        f"TOTAL={_t_search_total}ms"
    )

    # --- Trả về phản hồi cuối cùng ---
    return SearchResponse(
        query=query,
        ai_insight=ai_insight,
        results=results_list,
        disclaimer=SEARCH_DISCLAIMER,
        query_log_id=query_log_id,
        retrieval_note=EMBEDDING_FALLBACK_RETRIEVAL_NOTE if retrieval_mode == "lexical_fallback" else None,
        ai_response=ai_response_text or None
    )
