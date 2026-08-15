# Localization overhaul plan

Status: draft for review (Aug 2026). Owner: Teffen. Intended executor: a Claude session per PR — each PR section below is self-contained and lands independently.

## Background and diagnosis

authentik's localization pain is three separate problems that share a vocabulary:

- **A. Product-string pipeline hygiene.** The lit-localize → Transifex → catalog pipeline works but has accumulated debt (tracked in issue #24563: duplicate xliff files, `_` vs `-` tag inconsistency, no per-interface catalogs, over-extracted backend strings). Transifex stays; it is not the problem.
- **B. Operator-authored content cannot be translated.** Flow titles, prompt labels/help text, email subjects, brand footer links. This is the source of weekly user requests (#1451 and friends). Today it "works" only by accident: e.g. `authentik/stages/email/stage.py` passes the operator's string through gettext (`subject=_(current_stage.subject)`), so operator text translates only if it happens to collide with a msgid in authentik's own catalog. Users keep trying to inject their content into the product pipeline because no other mechanism exists.
- **C. Locale resolution is split-brain.** The client resolves locale one way (`?locale=` → sessionStorage → server hint → `navigator.languages`, in `web/src/common/ui/locale/utils.ts:191`) and the server another (Django `LocaleMiddleware` cookie/Accept-Language → user attr → brand default). They disagree, producing mixed-language UI (#18179) and the flow selector translating client strings but not server-rendered challenge strings (#22954). There is also a concrete bug: `User.locale()` at `authentik/core/models.py:610` returns `request.LANGUAGE_CODE` **before** consulting the user's own `attributes.settings.locale`, so the user's saved setting is shadowed whenever LocaleMiddleware resolves anything (which is always); the method also ends with dead code referencing `request.brand.locale`, a property that does not exist (it's `default_locale`).

**Architectural decision (agreed):** locale becomes fixed for the lifetime of a page. The server is the single resolver; changing locale = persist preference (Django language cookie) + full page reload. This is the same model lit-localize transform mode mandates and Angular `@angular/localize` ships; Cloudflare's dashboard does the equivalent (per-locale catalog chunk chosen at boot, reload to switch). Full reloads are acceptable — the path-based router work means the current URL round-trips through the server losslessly.

Consequences of that one decision:

- The `setLocale`/re-render machinery and all `() => msg(...)` thunk wrappers (~114 sites) become deletable — `msg()` at module scope can never go stale.
- The #18179/#22954 bug class becomes structurally impossible.
- lit-localize **transform mode is not required** to get the wins. It's parked as an optional final track.

Key serving facts (verified):

- The HTML shells are Django `TemplateView`s rendered per request: `authentik/core/views/interface.py:54` (`InterfaceView`), templates `authentik/core/templates/if/{admin,user}.html`, `authentik/flows/templates/if/flow.html`. Script srcs come from the `versioned_script` tag (`authentik/core/templatetags/authentik_core.py:11`) which substitutes `%v` with `authentik_full_version()`; the web build mirrors it via `BuildIdentifier` (`web/packages/core/version/node.js:64`).
- The resolved Django locale already reaches the page: `authentik/core/templates/base/header_js.html` sets `window.authentik.locale = "{{ LANGUAGE_CODE }}"`, and `skeleton.html` sets `<html lang>`.
- The Rust static server (`src/server/static.rs:154`) is a path-only `ServeDir` over `web/dist/`. **No Rust changes are needed anywhere in this plan.**
- Locale catalogs are runtime chunks: `web/src/common/ui/locale/definitions.ts:33` holds literal dynamic `import("#locales/<tag>")` calls (literal so esbuild chunks them); loaded via the single `configureLocalization` call in `web/src/elements/controllers/LocaleContextController.ts:60`. Catalog chunks are content-hashed under `dist/chunks/`.
- Locale middleware order (`authentik/root/settings.py:298`): Django `LocaleMiddleware` → `ImpersonateMiddleware` (applies `request.user.locale(request)`) → `BrandMiddleware` (applies `brand.default_locale`, which is a read-only property over `attributes.settings.locale`, `authentik/brands/models.py:169`).

Related issues: #1451, #13038, #15374 (closed), #18179, #22954 (closed), #24563, PR #20821. Docs: `website/docs/developer-docs/translation` (update at the end of each track).

---

## Track C — locale correctness (do first)

Goal: one resolver (the server), one locale per page load, no flash of untranslated content. Four PRs, strictly ordered.

### C1 — fix `User.locale()` precedence

- `authentik/core/models.py:610`: return the user's `attributes.settings.locale` **first** when set; fall back to `request.LANGUAGE_CODE`; delete the dead `request.brand.locale` branch (would `AttributeError` — the property is `default_locale` and brand fallback is already handled by `BrandMiddleware`).
- Add unit tests: user attr set → wins over Accept-Language; unset → LANGUAGE_CODE; anonymous → unchanged.
- Intended precedence after this PR (given middleware order): explicit cookie/session → user setting → brand default → Accept-Language → `settings.LANGUAGE_CODE`.
- Closes the root cause of #18179. Small, standalone, backportable.

### C2 — cookie-persisted preference; switching = reload

- All client locale-change paths stop calling `setLocale` and instead persist + reload:
  - user settings save (`web/src/elements/controllers/SessionContextController.ts:82` applies `session.user.settings.locale` post-render — after this PR the save round-trips and reloads),
  - the flow-screen locale selector,
  - prompt stage (`web/src/user/user-settings/details/stages/prompt/PromptStage.ts:130`).
- Persistence mechanism: Django's language cookie (`django.conf.settings.LANGUAGE_COOKIE_NAME`), which stock `LocaleMiddleware` already reads. Setting it from JS is fine (not httpOnly by default), but prefer a tiny endpoint or reusing Django's `set_language` view if CSRF/SameSite makes JS-set awkward — implementer's choice, document it.
- Delete the `sessionStorage["authentik:locale"]` path in `web/src/common/ui/locale/utils.ts`. Keep `?locale=` as a dev/test override, but honor it **server-side** in `InterfaceView` (validate against supported locales) so server and client can never disagree.
- `autoDetectLanguage` shrinks: the server hint (`window.authentik.locale`) becomes authoritative; `navigator.languages` matters only when the server had nothing (first anonymous visit) — and even that should converge with Accept-Language, so consider trusting the hint unconditionally.
- e2e: cover "change locale in user settings → page reloads → whole UI including server-rendered strings is in the new locale" (this is the #22954 regression test).

### C3 — kill the catalog waterfall (manifest + modulepreload)

Today the catalog chunk downloads only after the entry bundle boots → flash of English. Fix:

- In `web/scripts/build-web.mjs`, enable esbuild's `metafile` and emit `dist/manifest.json` mapping locale tag → hashed catalog chunk path (the `#locales/<tag>` entries are discoverable in the metafile outputs).
- Django: a template tag reading the manifest (cache it in-process; tolerate a missing manifest by emitting nothing) that emits `<link rel="modulepreload" href="/static/dist/chunks/<hash>.js">` for the request's resolved locale. Add to `skeleton.html` next to the existing script tags. `en` needs no preload (empty stub catalog).
- Web: make first render await the catalog import (with the preload it's already in cache, so this costs ~0; it removes the visible re-render).
- Note: Cloudflare can't do this because their preference lives in localStorage, invisible to the server; our cookie + server-rendered shell is exactly what enables it.

### C4 — delete the live-switching machinery (mechanical cleanup)

- `LocaleContextController` shrinks to: resolve once at boot, load catalog, set `document.documentElement.lang`. Delete the `lang` MutationObserver (`LocaleContextController.ts:115-141`), the lit-localize event re-render plumbing, and `setLocale` from the `LocaleContext` mixin surface (`web/src/elements/mixins/locale.ts`) — keep `activeLanguageTag` as a plain value.
- Unwrap the ~114 `() => msg(...)` thunk sites (grep `=> msg(` under `web/src`). Module-scope `msg()` is now safe. Big diff, zero logic — flag it as skimmable in the PR description.
- Do this **after** C2 ships and soaks; it's the point of no return for live switching.

## Track A — pipeline hygiene (parallel with Track C, any order)

Execute #24563's checklist as independent small PRs:

1. Delete orphan/underscore-duplicate xliff files in `web/xliff/` (`de_DE.xlf` alongside `de-DE.xlf`; orphans `cy_GB`, `hr_HR`, `no_NO`, `sk_SK`, `bn_BD` have no target locale). Only the hyphenated set is read by the build — verify against `lit-localize.json` `targetLocales` before deleting.
2. Decide + document the language-tag policy (BCP-47 hyphenated as canonical; Django's underscore forms mapped at the boundary) and the supported-language policy in `website/docs/developer-docs/translation`.
3. Per-interface catalogs — rescue or supersede open PR #20821.
4. Trim backend gettext usage that never reaches UI (`help_text`, `verbose_name` sweeps) so Transifex volume drops.
5. Docs note from #13038: formatting strings must not be translated.

## Track B — operator content translation (the feature; design doc first)

Goal: a supported mechanism replacing the accidental `_(operator_string)` behavior. **Write and circulate a short design doc before coding — this is API surface.**

Proposed shape (starting point for the doc):

- **Model:** a per-brand custom-translation overlay — rows of `(locale, source_string) → translated_string` (brand FK nullable for instance-wide entries; sort out tenant scoping with `django-tenants` in the doc). Managed objects → blueprint-able, which is exactly what #1451 asked for ("upload of custom translation files").
- **Application point:** a lookup helper `translate_content(request, s)` used at render time inside the existing `translation.override` context established by the middleware chain; overlay hit → translated, miss → raw string (never gettext on operator content anymore — that's the #15374-adjacent footgun).
- **Wire-up, one PR per field** (each tiny, each shippable):
  1. email stage subject (replaces the existing `_()` call — strictly a correctness improvement),
  2. flow title,
  3. prompt label / help text / placeholder,
  4. brand footer links / branding strings.
- **Why this shape:** flow content reaches the browser inside challenge JSON rendered server-side where locale is already resolved — the web UI needs no changes for flows. The alternative (per-field `{locale: text}` JSON columns) is more explicit but means migrations + bespoke admin UI per field across flows/stages/prompts/brands; the overlay is one model, one admin page, and covers future fields for free. Revisit only if UX demands per-field editing.
- **Admin UI + docs last**, after the mechanism is proven on email subjects.
- Custom content translations never go to Transifex — that's the boundary that un-sticks it.

## Track D — parked: lit-localize transform mode / per-locale bundles

Not scheduled. After C4, this would be a pure build change (no behavioral delta), so it can be evaluated on measured numbers. Notes for whoever picks it up:

- lit-localize's official transform integration is Rollup-only (`localeTransformers()` from `@lit/localize-tools/lib/rollup.js`). For esbuild, wrap the same transformer factories in an `onLoad` plugin: build one `ts.Program` over the project (the transformer needs the type checker), reuse it across N esbuild builds (one per locale), transform only files importing `@lit/localize`, print with `ts.Printer`. Precedent for in-memory config overrides: `web/scripts/pseudolocalize.mjs` already instantiates `TransformLitLocalizer`.
- Output: locale-suffixed entry names (`AdminInterface.de-DE-%v.js`, `versioned_script` grows `%l`), one **shared** `dist/chunks/` so byte-identical (untranslated) chunks dedupe by content hash; clean dist once, not per locale (`cleanDistDirectory()` currently wipes per invocation). Mind the `//go:embed` no-`_`-path-segment caveat noted at `web/scripts/build-web.mjs:92`, and Docker image size (`web/static.go` embeds `dist/*`).
- Wireit: `build.files` excludes `!src/locales/*.ts` — inverts under transform mode (xliff becomes a build input).
- Dev/watch builds stay single-locale (`en`).
- Evidence it may never be needed: Cloudflare's dashboard ships runtime lookup (Polyglot-style `%{var}` interpolation) with per-locale catalog chunks and is fine.

## Acceptance criteria for the overall effort

- A user's saved locale is respected everywhere, always (no mixed-language UI) — #18179 stays closed.
- Locale switch anywhere in the product = one reload, landing on the same route, fully translated including server-rendered flow strings.
- No flash of untranslated content on any interface (verify on a throttled connection).
- An admin can translate: email subject, flow title, prompt label/help text, footer links — per locale, via UI or blueprint — without touching Transifex or authentik's catalogs. #1451 closes.
- `web/xliff/` contains exactly one file per supported locale; the supported-language policy is documented.
