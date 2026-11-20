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

> **اگر در PowerShell هستید:** قبل از اجرای pytest متغیرهای پراکسی را خالی کنید؛ `sentry_sdk` هنگام بارگذاری `settings.py` آنها را میخواند و اگر مقدارشان فاقد Scheme باشد (`host:port` بهجای `http://host:port`)، با `ProxySchemeUnknown: Proxy URL had no scheme` میشکند. این مشکل کد پروژه نیست:
>
> ```powershell
> $env:HTTP_PROXY=""; $env:HTTPS_PROXY=""; $env:http_proxy=""; $env:https_proxy=""
> ./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_image.py -q
> ```
>
> در Git Bash همان کار را با پیشوند `HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy=` انجام میدهیم. دستور OCR داخل کانتینر هم در PowerShell نباید پرانتز داخل regex داشته باشد (نقل قولها توسط PowerShell حذف میشوند):
>
> ```powershell
> docker compose exec -T django tesseract --list-langs
> docker compose exec -T django pdftoppm -v
> ```

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

## ۷. تست OCR (اسناد اسکنشده)

هر ساب تسک تست جداگانه دارد تا محل شکست مشخص باشد: ایمیج، وابستگی پایتون، یا منطق استخراج.

### ساب تسک ۱ — موتور OCR در ایمیج

```bash
docker compose build django celery_worker
docker compose up -d --force-recreate django celery_worker
docker compose exec -T django sh -c 'tesseract --list-langs 2>&1 | grep -E "^(fas|eng)$" && pdftoppm -v'
./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_image.py -q
```

گام سوم روی کانتینر واقعی اجرا میشود و ثابت میکند `fas` واقعاً نصب است، نه فقط در Dockerfile نوشته شده. تست پایتون فقط ساختار ایمیج و Compose را بررسی میکند و نیازی به Tesseract روی میزبان ندارد.

### ساب تسک ۲ — وابستگیهای پایتون

```bash
./venv/Scripts/python.exe -m pip install -r requirements-django.txt -r requirements.txt
./venv/Scripts/python.exe -m pytest tests/test_ocr_python_dependencies.py -q
```

تستها نسخههای پینشده، پارامترهای ارسالشده به Tesseract (`lang`, `config`, `timeout`) و پیام خطای بستهٔ زبان گمشده را پوشش میدهند.

### ساب تسک ۳ — تشخیص PDF اسکنشده و استخراج

```bash
./venv/Scripts/python.exe -m pytest tests/test_ocr_extraction.py -q
./venv/Scripts/python.exe -m pytest tests/test_ocr_upload_validation.py -q
cd frontend && npx playwright test e2e/spreadsheet-upload.spec.ts
```

فایل آخر همان تستی است که از ناهماهنگی لیست فرمتهای فرانت جلوگیری میکند؛ اکنون علاوهبر XLSX/CSV، PNG و JPEG را هم بررسی میکند و GIF را رد مینماید.

### اثبات عملی در پلتفرم

نمونهها در `samples/scanned_letter_demo.png` و `samples/scanned_letter_demo.pdf` قرار دارند (تولیدشده توسط `samples/generate_ocr_demo.py`).

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"USERNAME","password":"PASSWORD"}' \
  | ./venv/Scripts/python.exe -c "import sys,json; print(json.load(sys.stdin)['access'])")
curl -X POST http://localhost:8000/api/documents/ \
  -H "Authorization: Bearer $TOKEN" \
  -F 'title=Scanned letter' -F 'department=DEPT_ID' \
  -F 'file_path=@samples/scanned_letter_demo.png;type=image/png'
# تا رسیدن status به Indexed منتظر بمانید، سپس:
curl -s -X POST http://localhost:8000/api/search/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"صورتجلسه"}'
```

همین کار را با `scanned_letter_demo.pdf` تکرار کنید؛ PDF نمونه فاقد لایه متن است و مسیر OCR را فعال میکند. نتیجهٔ جستوجو باید متن نامه را برگرداند.

## ۸. تست فرانت‌اند

```bash
cd frontend
npm run lint
npm run test:unit
npx playwright test
npx playwright test e2e/full-user-flow.spec.ts
npx playwright test --headed
```

`npm run test:unit` تست‌های خالص Node را اجرا می‌کند (`node --test "lib/**/*.test.mjs"`) — بدون DOM، بدون bundler و بدون وابستگی جدید. منطق `lib/answerFormat.ts` (پارسر قالب پاسخ و تشخیص جهت متن) همین‌جا پوشش داده می‌شود، چون خالص و قطعی است و تست آن میلی‌ثانیه‌ای است.

`playwright.config.ts` سرور Next را خودش اجرا می‌کند و در CI دو retry دارد. برای اجرای موفق سناریوی کامل، بک‌اند و داده اولیه لازم است؛ تست‌های `chat-feedback.spec.ts` و `answer-formatting.spec.ts` بک‌اند را کامل mock می‌کنند و به سرور نیاز ندارند.

### تست جداگانه هر ساب تسک (رابط فرمتهای جدید و نسخهبندی)

### تست جداگانه هر ساب تسک (رابط فرمتهای جدید و نسخهبندی)

در **PowerShell** (ترمینال پیشفرض VS Code روی ویندوز) از `;` بهجای `&&` استفاده کنید — PowerShell 5.1 ترکیب `&&` را نمیشناسد:

```powershell
cd C:\Users\heliya\enterprise-rag-platform\frontend; node --test lib\__tests__\uploadFormats.test.mjs
cd C:\Users\heliya\enterprise-rag-platform\frontend; npx playwright test e2e/format-guidance.spec.ts

cd C:\Users\heliya\enterprise-rag-platform\frontend; npx playwright test e2e/document-versioning.spec.ts

cd C:\Users\heliya\enterprise-rag-platform\frontend; node --test lib\__tests__\versionHistory.test.mjs
cd C:\Users\heliya\enterprise-rag-platform\frontend; npx playwright test e2e/version-history.spec.ts
```

> نکته: آرگومان مسیر تست Playwright را حتی در PowerShell با `/` بنویسید (`e2e/...`). Playwright آرگومان را بهعنوان regex میخواند و `\` در regex یک escape است، پس `e2e\format-guidance.spec.ts` به `e2eformat-guidance.spec.ts` تبدیل میشود و خطای `No tests found` میدهد.

همان دستورها در **Git Bash**:

```bash
cd frontend && node --test lib/__tests__/uploadFormats.test.mjs
cd frontend && npx playwright test e2e/format-guidance.spec.ts
cd frontend && npx playwright test e2e/document-versioning.spec.ts
cd frontend && node --test lib/__tests__/versionHistory.test.mjs
cd frontend && npx playwright test e2e/version-history.spec.ts
```

اگر اجرای Playwright در محیط محدود با خطای حذف دستجمعی `test-results` مواجه شد، خروجی را به مسیر دیگری ببرید:

```powershell
cd C:\Users\heliya\enterprise-rag-platform\frontend; npx playwright test e2e/version-history.spec.ts --output=C:\tmp\pw-ui-run --trace=off
```

## ۹. چک‌لیست قبل از Merge

- [ ] تست‌های جدید برای رفتار جدید نوشته شده
- [ ] `pytest` کامل سبز است
- [ ] `python manage.py check` بدون خطاست
- [ ] در صورت تغییر مدل، migration ساخته و commit شده
- [ ] `npm run lint` در فرانت‌اند سبز است (در صورت تغییر فرانت)
- [ ] `npm run test:unit` در فرانت‌اند سبز است (در صورت تغییر فرانت)
- [ ] مستندات مرتبط به‌روز شده‌اند
- [ ] هیچ Secret یا فایل داده واقعی در commit نیست

## ۱۰. شکست‌های رایج تست

| خطا | علت | راه‌حل |
|---|---|---|
| `database "enterprise_rag_test_template" does not exist` | Template ساخته نشده | دستور `createdb` بالا را اجرا کنید |
| `type "vector" does not exist` | افزونه در Template نصب نیست | `CREATE EXTENSION vector;` |
| `connection refused` به Redis | Redis بالا نیست | `docker compose up -d redis` |
| تست‌ها به شبکه وصل می‌شوند | mock نبودن سرویس AI | `unittest.mock.patch` روی `requests.post` |
| `PermissionDenied` غیرمنتظره | کاربر Factory دپارتمان/Tenant ندارد | از Factoryهای موجود استفاده کنید |
