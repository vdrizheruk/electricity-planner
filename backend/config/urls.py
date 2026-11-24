from django.contrib import admin
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import include, path


def healthz(_request: HttpRequest) -> HttpResponse:
    """Liveness probe: process is up."""
    return JsonResponse({"status": "ok"})


def readyz(_request: HttpRequest) -> HttpResponse:
    """Readiness probe: database is reachable."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "db_unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz),
    path("readyz", readyz),
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
]
