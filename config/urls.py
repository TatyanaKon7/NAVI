from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from bot import views


urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("files/<int:file_id>/", views.project_file, name="project_file"),
    path("materials/<int:material_id>/", views.material_file, name="material_file"),
]
