# PixelMart — Backend Developer Guide

> **Stack:** Django 6.0 · Django REST Framework · MySQL · JWT (SimpleJWT) · Redis · Stripe · Moneroo
> **Last updated:** February 2026
> **Author:** Initial architecture by Franck ZINSOU (CTO)
> **Security passes:** Bug fix (Feb 2026) · Serializer & data exposure (Feb 2026) · 2FA deep audit (Feb 2026) · Payout ledger (Feb 2026)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Getting Started](#2-getting-started)
3. [Project Structure](#3-project-structure)
4. [Apps & Responsibilities](#4-apps--responsibilities)
5. [Role System](#5-role-system)
6. [Complete Workflows — What the Code Actually Does](#6-complete-workflows--what-the-code-actually-does)
   - 6.1 [Authentication — All Roles](#61-authentication--all-roles)
   - 6.2 [Vendor Journey — Store to Payout](#62-vendor-journey--store-to-payout)
   - 6.3 [Customer Journey — Browse to Review](#63-customer-journey--browse-to-review)
   - 6.4 [Admin Operations](#64-admin-operations)
   - 6.5 [Order Processing & Payment Flow](#65-order-processing--payment-flow)
   - 6.6 [Financial Ledger — Payout & Transactions](#66-financial-ledger--payout--transactions)
   - 6.7 [Messaging & Notifications](#67-messaging--notifications)
7. [API Endpoint Reference](#7-api-endpoint-reference)
8. [Permissions Architecture](#8-permissions-architecture)
9. [Serializer Strategy — Data Exposure Rules](#9-serializer-strategy--data-exposure-rules)
10. [Security Rules — Read Before You Code](#10-security-rules--read-before-you-code)
11. [Known Gaps & What's Next](#11-known-gaps--whats-next)
12. [Full Change Log](#12-full-change-log)
13. [Environment Variables Reference](#13-environment-variables-reference)

---

## 1. Project Overview

PixelMart is an **AI-powered African marketplace** where vendors open digital stores and customers buy products. The backend is a Django REST Framework API serving a Next.js frontend.

**Core business rules hardcoded in the API:**
- One store per vendor — enforced server-side, raises `403` if violated
- Vendors must have 2FA enabled before requesting a payout — enforced at every payout creation
- All monetary values are integers in **XOF** (West African CFA franc) — no subdivisions, 1 XOF = 1 unit, never use floats for money
- Reviews require a verified purchase — enforced via `OrderItem` existence check
- Order *creation* is not implemented yet — it requires a dedicated atomic checkout endpoint
- Transactions are immutable — no UPDATE ever; errors use a `reversal` transaction
- Payouts are immutable — once created, no update or delete via API

---

## 2. Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 18
- **Redis** — required, the 2FA login flow will fail silently without it

### Setup

```bash
# 1. Clone and create virtualenv
git clone <repo>
cd pixelmart-backend
python -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill environment variables
cp .env.example .env
# The app will refuse to start if SECRET_KEY, DB_*, or ALLOWED_HOSTS are missing

# 4. Run migrations
python manage.py migrate

# 5. Create a superuser (admin)
python manage.py createsuperuser

# 6. Run
python manage.py runserver
```

> ⚠️ **Redis must be running before starting the server.** Configure `CACHES` in `settings.py` to point at your Redis instance. Without it, all 2FA logins will fail (the pending token cannot be stored or retrieved).

### API Docs (auto-generated)

- **Swagger UI** → `http://localhost:8000/api/docs/`
- **ReDoc** → `http://localhost:8000/api/redoc/`
- **Schema** → `http://localhost:8000/api/schema/`

---

## 3. Project Structure

```
pixelmart-backend/
├── config/
│   ├── settings.py       # Reads exclusively from .env — no hardcoded secrets
│   ├── urls.py           # Root URL routing — all apps under /api/v1/
│   ├── wsgi.py
│   └── asgi.py
├── common/
│   └── models.py         # TimeStampedModel — base for all models
├── users/                # Auth, registration, 2FA, profile
├── stores/               # Vendor stores, dashboard, balances
├── products/             # Catalog, categories, variants
├── orders/               # Orders, coupons, payouts
├── transactions/         # Financial ledger (read-only)
├── reviews/              # Reviews, messages, notifications
├── requirements.txt
└── .env.example
```

### URL Routing

```
/api/v1/auth/             → users.urls
/api/v1/stores/           → stores.urls  (my/ for owner, / for public)
/api/v1/products/         → products.urls
/api/v1/orders/           → orders.urls  (/ orders, /coupons/, /payouts/)
/api/v1/transactions/     → transactions.urls
/api/v1/reviews/          → reviews.urls  (/ reviews, /messages/, /notifications/)
/api/docs/                → Swagger UI
/api/redoc/               → ReDoc
```

---

## 4. Apps & Responsibilities

### `common`
- **`TimeStampedModel`** — abstract base with `created_at`, `updated_at`, and `uuid`. All models inherit from this (except `OrderItem` which has a standalone `uuid` field).

### `users`
| File | What it does |
|---|---|
| `models.py` | `User` — email login (no username), roles, 2FA flags, locale |
| `serializers.py` | `UserSerializer` (safe post-login fields), `PublicUserSerializer` (name+avatar only, embedded in reviews/messages), `UserRegistrationSerializer` (blocks `role=admin`), `UserUpdateSerializer`, `ChangePasswordSerializer`, `TOTPVerifySerializer` |
| `views.py` | `RegisterView`, `LoginView` (step 1), `Login2FAView` (step 2), `LogoutView`, `ProfileView`, `ChangePasswordView`, `TOTPSetupView`, `TOTPVerifyView`, `TOTPDisableView` |
| `urls.py` | All `/api/v1/auth/` routes |

### `stores`
| File | What it does |
|---|---|
| `models.py` | `Store` — status, subscription tier, balance, pending_balance, level, ratings, commission_rate |
| `serializers.py` | `StoreSerializer` (owner — includes balance, pending_balance), `PublicStoreSerializer` (no financials), `StoreCreateSerializer` (auto-generates slug), `StoreUpdateSerializer` |
| `views.py` | `StoreViewSet` (owner-only, enforces 1-store rule, dashboard action, balance action) + `PublicStoreViewSet` (anonymous read, `.only()` optimised) |
| `urls.py` | `my/` → `StoreViewSet`, `/` → `PublicStoreViewSet` |

### `products`
| File | What it does |
|---|---|
| `models.py` | `Category` (tree, max 2 levels), `Product`, `ProductVariant` |
| `serializers.py` | `ProductListSerializer` (lightest — card view), `ProductPublicSerializer` (detail without cost_price/internals), `ProductSerializer` (vendor/admin — full), `ProductCreateSerializer` (writable), `ProductVariantSerializer` (full), `ProductVariantPublicSerializer` (price + availability only) |
| `views.py` | `CategoryViewSet` (public read, admin-only write), `ProductViewSet` (public list, role-aware detail, vendor write, `duplicate` action, `inventory` patch action), `ProductVariantViewSet` (nested under product slug) |
| `urls.py` | `/categories/`, `/` (products), `/<slug>/variants/` |

### `orders`
| File | What it does |
|---|---|
| `models.py` | `Coupon`, `Order`, `OrderItem`, `Payout` (with FK to Transaction) |
| `serializers.py` | `OrderCustomerSerializer`, `OrderVendorSerializer`, `OrderAdminSerializer`, `OrderItemSerializer`, `CouponSerializer`, `CouponPublicSerializer` (validate endpoint), `PayoutSerializer` (vendor — exposes `transaction_id`), `PayoutAdminSerializer` |
| `views.py` | `OrderViewSet` (no create — role-scoped read + vendor status/tracking update), `CouponViewSet` (vendor CRUD + `validate` action for checkout), `PayoutViewSet` (vendor create — atomically creates Transaction + deducts balance) |
| `urls.py` | `/`, `/coupons/`, `/payouts/` |

### `transactions`
| File | What it does |
|---|---|
| `models.py` | `Transaction` — immutable ledger: type, direction, amount, balance_before, balance_after |
| `serializers.py` | `TransactionSerializer` (vendor — no metadata, no balance_before), `TransactionAdminSerializer` (all fields) |
| `views.py` | `TransactionViewSet` (ReadOnly — vendor sees own store, admin sees all) |

### `reviews`
| File | What it does |
|---|---|
| `models.py` | `Review` (purchase-verified, 1 per product+order+customer), `Message` (immutable, threaded), `Notification` (system-generated) |
| `serializers.py` | `ReviewPublicSerializer` (published, author as `PublicUserSerializer`), `ReviewCreateSerializer` (rating/title/body/images only — server injects the rest), `ReviewVendorSerializer` (vendor_reply writable only), `ReviewAdminSerializer` (all fields), `MessageSerializer`, `NotificationSerializer` |
| `views.py` | `ReviewViewSet`, `MessageViewSet` (`mark_read` action), `NotificationViewSet` (`mark_read` + `mark_all_read` actions) |
| `urls.py` | `/`, `/messages/`, `/notifications/` |

---

## 5. Role System

Three roles exist. They are set at registration and **cannot be self-upgraded**.

| Role | `user.role` | Key capabilities |
|---|---|---|
| `customer` | `'customer'` | Browse, buy (checkout TBD), review purchased products, message vendors |
| `vendor` | `'vendor'` | Own one store, manage products/coupons/orders, request payouts (requires 2FA) |
| `admin` | `'admin'` | Full read/write everywhere, all serializers, can ban users, delete reviews |

`admin` registration is blocked in `UserRegistrationSerializer.validate_role()`. Admins are created only via `manage.py createsuperuser` or the Django admin.

**Commission rates** are stored per-store as basis points (`commission_rate` field):
- Free tier: 500 bp = 5%
- Pro tier: 300 bp = 3%
- Business tier: 200 bp = 2%

**Store levels** are computed by `Store.calculate_level()` based on `total_orders`:
- Bronze: 0–99 orders
- Silver: 100–499
- Gold: 500–1999
- Platinum: 2000+

---

## 6. Complete Workflows — What the Code Actually Does

---

### 6.1 Authentication — All Roles

#### Registration

```
POST /api/v1/auth/register/
Body: { email, name, password, password_confirm, role, phone?, locale? }

Server:
  1. validate_role() → blocks role='admin' → raises 400
  2. Validates password match and strength (Django's validate_password)
  3. User.objects.create_user(**validated_data)
  4. _issue_tokens(user):
       - RefreshToken.for_user(user)
       - user.last_login_at = now()
       - user.save()

Response 201: { user: UserSerializer, access, refresh, message }

UserSerializer returns:
  uuid, email, name, avatar, role, phone, locale, is_2fa_enabled,
  is_verified, created_at
  — NEVER: totp_secret, is_banned, auth_provider
```

> ⚠️ `is_verified` is set `False` on registration. Email verification is not yet implemented — no email is sent, no token is generated. This is a known gap.

#### Login — No 2FA (customers, unverified vendors)

```
POST /api/v1/auth/login/
Body: { email, password }

Server:
  1. Normalize email (lowercase)
  2. User.objects.get(email=email) → if not found: same generic error as wrong password
     (prevents user enumeration — identical error message for both)
  3. user.check_password(password) → if False: 401 'Invalid credentials.'
  4. user.is_banned → 403 'Account suspended.'
  5. user.is_active → 403 'Account is inactive.'
  6. user.is_2fa_enabled == False → issue tokens directly

Response 200: { user: UserSerializer, access, refresh }
```

#### Login — With 2FA (vendors who have enabled TOTP)

```
Step 1 — POST /api/v1/auth/login/
Body: { email, password }

Server (same checks as above, then):
  6. user.is_2fa_enabled == True:
       pending_token = secrets.token_urlsafe(32)   ← 256-bit random, URL-safe
       cache.set(f'2fa_pending:{pending_token}', user.pk, timeout=300)  ← Redis, 5 min TTL
       ← NOTE: user.pk is NEVER sent to the client

Response 200: { requires_2fa: true, pending_token: "<opaque token>" }

──────────────────────────────────────────────────

Step 2 — POST /api/v1/auth/login/2fa/
Body: { pending_token, code }

Server:
  1. cache.get(f'2fa_pending:{pending_token}') → user_pk
     → if None (expired or wrong): 401 'Invalid or expired token.'
  2. ATOMIC attempt counter (race-condition-safe):
       cache.add(f'2fa_attempts:{pending_token}', 0, timeout=300)  ← only sets if absent
       attempts = cache.incr(f'2fa_attempts:{pending_token}')       ← atomic increment
       if attempts > 5:
           cache.delete(pending_token key)
           cache.delete(attempts key)
           → 429 'Too many attempts. Please log in again.'
  3. User.objects.get(pk=user_pk)
  4. if not user.totp_secret: → 401 (same generic error — no info leak)
  5. pyotp.TOTP(user.totp_secret).verify(code, valid_window=1)
     → valid_window=1 allows ±30 seconds clock drift
     → if False: 401 'Invalid 2FA code.'
  6. On success: delete both cache keys immediately (one-time token)
  7. _issue_tokens(user)

Response 200: { user: UserSerializer, access, refresh }
```

> ❌ **Never** return `user_id` or `user_pk` in the 2FA challenge. `pending_token` only.
> ❌ **Never** remove the attempt counter. Max 5 attempts per token, then destroy it.

#### Token Refresh

```
POST /api/v1/auth/refresh/
Body: { refresh }

→ SimpleJWT TokenRefreshView
→ Rotates both tokens: old refresh is blacklisted, new pair issued

Response 200: { access, refresh }
```

#### Logout

```
POST /api/v1/auth/logout/
Header: Authorization: Bearer <access>
Body: { refresh }

Server:
  1. RefreshToken(refresh_token).blacklist()
  → TokenError is swallowed (already expired → still 200)
  → Always returns 200 (prevents probing whether a token was still valid)

Response 200: { message: 'Logged out successfully.' }
```

#### Profile — Read & Update

```
GET /api/v1/auth/me/
→ UserSerializer (uuid, email, name, avatar, role, phone, locale, is_2fa_enabled, is_verified)

PATCH /api/v1/auth/me/
Body: { name?, avatar?, phone?, locale? }
→ UserUpdateSerializer
→ email updates are BLOCKED here — email change requires a dedicated flow with re-verification (not yet built)
→ role, is_verified, is_2fa_enabled are read-only in all cases
```

#### Change Password

```
PUT /api/v1/auth/me/password/
Body: { old_password, new_password, new_password_confirm }

Server:
  1. validate_old_password() → user.check_password()
  2. new_password != old_password → enforced (can't reuse same password)
  3. new_password == new_password_confirm
  4. validate_password() — Django's full password strength check
  5. user.set_password(new_password) + user.save()
  6. _blacklist_all_tokens_for(user):
       → ALL outstanding refresh tokens for this user are blacklisted
       → Stolen refresh tokens from before the password change are now dead

Response 200: { message: 'Password changed successfully. Please log in again.' }
```

#### 2FA Setup (vendors must complete this before payouts)

```
Step 1 — POST /api/v1/auth/2fa/setup/
Requires: valid JWT
→ Blocked if is_2fa_enabled == True (must disable first)

Server:
  1. secret = pyotp.random_base32()     ← random TOTP secret
  2. user.totp_secret = secret
  3. user.save(update_fields=['totp_secret'])   ← saved but NOT yet activated
  4. Generates QR code PNG as base64

Response 200: { secret, qr_code: "data:image/png;base64,...", next_step }

Note: totp_secret is stored plaintext — spec requires AES-256 at rest (TODO)
Note: calling setup again before verify OVERWRITES the previous secret (idempotent)

──────────────────────────────────────────────────

Step 2 — POST /api/v1/auth/2fa/verify/
Body: { code }   ← 6-digit code from authenticator app

Server:
  1. Blocked if is_2fa_enabled == True
  2. Blocked if totp_secret is None (setup was not called)
  3. pyotp.TOTP(user.totp_secret).verify(code, valid_window=1)
  4. On success: user.is_2fa_enabled = True; user.save()

Response 200: { message: '2FA enabled successfully.' }
```

#### 2FA Disable

```
POST /api/v1/auth/2fa/disable/
Body: { code }   ← must provide a valid current TOTP code to confirm

Server (order is intentional — prevents info leakage):
  1. Check is_2fa_enabled == True → else 400
  2. serializer.is_valid()  ← input validated FIRST, before any business logic
  3. If vendor: check for pending Payout → 403 'Cannot disable 2FA while a payout is pending.'
  4. Check totp_secret exists (state guard)
  5. pyotp.TOTP.verify(code)
  6. user.is_2fa_enabled = False; user.totp_secret = None; user.save()

Response 200: { message: '2FA disabled successfully.' }
```

---

### 6.2 Vendor Journey — Store to Payout

#### Create a Store

```
POST /api/v1/stores/my/
Requires: authenticated vendor
Body: { name, description?, logo?, banner?, country, currency }

Server:
  1. Check Store.objects.filter(owner=user).exists() → if True: 403 'You already own a store.'
  2. Auto-generate slug from name (slugify + numeric suffix on collision)
  3. store.owner = request.user (always server-side)
  4. store.status = 'pending' (default — needs admin activation)

Response 201: StoreSerializer
  (includes: balance, pending_balance, level, total_orders, avg_rating, is_verified)
```

#### Update Store

```
PATCH /api/v1/stores/my/{id}/
Body: { name?, description?, logo?, banner?, theme_id?, primary_color?, country?, currency? }
→ StoreUpdateSerializer
→ slug, balance, commission_rate, level, is_verified are NOT writable by the vendor
```

#### Store Dashboard

```
GET /api/v1/stores/my/{id}/dashboard/?period=week
period options: today | week (default) | month

Server computes:
  - revenue: SUM(total_amount) for orders in period
  - order_count: COUNT for orders in period
  - avg_order: revenue / order_count
  - top_products: top 5 by quantity sold (queried from Order.items JSONField)
  - pending_orders: COUNT orders with status='pending'
  - low_stock_count: Products where quantity <= low_stock_threshold

Response: {
  period, revenue: {value, change_pct},
  orders: {value, change_pct},
  avg_order: {value, change_pct},
  conversion: {value, change_pct},   ← always 0 for now (not computed yet)
  top_products, pending_orders, low_stock_alerts,
  balance: { available, pending, currency }
}
```

#### Store Balance

```
GET /api/v1/stores/my/{id}/balance/
Response: { available: int (XOF), pending: int (XOF), currency: str }
```

#### Manage Products

```
POST /api/v1/products/
Body: { store_slug, title, description, price, category (slug), ... }

Server:
  1. Store.objects.get(slug=store_slug, owner=request.user) → 422 if not found
  2. unique_slug() generates unique product slug (max 999 attempts → 422 if exhausted)
  3. serializer.save(store=store)

GET /api/v1/products/
→ Public list — status='active' only
→ Filters: ?category=slug, ?store=slug, ?search=term
→ Ordering: ?ordering=recent|price_asc|price_desc|bestseller|rating

GET /api/v1/products/{slug}/
→ Vendor/Admin: full ProductSerializer (includes cost_price, sku, barcode, etc.)
→ Public/Customer: ProductPublicSerializer (no cost_price, no internals)

POST /api/v1/products/{slug}/duplicate/
→ Creates a copy with status='draft' and slug='<original>-copy'
→ Copies all variants

PATCH /api/v1/products/{slug}/inventory/
Body: { quantity: int }
→ Direct stock adjustment — must be non-negative integer
```

#### Manage Variants

```
POST /api/v1/products/{product_slug}/variants/
Body: { title, options, price?, compare_price?, sku?, quantity, weight?, is_available }
→ Only product owner can create

GET /api/v1/products/{product_slug}/variants/
→ Public: ProductVariantPublicSerializer (price, is_available only)
→ Vendor/Admin: ProductVariantSerializer (full, including sku, weight)
```

#### Manage Coupons

```
POST /api/v1/orders/coupons/
Body: { store_slug, code, discount_type, value, min_order_amount?, max_uses?, expires_at?, ... }
→ code is always stored as uppercase
→ used_count is read-only (server-managed)

GET /api/v1/orders/coupons/
→ Vendors see only their own store's coupons
→ Admins see all

POST /api/v1/orders/coupons/validate/
Body: { code, store_id, cart_total }
→ Used at checkout to validate a coupon before applying
→ Checks: is_active, starts_at <= now, expires_at > now, max_uses, min_order_amount
→ Returns: { valid, discount_amount, discount_type, new_total }
→ Returns generic INVALID_CODE error for unknown codes (no info leak about whether code exists)
```

#### View Orders (Vendor)

```
GET /api/v1/orders/
→ filter(store__owner=user) — vendors only see their own store orders
→ OrderVendorSerializer:
   Returns: order_number, customer_name, customer_email (for fulfilment),
            status, payment_status, items, subtotal, commission_amount,
            shipping_address, tracking_number, carrier, estimated_delivery
   NEVER:  payment_reference, billing_address

PATCH /api/v1/orders/{id}/
→ Vendors can update: status, tracking_number, carrier, estimated_delivery
→ Customers cannot PATCH orders (403 enforced in update() and partial_update())
```

#### Request a Payout

```
POST /api/v1/orders/payouts/
Requires: vendor with is_2fa_enabled=True
Body: { store_slug, amount (XOF), currency, method, destination }

Server — validations (in order):
  1. role == 'vendor' → else 403
  2. user.is_2fa_enabled → else 403 '2FA must be enabled before requesting a payout.'
  3. Store.objects.get(slug=store_slug, owner=user) → else 422
  4. Payout.objects.filter(store=store, status='processing').exists()
     → if True: 422 'A payout is already being processed.'
  5. amount >= MIN_PAYOUT_AMOUNT (default 500 XOF) → else 422
  6. store.balance >= amount → else 422 'Insufficient balance.'

Server — atomic creation (db_transaction.atomic()):
  a. balance_before = store.balance
  b. balance_after = balance_before - amount
  c. Transaction.objects.create(
       store=store, transaction_type='payout', direction='debit',
       amount=amount, balance_before=balance_before, balance_after=balance_after,
       status='pending', description='Payout request — <method>'
     )
  d. store.balance = balance_after
  e. store.save(update_fields=['balance'])
  f. Payout saved with transaction=<ledger_entry>
  ← If ANY step fails: entire atomic block is rolled back

Response 201: PayoutSerializer
  { id, amount, currency, method, destination, status, transaction_id, processed_at, created_at }
```

#### View Transaction History (Vendor)

```
GET /api/v1/transactions/
→ filter(store__owner=user)
→ TransactionSerializer (vendor view):
   Returns: uuid, transaction_type, direction, amount, currency,
            balance_after, status, reference, description, processed_at
   STRIPPED: metadata (may contain payment processor internals), balance_before
```

---

### 6.3 Customer Journey — Browse to Review

#### Browse Products

```
GET /api/v1/products/
→ Returns all status='active' products
→ Filters: ?category=<slug>, ?store=<slug>, ?search=<term>
→ Ordering: ?ordering=recent|price_asc|price_desc|bestseller|rating
→ ProductListSerializer — lightest payload (card view data only)

GET /api/v1/products/{slug}/
→ ProductPublicSerializer:
   Returns: title, description, short_description, price, compare_price,
            images, tags, category, store (public), variants (public)
   NEVER:  cost_price, sku, barcode, track_inventory, low_stock_threshold,
           digital_file, seo_title, seo_description
```

#### Browse Stores

```
GET /api/v1/stores/
→ PublicStoreViewSet — status='active' stores only
→ Uses .only() for DB optimisation (fetches only public-safe columns)
→ PublicStoreSerializer:
   Returns: name, slug, description, logo, banner, subscription_tier,
            level, total_orders, avg_rating, is_verified, country, currency
   NEVER:  balance, pending_balance, commission_rate, owner (FK)

GET /api/v1/stores/{slug}/
→ Same public serializer, lookup by slug
```

#### Browse Reviews

```
GET /api/v1/reviews/
→ filter(is_published=True) for public/customers
→ ReviewPublicSerializer:
   Returns: author (PublicUserSerializer — name+avatar only, NEVER email),
            rating, title, body, images, is_verified,
            vendor_reply, replied_at, created_at
   NEVER:  order ID (privacy — customers shouldn't see each other's order IDs),
           flagged, is_published
```

#### Place an Order

> ⚠️ **Order creation is not yet implemented.** `OrderViewSet` intentionally has no `create` method. This is the most important missing piece of the backend. The checkout endpoint must be atomic: payment intent creation + inventory reservation + order record creation, all in a single DB transaction. Do not add `CreateModelMixin` to `OrderViewSet`.

#### View Own Orders

```
GET /api/v1/orders/
→ filter(customer=user)
→ OrderCustomerSerializer:
   Returns: order_number, status, payment_status, payment_method,
            items (full OrderItemSerializer), subtotal, shipping_amount,
            discount_amount, total_amount, currency, shipping_address,
            tracking_number, carrier, estimated_delivery, delivered_at, notes
   NEVER:  payment_reference (admin only), commission_amount (internal),
           billing_address (invoice endpoint only — not built yet)

GET /api/v1/orders/{id}/
→ Same serializer, single order
```

#### Write a Review

```
POST /api/v1/reviews/
Requires: authenticated customer
Body: { product: <uuid>, order: <uuid>, rating: 1-5, title?, body?, images? }

Server:
  1. role == 'customer' → else 403
  2. Purchase verification:
     OrderItem.objects.filter(
       order__customer=user,
       order__uuid=body['order'],
       product__uuid=body['product']
     ).exists() → if False: 422 'You can only review products you have purchased.'
  3. Product.objects.get(uuid=product_uuid)
  4. Order.objects.get(uuid=order_uuid, customer=user)
  5. serializer.save(customer=user, product=product, order=order, store=product.store)
     ← store is always injected server-side, never from client
  6. is_published defaults to False (moderation pending)
     unique_together: ['product', 'order', 'customer'] — one review per purchase

Response 201: ReviewPublicSerializer
```

> Note: the spec says `is_published` transitions to `True` automatically after 24h if not flagged. This cron job is not yet implemented.

#### Send a Message

```
POST /api/v1/reviews/messages/
Body: { receiver: <user_id>, thread_id, content, order?: <id>, store?: <id>, attachments?: [] }

Server:
  - sender = request.user (always server-side, NEVER from body)
  - is_auto = False (server flag, never client-writable)
  - Messages are IMMUTABLE after sending (no update, no delete)

GET /api/v1/reviews/messages/
→ filter(Q(sender=user) | Q(receiver=user))
→ Ordered by thread_id, created_at

POST /api/v1/reviews/messages/{id}/mark_read/
→ Receiver marks message as read
→ Checks message.receiver == request.user → else 403
→ Sets is_read=True, read_at=now()
```

#### Notifications

```
GET /api/v1/reviews/notifications/
→ filter(user=request.user)
→ NotificationSerializer:
   Returns: notification_type, title, body, link, is_read, created_at
   STRIPPED: channels, sent_via (delivery infrastructure), metadata

POST /api/v1/reviews/notifications/{id}/mark_read/
→ Sets is_read=True

POST /api/v1/reviews/notifications/mark_all_read/
→ Bulk update: sets is_read=True for all unread notifications of the user
→ Returns: { marked_read: <count> }
```

---

### 6.4 Admin Operations

#### User Management

Admins use the Django admin panel for user management. No dedicated API endpoints for user banning exist yet (the `is_banned` field exists in the model and is checked at login, but the admin endpoint to set it is not built).

#### Full Data Access

Admins receive the most permissive serializer at every endpoint:

```
GET /api/v1/orders/          → OrderAdminSerializer (fields='__all__' including payment_reference)
GET /api/v1/transactions/    → TransactionAdminSerializer (all fields including metadata, balance_before)
GET /api/v1/reviews/         → ReviewAdminSerializer (all fields including flagged, is_published)
GET /api/v1/orders/payouts/  → PayoutAdminSerializer (all fields including failure_reason, external_ref)
GET /api/v1/stores/my/       → StoreSerializer (all stores, not just their own)
```

#### Category Management

```
POST /api/v1/products/categories/   ← admin only
PUT  /api/v1/products/categories/{slug}/   ← admin only
DELETE /api/v1/products/categories/{slug}/ ← admin only
GET  /api/v1/products/categories/   ← public
```

#### Delete Reviews

```
DELETE /api/v1/reviews/{id}/
→ Only admins can delete reviews
→ Customers get 403, vendors get 403
```

#### Moderate Reviews

```
PATCH /api/v1/reviews/{id}/
Body: { is_published: true/false, flagged: true/false, ... }
→ Admins can set all fields via ReviewAdminSerializer
```

---

### 6.5 Order Processing & Payment Flow

> **This section describes what MUST be built. It is NOT yet implemented.**

The current state: `Order`, `OrderItem` models exist and are readable. There is no endpoint to create orders. Developers building the checkout must follow these constraints:

**Required: Atomic Checkout Endpoint**

```
POST /api/v1/checkout/   ← new endpoint, does NOT go in OrderViewSet

Atomic block (all or nothing):
  1. Validate cart items (products exist, are active, have sufficient quantity)
  2. Validate coupon if provided (Coupon.objects.get + all validity checks)
  3. Create payment intent with Stripe or Moneroo
  4. Reserve inventory: Product.quantity -= item.quantity for each item
     (use select_for_update() to prevent race conditions)
  5. Order.objects.create(
       customer=user, store=store, order_number=generate_unique_number(),
       items=[...], subtotal=..., shipping_amount=..., discount_amount=...,
       total_amount=..., payment_reference=<gateway_reference>,
       payment_status='pending', status='pending'
     )
  6. OrderItem.objects.bulk_create([...])
  7. If coupon: Coupon.used_count += 1 (F expression, atomic)
  8. Return { order_number, client_secret or redirect_url }
```

**Payment Webhook (Stripe/Moneroo)**

Once the gateway confirms payment, a webhook handler must:

```
POST /api/v1/webhooks/stripe/   (or /moneroo/)

Verified webhook → payment confirmed:
  1. Order.payment_status = 'paid'; Order.status = 'paid'
  2. Transaction.objects.create(
       store=order.store, order=order,
       transaction_type='sale', direction='credit',
       amount=order.total_amount - commission_amount,
       balance_before=store.balance,
       balance_after=store.balance + net_amount,
       status='completed'
     )
  3. store.balance = balance_after; store.save()
  4. store.total_orders += 1; store.save()
  5. Recalculate store.level via store.calculate_level()
  6. Create Notification for vendor (order_new type)
```

---

### 6.6 Financial Ledger — Payout & Transactions

#### How the Ledger Works

Every money movement creates an immutable `Transaction` record. There is never an UPDATE on the transactions table. If an error occurs, a new transaction of type `reversal` is created referencing the original.

```
Transaction types:
  sale         → direction=credit  — payment received from customer
  refund       → direction=debit   — money returned to customer
  payout       → direction=debit   — vendor withdrawal
  fee          → direction=debit   — platform commission
  credit       → direction=credit  — manual credit by admin
  transfer     → varies            — inter-store or internal transfer
  ad_payment   → direction=debit   — vendor pays for advertising slot
  subscription → direction=debit   — Pro/Business plan payment
```

The payout flow is the only one currently implemented end-to-end:

```
Payout creation (atomic):
  balance_before = store.balance          (e.g. 15000 XOF)
  balance_after  = balance_before - amount (e.g. 15000 - 10000 = 5000 XOF)

  Transaction record:
    type=payout, direction=debit
    amount=10000, balance_before=15000, balance_after=5000
    status=pending

  store.balance = 5000   (deducted atomically)

  Payout record:
    transaction → FK to the Transaction created above
    status=pending → changes to processing/completed/failed by external payout service

Vendor sees (TransactionSerializer):
  transaction_type, direction, amount, currency, balance_after (not balance_before),
  status, reference, description

Admin sees (TransactionAdminSerializer):
  all fields including metadata, balance_before
```

#### Payout Status Lifecycle

```
pending     → Payout created, transaction created, balance deducted
processing  → External service (bank/mobile money) is processing
completed   → Money successfully sent
failed      → Transfer failed; balance should be restored via reversal transaction

RULE: Only ONE payout per store can be in 'processing' state at a time.
This is enforced at creation: if a processing payout exists → 422.
```

---

### 6.7 Messaging & Notifications

#### Thread Model

Messages are grouped by `thread_id` (a string — can be order ID or any custom identifier). There is no Thread model — `thread_id` is just a string on the Message model that the frontend uses to group messages in a conversation view.

```
Fetch a thread:
GET /api/v1/reviews/messages/?thread_id=<value>
→ All messages where sender=user OR receiver=user, ordered by thread_id + created_at

Note: thread_id filtering is not explicitly implemented in the view — the frontend
must filter client-side or a filter backend must be added.
```

#### Notification Types

```
order_new       → Vendor: a customer placed an order
order_status    → Customer: order status changed (pending→shipped, etc.)
low_stock       → Vendor: product quantity <= low_stock_threshold
payment         → Vendor: payment received
review          → Vendor: customer left a review
system          → Platform-wide system message
promo           → Promotional notification

Notifications are system-generated only — no client can POST a notification.
Channels (push, email, sms, whatsapp) are stored but not exposed to clients.
```

---

## 7. API Endpoint Reference

### Auth — `/api/v1/auth/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/register/` | Public | Create account (vendor or customer) — throttled 10/min |
| POST | `/login/` | Public | Step 1 — credentials (throttled 5/min, returns `pending_token` if 2FA enabled) |
| POST | `/login/2fa/` | Public | Step 2 — verify TOTP code (max 5 attempts per token) |
| POST | `/logout/` | Required | Blacklist refresh token |
| POST | `/refresh/` | Public | Rotate JWT pair |
| GET | `/me/` | Required | Read profile |
| PATCH | `/me/` | Required | Update name, avatar, phone, locale |
| PUT | `/me/password/` | Required | Change password (invalidates all sessions) |
| DELETE | `/me/delete/` | Required | Soft delete account (requires password confirmation) |
| POST | `/2fa/setup/` | Required | Generate TOTP secret + QR code (must verify after) |
| POST | `/2fa/verify/` | Required | Activate 2FA (confirms setup) |
| POST | `/2fa/disable/` | Required | Disable 2FA (blocked if pending payout) |

### Stores — `/api/v1/stores/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/` | Public | List active stores (`PublicStoreSerializer`) |
| GET | `/{slug}/` | Public | Public store detail (no financials) |
| GET | `/my/` | Vendor | List own store |
| POST | `/my/` | Vendor | Create store (enforced: max 1 per vendor) |
| GET | `/my/{id}/` | Vendor | Store detail with financials |
| PUT | `/my/{id}/` | Vendor | Full update store info |
| PATCH | `/my/{id}/` | Vendor | Partial update store info |
| DELETE | `/my/{id}/` | Vendor | Close store |
| GET | `/my/{id}/dashboard/` | Vendor | KPIs (`?period=today\|week\|month`) |
| GET | `/my/{id}/balance/` | Vendor | Current balance (available + pending) |

### Products — `/api/v1/products/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/categories/` | Public | Category list (tree structure) |
| POST | `/categories/` | Admin | Create category |
| GET | `/categories/{slug}/` | Public | Category detail |
| PUT | `/categories/{slug}/` | Admin | Update category |
| PATCH | `/categories/{slug}/` | Admin | Partial update category |
| DELETE | `/categories/{slug}/` | Admin | Delete category |
| GET | `/` | Public | Product list (active only, filterable) |
| POST | `/` | Vendor | Create product |
| GET | `/{slug}/` | Public | Product detail (role-aware serializer) |
| PUT | `/{slug}/` | Vendor (owner) | Full update product |
| PATCH | `/{slug}/` | Vendor (owner) | Partial update product |
| DELETE | `/{slug}/` | Vendor (owner) | Delete product |
| POST | `/{slug}/duplicate/` | Vendor (owner) | Duplicate product as draft (copies variants) |
| PATCH | `/{slug}/inventory/` | Vendor (owner) | Adjust stock quantity directly |
| GET | `/{slug}/variants/` | Public | List variants |
| POST | `/{slug}/variants/` | Vendor (owner) | Create variant |
| GET | `/{slug}/variants/{uuid}/` | Vendor (owner) | Variant detail |
| PUT | `/{slug}/variants/{uuid}/` | Vendor (owner) | Update variant |
| PATCH | `/{slug}/variants/{uuid}/` | Vendor (owner) | Partial update variant |
| DELETE | `/{slug}/variants/{uuid}/` | Vendor (owner) | Delete variant |

### Orders — `/api/v1/orders/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/` | Required | List orders (role-scoped: customer=own, vendor=store, admin=all) |
| GET | `/{id}/` | Required | Order detail (role-scoped serializer) |
| PATCH | `/{id}/` | Vendor/Admin | Update status, tracking, carrier (customers blocked) |
| GET | `/coupons/` | Vendor/Admin | List coupons (vendor: own store, admin: all) |
| POST | `/coupons/` | Vendor | Create coupon |
| GET | `/coupons/{id}/` | Vendor/Admin | Coupon detail |
| PUT | `/coupons/{id}/` | Vendor | Update coupon |
| PATCH | `/coupons/{id}/` | Vendor | Partial update coupon |
| DELETE | `/coupons/{id}/` | Vendor | Delete coupon |
| POST | `/coupons/validate/` | Required | Validate coupon at checkout (returns discount info) |
| GET | `/payouts/` | Vendor/Admin | List payouts (vendor: own store, admin: all) |
| POST | `/payouts/` | Vendor | Request payout (requires 2FA, atomic transaction) |
| GET | `/payouts/{id}/` | Vendor/Admin | Payout detail |

> **Note:** Order creation (`POST /orders/`) is intentionally NOT implemented. A dedicated checkout endpoint will handle atomic payment + inventory + order creation.

### Transactions — `/api/v1/transactions/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/` | Vendor/Admin | List transactions (vendor: own store, admin: all) |
| GET | `/{id}/` | Vendor/Admin | Transaction detail (role-scoped serializer) |

> **Note:** Transactions are read-only and immutable. No create/update/delete endpoints exist.

### Reviews — `/api/v1/reviews/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/` | Public | Published reviews (vendor sees all including unpublished) |
| POST | `/` | Customer | Create review (requires verified purchase) |
| GET | `/{id}/` | Public | Review detail |
| PUT | `/{id}/` | Admin | Full update review |
| PATCH | `/{id}/` | Vendor/Admin | Vendor: reply only. Admin: all fields |
| DELETE | `/{id}/` | Admin | Delete review |
| GET | `/messages/` | Required | List messages (sent or received) |
| POST | `/messages/` | Required | Send message (immutable after creation) |
| GET | `/messages/{id}/` | Required | Message detail |
| POST | `/messages/{id}/mark_read/` | Required | Mark message as read (receiver only) |
| GET | `/notifications/` | Required | List own notifications |
| GET | `/notifications/{id}/` | Required | Notification detail |
| POST | `/notifications/{id}/mark_read/` | Required | Mark notification as read |
| POST | `/notifications/mark_all_read/` | Required | Mark all notifications as read |

### API Documentation — `/api/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/schema/` | Public | OpenAPI 3.0 schema (JSON) |
| GET | `/docs/` | Public | Swagger UI interactive documentation |
| GET | `/redoc/` | Public | ReDoc documentation |

### Django Admin — `/admin/`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| * | `/admin/` | Admin (superuser) | Django admin panel |

---

## 8. Permissions Architecture

### Custom Permission Classes

| Class | File | Rule |
|---|---|---|
| `IsStoreOwner` | `stores/views.py` | `obj.owner == request.user` |
| `IsProductOwner` | `products/views.py` | `obj.store.owner == request.user` (write only; reads are public) |
| `IsAdminUser` | DRF built-in | `user.is_staff == True` |
| `IsAuthenticatedOrReadOnly` | DRF built-in | Anonymous = safe methods only |

### Endpoint Access Matrix

```
Endpoint                                 Anon    Customer   Vendor(own)   Admin
────────────────────────────────────────────────────────────────────────────────────
POST /auth/register/                     ✅       ✅          ✅            ✅
POST /auth/login/                        ✅       ✅          ✅            ✅

GET  /products/                          ✅list   ✅list      ✅list        ✅list
GET  /products/{slug}/                   ✅pub    ✅pub       ✅full        ✅full
POST /products/                          ❌       ❌          ✅            ✅
PUT  /products/{slug}/                   ❌       ❌          ✅ owner      ✅

GET  /stores/                            ✅pub    ✅pub       ✅pub         ✅pub
GET  /stores/{slug}/                     ✅pub    ✅pub       ✅pub         ✅pub
GET  /stores/my/{id}/                    ❌       ❌          ✅ owner      ✅all
GET  /stores/my/{id}/dashboard/          ❌       ❌          ✅ owner      ✅

GET  /orders/                            ❌       ✅ own      ✅ store      ✅all
PATCH /orders/{id}/                      ❌       ❌          ✅ store      ✅
POST /orders/coupons/validate/           ❌       ✅          ✅            ✅
POST /orders/payouts/                    ❌       ❌          ✅+2FA        ❌

GET  /transactions/                      ❌       ❌          ✅ store      ✅all

GET  /reviews/                           ✅pub    ✅pub       ✅+unpublished ✅all
POST /reviews/                           ❌       ✅ bought   ❌            ✅
PATCH /reviews/{id}/                     ❌       ❌          ✅ reply only ✅ all fields
DELETE /reviews/{id}/                    ❌       ❌          ❌            ✅

GET  /reviews/messages/                  ❌       ✅ own      ✅ own        ✅all
GET  /reviews/notifications/             ❌       ✅ own      ✅ own        ✅all
```

`pub` = public serializer (sensitive fields stripped).
`+unpublished` = vendors see unpublished reviews for their store (for moderation).
`+2FA` = 2FA must be enabled on the account.

---

## 9. Serializer Strategy — Data Exposure Rules

**The rule: expose the minimum data required for the consumer's legitimate use case.**

Every field exclusion is intentional. Here is what is stripped and why:

| Field | Stripped from | Reason |
|---|---|---|
| `cost_price` | Public/Customer serializers | Vendor margin — private business figure |
| `sku`, `barcode` | Public product serializer | Internal inventory codes |
| `track_inventory`, `low_stock_threshold` | Public product serializer | Internal ops data |
| `digital_file` | Public product serializer | Served via signed URL, not directly |
| `seo_title`, `seo_description` | Public product serializer | Rendered server-side by Next.js |
| `balance`, `pending_balance` | `PublicStoreSerializer` | Financial — owner only |
| `commission_rate` | `PublicStoreSerializer` | Internal business config |
| `payment_reference` | Customer + Vendor order serializers | Raw payment gateway token — admin only |
| `commission_amount` | `OrderCustomerSerializer` | Platform fee — internal |
| `billing_address` | `OrderCustomerSerializer` | Invoice endpoint only (not built yet) |
| `metadata` | `TransactionSerializer`, `NotificationSerializer` | May contain internal payment processor IDs |
| `balance_before` | `TransactionSerializer` (vendor) | Can be inferred; reduces payload |
| `failure_reason`, `external_ref` | `PayoutSerializer` (vendor) | Admin-only — operational/sensitive |
| `flagged` | `ReviewPublicSerializer` | Leaks moderation state — customers could game it |
| `is_published` | `ReviewPublicSerializer` | Internal moderation flag |
| `is_auto` | `MessageSerializer` | Server-only flag for system messages |
| `channels`, `sent_via` | `NotificationSerializer` | Delivery infrastructure internals |
| `totp_secret` | **All serializers** | Never in any response, ever |
| `is_banned`, `auth_provider` | `UserSerializer` | Internal admin fields |

### The `PublicUserSerializer` Rule

Whenever a user is embedded in another resource's response (review author, message sender), use `PublicUserSerializer`, **never** `UserSerializer`. It exposes only `id`, `name`, `avatar`.

```python
# ✅ Correct — review author shows name + avatar only
class ReviewPublicSerializer(serializers.ModelSerializer):
    author = PublicUserSerializer(source='customer', read_only=True)

# ❌ Wrong — would expose customer email to anyone reading a review
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
```

---

## 10. Security Rules — Read Before You Code

### Authentication Rules

1. **Never return `user_id` in the 2FA challenge.** Use `pending_token` (Redis-backed opaque token) only.
2. **Never remove the 2FA attempt counter.** Max 5 attempts per token, then destroy both Redis keys.
3. **Invalidate all sessions on password change.** Call `_blacklist_all_tokens_for(user)` — stolen refresh tokens from before the reset must not be reusable.
4. **`totp_secret` must never appear in any API response.** Not in any serializer. Not in logs.

### Registration Rules

5. **`validate_role()` in `UserRegistrationSerializer` blocks `role='admin'`.** Never remove this validation or make it conditional.
6. **Email is case-normalized** (lowercased) at login. Enforce the same at registration.

### Data Access Rules

7. **All monetary amounts are integers in XOF.** No subdivisions. Never store or compute money as floats.
8. **Transactions are immutable.** No `UPDATE` on the transactions table. Ever. Use a `reversal` transaction for corrections.
9. **Vendors cannot see other stores' data.** Every `get_queryset()` filters by `store__owner=user` for non-admins.
10. **`payment_reference` is admin-only.** Never include it in customer or vendor serializers.

### Financial Rules

11. **Payout creation is atomic.** Transaction creation + balance deduction + Payout save must be a single `db_transaction.atomic()` block. If anything fails, nothing commits.
12. **Only one `processing` payout per store at a time.** Enforced at payout creation via `Payout.objects.filter(store=store, status='processing').exists()`.
13. **2FA is required before any payout.** `is_2fa_enabled` checked at payout creation. Vendors should be encouraged to enable 2FA immediately after store creation.

### Review Rules

14. **Reviews require a verified purchase.** Check `OrderItem.objects.filter(order__customer=user, order__uuid=..., product__uuid=...).exists()` before creating.
15. **Review `store` is always server-injected** from `product.store`. Never accept it from the client.
16. **Vendors can only set `vendor_reply`.** Any other field in a vendor PATCH raises 403.

### General Patterns

```python
# ✅ Blacklist all sessions after password change
def _blacklist_all_tokens_for(user):
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)

# ✅ Atomic payout creation
with db_transaction.atomic():
    ledger_entry = Transaction.objects.create(...)
    store.balance = balance_after
    store.save(update_fields=['balance'])
    serializer.save(store=store, initiated_by=user, transaction=ledger_entry)

# ✅ Atomic 2FA attempt counter
cache.add(a_key, 0, timeout=300)      # sets only if absent (no race)
attempts = cache.incr(a_key)           # atomic increment, returns new value
```

---

## 11. Known Gaps & What's Next

| Feature | Status | Notes |
|---|---|---|
| **Checkout / Order creation** | ❌ **Critical missing** | Highest priority. Atomic endpoint: payment intent + inventory reservation + Order + OrderItem creation. Without this, no purchases can happen. |
| **Stripe / Moneroo webhooks** | ❌ Not done | Keys configured in settings, handler views missing. Required to update `payment_status` and credit `store.balance` after payment. |
| **Email verification on register** | ❌ Not done | `is_verified=False` is set but no email is sent, no token is generated. |
| **Forgot / reset password** | ❌ Not done | No endpoint exists yet. |
| **Social auth (Google, Facebook)** | ❌ Not done | `auth_provider` field exists in the model, no OAuth flow implemented. |
| **Payout execution** | ⚠️ Stub | Payout records are created and balance is deducted, but no actual bank/mobile money transfer logic exists. A background service or webhook must handle `status=processing → completed/failed`. |
| **`totp_secret` encryption at rest** | ✅ Done | Encrypted with Fernet (AES-128) via `ENCRYPTION_KEY` setting. |
| **Per-endpoint rate limiting** | ✅ Done | Login: 5/min, Register: 10/min. Global: 60/min anon, 300/min user. |
| **Account deletion** | ✅ Done | `DELETE /auth/me/delete/` — soft delete with 30-day retention. Requires password confirmation. |
| **`change_pct` in dashboard** | ⚠️ Stub | Always returns `0`. Needs period comparison (current vs previous period). |
| **`conversion` in dashboard** | ⚠️ Stub | Always returns `0`. No visit tracking implemented. |
| **is_published auto-approval** | ❌ Not done | Spec: reviews auto-publish after 24h if not flagged. Requires a cron job or Celery task. |
| **Thread filtering in messages** | ⚠️ Partial | Messages are ordered by `thread_id + created_at` but `?thread_id=` filter is not implemented. |
| **Admin user ban endpoint** | ❌ Not done | `is_banned` field exists and is checked at login, but no API endpoint to set it. |
| **Redis cache backend** | ✅ Done | Configured in `settings.py` with `REDIS_URL` env var. |
| **Tests** | ❌ None | Highest priority before production. Start with auth flow, then payout atomicity. |

### Recommended Build Order

1. ~~Configure Redis in `settings.py` — 2FA depends on it~~ ✅ Done
2. ~~Encrypt `totp_secret` at rest~~ ✅ Done
3. Implement the checkout endpoint (the entire purchase flow is blocked without it)
4. Connect Stripe/Moneroo webhooks (required to complete payment flow)
5. Implement email verification
6. Write tests starting with auth and payout

---

## 12. Full Change Log

### Pass 1 — Bug Fixes (February 2026)

| # | Sev | File | Problem | Fix |
|---|---|---|---|---|
| 1 | 🔴 | `settings.py` | `token_blacklist` missing from `INSTALLED_APPS` — logout never blacklisted tokens | Added `rest_framework_simplejwt.token_blacklist` |
| 2 | 🔴 | `users/views.py` | `LoginView` returned `user_id` in 2FA challenge — user enumeration + brute-force target | Replaced with opaque `pending_token` in Redis (5-min TTL) |
| 3 | 🔴 | `users/views.py` | `Login2FAView` had no attempt limiting — all 1M TOTP codes could be tried freely | Redis counter per token, max 5 attempts |
| 4 | 🔴 | `stores/views.py` | `models.F(...)` used without `from django.db import models` — `NameError` on every dashboard request | Added the missing import |
| 5 | 🔴 | `products/views.py` | `self.request.user.role` called on `AnonymousUser` — `AttributeError` on public endpoints | Added `is_authenticated` guard before `.role` |
| 6 | 🟠 | `stores/serializers.py` | Public store list exposed `balance`, `pending_balance`, `commission_rate` | Created `PublicStoreSerializer` |
| 7 | 🟠 | `reviews/views.py` | `ReviewViewSet` returned `Review.objects.all()` — every authenticated user read every review | Scoped to authored reviews + own-store reviews |
| 8 | 🟠 | `stores/views.py` | No one-store-per-vendor enforcement | Added check in `perform_create` |
| 9 | 🟡 | `products/serializers.py` | Slug generation loop duplicated across stores and products | Extracted into `unique_slug()` utility |
| 10 | 🟡 | `settings.py` | `SECRET_KEY` and DB credentials had insecure fallback defaults | Removed all defaults |

### Pass 2 — Serializer Security & Data Minimisation (February 2026)

| # | Sev | File | Problem | Fix |
|---|---|---|---|---|
| 11 | 🔴 | `users/serializers.py` | Registration accepted `role: "admin"` — self-promotion to admin | Added `validate_role` blocking `admin` |
| 12 | 🔴 | `products/serializers.py` | `cost_price` exposed on public product detail | Created `ProductPublicSerializer` |
| 13 | 🔴 | `orders/` | No serializers existed — all fields exposed including `payment_reference`, `commission_amount` | Created role-scoped `Order*Serializer` hierarchy |
| 14 | 🔴 | `orders/views.py` | `OrderViewSet(ModelViewSet)` — customers could `PATCH` orders | Changed to explicit mixins; customer writes raise 403 |
| 15 | 🔴 | `transactions/` | No serializers — `metadata` JSONField fully exposed | Created `TransactionSerializer` (strips `metadata`, `balance_before`) |
| 16 | 🟠 | `reviews/` | No serializers — `flagged`, `is_published`, `is_auto`, `channels` all exposed | Created full serializer hierarchy per role |
| 17 | 🟠 | `reviews/views.py` | No purchase verification on review create | Added `OrderItem` existence check in `perform_create` |
| 18 | 🟠 | `reviews/views.py` | Vendor `update` had no field restriction — could modify rating, body | Restricted to `vendor_reply` only; others raise 403 |
| 19 | 🟠 | `products/serializers.py` | `sku`, `barcode`, `track_inventory`, `low_stock_threshold`, `seo_*`, `digital_file` exposed publicly | Stripped from `ProductPublicSerializer` |
| 20 | 🟠 | `products/serializers.py` | `ProductVariantSerializer` exposed `sku` and `weight` publicly | Created `ProductVariantPublicSerializer` |
| 21 | 🟠 | `orders/serializers.py` | `billing_address` returned in every customer order response | Excluded (invoice endpoint only) |
| 22 | 🟠 | `orders/views.py` | `PayoutViewSet` had no validation — no 2FA check, no balance check, any role could create | Added: vendor-only, 2FA required, min amount, sufficient balance |
| 23 | 🟡 | `users/serializers.py` | `UserSerializer` included `auth_provider`, `is_banned`, `last_login_at` | Removed — frontend doesn't need them |
| 24 | 🟡 | `reviews/serializers.py` | Review author shown as full user — would expose email publicly | Replaced with `PublicUserSerializer` |
| 25 | 🟡 | `orders/serializers.py` | Coupon `validate` leaked `used_count`, `max_uses` | Created `CouponPublicSerializer` |
| 26 | 🟡 | `orders/views.py` | Coupon `validate` did not check `starts_at` — future coupons were accepted | Added `starts_at > now` guard |
| 27 | 🟡 | `orders/views.py` | Fixed discount could make `new_total` negative | `discount_amount` capped at `cart_total` |
| 28 | 🟡 | `reviews/serializers.py` | `channels`, `sent_via`, `metadata` on notifications exposed | Excluded from `NotificationSerializer` |
| 29 | 🟡 | `reviews/serializers.py` | `is_auto` on messages exposed | Excluded from `MessageSerializer` |
| 30 | 🟡 | `products/serializers.py` | No price validation on create/update | Added `validate_price` (> 0) and `compare_price > price` cross-validation |

### Pass 3 — 2FA Deep Audit (February 2026)

| # | Sev | File | Problem | Fix |
|---|---|---|---|---|
| 31 | 🔴 | `users/views.py` | `Login2FAView` attempt counter used `get()` + `set()` — race condition allowed unlimited parallel requests to bypass the 5-attempt limit | Replaced with atomic `cache.add()` + `cache.incr()` |
| 32 | 🟠 | `users/views.py` | `TOTPSetupView` was a `GET` that wrote to DB — browser prefetch could silently overwrite a secret mid-scan | Changed to `POST`; `urls.py` updated |
| 33 | 🟠 | `users/views.py` | `ChangePasswordView` did not invalidate existing sessions — stolen refresh tokens remained valid after a password reset | Added `_blacklist_all_tokens_for(user)` |
| 34 | 🟡 | `users/views.py` | `TOTPDisableView` ran business checks before input validation — error messages revealed account state | Moved `serializer.is_valid()` to run first |

### Pass 4 — Payout Ledger (February 2026)

| # | Sev | File | Problem | Fix |
|---|---|---|---|---|
| 35 | 🔴 | `orders/models.py` | `Payout` had no link to `Transaction` — payouts were created without a ledger entry | Added `transaction = OneToOneField(Transaction, ...)` |
| 36 | 🔴 | `orders/views.py` | `PayoutViewSet.perform_create()` created a Payout without creating a Transaction or deducting `store.balance` — the financial ledger was never updated | Rewritten as atomic block: create Transaction + deduct balance + save Payout |
| 37 | 🟠 | `orders/views.py` | No check for an in-progress payout on the same store — concurrent payout requests could over-draw the balance | Added `filter(store=store, status='processing').exists()` guard |
| 38 | 🟡 | `orders/serializers.py` | `PayoutSerializer` did not expose `transaction_id` — vendors could not cross-reference their payouts with their ledger | Added `transaction_id` as read-only field |
| 39 | 🟡 | `orders/migrations/` | Migration `0004_payout_transaction.py` written manually to avoid `makemigrations` false positive on `OrderItem.uuid` | Manual `AddField` migration — do not use `makemigrations orders` |

---

## 13. Environment Variables Reference

All variables are required unless marked optional.

```bash
# Django — REQUIRED
SECRET_KEY=your-long-random-secret-key-min-50-chars
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# MySQL — REQUIRED
DB_NAME=pixelmart
DB_USER=pixelmart_user
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=5432

# Redis — REQUIRED (2FA will be broken without it)
REDIS_URL=redis://localhost:6379/0

# Encryption — REQUIRED for totp_secret encryption at rest
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your-fernet-key-here

# CORS — REQUIRED
CORS_ALLOWED_ORIGINS=https://yourdomain.com

To see the verification email, check the terminal where Django is running, or configure a real SMTP server in .env:
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
For Gmail: Use an App Password (https://support.google.com/accounts/answer/185833) instead of your regular password.

# JWT — optional, defaults shown
# ACCESS_TOKEN_LIFETIME=60 minutes
# REFRESH_TOKEN_LIFETIME=7 days

# Payout — optional, default 500 XOF
# MIN_PAYOUT_AMOUNT=500

# Stripe — optional during dev, required for payments
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Moneroo — optional during dev, required for African mobile money
MONEROO_SECRET_KEY=xxx
MONEROO_WEBHOOK_SECRET=xxx
```

> ⚠️ Never commit `.env` to git. Share secrets via a password manager or encrypted vault — never Slack or email.

---

*This document describes what the code currently does, not what it should eventually do. Update it whenever a new endpoint is built, a security decision is changed, or a known gap is resolved.*