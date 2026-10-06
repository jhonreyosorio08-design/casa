from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from datetime import datetime, timedelta
from django.utils import timezone
from .models import DiningTable, KTVRoom, Reservation


def ktv_slot_available(room, date, start, hours):
    start_at = datetime.combine(date, start)
    if timezone.is_naive(start_at):
        start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
    end_at = start_at + timedelta(hours=hours)
    bookings = Reservation.objects.filter(
        ktv_room=room,
        reservation_date__range=(date - timedelta(days=1), date + timedelta(days=1)),
    ).exclude(status__in=[Reservation.Status.CANCELLED, Reservation.Status.COMPLETED])
    for booking in bookings:
        booking_start = datetime.combine(booking.reservation_date, booking.reservation_time)
        if timezone.is_naive(booking_start):
            booking_start = timezone.make_aware(booking_start, timezone.get_current_timezone())
        booking_end = booking_start + timedelta(hours=booking.duration_hours)
        if start_at < booking_end and booking_start < end_at:
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
        if not room.min_capacity <= guests <= room.max_capacity:
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
