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
| MIME واقعی | PDF، TXT، DOC، DOCX، XLSX، CSV | `documents/filetypes.py` با `magic.from_buffer` |
| عنوان | غیرخالی | Serializer |
| Tenant کاربر | باید وجود داشته باشد | View |
| Tenant دپارتمان | باید با Tenant کاربر یکی باشد | View |
| عضویت دپارتمان | کاربر عضو باشد یا Admin | View |
| نرخ آپلود | ۱۰ در ساعت برای هر کاربر | django-ratelimit |

تشخیص نوع در `documents/filetypes.py` است، نه در Serializer. دو فرمت را نمی‌توان از روی بایت تشخیص داد:

| پسوند | پاسخ libmagic | چرا کافی نیست |
|---|---|---|
| `.xlsx` | `application/zip` | هر فایل zip همین پاسخ را می‌گیرد |
| `.csv` | `text/plain` | از `.txt` قابل تفکیک نیست |

برای همین `effective_file_type` پسوند را می‌خواند، اما تنها وقتی به آن اعتماد می‌کند که بایت‌ها تأییدش کنند:

- `.xlsx` → داخل zip باید پوشه `xl/` باشد.
- `.docx` → داخل zip باید پوشه `word/` باشد.
- `.csv` → ۶۴ کیلوبایت اول باید UTF-8 معتبر باشد؛ با decoder افزایشی خوانده می‌شود تا کاراکتر چندبایتیِ بریده در مرز خواندن، فایل سالم را خراب نشان ندهد.

اگر پسوند و بایت‌ها هم‌خوان نباشند `INVALID_FILE_TYPE` برمی‌گردد و آپلود با `400` رد می‌شود. عمداً به MIME خام برنمی‌گردیم: MIME یک `.csv` خراب `text/plain` است که مجاز است، پس فایل پذیرفته می‌شد و بیست ثانیه بعد در Celery به ردیف `Failed` تبدیل می‌شد.

نشانگر فایل پس از هر خواندن به ابتدا برگردانده می‌شود، چون همان هندل بعداً ذخیره می‌شود.

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

### نسخهٔ جدید یک سند (Versioning)

`POST /api/documents/{id}/versions/` مسیر آپلود اول را تکرار می‌کند، با سه تفاوت:

```python
with transaction.atomic():
    locked = Document.objects.select_for_update().get(pk=parent_id)

    if locked.status == "Archived":
        raise VersionConflict(...)          # → 409

    new_document = Document.objects.create(
        ...,
        version=locked.version + 1,
        parent_document=locked,
    )
    archive_document(locked)                # status + archived_at + حذف Embeddingها
```

1. **قفل ردیف والد.** بدون `select_for_update` دو آپلود هم‌زمان هر دو `v2` را محاسبه می‌کنند. قید `unique_document_version_per_parent` جلوی شاخه‌شدن را می‌گیرد و بازنده `409` می‌گیرد، ولی قفل کاری می‌کند که این حالت نادر باشد نه رایج.
2. **آرشیو در همان تراکنش.** هیچ خواننده‌ای حالت «آرشیوشده ولی هنوز قابل جست‌وجو» را نمی‌بیند.
3. **حذف Embeddingها، نگه‌داشتن Chunkها.** متن برای ارجاع‌های قدیمی می‌ماند؛ بردارها می‌روند تا ایندکس HNSW نسخهٔ منسوخ را برنگرداند.

دو محافظ در وظایف پس‌زمینه، چون صف می‌تواند بعد از آرشیو اجرا شود:

| وظیفه | محافظ |
|---|---|
| `process_document` | اگر سند `Archived` باشد، بدون استخراج و تکه‌بندی برمی‌گردد (`{"skipped": "archived"}`) |
| `generate_embedding_batch` | قبل از فراخوانی مدل بررسی می‌کند؛ اگر بین تولید بردار و نوشتن، سند آرشیو شود، با `select_for_update` می‌بیند و بردارهای تازه را خودش پاک می‌کند |

بدون این دو، سناریوی واقعی «آپلود v1 و بلافاصله v2» باعث می‌شد وظیفهٔ در جریان، نسخهٔ قدیمی را دوباره `Indexed` کند و به ایندکس برگرداند.

## ۳. استخراج متن

`documents/tasks.py` بر اساس `file_type` تصمیم می‌گیرد:

| MIME | استخراج‌کننده | کتابخانه |
|---|---|---|
| `application/pdf` | `extract_pdf_text` (با fallback به OCR) | `pypdf` + `pytesseract` |
| `image/jpeg` | `extract_image_text` | `pytesseract` + `Pillow` |
| `image/png` | `extract_image_text` | `pytesseract` + `Pillow` |
| `text/plain` | `extract_txt_text` | استاندارد |
| `application/msword` | `extract_word_text` | `python-docx` |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `extract_word_text` | `python-docx` |
| `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `extract_tabular_rows` | `openpyxl` |
| `text/csv` | `extract_tabular_rows` | `pandas` |
| `message/rfc822` | `extract_email_chunks` | `email` (استاندارد) |

نوع ناشناخته → `ValueError` و در نتیجه `Failed`.

محدودیت شناخته‌شده: `python-docx` فرمت قدیمی `.doc` باینری را واقعاً پشتیبانی نمی‌کند، هرچند MIME آن مجاز است. فایل‌های `.doc` ممکن است در مرحله استخراج شکست بخورند.

فایل‌های `.doc` باینری قدیمی ممکن است در مرحله استخراج شکست بخورند (بخش ۳٫۵ سند ۱۳).

### ایمیل (`.eml`)

یک ایمیل با قواعد خودش تکه می‌شود، نه با شمارش توکن. متادیتا و بدنه در **یک** Chunk قرار می‌گیرند، چون نام فرستنده و موضوع هیچ‌جا در بدنه نیامده‌اند و بدون آن‌ها نه می‌توان پاسخ را به فرستنده نسبت داد و نه با جست‌وجوی موضوع چیزی پیدا کرد:

```text
Subject: صورت‌حساب سالیانه — شعبهٔ مرکزی
From: سارا احمدی <sara.ahmadi@example.com>
To: finance@example.com
Cc: manager@example.com
Date: 2024-03-04T10:22+03:30
Attachments: invoice-1403.pdf

با سلام،
صورت‌حساب سالیانهٔ شعبهٔ مرکزی پیوست شد...
```

| تصمیم | دلیل |
|---|---|
| هدرها به شکل `Field: value` | مدل embedding باید برچسب را کنار مقدار ببیند؛ «چه کسی فرستاد» و «سارا احمدی» هر دو به `From:` نزدیک نیاز دارند |
| تاریخ ISO به‌جای RFC 5322 | `Mon, 4 Mar 2024 10:22:00 +0330` هم بد embedding می‌شود هم بد خوانده می‌شود؛ ISO منطقهٔ زمانی را نگه می‌دارد |
| `text/plain` بر `text/html` مقدم | پیام `multipart/alternative` همان متن را دو بار دارد؛ ایندکس کردن هر دو هر جمله را تکراری و شباهت هر Chunk را نصف می‌کند |
| HTML فقط وقتی متن ساده نبود | ایمیل‌های HTML-only رایج‌اند؛ تبدیل با `html.parser` استاندارد و بدون کتابخانهٔ اضافه |
| نام پیوست در هدر، محتوای پیوست نه | نام فایل ارزش جست‌وجو دارد؛ base64 یک PDF فقط نویز است |
| Chunkهای بعدی هدر فشرده می‌گیرند | مدل embedding حدود ۵۱۲ توکن می‌بیند؛ بدون تکرار هدر، نیمهٔ دوم ایمیل‌های بلند با جست‌وجوی موضوع پیدا نمی‌شود |

پارس با `policy.default` انجام می‌شود، نه `compat32`: `compat32` موضوعی را که به‌صورت UTF-8 خام در هدر نوشته شده (نامعتبر ولی بسیار رایج) به شیئی تبدیل می‌کند که به علامت سؤال تبدیل می‌شود — یعنی همان چیزی که کاربر جست‌وجو می‌کند از دست می‌رود. کدگذاری‌های بدنه به ترتیب `charset` اعلام‌شده، UTF-8، `cp1256` و `latin-1` امتحان می‌شوند.

سقف بدنه: `EMAIL_MAX_BODY_CHARS` (پیش‌فرض ۴۰۰۰۰ کاراکتر) — یک رشتهٔ reply طولانی می‌تواند مگابایت باشد.

**پشتیبانی نمی‌شود:** `.msg` (فرمت باینری Outlook). دلیلش در [13-known-issues.md](13-known-issues.md) آمده است.

### فایل‌های جدولی (XLSX / CSV)

`documents/extractors/tabular.py`

جدول متن نیست. اگر مثل بقیه فرمت‌ها با بودجه توکن تکه‌بندی شود، Chunk از وسط یک ردیف شروع می‌شود و سرستون‌ها را از دست می‌دهد؛ حاصل چیزی است شبیه `| 120 | USD |` که نه مدل Embedding می‌فهمد ۱۲۰ چیست و نه خواننده. برای همین این دو فرمت از `chunk_text` عبور نمی‌کنند و **ردیف به ردیف** تکه می‌شوند، و هر Chunk سرستون‌های خودش را تکرار می‌کند:

```text
Sheet: Prices
| Product | Price | Unit | Code |
| --- | --- | --- | --- |
| Bearing Kit | 45 | EUR | BR-777 |
```

یک ردیف = یک Chunk، به دو دلیل: معیار پذیرش «جست‌وجوی یک کلمه در سلول، دقیقاً همان سطر را برگرداند» است نه «بلوکی شامل آن»؛ و هر Chunk یک فراخوانی Embedding است، پس اندازه دانه مستقیماً هزینه را تعیین می‌کند.

تبدیل سلول‌ها:

| ورودی | خروجی | چرا |
|---|---|---|
| `120.0` (float) | `120` | قیمت نباید `120.0` نمایش داده شود |
| `9123456789.0` | `9123456789` | نه `9.12e+09` |
| `date` | `2024-03-01` | ISO، قابل مقایسه و جست‌وجو |
| `True` | `TRUE` | نه `1` |
| `NaN` / `None` | رشته خالی | سلول خالی باید خالی بماند |
| متن بلندتر از ۲۰۰ کاراکتر | کوتاه‌شده با `…` | یک سلول نباید کل پنجره Embedding را بگیرد |

سرستون‌ها:

- ستون بی‌نام → `Column N`.
- نام تکراری → `Price (2)`؛ `| Price | Price |` به خواننده نمی‌گوید عدد از کدام ستون است.
- اگر اولین ردیف غیرخالی کاملاً عددی باشد، سرستون نیست و داده است؛ در این حالت نام‌ها `Column N` می‌شوند تا رکورد اول قربانی نشود.

سقف‌ها: `MAX_ROWS = 2000` (از `TABULAR_MAX_ROWS`)، `MAX_COLUMNS = 40`، `MAX_CELL_CHARS = 200`، `MAX_ROW_CHARS = 1200`. سقف ردیف در لاگ هشدار می‌دهد؛ بی‌صدا بریدن داده بدتر از بریدن با اعلام است.

CSV: جداکننده با `sep=None` و موتور `python` حدس زده می‌شود (خروجی اکسل اروپایی با `;`)، `dtype=str` صفرهای ابتدایی شماره تلفن را حفظ می‌کند و `keep_default_na=False` سلول خالی را `NaN` نمی‌کند. فایل غیر UTF-8 با پیام روشن `ValueError` می‌دهد.

XLSX: `load_workbook(read_only=True, data_only=True)` — `read_only` برگه را جریان می‌دهد و `data_only` نتیجه محاسبه‌شده فرمول را برمی‌گرداند، نه رشته `=B2*C2`.

پیش‌نمایش این فایل‌ها (`documents/preview.py`) همان Chunkها را با فاصله خطوط به هم می‌چسباند؛ یعنی متنی که کاربر در کشوی استناد می‌بیند، دقیقاً همان متنی است که ایندکس شده.

### اسناد اسکنشده و تصاویر (OCR)

`documents/extractors/ocr.py` + `documents/extractors/pdf.py`

بسیاری از نامههای اداری فقط تصویرند: متنی برای `pypdf` وجود ندارد تا استخراج کند. این لایه سه حالت را از یک مسیر عبور میدهد:

```text
JPEG/PNG  ──────────────────────────────► OCR ─► chunk_text ─► Embedding
PDF       ─► page.extract_text()
             ├─ متن کافی (≥ ۲۰ کاراکتر) ─────► همان متن
             └─ صفحه تصویری ─────────────────► OCR همان صفحه
```

نکته مهم، **تصمیمگیری بهازای هر صفحه** است، نه بهازای کل سند. یک PDF میتواند روی جلد تایپشده و پیوستهای اسکنشده داشته باشد؛ OCR فقط صفحاتی را میخواند که لایه متنی آنها کمتر از ۲۰ کاراکتر است و ترتیب صفحات حفظ میشود. هیچ صفحهای دو بار پردازش نمیشود.

برای تصویر:

1. `ImageOps.exif_transpose` چرخش EXIF دوربین را اعمال میکند.
2. تصویر به خاکستری تبدیل و `autocontrast` میشود — نور ناهموار اسکنر، رایجترین دلیل از دست رفتن متن است.
3. Tesseract با `fas+eng` و `--oem 1 --psm 3` و timeout مشخص فراخوانی میشود.
4. `ي`/`ك` عربی به `ی`/`ک` فارسی تبدیل میشوند تا متن OCR با عبارت تایپشده کاربر مطابقت داشته باشد. **اعداد و کدها دستکاری نمیشوند**: `BR-777` و `۱۴۰۲` همانطور که خوانده شدهاند ذخیره میشوند.

محدودیتهای هزینه (همه قابل تنظیم از `.env`):

| پارامتر | پیشفرض | دلیل |
|---|---|---|
| `OCR_LANGUAGES` | `fas+eng` | متن فارسی همراه کد لاتین؛ بسته fas بهتنهایی کدها را میخورد |
| `OCR_DPI` | `150` | اندازه گلیف نزدیک به داده آموزش Tesseract؛ برای چاپ ریز ۲۰۰–۳۰۰ |
| `OCR_TIMEOUT` | `120` ثانیه | صفحه گیرکرده، وظیفه را برای همیشه نگه نمیدارد |
| `OCR_MAX_PAGES` | `20` | سند بزرگتر صریحاً رد میشود، نه نیمه Indexشده |
| `OCR_PAGE_BATCH` | `4` (ثابت در کد) | حداکثر چهار تصویر A4 در حافظه در هر لحظه |

OCR در **Celery worker** اجرا میشود، نه در فرآیند وب: Tesseract CPU-intensive است و worker با `concurrency=1` عمداً تک رشته است تا با بار Embedding رقابت نکند. پیشنمایش (`documents/preview.py`) دوباره OCR نمیکند؛ برای تصویر و PDF کاملاً اسکنشده متن Chunkهای ذخیرهشده را نشان میدهد (در PDF مختلط فقط صفحات متنی).

متن خروجی وارد همان `chunk_text` معمولی (۴۰۰ توکن، ۱۰٪ همپوشانی) میشود، بنابراین جستوجوی کلیدواژه و Embedding هیچ تغییری نمیکنند — فقط ورودی آنها از تصویر میآید.

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

> فایل‌های جدولی (`.xlsx`، `.csv`) به این تابع نمی‌رسند: `process_document` برای آن‌ها `extract_tabular_rows` را صدا می‌زند و هر ردیف خودش یک Chunk است (بخش ۳).

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

### پاک‌سازی نسخهٔ قبلی (Cleanup)

وقتی مرحلهٔ ۶ وضعیت را به `Indexed` می‌رساند، همان‌جا در انتهای تراکنش:

```python
if document.parent_document_id is not None:
    transaction.on_commit(
        lambda: cleanup_superseded_document.delay(document_id)
    )
```

`documents/cleanup.py` → `purge_superseded_versions`، برای هر جدِ آرشیوشده:

| مرحله | عملیات | چرا |
|---|---|---|
| ۱ | `select_for_update` روی ردیف سند | اگر بین خواندن زنجیره و پاک‌سازی نسخه برگردد، پاک نمی‌کنیم |
| ۲ | `DocumentChunk.update(is_active=False, purged_at=now)` | متن برای Citationهای قدیمی می‌ماند، از ایندکس بیرون می‌رود |
| ۳ | `Embedding.objects.filter(chunk__document_id=...).delete()` | تنها چیزی که می‌تواند متن منسوخ را زنده کند |
| ۴ | `Document.purged_at` فقط اگر `NULL` باشد | «از کِی از ایندکس بیرون است؟» یک جواب دارد؛ retry آن را جابه‌جا نمی‌کند |

سه تصمیم که باید سر جایش بماند:

1. **زمان اجرا `Indexed` است، نه لحظهٔ آپلود.** اگر هنگام آپلود پاک می‌کردیم، ایندکس نسخهٔ قدیمی قبل از آماده‌شدن نسخهٔ جدید نابود می‌شد و یک استخراج ناموفق دپارتمان را بی‌محتوا می‌گذاشت.
2. **Chunk حذف نمی‌شود، کنار گذاشته می‌شود.** `build_citations` منبع هر پاسخ را با `chunk_id` پیدا می‌کند؛ حذف سطر یعنی Citation پاسخ‌های قبلی خالی شود.
3. **حذف Embedding در هر اجرا تکرار می‌شود، حتی روی نسخهٔ قبلاً پاک‌شده.** یک batch که هنگام پاک‌سازی در حال اجرا بوده می‌تواند بعد از آن بردار بنویسد. این تکرار تنها چیزی است که آن بردار را می‌گیرد.

سه محافظ وظیفه:

| شرط | نتیجه |
|---|---|
| سند دیگر وجود ندارد | `{"skipped": "missing"}` |
| سند `Indexed` نیست (پردازش شکست خورد یا خودش منسوخ شد) | `{"skipped": "not_indexed"}` — پاک‌سازی نسخهٔ بعدی این فاصله را پر می‌کند |
| نسخه در این فاصله از آرشیو برگشته | `{"skipped": "not_archived"}` |

و یک بهینه‌سازی: آپلود اول (`parent_document_id is None`) هیچ وظیفه‌ای صف نمی‌کند، وگرنه به تعداد تمام سندهای پلتفرم وظیفهٔ بی‌اثر در صف می‌نشست.

زنجیره به‌طور کامل پیموده می‌شود، نه فقط والد بلافاصله: اگر یک پیام Celery گم شود، پاک‌سازی نسخهٔ بعدی نسخه‌های جامانده را هم جمع می‌کند و نیازی به job ترمیمی جداگانه نیست.

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
2. MIME مجاز را در `ALLOWED_FILE_TYPES` و نگاشت پسوند را در `EXTENSION_FILE_TYPES` (هر دو در `documents/filetypes.py`) اضافه کنید.
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
| حداکثر ردیف جدول | `documents/extractors/tabular.py` → `TABULAR_MAX_ROWS` (پیش‌فرض ۲۰۰۰) | هزینه Embedding یک‌به‌یک با هر ردیف بالا می‌رود |
| زبانهای OCR | `OCR_LANGUAGES` (پیشفرض `fas+eng`) | بسته fas را حتماً در ایمیج نصب کنید |
| DPI رندر PDF | `OCR_DPI` (پیشفرض `150`) | دقت در برابر حافظه و زمان |
| بودجه صفحه OCR | `OCR_MAX_PAGES` (پیشفرض `20`) | جلوگیری از اشغال worker توسط یک سند |
| مدل Embedding | `tasks.py` + `ai_service/main.py` | باید هر دو هم‌خوان باشند (۳۸۴ بُعد) |

> اگر مدل Embedding را عوض کنید، باید همه بردارهای موجود بازسازی شوند و بُعد جدید با `VectorField` و ایندکس HNSW هم‌خوان باشد. در غیر این صورت جست‌وجو خطا می‌دهد.
