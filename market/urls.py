from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

router = DefaultRouter()
router.register("works", views.WorkViewSet, basename="work")
router.register("categories", views.CategoryViewSet, basename="category")

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view()),
    path("auth/token/", TokenObtainPairView.as_view()),
    path("auth/token/refresh/", TokenRefreshView.as_view()),
    path("auth/me/works/", views.MeWorkListView.as_view()),
    path("auth/me/", views.MeView.as_view()),
    path("auth/me/profile/", views.MeProfileUpdateView.as_view()),
    path("site/overview/", views.SiteOverviewView.as_view()),
    path("checkins/status/", views.CheckInStatusView.as_view()),
    path("checkins/", views.CheckInView.as_view()),
    path("wallet/", views.WalletView.as_view()),
    path("works/<int:work_id>/unlock/", views.WorkUnlockView.as_view()),
    path("works/<int:work_id>/source/", views.WorkSourceUploadView.as_view()),
    path(
        "works/<int:work_id>/source/download/",
        views.WorkSourceArchiveDownloadView.as_view(),
    ),
    path(
        "works/<int:work_id>/source-files/<int:source_file_id>/",
        views.WorkSourceFileContentView.as_view(),
    ),
    path(
        "works/<int:work_id>/source-files/<int:source_file_id>/download/",
        views.WorkSourceFileDownloadView.as_view(),
    ),
    path("works/<int:work_id>/images/", views.WorkImageView.as_view()),
    path(
        "works/<int:work_id>/images/<int:image_id>/",
        views.WorkImageDeleteView.as_view(),
    ),
] + router.urls
