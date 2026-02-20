# PixelMart — Backend Developer Guide

> **Stack:** Django 4.2+ · Django REST Framework · MySQL · JWT (SimpleJWT) · Stripe · Moneroo  
> **Last updated:** February 2026  
> **Author:** Initial architecture by Franck ZINSOU (CTO)  
> **Security passes:** Bug fix pass (Feb 2026) · Serializer & data exposure pass (Feb 2026) · 2FA deep audit (Feb 2026)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Getting Started](#2-getting-started)
3. [Project Structure](#3-project-structure)
4. [Apps & Responsibilities](#4-apps--responsibilities)
5. [Authentication & Security Model](#5-authentication--security-model)
6. [API Conventions](#6-api-conventions)
7. [Permissions Architecture](#7-permissions-architecture)
8. [Serializer Strategy — The Core Pattern](#8-serializer-strategy--the-core-pattern)
9. [Security Rules — Read Before You Code](#9-security-rules--read-before-you-code)
10. [Full Change Log](#10-full-change-log)
11. [Known Gaps & What's Next](#11-known-gaps--whats-next)
12. [Environment Variables Reference](#12-environment-variables-reference)
13. [Appendix — Data Flow Diagrams](#13-appendix--data-flow-diagrams)

---

## 1. Project Overview

PixelMart is an **AI-powered African marketplace** where vendors open digital stores and sell products to customers. The backend is a Django REST Framework API serving a Next.js frontend.

### User Roles

| Role | Description |
|---|---|
| `customer` | Browses and buys products, writes reviews |
| `vendor` | Owns one store, lists products, manages orders, receives payouts |
| `admin` | Full platform access — can ban users, verify stores, see all data |

### Core Business Rules

- **One store per vendor.** Enforced server-side in `StoreViewSet.perform_create`.
- **Vendors must have 2FA enabled before requesting a payout.** Enforced in `PayoutViewSet.perform_create`.
- **Commission rates** vary by subscription tier — Free = 5%, Pro = 3%, Business = 2% (stored in `settings.COMMISSION_RATES` as basis points).
- **All monetary values stored as integers in centimes.** €1.00 = 100. Never use floats for money.
- **Reviews require a verified purchase.** A customer can only review a product they have an `OrderItem` for.
- **Order creation is intentionally NOT in `OrderViewSet`.** It requires its own atomic checkout endpoint (payment intent + inventory deduction). Do not add `CreateModelMixin` to `OrderViewSet`.
- **Payouts are immutable.** Once created, a `Payout` record cannot be updated or deleted via the API. Status changes are made by the payout processing service only.

---

## 2. Getting Started

### Prerequisites

- Python 3.11+
- MySQL 8+
- Redis (required — used by the 2FA pending token flow)

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
# → Edit .env with your values. The app will refuse to start if required vars are missing.

# 4. Run migrations (includes token_blacklist tables — required for logout to work)
python manage.py migrate

# 5. Create a superuser
python manage.py createsuperuser

# 6. Run the dev server
python manage.py runserver
```

> ⚠️ **Redis must be running** before starting the server. The 2FA login flow stores pending tokens in cache. If Redis is not configured, all 2FA logins will silently fail.

### API Docs

- **Swagger UI** → `http://localhost:8000/api/docs/`
- **ReDoc** → `http://localhost:8000/api/redoc/`

---

## 3. Project Structure

```
pixelmart-backend/
├── config/
│   ├── settings.py           # All Django settings — reads exclusively from .env
│   ├── urls.py               # Root URL routing
│   ├── wsgi.py
│   └── asgi.py
├── common/
│   ├── models.py             # TimeStampedModel base class
│   └── pagination/           # StandardPagination (20/page, max 100)
├── users/                    # Auth, registration, 2FA, profile
├── stores/                   # Vendor stores, dashboard, balances
├── products/                 # Catalog, categories, variants
├── orders/                   # Orders, coupons, payouts
├── transactions/             # Financial ledger (read-only)
├── reviews/                  # Product reviews, messages, notifications
├── requirements.txt
├── .env.example
└── DEVELOPER_GUIDE.md        # ← You are here
```

---

## 4. Apps & Responsibilities

### `common`
Base abstractions shared project-wide.
- **`TimeStampedModel`** — abstract model with `created_at` / `updated_at`. All models inherit from this.
- **`StandardPagination`** — `?page=1&limit=20`, max 100 per page.

### `users`
Everything about identity and authentication.

| File | Purpose |
|---|---|
| `models.py` | Custom `User` (email login, no username, roles, 2FA flags) |
| `serializers.py` | `UserSerializer` (post-login), `PublicUserSerializer` (name+avatar only — used when embedding a user in other objects), Registration, Password change, TOTP |
| `views.py` | Register, Login, 2FA login, Logout, Profile, TOTP setup/verify/disable |
| `urls.py` | All `/api/v1/auth/` routes |

### `stores`
Vendor store management + public discovery.

| File | Purpose |
|---|---|
| `models.py` | `Store` — status, subscription tier, balance, level, ratings |
| `serializers.py` | `StoreSerializer` (owner — includes financials), `PublicStoreSerializer` (anonymous — no financials ever), Create/Update |
| `views.py` | `StoreViewSet` (owner only, enforces 1-store rule) + `PublicStoreViewSet` (anonymous read, DB `.only()` optimised) |
| `urls.py` | `/my/` for owner routes, `/` for public |

### `products`
Product catalog with role-aware data exposure.

| File | Purpose |
|---|---|
| `models.py` | `Category`, `Product`, `ProductVariant` |
| `serializers.py` | `ProductListSerializer` (card — lightest), `ProductPublicSerializer` (detail — no `cost_price` or internals), `ProductSerializer` (vendor/admin — full), `ProductCreateSerializer`, public/full variant serializers, shared `unique_slug()` utility |
| `views.py` | Category CRUD (admin-only writes), Product CRUD (serializer chosen by role), Variant CRUD (public read, owner write) |

### `orders`
Purchase flow and payouts.

| File | Purpose |
|---|---|
| `models.py` | `Order`, `OrderItem`, `Coupon`, `Payout` |
| `serializers.py` | `OrderCustomerSerializer`, `OrderVendorSerializer`, `OrderAdminSerializer`, `CouponSerializer`, `CouponPublicSerializer` (for validate action), `PayoutSerializer`, `PayoutAdminSerializer` |
| `views.py` | `OrderViewSet` (no create — role-scoped read + vendor update only), `CouponViewSet`, `PayoutViewSet` (create validates 2FA + balance + ownership) |
| `urls.py` | `/api/v1/orders/`, `/api/v1/orders/coupons/`, `/api/v1/orders/payouts/` |

### `transactions`
Read-only financial ledger.

| File | Purpose |
|---|---|
| `models.py` | `Transaction` — ledger entries with type, direction, amount, metadata |
| `serializers.py` | `TransactionSerializer` (vendor — strips `metadata`, `balance_before`), `TransactionAdminSerializer` (full) |
| `views.py` | `TransactionViewSet` (ReadOnly, role-scoped serializer) |

### `reviews`
Reviews, messages, and notifications.

| File | Purpose |
|---|---|
| `models.py` | `Review`, `Message`, `Notification` |
| `serializers.py` | `ReviewPublicSerializer` (published only, `PublicUserSerializer` for author), `ReviewCreateSerializer` (minimal — server injects product/order/store), `ReviewVendorSerializer` (reply only), `ReviewAdminSerializer`, `MessageSerializer` (no `is_auto`), `NotificationSerializer` (no `metadata`/`channels`) |
| `views.py` | `ReviewViewSet` (purchase-verified create, vendor reply-only update, admin delete), `MessageViewSet` (immutable after send, `mark_read` action), `NotificationViewSet` (`mark_read` + `mark_all_read` actions) |

---

## 5. Authentication & Security Model

### JWT Flow

```
POST /api/v1/auth/register/  →  { user, access, refresh }
POST /api/v1/auth/login/     →  { user, access, refresh }  OR  { requires_2fa, pending_token }
POST /api/v1/auth/login/2fa/ →  { user, access, refresh }
POST /api/v1/auth/logout/    →  blacklists the refresh token
POST /api/v1/auth/refresh/   →  { access, refresh }  (rotates both, old token blacklisted)
```

All protected endpoints require:
```
Authorization: Bearer <access_token>
```

**Token lifetimes:**
- Access token: **60 minutes**
- Refresh token: **7 days**, rotated on each use

### 2FA Login Flow

The flow uses opaque tokens stored in Redis to avoid leaking internal user IDs.

```
1. POST /auth/login/
   ← { requires_2fa: true, pending_token: "Xk9...random...mQ" }
     └─ stored in Redis with 5-minute TTL

2. POST /auth/login/2fa/  { pending_token, code }
   → resolves user from Redis
   → checks attempt counter (max 5 per token — then token is deleted)
   → verifies TOTP code
   → deletes pending_token from Redis on success
   ← { user, access, refresh }
```

> ❌ **Never return `user_id` in the 2FA challenge.** `pending_token` only.  
> ❌ **Never remove the attempt counter.** Max 5 attempts, then destroy the token.

---

## 6. API Conventions

| Convention | Value |
|---|---|
| Base URL | `/api/v1/` |
| Auth header | `Authorization: Bearer {token}` |
| Pagination | `?page=1&limit=20` (max 100) |
| Ordering | `?ordering=recent` / `price_asc` / `price_desc` / `bestseller` / `rating` |
| Filters | `?status=active&category=mode&store=my-store` |
| Search | `?search=<term>` |
| Date format | ISO 8601 — `2026-02-19T23:32:00+01:00` |

**HTTP status codes:**

| Code | When |
|---|---|
| `200` | Successful GET / PATCH |
| `201` | Resource created |
| `204` | Deleted |
| `400` | Validation error |
| `401` | Not authenticated |
| `403` | Authenticated but not allowed |
| `404` | Not found |
| `422` | Business rule violation (coupon expired, insufficient balance…) |
| `429` | Rate limit exceeded |

---

## 7. Permissions Architecture

### Custom Permission Classes

| Class | File | Rule |
|---|---|---|
| `IsStoreOwner` | `stores/views.py` | `obj.owner == request.user` |
| `IsProductOwner` | `products/views.py` | `obj.store.owner == request.user` (write only) |
| `IsAdminUser` | DRF built-in | `user.is_staff == True` |
| `IsAuthenticatedOrReadOnly` | DRF built-in | Anonymous = read only |

### Endpoint Access Matrix

```
Endpoint                               Anon    Customer   Vendor(own)  Admin
──────────────────────────────────────────────────────────────────────────────
GET  /products/                        ✅       ✅          ✅           ✅
GET  /products/{slug}/                 ✅pub    ✅pub       ✅full       ✅full
POST /products/                        ❌       ❌          ✅           ✅
PUT  /products/{slug}/                 ❌       ❌          ✅           ✅

GET  /stores/                          ✅pub    ✅pub       ✅pub        ✅all
GET  /stores/my/{id}/                  ❌       ❌          ✅           ✅
GET  /stores/my/{id}/dashboard/        ❌       ❌          ✅           ✅

GET  /orders/                          ❌       ✅own       ✅store      ✅all
PATCH /orders/{id}/                    ❌       ❌          ✅store      ✅

GET  /transactions/                    ❌       ❌          ✅store      ✅all

GET  /reviews/                         ✅pub    ✅pub       ✅+unp       ✅all
POST /reviews/                         ❌       ✅bought    ❌           ✅
PATCH /reviews/{id}/ (reply only)      ❌       ❌          ✅own store  ✅
DELETE /reviews/{id}/                  ❌       ❌          ❌           ✅

GET  /reviews/messages/                ❌       ✅own       ✅own        ✅
GET  /reviews/notifications/           ❌       ✅own       ✅own        ✅
```
`pub` = public serializer (sensitive fields stripped). `+unp` = includes unpublished reviews (for moderation).

---

## 8. Serializer Strategy — The Core Pattern

**This is the most important section.** Every field in every serializer is a deliberate decision. The rule is: **serve the minimum data required for the consumer's legitimate use case.**

### How Serializers Are Chosen

```python
def get_serializer_class(self):
    role = getattr(self.request.user, 'role', None)
    if self.action == 'list':
        return ProductListSerializer        # lightest — card view only
    if self.action in ['create', 'update', 'partial_update']:
        return ProductCreateSerializer      # writable
    if role in ('admin', 'vendor'):
        return ProductSerializer            # full — includes cost_price, sku, etc.
    return ProductPublicSerializer          # anonymous / customer — internals stripped
```

### What Gets Stripped and Why

| Field | Stripped from | Reason |
|---|---|---|
| `cost_price` | `ProductPublicSerializer`, `ProductListSerializer` | Vendor's margin — a private business figure |
| `sku`, `barcode` | `ProductPublicSerializer` | Internal inventory codes |
| `track_inventory`, `low_stock_threshold` | `ProductPublicSerializer` | Internal ops data |
| `digital_file` | `ProductPublicSerializer` | Served via signed URL, not directly |
| `seo_title`, `seo_description` | `ProductPublicSerializer` | Rendered server-side by Next.js |
| `balance`, `pending_balance` | `PublicStoreSerializer` | Financial — owner only |
| `commission_rate` | `PublicStoreSerializer` | Internal business config |
| `payment_reference` | `OrderCustomerSerializer`, `OrderVendorSerializer` | Raw payment gateway token — admin only |
| `commission_amount` | `OrderCustomerSerializer` | Platform fee — internal |
| `billing_address` | `OrderCustomerSerializer` | Shown on invoice endpoint only |
| `metadata` | `TransactionSerializer`, `NotificationSerializer` | May contain payment processor internal IDs |
| `balance_before` | `TransactionSerializer` | Can be inferred; reduces payload |
| `flagged` | `ReviewPublicSerializer` | Leaks moderation state — customers could game it |
| `is_published` | `ReviewPublicSerializer` | Internal moderation flag |
| `is_auto` | `MessageSerializer` | Server-only flag for automated messages |
| `channels`, `sent_via` | `NotificationSerializer` | Delivery infrastructure internals |
| `auth_provider`, `is_banned` | `UserSerializer` | Internal admin fields |
| `totp_secret` | **All serializers** | Never. Not in any serializer, ever. |

### The `PublicUserSerializer` Rule

Any time a user is embedded in another resource's response (review author, message sender/receiver), use `PublicUserSerializer` — **never** `UserSerializer`. It exposes only `id`, `name`, `avatar`.

```python
# ✅ Correct
class ReviewPublicSerializer(serializers.ModelSerializer):
    author = PublicUserSerializer(source='customer', read_only=True)

# ❌ Wrong — leaks email to anyone reading a review
class ReviewPublicSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
```

---

## 9. Security Rules — Read Before You Code

These rules exist because real bugs were found and fixed. Violating them reintroduces known vulnerabilities.

### ✋ Never return `user_id` in unauthenticated responses
The 2FA challenge must return a `pending_token` (opaque Redis key), never the DB user ID. See Section 5.

### ✋ Always check `is_authenticated` before accessing `.role`
`AnonymousUser` has no `role` attribute — it will raise `AttributeError`.
```python
# ❌ Crashes for anonymous users
if self.request.user.role != 'admin': ...

# ✅ Safe
if not user.is_authenticated:
    return SomeModel.objects.none()
if getattr(user, 'role', None) != 'admin': ...
```

### ✋ Never use `StoreSerializer` on public endpoints
It exposes `balance`, `pending_balance`, `commission_rate`. Use `PublicStoreSerializer`.

### ✋ Never use `UserSerializer` when embedding a user in another object
Use `PublicUserSerializer` (name + avatar only). A review's author should never reveal their email.

### ✋ Never put `cost_price` in a public-facing serializer
It is the vendor's purchase cost — their margin. Only in `ProductSerializer` (vendor/admin access).

### ✋ `rest_framework_simplejwt.token_blacklist` must stay in `INSTALLED_APPS`
Without it, logout is broken. Do not remove it.

### ✋ Reviews require a verified purchase
`ReviewViewSet.perform_create` checks that an `OrderItem` exists. Never remove this.

### ✋ Vendor reply is the only field vendors can update on a review
The `update` method raises `403` for any field other than `vendor_reply`. `replied_at` is stamped server-side.

### ✋ Customers cannot modify orders
`PATCH`/`PUT` on `OrderViewSet` raises `403` for customers. Order mutations are vendor/admin only.

### ✋ Payouts require: vendor role + 2FA enabled + sufficient balance + minimum amount
All four checks are in `PayoutViewSet.perform_create`. Don't remove any.

### ✋ `SECRET_KEY` and DB credentials have no defaults
`settings.py` raises `UndefinedValueError` at startup if they're absent from `.env`. This is intentional.

### ✋ Never self-assign the `admin` role during registration
`UserRegistrationSerializer.validate_role` blocks it. If you add an admin creation flow, do it through `createsuperuser` or a dedicated admin-only endpoint.

### ✋ Never use GET for endpoints that write to the database

`GET` requests must be safe and idempotent (HTTP spec). Browsers, proxies, and Nginx may prefetch, cache, or retry them. Any `GET` that calls `.save()` can silently overwrite data on a retry.

`POST /auth/2fa/setup/` is a `POST` for exactly this reason — it writes `totp_secret` to the DB on every call. If it were a `GET`, a double-click or a prefetch could overwrite the secret while the user is scanning the QR code, silently breaking their 2FA. If you ever add a new setup-style endpoint, make it `POST`.

### ✋ Use atomic cache operations for counters under concurrent load

Never use `cache.get()` + `cache.set()` to implement a counter. Between those two calls, two simultaneous requests can both read the same value, both pass the limit check, and both set the same incremented value — effectively resetting the counter on every burst.

Always use `cache.add()` + `cache.incr()` instead:

```python
# ❌ Race condition — two parallel requests both read 0, both set 1
attempts = cache.get(a_key, 0)
if attempts >= MAX: ...
cache.set(a_key, attempts + 1, timeout=TTL)

# ✅ Atomic — Redis INCR is a single operation, no window between read and write
cache.add(a_key, 0, timeout=TTL)   # only sets if key doesn't exist
attempts = cache.incr(a_key)       # atomically increments, returns new value
if attempts > MAX: ...
```

The `Login2FAView` attempt counter uses this pattern. Don't change it back.

### ✋ Any endpoint that resets credentials must blacklist all existing tokens

If a user changes their password, all their outstanding refresh tokens must be invalidated immediately. Otherwise a stolen refresh token (from a log, a breach, a compromised device) remains valid for up to 7 days after the victim has already reset their password.

`ChangePasswordView` calls `_blacklist_all_tokens_for(user)` after saving. Apply the same pattern to any future endpoint that resets authentication credentials (email change, account recovery, etc.).

```python
def _blacklist_all_tokens_for(user):
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
```

---

## 10. Full Change Log

### Pass 1 — Bug Fixes (February 2026)

| # | Severity | File | Problem | Fix |
|---|---|---|---|---|
| 1 | 🔴 | `settings.py` | `token_blacklist` missing from `INSTALLED_APPS` — logout never blacklisted tokens | Added `rest_framework_simplejwt.token_blacklist` |
| 2 | 🔴 | `users/views.py` | `LoginView` returned `user_id` in 2FA challenge — user enumeration + brute-force target | Replaced with `pending_token` stored in Redis (5-min TTL) |
| 3 | 🔴 | `users/views.py` | `Login2FAView` had no attempt limiting — all 1M TOTP codes could be tried freely | Redis counter per `pending_token`, max 5 attempts |
| 4 | 🔴 | `stores/views.py` | `models.F(...)` used without `from django.db import models` — `NameError` on every dashboard request | Added the missing import |
| 5 | 🔴 | `products/views.py` | `self.request.user.role` called on `AnonymousUser` — `AttributeError` on public endpoints | Added `is_authenticated` guard before `.role` |
| 6 | 🟠 | `stores/serializers.py` | Public store list exposed `balance`, `pending_balance`, `commission_rate` | Created `PublicStoreSerializer` |
| 7 | 🟠 | `reviews/views.py` | `ReviewViewSet` returned `Review.objects.all()` — every authenticated user read every review | Scoped to authored reviews + own store reviews |
| 8 | 🟠 | `stores/views.py` | No one-store-per-vendor enforcement | Added check in `perform_create` |
| 9 | 🟡 | `products/serializers.py` | Slug generation loop duplicated across stores and products | Extracted into `unique_slug()` utility |
| 10 | 🟡 | `settings.py` | `SECRET_KEY` and DB credentials had insecure fallback defaults | Removed all defaults |

### Pass 2 — Serializer Security & Data Minimisation (February 2026)

| # | Severity | File | Problem | Fix |
|---|---|---|---|---|
| 11 | 🔴 | `users/serializers.py` | Registration accepted `role: "admin"` — self-promotion to admin | Added `validate_role` blocking `admin` |
| 12 | 🔴 | `products/serializers.py` | `cost_price` exposed on public product detail | Created `ProductPublicSerializer` without it |
| 13 | 🔴 | `orders/` | No serializers existed — all model fields exposed to all roles including `payment_reference`, `commission_amount` | Created role-scoped `Order*Serializer` hierarchy |
| 14 | 🔴 | `orders/views.py` | `OrderViewSet(ModelViewSet)` — customers could `PATCH` orders | Changed to explicit mixins; customer writes raise `403` |
| 15 | 🔴 | `transactions/` | No serializers — `metadata` JSONField (internal payment data) fully exposed | Created `TransactionSerializer` (strips `metadata`, `balance_before`) |
| 16 | 🟠 | `reviews/` | No serializers — `flagged`, `is_published`, `is_auto`, `metadata`, `channels` all exposed | Created full serializer hierarchy per role |
| 17 | 🟠 | `reviews/views.py` | No purchase verification on review create — anyone could review anything | Added `OrderItem` existence check in `perform_create` |
| 18 | 🟠 | `reviews/views.py` | Vendor `update` had no field restriction — could modify rating, body, etc. | Vendor update now only allows `vendor_reply`; others raise `403` |
| 19 | 🟠 | `products/serializers.py` | `sku`, `barcode`, `track_inventory`, `low_stock_threshold`, `seo_*`, `digital_file` exposed publicly | Stripped from `ProductPublicSerializer` |
| 20 | 🟠 | `products/serializers.py` | `ProductVariantSerializer` exposed `sku` and `weight` publicly | Created `ProductVariantPublicSerializer` |
| 21 | 🟠 | `orders/serializers.py` | `billing_address` returned on every order response to customers | Excluded from `OrderCustomerSerializer` (invoice endpoint only) |
| 22 | 🟠 | `orders/views.py` | `PayoutViewSet` had no validation — no 2FA check, no balance check, any role | Added: vendor-only, 2FA required, min amount, sufficient balance |
| 23 | 🟡 | `users/serializers.py` | `UserSerializer` included `auth_provider`, `is_banned`, `last_login_at` | Removed — frontend doesn't need them |
| 24 | 🟡 | `reviews/serializers.py` | Review author shown as full user — would expose email publicly | Replaced with `PublicUserSerializer` |
| 25 | 🟡 | `orders/serializers.py` | Coupon `validate` leaked `used_count`, `max_uses` to client | Created `CouponPublicSerializer` for validation response |
| 26 | 🟡 | `orders/views.py` | Coupon `validate` did not check `starts_at` — future coupons accepted | Added `starts_at > now` guard |
| 27 | 🟡 | `orders/views.py` | Fixed discount could make `new_total` negative | `discount_amount` capped at `cart_total` |
| 28 | 🟡 | `reviews/serializers.py` | `channels`, `sent_via`, `metadata` on notifications exposed | Excluded from `NotificationSerializer` |
| 29 | 🟡 | `reviews/serializers.py` | `is_auto` on messages exposed | Excluded from `MessageSerializer` |
| 30 | 🟡 | `products/serializers.py` | No price validation on create/update | Added `validate_price` (> 0) and `compare_price > price` cross-validation |

### Pass 3 — 2FA Deep Audit (February 2026)

| # | Severity | File | Problem | Fix |
|---|---|---|---|---|
| 31 | 🔴 | `users/views.py` | `Login2FAView` attempt counter used `cache.get()` + `cache.set()` — race condition allowed unlimited parallel attempts to bypass the 5-attempt limit | Replaced with atomic `cache.add()` + `cache.incr()` |
| 32 | 🟠 | `users/views.py` | `TOTPSetupView` was a `GET` that wrote `totp_secret` to the DB — browser prefetch / proxy retry could silently overwrite a secret mid-scan | Changed to `POST`; `urls.py` updated accordingly |
| 33 | 🟠 | `users/views.py` | `ChangePasswordView` did not invalidate existing sessions — a stolen refresh token remained valid for 7 days after a password reset | Added `_blacklist_all_tokens_for(user)` to blacklist all outstanding tokens on password change |
| 34 | 🟡 | `users/views.py` | `TOTPDisableView` ran payout + state checks before serializer validation — error messages revealed account state to malformed requests | Moved `serializer.is_valid()` to run first, before any business logic |

---

## 11. Known Gaps & What's Next

| Feature | Status | Notes |
|---|---|---|
| Email verification on register | ❌ Not done | URL in spec, no email sent, no token generated |
| Forgot / reset password | ❌ Not done | URL not defined yet |
| Social auth (Google, Facebook) | ❌ Not done | `auth_provider` field exists, no OAuth flow |
| Per-endpoint rate limiting | ⚠️ Partial | Global throttle added (60/min anon, 300/min auth); AI (20/min) and vendor writes (30/min) need `django-ratelimit` |
| `totp_secret` encryption at rest | ❌ Not done | Spec requires AES-256; currently plaintext — use `django-encrypted-model-fields` |
| Stripe / Moneroo webhook handlers | ❌ Not done | Keys configured, views missing |
| Checkout / Order creation | ❌ Not done | Needs atomic endpoint: payment intent + inventory reserve + order create |
| Actual payout execution | ⚠️ Stub | Records created; no bank/mobile-money transfer logic |
| Tests | ❌ None | Highest priority before any production deployment |
| Redis cache backend config | ⚠️ Assumed | `CACHES` must point to Redis in `settings.py` |

### Recommended Next Steps

1. Configure `CACHES` in `settings.py` with Redis — 2FA depends on it
2. Implement email verification (`django.core.signing.TimestampSigner`)
3. Encrypt `totp_secret` at rest (`django-encrypted-model-fields`)
4. Write auth flow tests (`RegisterView`, `LoginView`, `Login2FAView`, `LogoutView`)
5. Build the checkout endpoint (atomic: payment intent → inventory reserve → `Order` create)
6. Connect Stripe/Moneroo webhooks to update `Order.payment_status`

---

## 12. Environment Variables Reference

All variables are required unless marked optional. The app will not start if required ones are missing.

```bash
# Django — REQUIRED
SECRET_KEY=your-long-random-secret-key-min-50-chars
DEBUG=False                         # Always False in production
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# MySQL — REQUIRED
DB_NAME=pixelmart
DB_USER=pixelmart_user
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=3306

# CORS — REQUIRED
CORS_ALLOWED_ORIGINS=https://yourdomain.com

# Stripe — optional during dev, required for payments
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Moneroo — optional during dev, required for African payments
MONEROO_SECRET_KEY=xxx
MONEROO_WEBHOOK_SECRET=xxx
```

> ⚠️ Never commit `.env` to git. Share secrets via a password manager or secrets vault — never Slack or email.

---

## 13. Appendix — Data Flow Diagrams

### Registration

```
Client  →  POST /auth/register/
           body: { email, name, password, password_confirm, role }
           → validate_role() — blocks role='admin'
           → password match + strength validation
           → User.objects.create_user()
           → RefreshToken.for_user()
        ←  { user: UserSerializer, access, refresh }  [201]
```

### Login with 2FA

```
Client  →  POST /auth/login/
           body: { email, password }
           → constant-time check (same error for wrong email or wrong password)
           → check is_banned → 403
           → if 2FA enabled:
               pending_token = secrets.token_urlsafe(32)
               cache.set(f'2fa_pending:{pending_token}', user.pk, timeout=300)
           ←  { requires_2fa: true, pending_token }

Client  →  POST /auth/login/2fa/
           body: { pending_token, code }
           → cache.get(f'2fa_pending:{pending_token}') → user.pk
           → attempt counter check (max 5 → delete token → 429)
           → pyotp.TOTP.verify(code, valid_window=1)
           → cache.delete(pending_token)
           ←  { user: UserSerializer, access, refresh }
```

### Product Detail — Role-Aware Serialization

```
GET /products/{slug}/

→ ProductViewSet.get_serializer_class()
    user is admin or vendor (own product)?  → ProductSerializer
        returns: cost_price, sku, barcode, track_inventory,
                 low_stock_threshold, seo_*, digital_file, variants (full)
    else (anonymous / customer)?            → ProductPublicSerializer
        returns: price, compare_price, description, images,
                 variants (price/availability only) — internals excluded
```

### Order Access — Role-Aware Queryset + Serializer

```
GET /orders/

Customer  → filter(customer=user)      → OrderCustomerSerializer
              excludes: payment_reference, commission_amount, billing_address

Vendor    → filter(store__owner=user)  → OrderVendorSerializer
              includes: customer_name, customer_email, commission_amount
              excludes: payment_reference, billing_address

Admin     → all orders                 → OrderAdminSerializer (fields = '__all__')
```

### Review Creation — Purchase Verification

```
POST /reviews/
body: { product, order, rating, title, body, images }

→ ReviewViewSet.perform_create()
    role check: must be 'customer' → else 403
    → OrderItem.objects.filter(
          order__customer=user,
          order_id=body.order,
          product_id=body.product
      ).exists()  → if False: 422
    → serializer.save(
          customer=user,
          product=product,
          order=order,
          store=product.store   ← always server-side, never from client
      )
←  ReviewPublicSerializer  [201]
```

### Vendor Reply to Review

```
PATCH /reviews/{id}/
body: { vendor_reply: "Thank you for your feedback!" }

→ ReviewViewSet.update()
    role == 'vendor'?
        review.store.owner == request.user? → else 403
        disallowed_fields = set(body.keys()) - {'vendor_reply'}
        if disallowed_fields: raise 403
        review.vendor_reply = body.vendor_reply
        review.replied_at = timezone.now()   ← server-stamped
        review.save(update_fields=['vendor_reply', 'replied_at'])
←  ReviewVendorSerializer
```

---

*Update this document whenever a significant architectural decision is made, a new app is added, or a security rule changes. It is the contract between the current team and whoever comes next.*