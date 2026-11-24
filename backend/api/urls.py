from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import auth, export_views, power_views, views

catalog_router = DefaultRouter()
catalog_router.register("brands", views.BrandViewSet, basename="brand")
catalog_router.register("categories", views.CategoryViewSet, basename="category")
catalog_router.register("products", views.ProductViewSet, basename="product")

LIST = {"get": "list", "post": "create"}
DETAIL = {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    # auth
    path("auth/csrf/", auth.CsrfView.as_view()),
    path("auth/register/", auth.RegisterView.as_view()),
    path("auth/login/", auth.LoginView.as_view()),
    path("auth/logout/", auth.LogoutView.as_view()),
    path("auth/me/", auth.MeView.as_view()),
    # projects
    path("projects/", views.ProjectViewSet.as_view(LIST)),
    path("projects/<int:pk>/", views.ProjectViewSet.as_view(DETAIL)),
    path("projects/<int:pk>/calc/", views.ProjectViewSet.as_view({"get": "calc"})),
    path("projects/<int:pk>/power/", power_views.PowerView.as_view()),
    path("projects/<int:pk>/power/check/", power_views.PowerCheckView.as_view()),
    path("projects/<int:pk>/power/apply/", power_views.PowerApplyView.as_view()),
    path("projects/<int:pk>/bom/", export_views.BomView.as_view()),
    path("projects/<int:pk>/export/xlsx/", export_views.XlsxExportView.as_view()),
    path("projects/<int:pk>/export/pdf/", export_views.PdfExportView.as_view()),
    path("projects/<int:pk>/pv/", power_views.PvView.as_view()),
    path("projects/<int:pk>/pv/check/", power_views.PvCheckView.as_view()),
    path("projects/<int:pk>/pv/apply/", power_views.PvApplyView.as_view()),
    path("projects/<int:project_pk>/panels/", views.PanelViewSet.as_view(LIST)),
    path(
        "projects/<int:project_pk>/links/",
        views.PanelLinkViewSet.as_view({"get": "list", "post": "create"}),
    ),
    path("projects/<int:project_pk>/groups/", views.ConsumerGroupViewSet.as_view(LIST)),
    path(
        "projects/<int:project_pk>/groups/autoselect/",
        views.ConsumerGroupViewSet.as_view({"post": "autoselect"}),
    ),
    path(
        "links/<int:pk>/", views.PanelLinkViewSet.as_view({"get": "retrieve", "delete": "destroy"})
    ),
    path("groups/<int:pk>/", views.ConsumerGroupViewSet.as_view(DETAIL)),
    # panels
    path("panels/<int:pk>/", views.PanelViewSet.as_view(DETAIL)),
    path("panels/<int:pk>/validate/", views.PanelViewSet.as_view({"get": "validate_layout"})),
    path("panels/<int:pk>/autolayout/", views.PanelViewSet.as_view({"post": "autolayout"})),
    path("panels/<int:pk>/unplaced/", views.PanelViewSet.as_view({"get": "unplaced"})),
    path("panels/<int:panel_pk>/placements/", views.PlacementViewSet.as_view(LIST)),
    path(
        "panels/<int:panel_pk>/placements/bulk/",
        views.PlacementViewSet.as_view({"put": "bulk", "patch": "bulk"}),
    ),
    path("placements/<int:pk>/", views.PlacementViewSet.as_view(DETAIL)),
    path("panels/<int:panel_pk>/versions/", views.VersionViewSet.as_view(LIST)),
    path("versions/<int:pk>/", views.VersionViewSet.as_view({"get": "retrieve"})),
    path("versions/<int:pk>/restore/", views.VersionViewSet.as_view({"post": "restore"})),
    # catalog
    path("catalog/export/", views.CatalogExportView.as_view()),
    path("catalog/import/", views.CatalogImportView.as_view()),
    path("catalog/", include(catalog_router.urls)),
]
