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

Visit `http://127.0.0.1:8000/`. The private staff dashboard is at `http://127.0.0.1:8000/admin/`; create a staff account with `createsuperuser` before signing in. Django restricts this dashboard to staff accounts with the relevant model permissions.

Customers can create an account at `/accounts/register/` or sign in at `/accounts/login/`. A customer must be signed in to submit a reservation or continue its preorder and checkout. Each reservation is linked to its customer account, and order URLs are restricted to that account.

From Django Admin, staff can manage menu categories and dishes, tables, reservations, orders, gallery images, and the public website copy. Add a **Public website content** record to edit the homepage hero and introduction, About story, contact details, opening hours, and private dining copy. Gallery images can be unpublished without deleting them. Changes appear on the public pages from the database.

Uploaded images are served from `media/` in development. Configure `GCASH_WEBHOOK_SECRET` in the deployment environment before accepting payment notifications. A live GCash provider integration still needs provider credentials and checkout/webhook configuration; the local checkout currently records a pending payment only.
