# Architecture

How the concepts in `README.md` map onto code. Read this before changing the data model or the AI
integration.

## Components

```
 browser ──► frontend (nginx: SPA + reverse proxy) ──► backend (Django + DRF) ──► PostgreSQL + pgvector
                                                          │
                                                          ├──► generative LLM   (OpenAI-compatible; Unsloth Studio on the host)
                                                          └──► embedding model  (OpenAI-compatible; services/embeddings by default)
```

| Directory | What | Runs as |
|---|---|---|
| `backend/` | Django project `config`, domain apps in `apps/`, AI adapters in `ai/` | `backend` container, or `uv run` natively |
| `frontend/` | React + TypeScript SPA (Vite) | `frontend` container (nginx), or `npm run dev` |
| `services/embeddings/` | OpenAI-compatible `/v1/embeddings` around sentence-transformers | `embeddings` container (compose profile), or `uv run uvicorn` |

The frontend and backend always share one origin (Vite proxy in development, nginx in
production), so the API uses Django session auth and CSRF without CORS.

## Domain apps

| App | Models | Notes |
|---|---|---|
| `catalog` | `Ingredient`, `KitchenTool` | Global, shared by every family. Ingredient names are normalized on save (lowercase, single spaces); variants go in `aliases`. |
| `recipes` | `Cuisine`, `Recipe`, `RecipeIngredient`, `RecipeEmbedding` | Recipes are global too; quantities refer to `Recipe.servings` and scale linearly. |
| `families` | `Family`, `Membership`, `FamilyMember`, `Preference`, `RecipeBookEntry`, `FamilyEmbedding` | Everything family-specific. `RecipeBookEntry` is the per-family view of a recipe: candidate / approved / rejected, plus the explicit rating. |
| `menus` | `WeeklyMenu`, `MealSlot`, `SlotDish` | 7 days × {lunch, dinner}. Shopping list in `menus/shopping.py`, computed, never stored. |
| `core` | none (abstract mixins and helpers) | Seasonality and provenance helpers, shared serializer mixin. |

### Decisions worth knowing

- **Shared recipes, per-family recipe book** (confirmed by Paolo 2026-10-05). One `Recipe` row can be in many families' books.
  This is what makes collaborative recommendation possible ("families like yours loved X"), and
  keeps discovery candidates separate from accepted recipes (`RecipeBookEntry.Status.CANDIDATE`).
- **People per slot.** `MealSlot.people` is the source of truth. `Family.default_people` only
  prefills new slots (`WeeklyMenu.create_empty_slots`). `people = 0` means nobody eats at home,
  and that slot adds nothing to the shopping list.
- **One or more dishes per slot** (confirmed by Paolo 2026-10-05). `SlotDish` allows e.g. a first course plus a side dish; most
  slots will have one.
- **Implicit feedback lives on the slot.** `MealSlot.outcome` (planned / followed / replaced /
  skipped), with `eaten_instead` when replaced. `rating` and `comment` are the optional explicit
  layer.
- **Seasonality: stored as months, edited by season or by month** (decided with Paolo
  2026-10-05). Storage is always an array of months 1-12; an empty array means "all year". Users
  edit in two modes: **by season** (default; meteorological seasons, e.g. summer = June-August)
  or **by month** (advanced). The API field (`SeasonalityField`) reads as
  `{"months": [...], "seasons": [...], "by_season": bool}`, where `by_season` says whether the
  value is a union of whole seasons and so can be shown in season mode. It accepts
  `{"seasons": [...]}` or `{"months": [...]}` on write. A recipe has two levels:
  `season_months` (derived bottom-up via `Recipe.derive_season_months`, the intersection of its
  non-optional ingredients' months) and `climate_months` (whether the dish suits the weather).
  `Recipe.suitable_months()` combines them.
- **Proteins are explicit categories.** `IngredientCategory` separates red meat, white meat, cured
  meat, fish, seafood, egg, legume and cheese, so the "no same protein on adjacent days" rule can
  be checked from data.
- **Kitchen tools that heat the kitchen** (`KitchenTool.heats_kitchen`) are what "avoid the oven in
  summer" is computed from.

### Languages

The interface is multilingual: **Italian by default**, English available (decided 2026-10-05).

- Frontend: i18next (`frontend/src/i18n/`), one JSON file per language under `locales/`. The
  language comes from the user's last choice, then the browser, then Italian. Every visible string
  goes through `t()`; enum values from the API (categories, seasons, outcomes) are translated in
  the frontend from their stable codes.
- Backend: `LANGUAGES = it, en`, `LocaleMiddleware`, and choice labels wrapped in `gettext_lazy`.
  The SPA sends `Accept-Language`, so DRF error messages follow the interface language. Admin
  translation files (`backend/locale/`) need GNU gettext (`brew install gettext`) to generate
  with `makemessages -l it` and are not created yet.
- Code, identifiers and stored codes stay in English. Recipe content (titles, instructions) is
  data and stays in whatever language it was written in.

### Provenance: the user has the final say

Models carrying LLM-suggested or derived properties inherit `ProvenanceMixin`
(`apps/core/provenance.py`): a JSON map `field -> "llm" | "derived" | "user"`.

- Automatic code sets values only through `obj.propose(field, value, Source.LLM | Source.DERIVED)`,
  which refuses to overwrite a field whose source is `user`.
- Every write through the REST API is a user decision: `UserDecisionSerializerMixin` marks the
  fields listed in a serializer's `Meta.tracked_fields` as `user`.

Never assign a tracked field directly from LLM output; always go through `propose`.

### Multi-family access

A user sees only families they hold a `Membership` in. Viewsets over family-owned data use
`FamilyScopedMixin` (`apps/families/permissions.py`), which filters querysets and rejects writes
pointing at somebody else's family. Global catalogs (ingredients, tools, cuisines, recipes) are
readable and writable by any authenticated user for now.

## AI integration (`backend/ai/`)

Application code depends only on the protocols in `ai/base.py` and on `get_chat_provider()` and
`get_embedding_provider()`. The concrete provider is chosen by environment variables
(`LLM_*`, `EMBEDDINGS_*`, see `.env.example`) through the registries in `ai/factory.py`.

| Provider key | Class | Use |
|---|---|---|
| `openai_compatible` (chat) | `OpenAICompatibleChat` | Any OpenAI-compatible server: llama.cpp, vLLM, Ollama, cloud |
| `unsloth_studio` (chat) | `StudioChat` | Same, plus Studio's `enable_thinking`/`enable_tools` flags and model-loaded checks |
| `openai_compatible` (embeddings) | `OpenAICompatibleEmbeddings` | `services/embeddings`, Studio's `/v1/embeddings`, cloud APIs |

To add a provider: implement the protocol, register it in `ai/factory.py`. Nothing else changes.

### Unsloth Studio

Behaviour verified in the sibling project `../spyone` (Studio 2026.9.2) and carried over:

- Base URL `http://127.0.0.1:8888`; bearer API key from Settings → API keys (`LLM_API_KEY`).
- `{"detail": "Not authenticated"}` means a missing or expired key; 503 means no model loaded.
- Studio serves only the currently loaded chat model, unless **Settings → API → "Switch model by
  request"** is on. `StudioChat.ensure_model_available()` checks this upfront and gives a clear
  error instead of Studio's bare 404.
- Default chat model: `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` (MoE, 3B active), the same one spyone
  uses. `unsloth/gemma-4-E2B-it-GGUF` is the light alternative for fast iteration.
- From inside Docker, Studio is reached at `host.docker.internal:8888` (set in `docker-compose.yml`).

Verified live on 2026-10-05 against this project's adapter:

- **Function calling works**: passing OpenAI-style `tools` returns `finish_reason: "tool_calls"`
  with well-formed `tool_calls` (JSON arguments). This is what the agentic menu engine builds on.
- **`enable_tools: true` turns on Studio's own server-side web search**: the model searched,
  and the source URLs it cited resolved (HTTP 200), not hallucinated. This is the "native web
  search" recipe discovery relies on. Search results inflate the prompt (~1.9k tokens for one
  query). Keep it off for menu generation and on only for discovery.
- "Switch model by request" is on in Paolo's Studio, so a non-resident model is loaded on demand.

### Embeddings

- Default: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions,
  multilingual, light enough for a Raspberry Pi), served by `services/embeddings`. Vectors are
  L2-normalized, so cosine similarity equals the inner product.
- Embedding tables (`RecipeEmbedding`, `FamilyEmbedding`) store the **model name** with each
  vector, and the vector column has **no fixed dimension**. Swapping model means recomputing the
  rows for the new model, with no migration. The trade-off is that pgvector cannot build an ANN
  index on an undimensioned column. At recipe-book scale exact search is fast enough; add a
  dimensioned, indexed column if that ever stops being true.
- `content_hash` records which text was embedded, so stale vectors can be found after edits.

## Not built yet

Menu generation engine (agentic, RAG), recipe discovery, embedding computation jobs,
collaborative recommendation, and every frontend screen beyond the health/recipe list stub.
