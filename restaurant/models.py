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


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    reservation_date = models.DateField()
    reservation_time = models.TimeField()
    guests = models.PositiveSmallIntegerField()
    special_requests = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["reservation_date", "reservation_time"]
    def __str__(self): return f"{self.name} · {self.reservation_date}"
