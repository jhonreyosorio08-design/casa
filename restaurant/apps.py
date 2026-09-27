from django.apps import AppConfig


class RestaurantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "restaurant"


def site_content(request):
    from .models import SiteContent
    return {"site_content": SiteContent.objects.first()}
