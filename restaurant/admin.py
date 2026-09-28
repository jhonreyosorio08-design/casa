from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html
from django.urls import reverse
from .models import ActivityLog, CustomerNotification, DiningTable, Expense, FoodOrder, GalleryImage, MenuCategory, MenuItem, OrderItem, Reservation, SiteContent, InventoryItem, StockAlert, StockIn, StockMovement, Supplier

admin.site.site_header = "Casa Sonata Administration"
admin.site.site_title = "Casa Sonata"
admin.site.index_title = "Restaurant management"


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email", "active")
    list_filter = ("active",)
    search_fields = ("name", "contact_name", "email", "phone")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "category", "amount", "expense_date", "supplier", "reference")
    list_filter = ("category", "expense_date")
    search_fields = ("description", "reference", "supplier__name")
    date_hierarchy = "expense_date"


@admin.register(CustomerNotification)
class CustomerNotificationAdmin(admin.ModelAdmin):
    list_display = ("customer", "kind", "message", "is_read", "created_at")
    list_filter = ("kind", "is_read", "created_at")
    search_fields = ("customer__username", "message")
    readonly_fields = ("created_at",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target")
    list_filter = ("action", "created_at")
    search_fields = ("actor__username", "action", "target", "details")
    readonly_fields = ("actor", "action", "target", "details", "created_at")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("name", "supplier", "quantity", "unit", "low_stock_threshold", "unit_cost", "stock_state")
    search_fields = ("name",)
    readonly_fields = ("quantity", "unit_cost")


@admin.register(StockIn)
class StockInAdmin(admin.ModelAdmin):
    list_display = ("received_date", "item", "quantity", "supplier", "unit_cost", "total_cost", "reference", "recorded_by")
    list_filter = ("received_date", "supplier")
    search_fields = ("item__name", "supplier__name", "reference")
    date_hierarchy = "received_date"
    readonly_fields = ("recorded_by", "created_at")

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        with transaction.atomic():
            obj.recorded_by = request.user
            super().save_model(request, obj, form, change)
            item = InventoryItem.objects.select_for_update().get(pk=obj.item_id)
            item.quantity += obj.quantity
            item.unit_cost = obj.unit_cost
            if obj.supplier_id:
                item.supplier_id = obj.supplier_id
            item.save(update_fields=("quantity", "unit_cost", "supplier", "updated_at"))
            note = f"Stock-in {obj.reference}" if obj.reference else "Administrator stock-in"
            StockMovement.objects.create(item=item, kind=StockMovement.Kind.STOCK_IN, quantity=obj.quantity, note=note)
            Expense.objects.create(
                description=f"Inventory stock-in: {item.name}", category=Expense.Category.INVENTORY,
                amount=obj.total_cost, expense_date=obj.received_date, supplier=obj.supplier,
                reference=obj.reference, notes=obj.notes,
            )
            ActivityLog.objects.create(actor=request.user, action="Stock-in recorded", target=item.name, details=f"{obj.quantity} {item.unit} from {obj.supplier or 'unspecified supplier'}; cost ₱{obj.total_cost}")

    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "item", "message", "is_resolved", "resolved_at")
    list_filter = ("is_resolved", "created_at")
    readonly_fields = ("item", "message", "created_at", "resolved_at", "is_resolved")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("item", "kind", "quantity", "note", "created_at")
    list_filter = ("kind", "created_at")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

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

    def save_model(self, request, obj, form, change):
        old_status = Reservation.objects.filter(pk=obj.pk).values_list("status", flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        if change and old_status != obj.status:
            if obj.customer_id:
                CustomerNotification.objects.create(customer=obj.customer, reservation=obj, kind=CustomerNotification.Kind.RESERVATION, message=f"Your reservation {obj.reference} is now {obj.get_status_display().lower()}.")
            ActivityLog.objects.create(actor=request.user, action="Reservation status updated", target=obj.reference, details=obj.get_status_display())

@admin.register(DiningTable)
class DiningTableAdmin(admin.ModelAdmin):
    list_display = ("name", "seats", "active")

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("name", "unit_price")

@admin.register(FoodOrder)
class FoodOrderAdmin(admin.ModelAdmin):
    list_display = ("reservation", "amount", "payment_method", "payment_status", "order_status", "created_at", "print_receipt")
    list_filter = ("payment_status", "payment_method")
    search_fields = ("reservation__reference", "reservation__name", "gateway_reference")
    readonly_fields = ("payment_status", "paid_at")
    inlines = (OrderItemInline,)
    actions = ("accept_payments", "reject_payments")

    @admin.display(description="Receipt")
    def print_receipt(self, obj):
        return format_html('<a href="{}">View / print</a>', reverse("staff_receipt", args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        old_status = FoodOrder.objects.filter(pk=obj.pk).values_list("order_status", flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        if change and old_status != obj.order_status:
            reservation = obj.reservation
            if reservation.customer_id:
                CustomerNotification.objects.create(customer=reservation.customer, reservation=reservation, kind=CustomerNotification.Kind.ORDER, message=f"Your order for {reservation.reference} is now {obj.get_order_status_display().lower()}.")
            ActivityLog.objects.create(actor=request.user, action="Order status updated", target=reservation.reference, details=obj.get_order_status_display())

    @admin.action(description="Accept selected pending payments and confirm reservations")
    def accept_payments(self, request, queryset):
        changed = 0
        for order in queryset.select_related("reservation"):
            if order.payment_status != FoodOrder.PaymentStatus.PENDING: continue
            order.payment_status = FoodOrder.PaymentStatus.PAID
            order.paid_at = timezone.now()
            order.save(update_fields=("payment_status", "paid_at"))
            order.reservation.status = Reservation.Status.CONFIRMED
            order.reservation.save(update_fields=("status",))
            if order.reservation.customer_id:
                CustomerNotification.objects.create(customer=order.reservation.customer, reservation=order.reservation, kind=CustomerNotification.Kind.PAYMENT, message=f"Payment for {order.reservation.reference} was accepted. Your reservation is confirmed.")
            ActivityLog.objects.create(actor=request.user, action="Payment accepted", target=order.reservation.reference, details=f"Amount ₱{order.amount}; GCash reference {order.gateway_reference}")
            changed += 1
        self.message_user(request, f"Accepted {changed} pending payment(s).", messages.SUCCESS)

    @admin.action(description="Reject selected pending payments")
    def reject_payments(self, request, queryset):
        changed = 0
        for order in queryset.select_related("reservation"):
            if order.payment_status != FoodOrder.PaymentStatus.PENDING: continue
            order.payment_status = FoodOrder.PaymentStatus.FAILED
            order.save(update_fields=("payment_status",))
            if order.reservation.customer_id:
                CustomerNotification.objects.create(customer=order.reservation.customer, reservation=order.reservation, kind=CustomerNotification.Kind.PAYMENT, message=f"Payment for {order.reservation.reference} was not accepted. Please contact Casa Sonata or submit payment again.")
            ActivityLog.objects.create(actor=request.user, action="Payment rejected", target=order.reservation.reference, details=f"Amount ₱{order.amount}; GCash reference {order.gateway_reference}")
            changed += 1
        self.message_user(request, f"Rejected {changed} pending payment(s).", messages.SUCCESS)

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
