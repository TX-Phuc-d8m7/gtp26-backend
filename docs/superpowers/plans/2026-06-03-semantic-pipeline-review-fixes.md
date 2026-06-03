# Semantic Pipeline Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 3 production blockers (B1 tag over-filtering, B2 top-k starvation, B3 embedding hydration) plus agreed semantics changes (exclude_dishes hard filter, normalized tag matching) found in the review of `app/modules/search/pipeline/`.

**Architecture:** All changes stay inside `app/modules/search/pipeline/` behind the `SEARCH_PIPELINE_VERSION` flag (default `legacy` — production unaffected until flag flips). Decisions locked with user: B1 = whitelist critical tags mirroring legacy (Gout→"Hải sản"), remaining medical tags become scoring penalties; exclude_dishes = hard filter in safety stage.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, pgvector, pytest + pytest-asyncio.

**Quy ước commit (override template):** Claude KHÔNG BAO GIỜ chạy `git commit` — mỗi task kết thúc bằng *gợi ý* commit message để user tự chạy.

---

## File Structure

| File | Thay đổi |
| --- | --- |
| `app/modules/search/pipeline/_utils.py` | **Create** — helpers dùng chung (hiện copy-paste ×4 file) |
| `app/modules/search/pipeline/retrieval.py` | Defer embedding (B3), thêm `needs_retrieval_expansion` (B2) |
| `app/modules/search/pipeline/safety.py` | Whitelist critical tag (B1), normalized tag overlap, hard filter exclude_dishes |
| `app/modules/search/pipeline/scoring.py` | Bỏ dish penalty (chuyển sang safety), thêm medical_avoid penalty (B1), đổi tên cap |
| `app/modules/search/pipeline/types.py` | `CriticalSafetyRules.exclude_dishes`, `ScoreBreakdown.medical_penalty` (bỏ `dish_penalty`) |
| `app/modules/search/pipeline/intent.py` | `ExtractedIntent.medical_avoid_tags` |
| `app/modules/search/pipeline/orchestrator.py` | Wiring B1/B2, trace mới, sửa fallback note, TYPE_CHECKING imports |
| `tests/search/test_pipeline_utils.py` | **Create** |
| `tests/search/test_semantic_pipeline.py` | Thêm test cho task 3–5 |

---

### Task 1: Gom helpers trùng lặp vào `pipeline/_utils.py`

`_get_field`, `_coerce_list`, `_dedupe`, `_normalize_text` đang bị copy-paste trong orchestrator/safety/retrieval/scoring; `_overlap`/`_phrase_matches` (scoring) sắp được safety dùng chung. Gom về một chỗ TRƯỚC để các task sau import.

**Files:**

- Create: `app/modules/search/pipeline/_utils.py`
- Modify: `app/modules/search/pipeline/{orchestrator,safety,retrieval,scoring}.py` (xóa bản local, import từ `_utils`)
- Test: `tests/search/test_pipeline_utils.py`

- [ ] **Step 1: Viết test cho helpers**

```python
# tests/search/test_pipeline_utils.py
from app.modules.search.pipeline._utils import (
    dedupe,
    normalize_text,
    normalized_overlap,
    phrase_matches,
)


def test_normalize_text_strips_diacritics_and_case():
    assert normalize_text("Hải Sản") == "hai san"
    assert normalize_text("  Đậm   đà!! ") == "dam da"


def test_dedupe_keeps_first_casing():
    assert dedupe(["Phở", "phở", " PHỞ ", "Bún"]) == ["Phở", "Bún"]


def test_normalized_overlap_matches_across_diacritics():
    assert normalized_overlap(["hải sản", "Chiên"], ["Hải Sản"]) == ["hải sản"]


def test_phrase_matches_requires_word_boundary():
    assert phrase_matches(["pho bo"], "Pho bo tai chin") == ["pho bo"]
    assert phrase_matches(["pho"], "phong cach") == []
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/search/test_pipeline_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.search.pipeline._utils'`

- [ ] **Step 3: Tạo `_utils.py`** (copy nguyên văn từ các bản hiện có — KHÔNG đổi hành vi)

```python
# app/modules/search/pipeline/_utils.py
"""Shared helpers for the semantic-first search pipeline."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable


def get_field(food: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(food, dict):
        return food.get(field_name, default)
    return getattr(food, field_name, default)


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append(normalized)
    return result


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized_overlap(left: Iterable[str], right: Iterable[str]) -> list[str]:
    """Diacritic/case-insensitive overlap, giữ thứ tự và casing của `left`."""
    right_keys = {normalize_text(item) for item in (right or [])}
    matched: list[str] = []
    seen: set[str] = set()
    for value in left or []:
        key = normalize_text(value)
        if key and key in right_keys and key not in seen:
            seen.add(key)
            matched.append(str(value))
    return matched


def phrase_matches(needles: Iterable[str], haystack: str) -> list[str]:
    normalized_haystack = f" {normalize_text(haystack)} "
    matched: list[str] = []
    for needle in needles or []:
        normalized_needle = normalize_text(needle)
        if normalized_needle and f" {normalized_needle} " in normalized_haystack:
            matched.append(str(needle))
    return matched
```

- [ ] **Step 4: Chạy test utils, xác nhận PASS**

Run: `pytest tests/search/test_pipeline_utils.py -v`
Expected: 4 passed

- [ ] **Step 5: Thay bản local trong 4 module bằng import** (giữ tên `_x` để diff nhỏ nhất)

Trong `scoring.py`: xóa các hàm `_get_field`, `_coerce_list`, `_normalize_text`, `_overlap`, `_phrase_matches` (giữ lại phần còn lại), thêm:

```python
from ._utils import (
    coerce_list as _coerce_list,
    get_field as _get_field,
    normalized_overlap as _overlap,
    phrase_matches as _phrase_matches,
)
```

Trong `safety.py`: xóa `_get_field`, `_coerce_list`, thêm:

```python
from ._utils import coerce_list as _coerce_list, get_field as _get_field
```

Trong `retrieval.py`: xóa `_dedupe`, `_normalize_text`, `_get_field`, `_coerce_list`, thêm:

```python
from ._utils import (
    coerce_list as _coerce_list,
    dedupe as _dedupe,
    get_field as _get_field,
    normalize_text as _normalize_text,
)
```

Trong `orchestrator.py`: xóa `_dedupe`, `_get_field`, `_coerce_list` (GIỮ `_json_safe` — chỉ orchestrator dùng), thêm:

```python
from ._utils import coerce_list as _coerce_list, dedupe as _dedupe, get_field as _get_field
```

- [ ] **Step 6: Chạy toàn bộ test search, xác nhận không vỡ**

Run: `pytest tests/search/ -v`
Expected: tất cả pass (5 test cũ + 4 test mới)

- [ ] **Step 7: Gợi ý commit cho user**

```text
refactor: extract shared semantic pipeline helpers into _utils
```

---

### Task 2 (B3): Defer cột embedding trong cả hai đường retrieval

`Food.embedding` là `HALFVEC(3072)` (~6KB/row, `app/modules/foods/models.py:34`). Hiện semantic path hydrate embedding cho 100 hàng/query; lexical fallback hydrate **cả bảng**.

**Files:**

- Modify: `app/modules/search/pipeline/retrieval.py:60-89` (semantic), `:162-189` (lexical)

- [ ] **Step 1: Sửa `semantic_retrieve_foods`**

```python
async def semantic_retrieve_foods(
    db: "AsyncSession",
    query_vector: list[float],
    *,
    top_k: int,
    food_model: Any | None = None,
) -> list[RetrievedFood]:
    """Retrieve a wide unfiltered candidate pool by vector distance only."""
    if food_model is None:
        from app.models import Food as food_model
    from sqlalchemy import select
    from sqlalchemy.orm import defer

    distance_expr = food_model.embedding.cosine_distance(query_vector)
    stmt = (
        select(food_model, distance_expr.label("distance"))
        .options(defer(food_model.embedding))
        .where(food_model.embedding.is_not(None))
        .order_by(distance_expr)
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()
    # ... phần build RetrievedFood giữ nguyên
```

- [ ] **Step 2: Sửa `lexical_retrieve_foods`**

```python
    if food_model is None:
        from app.models import Food as food_model
    from sqlalchemy import select
    from sqlalchemy.orm import defer

    rows = (
        (await db.execute(select(food_model).options(defer(food_model.embedding))))
        .scalars()
        .all()
    )
```

⚠️ Lưu ý: KHÔNG truy cập `food.embedding` sau retrieval — với AsyncSession, lazy-load attribute deferred sẽ raise `MissingGreenlet`. Đã xác minh: orchestrator/safety/scoring/explanation không đọc field này.

- [ ] **Step 3: Compile check + chạy test**

Run: `python3 -m py_compile app/modules/search/pipeline/retrieval.py && pytest tests/search/ -v`
Expected: compile OK, tất cả pass

- [ ] **Step 4: Verify runtime với DB local** (xem Task 7 — smoke test gộp cuối)

- [ ] **Step 5: Gợi ý commit cho user**

```text
perf: defer 3072-dim embedding column in pipeline retrieval queries
```

---

### Task 3: Hard filter `exclude_dishes` + normalized tag matching trong safety

User nói rõ "không muốn món X" → loại hẳn (quyết định đã chốt, khôi phục ngữ nghĩa legacy `service.py:270-278`). Đồng thời sửa fail-open: tag match trong safety đang exact/case-sensitive trong khi scoring đã normalize.

**Files:**

- Modify: `app/modules/search/pipeline/types.py:35-41`, `safety.py`, `scoring.py`, `orchestrator.py` (`_build_safety_rules` + trace)
- Test: `tests/search/test_semantic_pipeline.py`

- [ ] **Step 1: Viết test FAIL**

```python
# thêm vào tests/search/test_semantic_pipeline.py
def test_excluded_dish_name_is_hard_filtered():
    from app.modules.search.pipeline.safety import (
        CriticalSafetyRules,
        evaluate_critical_safety,
    )

    food = make_food(name="Phở bò tái")
    rules = CriticalSafetyRules(exclude_dishes=["pho bo"])

    decision = evaluate_critical_safety(food, rules)

    assert decision.reject is True
    assert decision.reason == "excluded_dish_name"
    assert decision.matched_values == ["pho bo"]


def test_critical_tag_match_ignores_case_and_diacritics():
    from app.modules.search.pipeline.safety import (
        CriticalSafetyRules,
        evaluate_critical_safety,
    )

    food = make_food(soft_tags=["hải sản"])
    rules = CriticalSafetyRules(critical_exclude_tags=["Hải Sản"])

    decision = evaluate_critical_safety(food, rules)

    assert decision.reject is True
    assert decision.reason == "critical_tag_overlap"
```

Run: `pytest tests/search/test_semantic_pipeline.py -v -k "excluded_dish or ignores_case"`
Expected: FAIL (TypeError: unexpected keyword `exclude_dishes`; tag case-sensitive không match)

- [ ] **Step 2: `types.py` — thêm field vào `CriticalSafetyRules`**

```python
@dataclass
class CriticalSafetyRules:
    health_constraints: list[str] = field(default_factory=list)
    excluded_ingredient_keys: list[str] = field(default_factory=list)
    critical_exclude_tags: list[str] = field(default_factory=list)
    allergy_constraints: list[str] = field(default_factory=list)
    allergy_exclude_ingredients: list[str] = field(default_factory=list)
    exclude_dishes: list[str] = field(default_factory=list)
```

- [ ] **Step 3: `safety.py` — normalize tag match + check dish name**

Import thêm: `from ._utils import normalized_overlap, phrase_matches` (gộp với import Task 1).

Trong `evaluate_critical_safety`, đổi tag check (dòng 62) từ `_ordered_overlap` → `normalized_overlap` (GIỮ `_ordered_overlap` cho ingredient keys — keys là giá trị canonical máy sinh, hai phía cùng `generate_filter_keys` nên exact match là đúng):

```python
    tag_matches = normalized_overlap(
        get_food_scoring_tags(food),
        rules.critical_exclude_tags,
    )
```

Thêm dish check NGAY TRƯỚC `return SafetyDecision(reject=False)`:

```python
    dish_matches = phrase_matches(
        rules.exclude_dishes,
        str(_get_field(food, "name", "")),
    )
    if dish_matches:
        return SafetyDecision(
            reject=True,
            reason="excluded_dish_name",
            matched_values=dish_matches,
        )
```

- [ ] **Step 4: `scoring.py` — gỡ dish penalty (giờ là hard filter, để lại là dead code)**

Xóa: hằng `EXCLUDE_DISH_PENALTY` (dòng 21), block `exclude_dish_matches` (dòng 151–154), và `breakdown.dish_penalty` khỏi tổng penalty (dòng 165 → `penalty = min(MAX_PENALTY, breakdown.dislike_penalty)`).
Xóa field `dish_penalty` trong `ScoreBreakdown` (`types.py:64`). (Trace JSON trong `query_logs` mất key `dish_penalty` — chấp nhận, log là append-only theo schema từng version.)

- [ ] **Step 5: `orchestrator.py` — wire payload + trace**

Trong `_build_safety_rules` thêm:

```python
        exclude_dishes=_dedupe(payload.get("user_exclude_dishes", [])),
```

Trong `excluded_summary["critical_safety"]` thêm:

```python
            "exclude_dishes": safety_rules.exclude_dishes,
```

- [ ] **Step 6: Chạy test, xác nhận PASS**

Run: `pytest tests/search/ -v`
Expected: tất cả pass

- [ ] **Step 7: Gợi ý commit cho user**

```text
fix: hard-filter excluded dishes and normalize critical tag matching
```

---

### Task 4 (B1): Whitelist critical tag — gỡ over-filtering regression

Pipeline mới đang hard-filter TOÀN BỘ `medical_exclude_tags`, ngược với quyết định legacy đã document (`service.py:377-385`: chỉ Gout→"Hải sản" là chống chỉ định tuyệt đối; còn lại là tag "nên tránh" → over-filter). Quyết định đã chốt: whitelist như legacy, phần còn lại thành penalty.

**Files:**

- Modify: `safety.py` (whitelist + helper), `orchestrator.py:160-170` (`_build_safety_rules`), `intent.py` + `types.py` (field mới), `scoring.py` (penalty mới)
- Test: `tests/search/test_semantic_pipeline.py`

- [ ] **Step 1: Viết test FAIL**

```python
def test_only_whitelisted_tags_are_critical():
    from app.modules.search.pipeline.safety import select_critical_exclude_tags

    assert select_critical_exclude_tags(["Gout"]) == ["Hải sản"]
    assert select_critical_exclude_tags(["Tiểu đường"]) == []
    assert select_critical_exclude_tags(["Tiểu đường", "Gout"]) == ["Hải sản"]
    assert select_critical_exclude_tags([]) == []


def test_non_whitelisted_medical_tags_penalize_instead_of_reject():
    from app.modules.search.pipeline.scoring import ExtractedIntent, score_candidate
    from app.modules.search.pipeline.types import RetrievedFood

    food = make_food(soft_tags=["Chiên"])
    intent = ExtractedIntent(medical_avoid_tags=["Chiên"])

    scored = score_candidate(RetrievedFood(food=food, semantic_score=0.80), intent)

    assert scored.final_score < 0.80
    assert "medical_avoid_tag_penalty" in scored.reason_signals
```

Run: `pytest tests/search/test_semantic_pipeline.py -v -k "whitelisted or penalize_instead"`
Expected: FAIL (`ImportError: select_critical_exclude_tags`; `TypeError: medical_avoid_tags`)

- [ ] **Step 2: `safety.py` — whitelist + helper**

```python
from ._utils import dedupe

# Hard filter theo tag chỉ dành cho chống chỉ định TUYỆT ĐỐI về sinh học.
# Mirror quyết định legacy (app/modules/search/service.py:377-385):
# exclude_soft_tag của đa số bệnh trộn tag nguy hiểm cao với tag "nên tránh"
# (Nướng, Xào, Đậm đà...) — hard filter toàn bộ gây over-filtering.
# Tag "nên tránh" được xử lý bằng penalty trong scoring (medical_avoid_tags).
CRITICAL_TAG_WHITELIST: dict[str, list[str]] = {
    "Gout": ["Hải sản"],
}


def select_critical_exclude_tags(health_constraints: list[str]) -> list[str]:
    """Chỉ trả về tag thuộc whitelist chống chỉ định tuyệt đối theo bệnh."""
    critical: list[str] = []
    for condition in health_constraints or []:
        critical.extend(CRITICAL_TAG_WHITELIST.get(condition, []))
    return dedupe(critical)
```

- [ ] **Step 3: `orchestrator.py` — `_build_safety_rules` dùng whitelist**

```python
from .safety import apply_critical_safety_filter, select_critical_exclude_tags

def _build_safety_rules(
    payload: dict[str, Any],
    critical_exclude_ingredient_keys: list[str],
) -> CriticalSafetyRules:
    return CriticalSafetyRules(
        health_constraints=_dedupe(payload.get("symptoms", [])),
        excluded_ingredient_keys=critical_exclude_ingredient_keys,
        critical_exclude_tags=select_critical_exclude_tags(payload.get("symptoms", [])),
        allergy_constraints=_dedupe(payload.get("allergy_constraints", [])),
        allergy_exclude_ingredients=_dedupe(payload.get("allergy_exclude_ings", [])),
        exclude_dishes=_dedupe(payload.get("user_exclude_dishes", [])),
    )
```

Lưu ý: hard filter theo **ingredient keys** (allergy + disease) GIỮ NGUYÊN — chỉ thu hẹp phần tag.

- [ ] **Step 4: `types.py` + `intent.py` — chuyển phần tag còn lại sang intent**

`ExtractedIntent` thêm field:

```python
    medical_avoid_tags: list[str] = field(default_factory=list)
```

`intent_from_conflict_payload` (trong `return ExtractedIntent(...)`) thêm:

```python
        medical_avoid_tags=_dedupe(payload.get("medical_exclude_tags", [])),
```

`ScoreBreakdown` thêm field:

```python
    medical_penalty: float = 0.0
```

- [ ] **Step 5: `scoring.py` — penalty cho tag "nên tránh"**

```python
MEDICAL_AVOID_PENALTY = 0.12  # mạnh hơn disliked_tag (0.10): lý do y khoa > sở thích
```

Trong `score_candidate`, sau block `disliked_tag_matches`:

```python
    medical_avoid_matches = _overlap(food_tags, intent.medical_avoid_tags)
    if medical_avoid_matches:
        breakdown.medical_penalty += min(0.24, len(medical_avoid_matches) * MEDICAL_AVOID_PENALTY)
        signals.append("medical_avoid_tag_penalty")
```

Tổng penalty (đã bỏ dish_penalty ở Task 3):

```python
    penalty = min(
        MAX_PENALTY,
        breakdown.dislike_penalty + breakdown.medical_penalty,
    )
```

- [ ] **Step 6: Chạy test, xác nhận PASS**

Run: `pytest tests/search/ -v`
Expected: tất cả pass — đặc biệt `test_critical_safety_rejects_only_medical_ingredient_keys` (ingredient-key path không đổi) và `test_critical_tag_match_ignores_case_and_diacritics` (giờ rules được build từ whitelist nhưng test gọi trực tiếp `evaluate_critical_safety` nên vẫn pass)

- [ ] **Step 7: Gợi ý commit cho user**

```text
fix: restrict critical tag hard-filter to whitelist, demote rest to scoring penalty
```

---

### Task 5 (B2): Mở rộng retrieval khi safety filter làm cạn pool

Top-k=100 rồi mới lọc → user nhiều ràng buộc bị reject sạch dù món an toàn nằm ở rank 101+. Fix: một lần retry với pool ×5.

**Files:**

- Modify: `retrieval.py` (helper thuần để test được), `orchestrator.py:212-249` (`_retrieve_candidates` trả thêm query_vector) + `:298-330` (wiring)
- Test: `tests/search/test_semantic_pipeline.py`

- [ ] **Step 1: Viết test FAIL**

```python
def test_needs_retrieval_expansion_only_when_semantic_pool_starved():
    from app.modules.search.pipeline.retrieval import needs_retrieval_expansion

    assert needs_retrieval_expansion(2, 5, "semantic") is True
    assert needs_retrieval_expansion(0, 5, "semantic") is True
    assert needs_retrieval_expansion(5, 5, "semantic") is False
    assert needs_retrieval_expansion(0, 5, "lexical_fallback") is False
```

Run: `pytest tests/search/test_semantic_pipeline.py -v -k expansion`
Expected: FAIL — ImportError

- [ ] **Step 2: `retrieval.py` — helper + hằng số**

```python
RETRIEVAL_EXPANSION_FACTOR = 5


def needs_retrieval_expansion(
    safe_count: int,
    return_limit: int,
    retrieval_mode: str,
) -> bool:
    """Mở rộng pool khi safety filter loại gần hết candidates semantic.

    Chỉ áp dụng cho semantic: lexical fallback đã quét toàn bộ bảng nên
    không còn gì để mở rộng.
    """
    return retrieval_mode == "semantic" and safe_count < return_limit
```

- [ ] **Step 3: `orchestrator.py` — `_retrieve_candidates` trả thêm `query_vector`**

Đổi chữ ký + 3 điểm return:

```python
async def _retrieve_candidates(
    db: "AsyncSession",
    query: str,
    intent: ExtractedIntent,
    semantic_query_text: str,
    retrieval_notes: list[str],
    llm_runtime: dict[str, Any],
) -> tuple[list[RetrievedFood], str, list[float] | None]:
    ...
    if query_vector is not None:
        candidates = await semantic_retrieve_foods(db, list(query_vector), top_k=top_k)
        if candidates:
            llm_runtime["retrieval_mode"] = "semantic"
            return candidates, "semantic", list(query_vector)
    ...
    return candidates, "lexical_fallback", None
```

Call site: `candidates, retrieval_mode, query_vector = await _retrieve_candidates(...)`

- [ ] **Step 4: `orchestrator.py` — wiring expansion sau safety filter**

Import thêm từ `.retrieval`: `needs_retrieval_expansion`, `RETRIEVAL_EXPANSION_FACTOR`, `semantic_retrieve_foods` (đã có).

Chuyển dòng `return_limit = ...` (hiện ở dòng 321) lên TRƯỚC `apply_critical_safety_filter`, rồi sau safety filter:

```python
    safe_candidates, rejected_candidates = apply_critical_safety_filter(
        candidates,
        safety_rules,
    )

    if (
        query_vector is not None
        and needs_retrieval_expansion(len(safe_candidates), return_limit, retrieval_mode)
    ):
        expanded_top_k = _setting_int("semantic_retrieval_top_k", 100) * RETRIEVAL_EXPANSION_FACTOR
        wider_candidates = await semantic_retrieve_foods(db, query_vector, top_k=expanded_top_k)
        llm_runtime.setdefault("fallbacks_used", []).append("retrieval_expanded")
        llm_runtime["retrieval_expanded_top_k"] = expanded_top_k
        if len(wider_candidates) > len(candidates):
            candidates = wider_candidates
            safe_candidates, rejected_candidates = apply_critical_safety_filter(
                candidates,
                safety_rules,
            )
```

Trong `excluded_summary["retrieval"]` thêm:

```python
            "expanded_top_k": llm_runtime.get("retrieval_expanded_top_k"),
```

- [ ] **Step 5: Chạy test + compile**

Run: `pytest tests/search/ -v && python3 -m py_compile app/modules/search/pipeline/orchestrator.py`
Expected: tất cả pass

- [ ] **Step 6: Gợi ý commit cho user**

```text
fix: expand semantic retrieval pool when safety filter starves results
```

---

### Task 6: Dọn cơ học — TYPE_CHECKING imports, đổi tên cap, sửa fallback note

**Files:**

- Modify: `orchestrator.py:21-23` (TYPE_CHECKING), `:212-249` (note), `:407-422` (retrieval_note), `scoring.py:23,156-162` (rename)

- [ ] **Step 1: `orchestrator.py` — TYPE_CHECKING imports**

`FoodResult`/`SearchResponse`/`AIInsight` được dùng làm annotation nhưng chỉ import trong hàm (chạy được nhờ `from __future__ import annotations`, mypy/pyright fail):

```python
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.modules.search.schemas import AIInsight, FoodResult, SearchResponse
    from app.modules.users.models import UserHealthProfile
```

- [ ] **Step 2: `scoring.py` — `MAX_TAG_BONUS` → `MAX_TOTAL_BONUS`**

Hằng này cap TỔNG bonus (tag+context+preference+medical), không riêng tag. Đổi tên ở dòng 23 và dòng 157. (Đã verify: `MAX_TAG_BONUS` trong `app/modules/search/common.py`/`ranking.py` là hằng legacy riêng — KHÔNG đụng.)

- [ ] **Step 3: `orchestrator.py` — fallback note đúng nguyên nhân**

Hiện DB chưa có embedding nào (vector OK nhưng 0 candidates) vẫn báo user "dịch vụ phân tích tạm thời gián đoạn" — sai nguyên nhân. Sửa `_retrieve_candidates`:

```python
    if query_vector is not None:
        candidates = await semantic_retrieve_foods(db, list(query_vector), top_k=top_k)
        if candidates:
            llm_runtime["retrieval_mode"] = "semantic"
            return candidates, "semantic", list(query_vector)
        llm_runtime["retrieval_empty_reason"] = "no_embedded_foods"
    else:
        retrieval_notes.append(EMBEDDING_FALLBACK_RETRIEVAL_NOTE)
        llm_runtime["user_visible_retrieval_note_applied"] = True

    llm_runtime["retrieval_mode"] = "lexical_fallback"
    llm_runtime.setdefault("fallbacks_used", []).append("embedding")
    candidates = await lexical_retrieve_foods(db, query, intent, top_k=top_k)
    return candidates, "lexical_fallback", None
```

Và `SearchResponse` cuối hàm — note chỉ hiện khi embedding thật sự lỗi:

```python
        retrieval_note=retrieval_notes[0] if retrieval_notes else None,
```

- [ ] **Step 4: Chạy test + compile toàn pipeline**

Run: `pytest tests/search/ -v && python3 -m py_compile $(find app/modules/search/pipeline -name '*.py')`
Expected: tất cả pass

- [ ] **Step 5: Gợi ý commit cho user**

```text
chore: fix type-check imports, rename bonus cap, correct fallback note cause
```

---

### Task 7: Verification tổng — test suite + smoke test với flag bật

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -v`
Expected: tất cả pass (≥13 test trong tests/search/)

- [ ] **Step 2: Compile toàn bộ module search**

Run: `python3 -m py_compile $(find app/modules/search -name '*.py')`
Expected: exit 0, không output

- [ ] **Step 3: Smoke test local với pipeline mới**

```bash
docker-compose up -d
source venv/bin/activate
SEARCH_PIPELINE_VERSION=semantic_first uvicorn app.main:app --reload --port 8000
```

Tại `http://localhost:8000/docs`, gọi search với `debug=true` và kiểm tra từng case:

| Case | Query / profile | Kiểm tra trong `retrieval_trace` |
| --- | --- | --- |
| B1 | Profile tiểu đường + query "món chiên giòn" | `critical_safety.critical_exclude_tags` chỉ chứa tag whitelist (rỗng với tiểu đường); món "Chiên" vẫn xuất hiện nhưng có `medical_avoid_tag_penalty` trong `reason_signals` |
| B1 (Gout) | Profile Gout + query "hải sản" | Món tag "Hải sản" nằm trong `rejected_sample` với reason `critical_tag_overlap` |
| B2 | Profile nhiều dị ứng + query hẹp | Nếu pool cạn: `llm_runtime.fallbacks_used` chứa `retrieval_expanded`, `retrieval.expanded_top_k = 500`, results không rỗng nếu DB còn món an toàn |
| Dish | Query "gợi ý món nước, không ăn phở" | Không có "Phở" trong results; `rejected_sample` có reason `excluded_dish_name` |
| B3 | Bất kỳ | Server log không chậm bất thường; (tùy chọn) bật `echo=True` tạm để xác nhận SQL không SELECT cột embedding |

- [ ] **Step 4: Đối chiếu legacy** — chạy lại cùng các query với `SEARCH_PIPELINE_VERSION=legacy`, xác nhận response shape không đổi và legacy không bị ảnh hưởng.

---

## Ngoài phạm vi (ghi nhận, không làm trong plan này)

- **HNSW index** cho `foods.embedding` — cần khi data lớn; tạo bằng SQL migration riêng (`CREATE INDEX ... USING hnsw (embedding halfvec_cosine_ops)`), đo recall trước/sau.
- **Severity field trong `tags_data.json`** — giải pháp dài hạn thay whitelist hardcode; cần người rà từng rule y khoa.
- **`print` → structured logging** — nợ chung toàn codebase, ngoài blast radius của nhánh này.
- **Shadow traffic legacy vs semantic_first** qua `query_logs` trước khi flip flag production.
