# Architecture

How the concepts in `README.md` map onto code. Read this before changing the data model or the AI
integration.

## Components

```
 browser ──► frontend (nginx: SPA + reverse proxy) ──► backend (Django + DRF) ──► PostgreSQL + pgvector
    │                                                     │
    └── /auth (same origin) ──► Keycloak ◄── OIDC ────────┤
                                                          ├──► generative LLM   (OpenAI-compatible; Unsloth Studio on the host)
                                                          └──► embedding model  (OpenAI-compatible; services/embeddings by default)
```

| Directory | What | Runs as |
|---|---|---|
| `backend/` | Django project `config`, domain apps in `apps/`, AI adapters in `ai/` | `backend` container, or `uv run` natively |
| `frontend/` | React + TypeScript SPA (Vite) | `frontend` container (nginx), or `npm run dev` |
| `services/embeddings/` | OpenAI-compatible `/v1/embeddings` around sentence-transformers | `embeddings` container (compose profile), or `uv run uvicorn` |
| `keycloak/` | Keycloak image: login theme `mymenu` + Apple provider extension, served under `/auth` | `keycloak` container; realm configured by `keycloak-setup` |

The frontend and backend always share one origin (Vite proxy in development, nginx in
production), so the API uses Django session auth and CSRF without CORS. Both proxies must keep
the original `Host` header: Django builds the OIDC callback URL from it.

**Authentication** is Keycloak (email/password, Google, Microsoft, Apple) with Django as OIDC
client, and access is invitation-only. Full design and setup: `docs/authentication.md`.

## Domain apps

| App | Models | Notes |
|---|---|---|
| `catalog` | `Ingredient`, `KitchenTool` | Global, shared by every family. Ingredient names are normalized on save (lowercase, single spaces); variants go in `aliases`. |
| `recipes` | `Cuisine`, `Recipe`, `RecipeIngredient`, `RecipeEmbedding` | Recipes live in one common pool; quantities refer to `Recipe.servings` and scale linearly. The method is `Recipe.steps`, one entry per step. |
| `families` | `Family`, `Membership`, `FamilyMember`, `Preference`, `RecipeBookEntry`, `FamilyEmbedding` | Everything family-specific. `RecipeBookEntry` is the per-family view of a recipe: candidate / approved / rejected, plus the explicit rating. |
| `menus` | `WeeklyMenu`, `MealSlot`, `SlotDish` | 7 days × {lunch, dinner}. Shopping list in `menus/shopping.py`, computed, never stored. |
| `accounts` | `OIDCIdentity`, `Invitation` | OIDC backend and login view (`oidc.py`), Keycloak realm setup (`keycloak_admin.py`), `/api/me/`, invitations. |
| `assistant` | `AssistantSession` | The recipe assistant: conversation turns (`agent.py`), the recipe draft shape shared by every mode (`draft.py`). |
| `core` | none (abstract mixins and helpers) | Seasonality and provenance helpers, shared serializer mixin. |

### Decisions worth knowing

- **Shared recipes, per-family recipe book** (confirmed by Paolo 2026-10-05). One `Recipe` row can be in many families' books.
  A recipe has an **owner family** (the one that created it, the only one that can edit it;
  staff can edit everything) and a **visibility**: `shared` (default, decided 2026-10-06) or
  `private` (only the owner family sees it). `Recipe.objects.visible_to(user)` and
  `editable_by(user)` hold these rules. Creating a recipe through the API puts it in the
  creating family's book. Other families add a shared recipe to their own book; the owner can
  delete a recipe only while no other family keeps it. Removing a private recipe from the
  owner's book deletes it.
- **Shared catalogs** (ingredients, cuisines, kitchen tools): any user may read and add
  entries, only staff may change or delete them (`CatalogPermission`), because an edit would
  silently change other families' recipes. Ingredient search matches names and aliases.
  Ingredients and kitchen tools can be added from the recipe editor (no admin needed). The
  kitchen tools the app ships with carry a stable `code` and are shown translated
  (`tool.<code>` in the frontend locales); tools added by users have no code and are shown by
  the name they were given. Tool names are unique regardless of case.
- **Seeded ingredient catalog** (`catalog/migrations/0005_seed_common_ingredients.py`): about 160
  common ingredients in Italian (the first deployment's language) with category, unit, Italian
  seasonality and plural aliases. Idempotent and non-destructive: an entry is skipped when an
  ingredient already exists under its name or one of its aliases. Unlike shipped kitchen tools
  they have no code: ingredient names are data, matched by the assistant in the family's
  language. Database tests start from an empty catalog (`tests/conftest.py`); tests about the
  seed are marked `seeded`.
- **Preserved forms are distinct ingredients** with no season ("pomodoro pelato", "passata di
  pomodoro", "pisello surgelato", "tonno in scatola"): folding them into the fresh product would
  make a winter sauce of peeled tomatoes "in season" only in summer. The assistant's prompts say
  so, and `normalize_draft` forces an all-year season on names that denote a preserved product,
  because the model kept proposing the fresh product's season anyway.
- **Management section** (frontend `/manage`, staff only, from the user menu): one page per
  shared catalog, starting with ingredients: search, category filter, sorting by usage, editing
  (name, aliases, category, unit, season), deleting unused ones, and merging duplicates
  (`catalog/services.py`: recipe lines and preferences move to the target, same-unit quantities
  are added up when a recipe had both, the duplicate's name becomes an alias). Changing an
  ingredient's season re-derives the season of the recipes using it (unless the user set it)
  and refreshes their embeddings.
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
  `{"seasons": [...]}` or `{"months": [...]}` on write, or `{"auto": true}` to hand the value back
  to automatic derivation. A recipe has two levels:
  `season_months` (derived bottom-up via `Recipe.derive_season_months`, the intersection of its
  non-optional ingredients' months, or their union when they do not overlap; recomputed on every
  save until the user sets it) and `climate_months` (whether the dish suits the weather).
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

A user sees only families they hold a `Membership` in, and gets one only by accepting an
invitation (or by staff creating the family for them). Viewsets over family-owned data use
`FamilyScopedMixin` (`apps/families/permissions.py`), which filters querysets and rejects writes
pointing at somebody else's family. Global catalogs (ingredients, tools, cuisines, recipes) are
readable and writable by any authenticated user for now.

## Adding recipes (decided with Paolo 2026-10-06)

Built so far: MUI theme, recipe book (search, course filter, "in season" badge, ratings),
recipe page (scaling by number of people, rating, add/remove from book), the recipe editor, the
"+" FAB menu and the assistant in all four modes: "tell me", "help me search", "give me a link"
and "photo". A mode is enabled (`AVAILABLE_MODES` in `apps/assistant/models.py`) only once its
tools exist: offering a
mode before its tools exist would let the LLM invent the content of pages or photos.

**How the assistant works**

- An `AssistantSession` (family, user, mode) stores the exchange in OpenAI chat format, so a
  draft survives a page reload; only its author sees it.
- Each turn (`apps/assistant/agent.py`) sends a mode-specific system prompt plus the history and
  one tool, `propose_recipe`, whose parameters are the draft schema (`draft.py`). The model
  either asks a short question or calls the tool with the **whole** draft; after each correction
  it calls it again, so the latest call is the current draft. Tool calls and their results stay
  paired in the history. The history is trimmed at user turns to fit the 8k context; when it
  is, the current draft is re-sent as a system note.
- Drafts are normalized (`normalize_draft`): units mapped (kg -> g, "q.b." -> to taste),
  unknown categories/courses fall back to safe values. Measured live 2026-10-06 with
  Qwen3.6-35B-A3B: first draft in 7-16 s, a correction in about 4 s.
- Draft ingredients are matched to the catalog (`apps/catalog/matching.py`): exact name or
  alias, otherwise PostgreSQL trigram similarity (`pg_trgm`), preselecting a candidate from
  0.45 similarity ("pomodori" -> "pomodoro") and flagging it for the user to check.
- "Review and save" opens the editor with `?session=<id>`: matched ingredients are filled in,
  unknown ones must be created (category, unit and season prefilled from the draft) or replaced
  before saving. Saving links the recipe to the session and closes it.
- Gunicorn runs threaded workers so a turn waiting on the LLM does not block other requests.

**Link import** (`apps/assistant/web.py`, built 2026-10-06)

- A message containing a URL, in "tell me" or "link" mode, imports the page instead of asking
  the chat model. One page, the one given, fetched once; no crawling.
- **Only public addresses are fetched**: every redirect hop is checked, and every address the
  host resolves to must be global. `keycloak:8080`, `db`, `host.docker.internal`, LAN and
  loopback addresses are refused (verified from inside the backend container). The page is
  capped at 3 MB and must be HTML. A DNS answer changing between check and connection is not
  covered; acceptable for a family app, revisit before exposing the app widely.
- Text for the model: schema.org `Recipe` data when present, else the visible text with block
  elements split into lines (minified pages are one line otherwise) and cut to a ~9k-character
  window around where quantities cluster.
- A separate extraction call (`response_format` with the draft schema, temperature 0) structures
  the text. Ingredient names are always in the user's language, generic and singular, so they
  match the family catalog (an English page still yields "uovo", "parmigiano"); title,
  description and steps stay in the page's language. Cups, ounces and spoons become g/ml with
  the original measure in the note.
- From structured data, title (site name stripped), servings, times and steps are kept
  verbatim rather than as the model rewrote them; GialloZafferano-style photo numbers in steps
  ("padella antiaderente 4 e") are removed when they form a 1, 2, 3, ... sequence.
- The result is recorded in the history as a `propose_recipe` call, so corrections ("for 2
  people") work as in "tell me"; the source URL survives corrections.
- Failures carry a stable code (`unreachable`, `http_error`, `no_content`, `no_recipe`, ...)
  that the UI translates; the code is stripped from what is sent back to the model.
- Measured live: 9-16 s per import on GialloZafferano, Il Cucchiaio, BBC Good Food, Acadèmia and
  a small blog.

**Photo import** (built 2026-10-06)

- The camera button next to the message box works in every mode (in "photo" mode it is the
  main action); on phones it opens the back camera. The browser downscales to 1280 px JPEG before
  upload (`frontend/src/images.ts`): a 3300x4200 photo became 73 KB, about 1,500 tokens for the
  vision model. The backend accepts only JPEG/PNG/WebP, checked by their bytes, up to 10 MB
  (nginx allows 12 MB).
- Photos are stored in the database (`Attachment`), so they are in the backups, are shown beside
  the draft in the review screen, and are visible only to the conversation's author.
- Two steps, as decided: a strictly literal transcription by the vision model (`LLM_VISION_MODEL`,
  default the chat model), then the same structuring as link import. Compared on synthetic
  cookbook pages and handwritten cards (2026-10-06): with the literal prompt Qwen3.6 transcribed
  faithfully (one inflection wrong), gemma-4-E2B misread words, invented one and reordered a
  paragraph. The review screen shows each photo with the text read from it.
- All photos of a conversation are read together, so a recipe spanning pages is sent as several
  photos. Untested on real photos (blur, real handwriting).
- Measured live: 10-25 s per photo.

**Help me search** (`apps/assistant/search.py`, built 2026-10-06)

- Each message in search mode is a search; earlier messages of the conversation are added as
  context, so "with potatoes" refines the previous request. Picking a web result sends its URL:
  the conversation becomes a link import (mode switches to `link`), and later messages correct
  the draft.
- **Local**: keyword matches first (every meaningful word, roughly stemmed, must appear in the
  title or an ingredient: matching any word turned "un dolce al cioccolato" into a leek soup via
  its "paprika dolce"), then embedding similarity from 0.4. Shown as "in your recipe book" or
  "from other families" (shared recipes only; private ones never leave their family).
- **Web**: the chat model first turns the request into 3 concrete dishes (about 1 s; vague
  requests otherwise find only category and collection pages), then runs one web search per
  dish through Unsloth Studio's built-in search, two at a time. A result is shown only if its
  page exists, is public, and declares exactly one schema.org Recipe with ingredients and method;
  its title is the page's own. Measured: 22-29 s, 4-6 results.
- What was learned on the way (2026-10-06): asked for JSON, the model invented every URL without
  searching; left free, it chained searches for 90-110 s and nearly filled the context; Studio's
  search tool fails intermittently (the model then answers without links: retried once) and can
  hang up to its 300 s default (capped at 15 s per call).
- **Studio's server-side tools are restricted to `web_search`** (`ai/studio.py`, `SAFE_TOOLS`):
  for local models Studio also offers `python`, `terminal` and `edit_file`, which run on the
  host, and search prompts carry user text. Tool calls per message are capped too.


- **UI library**: MUI (Material UI) with the app's own theme (colours as in `frontend/src/index.css`).
  Material 3's guidance is followed where MUI allows (e.g. labelled FAB menu items).
- **Entry point**: a "+" FAB on the recipe book. **Tap/click always opens the menu** (hover may
  open it early on desktop), with labels always visible, so it behaves the same on touch:
  1. "Tell me the recipe" (first, highlighted): the user describes it, the LLM builds
     ingredients and steps, asking questions only when something essential is missing;
  2. "Help me search": guided search, local recipes first, then the web (Studio's built-in
     search);
  3. "Give me a link": import from a recipe page;
  4. "Upload or take a photo": a cookbook page, a handwritten card, a screenshot.
- **One assistant, three entry points**: the menu items open the same conversational panel in a
  given mode; the LLM still recognizes a pasted link or a search request in any mode.
- **Every path ends in the same draft review** (which doubles as manual entry): everything the
  LLM proposed is editable and marked as suggested (provenance) until the user saves.
  Ingredients are matched to the catalog, or proposed as new with suggested category/season/unit.
- **Visibility**: recipes are **shared by default** with other families (the collaborative
  recommendation needs a common pool); a family can mark a recipe private.

**Link import** (no crawling, no per-site scrapers; it reads only the page the user gave):

1. schema.org `Recipe` JSON-LD in the page, parsed without any LLM. Checked 2026-10-06: present on
   GialloZafferano, La Cucina Italiana, BBC Good Food, Acadèmia; absent on Il Cucchiaio and on a
   small blog.
2. Otherwise, LLM extraction from the page's visible text into the recipe JSON schema
   (`response_format`). Generic "main content" extractors are not enough: trafilatura dropped Il
   Cucchiaio's ingredient box, losing every quantity. What worked: all visible text, cut to a
   window around where quantities ("320 g", "50 ml") cluster, ~9k characters to fit the context.
   Both pages extracted correctly in 3-6 s.
3. Pages that cannot be read this way (rendered by JavaScript, bot-protected, social/video posts)
   fall back to asking the user to paste the text or take a screenshot (photo mode).

**Photo mode**: a vision-capable model reads the image. Checked 2026-10-06 with a synthetic
handwritten card: both `Qwen3.6-35B-A3B` and `gemma-4-E2B` read it in ~5 s, but Qwen, asked to
"transcribe", **embellished the method with steps not on the card**. So photo import is two
steps: a strictly literal transcription prompt ("only what is written, nothing added"), then the
same structuring as link import, and the review screen shows the source image beside the draft.
Real photos (blur, real handwriting, two-column cookbook pages) are untested.

**Context size**: Studio currently loads the chat model with an 8,192-token context (the model
supports 262k). Page text, images and conversations all count against it; raise it in Studio
when loading the model if long pages or conversations get truncated.

**Build order**: 1. MUI, recipe book, draft review / manual entry; 2. FAB and assistant panel;
3. link import; 4. photo import (reuses link import's structuring); 5. "Tell me the recipe";
6. "Help me search" (needs recipe embeddings first).



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
- Recipes are embedded (`apps/recipes/embeddings.py`) from a short document: title, course,
  cuisine, ingredient names, description, the start of the method. On every save, after the
  transaction and best effort (a down embedding service never blocks a save); the one-shot
  `embed-recipes` compose service (`manage.py embed_recipes`, idempotent) catches up on every
  `up`. The embedding service is part of the default stack, with a readiness check that passes
  once the model is loaded.

## Not built yet

Menu generation engine (agentic, RAG), recipe discovery, embedding computation jobs,
collaborative recommendation, a UI for creating invitations, streaming replies, weekly menus
and the shopping list UI.
