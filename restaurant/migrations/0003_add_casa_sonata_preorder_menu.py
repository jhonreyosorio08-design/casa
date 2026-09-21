from decimal import Decimal

from django.db import migrations


MENU = {
    "Pasta": [("Seafood Pasta", "330"), ("Carbonara w/ Bread", "295"), ("Filipino Style Pasta w/ Bread", "295")],
    "Salad": [("Casa Sonata Salad", "280")],
    "Snacks": [("Club House", "195"), ("Casa Sonata Cheese Burger", "260"), ("Nachos Overload", "248"), ("Tuna Sandwich", "195"), ("French Fries", "88")],
    "Dessert": [("Halo-Halo", "140"), ("Mais Con Yelo", "140")],
    "Waffles": [("Plain", "40"), ("Chocolate", "55"), ("Peanut Butter", "55"), ("Blueberry & Cream Cheese", "75"), ("Nutella", "65"), ("Biscoff", "65"), ("Nutella & Oreo", "75"), ("Hazel Nut & Oreo", "75"), ("Cream Cheese", "60"), ("Caramel", "55")],
    "Mains": [("Shrimp Tempura", "280"), ("Buttered Shrimp", "380"), ("Bam-E", "295"), ("Pancit Guisado", "295"), ("Lumpia Shanghai", "280"), ("Sweet N' Sour Pork", "450"), ("Sweet N' Sour Fish", "450"), ("Chicken Teriyaki", "280"), ("Buffalo Wings", "280"), ("Buttered Chicken", "550"), ("Fried Chicken", "550"), ("Crispy Pata", "450"), ("Chopsuey", "295"), ("Beef Salpicao", "450"), ("Beef Steak", "450"), ("Sizzling Sisig", "148"), ("Rice Platter (Plain/Garlic)", "150"), ("Cup Rice (Plain/Garlic)", "30")],
    "Grilled": [("Grilled Panga", "180"), ("Pork Belly", "208"), ("Grilled Bangus", "208"), ("Grilled Pecho", "185"), ("Grilled Paa", "175")],
    "Soup": [("Pochero", "450"), ("Tinolang Manok", "450"), ("Chicken Halang-Halang", "450"), ("Tinolang Isda", "380"), ("Pork Sinigang", "380")],
}


def add_menu(apps, schema_editor):
    Category = apps.get_model("restaurant", "MenuCategory")
    Item = apps.get_model("restaurant", "MenuItem")
    for order, (category_name, items) in enumerate(MENU.items(), start=1):
        category, _ = Category.objects.get_or_create(name=category_name, defaults={"slug": category_name.lower(), "order": order})
        for name, price in items:
            Item.objects.update_or_create(category=category, name=name, defaults={"description": "", "price": Decimal(price), "available": True})


class Migration(migrations.Migration):
    dependencies = [("restaurant", "0002_diningtable_reservation_reference_and_more")]
    operations = [migrations.RunPython(add_menu, migrations.RunPython.noop)]
