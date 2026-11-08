# راهنمای مشارکت

## ۱. پیش از شروع

```bash
python -m venv venv
source venv/Scripts/activate      # Windows / Git Bash
pip install -r requirements-django.txt

python manage.py migrate
python manage.py check
pytest
```

```bash
cd frontend
npm install
npm run lint
```

اگر تست‌ها اجرا نمی‌شوند، ابتدا [10-testing.md](10-testing.md) را بخوانید؛ دیتابیس Template پیش‌نیاز است.

## ۲. جریان کار

1. Issue یا توضیح کوتاه از تغییر بنویسید.
2. یک branch بسازید:

```bash
git checkout -b feat/document-pagination
git checkout -b fix/tenant-scope
git checkout -b docs/api-reference
```

3. تغییرات کوچک و متمرکز بدهید.
4. تست و مستندات را هم‌زمان به‌روزرسانی کنید.
5. Pull Request با توضیح «چه»، «چرا» و «چطور تست شد» باز کنید.

### پیشوندهای پیشنهادی

| پیشوند | کاربرد |
|---|---|
| `feat/` | قابلیت جدید |
| `fix/` | رفع باگ |
| `docs/` | مستندات |
| `refactor/` | بازنویسی بدون تغییر رفتار |
| `test/` | تست |
| `chore/` | ابزار، وابستگی، CI |

## ۳. قواعد بک‌اند

### سبک

- Python 3.13، خط حداکثر حدود ۷۹ کاراکتر (سبک فعلی کد).
- importها در بالای فایل و گروه‌بندی‌شده.
- نام‌ها انگلیسی و توصیفی.
- از f-string برای پیام‌های خطا استفاده کنید.
- از `transaction.atomic()` برای عملیات چندمرحله‌ای.
- عملیات سنگین را به Celery بسپارید، نه به چرخه درخواست.

### امنیت

- **هرگز** `tenant_id` را از ورودی کاربر نگیرید؛ همیشه از `request.user.tenant_id`.
- هر QuerySet جدید را با Tenant فیلتر کنید.
- برای دسترسی شیءمحور، `get_object` یا `get_queryset` را محدود کنید.
- نتایج سرویس‌های خارجی را قبل از نمایش، در دیتابیس بازبینی کنید.
- پیام خطا نباید Secret یا جزئیات داخلی افشا کند.

### افزودن endpoint جدید

```python
@extend_schema(
    request=MySerializer,
    responses=OpenApiResponse(description="..."),
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def my_view(request):
    tenant_error = _tenant_required_response(request)
    if tenant_error:
        return tenant_error

    serializer = MySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # منطق
    create_audit_log(request.user, "MY_ACTION")

    return Response({...}, status=status.HTTP_200_OK)
```

چک‌لیست:

- [ ] مسیر در `api/urls.py` یا `documents/urls.py` ثبت شد
- [ ] permission مناسب انتخاب شد (`IsAuthenticated`، `IsAdminUser`، `IsDepartmentMember`)
- [ ] فیلتر Tenant اعمال شد
- [ ] Serializer ورودی دارد و `max_length`/`min_value` گذاشته شد
- [ ] خطاها کد وضعیت درست دارند
- [ ] در صورت تغییر قرارداد، [04-api-reference.md](04-api-reference.md) به‌روز شد
- [ ] تست موفق و خطا اضافه شد

### مدل و migration

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py sqlmigrate documents 0014
```

قواعد:

- نام migration توصیفی باشد.
- برای فیلد جدید روی جدول بزرگ، مقدار پیش‌فرض یا `null=True` در نظر بگیرید.
- ایندکس و قید را در `Meta` تعریف کنید، نه با SQL دستی.
- migrationهای داده‌ای باید idempotent باشند.
- قبل از merge، `showmigrations` را بررسی کنید.

### Celery

- وظیفه باید idempotent باشد؛ ممکن است دوباره اجرا شود.
- از `transaction.on_commit` برای ارسال وظیفه پس از Commit استفاده کنید.
- `autoretry_for` و `max_retries` را آگاهانه تنظیم کنید.
- در خطا، وضعیت دامنه (مثل `Document.status`) را به حالت قابل فهم ببرید.

## ۴. قواعد فرانت‌اند

- TypeScript و کامپوننت‌های تابعی.
- صفحات تعاملی `"use client"`.
- داده‌گیری با `lib/api.ts`، نه Axios خام (به‌جز stream).
- برای مسیرهای محافظت‌شده از `withAuth` استفاده کنید.
- خطا را به کاربر نشان دهید، نه فقط `console.error`.
- استایل با Tailwind و کلاس‌های موجود.
- قبل از commit:

```bash
npm run lint
npm run build
```

### افزودن صفحه

1. پوشه در `app/` بسازید.
2. در صورت نیاز `withAuth` را اعمال کنید.
3. در صورت نیاز نقش را بررسی کنید (و در بک‌اند هم اعمال کنید).
4. در [09-frontend.md](09-frontend.md) مسیر را اضافه کنید.

## ۵. تست

- برای هر باگ، تست بازتولیدکننده بنویسید.
- برای هر endpoint جدید، حداقل تست موفقیت و تست مجوز.
- برای منطق چند-مستأجری، دو Tenant بسازید.
- سرویس‌های خارجی را mock کنید.
- از Factoryهای `tests/factories.py` استفاده کنید.

```bash
pytest tests/test_api_views.py -q
pytest -k "tenant and not slow"
pytest --cov=api --cov=documents --cov-report=term-missing
```

## ۶. مستندات

هر تغییر در این موارد باید مستند شود:

| تغییر | سند |
|---|---|
| endpoint یا قرارداد | [04-api-reference.md](04-api-reference.md) |
| مدل داده یا migration | [05-data-model.md](05-data-model.md) |
| پردازش سند | [06-document-pipeline.md](06-document-pipeline.md) |
| بازیابی و Prompt | [07-rag-pipeline.md](07-rag-pipeline.md) |
| مجوز و امنیت | [08-security.md](08-security.md) |
| صفحه یا جریان فرانت | [09-frontend.md](09-frontend.md) |
| متغیر محیطی یا سرویس | [11-deployment.md](11-deployment.md) |
| محدودیت جدید | [13-known-issues.md](13-known-issues.md) |

قواعد نوشتار:

- رفتار فعلی را توصیف کنید، نه آرزوها.
- نمونه‌ها باید اجراشدنی باشند.
- مسیر فایل‌ها را دقیق بنویسید.
- هرگز Secret واقعی در مستندات نگذارید.

## ۷. Commit

پیام‌ها کوتاه و انگلیسی یا فارسی، اما یکدست:

```text
feat: add pagination to document list
fix: scope document list to user department
docs: document RAG citation flow
test: cover cross-tenant chunk access
```

از commitهای بزرگ و مخلوط (فرمت + منطق + مستندات در یک commit) پرهیز کنید.

## ۸. چک‌لیست Pull Request

- [ ] تغییر متمرکز و قابل مرور است
- [ ] `pytest` سبز است
- [ ] `python manage.py check` بدون خطاست
- [ ] migration در صورت نیاز ساخته شده
- [ ] `npm run lint` و `npm run build` سبز است (در صورت تغییر فرانت)
- [ ] تست جدید اضافه شده
- [ ] مستندات مرتبط به‌روز شده
- [ ] هیچ Secret، فایل داده یا خروجی Build در commit نیست
- [ ] رفتار امنیتی (Tenant/نقش) بررسی شده
- [ ] توضیح داده شده چطور تست شده است

## ۹. گزارش باگ

این اطلاعات را ضمیمه کنید:

- نسخه کد (commit hash)
- سیستم‌عامل و نسخه Docker/Python/Node
- مراحل بازتولید
- رفتار انتظاری و رفتار واقعی
- لاگ مرتبط (بدون توکن و Secret)
- خروجی `docker compose ps` در صورت مرتبط بودن

## ۱۰. گزارش آسیب‌پذیری

آسیب‌پذیری امنیتی را در Issue عمومی منتشر نکنید. آن را از مسیر خصوصی تیم یا مالک مخزن اطلاع دهید و جزئیات بازتولید را فقط در همان کانال به اشتراک بگذارید.
