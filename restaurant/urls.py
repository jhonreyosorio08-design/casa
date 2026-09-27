from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(template_name="restaurant/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("", views.home, name="home"), path("menu/", views.menu, name="menu"),
    path("about/", views.about, name="about"), path("gallery/", views.gallery, name="gallery"),
    path("reservations/", views.reservation, name="reservation"),
    path("reservations/<str:reference>/order/", views.preorder, name="preorder"),
    path("reservations/<str:reference>/checkout/", views.checkout, name="checkout"),
    path("reservations/<str:reference>/payment/", views.payment_pending, name="payment_pending"),
    path("payments/gcash/webhook/", views.payment_webhook, name="payment_webhook"),
    path("contact/", views.contact, name="contact"),
]
