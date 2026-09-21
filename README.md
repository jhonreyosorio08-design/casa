# Casa Sonata

A Django restaurant website with a responsive customer site, online reservations, and admin management for menu, gallery, and bookings.

## Run locally

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py loaddata sample_menu
python manage.py createsuperuser
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` and manage content at `http://127.0.0.1:8000/admin/`.

Images uploaded through Django Admin are served from `media/` in development. The public gallery includes attractive fallback photography until gallery images are added.
