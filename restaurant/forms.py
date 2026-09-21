from django import forms
from django.utils import timezone
from .models import Reservation


class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ["name", "email", "phone", "reservation_date", "reservation_time", "guests", "special_requests"]
        widgets = {
            "reservation_date": forms.DateInput(attrs={"type": "date"}),
            "reservation_time": forms.TimeInput(attrs={"type": "time"}),
            "guests": forms.NumberInput(attrs={"min": 1, "max": 20}),
            "special_requests": forms.Textarea(attrs={"rows": 3, "placeholder": "Allergies, celebrations, seating preferences…"}),
        }

    def clean_reservation_date(self):
        date = self.cleaned_data["reservation_date"]
        if date < timezone.localdate():
            raise forms.ValidationError("Please select today or a future date.")
        return date
