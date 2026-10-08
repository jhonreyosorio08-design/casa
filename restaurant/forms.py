from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from datetime import datetime, timedelta
from django.utils import timezone
from .models import DiningTable, KTVRoom, Reservation


def ktv_slot_available(room, date, start, hours, exclude_booking_id=None):
    start_at = datetime.combine(date, start)
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
    end_at = start_at + timedelta(hours=hours)
    bookings = Reservation.objects.filter(
        ktv_room=room,
        reservation_date__range=(date - timedelta(days=1), date + timedelta(days=1)),
    ).exclude(status__in=[Reservation.Status.CANCELLED, Reservation.Status.REJECTED, Reservation.Status.COMPLETED])
    if exclude_booking_id:
        bookings = bookings.exclude(pk=exclude_booking_id)
    for booking in bookings:
        booking_start = datetime.combine(booking.reservation_date, booking.reservation_time)
        if timezone.is_naive(booking_start):
            booking_start = timezone.make_aware(booking_start, timezone.get_current_timezone())
        booking_end = booking_start + timedelta(hours=booking.duration_hours + booking.additional_ktv_hours)
        if start_at < booking_end and booking_start < end_at:
            return False
    return True


def dining_slot_available(table, date, start, exclude_booking_id=None):
    start_at = datetime.combine(date, start)
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
    end_at = start_at + timedelta(hours=ReservationForm.DINING_SLOT_HOURS)
    active_statuses = [Reservation.Status.PENDING, Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED]
    bookings = Reservation.objects.filter(
        table=table,
        reservation_date__range=(date - timedelta(days=1), date + timedelta(days=1)),
        status__in=active_statuses,
    )
    if exclude_booking_id:
        bookings = bookings.exclude(pk=exclude_booking_id)
    for booking in bookings:
        booked_start = datetime.combine(booking.reservation_date, booking.reservation_time)
        if timezone.is_naive(booked_start):
            booked_start = timezone.make_aware(booked_start, timezone.get_current_timezone())
        booked_end = booked_start + timedelta(hours=ReservationForm.DINING_SLOT_HOURS)
        if start_at < booked_end and booked_start < end_at:
            return False
    return True


class CustomerRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class StaffAccountForm(UserCreationForm):
    email = forms.EmailField(required=False)
    groups = forms.ModelMultipleChoiceField(queryset=Group.objects.none(), required=False, label="Staff role groups", widget=forms.CheckboxSelectMultiple)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name", "groups", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = Group.objects.all().order_by("name")
        if self.instance.pk:
            self.fields["password1"].required = False
            self.fields["password2"].required = False
            self.fields["password1"].help_text = "Leave blank to keep the current password."

    def save(self, commit=True):
        user = super(UserCreationForm, self).save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        user.is_staff = True
        user.is_superuser = False
        if commit:
            user.save()
            self.save_m2m()
        return user


class PaymentSubmissionForm(forms.Form):
    payment_completed = forms.BooleanField(required=True)
    gcash_reference = forms.CharField(max_length=160, strip=True)
    payment_proof = forms.ImageField()


class WalkInReservationForm(forms.Form):
    reservation_type = forms.ChoiceField(choices=(("dine_in", "Dine-In"), ("ktv", "KTV")), label="Service type", initial="dine_in", widget=forms.RadioSelect)
    name = forms.CharField(max_length=120, label="Guest name")
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=30)
    guests = forms.IntegerField(min_value=1, max_value=20, initial=2)
    start_time = forms.TimeField(
        label="KTV start time",
        required=False,
        initial=lambda: timezone.localtime().time().replace(second=0, microsecond=0),
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    table = forms.ModelChoiceField(queryset=DiningTable.objects.none(), required=False)
    room = forms.ModelChoiceField(queryset=KTVRoom.objects.none(), required=False, label="Available KTV room")
    duration_hours = forms.IntegerField(min_value=1, max_value=12, initial=2, required=False, label="KTV hours")
    payment_method = forms.ChoiceField(choices=(("cash", "Over the counter (Cash)"), ("gcash", "GCash")), initial="cash", label="Payment method")
    cash_tendered = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, required=False, label="Cash received")
    gcash_reference = forms.CharField(max_length=160, required=False, label="GCash transaction reference")
    payment_verified = forms.BooleanField(required=False, label="I verified the GCash payment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_bookings = [Reservation.Status.PENDING, Reservation.Status.PAID, Reservation.Status.CONFIRMED, Reservation.Status.PREPARING, Reservation.Status.READY, Reservation.Status.SERVED]
        self.fields["table"].queryset = DiningTable.objects.filter(active=True, occupied=False).exclude(
            reservations__reservation_date=timezone.localdate(), reservations__status__in=active_bookings,
        ).distinct().order_by("name")
        self.fields["room"].queryset = KTVRoom.objects.filter(active=True, status=KTVRoom.Status.AVAILABLE).order_by("name")

    def clean(self):
        cleaned = super().clean()
        reservation_type = cleaned.get("reservation_type")
        guests = cleaned.get("guests")
        if reservation_type == "dine_in":
            table = cleaned.get("table")
            if not table:
                self.add_error("table", "Choose an available table.")
            elif guests and guests > table.seats:
                self.add_error("guests", f"{table.name} seats up to {table.seats} guests.")
        elif reservation_type == "ktv":
            room = cleaned.get("room")
            hours = cleaned.get("duration_hours")
            start_time = cleaned.get("start_time")
            if not room:
                self.add_error("room", "Choose an available KTV room.")
            elif guests and not room.min_capacity <= guests <= room.max_capacity and not (room.name == "Room A" and guests == 3):
                self.add_error("guests", f"{room.name} accommodates {room.min_capacity}–{room.max_capacity} guests.")
            if not hours:
                self.add_error("duration_hours", "Enter the number of KTV hours.")
            if not start_time:
                self.add_error("start_time", "Enter the KTV start time.")
        method = cleaned.get("payment_method")
        if method == "cash" and cleaned.get("cash_tendered") is None:
            self.add_error("cash_tendered", "Enter the cash received.")
        if method == "gcash":
            if not cleaned.get("gcash_reference"):
                self.add_error("gcash_reference", "Enter the GCash transaction reference.")
            if not cleaned.get("payment_verified"):
                self.add_error("payment_verified", "Verify the GCash payment before completing this walk-in booking.")
        return cleaned


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }


class ReservationForm(forms.ModelForm):
    DINING_SLOT_HOURS = 2

    class Meta:
        model = Reservation
        fields = ["name", "email", "phone", "reservation_date", "reservation_time", "guests", "table", "special_requests"]
        widgets = {
            "reservation_date": forms.DateInput(attrs={"type": "date"}),
            "reservation_time": forms.TimeInput(attrs={"type": "time"}),
            "guests": forms.NumberInput(attrs={"min": 1, "max": 20}),
            "special_requests": forms.Textarea(attrs={"rows": 3, "placeholder": "Allergies, celebrations, seating preferences…"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["table"].queryset = DiningTable.objects.filter(active=True)
        self.fields["table"].empty_label = "Choose an available table"

    def clean_reservation_date(self):
        date = self.cleaned_data["reservation_date"]
        if date < timezone.localdate():
            raise forms.ValidationError("Please select today or a future date.")
        return date

    def clean(self):
        cleaned = super().clean()
        table = cleaned.get("table")
        date = cleaned.get("reservation_date")
        start = cleaned.get("reservation_time")
        guests = cleaned.get("guests")
        if not all((table, date, start, guests)):
            return cleaned
        if guests > table.seats:
            self.add_error("guests", f"{table.name} seats up to {table.seats} guests.")
            return cleaned
        if not dining_slot_available(table, date, start):
            self.add_error("table", f"{table.name} already has a reservation during that two-hour seating window.")
        return cleaned


class KTVReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ["name", "email", "phone", "reservation_date", "reservation_time", "guests"]
        widgets = {
            "reservation_date": forms.DateInput(attrs={"type": "date"}),
            "reservation_time": forms.TimeInput(attrs={"type": "time"}),
            "guests": forms.NumberInput(attrs={"min": 1}),
        }

    room = forms.ModelChoiceField(queryset=KTVRoom.objects.none())
    duration_hours = forms.IntegerField(min_value=1, max_value=12, initial=2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = KTVRoom.objects.filter(active=True)

    def clean_reservation_date(self):
        date = self.cleaned_data["reservation_date"]
        if date < timezone.localdate():
            raise forms.ValidationError("Please select today or a future date.")
        return date

    def clean(self):
        cleaned = super().clean()
        room = cleaned.get("room")
        date = cleaned.get("reservation_date")
        start = cleaned.get("reservation_time")
        hours = cleaned.get("duration_hours")
        guests = cleaned.get("guests")
        if not all((room, date, start, hours, guests)):
            return cleaned
        # Room A can be booked by a small party when they specifically select it.
        # Keep the configured capacity range for all other room/guest combinations.
        if not room.min_capacity <= guests <= room.max_capacity and not (room.name == "Room A" and guests == 3):
            self.add_error("guests", f"{room.name} accommodates {room.min_capacity}–{room.max_capacity} guests.")
            return cleaned
        start_at = datetime.combine(date, start)
        if timezone.is_naive(start_at):
            start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
        if start_at <= timezone.now():
            self.add_error("reservation_time", "Choose a future starting time.")
            return cleaned
        if not ktv_slot_available(room, date, start, hours):
            self.add_error("reservation_time", "This room is already reserved for part of that time. Please choose another time or room.")
        return cleaned
