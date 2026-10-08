import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.forms import modelform_factory
from django.db import transaction
from django.db.models import Prefetch, Sum, F, Q, Count, ExpressionWrapper, DecimalField
from django.utils.timezone import localdate
from datetime import timedelta
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import CustomerRegistrationForm, KTVReservationForm, PaymentSubmissionForm, ProfileUpdateForm, ReservationForm, StaffAccountForm, WalkInReservationForm, dining_slot_available, ktv_slot_available
from .models import ActivityLog, CustomerNotification, DashboardNotification, DiningTable, Event, Expense, FoodOrder, GalleryImage, KTVRoom, KTVTimeExtension, MenuCategory, MenuItem, OrderItem, Reservation, InventoryItem, StockAlert, StockIn, StockMovement, Supplier, SiteContent
from .notification_utils import navigation_notifications, notify_operations

@login_required
def notification_status(request):
    notifications = navigation_notifications(request.user)
    return JsonResponse({
        "count": notifications["count"],
        "items": [
            {"message": item["message"], "kind": item["kind"], "date": item["date"], "url": item["url"], "is_read": item["is_read"]}
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


def _reservation_ready_message(reservation):
    place = f"KTV room {reservation.ktv_room.name}" if reservation.is_ktv else f"table {reservation.table.name}" if reservation.table_id else "reserved table"
    return f"Your {place} is ready. We look forward to welcoming you for reservation {reservation.reference}."


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
    return render(request, "restaurant/menu.html", {
        "categories": MenuCategory.objects.filter(items__isnull=False).distinct().prefetch_related("items"),
    })


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
        with transaction.atomic():
            booking = form.save(commit=False)
            booking.customer = request.user
            if booking.table_id:
                table = DiningTable.objects.select_for_update().get(pk=booking.table_id)
                if not dining_slot_available(table, booking.reservation_date, booking.reservation_time):
                    form.add_error("table", f"{table.name} was just reserved for that time. Please choose another table or time.")
                    booking = None
                else:
                    booking.table = table
            if booking:
                booking.save()
        if booking:
            _notify_customer(booking, CustomerNotification.Kind.RESERVATION, f"Reservation {booking.reference} was received. Choose food for your visit; your table booking is free.")
            notify_operations(("staff", "admin"), "Reservation", f"New dine-in reservation {booking.reference}: {booking.guests} guests on {booking.reservation_date} at {booking.reservation_time}.")
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
            notify_operations(("staff", "admin"), "KTV schedule", f"New KTV booking {booking.reference} for {booking.ktv_room.name} on {booking.reservation_date} at {booking.reservation_time}.")
            return redirect("preorder", reference=booking.reference)
    return render(request, "restaurant/ktv_reservation.html", {"form": form, "rooms": KTVRoom.objects.filter(active=True)})


@login_required
def preorder(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference, customer=request.user)
    menu_items = MenuItem.objects.filter(available=True).select_related("category")
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
                notify_operations(("staff", "admin"), "New order", f"A food order for reservation {reservation.reference} is ready for review.")
                return redirect("checkout", reference=reservation.reference)
    quantities = {item.menu_item_id: item.quantity for item in order.items.all()}
    categories = MenuCategory.objects.filter(items__available=True).distinct().prefetch_related(
        Prefetch("items", queryset=menu_items, to_attr="preorder_items")
    )
    return render(request, "restaurant/preorder.html", {"reservation": reservation, "categories": categories, "quantities": quantities})


@login_required
def checkout(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference, customer=request.user)
    order = get_object_or_404(FoodOrder.objects.prefetch_related("items"), reservation=reservation)
    if not order.items.exists() and not reservation.is_ktv: return redirect("preorder", reference=reference)
    if request.method == "POST":
        form = PaymentSubmissionForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Complete the GCash payment first, confirm it, then enter the reference number and upload a valid proof image.")
            return redirect("checkout", reference=reference)
        gcash_reference = form.cleaned_data["gcash_reference"]
        payment_proof = form.cleaned_data["payment_proof"]
        order.payment_method = "gcash"
        order.gateway_reference = gcash_reference
        order.payment_proof = payment_proof
        order.payment_status = FoodOrder.PaymentStatus.PENDING
        order.paid_at = None
        order.save(update_fields=["payment_method", "gateway_reference", "payment_proof", "payment_status", "paid_at"])
        notify_operations(("staff", "admin"), "Pending GCash payment", f"GCash payment for reservation {reservation.reference} is waiting for verification.")
        return redirect("payment_pending", reference=reference)
    return render(request, "restaurant/checkout.html", {
        "reservation": reservation,
        "order": order,
        "total_amount": order.total_amount,
        "site_content": SiteContent.objects.first(),
    })


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
    reservations = Reservation.objects.filter(customer=request.user).select_related("table", "ktv_room").prefetch_related("food_order__items", "time_extensions").order_by("-created_at")
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
        notify_operations(("staff", "admin"), "Cancelled reservation", f"KTV reservation {booking.reference} for {booking.reservation_date} at {booking.reservation_time} was cancelled.")
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
    order = get_object_or_404(FoodOrder.objects.select_related("reservation", "reservation__ktv_room").prefetch_related("items", "reservation__time_extensions"), reservation=reservation, payment_status=FoodOrder.PaymentStatus.PAID)
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
def staff_walkin_payment(request):
    user = request.user
    if not user.is_active or not user.is_staff or not _staff_can(user, "change_staff_payments", ("Cashier",)):
        raise PermissionDenied
    menu_items = MenuItem.objects.filter(available=True).select_related("category").order_by("category__order", "name")
    requested_service = request.GET.get("service")
    initial = {"reservation_type": requested_service} if requested_service in ("dine_in", "ktv") else None
    form = WalkInReservationForm(request.POST or None, initial=initial)
    quantities = {}
    if request.method == "POST" and form.is_valid():
        selected = []
        reservation_type = form.cleaned_data["reservation_type"]
        invalid_quantity = False
        for item in menu_items:
            raw_quantity = request.POST.get(f"item_{item.pk}", "0")
            try:
                quantity = int(raw_quantity or 0)
            except (TypeError, ValueError):
                quantity = -1
            quantities[item.pk] = quantity
            if quantity < 0 or quantity > 99:
                invalid_quantity = True
            elif quantity:
                selected.append((item, quantity))
        if invalid_quantity:
            form.add_error(None, "Enter whole-number quantities from 0 to 99.")
        elif not selected:
            form.add_error(None, "Choose at least one menu item for this walk-in order.")
        else:
            food_total = sum((item.price * quantity for item, quantity in selected), Decimal("0"))
            selected_room = form.cleaned_data.get("room") if reservation_type == "ktv" else None
            duration_hours = form.cleaned_data.get("duration_hours") or 0
            room_fee = selected_room.hourly_price * duration_hours if selected_room else Decimal("0")
            total_due = food_total + room_fee
            payment_method = form.cleaned_data["payment_method"]
            cash_received = form.cleaned_data.get("cash_tendered") or Decimal("0")
            if payment_method == "cash" and cash_received < total_due:
                form.add_error("cash_tendered", f"Cash received must be at least ₱{total_due:.2f}.")
            else:
                now = timezone.localtime()
                reservation_time = form.cleaned_data["start_time"] if reservation_type == "ktv" else now.time().replace(second=0, microsecond=0)
                try:
                    with transaction.atomic():
                        table = None
                        room = None
                        if reservation_type == "dine_in":
                            table = DiningTable.objects.select_for_update().get(pk=form.cleaned_data["table"].pk, active=True, occupied=False)
                            active_statuses = [Reservation.Status.PENDING, Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED]
                            if Reservation.objects.select_for_update().filter(table=table, reservation_date=now.date(), status__in=active_statuses).exists():
                                raise DiningTable.DoesNotExist
                        else:
                            room = KTVRoom.objects.select_for_update().get(pk=selected_room.pk, active=True, status=KTVRoom.Status.AVAILABLE)
                            if not ktv_slot_available(room, now.date(), reservation_time, duration_hours):
                                raise KTVRoom.DoesNotExist
                        booking = Reservation.objects.create(
                            name=form.cleaned_data["name"], email=form.cleaned_data["email"],
                            phone=form.cleaned_data["phone"], reservation_date=now.date(),
                            reservation_time=reservation_time, guests=form.cleaned_data["guests"],
                            table=table, ktv_room=room, duration_hours=duration_hours if room else 0,
                            ktv_fee=room_fee, source=Reservation.Source.WALK_IN,
                            status=Reservation.Status.CONFIRMED,
                        )
                        order = FoodOrder.objects.create(
                            reservation=booking, payment_method=payment_method,
                            payment_status=FoodOrder.PaymentStatus.PAID,
                            order_status=FoodOrder.OrderStatus.NEW, amount=food_total,
                            gateway_reference=form.cleaned_data.get("gcash_reference", "") if payment_method == "gcash" else "",
                            cash_received=cash_received if payment_method == "cash" else Decimal("0"),
                            cash_change=cash_received - total_due if payment_method == "cash" else Decimal("0"),
                            paid_at=now,
                        )
                        OrderItem.objects.bulk_create([
                            OrderItem(order=order, menu_item=item, name=item.name, unit_price=item.price, quantity=quantity)
                            for item, quantity in selected
                        ])
                        if table:
                            table.occupied = True
                            table.save(update_fields=["occupied"])
                        else:
                            room.status = KTVRoom.Status.RESERVED
                            room.save(update_fields=["status"])
                        place = table.name if table else f"KTV room {room.name}"
                        ActivityLog.objects.create(
                            actor=user, action=f"Walk-in {payment_method} payment recorded", target=booking.reference,
                            details=f"{place}; food PHP {food_total:.2f}; KTV fee PHP {room_fee:.2f}; total PHP {total_due:.2f}; status {order.get_payment_status_display()}; reference {order.gateway_reference}; cash received PHP {cash_received:.2f}; change PHP {order.cash_change:.2f}.",
                        )
                except DiningTable.DoesNotExist:
                    form.add_error("table", "That table is no longer available. Choose another table.")
                except KTVRoom.DoesNotExist:
                    form.add_error("room", "That KTV room is no longer available. Choose another room or service.")
                else:
                    notify_operations(("admin", "staff"), "Walk-in order", f"Walk-in order {booking.reference} was recorded at {place}.")
                    return redirect("staff_receipt", order_id=order.pk)
    quantity_rows = [{"item": item, "quantity": quantities.get(item.pk, 0)} for item in menu_items]
    room_rates = {str(room.pk): str(room.hourly_price) for room in form.fields["room"].queryset}
    return render(request, "restaurant/staff_walkin.html", {
        "form": form,
        "quantity_rows": quantity_rows,
        "room_rates": room_rates,
        "site_content": SiteContent.objects.first(),
        "walkin_orders": FoodOrder.objects.filter(
            reservation__source=Reservation.Source.WALK_IN,
        ).select_related(
            "reservation", "reservation__table", "reservation__ktv_room",
        ).prefetch_related("items", "reservation__time_extensions").order_by("-created_at")[:30],
    })


@login_required(login_url="staff_login")
def staff_dashboard(request):
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied
    can_reservations = _staff_can(request.user, "view_staff_reservations", ("Cashier", "Kitchen Staff"))
    can_reservation_update = _staff_can(request.user, "change_staff_reservations", ("Cashier", "Kitchen Staff"))
    can_orders = _staff_can(request.user, "view_staff_orders", ("Cashier", "Kitchen Staff"))
    can_order_update = _staff_can(request.user, "change_staff_order_status", ("Cashier", "Kitchen Staff"))
    can_payments = _staff_can(request.user, "view_staff_payments", ("Cashier",))
    can_payment_update = _staff_can(request.user, "change_staff_payments", ("Cashier",))
    can_walkin = can_payment_update
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
                notify_operations(("admin", "staff"), "Payment update", f"Payment for {order.reservation.reference} was verified by staff.")
            else:
                order.payment_status = FoodOrder.PaymentStatus.REJECTED
                order.save(update_fields=["payment_status"])
                if order.reservation.source == Reservation.Source.WALK_IN:
                    if order.reservation.table_id:
                        DiningTable.objects.filter(pk=order.reservation.table_id).update(occupied=False)
                    if order.reservation.ktv_room_id:
                        KTVRoom.objects.filter(pk=order.reservation.ktv_room_id).update(status=KTVRoom.Status.AVAILABLE)
                    order.reservation.status = Reservation.Status.REJECTED
                    order.reservation.save(update_fields=["status"])
                _notify_customer(order.reservation, CustomerNotification.Kind.PAYMENT, f"Payment for {order.reservation.reference} was not accepted. Please contact Casa Sonata or submit payment again.")
                _log_staff(request.user, "Payment rejected", order.reservation.reference, f"Amount ₱{order.total_amount}; GCash reference {order.gateway_reference}")
                messages.info(request, f"Payment for {order.reservation.reference} rejected.")
                notify_operations(("admin", "staff"), "Payment update", f"Payment for {order.reservation.reference} was rejected by staff.")
        elif action == "update_reservation_status" and can_reservation_update:
            booking = get_object_or_404(Reservation.objects.select_related("table", "ktv_room", "customer"), pk=request.POST.get("reservation_id"))
            status = request.POST.get("status")
            allowed_statuses = [value for value, _ in booking.next_status_choices]
            if status not in allowed_statuses:
                messages.error(request, f"{booking.reference} can only move forward to an available reservation status.")
                return redirect("staff_dashboard")
            booking.status = status
            booking.save(update_fields=["status"])
            reservation_order_status = {
                Reservation.Status.CONFIRMED: FoodOrder.OrderStatus.NEW,
                Reservation.Status.PREPARING: FoodOrder.OrderStatus.PREPARING,
                Reservation.Status.READY: FoodOrder.OrderStatus.READY,
                Reservation.Status.SERVED: FoodOrder.OrderStatus.SERVED,
                Reservation.Status.COMPLETED: FoodOrder.OrderStatus.COMPLETED,
            }.get(status)
            if reservation_order_status:
                FoodOrder.objects.filter(reservation=booking).update(order_status=reservation_order_status)
            if booking.ktv_room_id and status in (Reservation.Status.PREPARING, Reservation.Status.READY):
                KTVRoom.objects.filter(pk=booking.ktv_room_id).exclude(status=KTVRoom.Status.MAINTENANCE).update(status=KTVRoom.Status.RESERVED)
            if status == Reservation.Status.READY:
                _notify_customer(booking, CustomerNotification.Kind.RESERVATION, _reservation_ready_message(booking))
            elif status == Reservation.Status.SERVED:
                if booking.table_id:
                    DiningTable.objects.filter(pk=booking.table_id).update(occupied=True)
                if booking.ktv_room_id:
                    KTVRoom.objects.filter(pk=booking.ktv_room_id).update(status=KTVRoom.Status.OCCUPIED)
            elif status == Reservation.Status.COMPLETED:
                if booking.table_id:
                    DiningTable.objects.filter(pk=booking.table_id).update(occupied=False)
                if booking.ktv_room_id:
                    KTVRoom.objects.filter(pk=booking.ktv_room_id).update(status=KTVRoom.Status.AVAILABLE)
            if status != Reservation.Status.READY:
                _notify_customer(booking, CustomerNotification.Kind.RESERVATION, f"Reservation {booking.reference} is now {booking.get_status_display().lower()}.")
            _log_staff(request.user, "Reservation status updated", booking.reference, booking.get_status_display())
            messages.success(request, f"Reservation {booking.reference} updated to {booking.get_status_display()}.")
        elif action == "update_order_status" and can_order_update:
            with transaction.atomic():
                order = get_object_or_404(FoodOrder.objects.select_for_update().select_related("reservation", "reservation__table", "reservation__ktv_room"), pk=request.POST.get("order_id"))
                booking = order.reservation
                status = request.POST.get("status")
                if order.payment_status != FoodOrder.PaymentStatus.PAID:
                    messages.error(request, "The payment must be verified before kitchen preparation can begin.")
                    return redirect("staff_dashboard")
                if booking.status in (Reservation.Status.CANCELLED, Reservation.Status.REJECTED, Reservation.Status.COMPLETED):
                    messages.error(request, "This reservation is closed and its order can no longer be advanced.")
                    return redirect("staff_dashboard")
                allowed_statuses = [value for value, _ in order.next_status_choices]
                if status not in allowed_statuses:
                    messages.error(request, "Choose a later order status: Preparing, Ready, Served, or Completed.")
                    return redirect("staff_dashboard")

                order.order_status = status
                order.save(update_fields=["order_status"])
                reservation_status = {
                    FoodOrder.OrderStatus.NEW: Reservation.Status.CONFIRMED,
                    FoodOrder.OrderStatus.PREPARING: Reservation.Status.PREPARING,
                    FoodOrder.OrderStatus.READY: Reservation.Status.READY,
                    FoodOrder.OrderStatus.SERVED: Reservation.Status.SERVED,
                    FoodOrder.OrderStatus.COMPLETED: Reservation.Status.COMPLETED,
                }[status]
                booking.status = reservation_status
                booking.save(update_fields=["status"])

                if booking.table_id:
                    DiningTable.objects.filter(pk=booking.table_id).update(occupied=status == FoodOrder.OrderStatus.SERVED)
                if booking.ktv_room_id:
                    room_status = KTVRoom.Status.AVAILABLE if status == FoodOrder.OrderStatus.COMPLETED else KTVRoom.Status.OCCUPIED if status == FoodOrder.OrderStatus.SERVED else KTVRoom.Status.RESERVED
                    KTVRoom.objects.filter(pk=booking.ktv_room_id).exclude(status=KTVRoom.Status.MAINTENANCE).update(status=room_status)

                if status == FoodOrder.OrderStatus.PREPARING:
                    place = f"KTV room {booking.ktv_room.name}" if booking.is_ktv else f"table {booking.table.name}" if booking.table_id else "your table"
                    notice = f"We're preparing your food and {place} for reservation {booking.reference}."
                elif status == FoodOrder.OrderStatus.READY:
                    place = f"KTV room {booking.ktv_room.name}" if booking.is_ktv else f"table {booking.table.name}" if booking.table_id else "your table"
                    notice = f"Your food and {place} are ready for reservation {booking.reference}."
                elif status == FoodOrder.OrderStatus.SERVED:
                    notice = f"Your order for reservation {booking.reference} is now served."
                else:
                    notice = f"Your order and reservation {booking.reference} are completed. Thank you for dining with Casa Sonata."
                _notify_customer(booking, CustomerNotification.Kind.ORDER, notice)
                _log_staff(request.user, "Order status updated", booking.reference, f"Order {order.get_order_status_display()}; reservation {booking.get_status_display()}")
                messages.success(request, f"Order {booking.reference} updated to {order.get_order_status_display()}; reservation status followed.")
        elif action == "toggle_table" and can_table_update:
            table = get_object_or_404(DiningTable, pk=request.POST.get("table_id"))
            table.occupied = request.POST.get("occupied") == "true"
            table.save(update_fields=["occupied"])
            _log_staff(request.user, "Table status updated", table.name, "Occupied" if table.occupied else "Available")
            messages.success(request, f"{table.name} marked {'occupied' if table.occupied else 'available'}.")
        elif action == "add_ktv_time" and can_ktv_update:
            try:
                extra_hours = int(request.POST.get("extra_hours", "0"))
                cash_received = Decimal(request.POST.get("cash_received", "0"))
            except (ValueError, InvalidOperation):
                extra_hours, cash_received = 0, Decimal("0")
            with transaction.atomic():
                booking = get_object_or_404(Reservation.objects.select_for_update().select_related("ktv_room", "customer"), pk=request.POST.get("reservation_id"), ktv_room__isnull=False)
                booking.ktv_room = KTVRoom.objects.select_for_update().get(pk=booking.ktv_room_id)
                if booking.status != Reservation.Status.SERVED:
                    messages.error(request, "Additional KTV time can only be approved while the room is in use.")
                elif not hasattr(booking, "food_order") or booking.food_order.payment_status != FoodOrder.PaymentStatus.PAID:
                    messages.error(request, "Verify the original reservation payment before adding KTV time.")
                elif extra_hours < 1 or extra_hours > 6:
                    messages.error(request, "Enter between 1 and 6 additional hours.")
                elif not cash_received.is_finite() or cash_received < 0:
                    messages.error(request, "Enter a valid cash amount for the added KTV time.")
                else:
                    rate = booking.ktv_room.hourly_price
                    extra_amount = rate * extra_hours
                    extended_duration = booking.duration_hours + booking.additional_ktv_hours + extra_hours
                    available = ktv_slot_available(booking.ktv_room, booking.reservation_date, booking.reservation_time, extended_duration, exclude_booking_id=booking.pk)
                    if not available:
                        messages.error(request, "This extension overlaps another KTV reservation for the room.")
                    elif cash_received < extra_amount:
                        messages.error(request, f"Collect at least PHP {extra_amount:.2f} for the approved extension.")
                    else:
                        extension = KTVTimeExtension.objects.create(
                            reservation=booking, hours=extra_hours, hourly_rate=rate,
                            amount=extra_amount, cash_received=cash_received,
                            cash_change=cash_received - extra_amount, recorded_by=request.user,
                        )
                        _notify_customer(booking, CustomerNotification.Kind.ORDER, f"{extra_hours} additional KTV hour(s) were approved and paid in cash. Additional charge: PHP {extra_amount:.2f}. The session now ends at {booking.scheduled_end_at:%I:%M %p}.")
                        _log_staff(request.user, "KTV time extension approved and paid", booking.reference, f"{extension.hours} hour(s) at PHP {rate}/hour; charge PHP {extra_amount:.2f}; cash received PHP {cash_received:.2f}; change PHP {extension.cash_change:.2f}.")
                        messages.success(request, f"Approved {extra_hours} additional hour(s) for {booking.ktv_room.name}; PHP {extension.cash_change:.2f} change.")
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
    def paid_total(queryset, extension_start, extension_end):
        values = queryset.aggregate(food=Sum("amount"), ktv=Sum("reservation__ktv_fee"))
        extensions = KTVTimeExtension.objects.filter(created_at__date__range=(extension_start, extension_end)).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return (values["food"] or Decimal("0")) + (values["ktv"] or Decimal("0")) + extensions
    def food_total(queryset):
        return queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    sales_today = paid_total(paid.filter(paid_at__date=today), today, today) if can_reports else Decimal("0")
    month_sales = paid_total(paid.filter(paid_at__date__gte=today.replace(day=1)), today.replace(day=1), today) if can_reports else Decimal("0")
    year_sales = paid_total(paid.filter(paid_at__date__gte=today.replace(month=1, day=1)), today.replace(month=1, day=1), today) if can_reports else Decimal("0")
    inventory_cost = sum((item.quantity * item.unit_cost for item in items), Decimal("0")) if can_reports else Decimal("0")
    weekly_sales = []
    for offset in range(6, -1, -1) if can_reports else ():
        day = today - timedelta(days=offset)
        value = paid_total(paid.filter(paid_at__date=day), day, day)
        weekly_sales.append({"label": day.strftime("%a"), "amount": value})
    active_reservation_statuses = (Reservation.Status.PENDING, Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED)
    reservations_today = Reservation.objects.filter(reservation_date=today, status__in=active_reservation_statuses).count() if can_reservations else 0
    active_order_statuses = (FoodOrder.OrderStatus.NEW, FoodOrder.OrderStatus.PREPARING, FoodOrder.OrderStatus.READY, FoodOrder.OrderStatus.SERVED)
    active_orders_count = FoodOrder.objects.filter(payment_status=FoodOrder.PaymentStatus.PAID, order_status__in=active_order_statuses).count() if can_orders else 0
    walkin_customers_today = Reservation.objects.filter(source=Reservation.Source.WALK_IN, reservation_date=today).count() if can_reservations else 0
    available_tables_count = DiningTable.objects.filter(active=True, occupied=False).exclude(
        reservations__reservation_date=today,
        reservations__status__in=active_reservation_statuses,
    ).distinct().count() if can_tables else 0
    active_ktv_rooms_count = KTVRoom.objects.filter(active=True).count() if can_ktv else 0
    pending_task_count = (pending.count() if can_payments else 0) + (FoodOrder.objects.filter(
        payment_status=FoodOrder.PaymentStatus.PAID,
        order_status__in=(FoodOrder.OrderStatus.NEW, FoodOrder.OrderStatus.PREPARING, FoodOrder.OrderStatus.READY, FoodOrder.OrderStatus.SERVED),
    ).count() if can_orders else 0)
    return render(request, "restaurant/staff_dashboard.html", {
        "today": today,
        "can_reservations": can_reservations, "can_reservation_update": can_reservation_update, "can_orders": can_orders,
        "can_order_update": can_order_update, "can_payments": can_payments,
        "can_payment_update": can_payment_update, "can_tables": can_tables,
        "can_walkin": can_walkin,
        "can_table_update": can_table_update, "can_inventory": can_inventory,
        "can_ktv": can_ktv, "can_ktv_update": can_ktv_update,
        "can_inventory_update": can_inventory_update, "can_movements": can_movements,
        "can_stock_update": can_stock_update, "can_reports": can_reports,
        "orders": FoodOrder.objects.select_related("reservation", "reservation__table", "reservation__ktv_room").prefetch_related("items").order_by("-created_at") if can_orders else FoodOrder.objects.none(),
        "payment_orders": FoodOrder.objects.select_related("reservation").order_by("-created_at")[:30] if can_payments else FoodOrder.objects.none(),
        "tables": DiningTable.objects.filter(active=True) if can_tables else DiningTable.objects.none(),
        "ktv_rooms": KTVRoom.objects.filter(active=True) if can_ktv else KTVRoom.objects.none(),
        "ktv_reservations_today": Reservation.objects.filter(ktv_room__isnull=False, reservation_date__gte=today - timedelta(days=1), status__in=[Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED]).select_related("ktv_room", "customer").prefetch_related("food_order__items", "time_extensions").order_by("reservation_date", "reservation_time")[:50] if can_ktv else Reservation.objects.none(),
        "ktv_cancellations": Reservation.objects.filter(ktv_room__isnull=False, status=Reservation.Status.CANCELLED).select_related("ktv_room", "customer").prefetch_related("food_order").order_by("-cancelled_at")[:20] if can_ktv else Reservation.objects.none(),
        "tables_occupied": DiningTable.objects.filter(active=True, occupied=True).count() if can_tables else 0,
        "pending_orders": pending, "inventory": items, "low_stock": items.filter(quantity__lte=F("low_stock_threshold")),
        "sales_today": sales_today, "reservations_today": reservations_today,
        "walkin_customers_today": walkin_customers_today,
        "active_orders_count": active_orders_count,
        "available_tables_count": available_tables_count,
        "active_ktv_rooms_count": active_ktv_rooms_count,
        "pending_task_count": pending_task_count,
        "ktv_income_today": (paid.filter(reservation__ktv_room__isnull=False, paid_at__date=today).aggregate(total=Sum("reservation__ktv_fee"))["total"] or Decimal("0")) + (KTVTimeExtension.objects.filter(created_at__date=today).aggregate(total=Sum("amount"))["total"] or Decimal("0")),
        "food_income_today": food_total(paid.filter(paid_at__date=today)),
        "ktv_reservation_count_today": Reservation.objects.filter(ktv_room__isnull=False, reservation_date=today).count(),
        "orders_today": FoodOrder.objects.filter(created_at__date=today).count(),
        "month_sales": month_sales, "year_sales": year_sales, "inventory_cost": inventory_cost,
        "estimated_net": year_sales - inventory_cost, "weekly_sales": weekly_sales,
        "customers": Reservation.objects.values("customer").distinct().count() if can_reports else 0,
        "recent_reservations": Reservation.objects.filter(status__in=[Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED]).select_related("table", "ktv_room").order_by("reservation_date", "reservation_time")[:100] if can_reservations else Reservation.objects.none(),
        "recent_movements": StockMovement.objects.select_related("item").order_by("-created_at")[:6] if can_movements else StockMovement.objects.none(),
        "dashboard_notifications": DashboardNotification.objects.filter(recipient=request.user, is_read=False)[:6],
        "dashboard_unread_count": DashboardNotification.objects.filter(recipient=request.user, is_read=False).count(),
    })


@login_required(login_url="staff_login")
def staff_receipt(request, order_id):
    if not request.user.is_staff or not _staff_can(request.user, "view_staff_payments", ("Cashier",)):
        raise PermissionDenied
    order = get_object_or_404(FoodOrder.objects.select_related("reservation", "reservation__ktv_room").prefetch_related("items", "reservation__time_extensions"), pk=order_id)
    return render(request, "restaurant/staff_receipt.html", {"order": order})


@user_passes_test(lambda user: user.is_active and user.is_superuser, login_url="login")
def admin_dashboard(request):
    today = localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    paid = FoodOrder.objects.filter(payment_status=FoodOrder.PaymentStatus.PAID)

    def paid_totals(queryset, extension_start, extension_end):
        totals = queryset.aggregate(food=Sum("amount"), ktv=Sum("reservation__ktv_fee"))
        extensions = KTVTimeExtension.objects.filter(created_at__date__range=(extension_start, extension_end)).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return (totals["food"] or Decimal("0")) + (totals["ktv"] or Decimal("0")) + extensions

    def ktv_income(queryset, extension_start, extension_end):
        room_income = queryset.filter(reservation__ktv_room__isnull=False).aggregate(total=Sum("reservation__ktv_fee"))["total"] or Decimal("0")
        extensions = KTVTimeExtension.objects.filter(reservation__ktv_room__isnull=False, created_at__date__range=(extension_start, extension_end)).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return room_income + extensions
    def food_income(queryset):
        return queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    def payment_breakdown(start, end):
        period = paid.filter(paid_at__date__range=(start, end))
        def source_total(source):
            amounts = period.filter(reservation__source=source).aggregate(food=Sum("amount"), ktv=Sum("reservation__ktv_fee"))
            extras = KTVTimeExtension.objects.filter(reservation__source=source, created_at__date__range=(start, end)).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            return (amounts["food"] or Decimal("0")) + (amounts["ktv"] or Decimal("0")) + extras
        def method_total(method):
            amounts = period.filter(payment_method=method).aggregate(food=Sum("amount"), ktv=Sum("reservation__ktv_fee"))
            extras = KTVTimeExtension.objects.filter(created_at__date__range=(start, end)).aggregate(total=Sum("amount"))["total"] or Decimal("0") if method == "cash" else Decimal("0")
            return (amounts["food"] or Decimal("0")) + (amounts["ktv"] or Decimal("0")) + extras
        return {"online": source_total(Reservation.Source.ONLINE), "walk_in": source_total(Reservation.Source.WALK_IN), "gcash": method_total("gcash"), "cash": method_total("cash"), "total": paid_totals(period, start, end)}

    def income_since(start):
        return paid_totals(paid.filter(paid_at__date__range=(start, today)), start, today)

    def expense_since(start):
        return Expense.objects.filter(expense_date__range=(start, today)).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    daily_income = paid_totals(paid.filter(paid_at__date=today), today, today)
    daily_expense = Expense.objects.filter(expense_date=today).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    weekly_income, weekly_expense = income_since(week_start), expense_since(week_start)
    monthly_income, monthly_expense = income_since(month_start), expense_since(month_start)
    yearly_income, yearly_expense = income_since(year_start), expense_since(year_start)
    week_chart = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        income = paid_totals(paid.filter(paid_at__date=day), day, day)
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
    upcoming_events = Event.objects.filter(
        status__in=[Event.Status.PUBLISHED, Event.Status.ONGOING],
        event_date__gte=today,
    ).order_by("event_date", "start_time")
    upcoming_event_count = upcoming_events.count()
    upcoming_events = upcoming_events[:5]
    recent_table_orders = FoodOrder.objects.filter(reservation__table__isnull=False).select_related("reservation", "reservation__table").prefetch_related("items").order_by("-created_at")[:10]
    ktv_reservations = Reservation.objects.filter(ktv_room__isnull=False).select_related("ktv_room", "customer").prefetch_related("food_order__items", "time_extensions").order_by("-reservation_date", "-reservation_time")[:25]
    ktv_cancellations = Reservation.objects.filter(ktv_room__isnull=False, status=Reservation.Status.CANCELLED).select_related("ktv_room", "customer").prefetch_related("food_order").order_by("-cancelled_at")[:25]
    today_breakdown = payment_breakdown(today, today)
    pending_online_payments = FoodOrder.objects.filter(
        payment_status=FoodOrder.PaymentStatus.PENDING,
        payment_method="gcash",
        reservation__source=Reservation.Source.ONLINE,
    ).select_related("reservation").prefetch_related("items").order_by("created_at")[:6]
    recent_transactions = paid.select_related(
        "reservation", "reservation__table", "reservation__ktv_room",
    ).prefetch_related("items").order_by("-paid_at")[:8]
    recent_orders = FoodOrder.objects.select_related(
        "reservation", "reservation__table", "reservation__ktv_room",
    ).prefetch_related("items").order_by("-created_at")[:8]
    ktv_bookings_today = Reservation.objects.filter(
        ktv_room__isnull=False,
        reservation_date=today,
    ).exclude(status__in=(Reservation.Status.CANCELLED, Reservation.Status.REJECTED)).select_related("ktv_room").prefetch_related("time_extensions").order_by("reservation_time")
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
        "online_pending_payments": FoodOrder.objects.filter(
            payment_status=FoodOrder.PaymentStatus.PENDING,
            reservation__source=Reservation.Source.ONLINE,
        ).count(),
        "walkin_pending_payments": FoodOrder.objects.filter(
            payment_status=FoodOrder.PaymentStatus.PENDING,
            reservation__source=Reservation.Source.WALK_IN,
        ).count(),
        "upcoming_events": upcoming_events, "upcoming_event_count": upcoming_event_count,
        "low_inventory": low_inventory, "staff_count": request.user.__class__.objects.filter(is_staff=True, is_active=True, is_superuser=False).count(),
        "supplier_count": Supplier.objects.count(), "inventory_count": InventoryItem.objects.count(),
        "notification_count": open_stock_alerts.count() + DashboardNotification.objects.filter(recipient=request.user, is_read=False).count(),
        "dashboard_notifications": DashboardNotification.objects.filter(recipient=request.user, is_read=False)[:6],
        "dashboard_unread_count": DashboardNotification.objects.filter(recipient=request.user, is_read=False).count(),
        "open_stock_alerts": open_stock_alerts,
        "out_of_stock_count": InventoryItem.objects.filter(quantity__lte=0).count(),
        "occupied_tables": DiningTable.objects.filter(active=True, occupied=True).count(),
        "active_ktv_rooms": KTVRoom.objects.filter(active=True).count(),
        "weekly_orders": weekly_orders, "monthly_orders": monthly_orders,
        "popular_items": popular_items, "table_metrics": table_metrics,
        "recent_table_orders": recent_table_orders,
        "ktv_reservations": ktv_reservations,
        "ktv_cancellations": ktv_cancellations,
        "today_breakdown": today_breakdown,
        "pending_online_payments": pending_online_payments,
        "recent_transactions": recent_transactions,
        "recent_orders": recent_orders,
        "ktv_bookings_today": ktv_bookings_today,
        "ktv_rooms": KTVRoom.objects.all(),
        "ktv_income_today": ktv_income(paid.filter(paid_at__date=today), today, today),
        "ktv_income_week": ktv_income(paid.filter(paid_at__date__range=(week_start, today)), week_start, today),
        "ktv_income_month": ktv_income(paid.filter(paid_at__date__range=(month_start, today)), month_start, today),
        "ktv_income_year": ktv_income(paid.filter(paid_at__date__range=(year_start, today)), year_start, today),
        "food_income_today": food_income(paid.filter(paid_at__date=today)),
        "food_income_week": food_income(paid.filter(paid_at__date__range=(week_start, today))),
        "food_income_month": food_income(paid.filter(paid_at__date__range=(month_start, today))),
        "food_income_year": food_income(paid.filter(paid_at__date__range=(year_start, today))),
        "payment_breakdowns": [
            ("Today", payment_breakdown(today, today)),
            ("This week", payment_breakdown(week_start, today)),
            ("This month", payment_breakdown(month_start, today)),
            ("This year", payment_breakdown(year_start, today)),
        ],
        "tables": DiningTable.objects.filter(active=True).order_by("name"),
        "recent_activity": ActivityLog.objects.select_related("actor")[:12],
    })


@login_required
def notification_center(request):
    can_view_operations = request.user.is_staff or request.user.is_superuser
    if request.method == "POST":
        dashboard_notes = DashboardNotification.objects.filter(recipient=request.user) if can_view_operations else DashboardNotification.objects.none()
        if request.POST.get("dashboard_notification_id"):
            note = get_object_or_404(dashboard_notes, pk=request.POST.get("dashboard_notification_id"))
            note.is_read = True
            note.save(update_fields=["is_read"])
            messages.success(request, "Notification marked as read.")
            return redirect("notification_center")
        if can_view_operations:
            notes = CustomerNotification.objects.none()
        else:
            notes = CustomerNotification.objects.filter(customer=request.user)
        if request.POST.get("action") == "mark_all_read":
            dashboard_notes.filter(is_read=False).update(is_read=True)
            notes.filter(is_read=False).update(is_read=True)
            messages.success(request, "Notifications marked as read.")
        elif request.POST.get("action") == "mark_read":
            note = get_object_or_404(notes, pk=request.POST.get("notification_id"))
            note.is_read = True
            note.save(update_fields=["is_read"])
            messages.success(request, "Notification marked as read.")
        return redirect("notification_center")

    entries = []
    dashboard_notes = DashboardNotification.objects.filter(recipient=request.user) if can_view_operations else DashboardNotification.objects.none()
    unread_count = dashboard_notes.filter(is_read=False).count()
    if request.user.is_superuser:
        customer_notes = CustomerNotification.objects.none()
        stock_alerts = StockAlert.objects.select_related("item").all()
        unread_count += customer_notes.filter(is_read=False).count() + stock_alerts.filter(is_resolved=False).count()
    elif request.user.is_staff:
        can_view_inventory = _staff_can(request.user, "view_inventoryitem", ("Inventory Staff",))
        customer_notes = CustomerNotification.objects.none()
        stock_alerts = StockAlert.objects.filter(is_resolved=False).select_related("item") if can_view_inventory else StockAlert.objects.none()
        unread_count += stock_alerts.count()
    else:
        customer_notes = CustomerNotification.objects.filter(customer=request.user).select_related("reservation")
        stock_alerts = StockAlert.objects.none()
        unread_count += customer_notes.filter(is_read=False).count()

    for note in dashboard_notes:
        entries.append({
            "id": f"ops-{note.pk}", "kind": note.kind, "message": note.message,
            "created_at": note.created_at, "is_read": note.is_read, "dashboard_note": note,
        })

    for note in customer_notes:
        entries.append({
            "id": f"customer-{note.pk}", "kind": note.get_kind_display(), "message": note.message,
            "created_at": note.created_at, "is_read": note.is_read, "customer_note": note,
        })
    for alert in stock_alerts:
        entries.append({
            "id": f"stock-{alert.pk}", "kind": "Inventory", "message": alert.message,
            "created_at": alert.created_at, "is_read": alert.is_resolved, "stock_alert": alert,
        })
    entries.sort(key=lambda entry: entry["created_at"], reverse=True)
    return render(request, "restaurant/notifications.html", {"entries": entries, "unread_count": unread_count})


ADMIN_MODULES = {
    "reservations": (Reservation, "Reservations", ("reference", "customer", "cancelled_at", "created_at"), None),
    "tables": (DiningTable, "Dine-in tables", (), None),
    "ktv": (KTVRoom, "KTV rooms", (), None),
    "orders": (FoodOrder, "Food orders", ("created_at", "paid_at"), ("reservation", "order_status", "gateway_reference", "amount")),
    "menu-categories": (MenuCategory, "Menu categories", (), None),
    "menu": (MenuItem, "Menu items", (), None),
    "gallery": (GalleryImage, "Gallery", (), None),
    "events": (Event, "Events", ("created_at", "updated_at"), None),
    "inventory": (InventoryItem, "Inventory", ("quantity", "updated_at"), None),
    "suppliers": (Supplier, "Suppliers", (), None),
    "expenses": (Expense, "Expenses", ("created_at",), None),
    "website": (SiteContent, "Website content", (), None),
}


@user_passes_test(lambda user: user.is_active and user.is_superuser, login_url="login")
def admin_module(request, module, object_id=None):
    """Custom, administrator-only record manager for restaurant data."""
    from django.http import Http404

    staff_module = module == "staff"
    customer_module = module == "customers"
    read_only = customer_module
    if staff_module or customer_module:
        from django.contrib.auth import get_user_model
        model = get_user_model()
        title, exclude, fields = ("Staff accounts", (), None) if staff_module else ("Customers", (), None)
    else:
        config = ADMIN_MODULES.get(module)
        if not config:
            raise Http404
        model, title, exclude, fields = config
    singleton = model is SiteContent
    instance = None
    if singleton:
        instance = model.objects.first()
        if object_id is not None or request.method == "POST" or request.GET.get("edit"):
            object_id = instance.pk if instance else None
    if object_id is not None:
        if staff_module:
            instance = get_object_or_404(model, pk=object_id, is_staff=True, is_superuser=False)
        elif customer_module:
            instance = get_object_or_404(model, pk=object_id, is_staff=False, is_superuser=False)
        else:
            instance = get_object_or_404(model, pk=object_id)
    editing = instance is not None
    if customer_module:
        FormClass = None
    elif staff_module:
        FormClass = StaffAccountForm
    elif fields:
        FormClass = modelform_factory(model, fields=fields)
    else:
        FormClass = modelform_factory(model, exclude=exclude)
    if request.method == "POST" and not read_only:
        form = FormClass(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            previous_status = instance.status if module == "reservations" and instance else None
            record = form.save()
            details = ""
            if module == "reservations" and previous_status != record.status:
                details = f"Reservation status: {record.get_status_display()}"
                if record.status == Reservation.Status.READY:
                    _notify_customer(record, CustomerNotification.Kind.RESERVATION, _reservation_ready_message(record))
                else:
                    _notify_customer(record, CustomerNotification.Kind.RESERVATION, f"Reservation {record.reference} is now {record.get_status_display().lower()}.")
                if record.status == Reservation.Status.CANCELLED:
                    notify_operations(("staff", "admin"), "Cancelled reservation", f"Reservation {record.reference} was cancelled.")
                if record.ktv_room_id and record.status in (Reservation.Status.PREPARING, Reservation.Status.READY):
                    KTVRoom.objects.filter(pk=record.ktv_room_id).exclude(status=KTVRoom.Status.MAINTENANCE).update(status=KTVRoom.Status.RESERVED)
                if record.status == Reservation.Status.SERVED:
                    if record.table_id:
                        DiningTable.objects.filter(pk=record.table_id).update(occupied=True)
                    if record.ktv_room_id:
                        KTVRoom.objects.filter(pk=record.ktv_room_id).update(status=KTVRoom.Status.OCCUPIED)
                if record.status in (Reservation.Status.COMPLETED, Reservation.Status.CANCELLED):
                    if record.table_id:
                        DiningTable.objects.filter(pk=record.table_id).update(occupied=False)
                    if record.ktv_room_id:
                        KTVRoom.objects.filter(pk=record.ktv_room_id).update(status=KTVRoom.Status.AVAILABLE)
            ActivityLog.objects.create(actor=request.user, action="Updated" if editing else "Created", target=f"{title}: {record}", details=details)
            messages.success(request, f"{title[:-1] if title.endswith('s') else title} saved.")
            return redirect("admin_module", module=module)
    elif not read_only:
        form = FormClass(instance=instance)
    else:
        form = None
    if staff_module:
        queryset = model.objects.filter(is_staff=True, is_superuser=False).order_by("username")
    elif customer_module:
        queryset = model.objects.filter(is_staff=False, is_superuser=False).prefetch_related("restaurant_reservations__food_order__items").order_by("username")
    elif module == "orders":
        queryset = model.objects.select_related("reservation", "reservation__table", "reservation__ktv_room").prefetch_related("items").order_by("-created_at")
    elif module == "tables":
        queryset = model.objects.prefetch_related(Prefetch(
            "reservations", queryset=Reservation.objects.filter(reservation_date=localdate()).select_related("customer").prefetch_related("food_order__items"),
        )).order_by("name")
    elif module == "ktv":
        queryset = model.objects.prefetch_related("reservations__customer", "reservations__food_order__items").order_by("name")
    elif module == "inventory":
        queryset = model.objects.select_related("supplier").order_by("quantity", "name")
    elif module == "events":
        queryset = model.objects.order_by("-event_date", "start_time")
    else:
        queryset = model.objects.all().order_by("pk")
    return render(request, "restaurant/admin_module.html", {
        "module": module, "title": title, "form": form, "editing": editing,
        "records": queryset, "can_add": not singleton or not queryset.exists(),
        "singleton": singleton, "read_only": read_only,
    })


@user_passes_test(lambda user: user.is_active and user.is_superuser, login_url="login")
def admin_payments(request):
    if request.method == "POST":
        order = get_object_or_404(FoodOrder.objects.select_related("reservation"), pk=request.POST.get("order_id"))
        if order.payment_status != FoodOrder.PaymentStatus.PENDING:
            messages.error(request, "Only pending payments can be reviewed.")
            return redirect("admin_payments")
        if request.POST.get("decision") == "accept":
            order.payment_status = FoodOrder.PaymentStatus.PAID
            order.paid_at = timezone.now()
            order.reservation.status = Reservation.Status.CONFIRMED
            order.reservation.save(update_fields=["status"])
            order.save(update_fields=["payment_status", "paid_at"])
            _notify_customer(order.reservation, CustomerNotification.Kind.PAYMENT, f"Payment for {order.reservation.reference} was accepted. Your reservation is confirmed.")
            action = "Payment accepted"
        elif request.POST.get("decision") == "reject":
            order.payment_status = FoodOrder.PaymentStatus.REJECTED
            order.save(update_fields=["payment_status"])
            if order.reservation.source == Reservation.Source.WALK_IN:
                if order.reservation.table_id:
                    DiningTable.objects.filter(pk=order.reservation.table_id).update(occupied=False)
                if order.reservation.ktv_room_id:
                    KTVRoom.objects.filter(pk=order.reservation.ktv_room_id).update(status=KTVRoom.Status.AVAILABLE)
                order.reservation.status = Reservation.Status.REJECTED
                order.reservation.save(update_fields=["status"])
            _notify_customer(order.reservation, CustomerNotification.Kind.PAYMENT, f"Payment for {order.reservation.reference} was not accepted. Please review and submit payment again.")
            action = "Payment rejected"
        else:
            raise PermissionDenied
        ActivityLog.objects.create(actor=request.user, action=action, target=order.reservation.reference, details=f"Amount {order.total_amount}; GCash reference {order.gateway_reference}")
        notify_operations(("staff",), "Payment update", f"{action} for {order.reservation.reference} by an administrator.")
        messages.success(request, f"{order.reservation.reference}: {action.lower()}.")
        return redirect("admin_payments")
    payments = FoodOrder.objects.select_related("reservation", "reservation__customer", "reservation__table", "reservation__ktv_room").prefetch_related("items").order_by("payment_status", "-created_at")
    filters = {key: request.GET.get(key, "") for key in ("payment_method", "source", "status", "date_from", "date_to")}
    if filters["payment_method"]:
        payments = payments.filter(payment_method=filters["payment_method"])
    if filters["source"]:
        payments = payments.filter(reservation__source=filters["source"])
    if filters["status"]:
        payments = payments.filter(payment_status=filters["status"])
    if filters["date_from"]:
        payments = payments.filter(created_at__date__gte=filters["date_from"])
    if filters["date_to"]:
        payments = payments.filter(created_at__date__lte=filters["date_to"])
    return render(request, "restaurant/admin_payments.html", {"payments": payments, "filters": filters})


@user_passes_test(lambda user: user.is_active and user.is_superuser, login_url="login")
@require_POST
def admin_stock_action(request):
    item = get_object_or_404(InventoryItem, pk=request.POST.get("item_id"))
    try:
        quantity = Decimal(request.POST.get("quantity", "0"))
    except (InvalidOperation, ValueError, TypeError):
        quantity = Decimal("0")
    action = request.POST.get("action")
    if not quantity.is_finite() or quantity <= 0 or action not in ("in", "usage") or (action == "usage" and quantity > item.quantity):
        messages.error(request, "Enter a positive quantity. Stock usage cannot exceed the current stock.")
        return redirect("admin_module", module="inventory")
    with transaction.atomic():
        item.quantity += quantity if action == "in" else -quantity
        item.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(item=item, kind=StockMovement.Kind.STOCK_IN if action == "in" else StockMovement.Kind.USAGE, quantity=quantity, note=request.POST.get("note", ""))
        ActivityLog.objects.create(actor=request.user, action="Inventory stock in" if action == "in" else "Inventory usage", target=item.name, details=f"{quantity} {item.unit}; {request.POST.get('note', '')}")
    messages.success(request, f"Inventory updated for {item.name}.")
    return redirect("admin_module", module="inventory")


@user_passes_test(lambda user: user.is_active and user.is_superuser, login_url="login")
def admin_receipt(request, order_id):
    order = get_object_or_404(FoodOrder.objects.select_related("reservation", "reservation__table", "reservation__ktv_room").prefetch_related("items"), pk=order_id)
    return render(request, "restaurant/staff_receipt.html", {"order": order})


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
