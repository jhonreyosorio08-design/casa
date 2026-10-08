import re

from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as format_date

from django.contrib.auth import get_user_model

from .models import CustomerNotification, DashboardNotification, Reservation, StockAlert


def operational_notification_url(user, message, fallback=""):
    reference = re.search(r"\bCS-[A-F0-9]{8}\b", message.upper())
    if not reference:
        return fallback
    booking = Reservation.objects.filter(reference=reference.group()).only("pk").first()
    if not booking:
        return fallback
    if user.is_superuser:
        return reverse("admin_module_edit", args=("reservations", booking.pk))
    if user.is_staff and (user.has_perm("restaurant.view_staff_reservations") or user.groups.filter(name__in=("Cashier", "Kitchen Staff")).exists()):
        return reverse("staff_reservation_detail", args=(booking.pk,))
    return fallback


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
    lower_kind = kind.lower()
    if "payment" in lower_kind or "gcash" in lower_kind:
        staff_url, admin_url = reverse("staff_dashboard") + "#payments", reverse("admin_payments")
    elif "order" in lower_kind or "walk-in" in lower_kind:
        staff_url, admin_url = reverse("staff_dashboard") + "#orders", reverse("admin_module", args=("orders",))
    elif "ktv" in lower_kind:
        staff_url, admin_url = reverse("staff_dashboard") + "#ktv", reverse("admin_dashboard") + "#admin-ktv"
    elif "table" in lower_kind:
        staff_url, admin_url = reverse("staff_dashboard") + "#tables", reverse("admin_dashboard") + "#admin-tables"
    elif "inventory" in lower_kind or "stock" in lower_kind:
        staff_url, admin_url = reverse("staff_dashboard") + "#inventory", reverse("admin_dashboard") + "#inventory-attention"
    else:
        staff_url, admin_url = reverse("staff_dashboard") + "#reservations", reverse("admin_module", args=("reservations",))
    notifications = [
        DashboardNotification(
            recipient=user, kind=kind, message=message,
            url=operational_notification_url(user, message, admin_url if user.is_superuser else staff_url),
        )
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
