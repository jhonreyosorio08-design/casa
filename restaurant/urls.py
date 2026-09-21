from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"), path("menu/", views.menu, name="menu"),
    path("about/", views.about, name="about"), path("gallery/", views.gallery, name="gallery"),
    path("reservations/", views.reservation, name="reservation"), path("contact/", views.contact, name="contact"),
]
