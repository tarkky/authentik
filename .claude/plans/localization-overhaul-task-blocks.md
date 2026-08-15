# Localization overhaul — queued task blocks

Each block below is a self-contained prompt for a fresh Claude session. Run them **one per session**.
Ordering: **C1 (done) → C2 → C3 → C4**, each merged before starting the next. **A1 is independent** and can run anytime.

Every block keeps the same guard rails as C1: read the plan first, execute exactly one PR, respect the out-of-scope fence. The fences differ per task — C1 forbade touching `web/`, but C2/C3/C4 *live* in `web/`, so read each block's fence carefully.

---

## C2 — save language in a cookie, reload to switch

Read `.claude/plans/localization-overhaul.md` in full before doing anything. It's a reviewed plan for
overhauling localization; you are executing exactly ONE PR from it, not the whole plan. The file paths
and line references in the Background section were verified recently — trust them, don't re-derive the
architecture. Depends on C1 (`User.locale()` precedence fix) already being merged — confirm it's on main
before starting.

Your task: Track C, PR C2 — persist the locale preference in a cookie and switch by reloading, instead
of switching live in JavaScript.

Scope, precisely:
- Every client path that changes locale must stop calling `setLocale` and instead persist the choice +
  full page reload:
  - user settings save — `web/src/elements/controllers/SessionContextController.ts:82` (currently applies
    `session.user.settings.locale` after render; it should round-trip and reload),
  - the flow-screen locale selector,
  - the prompt stage — `web/src/user/user-settings/details/stages/prompt/PromptStage.ts:130`.
- Persistence mechanism: Django's language cookie (`django.conf.settings.LANGUAGE_COOKIE_NAME`), which the
  stock `LocaleMiddleware` already reads. Setting it from JS is acceptable (not httpOnly by default);
  if CSRF/SameSite makes JS-set awkward, prefer a tiny endpoint or reuse Django's `set_language` view.
  Implementer's choice — document whichever you pick in the PR description.
- Delete the `sessionStorage["authentik:locale"]` path in `web/src/common/ui/locale/utils.ts`.
- Keep `?locale=` as a dev/test override, but honor it SERVER-SIDE in `InterfaceView`
  (`authentik/core/views/interface.py`), validating against the supported-locale list, so the server and
  client can never disagree.
- Shrink `autoDetectLanguage`: the server hint (`window.authentik.locale`) becomes authoritative;
  `navigator.languages` matters only on a first anonymous visit when the server had nothing.
- e2e test (this is the #22954 regression guard): change locale in user settings → the page reloads →
  the whole UI, INCLUDING server-rendered flow/challenge strings, is in the new locale.

Out of scope — do NOT touch: Track A/B/D work, the C3 catalog-preload machinery, the C4 thunk-unwrapping
(`() => msg(...)` sites) or the `LocaleContextController` MutationObserver. You are changing how locale is
*persisted and applied*, not deleting the live-switching machinery — that's C4. If the change seems to
want C4's deletions to work, stop and report instead of expanding scope.

Before finishing, run `make web-test` and the relevant e2e suite, plus `make test authentik/core` if you
touch `InterfaceView`, and `make lint-fix`. Branch off main. Commit message style: match recent history
for the subtree you touch (`web:` / `core:`). Do not add a Claude co-author trailer. Do not create a PR
or issue.

---

## C3 — preload the translation file so there's no flash of English

Read `.claude/plans/localization-overhaul.md` in full before doing anything. It's a reviewed plan; you are
executing exactly ONE PR from it, not the whole plan. Trust the verified file paths/line refs in the
Background section. Depends on C2 already being merged — confirm before starting.

Your task: Track C, PR C3 — eliminate the flash of untranslated (English) content by telling the browser
which locale catalog to fetch before first render.

Scope, precisely:
- In `web/scripts/build-web.mjs`, enable esbuild's `metafile` and emit `dist/manifest.json` mapping each
  locale tag → its hashed catalog chunk path. The `#locales/<tag>` entries are discoverable in the
  metafile outputs (the literal dynamic imports live in `web/src/common/ui/locale/definitions.ts:33`).
- Add a Django template tag that reads that manifest (cache it in-process; if the manifest is missing,
  emit nothing rather than erroring) and outputs
  `<link rel="modulepreload" href="/static/dist/chunks/<hash>.js">` for the request's resolved locale.
  Wire it into `authentik/flows/templates/if/skeleton.html` next to the existing script tags. `en` needs
  no preload (its catalog is an empty stub).
- On the web side, make first render await the catalog import. With the preload in place the chunk is
  already cached, so this costs ~0 — it just removes the visible re-render.

Out of scope — do NOT touch: the persistence/reload logic (that's C2, assumed merged), the C4 deletions,
or any Track A/B/D work. No Rust changes are needed anywhere. If it seems to want C4's cleanup, stop and
report.

Before finishing, run `make web` (build must succeed and produce `dist/manifest.json`), `make web-test`,
`make test authentik/flows` (or the app owning the template tag), and `make lint-fix`. Verify on a
throttled connection that there's no flash of English. Branch off main. Commit style: match the subtree
(`web:` / `core:`). No Claude co-author trailer. Do not create a PR or issue.

---

## C4 — delete the dead live-switching machinery (mechanical, huge diff)

Read `.claude/plans/localization-overhaul.md` in full before doing anything. Execute exactly ONE PR.
Trust the verified paths/line refs. Depends on C2 having shipped AND soaked — confirm with the human that
C2 has been live long enough before starting. This PR is the point of no return for live locale switching.

Your task: Track C, PR C4 — now that switching is reload-based (C2), remove the live re-render machinery.

Scope, precisely:
- Shrink `LocaleContextController` (`web/src/elements/controllers/LocaleContextController.ts`) to: resolve
  the locale once at boot, load the catalog, set `document.documentElement.lang`. Delete the `lang`
  MutationObserver (`LocaleContextController.ts:115-141`) and the lit-localize event re-render plumbing.
- Remove `setLocale` from the `LocaleContext` mixin surface (`web/src/elements/mixins/locale.ts`); keep
  `activeLanguageTag` as a plain value.
- Unwrap the ~114 `() => msg(...)` thunk sites (grep `=> msg(` under `web/src`) into plain module-scope
  `msg(...)` — safe now that locale is fixed per page load. This is a big diff with zero logic change;
  call it out as skimmable in the PR description.

Out of scope — do NOT touch: backend/Python, the C3 manifest/preload code, or Track A/B/D. This is
mechanical deletion + unwrapping only; if you find yourself changing behavior, stop and report.

Before finishing, run `make web-test`, `make web`, and `make lint-fix`. Sanity-check that the three apps
(Admin, User, Flow) still render translated. Branch off main. Commit style: `web:`. No Claude co-author
trailer. Do not create a PR or issue.

---

## A1 — delete duplicate / orphan translation files (independent)

Read `.claude/plans/localization-overhaul.md` in full before doing anything. Execute exactly ONE PR — this
is Track A item 1. Trust the verified paths. Independent of Track C; can run in any order.

Your task: Track A, PR A1 — remove translation (xliff) files in `web/xliff/` that the build does not use.

Scope, precisely:
- Delete underscore-form duplicates that sit alongside the canonical hyphenated file (e.g. `de_DE.xlf`
  next to `de-DE.xlf`), and orphan files for locales with no target locale: `cy_GB`, `hr_HR`, `no_NO`,
  `sk_SK`, `bn_BD`.
- CRITICAL: only the hyphenated set is read by the build. Before deleting anything, verify each file
  you're removing against `web/lit-localize.json`'s `targetLocales` — delete only files whose tag is NOT
  in that list. If a file you expected to delete IS listed, stop and report rather than removing it.

Out of scope — do NOT touch: any Track C work, the build scripts, `lit-localize.json` itself (you're only
reading it), or any `.ts`/`.py` source. Files-only deletion.

Before finishing, run `make web` (the build must still succeed) and `make lint-fix`. Branch off main.
Commit style: `web:`. No Claude co-author trailer. Do not create a PR or issue.
