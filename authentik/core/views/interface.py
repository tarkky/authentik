"""Interface views"""

from json import dumps
from typing import Any

from django.contrib.auth.mixins import AccessMixin
from django.http import HttpRequest
from django.http.response import HttpResponse
from django.shortcuts import redirect
from django.utils.translation import check_for_language, override
from django.utils.translation import gettext as _
from django.views.generic.base import RedirectView, TemplateView

from authentik import authentik_build_hash
from authentik.admin.tasks import LOCAL_VERSION
from authentik.api.v3.config import ConfigView
from authentik.brands.api import CurrentBrandSerializer
from authentik.brands.models import Brand
from authentik.core.apps import Setup
from authentik.core.models import UserTypes
from authentik.lib.config import CONFIG
from authentik.policies.denied import AccessDeniedResponse


class RootRedirectView(AccessMixin, RedirectView):
    """Root redirect view, redirect to brand's default application if set"""

    pattern_name = "authentik_core:if-user"
    query_string = True

    def redirect_to_app(self, request: HttpRequest):
        if request.user.is_authenticated and request.user.type in (
            UserTypes.EXTERNAL,
            UserTypes.SERVICE_ACCOUNT,
            UserTypes.INTERNAL_SERVICE_ACCOUNT,
        ):
            brand: Brand = request.brand
            if brand.default_application:
                return redirect(
                    "authentik_core:application-launch",
                    application_slug=brand.default_application.slug,
                )
        return None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not Setup.get():
            return redirect("authentik_core:setup")
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if redirect_response := RootRedirectView().redirect_to_app(request):
            return redirect_response
        return super().dispatch(request, *args, **kwargs)


class InterfaceView(TemplateView):
    """Base interface view"""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Honor an explicit `?locale=` override server-side (a dev/test aid), validated
        # against the supported languages, so the server-rendered shell and the web UI —
        # which reads the same parameter — can never disagree on the active locale.
        locale = request.GET.get("locale")
        if locale and check_for_language(locale):
            with override(locale):
                response = super().dispatch(request, *args, **kwargs)
                # TemplateResponse renders lazily, after this context exits; force it
                # now so the shell is rendered while the override language is active.
                if hasattr(response, "render") and callable(response.render):
                    response.render()
                return response
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        brand = CurrentBrandSerializer(self.request.brand, context={"request": self.request})
        kwargs["config_json"] = dumps(ConfigView.get_config(self.request).data)
        kwargs["ui_theme"] = brand.data["ui_theme"]
        kwargs["brand_json"] = dumps(brand.data)
        kwargs["version_family"] = f"{LOCAL_VERSION.major}.{LOCAL_VERSION.minor}"
        kwargs["version_subdomain"] = f"version-{LOCAL_VERSION.major}-{LOCAL_VERSION.minor}"
        kwargs["build"] = authentik_build_hash()
        kwargs["url_kwargs"] = self.kwargs
        kwargs["base_url"] = self.request.build_absolute_uri(CONFIG.get("web.path", "/"))
        kwargs["base_url_rel"] = CONFIG.get("web.path", "/")
        return super().get_context_data(**kwargs)


class BrandDefaultRedirectView(InterfaceView):
    """By default redirect to default app"""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated and request.user.type in (
            UserTypes.EXTERNAL,
            UserTypes.SERVICE_ACCOUNT,
            UserTypes.INTERNAL_SERVICE_ACCOUNT,
        ):
            brand: Brand = request.brand
            if brand.default_application:
                return redirect(
                    "authentik_core:application-launch",
                    application_slug=brand.default_application.slug,
                )
            response = AccessDeniedResponse(self.request)
            response.error_message = _("Interface can only be accessed by internal users.")
            return response
        return super().dispatch(request, *args, **kwargs)
