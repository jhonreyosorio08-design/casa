from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import InventoryItem, StockAlert


@receiver(post_save, sender=InventoryItem)
def update_inventory_alert(sender, instance, **kwargs):
    if instance.quantity <= instance.low_stock_threshold:
        active = StockAlert.objects.filter(item=instance, is_resolved=False)
        state = "out of stock" if instance.quantity <= 0 else "low stock"
        message = f"{instance.name} is {state} ({instance.quantity} {instance.unit} remaining)."
        alert = active.first()
        if alert:
            if alert.message != message:
                alert.message = message
                alert.save(update_fields=("message",))
        else:
            StockAlert.objects.create(item=instance, message=message)
    else:
        StockAlert.objects.filter(item=instance, is_resolved=False).update(is_resolved=True, resolved_at=timezone.now())
