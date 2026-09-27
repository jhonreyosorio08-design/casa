from django.contrib import admin
from .models import DiningTable, FoodOrder, GalleryImage, MenuCategory, MenuItem, OrderItem, Reservation, SiteContent

admin.site.site_header = "Casa Sonata Administration"
admin.site.site_title = "Casa Sonata"
admin.site.index_title = "Restaurant management"

@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name", "order")

@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "featured", "available")
    list_filter = ("category", "featured", "available")
    search_fields = ("name", "description")

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("reference", "name", "table", "reservation_date", "reservation_time", "guests", "status")
    list_filter = ("status", "reservation_date")
    search_fields = ("name", "email", "phone")
    list_editable = ("status",)

@admin.register(DiningTable)
class DiningTableAdmin(admin.ModelAdmin):
    list_display = ("name", "seats", "active")

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("name", "unit_price")

@admin.register(FoodOrder)
class FoodOrderAdmin(admin.ModelAdmin):
    list_display = ("reservation", "amount", "payment_method", "payment_status", "created_at")
    list_filter = ("payment_status", "payment_method")
    search_fields = ("reservation__reference", "reservation__name", "gateway_reference")
    list_editable = ("payment_status",)
    inlines = (OrderItemInline,)

@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "order")
    list_filter = ("category", "is_published")


@admin.register(SiteContent)
class SiteContentAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Home page", {"fields": ("restaurant_name", "tagline", "hero_title", "hero_description", "hero_image", "introduction_title", "introduction", "announcement")}),
        ("About page", {"fields": ("about_title", "about_story")}),
        ("Contact information", {"fields": ("address", "phone", "email", "opening_hours", "private_dining_text")}),
    )

    def has_add_permission(self, request):
        return not SiteContent.objects.exists()
