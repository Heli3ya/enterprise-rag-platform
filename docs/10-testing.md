# ۱۰ — تست، CI و بارگذاری

## ۱. چیدمان تست‌ها

| فایل | تمرکز |
|---|---|
| `tests/factories.py` | Factoryهای Tenant، Department، User، Admin، Document، DocumentChunk |
| `tests/test_factories.py` | صحت Factoryها |
| `tests/test_document_chunking.py` | تکه‌بندی توکنی، محدوده‌ها، هم‌پوشانی |
| `tests/test_document_tasks.py` | پردازش سند، وضعیت‌ها، batchها |
| `tests/test_api_services.py` | بازیابی ترکیبی، Rerank، ساخت Prompt، Citation |
| `tests/test_api_views.py` | قرارداد endpointها، مجوزها، پاسخ‌ها |
| `tests/test_jwt_security.py` | اعتبارسنجی توکن و Tenant |
| `tests/test_cross_department_security.py` | جلوگیری از دسترسی بین دپارتمان‌ها |
| `tests/test_integration_document_search.py` | جریان کامل آپلود تا جست‌وجو |

## ۲. پیکربندی pytest

`pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = tests.py test_*.py *_tests.py
```

### پیش‌نیاز مهم: دیتابیس Template

در `settings.py`:

```python
"TEST": {
    "TEMPLATE": "enterprise_rag_test_template",
}
```

Django دیتابیس تست را از این Template می‌سازد. بنابراین باید از قبل وجود داشته باشد و افزونه `vector` در آن نصب شده باشد:

```bash
createdb -h localhost -U postgres -T template0 enterprise_rag_test_template
psql -h localhost -U postgres -d enterprise_rag_test_template \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

اگر این مرحله انجام نشود، خطای `database ... does not exist` یا خطای نبود نوع `vector` می‌گیرید.

### متغیرهای محیطی تست

حداقل این‌ها لازم است:

```dotenv
DJANGO_SECRET_KEY=test-only-secret
DB_NAME=enterprise_rag
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=127.0.0.1
DB_PORT=5432
```

Redis برای تست‌های واحد لازم نیست، اما تست‌هایی که throttle یا cache را لمس می‌کنند به آن نیاز دارند.

## ۳. اجرا

```bash
pytest
pytest -q
pytest tests/test_jwt_security.py
pytest -k "tenant"
pytest --maxfail=1 -x
pytest --cov=. --cov-report=term-missing
```

نکات:

- `pytest` از `pytest-django` استفاده می‌کند؛ نیازی به `manage.py test` نیست، اما آن هم کار می‌کند.
- اگر تست‌ها به‌صورت موازی اجرا شوند، هر worker دیتابیس جدا می‌خواهد؛ `pytest-xdist` در وابستگی‌ها نیست.
- تست‌های سرویس AI در `ai_service/test_llm_client.py` و `ai_service/test_rate_limit.py` هستند و جداگانه اجرا می‌شوند:

```bash
cd ai_service
pytest
```

## ۴. نوشتن تست جدید

### استفاده از Factory

```python
from tests.factories import (
    TenantFactory, DepartmentFactory, UserFactory, AdminFactory,
    DocumentFactory, DocumentChunkFactory,
)

def test_member_cannot_read_other_department(db):
    other = DepartmentFactory()
    chunk = DocumentChunkFactory(document=DocumentFactory(department=other))
    ...
```

`UserFactory` به‌طور خودکار `tenant` را از `department` می‌گیرد و `DocumentFactory` هم `tenant` را از `uploaded_by` می‌گیرد.

### قواعد

- هر تست باید مستقل باشد و به داده تست دیگر وابسته نباشد.
- برای سرویس‌های خارجی (AI، LLM) همیشه mock بزنید؛ تست‌ها نباید به شبکه وابسته باشند.
- مسیرهای حساس را با هر دو نقش (`Member` و `Admin`) تست کنید.
- برای سناریوهای چند-مستأجری، حداقل دو Tenant بسازید و تلاش برای دسترسی متقابل را assert کنید.

## ۵. CI

`.github/workflows/ci.yml` روی `push` و `pull_request` به `main` اجرا می‌شود.

```text
PostgreSQL (pgvector/pgvector:pg16)  +  Redis 7
        │
        ├─ نصب Python 3.13 و libmagic
        ├─ نصب requirements.txt + پکیج‌های Django
        ├─ ساخت enterprise_rag_test_template و CREATE EXTENSION vector
        ├─ flake8 --select=F821,F822 (خطاهای نام‌تعریف‌شده)
        └─ pytest
```

نکته‌ها:

- flake8 فقط دو نوع خطا را بررسی می‌کند: `F821` (نام تعریف‌نشده) و `F822` (نام تعریف‌نشده در `__all__`). سبک کد، طول خط و importهای مرتب بررسی نمی‌شوند.
- CI فقط بک‌اند را تست می‌کند؛ فرانت‌اند workflow جدا ندارد.
- پوشش کد (coverage) آستانه ندارد.

## ۶. تست بار با Locust

`locustfile.py` یک کاربر جست‌وجو را شبیه‌سازی می‌کند.

```bash
export LOCUST_ACCESS_TOKEN="<ACCESS_TOKEN>"
locust -f locustfile.py --host http://127.0.0.1:8000
```

سپس `http://localhost:8089`.

نکات:

- توکن باید معتبر و متعلق به کاربری با دپارتمان باشد.
- بار اصلی روی `POST /api/query/search/` است؛ این مسیر Rerank و ذخیره تاریخچه دارد و سنگین‌ترین مسیر است.
- برای بار چت، سناریوی جداگانه بنویسید؛ چون SSE است و با `HttpUser` ساده به‌درستی اندازه‌گیری نمی‌شود.
- قبل از بارگذاری، `RateLimitConfig` و محدودیت Nginx را در نظر بگیرید؛ در غیر این صورت بیشتر پاسخ‌ها `429` خواهند بود.

## ۷. تست فرانت‌اند

```bash
cd frontend
npm run lint
npx playwright test
npx playwright test e2e/full-user-flow.spec.ts
npx playwright test --headed
```

`playwright.config.ts` سرور Next را خودش اجرا می‌کند و در CI دو retry دارد. برای اجرای موفق سناریوی کامل، بک‌اند و داده اولیه لازم است.

## ۸. چک‌لیست قبل از Merge

- [ ] تست‌های جدید برای رفتار جدید نوشته شده
- [ ] `pytest` کامل سبز است
- [ ] `python manage.py check` بدون خطاست
- [ ] در صورت تغییر مدل، migration ساخته و commit شده
- [ ] `npm run lint` در فرانت‌اند سبز است (در صورت تغییر فرانت)
- [ ] مستندات مرتبط به‌روز شده‌اند
- [ ] هیچ Secret یا فایل داده واقعی در commit نیست

## ۹. شکست‌های رایج تست

| خطا | علت | راه‌حل |
|---|---|---|
| `database "enterprise_rag_test_template" does not exist` | Template ساخته نشده | دستور `createdb` بالا را اجرا کنید |
| `type "vector" does not exist` | افزونه در Template نصب نیست | `CREATE EXTENSION vector;` |
| `connection refused` به Redis | Redis بالا نیست | `docker compose up -d redis` |
| تست‌ها به شبکه وصل می‌شوند | mock نبودن سرویس AI | `unittest.mock.patch` روی `requests.post` |
| `PermissionDenied` غیرمنتظره | کاربر Factory دپارتمان/Tenant ندارد | از Factoryهای موجود استفاده کنید |
