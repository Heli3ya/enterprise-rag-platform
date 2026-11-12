# ۰۴ — مرجع API

## ۱. قواعد کلی

| موضوع | مقدار |
|---|---|
| Base URL (توسعه) | `http://127.0.0.1:8000/api` |
| Base URL (Docker) | `http://127.0.0.1:8000/api` |
| احراز هویت | `Authorization: Bearer <access_token>` |
| Content-Type | `application/json` (به‌جز آپلود: `multipart/form-data`) |
| صفحه‌بندی | ندارد؛ لیست‌ها کامل برگردانده می‌شوند |
| مستندات تعاملی | `GET /api/docs/` و `GET /api/schema/` |
| متریک‌ها | `GET /metrics/` |

### مدل خطا

دو شکل خطا وجود دارد:

- خطاهای DRF (اعتبارسنجی، مجوز، احراز هویت): `{"detail": "..."}` یا `{"field": ["..."]}`
- خطاهای سفارشی Viewها: `{"error": "..."}`

| کد | معنا در این پروژه |
|---|---|
| 400 | ورودی نامعتبر (طول، فرمت تاریخ، `chunk_ids` خالی) |
| 401 | توکن نامعتبر/منقضی، کاربر بدون Tenant، Tenant غیرفعال |
| 403 | نقش کافی نیست، دپارتمان نامرتبط، عدم دسترسی به سند |
| 404 | سند یا Chunk یافت نشد |
| 409 | بازخورد تکراری برای همان پاسخ |
| 429 | محدودیت نرخ (چت، آپلود، Nginx) |
| 502 | خطا در سرویس AI یا LLM |
| 500 | خطای پیش‌بینی‌نشده |

### محدودیت‌های نرخ

| مسیر | محدودیت | لایه |
|---|---|---|
| `POST /api/chat/ask/` | ۵۰ در ساعت (Member)، ۲۰۰ در ساعت (Admin) | DRF Throttle + `RateLimitConfig` |
| `POST /api/chat/feedback/` | ۶۰ در ساعت به‌ازای هر کاربر | DRF Throttle (`feedback`) |
| `POST /api/documents/` | ۱۰ در ساعت به‌ازای هر کاربر | django-ratelimit |
| `/api/documents/` (همه متدها) | ۱۰ درخواست/ثانیه + ۲ POST/دقیقه به‌ازای IP | Nginx |
| سایر `/api/` | ۱۰ درخواست/ثانیه به‌ازای IP | Nginx |

## ۲. احراز هویت

### `POST /api/auth/login/`

بدون احراز هویت. بدنه:

```json
{"username": "admin", "password": "secret"}
```

پاسخ `200`:

```json
{
  "refresh": "eyJ...",
  "access": "eyJ..."
}
```

خطا: `401` برای اعتبارنامه نادرست.

> در تنظیمات فعلی `SIMPLE_JWT` تعریف نشده است؛ بنابراین مقادیر پیش‌فرض کتابخانه اعمال می‌شود: access پنج دقیقه و refresh یک روز.

### `POST /api/auth/refresh/`

```json
{"refresh": "eyJ..."}
```

پاسخ `200`:

```json
{"access": "eyJ..."}
```

### `GET /api/auth/me/`

نیازمند احراز هویت. پاسخ `200`:

```json
{
  "id": 3,
  "username": "admin",
  "role": "Admin",
  "department_id": 1,
  "department_name": "IT"
}
```

> این پاسخ عمداً `tenant` را برنمی‌گرداند. اگر فرانت‌اند به نام سازمان نیاز دارد، باید endpoint یا فیلد اضافه شود.

## ۳. دپارتمان‌ها

### `GET /api/departments/`

هر کاربر احراز هویت‌شده. فقط دپارتمان‌های Tenant خودش.

```json
[
  {"id": 1, "name": "IT", "description": "Technical", "created_at": "2026-01-01T10:00:00Z"}
]
```

### `POST /api/departments/create/`

فقط `Admin`. `tenant` به‌صورت خودکار از کاربر گرفته می‌شود.

```json
{"name": "HR", "description": "Human Resources"}
```

پاسخ `201` با شیء دپارتمان.

هنگام ساخت دپارتمان، یک سند راهنمای خودکار هم برای آن ساخته می‌شود (بخش «سند راهنمای خودکار» در [`06-document-pipeline.md`](06-document-pipeline.md)). این کار در تراکنش جدا و بدون دخالت کلاینت انجام می‌شود و اگر شکست بخورد، ساخت دپارتمان را خراب نمی‌کند.

### `GET /api/departments/readiness/`

هر کاربر احراز هویت‌شده با دپارتمان. یک کاوش ارزان (سه کوئری محدود، بدون فراخوانی سرویس AI) برای تصمیم‌گیری داشبورد بین «شروع از صفر» و «پایگاه دانش آماده است».

```json
{
  "department_id": 1,
  "department_name": "IT",
  "document_count": 0,
  "has_searchable_content": true,
  "is_empty": true,
  "onboarding_document_id": 41
}
```

| فیلد | معنی |
|---|---|
| `document_count` | تعداد اسناد **کاربر**؛ سند راهنمای خودکار شمرده نمی‌شود |
| `has_searchable_content` | آیا دپارتمان حتی یک Chunk دارد؟ (سند راهنما هم Chunk دارد) |
| `is_empty` | `document_count == 0` — مبنای نمایش Empty State |
| `onboarding_document_id` | شناسه سند راهنما، یا `null` اگر دپارتمان قدیمی هنوز backfill نشده باشد |

تفکیک `is_empty` از `has_searchable_content` عمدی است: دپارتمان تازه‌ساز با سند راهنما «خالی» است ولی «بی‌پاسخ» نیست.

خطاها: `401` بدون احراز هویت، `403` اگر کاربر Tenant یا دپارتمان نداشته باشد.

## ۴. اسناد

### `GET /api/documents/`

کاربر باید عضو یک دپارتمان باشد (`IsDepartmentMember`). لیست اسناد **همه دپارتمان‌های Tenant** را برمی‌گرداند، نه فقط دپارتمان کاربر.

```json
[
  {
    "id": 12,
    "title": "Employee Handbook",
    "department": 1,
    "status": "Indexed",
    "created_at": "2026-01-02T08:30:00Z",
    "is_system": false
  }
]
```

`is_system: true` یعنی سند را پلتفرم ساخته است (سند راهنمای دپارتمان). چنین سندی در رابط کاربری نشان «System guide» می‌گیرد و دکمه حذف ندارد؛ در `document_count` مربوط به readiness و در آمار داشبورد ادمین هم شمرده نمی‌شود.

### `POST /api/documents/`

`multipart/form-data`:

| فیلد | نوع | الزامی | توضیح |
|---|---|---|---|
| `title` | string | بله | عنوان غیرخالی |
| `department` | int | بله | شناسه دپارتمان در همان Tenant |
| `file_path` | file | بله | حداکثر ۵ مگابایت |

نوع مجاز بر اساس MIME واقعی:

- `application/pdf`
- `text/plain`
- `application/msword`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`

قواعد مجوز:

- کاربر بدون Tenant → `403`
- دپارتمان متعلق به Tenant دیگر → `403`
- کاربر عضو دپارتمان نباشد و Admin نباشد → `403`

پاسخ `201`:

```json
{"document_id": 12, "status": "Pending"}
```

پس از پاسخ، پردازش در Celery آغاز می‌شود.

نمونه:

```bash
curl -X POST http://127.0.0.1:8000/api/documents/ \
  -H "Authorization: Bearer $TOKEN" \
  -F "title=Employee Handbook" \
  -F "department=1" \
  -F "file_path=@handbook.pdf"
```

### `GET /api/documents/{id}/`

وضعیت سند. `Admin` هر سند Tenant را می‌بیند؛ `Member` فقط اسناد دپارتمان خودش را.

```json
{
  "id": 12,
  "title": "Employee Handbook",
  "file_type": "application/pdf",
  "status": "Indexed",
  "department": 1,
  "uploaded_by": 3,
  "created_at": "2026-01-02T08:30:00Z"
}
```

مقادیر `status`: `Pending` | `Processing` | `Indexed` | `Failed`

### `DELETE /api/documents/{id}/delete/`

آپلودکننده یا `Admin`. فایل فیزیکی و رکورد (به‌همراه Chunkها و Embeddingها با CASCADE) حذف می‌شود. پاسخ `204`.

### `GET /api/documents/chunks/{chunk_id}/`

جزئیات یک Chunk ارجاع‌داده‌شده. این endpoint پشت «Clickable Citations» است: وقتی کاربر روی `[93]` در پاسخ کلیک می‌کند، همین مسیر متن دقیقِ بازیابی‌شده و سند مبدأ را برمی‌گرداند.

قواعد دسترسی عیناً مثل جست‌وجو است: همان Tenant، و برای `Member` همان دپارتمان؛ `Admin` همه دپارتمان‌های Tenant خودش را می‌بیند.

پارامتر اختیاری `q`: همان سؤالی که این ارجاع را تولید کرده. اگر بفرستید، بخش‌های منطبق با سؤال داخل `content` علامت‌گذاری می‌شوند.

```bash
curl -G http://127.0.0.1:8000/api/documents/chunks/93/ \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "q=کد ORBIT-742 چیست؟"
```

```json
{
  "chunk_id": 93,
  "chunk_index": 0,
  "content": "The unique project verification code is ORBIT-742.",
  "document_id": 30,
  "document_title": "e2e-rag-test.txt",
  "filename": "e2e-rag-test.txt",
  "file_type": "text/plain",
  "file_url": "/documents/30/file/",
  "preview_url": "/documents/30/preview/",
  "department": "IT",
  "department_id": 1,
  "is_public": false,
  "uploaded_by": "heliya",
  "created_at": "2026-11-07T09:12:44Z",
  "highlights": [[40, 49]],
  "matched_terms": ["orbit", "742"]
}
```

| فیلد | توضیح |
| --- | --- |
| `highlights` | آرایه‌ای از `[start, end)` روی `content`؛ آماده برای `<mark>` در فرانت‌اند |
| `matched_terms` | واژه‌های سؤال که واقعاً در متن پیدا شدند (برای نمایش «Highlighted: …») |

نکات:

- محاسبه در بک‌اند انجام می‌شود تا توکن‌بندی، حذف stopword و نرمال‌سازی حروف عربی/فارسی (`ي`→`ی`، `ك`→`ک`) یک‌جا و یکسان با جست‌وجو بماند.
- بازه‌های هم‌پوشان ادغام می‌شوند؛ دو تکهٔ یک شناسه که فقط با `-` جدا شده‌اند (مثل `ORBIT` و `742`) یک هایلایت واحد می‌شوند.
- اگر سؤال واژه‌ای نداشته باشد یا هیچ واژه‌ای در متن نباشد (مثلاً تطابق صرفاً معنایی)، هر دو فیلد آرایه خالی برمی‌گردانند و متن ساده نمایش داده می‌شود.

پاسخ‌ها: `200` موفق، `401` بدون توکن، `403` دپارتمان دیگر، `404` Chunk ناموجود یا Tenant دیگر.

`file_url` و `preview_url` مسیر **نسبی به ریشه API** هستند، نه به ریشه دامنه. یعنی فرانت‌اند باید `NEXT_PUBLIC_API_BASE_URL` (که خودش به `/api` ختم می‌شود) را جلوی آن‌ها بگذارد:

```text
http://127.0.0.1:8000/api  +  /documents/30/file/  =  http://127.0.0.1:8000/api/documents/30/file/
```

اگر این مسیرها با `/api` برمی‌گشتند، نتیجه `.../api/api/documents/...` و خطای `404` بود.

### `GET /api/documents/{id}/preview/?q=`

متن استخراج‌شدهٔ **کل سند** به‌همراه هایلایت همهٔ بخش‌های منطبق با `q`. برای سندهایی است که مرورگر خودش نمی‌تواند نمایش دهد (PDF/DOCX) یا وقتی کاربر می‌خواهد ببیند مطلب در کجای فایل آمده.

```json
{
  "document_id": 30,
  "title": "e2e-rag-test.txt",
  "filename": "e2e-rag-test.txt",
  "file_type": "text/plain",
  "file_url": "/documents/30/file/",
  "department": "IT",
  "content": "E2E RAG Integration Test\n\nThe unique project verification code is ORBIT-742.\n...",
  "highlights": [[55, 64], [103, 112]],
  "matched_terms": ["orbit", "742"],
  "truncated": false
}
```

- استخراج متن از همان ماژول‌های pipeline انجام می‌شود (`documents/extractors/`)، پس با متن ایندکس‌شده یکی است.
- سقف ۱۲۰٬۰۰۰ کاراکتر؛ اگر سند بلندتر باشد `truncated: true` برمی‌گردد و UI پیام می‌دهد.
- `highlights` روی **همهٔ** تکرارها محاسبه می‌شود، نه فقط اولین مورد.

پاسخ‌ها: `200`، `401`، `403` (دپارتمان دیگر)، `404` (سند یا فایل موجود نیست)، `415` (نوع فایل قابل استخراج نیست).

### `GET /api/documents/{id}/file/`

فایل اصلی سند را با احراز هویت برمی‌گرداند (`FileResponse`). مسیر عمومی `/media/` برای این کار استفاده نمی‌شود، چون هر کسی با حدس زدن مسیر می‌توانست اسناد Tenantها را بخواند.

هدرها:

| هدر | مقدار |
| --- | --- |
| `Content-Type` | `file_type` ذخیره‌شده یا نتیجه `mimetypes` |
| `Content-Disposition` | `inline; filename*=UTF-8''<name>` |
| `X-Content-Type-Options` | `nosniff` |
| `Content-Security-Policy` | `sandbox` |

پاسخ‌ها: `200`، `401`، `403` (دپارتمان دیگر)، `404` (سند ناموجود یا فایل حذف‌شده از دیسک).

## ۵. جست‌وجو

### `POST /api/search/`

جست‌وجوی سریع بدون ذخیره تاریخچه. بدنه:

```json
{"query": "remote work policy"}
```

پاسخ `200`:

```json
{
  "query": "remote work policy",
  "results": [
    {
      "document_id": 12,
      "document_title": "Employee Handbook",
      "chunk_id": 340,
      "chunk_index": 7,
      "score": 0.812345,
      "content": "Employees may work remotely up to two days per week..."
    }
  ]
}
```

نکته: `score` در این endpoint امتیاز ادغام‌شده است، نه امتیاز Rerank. حداکثر ۵ نتیجه برگردانده می‌شود.

اگر دپارتمان کاربر هیچ Chunk قابل جست‌وجو نداشته باشد (شروع سرد)، پاسخ همان `{"query": ..., "results": []}` است اما سرویس AI **فراخوانی نمی‌شود**: Embedding پرسش ساخته نمی‌شود چون نتیجه‌اش تغییرناپذیر است.

### `POST /api/query/search/`

جست‌وجوی کامل با ذخیره تاریخچه و Audit. بدنه:

```json
{"query_text": "remote work policy", "top_k": 5}
```

محدودیت‌ها: `query_text` حداکثر ۱۰۰۰ کاراکتر، `top_k` بین ۱ و ۵۰ (پیش‌فرض ۵).

پاسخ `200`:

```json
{
  "query_text": "remote work policy",
  "results": [
    {
      "chunk_id": 340,
      "document_id": 12,
      "document_title": "Employee Handbook",
      "score": 0.93421,
      "content": "Employees may work remotely up to two days per week..."
    }
  ]
}
```

نتایجی که Reranker امتیازشان را برنگردانده (`rerank_score == MISSING_RERANK_SCORE`) حذف می‌شوند. فیلتر `rerank_score > 0` عمداً استفاده نمی‌شود: امتیاز cross-encoder یک logit خام است و برای تطابق‌های معتبر هم منفی می‌شود، پس آن فیلتر همهٔ نتایج را دور می‌ریخت. در صورت موفقیت، `SearchQuery`، `QueryResult`ها و `AuditLog(SEARCH)` ثبت می‌شوند.

در دپارتمان بدون Chunk، سرویس AI فراخوانی نمی‌شود و `results` خالی است؛ با این حال `SearchQuery` با صفر `QueryResult` ثبت می‌شود تا آمار جست‌وجو ناقص نماند.

### `POST /api/query/ask/`

پاسخ RAG کامل (غیرجریانی). بدنه همان `SearchQuerySerializer`:

```json
{"query_text": "How many remote days are allowed?", "top_k": 5}
```

پاسخ `200`:

```json
{
  "query_text": "How many remote days are allowed?",
  "answer": "Employees may work remotely up to two days per week [340].",
  "answer_id": "0f3a6f0e-5b6f-4f0e-9f0e-1c2b3a4d5e6f",
  "no_documents": false,
  "reason": null,
  "citations": [
    {
      "document_id": 12,
      "title": "Employee Handbook",
      "filename": "handbook.pdf",
      "department": "IT",
      "chunk_id": 340,
      "chunk_index": 7,
      "snippet": "Employees may work remotely up to two days per week..."
    }
  ]
}
```

`answer_id` همان شناسه‌ای است که برای ثبت بازخورد در `POST /api/chat/feedback/` لازم است.

اگر چیزی برای پاسخ‌دادن نباشد (`no_documents: true`)، مدل زبانی **فراخوانی نمی‌شود**، پاسخ ذخیره نمی‌شود و `answer_id` برابر `null` است:

```json
{
  "query_text": "What is the parental leave policy?",
  "answer": "در حال حاضر سندی مرتبط با این موضوع در دپارتمان شما یافت نشد.",
  "citations": [],
  "answer_id": null,
  "no_documents": true,
  "reason": "empty_department"
}
```

`reason` یکی از دو مقدار است: `empty_department` (دپارتمان هیچ Chunk ندارد) یا `no_match` (Chunk وجود دارد ولی هیچ‌کدام به پرسش مربوط نبود). متن `answer` برای کلاینت‌های غیرمرورگری است؛ رابط کاربری پیام خودش را بر اساس `reason` و زبان انتخابی می‌سازد.

### `POST /api/chat/ask/`

پاسخ جریانی با SSE. بدنه:

```json
{"question": "How many remote days are allowed?", "conversation_id": "conversation-123"}
```

`conversation_id` اجباری است و همراه پاسخ ذخیره می‌شود تا بازخوردها و پاسخ‌ها به یک مکالمه قابل انتساب باشند.

پاسخ: `Content-Type: text/event-stream`

```text
event: meta
data: {"answer_id":"0f3a6f0e-5b6f-4f0e-9f0e-1c2b3a4d5e6f","conversation_id":"conversation-123"}

event: token
data: {"content":"Employees "}

event: token
data: {"content":"may work "}

event: citations
data: [{"document_id":12,"title":"Employee Handbook","filename":"handbook.pdf","department":"IT","chunk_id":340,"chunk_index":7,"snippet":"Employees may work remotely up to two days per week..."}]

event: done
data: {}
```

اولین رویداد همیشه `meta` است و `answer_id` را پیش از رسیدن نخستین توکن می‌دهد تا رابط کاربری بتواند از همان لحظه دکمه‌های بازخورد را به پاسخ متصل کند. پاسخ فقط پس از پایان جریان (و پیش از ارسال `done`) در جدول `ChatAnswer` نوشته می‌شود؛ اگر اتصال وسط کار قطع شود یا خطا رخ دهد، متن ناقص با `is_complete=False` ذخیره می‌شود.

#### رویداد `no_documents` (شروع سرد)

اگر دپارتمان هیچ Chunk قابل جست‌وجو نداشته باشد، یا هیچ Chunkی به پرسش مربوط نباشد، جریان به‌جای `token`/`citations` فقط یک رویداد `no_documents` و سپس `done` می‌فرستد. مدل زبانی و حتی Embedding پرسش فراخوانی نمی‌شود و هیچ ردیفی در `ChatAnswer` نوشته نمی‌شود، پس `answer_id` آمده در `meta` قابل ثبت بازخورد نیست.

```text
event: meta
data: {"answer_id":"...","conversation_id":"conversation-123"}

event: no_documents
data: {"reason":"empty_department","message":"در حال حاضر سندی مرتبط با این موضوع در دپارتمان شما یافت نشد."}

event: done
data: {}
```

جریان همیشه با `done` تمام می‌شود؛ کلاینت تنها بر اساس همین رویداد نشانگر «در حال فکر کردن» را خاموش می‌کند.

فیلدهای هر Citation:

| فیلد | توضیح |
| --- | --- |
| `document_id` | شناسه سند مبدأ |
| `title` | عنوان سند |
| `filename` | نام فایل (بدون مسیر ذخیره‌سازی) |
| `department` | نام دپارتمان مالک سند |
| `chunk_id` | همان عددی که داخل `[n]` در متن پاسخ آمده |
| `chunk_index` | شماره Chunk در سند (از صفر) |
| `snippet` | ۲۸۰ کاراکتر اول متن Chunk، برای پیش‌نمایش فوری |

در خطا:

```text
event: error
data: {"error":"RAG service unavailable"}
```

نمونه کلاینت:

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/ask/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"remote work policy?","conversation_id":"c-1"}'
```

> اگر پشت پراکسی هستید، بافر شدن پاسخ را غیرفعال کنید تا توکن‌ها به‌صورت زنده برسند.

### `POST /api/chat/feedback/`

ثبت بازخورد کاربر روی یک پاسخ مشخص. نیازمند احراز هویت و Tenant فعال.

بدنه:

```json
{
  "answer_id": "0f3a6f0e-5b6f-4f0e-9f0e-1c2b3a4d5e6f",
  "is_positive": true,
  "user_comment": "دقیق و کامل بود."
}
```

| فیلد | نوع | اجباری | توضیح |
| --- | --- | --- | --- |
| `answer_id` | UUID | بله | همان مقدار `answer_id` از رویداد `meta` یا پاسخ `/api/query/ask/` |
| `is_positive` | boolean | بله | `true` = مفید، `false` = نامفید |
| `user_comment` | string ≤ 2000 | خیر | متن آزاد؛ خالی و حذف‌شده هر دو مجازند |

پاسخ `201`:

```json
{
  "id": 41,
  "answer_id": "0f3a6f0e-5b6f-4f0e-9f0e-1c2b3a4d5e6f",
  "is_positive": true,
  "user_comment": "دقیق و کامل بود.",
  "created_at": "2026-11-09T14:52:10.184223Z"
}
```

| کد | حالت |
| --- | --- |
| 201 | بازخورد ثبت شد |
| 400 | `answer_id` نامعتبر، `is_positive` غایب، یا توضیح بلندتر از ۲۰۰۰ کاراکتر |
| 401 | بدون توکن |
| 403 | کاربر بدون Tenant یا Tenant غیرفعال |
| 404 | پاسخ یافت نشد (شناسه ناموجود یا متعلق به کاربر/سازمان دیگر) |
| 409 | برای این پاسخ قبلاً بازخورد ثبت شده است |
| 429 | عبور از سقف ۶۰ درخواست در ساعت |

> قاعده «یک بازخورد به‌ازای هر کاربر برای هر پاسخ» با `UniqueConstraint(answer, user)` در سطح دیتابیس تضمین می‌شود؛ بنابراین دو درخواست هم‌زمان هم نمی‌توانند دو ردیف بسازند و دومی `409` می‌گیرد.

نمونه:

```bash
curl -X POST http://127.0.0.1:8000/api/chat/feedback/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"answer_id":"0f3a6f0e-5b6f-4f0e-9f0e-1c2b3a4d5e6f","is_positive":false,"user_comment":"به بخش مرخصی اشاره نکرد."}'
```

## ۶. تولید دستی Embedding

### `POST /api/embeddings/create/`

فقط `Admin`. برای بازسازی دستی بردارها.

```json
{"chunk_ids": [340, 341, 342]}
```

پاسخ `201`:

```json
{
  "embeddings": [
    {"id": 900, "chunk_id": 340, "dimension": 384}
  ],
  "count": 1
}
```

قواعد:

- فقط Chunkهای همان Tenant پذیرفته می‌شوند.
- اگر هیچ Chunk معتبری نباشد → `404`.
- خطای سرویس AI → `502`.
- این endpoint محدودیت یکتا ندارد و می‌تواند Embedding تکراری بسازد؛ برای مسیر عادی از پردازش خودکار استفاده کنید.

## ۷. ادمین

### `GET /api/audit-logs/`

فقط `Admin`. فیلترهای اختیاری:

| پارامتر | فرمت | مثال |
|---|---|---|
| `user_id` | int | `?user_id=3` |
| `date_from` | `YYYY-MM-DD` | `?date_from=2026-01-01` |
| `date_to` | `YYYY-MM-DD` | `?date_to=2026-01-31` |

```json
[
  {"id": 88, "user": 3, "action": "SEARCH", "timestamp": "2026-01-05T12:00:00Z"}
]
```

تاریخ نامعتبر → `400`.

### `GET /api/admin/analytics/`

فقط `Admin`. پاسخ:

```json
{
  "total_documents": 42,
  "total_file_size_bytes": 104857600,
  "total_searches": 315,
  "departments": [
    {
      "department_id": 1,
      "department_name": "IT",
      "document_count": 20,
      "file_size_bytes": 52428800,
      "search_count": 180
    }
  ],
  "recent_searches": [
    {
      "id": 315,
      "username": "member1",
      "department_name": "IT",
      "query_text": "vpn setup",
      "created_at": "2026-01-05T12:00:00Z"
    }
  ]
}
```

`recent_searches` حداکثر ۱۰ مورد آخر است.

## ۸. مسیرهای سیستمی

| مسیر | توضیح |
|---|---|
| `GET /api/schema/` | OpenAPI schema خام |
| `GET /api/docs/` | Swagger UI |
| `GET /metrics/` | متریک‌های Prometheus |
| `GET /admin/` | Django Admin (Session) |

## ۹. API داخلی سرویس AI

این مسیرها روی پورت `8001` هستند، در Compose به بیرون منتشر نمی‌شوند و **احراز هویت ندارند**.

| متد | مسیر | بدنه | پاسخ |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| GET | `/api/db/test/` | — | وضعیت اتصال دیتابیس |
| POST | `/api/embed/` | `{"texts":["..."]}` | `{"embeddings":[[...]],"dimension":384}` |
| POST | `/api/vector-search/` | `{"query":"...","tenant_id":1,"allowed_department_ids":[1],"limit":5}` | لیست نتایج با `distance` |
| POST | `/api/rerank/` | `{"query":"...","results":["..."]}` | `{"results":[{"content":"...","score":0.9}]}` |
| POST | `/api/llm/` | `{"prompt":"..."}` | `{"answer":"..."}` |
| POST | `/api/llm/stream/` | `{"prompt":"..."}` | `text/plain` جریانی |

محدودیت‌های اعتبارسنجی:

- `texts` حداقل یک عضو
- `tenant_id > 0`
- `allowed_department_ids` حداقل یک عضو
- `limit` بین ۱ و ۵۰
- `results` در Rerank بین ۱ و ۵۰ عضو
