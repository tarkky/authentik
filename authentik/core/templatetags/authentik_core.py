"""authentik core tags"""

import json
from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static as static_loader
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

from authentik import authentik_full_version

register = template.Library()


@register.simple_tag()
def versioned_script(path: str) -> str:
    """Wrapper around {% static %} tag that supports setting the version"""
    return static_loader(path.replace("%v", authentik_full_version()))


@lru_cache
def _load_locale_manifest() -> dict[str, str]:
    """Load and cache the locale catalog manifest emitted by the web build.

    The manifest maps a locale tag to its content-hashed catalog chunk (relative to
    `dist/`). A missing or malformed manifest is tolerated as "no catalogs known",
    so the interface still renders (without the preload optimization)."""
    manifest_path = finders.find("dist/manifest.json")
    if not manifest_path:
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as manifest_file:
            data = json.load(manifest_file)
    except OSError, json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_catalog_tag(manifest: dict[str, str], language_code: str | None) -> str | None:
    """Map an active Django language code to a catalog tag present in the manifest.

    Mirrors the web client's best-match: an exact (case-insensitive) tag wins, else the
    first catalog sharing the base language. The source locale (`en`) and the `en-XA`
    pseudo-locale ship no preloadable catalog."""
    if not language_code:
        return None
    normalized = language_code.lower()
    by_lower = {tag.lower(): tag for tag in manifest}
    if normalized in by_lower:
        return by_lower[normalized]
    base = normalized.split("-", 1)[0]
    if base == "en":
        return None
    for lower, original in by_lower.items():
        if lower == "en-xa":
            continue
        if lower.split("-", 1)[0] == base:
            return original
    return None


@register.simple_tag()
def locale_modulepreload() -> str:
    """Emit a `modulepreload` for the active locale's catalog chunk, when known.

    This lets the browser fetch the catalog before the entry bundle boots, removing the
    flash of untranslated content. Emits nothing for the source locale or when the build
    manifest is unavailable."""
    manifest = _load_locale_manifest()
    tag = _resolve_catalog_tag(manifest, get_language())
    if not tag:
        return ""
    href = static_loader(f"dist/{manifest[tag]}")
    # href is built from our own build manifest and the static loader, not user input.
    return mark_safe(f'<link rel="modulepreload" href="{href}">')  # nosec B308,B703
