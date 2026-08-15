"""Tests for authentik_core template tags"""

from unittest.mock import patch

from django.test import TestCase
from django.utils import translation

from authentik.core.templatetags.authentik_core import (
    _resolve_catalog_tag,
    locale_modulepreload,
)

MANIFEST = {
    "de-DE": "chunks/de.abc123.js",
    "fr-FR": "chunks/fr.def456.js",
    "zh-Hans": "chunks/zhs.789.js",
    "zh-Hant": "chunks/zht.012.js",
    "en-XA": "chunks/pseudo.345.js",
}

MANIFEST_PATH = "authentik.core.templatetags.authentik_core._load_locale_manifest"


class TestResolveCatalogTag(TestCase):
    """The Django language code is mapped to a catalog tag present in the manifest."""

    def test_exact_tag_is_returned(self):
        self.assertEqual(_resolve_catalog_tag(MANIFEST, "de-DE"), "de-DE")

    def test_match_is_case_insensitive(self):
        self.assertEqual(_resolve_catalog_tag(MANIFEST, "de-de"), "de-DE")
        self.assertEqual(_resolve_catalog_tag(MANIFEST, "zh-hans"), "zh-Hans")

    def test_base_language_matches_regional_catalog(self):
        self.assertEqual(_resolve_catalog_tag(MANIFEST, "fr"), "fr-FR")

    def test_english_resolves_to_no_catalog(self):
        self.assertIsNone(_resolve_catalog_tag(MANIFEST, "en"))

    def test_english_never_resolves_to_pseudo_locale(self):
        """`en` must not fall through to the `en-XA` pseudo catalog."""
        self.assertNotEqual(_resolve_catalog_tag(MANIFEST, "en"), "en-XA")

    def test_unknown_language_resolves_to_no_catalog(self):
        self.assertIsNone(_resolve_catalog_tag(MANIFEST, "xx"))

    def test_empty_language_resolves_to_no_catalog(self):
        self.assertIsNone(_resolve_catalog_tag(MANIFEST, ""))


class TestLocaleModulePreload(TestCase):
    """The template tag emits a modulepreload for the active locale's catalog."""

    def test_emits_modulepreload_for_active_locale(self):
        with patch(MANIFEST_PATH, return_value=MANIFEST), translation.override("de"):
            html = locale_modulepreload()
        self.assertIn('rel="modulepreload"', html)
        self.assertIn("/static/dist/chunks/de.abc123.js", html)

    def test_emits_nothing_for_english(self):
        with patch(MANIFEST_PATH, return_value=MANIFEST), translation.override("en"):
            self.assertEqual(locale_modulepreload(), "")

    def test_emits_nothing_without_manifest(self):
        with patch(MANIFEST_PATH, return_value={}), translation.override("de"):
            self.assertEqual(locale_modulepreload(), "")
