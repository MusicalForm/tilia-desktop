# LCMA Validation Pane — Implementation Plan

Item 4 of `docs/lcma-pane-todo.md`: **"Validierungspane von Annotation-UI übertragen"** —
bring the annotation-ui session-wide validation ("Problems") pane into TiLiA's LCMA UI.

Target branch: `feat/lcma-pane-layout` (this worktree). Split to `feat/lcma-validation-pane`
if PR isolation is wanted.

## Status (2026-07-08)

- **Phase 0 done** — annotation-ui headless validator bundle committed on `dev` (`019f712`).
- **Phase 1 done** — `validator.html` + `SOURCE.txt` vendored to `tilia/ui/timelines/lcma/validator/`;
  `sync_lcma_assets.py`, pyproject `package-data`, and `test_vendored_assets.py` extended. Vendored
  **validator only** (embed.html stays at `105f170`): verified format-compatible — `fromJsonLd` parses
  structurally and never reads `@context`, so validator@`019f712` reads builder@`105f170` output. The
  builder bundle is left untouched to keep the diff focused.
- **Phase 2 done** — `session_io.get_session_annotations()` + `test_session_io.py` (green).
- **Note:** the builder dock already implements pane-todos **1 / 2 / 3 / 5** (left-docked, eager on
  timeline create via `timeline.py`, not user-hideable through `registers_in_view_menu = False`,
  Enter-focus via `focus_editor`) — see `builder_dock.py` + `test_pane_layout.py`. So the validation
  dock **mirrors `builder_dock.py`**, and item 4 is now purely the dock's validation content + wiring.
- **Next: Phase 3** — `validation_dock.py`. (19 targeted tests green so far.)

## Decision: Hybrid (native Qt UI + reused JS engine)

The pane has two layers; decide per layer, not wholesale:

- **Engine** (`diagnose()` + JSON-LD parse + model): a native Python reimplementation would
  duplicate **~1,700–1,800 LOC** of TypeScript (`diagnostics.ts` 369, `jsonld.ts` 465,
  `attributes.ts` 304, `functionOps.ts` 213, `vocab.ts` 156, `attributeVocab.ts` 115,
  `types.ts` 94). That closure is **actively churning**: `diagnostics.ts` touched 7×,
  `jsonld.ts` 8× in the last 90 days, both last changed 2026-07-03; ~50 commits/30 days in
  annotation-ui. A Python copy would drift immediately and carry a permanent sync tax.
  → **Reuse the TS unchanged.**
- **UI** (the Problems list, `ValidationPane.tsx` ~65 lines): a native Qt `QTreeWidget` is
  simpler than a second React embed + second visible webview + a second vendoring entry, and
  fits the other pane todos (left-docked, always visible, native look).
  → **Build native.**

So: **native Qt dock, diagnostics computed by the existing vendored JS run headlessly.**

Rejected alternatives:
- *Full native port* — large one-time port of churning logic + permanent drift. Revisit only
  if the lint stabilizes.
- *Full embed port* (ValidationPane.tsx + diagnose() in a 2nd visible webview) — saves the
  ~65 Qt lines but costs a 2nd interactive Chromium view, 2nd vite config, vendoring entry,
  and a JS→Py select bridge. Worse fit for a native, always-visible left pane.

## Confirmed design decisions

1. **Scope = one LCMA timeline.** References resolve within a single unit set. With multiple
   LCMA timelines the dock follows the focused one; **v1 binds to the first/only** LCMA timeline.
2. **Dedicated invisible `QWebEnginePage`** for the engine (not the builder's page) — validation
   stays live even when the builder dock is closed. Cost: a 2nd page. A shared "JS-services"
   singleton page is noted as a later optimization. No app-global event filter on the new page
   (QtWebEngine segfault history — see `builder_dock` file-drop mitigation).
3. **Clicking a diagnostic also loads that unit into the builder** — intended; mirrors
   annotation-ui `onSelect`, which loads the row into the entry bar.

## Architecture / data flow

```
LcmaTimeline (backend)                     ValidationDock (native, Qt)
   │  N × LcmaForm.annotation_data (JSON-LD)      │
   │                                              ├─ QTreeWidget (errors ▸ warnings)
   ▼                                              │     ▲ row click
session_io.get_session_annotations(tl_id)         │     │
   → [(cmp_id, jsonld), …]  (stable order)        │  select_element(unit) ─ on_select ─▶ Builder loads unit
   │                                              │
   ▼   runJavaScript(diagnoseSession(arr), cb)    │
[invisible QWebEnginePage: validator.html] ───────┘
   window.diagnoseSession(jsonld[]) → Diagnostic[] (JSON)
   = diagnose(arr.map(fromJsonLd))   ← unchanged, reused TS
```

`Diagnostic` shape (from `annotation-ui/src/model/diagnostics.ts`):
`{ index, name, severity: "error"|"warning", code, message }`. `index` = position in the array
passed to `diagnoseSession`, which Python builds in the same stable order it maps back from.

Refresh triggers: `Post.TIMELINE_COMPONENT_CREATED / _DELETED / _SET_DATA_DONE`
(`tilia/requests/post.py:66-70`), filtered to the bound LCMA timeline, ~150 ms debounce.

## Part A — annotation-ui (headless engine bundle)

Reuse `diagnose()` + `fromJsonLd` without React. In `~/lcma-annotation-ui`:

1. **`src/validator.ts`** (~6 lines):
   ```ts
   import { diagnose } from "./model/diagnostics";
   import { fromJsonLd } from "./model/jsonld";
   (window as any).diagnoseSession = (arr: string[]): string =>
     JSON.stringify(diagnose(arr.map((s) => (s && s.trim() ? fromJsonLd(s) : { forms: [] }))));
   ```
2. **`validator.html`** — entry loading only `src/validator.ts` (no `#root`, no DOM).
3. **`vite.config.validator.ts`** — like `vite.config.embed.ts` but input `validator.html`
   → `dist-validator/validator.html` (separate outDir so it never clobbers the embed build;
   `viteSingleFile` inlines everything).
4. **`package.json`**: `"build:validator": "vite build -c vite.config.validator.ts"`.

Verify before vendoring: open `validator.html` in a browser, call
`diagnoseSession(['…jsonld…'])` in the console → confirms the engine runs standalone.

## Part B — TiLiA (Python)

Template throughout: `tilia/ui/timelines/lcma/builder_dock.py` (same patterns — get-or-create
via a `Get` member, `serve`, `ViewDockWidget`, `runJavaScript`).

1. **`tilia/requests/get.py`** — add `LCMA_VALIDATION = auto()` (next to `LCMA_BUILDER`, line 52).
2. **`tilia/ui/timelines/lcma/session_io.py`** (new, Qt-free → unit-testable):
   ```python
   def get_session_annotations(timeline_id: int) -> list[tuple[int, str]]:
       # Get.TIMELINE(tl_id) → sorted(components) (ORDERING_ATTRS from Hierarchy)
       # → [(cmp.id, cmp.annotation_data), …]. List index i ≙ Diagnostic.index.
   ```
3. **`tilia/ui/timelines/lcma/validator/validator.html`** (new, vendored) + `SOURCE.txt`
   (provenance, like the builder bundle).
4. **`tilia/ui/timelines/lcma/validation_dock.py`** (new) — core:
   - invisible `QWebEnginePage` loading `validator.html`; on `loadFinished`, drain a compute
     queue (analogous to the builder's `_bridge_ready` / `_pending`).
   - `QTreeWidget`: columns *severity icon · #i name · message*; errors first (JS already
     sorts). Empty state: "clean" badge + reassuring line (mirrors `ValidationPane.tsx`).
   - `_recompute()`: `session_io` → `page.runJavaScript("diagnoseSession(%s)" % json.dumps(arr),
     self._on_diagnostics)`; callback parses JSON → fills the tree. Debounce with
     `QTimer.singleShot`.
   - `listen(...)` on the 3 lifecycle Posts, filtered to the bound LCMA timeline.
   - row click → `Get.TIMELINE_UI_ELEMENT(tl_id, cmp_id)` → `timeline_ui.deselect_all_elements()`
     + `select_element(el)` (`tilia/ui/timelines/base/timeline.py:446`). Selection runs through
     `on_select` → also loads the unit into the builder. Scroll-to is optional (v2).
   - `serve(self, Get.LCMA_VALIDATION, lambda: self)`; `get_or_create_validation_dock()`.
   - `addDockWidget(LeftDockWidgetArea, …)` (todo item 3: left).
5. **Creation / visibility** (todo item 1: always visible): create the dock when an LCMA
   timeline UI is created (get-or-create), not lazily on selection like the builder. Hook:
   the LCMA timeline-UI constructor / setup. v1 binds to the first LCMA timeline (decision 1).

Key anchors (this worktree):
- `tilia/ui/timelines/lcma/builder_dock.py` — dock template (Get/serve/get-or-create/webchannel).
- `tilia/ui/windows/view_window.py:54` — `ViewDockWidget` base (`menu_title`, `showEvent`
  registers in the Window menu, `DockWidgetMovable`).
- `tilia/ui/timelines/lcma/element.py:202` — `on_select` → `get_or_create_builder_dock().load_annotation(...)`.
- `tilia/timelines/lcma/components.py:43` — `LcmaForm.annotation_data`; `SERIALIZABLE` includes it (line 24).
- `tilia/ui/timelines/base/timeline.py:446` — `select_element`; `475` `deselect_all_elements`.

## Part C — vendoring

Extend `scripts/sync_lcma_assets.py` to vendor `validator.html` (from `dist-validator/`) as a
2nd artifact beside `embed.html` (from `dist-embed/`; same `--source ~/lcma-annotation-ui`). Build gotcha: `py` is absent on macOS, so
`--build` is broken — build manually then sync without `--build`:
1. `cd ~/lcma-annotation-ui && npm run build:embed && npm run build:validator`
2. `python3 ontology/scripts/generate_artifacts.py --profile full --out src/generated`
3. `cd tilia-lcma && uv run python scripts/sync_lcma_assets.py --source ~/lcma-annotation-ui` then `--check`

`--check` should also report `validator/SOURCE.txt`. Never commit a bundle stamped `dirty: true`.

## Part D — tests (per TESTING.md; gold reference = marker test file)

`tests/ui/timelines/lcma/test_validation_dock.py`:
- **`session_io`** pure test (no webview): create units with known `annotation_data` →
  assert order + index mapping.
- **dock with mocked JS**: patch `runJavaScript` to yield known `Diagnostic[]` JSON → assert
  `QTreeWidget` rows (order, icon, text) and the empty/clean state.
- **click → selection**: click a row → correct `LcmaForm` selected (`Get.TIMELINE_ELEMENTS_SELECTED`).
- **refresh**: create/delete/edit a unit via `commands.execute(...)` → `_recompute` fires
  (mocked engine).
- `diagnose()` itself is covered by the annotation-ui suite, **not** TiLiA's.

## Order

Phase 0 validator bundle (A) → 1 vendoring (C) → 2 `session_io` (pure + test) →
3 dock static (loads + shows, no refresh) → 4 refresh wiring → 5 click→select →
6 always-visible/left → 7 remaining tests.

**Effort**: medium-large, ~1–2 days. Biggest unknown: async `runJavaScript` marshalling +
page lifecycle (phase 3).

## Open items / risks

- Async result marshalling: `runJavaScript` returns via callback; queue computes until
  `loadFinished`, debounce rapid edits, coalesce in-flight recomputes.
- 2nd `QWebEnginePage` adds webview surface — keep the file-drop / event-filter mitigation from
  `builder_dock`; no app-global filter on the new page.
- Multiple LCMA timelines: v1 binds to the first; "follow focused timeline" is a later step.
