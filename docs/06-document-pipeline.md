# ۰۶ — چرخه پردازش سند

این سند مسیر یک فایل از آپلود تا آماده شدن برای جست‌وجو را توضیح می‌دهد.

## ۱. نمای کلی

```text
آپلود (HTTP)
  └─ اعتبارسنجی فایل و مجوز
  └─ ذخیره فایل روی دیسک
  └─ Document(status=Pending)
  └─ process_document.delay(document_id)
            │
            ▼
process_document (Celery)
  ├─ status = Processing
  ├─ استخراج متن بر اساس MIME
  ├─ chunk_text()
  ├─ حذف Chunkهای قبلی + درج Chunkهای جدید
  ├─ صف‌بندی generate_embedding_batch برای هر ۱۶ Chunk
  └─ در خطا: status = Failed و retry
            │
            ▼
generate_embedding_batch (Celery)
  ├─ فراخوانی /api/embed/
  ├─ درج Embeddingها
  └─ اگر همه Chunkها بردار دارند: status = Indexed
```

## ۲. مرحله آپلود

فایل‌های دخیل:

- `documents/views.py` — `DocumentUploadView`
- `documents/serializers.py` — `DocumentSerializer`

### اعتبارسنجی

| بررسی | مقدار | محل |
|---|---|---|
| اندازه | ≤ ۵ مگابایت | Serializer |
| MIME واقعی | PDF، TXT، DOC، DOCX | Serializer با `magic.from_buffer` |
| عنوان | غیرخالی | Serializer |
| Tenant کاربر | باید وجود داشته باشد | View |
| Tenant دپارتمان | باید با Tenant کاربر یکی باشد | View |
| عضویت دپارتمان | کاربر عضو باشد یا Admin | View |
| نرخ آپلود | ۱۰ در ساعت برای هر کاربر | django-ratelimit |

نوع فایل با خواندن ۲۰۴۸ بایت اول و `magic.from_buffer(..., mime=True)` تشخیص داده می‌شود، نه با پسوند فایل. پس از تشخیص، نشانگر فایل به ابتدا برگردانده می‌شود.

### ذخیره‌سازی

```text
media/documents/tenant_<tenant_id>/<filename>
```

فقط نام فایل نگه داشته می‌شود و مسیرهای موجود در نام ارسالی حذف می‌شوند. نام فایل یکتا نمی‌شود.

### ثبت و صف

```python
document = serializer.save(
    tenant_id=user.tenant_id,
    uploaded_by=user,
    status="Pending",
    file_type=file_type,
    file_size=file.size,
)
create_audit_log(user, "UPLOAD")
transaction.on_commit(lambda: process_document.delay(document.id))
```

`transaction.on_commit` تضمین می‌کند وظیفه فقط پس از Commit تراکنش ارسال شود؛ در غیر این صورت worker ممکن است رکورد را پیدا نکند.

### سند راهنمای خودکار (Onboarding)

دپارتمان تازه هیچ سندی ندارد، پس هر پرسش به بن‌بست می‌خورد. برای همین هنگام ساخت هر دپارتمان یک سند راهنما ساخته می‌شود:

- کد: `documents/onboarding.py` → `ensure_onboarding_document`
- محرک: سیگنال `post_save` روی `Department` در `departments/signals.py`
- متن: `build_onboarding_text` — راهنمای فارسی درباره آپلود، فرمت‌ها، وضعیت‌ها، جست‌وجو، استناد، حریم خصوصی و پرسش‌های رایج

ترتیب کار:

1. فایل متنی در `media/documents/tenant_<id>/onboarding-<dept_id>-<slug>.txt` نوشته می‌شود.
2. ردیف `Document` با `is_system=True` و `status="Processing"` ساخته می‌شود.
3. Chunkها **همگام** با همان `save_document_chunks` خط لوله اصلی ساخته می‌شوند (چند میلی‌ثانیه، بدون شبکه).
4. Embeddingها **پس از Commit** با `generate_embedding_batch.delay` در صف قرار می‌گیرند.

چرا این تفکیک مهم است: اگر Redis یا worker در دسترس نباشد، مرحله ۳ انجام شده است و سند از طریق نیمه کلیدواژه‌ای `hybrid_search` پیدا می‌شود؛ پس وعده «دپارتمان تازه هم حداقل به پرسش‌های پایه پاسخ می‌دهد» حتی در قطعی جزئی برقرار می‌ماند. اگر صف شکست بخورد فقط یک `logger.exception` ثبت می‌شود و سند در وضعیت `Processing` می‌ماند.

نکات پیاده‌سازی:

- تابع idempotent است: اگر دپارتمان از قبل سند `is_system` داشته باشد `None` برمی‌گرداند و Chunk تکراری نمی‌سازد.
- کل بلوک سیگنال در `try/except` است؛ خطا در ساخت راهنما نباید ساخت دپارتمان را rollback کند.
- نویسنده سند: مدیر سازنده از طریق `attributed_to(user)` در View، و در غیر آن اولین Admin فعال Tenant.
- متن راهنما عمداً هیچ عددی داخل قلاب ندارد؛ `extract_citation_ids` هر `[12]` را استناد می‌گیرد و به Chunk بی‌ربط نگاشت می‌کند.
- برای دپارتمان‌های قدیمی: `python manage.py seed_onboarding_docs --tenant-id 3 --dry-run` (بدون آرگومان: همه Tenantها).

## ۳. استخراج متن

`documents/tasks.py` بر اساس `file_type` تصمیم می‌گیرد:

| MIME | استخراج‌کننده | کتابخانه |
|---|---|---|
| `application/pdf` | `extract_pdf_text` | `pypdf` |
| `text/plain` | `extract_txt_text` | استاندارد |
| `application/msword` | `extract_word_text` | `python-docx` |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `extract_word_text` | `python-docx` |

نوع ناشناخته → `ValueError` و در نتیجه `Failed`.

محدودیت شناخته‌شده: `python-docx` فرمت قدیمی `.doc` باینری را واقعاً پشتیبانی نمی‌کند، هرچند MIME آن مجاز است. فایل‌های `.doc` ممکن است در مرحله استخراج شکست بخورند.

فایل‌های اسکن‌شده PDF بدون لایه متنی، متن تولید نمی‌کنند؛ OCR در پروژه وجود ندارد.

## ۴. تکه‌بندی

`documents/chunking.py`

```python
chunk_text(text, chunk_size=400, overlap_percent=10)
```

| پارامتر | مقدار مجاز | مقدار استفاده‌شده در پردازش |
|---|---|---|
| `chunk_size` | ۳۰۰ تا ۵۰۰ توکن | ۴۰۰ |
| `overlap_percent` | ۱۰ تا ۱۵ درصد | ۱۰ |

جزئیات پیاده‌سازی:

- توکن‌سازی با `tiktoken` و انکودینگ `cl100k_base`.
- `overlap_tokens = chunk_size * overlap_percent / 100`
- `step = chunk_size - overlap_tokens`
- پنجره با گام `step` حرکت می‌کند و در هر مرحله حداکثر `chunk_size` توکن برمی‌دارد.
- متن خالی → لیست خالی.
- Chunkهای خالی یا فقط فاصله حذف می‌شوند.

اگر هیچ Chunkی تولید نشود، وظیفه با `ValueError("No text chunks were generated.")` شکست می‌خورد.

## ۵. ذخیره Chunkها

داخل یک تراکنش:

1. همه Chunkهای قبلی همان سند حذف می‌شوند.
2. Chunkهای جدید با `bulk_create` درج می‌شوند.
3. شناسه‌ها خوانده می‌شوند و به batchهای ۱۶تایی تقسیم می‌شوند.

حذف قبلی باعث می‌شود پردازش مجدد یک سند، Chunkهای تکراری نسازد. قید `UNIQUE(document, chunk_index)` هم پشتیبان این رفتار است.

## ۶. تولید Embedding

`generate_embedding_batch(document_id, chunk_ids)`

1. Chunkها به ترتیب `chunk_index` خوانده می‌شوند.
2. متن‌ها به `POST {AI_SERVICE_URL}/api/embed/` فرستاده می‌شوند.
3. اگر تعداد بردارها با تعداد Chunkها برابر نباشد → خطا.
4. Embeddingها با `bulk_create(ignore_conflicts=True)` درج می‌شوند.
5. تعداد کل Chunkها و Embeddingهای سند شمرده می‌شود.
6. اگر برابر باشند، `status = Indexed`.

مدل: `intfloat/multilingual-e5-small` با بُعد ۳۸۴.

### چرا دسته‌ای؟

- محدود کردن حافظه سرویس AI
- امکان retry مستقل برای هر دسته
- کاهش زمان هر وظیفه و جلوگیری از timeout

## ۷. خطا، retry و بازیابی

هر دو وظیفه:

```python
@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
)
```

رفتار:

- خطا → تلاش مجدد با تأخیر فزاینده تا ۶۰ ثانیه، حداکثر ۳ بار.
- در `process_document`، هر خطا وضعیت سند را `Failed` می‌کند.
- `generate_embedding_batch` وضعیت را `Failed` نمی‌کند؛ اگر یک batch شکست بخورد، سند در `Processing` می‌ماند و تنها Celery log نشانه خطاست.

### بازیابی دستی

```bash
# اجرای مجدد پردازش
python manage.py shell -c "from documents.tasks import process_document; process_document.delay(<DOC_ID>)"
```

یا آپلود مجدد فایل. برای سند `Failed`، ابتدا Celery log را بررسی کنید:

```bash
docker compose logs --tail=200 celery_worker
```

## ۸. افزودن فرمت جدید

برای پشتیبانی از فرمتی مثل `.pptx`:

1. استخراج‌کننده در `documents/extractors/` اضافه کنید.
2. MIME مجاز را در `ALLOWED_FILE_TYPES` (`documents/serializers.py`) اضافه کنید.
3. شاخه مربوطه را در `process_document` اضافه کنید.
4. تست استخراج و تست پردازش اضافه کنید.
5. این سند و [04-api-reference.md](04-api-reference.md) را به‌روزرسانی کنید.

## ۹. پارامترهای قابل تنظیم

| پارامتر | محل | اثر |
|---|---|---|
| حداکثر اندازه فایل | `documents/serializers.py` → `MAX_FILE_SIZE` | مصرف دیسک و زمان پردازش |
| اندازه Chunk | `documents/tasks.py` → `chunk_size=400` | دقت بازیابی در برابر تعداد بردار |
| هم‌پوشانی | `documents/tasks.py` → `overlap_percent=10` | حفظ پیوستگی متن در مرز Chunkها |
| اندازه batch | `EMBEDDING_BATCH_SIZE = 16` | حافظه و تعداد وظایف |
| مدل Embedding | `tasks.py` + `ai_service/main.py` | باید هر دو هم‌خوان باشند (۳۸۴ بُعد) |

> اگر مدل Embedding را عوض کنید، باید همه بردارهای موجود بازسازی شوند و بُعد جدید با `VectorField` و ایندکس HNSW هم‌خوان باشد. در غیر این صورت جست‌وجو خطا می‌دهد.
