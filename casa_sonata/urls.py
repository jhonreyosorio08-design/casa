from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [path("admin/", admin.site.urls), path("", include("restaurant.urls"))]
# Only authorized administrators manage users and system configuration in Django Admin.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
