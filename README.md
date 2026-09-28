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

Visit `http://127.0.0.1:8000/` for the public restaurant site. When a superuser is signed in, `/` opens the custom administrator dashboard; the customer homepage remains available at `/website/`. The private staff sign-in is at `/staff/login/` and the operations dashboard is at `/staff/`. The administrator dashboard is also available at `/administrator/`; Django's standard management interface remains at `/admin/`. Administrators create, activate, deactivate, and remove staff from **Authentication and Authorization → Users**. Public registration creates customer accounts only. Staff cannot access Django Admin, account management, or system settings.

Customers can create an account at `/accounts/register/` or sign in at `/accounts/login/`. A customer must be signed in to submit a reservation or continue its preorder and checkout. Each reservation is linked to its customer account, and order URLs are restricted to that account.

Assign staff to the **Cashier**, **Kitchen Staff**, or **Inventory Staff** group from the user's admin form. Cashiers can review payments, orders, reservations, and tables; Kitchen Staff can view orders and update preparation status without payment details; Inventory Staff can update stock and view the read-only movement history. Individual Django permissions can grant additional functions, including financial reports. Administrators can manage suppliers, operating expenses, and customer notifications in Django Admin. The administrator dashboard summarizes verified order income, recorded expenses, estimated net income, sales charts, stock alerts, and the staff activity log. Customers can view notifications, reservations, and their paid digital receipt at `/account/` after signing in.

From Django Admin, administrators can manage menu categories and dishes, tables, reservations, orders, gallery images, inventory, and the public website copy. Add a **Public website content** record to edit the homepage hero and introduction, About story, contact details, opening hours, and private dining copy. Gallery images can be unpublished without deleting them. Changes appear on the public pages from the database.

Uploaded images are served from `media/` in development. Configure `GCASH_WEBHOOK_SECRET` in the deployment environment before accepting payment notifications. A live GCash provider integration still needs provider credentials and checkout/webhook configuration; the local checkout currently records a pending payment only.
