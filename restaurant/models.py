import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import MinValueValidator


class MenuCategory(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "menu categories"

    def __str__(self): return self.name


class MenuItem(models.Model):
    category = models.ForeignKey(MenuCategory, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=120)
    description = models.TextField()
    price = models.DecimalField(max_digits=8, decimal_places=2)
    image = models.ImageField(upload_to="menu/", blank=True, null=True)
    featured = models.BooleanField(default=False)
    available = models.BooleanField(default=True)

    class Meta: ordering = ["category", "name"]
    def __str__(self): return self.name


class GalleryImage(models.Model):
    title = models.CharField(max_length=120)
    image = models.ImageField(upload_to="gallery/")
    caption = models.CharField(max_length=220, blank=True)
    category = models.CharField(max_length=80, blank=True, help_text="For example: Food, Interior, or Events")
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    class Meta: ordering = ["order", "title"]
    def __str__(self): return self.title


class Event(models.Model):
    class Category(models.TextChoices):
        LIVE_MUSIC = "live_music", "Live music"
        ACOUSTIC = "acoustic", "Acoustic night"
        DINING = "dining", "Special dining night"
        HOLIDAY = "holiday", "Holiday celebration"
        KTV = "ktv", "KTV event"
        PROMOTION = "promotion", "Food promotion"
        BIRTHDAY = "birthday", "Birthday event"
        PRIVATE = "private", "Private gathering"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class ReservationOption(models.TextChoices):
        NONE = "none", "No reservation link"
        TABLE = "table", "Dine-in table"
        KTV = "ktv", "KTV room"
        BOTH = "both", "Table and KTV"

    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField()
    image = models.ImageField(upload_to="events/", blank=True, null=True)
    event_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=180, default="Casa Sonata")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    additional_details = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    featured = models.BooleanField(default=False)
    reservation_option = models.CharField(max_length=8, choices=ReservationOption.choices, default=ReservationOption.NONE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event_date", "start_time", "title"]

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            from django.core.exceptions import ValidationError
            raise ValidationError({"end_time": "The event end time must be after the start time."})

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "event"
            candidate = base_slug
            suffix = 2
            while Event.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = "{}-{}".format(base_slug, suffix)
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def display_status(self):
        if self.status in (self.Status.DRAFT, self.Status.CANCELLED, self.Status.COMPLETED):
            return self.get_status_display()
        now = timezone.localtime()
        if self.event_date < now.date() or (self.event_date == now.date() and self.end_time <= now.time()):
            return self.Status.COMPLETED.label
        if self.event_date == now.date() and self.start_time <= now.time() < self.end_time:
            return self.Status.ONGOING.label
        return self.get_status_display()

    @property
    def is_past(self):
        return self.display_status == self.Status.COMPLETED.label or self.event_date < timezone.localdate()

    def __str__(self):
        return self.title


class SiteContent(models.Model):
    """Editable copy and contact details shared by the public site."""
    restaurant_name = models.CharField(max_length=120, default="Casa Sonata")
    tagline = models.CharField(max_length=180, default="Contemporary Italian kitchen")
    hero_title = models.CharField(max_length=180, default="Every meal, a little sonata.")
    hero_description = models.TextField(default="An intimate neighborhood table for seasonal cooking and the pleasure of staying awhile.")
    hero_image = models.ImageField(upload_to="site/", blank=True)
    introduction_title = models.CharField(max_length=180, default="The kind of place you find yourself returning to.")
    introduction = models.TextField(default="Casa Sonata brings the warmth of an Italian home to the heart of the city.")
    about_title = models.CharField(max_length=180, default="Born from a love of feeding people well.")
    about_story = models.TextField(default="Casa Sonata began with a simple dream: create the kind of restaurant that feels like the home of a dear friend with exceptional taste.")
    address = models.TextField(default="18 Via del Teatro\n20121 Milano, Italy")
    phone = models.CharField(max_length=60, default="+39 02 555 0199")
    email = models.EmailField(default="ciao@casasonata.it")
    opening_hours = models.TextField(default="Tuesday – Thursday: 5:30pm – 11pm\nFriday – Sunday: 5:30pm – 11:30pm\nMonday: Closed")
    announcement = models.CharField(max_length=240, blank=True)
    private_dining_text = models.TextField(default="For intimate celebrations, team dinners, and everything worth marking, our private dining room is yours.")

    def __str__(self): return "Public website content"


class DiningTable(models.Model):
    name = models.CharField(max_length=40, unique=True)
    seats = models.PositiveSmallIntegerField()
    active = models.BooleanField(default=True)
    occupied = models.BooleanField(default=False)

    class Meta:
        ordering = ["seats", "name"]
        permissions = [("view_staff_tables", "Can view table service status"), ("change_staff_tables", "Can update table service status")]

    @property
    def current_status_label(self):
        if not self.active:
            return "Unavailable"
        if self.occupied:
            return "Occupied"
        now = timezone.localtime()
        active_statuses = [Reservation.Status.PENDING, Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED]
        if self.reservations.filter(reservation_date=now.date(), food_order__order_status=FoodOrder.OrderStatus.PREPARING).exists():
            return "Preparing"
        if self.reservations.filter(reservation_date__gte=now.date(), status__in=active_statuses).exists():
            return "Reserved"
        return "Available"

    def __str__(self): return f"{self.name} ({self.seats} seats)"


class KTVRoom(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        OCCUPIED = "occupied", "Occupied"
        COMPLETED = "completed", "Completed"
        MAINTENANCE = "maintenance", "Maintenance"

    name = models.CharField(max_length=40, unique=True)
    room_type = models.CharField(max_length=40)
    min_capacity = models.PositiveSmallIntegerField()
    max_capacity = models.PositiveSmallIntegerField()
    hourly_price = models.DecimalField(max_digits=8, decimal_places=2)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="ktv_rooms/", blank=True)
    active = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        ordering = ["name"]
        permissions = [("change_staff_ktv_room_status", "Can update KTV room service status")]

    def __str__(self):
        return self.name

    @property
    def current_status_label(self):
        if self.status == self.Status.MAINTENANCE:
            return self.Status.MAINTENANCE.label
        if self.status in (self.Status.OCCUPIED, self.Status.COMPLETED):
            return self.get_status_display()
        now = timezone.localtime()
        for booking in self.reservations.filter(
            reservation_date__gte=now.date(),
            status__in=[Reservation.Status.PENDING, Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED],
        ):
            starts_at = datetime.combine(booking.reservation_date, booking.reservation_time)
            if timezone.is_naive(starts_at):
                starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
            ends_at = starts_at + timedelta(hours=booking.duration_hours)
            if ends_at > now:
                return "Reserved"
        return self.get_status_display()

    @property
    def next_status_choices(self):
        transitions = {
            self.Status.AVAILABLE: (self.Status.RESERVED,),
            self.Status.RESERVED: (self.Status.OCCUPIED,),
            self.Status.OCCUPIED: (self.Status.COMPLETED,),
            self.Status.COMPLETED: (self.Status.AVAILABLE,),
        }
        allowed = transitions.get(self.status, ())
        return tuple((value, self.Status(value).label) for value in allowed)


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CONFIRMED = "confirmed", "Reserved"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"
        CANCELLED = "cancelled", "Cancelled"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    reference = models.CharField(max_length=20, unique=True, editable=False, default="")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="restaurant_reservations", null=True, blank=True)
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30)
    reservation_date = models.DateField()
    reservation_time = models.TimeField()
    guests = models.PositiveSmallIntegerField()
    table = models.ForeignKey(DiningTable, on_delete=models.PROTECT, related_name="reservations", null=True, blank=True)
    ktv_room = models.ForeignKey(KTVRoom, on_delete=models.PROTECT, related_name="reservations", null=True, blank=True)
    duration_hours = models.PositiveSmallIntegerField(default=0)
    ktv_fee = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    special_requests = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["reservation_date", "reservation_time"]
        permissions = [
            ("view_staff_reservations", "Can view staff reservation details"),
            ("change_staff_reservations", "Can update staff reservation status"),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"CS-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_ktv(self):
        return self.ktv_room_id is not None

    @property
    def total_amount(self):
        food_amount = self.food_order.amount if hasattr(self, "food_order") else Decimal("0")
        return self.ktv_fee + self.additional_ktv_fee + food_amount

    @property
    def additional_ktv_hours(self):
        if not self.is_ktv:
            return 0
        return sum(extension.hours for extension in self.time_extensions.all())

    @property
    def additional_ktv_fee(self):
        if not self.is_ktv:
            return Decimal("0")
        return sum((extension.amount for extension in self.time_extensions.all()), Decimal("0"))

    @property
    def scheduled_start_at(self):
        start_at = datetime.combine(self.reservation_date, self.reservation_time)
        return timezone.make_aware(start_at, timezone.get_current_timezone()) if timezone.is_naive(start_at) else start_at

    @property
    def scheduled_end_at(self):
        return self.scheduled_start_at + timedelta(hours=self.duration_hours + self.additional_ktv_hours)

    @property
    def ktv_timing_status(self):
        if not self.is_ktv:
            return ""
        if self.status == self.Status.COMPLETED:
            return "Completed"
        if self.status == self.Status.CANCELLED:
            return "Cancelled"
        now = timezone.now()
        if now < self.scheduled_start_at:
            return "Upcoming"
        seconds_left = (self.scheduled_end_at - now).total_seconds()
        if seconds_left <= 0:
            return "Overdue"
        if seconds_left <= 15 * 60:
            return "Ending Soon"
        return "Active"

    @property
    def can_cancel_ktv(self):
        if not self.is_ktv or self.status in (self.Status.CANCELLED, self.Status.COMPLETED):
            return False
        starts_at = datetime.combine(self.reservation_date, self.reservation_time)
        if timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
        return timezone.now() < starts_at

    @property
    def next_status_choices(self):
        transitions = {
            self.Status.CONFIRMED: (self.Status.PREPARING,),
            self.Status.PREPARING: (self.Status.READY,),
            self.Status.READY: (self.Status.SERVED,),
            self.Status.SERVED: (self.Status.COMPLETED,),
        }
        allowed = transitions.get(self.status, ())
        return tuple((value, self.Status(value).label) for value in allowed)

    def __str__(self): return f"{self.reference} · {self.name}"


class KTVTimeExtension(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="time_extensions")
    hours = models.PositiveSmallIntegerField()
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    amount = models.DecimalField(max_digits=9, decimal_places=2)
    cash_received = models.DecimalField(max_digits=9, decimal_places=2)
    cash_change = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ktv_time_extensions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.reservation.reference} +{self.hours} KTV hour(s)"


class FoodOrder(models.Model):
    class OrderStatus(models.TextChoices):
        NEW = "new", "New"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"
        COMPLETED = "completed", "Completed"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pending verification"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    reservation = models.OneToOneField(Reservation, on_delete=models.CASCADE, related_name="food_order")
    payment_method = models.CharField(max_length=30, default="gcash")
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    order_status = models.CharField(max_length=12, choices=OrderStatus.choices, default=OrderStatus.NEW)
    gateway_reference = models.CharField(max_length=160, blank=True)
    payment_proof = models.ImageField(upload_to="payment_proofs/", blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_received = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_change = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("view_staff_orders", "Can view food orders in staff interface"),
            ("change_staff_order_status", "Can update food order status"),
            ("view_staff_payments", "Can view customer payment details"),
            ("change_staff_payments", "Can approve or reject customer payments"),
            ("view_staff_reports", "Can view financial reports"),
        ]

    def recalculate_total(self):
        total = sum((item.line_total for item in self.items.all()), start=0)
        self.amount = total
        self.save(update_fields=["amount"])
        return total

    def __str__(self): return f"Order {self.reservation.reference}"

    @property
    def total_amount(self):
        return self.amount + self.reservation.ktv_fee + self.reservation.additional_ktv_fee

    @property
    def next_status_choices(self):
        transitions = {
            self.OrderStatus.NEW: (self.OrderStatus.PREPARING,),
            self.OrderStatus.PREPARING: (self.OrderStatus.READY,),
            self.OrderStatus.READY: (self.OrderStatus.SERVED,),
            self.OrderStatus.SERVED: (self.OrderStatus.COMPLETED,),
        }
        allowed = transitions.get(self.order_status, ())
        return tuple((value, self.OrderStatus(value).label) for value in allowed)


class InventoryItem(models.Model):
    name = models.CharField(max_length=120, unique=True)
    category = models.CharField(max_length=80, default="General")
    supplier = models.ForeignKey("Supplier", on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_items")
    unit = models.CharField(max_length=24, default="pcs")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=5)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def stock_state(self):
        if self.quantity <= 0: return "Out of stock"
        if self.quantity <= self.low_stock_threshold: return "Low stock"
        return "In stock"

    def __str__(self): return self.name


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        STOCK_IN = "in", "Stock in"
        USAGE = "usage", "Usage"
        ADJUSTMENT = "adjustment", "Adjustment"

    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class StockAlert(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name="alerts")
    message = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self): return self.message


class Supplier(models.Model):
    name = models.CharField(max_length=140, unique=True)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    def __str__(self): return self.name


class StockIn(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="stock_ins")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_ins")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    received_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_date", "-created_at"]

    @property
    def total_cost(self): return self.quantity * self.unit_cost

    def __str__(self): return f"{self.item.name} · {self.quantity} received"


class Expense(models.Model):
    class Category(models.TextChoices):
        INVENTORY = "inventory", "Inventory"
        UTILITIES = "utilities", "Utilities"
        PAYROLL = "payroll", "Payroll"
        RENT = "rent", "Rent"
        OPERATIONS = "operations", "Operations"
        OTHER = "other", "Other"

    description = models.CharField(max_length=180)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    amount = models.DecimalField(max_digits=11, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    expense_date = models.DateField(default=timezone.localdate)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-expense_date", "-created_at"]

    def __str__(self): return f"{self.description} · {self.amount}"


class CustomerNotification(models.Model):
    class Kind(models.TextChoices):
        RESERVATION = "reservation", "Reservation"
        PAYMENT = "payment", "Payment"
        ORDER = "order", "Order"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="restaurant_notifications")
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="notifications", null=True, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    message = models.CharField(max_length=240)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ActivityLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="restaurant_activity")
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "staff activity"
        verbose_name_plural = "staff activity log"

    def __str__(self): return f"{self.action} · {self.target}"


class OrderItem(models.Model):
    order = models.ForeignKey(FoodOrder, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta: unique_together = ("order", "menu_item")

    @property
    def line_total(self): return self.unit_price * self.quantity
    def __str__(self): return f"{self.quantity} × {self.name}"
