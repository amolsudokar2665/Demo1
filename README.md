# Nakkasi – The Studio backend

A starter Flask backend for a **retail-only** artificial jewellery shop. It includes product APIs, retail order creation, manual UPI reference submission, an admin login/dashboard, product and stock management, and order status updates.

## Important payment note

This version uses **manual UPI**. It does not automatically verify payment with a bank or payment provider. A customer submits a UPI UTR/reference; an admin must verify the actual transaction in the store's UPI/bank app before setting the order to `Paid`. Do not trust payment screenshots alone. No Razorpay integration is enabled in this project. If Razorpay is added later, the server must create the payment order and verify the provider's signature using a secret stored only on the server; never accept a client-side `paid=true` value.

## 1. Requirements

- Python 3.11 or newer
- A terminal / command prompt
- For production, PostgreSQL is recommended; SQLite is convenient for local testing.

## 2. Install and run locally

```bash
# From this folder
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set a unique secret, admin username/password, and your actual UPI ID. Never commit `.env` to Git.

```bash
flask --app app init-db
flask --app app run --debug
```

Open `http://127.0.0.1:5000` for the API status and `http://127.0.0.1:5000/admin/login` for the admin dashboard. The admin is created from `ADMIN_USERNAME` and `ADMIN_PASSWORD` the first time `init-db` runs. If you change the password in `.env` later, the existing database user is not automatically changed.

## 3. Database schema

- `Product`: name, description, category, price, stock, image URL, active flag, creation time.
- `Order`: unique order number, customer contact/delivery details, total, status, payment method, UPI reference, admin note, creation time.
- `OrderItem`: order/product references, snapshotted product name, quantity and unit price.
- `AdminUser`: unique username and Werkzeug password hash.

Prices are calculated on the server from database product prices; prices submitted by the browser are ignored. The stock count is reduced when the order is created. For a real production store, add a stock reservation/expiry process and database transactions appropriate to your database before accepting concurrent high-volume orders.

## 4. API endpoints

All JSON request/response bodies use JSON unless noted.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/products` | List active products |
| GET | `/api/products/<id>` | Get one active product |
| POST | `/api/orders` | Create a retail order; calculates total and decrements stock |
| POST | `/api/orders/<order_number>/payment-reference` | Submit UPI UTR; requires order email and reference |
| GET | `/api/orders/<order_number>?email=customer@example.com` | Look up limited order status by order number + email |

Admin browser routes:

- `GET/POST /admin/login`
- `POST /admin/logout`
- `GET /admin`
- `POST /admin/products`
- `POST /admin/products/<id>/update`
- `POST /admin/orders/<order_number>/update`

### Example: list products

```bash
curl http://127.0.0.1:5000/api/products
```

### Example: create order

Use an existing product ID returned by `/api/products`:

```bash
curl -X POST http://127.0.0.1:5000/api/orders \
  -H 'Content-Type: application/json' \
  -d '{"customer_name":"Test Customer","email":"customer@example.com","phone":"9876543210","address":"Full delivery address","items":[{"product_id":1,"quantity":2}]}'
```

The response contains the generated order number and configured UPI ID. The frontend should show payment instructions and ask the customer to submit the UTR after paying.

### Example: submit UPI reference

```bash
curl -X POST http://127.0.0.1:5000/api/orders/NK260101ABC123/payment-reference \
  -H 'Content-Type: application/json' \
  -d '{"email":"customer@example.com","upi_reference":"123456789012"}'
```

Replace the sample order number with the one returned when creating the order.

## 5. Connect your existing website

Your frontend should call the API at the deployed backend URL. Set the API base URL in the frontend configuration, fetch `/api/products`, and build cart items as `{ "product_id": id, "quantity": qty }`. Do not send or trust prices from the browser. After creating an order, show the order number, UPI ID, amount, and payment instructions, then call the payment-reference endpoint with the order number, customer's email and UTR.

This folder is the backend API/admin starter; it does not automatically replace or wire itself into an existing standalone HTML file.

## 6. Deploy (Render / similar Python host)

1. Push this folder to a private/public Git repository, excluding `.env` and database files.
2. Create a Python web service and set build command to `pip install -r requirements.txt`.
3. Set start command to `gunicorn app:app`.
4. Add environment variables in the host dashboard: `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `UPI_ID`, `DATABASE_URL`, and `COOKIE_SECURE=true` for HTTPS.
5. Use a managed PostgreSQL database for production and put its connection URL in `DATABASE_URL` (some providers use `postgres://`; the app normalizes that prefix).
6. Run `flask --app app init-db` once as a release/one-off command. Confirm your host's persistent database setup before accepting orders.
7. Use the deployed `/health` endpoint to check service health.

Free hosting tiers, database persistence, sleep limits, and pricing change; verify the provider's current terms. Do not use ephemeral local SQLite storage for a live shop because data may disappear on redeploy/restart.

## 7. Before going live

- Use a strong unique `SECRET_KEY` and admin password; enable HTTPS and `COOKIE_SECURE=true`.
- Add CSRF protection to admin forms, login rate limiting, security monitoring, database backups, and appropriate privacy/retention practices before public production use.
- Restrict upload sizes and review uploaded images. Consider object storage for production images.
- Add order confirmation email/SMS only after configuring a trusted provider.
- Test stock, cancellation/refund, delivery, and tax/shipping rules.
- Manual UPI is not automated payment verification. Check the real transaction in your account before marking it Paid.
