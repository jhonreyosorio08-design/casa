from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"), path("menu/", views.menu, name="menu"),
    path("about/", views.about, name="about"), path("gallery/", views.gallery, name="gallery"),
    path("reservations/", views.reservation, name="reservation"),
    path("reservations/<str:reference>/order/", views.preorder, name="preorder"),
    path("reservations/<str:reference>/checkout/", views.checkout, name="checkout"),
    path("reservations/<str:reference>/payment/", views.payment_pending, name="payment_pending"),
    path("payments/gcash/webhook/", views.payment_webhook, name="payment_webhook"),
    path("contact/", views.contact, name="contact"),
]
