from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as format_date

from .models import CustomerNotification, StockAlert


def navigation_notifications(user):
    if not user.is_authenticated or not user.is_active:
        return {"count": 0, "items": [], "status_url": "", "footer_url": ""}

    items = []
    if user.is_superuser:
        customer_notes = CustomerNotification.objects.filter(is_read=False).select_related("customer")
        stock_alerts = StockAlert.objects.filter(is_resolved=False).select_related("item")
        count = customer_notes.count() + stock_alerts.count()
        for note in customer_notes[:5]:
            items.append({"message": note.message, "kind": "Customer", "created": note.created_at, "url": "/admin/restaurant/customernotification/"})
        for alert in stock_alerts[:5]:
            items.append({"message": alert.message, "kind": "Inventory", "created": alert.created_at, "url": reverse("admin_dashboard") + "#stock-notifications"})
        footer_url = reverse("admin_dashboard")
    elif user.is_staff:
        can_view_inventory = user.has_perm("restaurant.view_inventoryitem") or user.groups.filter(name="Inventory Staff").exists()
        if not can_view_inventory:
            return {"count": 0, "items": [], "status_url": reverse("notification_status"), "footer_url": reverse("staff_dashboard")}
        stock_alerts = StockAlert.objects.filter(is_resolved=False).select_related("item")
        count = stock_alerts.count()
        for alert in stock_alerts[:8]:
            items.append({"message": alert.message, "kind": "Inventory", "created": alert.created_at, "url": reverse("staff_dashboard") + "#inventory"})
        footer_url = reverse("staff_dashboard") + "#inventory"
    else:
        customer_notes = CustomerNotification.objects.filter(customer=user, is_read=False)
        count = customer_notes.count()
        for note in customer_notes[:8]:
            items.append({"message": note.message, "kind": note.get_kind_display(), "created": note.created_at, "url": reverse("account_dashboard")})
        footer_url = reverse("account_dashboard")

    items.sort(key=lambda item: item["created"], reverse=True)
    for item in items:
        item["date"] = format_date(timezone.localtime(item["created"]), "M j · g:i A")
    return {
        "count": count,
        "items": items[:8],
        "status_url": reverse("notification_status"),
        "footer_url": footer_url,
    }


def nav_notifications(request):
    return {"nav_notifications": navigation_notifications(request.user)}
