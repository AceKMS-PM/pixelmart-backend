# PixelMart — Backend Developer Guide

> **Stack:** Django 4.2+ · Django REST Framework · MySQL · JWT (SimpleJWT) · Stripe · Moneroo  
> **Last updated:** February 2026  
> **Author:** Initial architecture by Franck ZINSOU (CTO) — security pass & bug fixes applied February 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Getting Started](#2-getting-started)
3. [Project Structure](#3-project-structure)
4. [Apps & Responsibilities](#4-apps--responsibilities)
5. [Authentication & Security Model](#5-authentication--security-model)
6. [API Conventions](#6-api-conventions)
7. [Permissions Architecture](#7-permissions-architecture)
8. [Key Design Patterns](#8-key-design-patterns)
9. [Security Rules — Read Before You Code](#9-security-rules--read-before-you-code)
10. [Bug Fixes Applied (Feb 2026)](#10-bug-fixes-applied-feb-2026)
11. [Known Gaps & What's Next](#11-known-gaps--whats-next)
12. [Environment Variables Reference](#12-environment-variables-reference)

---

## 1. Project Overview

PixelMart is an **AI-powered African marketplace** where vendors open digital stores and sell products to customers. The backend is a Django REST Framework API that serves a Next.js frontend.

### User Roles

| Role | Description |
|---|---|
| `customer` | Browses and buys products |
| `vendor` | Owns one store, lists products, receives payouts |
| `admin` | Full platform access, can ban users / verify stores |

### Business Rules to Know

- **One store per vendor.** Enforced server-side in `StoreViewSet.perform_create`.
- **Vendors must have 2FA enabled before requesting a payout.** Enforced in `PayoutViewSet`.
- **Commission rates** vary by subscription tier: Free = 5%, Pro = 3%, Business = 2% (stored in `settings.COMMISSION_RATES`).
- **Balances are stored in centimes** (integer). €1 = 100.

---

## 2. Getting Started

### Prerequisites

- Python 3.11+
- MySQL 8+
- Redis (for cache — used by 2FA pending tokens and future rate limiting)

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
# → edit .env with your values (see Section 12)

# 4. Run migrations
python manage.py migrate

# 5. Create a superuser
python manage.py createsuperuser

# 6. Run the dev server
python manage.py runserver
```

### API Docs

Once the server is running, interactive docs are available at:

- **Swagger UI** → `http://localhost:8000/api/docs/`
- **ReDoc** → `http://localhost:8000/api/redoc/`

---

## 3. Project Structure

```
pixelmart-backend/
├── config/
│   ├── settings.py         # All Django settings (reads from .env)
│   ├── urls.py             # Root URL routing
│   ├── wsgi.py
│   └── asgi.py
├── common/
│   ├── models.py           # TimeStampedModel base class
│   └── pagination/         # StandardPagination (20/page, max 100)
├── users/                  # Auth, registration, 2FA, profile
├── stores/                 # Vendor stores, dashboard, balances
├── products/               # Catalog, variants, categories
├── orders/                 # Orders, coupons, payouts
├── transactions/           # Financial ledger (read-only)
├── reviews/                # Product reviews, messages, notifications
├── requirements.txt
├── .env.example
└── DEVELOPER_GUIDE.md      # ← You are here
```

---

## 4. Apps & Responsibilities

### `common`
Base abstractions shared across the project.

- **`TimeStampedModel`** — abstract model with `created_at` / `updated_at`. **All models inherit from this.**
- **`StandardPagination`** — `page` + `limit` query params, max 100 per page.

### `users`
Everything about identity and authentication.

| File | Purpose |
|---|---|
| `models.py` | Custom `User` model (email login, no username, roles, 2FA flags) |
| `serializers.py` | Registration, profile, password change, TOTP validation |
| `views.py` | Register, Login, 2FA login, Logout, Profile, TOTP setup/verify/disable |
| `urls.py` | All `/api/v1/auth/` routes |

### `stores`
Vendor-facing store management + public store discovery.

| File | Purpose |
|---|---|
| `models.py` | `Store` model — status, subscription tier, balance, level, ratings |
| `serializers.py` | `StoreSerializer` (owner), `PublicStoreSerializer` (no financial data), Create/Update |
| `views.py` | `StoreViewSet` (owner only) + `PublicStoreViewSet` (anonymous read) |
| `urls.py` | `/my/` prefix for owner routes, `/` for public |

### `products`
Product catalog.

| File | Purpose |
|---|---|
| `models.py` | `Category`, `Product`, `ProductVariant` |
| `serializers.py` | List (light), Detail, Create/Update with nested variants. Shared `unique_slug()` utility |
| `views.py` | Category CRUD (admin-only writes), Product CRUD, Variant CRUD |

### `orders`
Purchase flow and financial disbursement.

| File | Purpose |
|---|---|
| `models.py` | `Order`, `OrderItem`, `Coupon`, `Payout` |
| `views.py` | `OrderViewSet` (role-scoped), `CouponViewSet`, coupon `validate` action, `PayoutViewSet` |

### `transactions`
**Read-only** financial log. Vendors can only view their own store's transactions.

### `reviews`
- `ReviewViewSet` — users see reviews they wrote or reviews on their store's products.
- `MessageViewSet` — inbox/outbox scoped to the current user.
- `NotificationViewSet` — read-only, user-scoped.

---

## 5. Authentication & Security Model

### JWT Flow

```
POST /api/v1/auth/register/  →  { user, access, refresh }
POST /api/v1/auth/login/     →  { user, access, refresh }  OR  { requires_2fa, pending_token }
POST /api/v1/auth/login/2fa/ →  { user, access, refresh }
POST /api/v1/auth/logout/    →  blacklists the refresh token
POST /api/v1/auth/refresh/   →  { access, refresh }  (rotates both)
```

All protected endpoints require the header:
```
Authorization: Bearer <access_token>
```

**Token lifetimes:**
- Access token: **60 minutes**
- Refresh token: **7 days** (rotated on each use, old token blacklisted)

### 2FA Login Flow

The 2FA flow was redesigned to avoid leaking user IDs. Here's how it works:

```
1. POST /auth/login/   →  { requires_2fa: true, pending_token: "abc123..." }
                            ↑ opaque token stored in Redis with 5-min TTL

2. POST /auth/login/2fa/  { pending_token: "abc123...", code: "123456" }
                            ↑ max 5 attempts, then token invalidated

3. Success             →  { user, access, refresh }
```

> ⚠️ **Never return `user_id` in the 2FA challenge response.** That was the old broken behaviour. Use `pending_token` only.

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
| Date format | ISO 8601: `2026-02-19T23:32:00+01:00` |

**Standard HTTP status codes used:**

| Code | When |
|---|---|
| `200` | Successful GET / PATCH |
| `201` | Resource created |
| `204` | Deleted (no body) |
| `400` | Bad request / validation error |
| `401` | Not authenticated |
| `403` | Authenticated but not allowed |
| `404` | Resource not found |
| `422` | Business rule violation (e.g. coupon expired) |
| `429` | Rate limit exceeded |

---

## 7. Permissions Architecture

### Permission Classes

| Class | File | Rule |
|---|---|---|
| `IsStoreOwner` | `stores/views.py` | `obj.owner == request.user` |
| `IsProductOwner` | `products/views.py` | `obj.store.owner == request.user` (write only) |
| `IsAdminUser` | DRF built-in | `user.is_staff == True` |
| `IsAuthenticatedOrReadOnly` | DRF built-in | Anonymous users can read; writes need auth |

### Who Can Do What

```
GET    /api/v1/products/          → Anyone (active products only)
GET    /api/v1/products/{slug}/   → Anyone
POST   /api/v1/products/          → Authenticated vendor (owns the store)
PUT    /api/v1/products/{slug}/   → Owner of that product's store only
DELETE /api/v1/products/{slug}/   → Owner only

GET    /api/v1/stores/            → Anyone (active stores, public fields only)
GET    /api/v1/stores/my/         → Vendor sees their own store (+ financial data)
POST   /api/v1/stores/my/         → Vendor (max 1 store)
GET    /api/v1/stores/my/{id}/dashboard/ → Store owner only

GET    /api/v1/orders/            → Customer sees own orders / Vendor sees store orders / Admin sees all
GET    /api/v1/transactions/      → Vendor sees own store transactions only
```

---

## 8. Key Design Patterns

### Serializer Strategy (multiple serializers per viewset)

ViewSets use different serializers per action to control what data is exposed:

```python
def get_serializer_class(self):
    if self.action == 'list':
        return ProductListSerializer      # lighter, fewer fields
    if self.action in ['create', 'update', 'partial_update']:
        return ProductCreateSerializer    # writable
    return ProductSerializer              # full detail
```

### Public vs. Private Store Serializers

**This is important.** Never use `StoreSerializer` on public endpoints — it exposes financial data.

| Serializer | Used for | Exposes balance? |
|---|---|---|
| `PublicStoreSerializer` | `GET /api/v1/stores/` (anonymous) | ❌ No |
| `StoreSerializer` | `GET /api/v1/stores/my/` (owner) | ✅ Yes |

### Unique Slug Generation

Both stores and products need unique URL slugs. Use the shared utility in `products/serializers.py`:

```python
from products.serializers import unique_slug

slug = unique_slug(Product, product_title)
# → "my-product", "my-product-1", "my-product-2" etc.
```

Do **not** write the while-loop inline again. Use the utility.

### Partial Saves

When updating only a few fields, use `update_fields` to avoid unnecessary DB writes and reduce race-condition risk:

```python
user.is_2fa_enabled = True
user.save(update_fields=['is_2fa_enabled'])
```

---

## 9. Security Rules — Read Before You Code

These rules exist because of real bugs that were found and fixed. Please read them.

### ✋ Never expose `user_id` in unauthenticated responses

The 2FA challenge must return a `pending_token` (random opaque string stored in Redis), not the actual database `user_id`. Exposing the ID allows attackers to target specific accounts.

### ✋ Never use `StoreSerializer` on public endpoints

`StoreSerializer` includes `balance`, `pending_balance`, and `commission_rate`. These are financial fields visible only to the store owner. Use `PublicStoreSerializer` for anonymous-facing endpoints.

### ✋ Always check `request.user.is_authenticated` before accessing `.role`

`AnonymousUser` does not have a `role` attribute. This pattern **will crash**:

```python
# ❌ WRONG — crashes for anonymous users
if self.request.user.role != 'admin':
    ...
```

```python
# ✅ CORRECT
user = self.request.user
if not user.is_authenticated:
    return SomeModel.objects.none()
if getattr(user, 'role', None) != 'admin':
    ...
```

### ✋ `rest_framework_simplejwt.token_blacklist` must be in INSTALLED_APPS

Without this app, `BLACKLIST_AFTER_ROTATION = True` in JWT settings does **nothing**. Logout and token rotation will not work. It is now in settings — don't remove it.

### ✋ SECRET_KEY and DB credentials have no defaults

`settings.py` intentionally raises an error if `SECRET_KEY`, `DB_NAME`, `DB_USER`, or `DB_PASSWORD` are not set in `.env`. This prevents accidentally running production with placeholder values.

### ✋ Rate-limit 2FA attempts

The `Login2FAView` uses Redis cache to count attempts per `pending_token`. Max 5 attempts, then the token is invalidated and the user must log in again. If you refactor this view, preserve this behaviour.

### ✋ Reviews are not globally readable

`ReviewViewSet` must scope its queryset to reviews the current user wrote OR reviews on their store's products. The original code returned `Review.objects.all()` — every authenticated user could read every review on the platform.

---

## 10. Bug Fixes Applied (Feb 2026)

This section documents every bug that was found and fixed in the initial codebase, so you understand why the code is written the way it is.

---

### 🔴 FIX 1 — Token blacklist not working (settings.py)

**Problem:** `SIMPLE_JWT['BLACKLIST_AFTER_ROTATION'] = True` was set, but `rest_framework_simplejwt.token_blacklist` was missing from `INSTALLED_APPS`. Logout did not actually invalidate tokens.

**Fix:** Added `'rest_framework_simplejwt.token_blacklist'` to `INSTALLED_APPS`. Run `python manage.py migrate` after pulling this change.

```python
# settings.py — INSTALLED_APPS
'rest_framework_simplejwt.token_blacklist',  # ← added
```

---

### 🔴 FIX 2 — user_id leaked in 2FA challenge (users/views.py)

**Problem:** `LoginView` returned `{ "requires_2fa": true, "user_id": 42 }`. Any observer (network log, frontend bug, etc.) could see the internal DB ID of any user, enabling targeted brute-force on the 2FA endpoint.

**Fix:** `LoginView` now returns a `pending_token` (32-byte random string stored in Redis with 5-min TTL). `Login2FAView` resolves the user from this token.

---

### 🔴 FIX 3 — No brute-force protection on 2FA (users/views.py)

**Problem:** `Login2FAView` had no attempt limiting. An attacker with a `user_id` could try all 1,000,000 possible 6-digit TOTP codes.

**Fix:** Redis counter per `pending_token`. After 5 failed attempts, the `pending_token` is deleted from cache and the user must re-authenticate from scratch.

---

### 🔴 FIX 4 — `models.F` NameError in dashboard (stores/views.py)

**Problem:** `stores/views.py` used `models.F('low_stock_threshold')` but never imported `from django.db import models`. This caused a `NameError` on every dashboard request.

**Fix:** Added the import. The line now works correctly.

```python
from django.db import models  # was missing
```

---

### 🔴 FIX 5 — AnonymousUser crash in ProductViewSet (products/views.py)

**Problem:** `get_queryset()` called `self.request.user.role` unconditionally. `AnonymousUser` has no `role` attribute, so any public `GET /products/` request that hit the non-list branch would raise `AttributeError`.

**Fix:** Added `is_authenticated` check before accessing `.role`. Unauthenticated users hitting write-intended branches now get an empty queryset.

---

### 🟠 FIX 6 — Financial data exposed on public store endpoint (stores/serializers.py)

**Problem:** The public store list (`GET /stores/`) used `StoreSerializer`, which includes `balance`, `pending_balance`, and `commission_rate`. Any anonymous user could see all vendors' financial information.

**Fix:** Created `PublicStoreSerializer` with only public fields. `StoreViewSet` (owner) still uses `StoreSerializer`. `PublicStoreViewSet` uses `PublicStoreSerializer`.

---

### 🟠 FIX 7 — All reviews readable by all users (reviews/views.py)

**Problem:** `ReviewViewSet.get_queryset()` returned `Review.objects.all()`. Any authenticated user could read every review on the platform.

**Fix:** Scoped the queryset to reviews the user authored or reviews on their own store's products.

---

### 🟠 FIX 8 — No one-store-per-vendor enforcement (stores/views.py)

**Problem:** The business rule "one store per vendor" existed in the spec but was never enforced in code. A vendor could create unlimited stores.

**Fix:** Added check in `StoreViewSet.perform_create`:

```python
if Store.objects.filter(owner=self.request.user).exists():
    raise PermissionDenied('You already own a store.')
```

---

### 🟡 FIX 9 — Duplicate slug generation logic (products/serializers.py)

**Problem:** The while-loop for generating unique slugs was copy-pasted in `StoreCreateSerializer` and `ProductCreateSerializer`. Any bug fix would need to be applied twice.

**Fix:** Extracted into `unique_slug(model_class, text)` utility at the top of `products/serializers.py`. Both serializers now call this function.

---

### 🟡 FIX 10 — Insecure defaults in settings (config/settings.py)

**Problem:** `SECRET_KEY` had `default='django-insecure-change-me-in-production'` and DB credentials had empty defaults. A misconfigured deployment could silently use these values.

**Fix:** Removed all defaults from critical secrets. `python-decouple` will raise `UndefinedValueError` at startup if they're missing, making misconfiguration impossible to miss.

---

## 11. Known Gaps & What's Next

These features are in the spec but not yet implemented. Pick these up in the next sprint.

| Feature | Status | Notes |
|---|---|---|
| Email verification on register | ❌ Not done | Endpoint exists in URL list but no email is sent |
| Forgot / reset password | ❌ Not done | URL not even defined yet |
| Social auth (Google, Facebook) | ❌ Not done | `auth_provider` field exists on User model |
| Rate limiting per endpoint | ⚠️ Partial | Global DRF throttling added; per-endpoint (AI = 20/min) still needed |
| `TOTP secret` encryption at rest | ❌ Not done | Spec says AES-256, currently stored plaintext in DB |
| Stripe / Moneroo webhook handlers | ❌ Not done | Keys are configured, views are missing |
| Order creation flow | ⚠️ Stub | `OrderViewSet` reads orders; create logic (inventory deduction, payment intent) missing |
| Payout logic | ⚠️ Stub | `PayoutViewSet` exists; actual transfer logic missing |
| Tests | ❌ None | No test suite exists yet — priority for Phase 1 handoff |
| Redis cache backend | ⚠️ Assumed | Cache is used for 2FA tokens; ensure `CACHES` is configured in settings for production |

### Immediate Next Steps (Recommended Order)

1. Configure Redis cache in `settings.py` — the 2FA flow depends on it
2. Add `python manage.py migrate` to CI (token_blacklist tables must exist)
3. Implement email verification (use `django.core.mail` + signed tokens)
4. Encrypt `totp_secret` at rest (use `django-encrypted-model-fields` or a custom field)
5. Write tests for auth flows (`RegisterView`, `LoginView`, `Login2FAView`)

---

## 12. Environment Variables Reference

Copy `.env.example` to `.env` and fill in all values. The app **will not start** if required variables are missing.

```bash
# Django — REQUIRED
SECRET_KEY=your-long-random-secret-key-here
DEBUG=True                          # Set False in production
ALLOWED_HOSTS=localhost,127.0.0.1

# MySQL — REQUIRED
DB_NAME=pixelmart
DB_USER=root
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=3306

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Stripe (leave empty to disable payment features during dev)
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Moneroo (African payments)
MONEROO_SECRET_KEY=xxx
MONEROO_WEBHOOK_SECRET=xxx
```

> ⚠️ Never commit `.env` to git. It is in `.gitignore`. If you need to share config with a teammate, use a password manager or a secrets vault.

---

## Appendix — Data Flow Diagrams

### Registration

```
Client  →  POST /auth/register/  →  UserRegistrationSerializer.validate()
                                 →  User.objects.create_user()
                                 →  RefreshToken.for_user()
                                 ←  { user, access, refresh }
```

### Login with 2FA

```
Client  →  POST /auth/login/      →  check password + is_banned
                                  →  if 2FA: store pending_token in Redis (5min TTL)
                                  ←  { requires_2fa: true, pending_token }

Client  →  POST /auth/login/2fa/  →  resolve user from pending_token (cache)
                                  →  check attempt count (max 5)
                                  →  pyotp.TOTP.verify(code)
                                  →  delete pending_token from cache
                                  ←  { user, access, refresh }
```

### Product Creation

```
Client  →  POST /products/  →  IsAuthenticatedOrReadOnly (pass)
                            →  IsProductOwner (write = owner check, pass for create)
                            →  ProductViewSet.perform_create()
                               →  Store.objects.get(slug=store_slug, owner=request.user)
                               →  ProductCreateSerializer.create()
                                  →  unique_slug(Product, title)
                                  →  Product.objects.create()
                                  →  ProductVariant.objects.create() × N
                            ←  ProductSerializer(product).data  [201]
```

---

*This document should be updated whenever a significant architectural decision is made or a new app is added. Keep it close to the code.*