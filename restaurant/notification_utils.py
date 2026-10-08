from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as format_date

from django.contrib.auth import get_user_model

from .models import CustomerNotification, DashboardNotification, StockAlert


def notify_operations(audiences, kind, message):
    user_model = get_user_model()
    recipients = user_model.objects.filter(is_active=True)
    if "staff" in audiences:
        staff = recipients.filter(is_staff=True, is_superuser=False)
    else:
        staff = recipients.none()
    if "admin" in audiences:
        admins = recipients.filter(is_superuser=True)
    else:
        admins = recipients.none()
    notifications = [
        DashboardNotification(recipient=user, kind=kind, message=message)
        for user in (staff | admins).distinct()
    ]
    DashboardNotification.objects.bulk_create(notifications)


def navigation_notifications(user):
    if not user.is_authenticated or not user.is_active:
        return {"count": 0, "items": [], "status_url": "", "footer_url": ""}

    items = []
    dashboard_notes = DashboardNotification.objects.filter(recipient=user).order_by("-created_at") if (user.is_staff or user.is_superuser) else DashboardNotification.objects.none()
    if user.is_superuser:
        stock_alerts = StockAlert.objects.filter(is_resolved=False).select_related("item")
        count = stock_alerts.count()
        for alert in stock_alerts[:5]:
            items.append({"message": alert.message, "kind": "Inventory", "created": alert.created_at, "is_read": False, "url": reverse("notification_center") + f"#stock-{alert.pk}"})
        footer_url = reverse("notification_center")
    elif user.is_staff:
        can_view_inventory = user.has_perm("restaurant.view_inventoryitem") or user.groups.filter(name="Inventory Staff").exists()
        stock_alerts = StockAlert.objects.filter(is_resolved=False).select_related("item") if can_view_inventory else StockAlert.objects.none()
        count = stock_alerts.count()
        for alert in stock_alerts[:8]:
            items.append({"message": alert.message, "kind": "Inventory", "created": alert.created_at, "is_read": False, "url": reverse("notification_center") + f"#stock-{alert.pk}"})
        footer_url = reverse("notification_center")
    else:
        customer_notes = CustomerNotification.objects.filter(customer=user).order_by("-created_at")
        count = customer_notes.filter(is_read=False).count()
        titles = {
            CustomerNotification.Kind.RESERVATION: "Reservation update",
            CustomerNotification.Kind.PAYMENT: "GCash payment update",
            CustomerNotification.Kind.ORDER: "Food order update",
        }
        for note in customer_notes[:8]:
            items.append({
                "message": note.message,
                "kind": titles.get(note.kind, note.get_kind_display()),
                "created": note.created_at,
                "is_read": note.is_read,
                "url": reverse("notification_center") + f"#customer-{note.pk}",
            })
        footer_url = reverse("notification_center")

    if user.is_staff or user.is_superuser:
        count += dashboard_notes.filter(is_read=False).count()
        for note in dashboard_notes[:8]:
            items.append({"message": note.message, "kind": note.kind, "created": note.created_at, "is_read": note.is_read, "url": reverse("notification_center") + f"#ops-{note.pk}"})

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
