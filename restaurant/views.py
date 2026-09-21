from django.contrib import messages
from django.shortcuts import redirect, render
from .forms import ReservationForm
from .models import GalleryImage, MenuCategory, MenuItem


def home(request):
    featured = MenuItem.objects.filter(featured=True, available=True)[:3]
    return render(request, "restaurant/home.html", {"featured": featured, "gallery": GalleryImage.objects.all()[:4]})

def menu(request):
    return render(request, "restaurant/menu.html", {"categories": MenuCategory.objects.prefetch_related("items")})

def about(request): return render(request, "restaurant/about.html")
def gallery(request): return render(request, "restaurant/gallery.html", {"gallery": GalleryImage.objects.all()})

def reservation(request):
    form = ReservationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        booking = form.save()
        messages.success(request, f"Thank you, {booking.name}. Your reservation request has been received!")
        return redirect("reservation")
    return render(request, "restaurant/reservation.html", {"form": form})

def contact(request): return render(request, "restaurant/contact.html")
