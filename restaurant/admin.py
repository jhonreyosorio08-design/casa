from django.contrib import admin
from .models import GalleryImage, MenuCategory, MenuItem, Reservation

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
    list_display = ("name", "reservation_date", "reservation_time", "guests", "status")
    list_filter = ("status", "reservation_date")
    search_fields = ("name", "email", "phone")
    list_editable = ("status",)

@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("title", "order")
