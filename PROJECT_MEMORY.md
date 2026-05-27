# PROJECT MEMORY - Food Recommendation Backend

Last updated: 2026-05-24

This file is working memory for future engineers/AI agents. It records the current backend shape, what is reliable, what is intentionally MVP, and what should not be assumed.

## 1. Current Snapshot

The backend has been refactored from root-level `services/routers/models` into a modular layout under `app/modules`.

Current app entrypoint:

- Preferred: `app.main:app`
- Compatibility: root `main.py` re-exports `app.main:app`

Current public search endpoint:

- `GET /foods/search?q=...`
- Handler: `app.modules.search.service.search_food`
- `app.modules.search.service` is now the orchestration/facade layer; detailed search behavior is split across dedicated search engine modules.

Current runtime food seed:

- `standard-data/ingredients-data/food-clean-categorized/raw_foods_enriched_labeled(final_488).categorized.clean.json`

Current rule seed:

- `standard-data/tags_data.json`

Current medical advice runtime file:

- `standard-data/generated-rules/medical-advice-rules/medical_advice_rules.json`

## 2. Current Module Ownership

Important modules:

- `app/modules/auth`: signup, login, stateless refresh, logout, current user.
- `app/modules/users`: user health profile.
- `app/modules/foods`: food library browsing/detail.
- `app/modules/search`: AI food recommendation search.
- `app/modules/favorites`: saved foods, notes, rating, recommendations, shopping list.
- `app/modules/chat`: chat threads/messages and assistant message feedback.
- `app/modules/query_logs`: admin query log browsing.
- `app/modules/admin/foods`: food CRUD/import/image/key/embedding admin.
- `app/modules/admin/tags`: tag/rule CRUD admin.
- `app/modules/admin/users`: user admin.
- `app/modules/admin/alias_overrides`: ingredient alias override admin.
- `app/modules/ingredients`: shared ingredient key generation.
- `app/db/seed.py`: startup/manual seed sync.
- `app/integrations/vertex_ai.py`: embedding helpers and food embedding text.

Root compatibility files still exist:

- `main.py`
- `models.py`
- `schemas.py`
- `database.py`

New code should prefer module imports from `app.modules.<domain>`.

## 3. Database State

Models are defined in module-owned `models.py` files and imported by `app/db/base.py`.

Current tables:

- `users`
- `user_health_profiles`
- `foods`
- `tags`
- `favorite_foods`
- `chat_threads`
- `chat_messages`
- `query_logs`
- `ingredient_alias_overrides`

Not currently implemented:

- `refresh_tokens`
- `food_feedback`
- `user_disliked_foods`
- `admin_audit_logs`

Foreign key status:

- DB-level `ForeignKey` constraints are intentionally not used at the moment.
- Relation fields use UUID columns plus indexes/unique constraints and service-level handling.
- `favorite_foods.food_id`, `favorite_foods.user_id`, and `user_health_profiles.user_id` are not FK-constrained.
- Seed stale-delete code manually deletes `favorite_foods` rows when deleting stale foods.

## 4. Auth Reality

Current endpoints:

- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`

Important: `/auth/refresh` is MVP/stateless. It requires a valid Bearer access token and returns a new access token. There is no refresh token table, refresh token rotation, token blacklist, or server-side revocation store.

Do not claim that the backend has real refresh-token persistence.

## 5. User Preference Reality

User health profile API:

- `GET /users/me/health-profile`
- `PUT /users/me/health-profile`
- `PATCH /users/me/health-profile`
- `DELETE /users/me/health-profile`

Stored fields:

- `health_conditions`
- `allergies`
- `diet_preferences`
- `nutrition_goals`
- `disliked_ingredients`
- `preferred_ingredients`
- `notes`

There is no `user_disliked_foods` table/API by `food_id`. Food dislike is not modeled separately. Current dislike support is ingredient text through `user_health_profiles.disliked_ingredients`.

## 6. Feedback Reality

Current feedback-like features:

- `favorite_foods.rating`
- `favorite_foods.notes`
- `chat_messages.feedback`

Current chat feedback endpoint:

- `PATCH /chat/threads/{thread_id}/messages/{message_id}/feedback`
- Accepts `like`, `dislike`, or `null`

There is no separate `food_feedback` table/API.

## 7. Admin Reality

Current admin APIs include:

- `/admin/foods`
- `/admin/tags`
- `/admin/users`
- `/admin/ingredient-alias-overrides`
- `/admin/query-logs`

There is no `admin_audit_logs` table/API yet. Admin CRUD actions are not currently persisted to a dedicated audit log.

## 8. Startup And Seed Sync

Config source:

- `app/core/config.py`
- `.env`

Important flags:

```env
RUN_SEED_ON_STARTUP=true
SYNC_TAGS_ON_STARTUP=true
SYNC_FOODS_ON_STARTUP=true
SYNC_FOODS_DELETE_STALE_ON_STARTUP=true
RUN_EMBEDDING_ON_STARTUP=true
```

Startup flow:

1. `app.main` lifespan calls `init_db()`.
2. `init_db()` creates extension/table/index/compat columns.
3. If `RUN_SEED_ON_STARTUP=true`, `seed_data()` runs.
4. `sync_tags()` syncs `tags_data.json`.
5. `sync_foods()` syncs the clean categorized food JSON.
6. If `SYNC_FOODS_DELETE_STALE_ON_STARTUP=true`, foods present in DB but absent from the JSON are deleted.
7. Stale favorite rows are deleted before stale food rows.
8. If `RUN_EMBEDDING_ON_STARTUP=true`, missing embeddings are backfilled.

Manual seed commands:

```bash
python3 -m app.db.seed --foods --delete-stale-foods
python3 -m app.db.seed --all --delete-stale-foods
```

Safety note:

- Stale delete is guarded: if the seed file has no valid food names, it skips deleting all DB foods.

## 9. Food Data Model

`foods` currently stores:

- `name`
- `description`
- `img_url`
- `core_ingredients`
- `raw_ingredients`
- `raw_instructions`
- `core_ingredient_keys`
- `soft_tags`
- `taste_profile`
- `meal_context`
- `occasion_context`
- `embedding`

The category migration is complete enough for MVP:

- `taste_profile` stores taste signals.
- `meal_context` stores meal timing.
- `occasion_context` stores usage context.
- `soft_tags` stores form/method/nutrition/cuisine/texture signals.

Embedding text should stay aligned between food seed and search query. Current source of truth for food embedding text is `app/integrations/vertex_ai.py`.

## 10. Ingredient Key System

Shared service:

- `app/modules/ingredients/service.py`

Baseline alias generation/audit:

- `scripts/generate_ingredient_key_preview.py`
- `standard-data/alias-rules/ingredient_key_preview.v1.json`

Key types:

- `base:*`: normalized raw ingredient key.
- `canon:*`: canonical ingredient.
- `group:*`: broader ingredient group.

Admin override table:

- `ingredient_alias_overrides`

Admin override API:

- `GET /admin/ingredient-alias-overrides`
- `POST /admin/ingredient-alias-overrides`
- `PATCH /admin/ingredient-alias-overrides/{override_id}`
- `DELETE /admin/ingredient-alias-overrides/{override_id}`
- `POST /admin/ingredient-alias-overrides/rebuild-food-keys`

Important recent behavior:

- Filter intent exact match maps `cá` with accents to `canon:ca`.
- Plain `ca` is not globally mapped to `canon:ca`, to avoid collision with `cà chua`, `cà rốt`, `cà tím`.
- Fish intent can trigger adaptive ingredient include filtering with `canon:ca` / `group:ca_co_vay`.

## 11. Search Flow

Public facade:

- `app/modules/search/service.py`

Search engine module ownership:

- `service.py`: orchestrates `search_food()` and preserves existing imports for router/chat/scripts.
- `repository.py`: DB queries only.
- `common.py`: shared constants, Gemini client/model config, tag/normalization helpers.
- `intent.py`: supervisor LLM, fallback intent extraction, health constraint extraction.
- `safety.py`: allergy text matching plus medical/allergy constraint resolution.
- `filtering.py`: adaptive hard filters for context, dish name, and ingredient include.
- `retrieval.py`: Gemini query embedding and lexical fallback scoring.
- `ranking.py`: serving role inference, tag scoring, rerank, dedupe, preference conflict notes.
- `explanation.py`: deterministic food reasons, no-result response, post-processing LLM.
- `tracing.py`: retrieval trace helpers and query-log debug payload pieces.

Dependency direction:

- API/chat/scripts call `search.service.search_food`.
- `service.py` calls the specialized modules and `repository.py`.
- Specialized modules may import `common.py`, but should not import `service.py`.
- `repository.py` should not contain scoring/filter business logic.

Current flow:

1. `service.search_food()` initializes LLM runtime state and retrieval trace.
2. `safety.resolve_food_conflicts()` calls `intent.run_supervisor_with_timeout()` to extract health constraints, include/exclude dishes, ingredients, tags, and contexts.
3. `safety.resolve_food_conflicts()` loads matching `Tag` rows through `repository.py` and merges user preferences/profile with medical rules.
4. `service.py` converts ingredient exclusions to alias keys and asks `repository.py` for SQL-filtered candidates.
5. `safety.py` and `filtering.py` apply Python hard filter, allergy text fallback, medical soft-tag hard filter, context filters, dish-name include filter, and ingredient include adaptive filter.
6. `retrieval.py` generates query embedding; if embedding fails, lexical fallback signals are used.
7. `service.py` computes in-memory semantic/lexical scores and delegates tag/meal-role adjustments to `ranking.py`.
8. `ranking.py` deduplicates top K and records preference conflicts when useful.
9. `explanation.py` builds deterministic per-food `reason` and final cautious `ai_response` using `medical_advice_rules.json`.
10. `tracing.py` builds trace items for debug/query log; API response shape remains unchanged.

## 12. Medical Rule Behavior

Hard rule source:

- `standard-data/tags_data.json`
- DB table `tags`

Important behavior:

- Disease `exclude_ingredient` becomes hard ingredient filter.
- Disease `exclude_soft_tag` is currently a hard filter.
- Allergy safety primarily relies on `exclude_ingredient` plus allergy text fallback.
- Broad allergy soft-tag blocking is avoided to reduce false positives.

Advice rule source:

- `standard-data/generated-rules/medical-advice-rules/medical_advice_rules.json`

Advice rules do not block foods. They only guide final explanation after retrieval.

Current caution/penalty example:

- `Gout` + `group:purine_vua` gets soft penalty/warning for ingredients such as `chao`.

## 13. Known Search Design Details

Dish base prompt list:

- `USER_FOOD_BASE_PHRASES` is injected into the supervisor prompt.
- Deterministic keyword mapping from raw query to `user_include_dishes` was removed because it mishandled negation.
- LLM should decide include vs exclude dishes.

Fish intent:

- `cá` with accents resolves to `canon:ca`.
- `ca` without accents is left ambiguous unless LLM/context resolves it to `cá`.
- `cà chua` / `ca chua` must not become `canon:ca`.

Logging:

- `SEARCH_VERBOSE_LOGS=false` keeps backend console readable.
- Candidate/scoring detail logs are limited by `SEARCH_CANDIDATE_LOG_LIMIT` and `SEARCH_SCORE_LOG_LIMIT`.

## 14. Data Quality Notes

Runtime food data is useful for demo but still heuristic. Known categories of risk:

- Dish names and ingredient lists may be inconsistent.
- Vietnamese substring collisions are common: `cá/cà/ca`, `bò/bơ/bo`, `mè/me`, `sữa/sứa`.
- Hidden ingredients require both alias key coverage and text fallback.
- Soft tags such as `Healthy / Eat Clean` can be too optimistic for specific diseases.
- Some dish role inference can misclassify dishes with words like `bánh tráng` as snack even when they are meal-like.

Do not solve source-data errors only by adding broad code rules. Prefer fixing data or alias rules when the issue is data-specific.

## 15. Current API Surface Checklist

Implemented:

- Auth MVP.
- User health profile.
- Food search.
- Food library browse/detail.
- Favorites with notes/rating/recommendations/shopping list.
- Chat threads/messages/regenerate/edit-and-resend/message feedback.
- Admin food CRUD/import/image/key/embedding.
- Admin tag CRUD.
- Admin user list/update/lock/unlock.
- Admin ingredient alias overrides.
- Admin query logs.

Not implemented:

- Persistent refresh token table/API.
- DB-level FK constraints.
- Dedicated food feedback.
- Dedicated disliked-food table/API.
- Admin audit logs.

## 16. Useful Commands

Run backend:

```bash
source venv/bin/activate
python -m uvicorn app.main:app --reload
```

Compile core files:

```bash
python3 -m py_compile $(find app/modules/search app/modules/chat scripts -type f -name '*.py')
```

Generate ingredient key preview:

```bash
python3 scripts/generate_ingredient_key_preview.py --force
```

Run pathology tests:

```bash
python3 scripts/run_pathology_tests.py
```

## 17. Future Work

High-priority candidates:

1. Add regression tests for the 17 focused disease/allergy/symptom tags.
2. Add tests for ambiguous Vietnamese ingredient aliases.
3. Improve ranking for disease-specific cases where a generally healthy tag hides risk.
4. Add real refresh token persistence if auth needs production-grade sessions.
5. Add dedicated `food_feedback` if product needs per-food like/dislike beyond favorite rating.
6. Add `user_disliked_foods` if user dislikes should target exact `food_id`.
7. Add `admin_audit_logs` before production admin usage.
8. Consider DB-level FK constraints when schema migration strategy is ready.

Longer-term agentic/RAG roadmap remains possible, but only after deterministic search/rule behavior is stable enough to evaluate.

## 18. Worktree Caution

The repo often has a dirty worktree due to active data cleaning, generated files, and demo scripts. Do not revert unrelated changes without explicit user approval.
