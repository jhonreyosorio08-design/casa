from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from .models import DiningTable, Reservation


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
