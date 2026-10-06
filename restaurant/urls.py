from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from . import views

urlpatterns = [
    path("administrator/", views.admin_dashboard, name="admin_dashboard"),
    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path("staff/login/", views.staff_login, name="staff_login"),
    path("staff/receipt/<int:order_id>/", views.staff_receipt, name="staff_receipt"),
    path("account/", views.account_dashboard, name="account_dashboard"),
    path("account/ktv/<str:reference>/cancel/", views.cancel_ktv_reservation, name="cancel_ktv_reservation"),
    path("notifications/status/", views.notification_status, name="notification_status"),
    path("profile/", views.account_profile, name="account_profile"),
    path("profile/password/", auth_views.PasswordChangeView.as_view(template_name="restaurant/password_change.html", success_url=reverse_lazy("account_profile")), name="password_change"),
    path("account/receipt/<str:reference>/", views.customer_receipt, name="customer_receipt"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="restaurant/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("website/", views.public_home, name="public_home"),
    path("", views.home, name="home"), path("menu/", views.menu, name="menu"),
    path("about/", views.about, name="about"), path("gallery/", views.gallery, name="gallery"),
    path("events/", views.events_page, name="events"),
    path("events/<slug:slug>/", views.event_detail, name="event_detail"),
    path("reservations/", views.reservation, name="reservation"),
    path("reservations/ktv/", views.ktv_reservation, name="ktv_reservation"),
    path("reservations/<str:reference>/order/", views.preorder, name="preorder"),
    path("reservations/<str:reference>/checkout/", views.checkout, name="checkout"),
    path("reservations/<str:reference>/payment/", views.payment_pending, name="payment_pending"),
    path("payments/gcash/webhook/", views.payment_webhook, name="payment_webhook"),
    path("contact/", views.contact, name="contact"),
]
