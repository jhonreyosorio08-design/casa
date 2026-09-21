import hashlib
import hmac
import json
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import ReservationForm
from .models import FoodOrder, GalleryImage, MenuCategory, MenuItem, OrderItem, Reservation

PREORDER_CATEGORIES = ["Pasta", "Salad", "Snacks", "Dessert", "Waffles", "Mains", "Grilled", "Soup"]


def home(request):
    featured = MenuItem.objects.filter(featured=True, available=True)[:3]
    return render(request, "restaurant/home.html", {"featured": featured, "gallery": GalleryImage.objects.all()[:4]})


def menu(request):
    return render(request, "restaurant/menu.html", {"categories": MenuCategory.objects.prefetch_related("items")})


def about(request): return render(request, "restaurant/about.html")
def gallery(request): return render(request, "restaurant/gallery.html", {"gallery": GalleryImage.objects.all()})
def contact(request): return render(request, "restaurant/contact.html")


def reservation(request):
    form = ReservationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        booking = form.save()
        request.session["reservation_id"] = booking.pk
        return redirect("preorder", reference=booking.reference)
    return render(request, "restaurant/reservation.html", {"form": form})


def preorder(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference)
    menu_items = MenuItem.objects.filter(available=True, category__name__in=PREORDER_CATEGORIES).select_related("category")
    order, _ = FoodOrder.objects.get_or_create(reservation=reservation)
    if request.method == "POST":
        with transaction.atomic():
            order.items.all().delete()
            for item in menu_items:
                quantity = int(request.POST.get(f"item_{item.pk}", 0) or 0)
                if quantity > 0:
                    OrderItem.objects.create(order=order, menu_item=item, name=item.name, unit_price=item.price, quantity=quantity)
            if not order.items.exists():
                messages.error(request, "Please add at least one food or beverage item before continuing.")
            else:
                order.recalculate_total()
                return redirect("checkout", reference=reservation.reference)
    quantities = {item.menu_item_id: item.quantity for item in order.items.all()}
    categories = MenuCategory.objects.filter(name__in=PREORDER_CATEGORIES).prefetch_related(
        Prefetch("items", queryset=menu_items, to_attr="preorder_items")
    )
    return render(request, "restaurant/preorder.html", {"reservation": reservation, "categories": categories, "quantities": quantities})


def checkout(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference)
    order = get_object_or_404(FoodOrder.objects.prefetch_related("items"), reservation=reservation)
    if not order.items.exists(): return redirect("preorder", reference=reference)
    if request.method == "POST":
        # A real GCash gateway redirects from here; credentials are configured outside source control.
        order.payment_method = "gcash"
        order.gateway_reference = f"GCASH-{reservation.reference}"
        order.save(update_fields=["payment_method", "gateway_reference"])
        return redirect("payment_pending", reference=reference)
    return render(request, "restaurant/checkout.html", {"reservation": reservation, "order": order})


def payment_pending(request, reference):
    reservation = get_object_or_404(Reservation, reference=reference)
    order = get_object_or_404(FoodOrder, reservation=reservation)
    return render(request, "restaurant/payment_pending.html", {"reservation": reservation, "order": order})


@csrf_exempt
@require_POST
def payment_webhook(request):
    secret = getattr(settings, "GCASH_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Casa-Signature", "")
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(signature, expected): return HttpResponseForbidden("Invalid webhook signature")
    payload = json.loads(request.body)
    order = get_object_or_404(FoodOrder, gateway_reference=payload.get("gateway_reference"))
    if payload.get("status") == "paid":
        order.payment_status = FoodOrder.PaymentStatus.PAID
        order.paid_at = timezone.now()
        order.save(update_fields=["payment_status", "paid_at"])
        order.reservation.status = Reservation.Status.CONFIRMED
        order.reservation.save(update_fields=["status"])
    return JsonResponse({"ok": True})
