import uuid

from django.db import models


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
    order = models.PositiveIntegerField(default=0)
    class Meta: ordering = ["order", "title"]
    def __str__(self): return self.title


class DiningTable(models.Model):
    name = models.CharField(max_length=40, unique=True)
    seats = models.PositiveSmallIntegerField()
    active = models.BooleanField(default=True)

    class Meta: ordering = ["seats", "name"]
    def __str__(self): return f"{self.name} ({self.seats} seats)"


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CONFIRMED = "confirmed", "Confirmed"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    reference = models.CharField(max_length=20, unique=True, editable=False, default="")
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    reservation_date = models.DateField()
    reservation_time = models.TimeField()
    guests = models.PositiveSmallIntegerField()
    table = models.ForeignKey(DiningTable, on_delete=models.PROTECT, related_name="reservations", null=True, blank=True)
    special_requests = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta: ordering = ["reservation_date", "reservation_time"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"CS-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self): return f"{self.reference} · {self.name}"


class FoodOrder(models.Model):
    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    reservation = models.OneToOneField(Reservation, on_delete=models.CASCADE, related_name="food_order")
    payment_method = models.CharField(max_length=30, default="gcash")
    payment_status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    gateway_reference = models.CharField(max_length=160, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def recalculate_total(self):
        total = sum((item.line_total for item in self.items.all()), start=0)
        self.amount = total
        self.save(update_fields=["amount"])
        return total

    def __str__(self): return f"Order {self.reservation.reference}"


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
