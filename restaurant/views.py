import hashlib
import hmac
import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch, Sum, F, Q, Count, ExpressionWrapper, DecimalField
from django.utils.timezone import localdate
from datetime import timedelta
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import CustomerRegistrationForm, KTVReservationForm, ProfileUpdateForm, ReservationForm, ktv_slot_available
from .models import ActivityLog, CustomerNotification, DiningTable, Event, Expense, FoodOrder, GalleryImage, KTVRoom, MenuCategory, MenuItem, OrderItem, Reservation, InventoryItem, StockAlert, StockIn, StockMovement, Supplier
from .notification_utils import navigation_notifications

PREORDER_CATEGORIES = ["Pasta", "Salad", "Snacks", "Dessert", "Waffles", "Mains", "Grilled", "Soup"]


@login_required
def notification_status(request):
    notifications = navigation_notifications(request.user)
    return JsonResponse({
        "count": notifications["count"],
        "items": [
            {"message": item["message"], "kind": item["kind"], "date": item["date"], "url": item["url"]}
            for item in notifications["items"]
        ],
        "footer_url": notifications["footer_url"],
    })


def _notify_customer(reservation, kind, message):
    if reservation.customer_id:
        CustomerNotification.objects.create(customer=reservation.customer, reservation=reservation, kind=kind, message=message)


def _log_staff(user, action, target, details=""):
    if user.is_staff and not user.is_superuser:
        ActivityLog.objects.create(actor=user, action=action, target=target, details=details)


def home(request):
    if request.user.is_authenticated and request.user.is_active and request.user.is_superuser:
        return redirect("admin_dashboard")
    return public_home(request)


def public_home(request):
    featured = MenuItem.objects.filter(featured=True, available=True)[:3]
    today = localdate()
    upcoming_events = [
        event for event in Event.objects.filter(
            featured=True,
            status__in=[Event.Status.PUBLISHED, Event.Status.ONGOING],
            event_date__gte=today,
        ).order_by("event_date", "start_time")[:12]
        if not event.is_past
    ][:3]
    return render(request, "restaurant/home.html", {
        "featured": featured,
        "gallery": GalleryImage.objects.filter(is_published=True)[:4],
        "upcoming_events": upcoming_events,
    })


def events_page(request):
    events = list(Event.objects.exclude(status=Event.Status.DRAFT))
    upcoming_events = [event for event in events if not event.is_past]
    past_events = [event for event in events if event.is_past]
    past_events.reverse()
    return render(request, "restaurant/events.html", {
        "upcoming_events": upcoming_events,
        "past_events": past_events,
    })


def event_detail(request, slug):
    event = get_object_or_404(Event.objects.exclude(status=Event.Status.DRAFT), slug=slug)
    return render(request, "restaurant/event_detail.html", {"event": event})


def menu(request):
    return render(request, "restaurant/menu.html", {"categories": MenuCategory.objects.prefetch_related("items")})


def about(request): return render(request, "restaurant/about.html")
def gallery(request): return render(request, "restaurant/gallery.html", {"gallery": GalleryImage.objects.filter(is_published=True)})
def contact(request): return render(request, "restaurant/contact.html")


def register(request):
    form = CustomerRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "restaurant/register.html", {"form": form})


@login_required
def reservation(request):
    form = ReservationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        booking = form.save(commit=False)
        booking.customer = request.user
        booking.save()
        _notify_customer(booking, CustomerNotification.Kind.RESERVATION, f"Reservation {booking.reference} was received. Choose food for your visit; your table booking is free.")
        request.session["reservation_id"] = booking.pk
        return redirect("preorder", reference=booking.reference)
    return render(request, "restaurant/reservation.html", {"form": form})


@login_required
def ktv_reservation(request):
    form = KTVReservationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        booking = None
        with transaction.atomic():
            room = KTVRoom.objects.select_for_update().get(pk=form.cleaned_data["room"].pk)
            available = ktv_slot_available(room, form.cleaned_data["reservation_date"], form.cleaned_data["reservation_time"], form.cleaned_data["duration_hours"])
            if not available:
                form.add_error("reservation_time", "This room was just reserved for part of that time. Please choose another time or room.")
            else:
                booking = form.save(commit=False)
                booking.customer = request.user
                booking.ktv_room = room
                booking.table = None
                booking.duration_hours = form.cleaned_data["duration_hours"]
                booking.ktv_fee = room.hourly_price * booking.duration_hours
                booking.save()
                if room.status == KTVRoom.Status.AVAILABLE:
                    room.status = KTVRoom.Status.RESERVED
                    room.save(update_fields=["status"])
        if booking:
            _notify_customer(booking, CustomerNotification.Kind.RESERVATION, f"KTV reservation {booking.reference} was received. Choose food and drinks for your visit.")
            return redirect("preorder", reference=booking.reference)
    return render(request, "restaurant/ktv_reservation.html", {"form": form, "rooms": KTVRoom.objects.filter(active=True)})


@login_required
def preorder(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference, customer=request.user)
    menu_items = MenuItem.objects.filter(available=True, category__name__in=PREORDER_CATEGORIES).select_related("category")
    order, _ = FoodOrder.objects.get_or_create(reservation=reservation)
    if request.method == "POST":
        with transaction.atomic():
            order.items.all().delete()
            for item in menu_items:
                quantity = int(request.POST.get(f"item_{item.pk}", 0) or 0)
                if quantity > 0:
                    OrderItem.objects.create(order=order, menu_item=item, name=item.name, unit_price=item.price, quantity=quantity)
            if not order.items.exists() and not reservation.is_ktv:
                messages.error(request, "Please add at least one food or beverage item before continuing.")
            else:
                order.recalculate_total()
                return redirect("checkout", reference=reservation.reference)
    quantities = {item.menu_item_id: item.quantity for item in order.items.all()}
    categories = MenuCategory.objects.filter(name__in=PREORDER_CATEGORIES).prefetch_related(
        Prefetch("items", queryset=menu_items, to_attr="preorder_items")
    )
    return render(request, "restaurant/preorder.html", {"reservation": reservation, "categories": categories, "quantities": quantities})


@login_required
def checkout(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference, customer=request.user)
    order = get_object_or_404(FoodOrder.objects.prefetch_related("items"), reservation=reservation)
    if not order.items.exists() and not reservation.is_ktv: return redirect("preorder", reference=reference)
    if request.method == "POST":
        # A real GCash gateway redirects from here; credentials are configured outside source control.
        order.payment_method = "gcash"
        order.gateway_reference = f"GCASH-{reservation.reference}"
        order.save(update_fields=["payment_method", "gateway_reference"])
        return redirect("payment_pending", reference=reference)
    return render(request, "restaurant/checkout.html", {"reservation": reservation, "order": order, "total_amount": order.total_amount})


@login_required
def payment_pending(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference, customer=request.user)
    order = get_object_or_404(FoodOrder, reservation=reservation)
    return render(request, "restaurant/payment_pending.html", {"reservation": reservation, "order": order})


@login_required
def account_dashboard(request):
    if request.method == "POST":
        notification = get_object_or_404(CustomerNotification, pk=request.POST.get("notification_id"), customer=request.user)
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return redirect("account_dashboard")
    reservations = Reservation.objects.filter(customer=request.user).select_related("table").prefetch_related("food_order__items").order_by("-created_at")
    notifications = CustomerNotification.objects.filter(customer=request.user)
    return render(request, "restaurant/account.html", {"reservations": reservations, "notifications": notifications, "unread_notifications": notifications.filter(is_read=False).count()})


@login_required
@require_POST
def cancel_ktv_reservation(request, reference):
    booking = get_object_or_404(Reservation, reference=reference, customer=request.user, ktv_room__isnull=False)
    if not booking.can_cancel_ktv:
        messages.error(request, "This KTV reservation can no longer be cancelled online.")
        return redirect("account_dashboard")

    with transaction.atomic():
        booking.status = Reservation.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=["status", "cancelled_at"])
        _notify_customer(booking, CustomerNotification.Kind.RESERVATION, f"KTV reservation {booking.reference} has been cancelled. Your payment record remains available for administrator review.")
        payment_status = booking.food_order.get_payment_status_display() if hasattr(booking, "food_order") else "No payment submitted"
        ActivityLog.objects.create(
            actor=request.user,
            action="KTV reservation cancelled",
            target=booking.reference,
            details=f"{booking.ktv_room} on {booking.reservation_date} at {booking.reservation_time}; {booking.duration_hours} hours; KTV fee ₱{booking.ktv_fee}; payment {payment_status}; cancelled at {booking.cancelled_at:%Y-%m-%d %H:%M:%S %Z}.",
        )
        room = KTVRoom.objects.select_for_update().get(pk=booking.ktv_room_id)
        if room.status == KTVRoom.Status.RESERVED and not room.reservations.exclude(status__in=[Reservation.Status.CANCELLED, Reservation.Status.COMPLETED]).exists():
            room.status = KTVRoom.Status.AVAILABLE
            room.save(update_fields=["status"])
    messages.success(request, f"KTV reservation {booking.reference} has been cancelled. You can now make a dine-in reservation.")
    return redirect("account_dashboard")


@login_required
def account_profile(request):
    form = ProfileUpdateForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile details have been updated.")
        return redirect("account_profile")
    return render(request, "restaurant/profile.html", {"form": form})


@login_required
def customer_receipt(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference, customer=request.user)
    order = get_object_or_404(FoodOrder.objects.select_related("reservation").prefetch_related("items"), reservation=reservation, payment_status=FoodOrder.PaymentStatus.PAID)
    return render(request, "restaurant/customer_receipt.html", {"order": order})


def _staff_can(user, codename, groups=()):
    return user.is_superuser or user.has_perm(f"restaurant.{codename}") or user.groups.filter(name__in=groups).exists()


def staff_login(request):
    from django.contrib.auth.forms import AuthenticationForm
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if not user.is_staff or not user.is_active:
            form.add_error(None, "These credentials are not enabled for staff access.")
        else:
            login(request, user)
            return redirect("staff_dashboard")
    return render(request, "restaurant/staff_login.html", {"form": form})


@login_required(login_url="staff_login")
def staff_dashboard(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied
    can_reservations = _staff_can(request.user, "view_staff_reservations", ("Cashier", "Kitchen Staff"))
    can_orders = _staff_can(request.user, "view_staff_orders", ("Cashier", "Kitchen Staff"))
    can_order_update = _staff_can(request.user, "change_staff_order_status", ("Cashier", "Kitchen Staff"))
    can_payments = _staff_can(request.user, "view_staff_payments", ("Cashier",))
    can_payment_update = _staff_can(request.user, "change_staff_payments", ("Cashier",))
    can_tables = _staff_can(request.user, "view_staff_tables", ("Cashier", "Kitchen Staff"))
    can_table_update = _staff_can(request.user, "change_staff_tables", ("Cashier",))
    can_ktv = can_reservations or _staff_can(request.user, "view_ktvroom", ("Cashier",))
    can_ktv_update = _staff_can(request.user, "change_staff_ktv_room_status", ("Cashier",))
    can_inventory = _staff_can(request.user, "view_inventoryitem", ("Inventory Staff",))
    can_inventory_update = _staff_can(request.user, "change_inventoryitem", ("Inventory Staff",))
    can_movements = _staff_can(request.user, "view_stockmovement", ("Inventory Staff",))
    can_stock_update = _staff_can(request.user, "add_stockmovement", ("Inventory Staff",))
    can_reports = _staff_can(request.user, "view_staff_reports")
    if not any((can_reservations, can_orders, can_payments, can_tables, can_inventory)):
        raise PermissionDenied("Your administrator has not assigned an operations role.")
    today = localdate()
    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("approve_payment", "reject_payment") and can_payment_update:
            order = get_object_or_404(FoodOrder.objects.select_related("reservation"), pk=request.POST.get("order_id"))
            if order.payment_status != FoodOrder.PaymentStatus.PENDING:
                raise PermissionDenied("Only pending payments can be reviewed.")
            if action == "approve_payment":
                order.payment_status = FoodOrder.PaymentStatus.PAID
                order.paid_at = timezone.now()
                order.reservation.status = Reservation.Status.CONFIRMED
                order.reservation.save(update_fields=["status"])
                order.save(update_fields=["payment_status", "paid_at"])
                _notify_customer(order.reservation, CustomerNotification.Kind.PAYMENT, f"Payment for {order.reservation.reference} was accepted. Your reservation is confirmed.")
                _log_staff(request.user, "Payment accepted", order.reservation.reference, f"Amount ₱{order.total_amount}; GCash reference {order.gateway_reference}")
                messages.success(request, f"Payment for {order.reservation.reference} approved; reservation confirmed.")
            else:
                order.payment_status = FoodOrder.PaymentStatus.FAILED
                order.save(update_fields=["payment_status"])
                _notify_customer(order.reservation, CustomerNotification.Kind.PAYMENT, f"Payment for {order.reservation.reference} was not accepted. Please contact Casa Sonata or submit payment again.")
                _log_staff(request.user, "Payment rejected", order.reservation.reference, f"Amount ₱{order.total_amount}; GCash reference {order.gateway_reference}")
                messages.info(request, f"Payment for {order.reservation.reference} rejected.")
        elif action == "update_order_status" and can_order_update:
            order = get_object_or_404(FoodOrder.objects.select_related("reservation"), pk=request.POST.get("order_id"))
            status = request.POST.get("status")
            if status not in FoodOrder.OrderStatus.values:
                raise PermissionDenied
            if status == FoodOrder.OrderStatus.COMPLETED and order.reservation.is_ktv:
                room = order.reservation.ktv_room
                if room.status not in (KTVRoom.Status.OCCUPIED, KTVRoom.Status.COMPLETED):
                    messages.error(request, f"Move {room.name} through Reserved and Occupied before completing its KTV order.")
                    return redirect("staff_dashboard")
                if room.status == KTVRoom.Status.OCCUPIED:
                    room.status = KTVRoom.Status.COMPLETED
                    room.save(update_fields=["status"])
            order.order_status = status
            order.save(update_fields=["order_status"])
            _notify_customer(order.reservation, CustomerNotification.Kind.ORDER, f"Your order for {order.reservation.reference} is now {order.get_order_status_display().lower()}.")
            _log_staff(request.user, "Order status updated", order.reservation.reference, order.get_order_status_display())
            if status == FoodOrder.OrderStatus.COMPLETED:
                order.reservation.status = Reservation.Status.COMPLETED
                order.reservation.save(update_fields=["status"])
            messages.success(request, f"Order {order.reservation.reference} updated.")
        elif action == "toggle_table" and can_table_update:
            table = get_object_or_404(DiningTable, pk=request.POST.get("table_id"))
            table.occupied = request.POST.get("occupied") == "true"
            table.save(update_fields=["occupied"])
            _log_staff(request.user, "Table status updated", table.name, "Occupied" if table.occupied else "Available")
            messages.success(request, f"{table.name} marked {'occupied' if table.occupied else 'available'}.")
        elif action == "update_ktv_room_status" and can_ktv_update:
            room = get_object_or_404(KTVRoom, pk=request.POST.get("room_id"))
            status = request.POST.get("status")
            allowed_statuses = [value for value, _ in room.next_status_choices]
            if status not in allowed_statuses:
                messages.error(request, f"{room.name} can only move to its next KTV status.")
                return redirect("staff_dashboard")
            room.status = status
            room.save(update_fields=["status"])
            _log_staff(request.user, "KTV room status updated", room.name, room.get_status_display())
            messages.success(request, f"{room.name} marked {room.get_status_display().lower()}.")
        elif action in ("stock_in", "stock_usage") and can_stock_update and can_inventory_update:
            item = get_object_or_404(InventoryItem, pk=request.POST.get("item_id"))
            try:
                amount = Decimal(request.POST.get("quantity", "0"))
                if amount <= 0: raise ValueError
                if action == "stock_usage" and amount > item.quantity: raise ValueError
                item.quantity += amount if action == "stock_in" else -amount
                item.save(update_fields=["quantity", "updated_at"])
                StockMovement.objects.create(item=item, kind="in" if action == "stock_in" else "usage", quantity=amount, note=request.POST.get("note", ""))
                _log_staff(request.user, "Inventory stock in" if action == "stock_in" else "Inventory usage", item.name, f"{amount} {item.unit}; {request.POST.get('note', '')}")
                messages.success(request, f"Inventory updated for {item.name}.")
            except (ValueError, ArithmeticError):
                messages.error(request, "Enter a valid quantity. Usage cannot exceed current stock.")
        else:
            raise PermissionDenied
        return redirect("staff_dashboard")

    pending = FoodOrder.objects.filter(payment_status=FoodOrder.PaymentStatus.PENDING).select_related("reservation").prefetch_related("items") if can_payments else FoodOrder.objects.none()
    items = InventoryItem.objects.all().order_by("quantity", "name") if can_inventory else InventoryItem.objects.none()
    paid = FoodOrder.objects.filter(payment_status="paid")
    def paid_total(queryset):
        values = queryset.aggregate(food=Sum("amount"), ktv=Sum("reservation__ktv_fee"))
        return (values["food"] or Decimal("0")) + (values["ktv"] or Decimal("0"))
    def food_total(queryset):
        return queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    sales_today = paid_total(paid.filter(paid_at__date=today)) if can_reports else Decimal("0")
    month_sales = paid_total(paid.filter(paid_at__date__gte=today.replace(day=1))) if can_reports else Decimal("0")
    year_sales = paid_total(paid.filter(paid_at__date__gte=today.replace(month=1, day=1))) if can_reports else Decimal("0")
    inventory_cost = sum((item.quantity * item.unit_cost for item in items), Decimal("0")) if can_reports else Decimal("0")
    weekly_sales = []
    for offset in range(6, -1, -1) if can_reports else ():
        day = today - timedelta(days=offset)
        value = paid_total(paid.filter(paid_at__date=day))
        weekly_sales.append({"label": day.strftime("%a"), "amount": value})
    reservations_today = Reservation.objects.filter(reservation_date=today).count() if can_reservations else 0
    return render(request, "restaurant/staff_dashboard.html", {
        "today": today,
        "can_reservations": can_reservations, "can_orders": can_orders,
        "can_order_update": can_order_update, "can_payments": can_payments,
        "can_payment_update": can_payment_update, "can_tables": can_tables,
        "can_table_update": can_table_update, "can_inventory": can_inventory,
        "can_ktv": can_ktv, "can_ktv_update": can_ktv_update,
        "can_inventory_update": can_inventory_update, "can_movements": can_movements,
        "can_stock_update": can_stock_update, "can_reports": can_reports,
        "orders": FoodOrder.objects.select_related("reservation", "reservation__table").prefetch_related("items").order_by("created_at") if can_orders else FoodOrder.objects.none(),
        "order_status_choices": FoodOrder.OrderStatus.choices,
        "payment_orders": FoodOrder.objects.select_related("reservation").order_by("-created_at")[:30] if can_payments else FoodOrder.objects.none(),
        "tables": DiningTable.objects.filter(active=True) if can_tables else DiningTable.objects.none(),
        "ktv_rooms": KTVRoom.objects.filter(active=True) if can_ktv else KTVRoom.objects.none(),
        "ktv_reservations_today": Reservation.objects.filter(ktv_room__isnull=False, reservation_date=today).select_related("ktv_room", "customer").prefetch_related("food_order__items").order_by("reservation_time") if can_ktv else Reservation.objects.none(),
        "ktv_cancellations": Reservation.objects.filter(ktv_room__isnull=False, status=Reservation.Status.CANCELLED).select_related("ktv_room", "customer").prefetch_related("food_order").order_by("-cancelled_at")[:20] if can_ktv else Reservation.objects.none(),
        "tables_occupied": DiningTable.objects.filter(active=True, occupied=True).count() if can_tables else 0,
        "pending_orders": pending, "inventory": items, "low_stock": items.filter(quantity__lte=F("low_stock_threshold")),
        "sales_today": sales_today, "reservations_today": reservations_today,
        "ktv_income_today": paid.filter(reservation__ktv_room__isnull=False, paid_at__date=today).aggregate(total=Sum("reservation__ktv_fee"))["total"] or Decimal("0"),
        "food_income_today": food_total(paid.filter(paid_at__date=today)),
        "ktv_reservation_count_today": Reservation.objects.filter(ktv_room__isnull=False, reservation_date=today).count(),
        "orders_today": FoodOrder.objects.filter(created_at__date=today).count(),
        "month_sales": month_sales, "year_sales": year_sales, "inventory_cost": inventory_cost,
        "estimated_net": year_sales - inventory_cost, "weekly_sales": weekly_sales,
        "customers": Reservation.objects.values("customer").distinct().count() if can_reports else 0,
        "recent_reservations": Reservation.objects.select_related("table").order_by("-created_at")[:6] if can_reservations else Reservation.objects.none(),
        "recent_movements": StockMovement.objects.select_related("item").order_by("-created_at")[:6] if can_movements else StockMovement.objects.none(),
    })


@login_required(login_url="staff_login")
def staff_receipt(request, order_id):
    if not request.user.is_staff or not _staff_can(request.user, "view_staff_payments", ("Cashier",)):
        raise PermissionDenied
    order = get_object_or_404(FoodOrder.objects.select_related("reservation").prefetch_related("items"), pk=order_id)
    return render(request, "restaurant/staff_receipt.html", {"order": order})


@user_passes_test(lambda user: user.is_active and user.is_superuser, login_url="admin:login")
def admin_dashboard(request):
    today = localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    paid = FoodOrder.objects.filter(payment_status=FoodOrder.PaymentStatus.PAID)

    def paid_totals(queryset):
        totals = queryset.aggregate(food=Sum("amount"), ktv=Sum("reservation__ktv_fee"))
        return (totals["food"] or Decimal("0")) + (totals["ktv"] or Decimal("0"))

    def ktv_income(queryset):
        return queryset.filter(reservation__ktv_room__isnull=False).aggregate(total=Sum("reservation__ktv_fee"))["total"] or Decimal("0")
    def food_income(queryset):
        return queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    def income_since(start):
        return paid_totals(paid.filter(paid_at__date__range=(start, today)))

    def expense_since(start):
        return Expense.objects.filter(expense_date__range=(start, today)).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    daily_income = paid_totals(paid.filter(paid_at__date=today))
    daily_expense = Expense.objects.filter(expense_date=today).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    weekly_income, weekly_expense = income_since(week_start), expense_since(week_start)
    monthly_income, monthly_expense = income_since(month_start), expense_since(month_start)
    yearly_income, yearly_expense = income_since(year_start), expense_since(year_start)
    week_chart = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        income = paid_totals(paid.filter(paid_at__date=day))
        expenses = Expense.objects.filter(expense_date=day).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        week_chart.append({"label": day.strftime("%a"), "income": income, "expenses": expenses})
    max_chart = max((max(row["income"], row["expenses"]) for row in week_chart), default=Decimal("0")) or Decimal("1")
    for row in week_chart:
        row["income_height"] = max(3, int(row["income"] * 100 / max_chart))
        row["expense_height"] = max(3, int(row["expenses"] * 100 / max_chart))
    weekly_orders = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        weekly_orders.append({"label": day.strftime("%a"), "count": FoodOrder.objects.filter(created_at__date=day).count()})
    order_max = max((row["count"] for row in weekly_orders), default=0) or 1
    for row in weekly_orders:
        row["height"] = max(3, int(row["count"] * 100 / order_max))
    monthly_orders = []
    for offset in range(11, -1, -1):
        month_index = today.year * 12 + today.month - 1 - offset
        year, month = divmod(month_index, 12)
        month += 1
        monthly_orders.append({"label": f"{month:02d}/{str(year)[-2:]}", "count": FoodOrder.objects.filter(created_at__year=year, created_at__month=month).count()})
    monthly_order_max = max((row["count"] for row in monthly_orders), default=0) or 1
    for row in monthly_orders:
        row["height"] = max(3, int(row["count"] * 100 / monthly_order_max))
    popular_items = OrderItem.objects.filter(order__payment_status=FoodOrder.PaymentStatus.PAID).values("name").annotate(
        quantity_sold=Sum("quantity"),
        revenue=Sum(ExpressionWrapper(F("unit_price") * F("quantity"), output_field=DecimalField(max_digits=14, decimal_places=2))),
    ).order_by("-quantity_sold")[:5]
    table_metrics = DiningTable.objects.filter(active=True).annotate(
        reservation_count=Count("reservations", filter=Q(reservations__reservation_date__gte=month_start, reservations__reservation_date__lte=today)),
        order_count=Count("reservations__food_order", filter=Q(reservations__reservation_date__gte=month_start, reservations__reservation_date__lte=today), distinct=True),
        table_income=Sum("reservations__food_order__amount", filter=Q(reservations__food_order__payment_status=FoodOrder.PaymentStatus.PAID, reservations__reservation_date__gte=month_start, reservations__reservation_date__lte=today)),
    ).order_by("name")
    low_inventory = InventoryItem.objects.filter(quantity__lte=F("low_stock_threshold"))
    open_stock_alerts = StockAlert.objects.filter(is_resolved=False).select_related("item")
    recent_table_orders = FoodOrder.objects.filter(reservation__table__isnull=False).select_related("reservation", "reservation__table").prefetch_related("items").order_by("-created_at")[:10]
    ktv_reservations = Reservation.objects.filter(ktv_room__isnull=False).select_related("ktv_room", "customer").prefetch_related("food_order__items").order_by("-reservation_date", "-reservation_time")[:25]
    ktv_cancellations = Reservation.objects.filter(ktv_room__isnull=False, status=Reservation.Status.CANCELLED).select_related("ktv_room", "customer").prefetch_related("food_order").order_by("-cancelled_at")[:25]
    return render(request, "restaurant/admin_dashboard.html", {
        "today": today, "daily_income": daily_income, "daily_expense": daily_expense,
        "weekly_income": weekly_income, "weekly_expense": weekly_expense,
        "monthly_income": monthly_income, "monthly_expense": monthly_expense,
        "yearly_income": yearly_income, "yearly_expense": yearly_expense,
        "daily_net": daily_income - daily_expense, "weekly_net": weekly_income - weekly_expense,
        "monthly_net": monthly_income - monthly_expense, "yearly_net": yearly_income - yearly_expense,
        "week_chart": week_chart,
        "paid_count": paid.count(), "paid_today": paid.filter(paid_at__date=today).count(),
        "orders_today": FoodOrder.objects.filter(created_at__date=today).count(),
        "reservations_today": Reservation.objects.filter(reservation_date=today).count(),
        "orders_week": FoodOrder.objects.filter(created_at__date__gte=week_start).count(),
        "orders_month": FoodOrder.objects.filter(created_at__date__gte=month_start).count(),
        "orders_year": FoodOrder.objects.filter(created_at__date__gte=year_start).count(),
        "reservations_week": Reservation.objects.filter(reservation_date__gte=week_start, reservation_date__lte=today).count(),
        "reservations_month": Reservation.objects.filter(reservation_date__gte=month_start, reservation_date__lte=today).count(),
        "reservations_year": Reservation.objects.filter(reservation_date__gte=year_start, reservation_date__lte=today).count(),
        "accepted_week": paid.filter(paid_at__date__range=(week_start, today)).count(),
        "accepted_month": paid.filter(paid_at__date__range=(month_start, today)).count(),
        "accepted_year": paid.filter(paid_at__date__range=(year_start, today)).count(),
        "pending_payments": FoodOrder.objects.filter(payment_status=FoodOrder.PaymentStatus.PENDING).count(),
        "low_inventory": low_inventory, "staff_count": request.user.__class__.objects.filter(is_staff=True, is_active=True, is_superuser=False).count(),
        "supplier_count": Supplier.objects.count(), "inventory_count": InventoryItem.objects.count(),
        "notification_count": CustomerNotification.objects.filter(is_read=False).count() + open_stock_alerts.count(),
        "open_stock_alerts": open_stock_alerts,
        "out_of_stock_count": InventoryItem.objects.filter(quantity__lte=0).count(),
        "occupied_tables": DiningTable.objects.filter(active=True, occupied=True).count(),
        "weekly_orders": weekly_orders, "monthly_orders": monthly_orders,
        "popular_items": popular_items, "table_metrics": table_metrics,
        "recent_table_orders": recent_table_orders,
        "ktv_reservations": ktv_reservations,
        "ktv_cancellations": ktv_cancellations,
        "ktv_rooms": KTVRoom.objects.all(),
        "ktv_income_today": ktv_income(paid.filter(paid_at__date=today)),
        "ktv_income_week": ktv_income(paid.filter(paid_at__date__range=(week_start, today))),
        "ktv_income_month": ktv_income(paid.filter(paid_at__date__range=(month_start, today))),
        "ktv_income_year": ktv_income(paid.filter(paid_at__date__range=(year_start, today))),
        "food_income_today": food_income(paid.filter(paid_at__date=today)),
        "food_income_week": food_income(paid.filter(paid_at__date__range=(week_start, today))),
        "food_income_month": food_income(paid.filter(paid_at__date__range=(month_start, today))),
        "food_income_year": food_income(paid.filter(paid_at__date__range=(year_start, today))),
        "tables": DiningTable.objects.filter(active=True).order_by("name"),
        "recent_activity": ActivityLog.objects.select_related("actor")[:12],
    })


@csrf_exempt
@require_POST
def payment_webhook(request):
    secret = getattr(settings, "GCASH_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Casa-Signature", "")
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(signature, expected): return HttpResponseForbidden("Invalid webhook signature")
    payload = json.loads(request.body)
    order = get_object_or_404(FoodOrder, gateway_reference=payload.get("gateway_reference"))
    if payload.get("status") == "paid" and order.payment_status == FoodOrder.PaymentStatus.PENDING:
        order.payment_status = FoodOrder.PaymentStatus.PAID
        order.paid_at = timezone.now()
        order.save(update_fields=["payment_status", "paid_at"])
        order.reservation.status = Reservation.Status.CONFIRMED
        order.reservation.save(update_fields=["status"])
        _notify_customer(order.reservation, CustomerNotification.Kind.PAYMENT, f"Payment for {order.reservation.reference} was accepted. Your reservation is confirmed.")
    return JsonResponse({"ok": True})
