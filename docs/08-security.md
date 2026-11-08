# ۰۸ — امنیت و کنترل دسترسی

## ۱. اصول طراحی

1. **منبع حقیقت، Django است.** هیچ تصمیم دسترسی در فرانت‌اند یا سرویس AI گرفته نمی‌شود.
2. **Fail closed.** کاربر بدون Tenant یا با Tenant غیرفعال رد می‌شود؛ نبود دپارتمان یعنی نتیجه خالی، نه دسترسی کامل.
3. **دفاع لایه‌ای.** فیلتر Tenant در کوئری، احراز هویت، View و بازبینی نتایج تکرار می‌شود.
4. **کمترین افشا.** فایل‌های آپلودی از طریق Nginx عمومی نمی‌شوند (`location /` → 404).

## ۲. احراز هویت

### JWT

- کتابخانه: `djangorestframework-simplejwt`
- کلاس پیش‌فرض: `accounts.authentication.TenantJWTAuthentication`
- هدر: `Authorization: Bearer <access>`

```python
class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, validated_token = result
        tenant = getattr(user, "tenant", None)
        if tenant is None:
            raise AuthenticationFailed("Your account is not assigned to an organization.")
        if not tenant.is_active:
            raise AuthenticationFailed("Your organization is inactive.")
        request.tenant = tenant
        return user, validated_token
```

پیامدها:

- توکن معتبر برای کاربر بدون Tenant → `401`، نه `403`.
- غیرفعال شدن Tenant، بلافاصله همه درخواست‌های بعدی را می‌بندد (توکن هنوز از نظر امضأ معتبر است).
- `request.tenant` در لایه احراز هویت ست می‌شود.

### Session

`TenantMiddleware` برای درخواست‌های احراز هویت‌شده با Session (مثلاً Django Admin) مقدار `request.tenant` را ست می‌کند. برای APIهای JWT، این کار توسط `TenantJWTAuthentication` انجام می‌شود.

### طول عمر توکن

در `settings.py` هیچ بلوک `SIMPLE_JWT` وجود ندارد؛ بنابراین پیش‌فرض‌های کتابخانه اعمال می‌شود:

| توکن | عمر پیش‌فرض |
|---|---|
| Access | ۵ دقیقه |
| Refresh | ۱ روز |

اپ `token_blacklist` نصب شده، اما چرخش (rotation) و blacklist پس از refresh فعال نیست. یعنی refresh token تا انقضا قابل استفاده مجدد است.

## ۳. مجوزها

### نقش‌ها

| نقش | تشخیص | دسترسی |
|---|---|---|
| `Admin` | `user.role == "Admin"` | تحلیل، Audit، آپلود به هر دپارتمان Tenant، مشاهده همه اسناد Tenant، تولید Embedding |
| `Member` | پیش‌فرض | آپلود به دپارتمان خود، مشاهده اسناد دپارتمان خود، جست‌وجو و چت |

`IsAdminUser` و `IsDepartmentMember` در `api/permissions.py` تعریف شده‌اند.

### ماتریس دسترسی endpointها

| Endpoint | ناشناس | Member | Admin |
|---|---|---|---|
| `POST /auth/login/` | ✅ | ✅ | ✅ |
| `POST /auth/refresh/` | ✅ | ✅ | ✅ |
| `GET /auth/me/` | ❌ | ✅ | ✅ |
| `GET /departments/` | ❌ | ✅ | ✅ |
| `POST /departments/create/` | ❌ | ❌ | ✅ |
| `GET /documents/` | ❌ | ✅ (کل Tenant) | ✅ |
| `POST /documents/` | ❌ | ✅ (دپارتمان خود) | ✅ (هر دپارتمان Tenant) |
| `GET /documents/{id}/` | ❌ | ✅ (دپارتمان خود) | ✅ |
| `DELETE /documents/{id}/delete/` | ❌ | ✅ (فقط آپلود خود) | ✅ |
| `POST /search/` | ❌ | ✅ | ✅ |
| `POST /query/search/` | ❌ | ✅ | ✅ |
| `POST /query/ask/` | ❌ | ✅ | ✅ |
| `POST /chat/ask/` | ❌ | ✅ | ✅ |
| `POST /embeddings/create/` | ❌ | ❌ | ✅ |
| `GET /audit-logs/` | ❌ | ❌ | ✅ |
| `GET /admin/analytics/` | ❌ | ❌ | ✅ |
| `GET /api/docs/` و `/api/schema/` | ✅ | ✅ | ✅ |
| `GET /metrics/` | ✅ | ✅ | ✅ |

> `api/docs`، `api/schema` و `metrics` در تنظیمات فعلی محدود نشده‌اند. در Production باید پشت شبکه داخلی یا احراز هویت قرار بگیرند.

## ۴. جداسازی چند-مستأجری

### لایه ۱ — مدل داده

`Tenant` روی `User`، `Department`، `Document`، `SearchQuery` و `AuditLog` وجود دارد. `Document.department` هم به دپارتمان همان Tenant اشاره می‌کند (این هم‌خوانی در View آپلود بررسی می‌شود).

### لایه ۲ — احراز هویت

کاربر بدون Tenant یا با Tenant غیرفعال اجازه ورود به هیچ APIای را ندارد.

### لایه ۳ — کوئری‌ها

نمونه‌ها:

```python
Document.objects.filter(tenant_id=user.tenant_id)
DocumentChunk.objects.filter(
    id__in=chunk_ids,
    document__tenant_id=tenant_id,
    document__department__tenant_id=tenant_id,
)
AuditLog.objects.filter(
    tenant_id=tenant_id,
    user__tenant_id=tenant_id,
)
```

توجه: فیلتر `document__department__tenant_id` عمداً اضافه شده تا حتی اگر داده ناسازگار شد، Chunk از Tenant دیگر برنگردد.

### لایه ۴ — سرویس AI

`/api/vector-search/` با `tenant_id` و `allowed_department_ids` کار می‌کند و فیلتر را در SQL اعمال می‌کند.

### لایه ۵ — بازبینی نتایج

`_filter_tenant_search_results` پس از بازیابی، مالکیت هر Chunk را در دیتابیس بررسی می‌کند. `build_citations` هم همین کار را برای منابع پاسخ انجام می‌دهد.

## ۵. دسترسی به سند

| عملیات | قاعده |
|---|---|
| آپلود | `department.tenant_id == user.tenant_id` و (`user.department_id == department.id` یا Admin) |
| مشاهده وضعیت | Admin یا `document.department_id == user.department_id` |
| حذف | `document.uploaded_by_id == user.id` یا Admin |
| بازیابی در جست‌وجو | Chunk در دپارتمان کاربر؛ فیلتر نهایی View اسناد `is_public` را هم مجاز می‌داند |
| Citation | همان قواعد بازیابی، دوباره در دیتابیس |

### نکته‌های ظریف

- **لیست اسناد** (`GET /api/documents/`) همه اسناد Tenant را برمی‌گرداند، نه فقط دپارتمان کاربر. یعنی یک Member می‌تواند عنوان و وضعیت اسناد دپارتمان‌های دیگر را ببیند. این یک شکاف حریم خصوصی است.
- **اسناد public**: `is_public=True` در فیلتر نهایی مجاز است، اما `semantic_search` و `keyword_search` فقط دپارتمان کاربر را می‌گردند. نتیجه: اسناد public دپارتمان دیگر عملاً در جست‌وجو پیدا نمی‌شوند. این ناسازگاری باید یک‌طرف شود.
- **Admin بدون دپارتمان** نمی‌تواند جست‌وجو کند، چون `get_user_department_id` مقدار `None` برمی‌گرداند.

## ۶. محدودیت نرخ

| لایه | محدودیت | پیاده‌سازی |
|---|---|---|
| چت | ۵۰/ساعت Member، ۲۰۰/ساعت Admin | `ChatUserRateThrottle` + `RateLimitConfig` + Redis |
| آپلود | ۱۰/ساعت هر کاربر | `django-ratelimit` روی `create` |
| API عمومی | ۱۰ r/s هر IP | Nginx |
| آپلود در Nginx | ۲ POST/دقیقه هر IP | Nginx `map` روی متد |
| بدنه درخواست | ۶ مگابایت | Nginx `client_max_body_size` |

`RateLimitConfig` یک رکورد سراسری است، نه per-tenant. تغییر آن روی همه سازمان‌ها اثر می‌گذارد.

## ۷. Audit

رویدادهای ثبت‌شده:

| اقدام | محل |
|---|---|
| `UPLOAD` | پس از آپلود موفق |
| `DELETE` | پس از حذف سند |
| `SEARCH` | پس از `POST /api/query/search/` |
| `RAG_QUERY` | پس از `POST /api/query/ask/` |

ثبت‌شده: Tenant، کاربر، نوع اقدام، زمان.
ثبت‌نشده: IP، User-Agent، شناسه سند، متن پرسش، نتیجه.

مشاهده فقط برای Admin و فقط در محدوده Tenant خودش.

## ۸. مدیریت Secret

- همه Secretها از `.env` خوانده می‌شوند (`python-dotenv`).
- `.env` در `.dockerignore` و `.gitignore` است.
- `DJANGO_SECRET_KEY` پیش‌فرض ندارد؛ اگر ست نشود، Django بالا نمی‌آید (رفتار fail-fast مطلوب).
- `SENTRY_DSN` و `SENTRY_FASTAPI_DSN` اختیاری‌اند؛ `send_default_pii=False`.

توصیه‌ها:

```bash
chmod 600 .env
```

- از Secret Manager یا متغیرهای محیطی Orchestrator در Production استفاده کنید.
- کلیدها را در لاگ چاپ نکنید.
- برای هر محیط کلید جدا بسازید.

## ۹. شبکه و استقرار

| سرویس | پورت میزبان | وضعیت مطلوب |
|---|---|---|
| Nginx | 80/443 | عمومی |
| Django | 8000 (و 18001 در Compose) | فقط Loopback پشت Nginx |
| AI Service | منتشر نشده | داخلی |
| PostgreSQL | منتشر نشده | داخلی |
| Redis | منتشر نشده | داخلی |
| Next.js | 3000 (توسعه) | جدا یا پشت Nginx |

در `docker-compose.yml` فعلی، Django با `8000:8000` روی همه رابط‌ها منتشر می‌شود و یک نگاشت اضافی `18001:8000` هم دارد. برای Production:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

## ۱۰. شکاف‌های امنیتی شناخته‌شده

| # | موضوع | ریسک | پیشنهاد |
|---|---|---|---|
| ۱ | توکن در `localStorage` | سرقت توکن با XSS | کوکی `HttpOnly` + `SameSite` + CSRF |
| ۲ | بدون rotation/blacklist | استفاده مجدد refresh token | فعال‌سازی `ROTATE_REFRESH_TOKENS` و `BLACKLIST_AFTER_ROTATION` |
| ۳ | لیست اسناد در سطح Tenant | افشای فراداده بین دپارتمان‌ها | محدود کردن به دپارتمان یا فیلتر `is_public` |
| ۴ | ناسازگاری اسناد public | رفتار غیرقابل پیش‌بینی دسترسی | یکسان‌سازی فیلتر بازیابی و View |
| ۵ | سرویس AI بدون احراز هویت | دسترسی مستقیم به داده در صورت نشت شبکه | شبکه داخلی + mTLS یا API key داخلی |
| ۶ | `/api/docs/` و `/metrics/` عمومی | افشای ساختار و آمار | محدودسازی به شبکه داخلی |
| ۷ | بدون HTTPS در Nginx | شنود توکن | TLS + HSTS + redirect |
| ۸ | `DEBUG` پیش‌فرض True | افشای جزئیات خطا | صریحاً `False` در Production |
| ۹ | نام فایل یکتا نیست | بازنویسی فایل سند دیگر | UUID در نام فایل |
| ۱۰ | بدون اسکن بدافزار | آپلود فایل مخرب | ClamAV یا سرویس اسکن |
| ۱۱ | بدون MFA و سیاست رمز سازمانی | ضعف حساب ادمین | MFA و SSO |
| ۱۲ | لاگ بدون IP و جزئیات | ضعف در بررسی حادثه | افزودن متادیتا |

## ۱۱. چک‌لیست Production

- [ ] `DJANGO_DEBUG=False` و `DJANGO_SECRET_KEY` یکتا و تصادفی
- [ ] `DJANGO_ALLOWED_HOSTS` و `CORS_ALLOWED_ORIGINS` دقیقاً دامنه واقعی
- [ ] HTTPS فعال، HSTS و redirect از HTTP
- [ ] پورت Django فقط روی Loopback
- [ ] PostgreSQL، Redis و AI Service از اینترنت در دسترس نیستند
- [ ] `/metrics/` و `/api/docs/` محدود شده‌اند
- [ ] سیاست پشتیبان‌گیری و بازیابی آزمایش شده
- [ ] توکن‌ها در کوکی امن یا حداقل CSP سخت‌گیرانه
- [ ] نقش‌ها و دسترسی دپارتمان‌ها با داده واقعی تست شده
- [ ] لاگ‌ها و هشدارهای Sentry/Prometheus فعال
- [ ] محدودیت نرخ در Nginx و DRF با بار واقعی تنظیم شده
