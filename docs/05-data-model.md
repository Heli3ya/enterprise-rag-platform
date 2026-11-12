# ۰۵ — مدل داده

## ۱. نمای روابط

```text
Tenant 1 ──── * User
   │              │
   │              └── * Department (SET_NULL)
   │
   ├── * Department 1 ──── * Document
   │                          │
   │                          └── * DocumentChunk
   │                                 │
   │                                 └── * Embedding
   │
   ├── * SearchQuery 1 ──── * QueryResult ──── 1 DocumentChunk
   │        │
   │        └── User
   │
   ├── * ChatAnswer 1 ──── * AnswerFeedback
   │        │                    │
   │        └── User             └── User
   │
   └── * AuditLog ──── User
```

همه جداول اصلی یک `tenant_id` دارند. این ستون مرز اصلی جداسازی داده است.

## ۲. Tenant

`tenants/models.py`

| فیلد | نوع | توضیح |
|---|---|---|
| `id` | BigAutoField | کلید اصلی |
| `name` | CharField(150), unique | نام سازمان |
| `created_at` | DateTime, auto_now_add | زمان ایجاد |
| `is_active` | Boolean, default True | سازمان غیرفعال نمی‌تواند احراز هویت کند |

ترتیب پیش‌فرض: `name`.

## ۳. User

`accounts/models.py` — جایگزین `AbstractUser` (`AUTH_USER_MODEL = "accounts.User"`).

| فیلد | نوع | توضیح |
|---|---|---|
| `role` | CharField(10) | `Admin` یا `Member` (پیش‌فرض `Member`) |
| `tenant` | FK → Tenant, PROTECT, nullable | سازمان کاربر |
| `department` | FK → Department, SET_NULL, nullable | دپارتمان کاربر |
| سایر فیلدها | — | از `AbstractUser` (username، password، email، is_staff، ...) |

نکته: `ROLE_CHOICES` فقط `("Admin", "Admin")` را تعریف کرده، اما مقدار پیش‌فرض `Member` است. این ناسازگاری در سطح دیتابیس مانعی ایجاد نمی‌کند (Django فقط در فرم‌ها choices را اعمال می‌کند)، ولی باعث می‌شود `Member` در Django Admin به‌عنوان گزینه معتبر دیده نشود. جزئیات در [13-known-issues.md](13-known-issues.md).

## ۴. Department

`departments/models.py`

| فیلد | نوع | توضیح |
|---|---|---|
| `tenant` | FK → Tenant, PROTECT | اجباری |
| `name` | CharField(100) | نام دپارتمان |
| `description` | TextField, nullable | توضیح |
| `created_at` | DateTime | — |

قید: `UNIQUE (tenant, name)` با نام `unique_department_name_per_tenant`.

## ۵. Document

`documents/models.py`

| فیلد | نوع | توضیح |
|---|---|---|
| `tenant` | FK → Tenant, PROTECT, nullable | سازمان سند |
| `title` | CharField(255) | عنوان |
| `file_size` | PositiveBigInteger | بایت |
| `file_path` | FileField | مسیر ذخیره‌سازی |
| `file_type` | CharField(20) | MIME واقعی |
| `status` | CharField(20) | `Pending` / `Processing` / `Indexed` / `Failed` |
| `uploaded_by` | FK → User, CASCADE | آپلودکننده |
| `department` | FK → Department, CASCADE | دپارتمان مالک |
| `is_public` | Boolean, default False | قابل مشاهده برای همه دپارتمان‌های Tenant |
| `is_system` | Boolean, default False | سند تولیدشده توسط پلتفرم (راهنمای دپارتمان) |
| `created_at` | DateTime | — |

### `is_system`

سندی که پلتفرم خودش می‌سازد (فعلاً فقط سند راهنمای دپارتمان) با `is_system=True` علامت می‌خورد. این پرچم یک فیلد واقعی است و نه یک حدس بر اساس عنوان، چون سه تصمیم به آن وابسته است:

1. `GET /api/departments/readiness/` این اسناد را در `document_count` نمی‌شمارد؛ وگرنه هیچ دپارتمانی «خالی» نمی‌شد و Empty State هرگز نمایش داده نمی‌شد.
2. آمار داشبورد ادمین (`/api/admin/analytics/`) این اسناد را در تعداد و حجم اسناد حساب نمی‌کند.
3. رابط کاربری به‌جای دکمه حذف، نشان «System guide» نشان می‌دهد تا کاربر راهنمای شروع سرد را پاک نکند.

این سندها مثل هر سند دیگری Chunk و Embedding دارند و در جست‌وجو و استناد کاملاً عادی شرکت می‌کنند.

### مسیر ذخیره فایل

```python
f"documents/tenant_{instance.tenant_id}/{safe_filename}"
```

- فقط نام فایل نگه داشته می‌شود؛ مسیرهای ارسالی کاربر حذف می‌شوند (`\` و `/` نرمال‌سازی می‌شوند).
- اگر `tenant_id` خالی باشد، خطا می‌دهد.
- نام فایل یکتا نمی‌شود؛ دو سند با نام یکسان در یک Tenant می‌توانند فایل را بازنویسی کنند. این ریسک در [13-known-issues.md](13-known-issues.md) ثبت شده است.

## ۶. DocumentChunk

| فیلد | نوع | توضیح |
|---|---|---|
| `document` | FK → Document, CASCADE | سند مالک |
| `content` | TextField | متن Chunk |
| `chunk_index` | PositiveInteger | ترتیب صفر-مبنا |

قیدها و ایندکس‌ها:

- `UNIQUE (document, chunk_index)` — `unique_document_chunk_index`
- `GIN (to_tsvector('simple', content))` — `documentchunk_content_fts_idx`
- ترتیب پیش‌فرض: `chunk_index`

## ۷. Embedding

| فیلد | نوع | توضیح |
|---|---|---|
| `chunk` | FK → DocumentChunk, CASCADE | Chunk مالک |
| `embedding_vector` | `VectorField(384)` | بردار ۳۸۴ بُعدی |
| `model_name` | CharField(100) | فعلاً همیشه `intfloat/multilingual-e5-small` |
| `created_at` | DateTime | — |

ایندکس:

```python
HnswIndex(
    name="embedding_vector_hnsw_idx",
    fields=["embedding_vector"],
    m=16,
    ef_construction=64,
    opclasses=["vector_cosine_ops"],
)
```

- `m=16` تعادل حافظه/کیفیت برای شروع است.
- `vector_cosine_ops` با عملگر `<=>` در کوئری سرویس AI هم‌خوان است.
- هیچ قید یکتایی روی `chunk` وجود ندارد؛ بنابراین امکان Embedding تکراری هست.

## ۸. SearchQuery و QueryResult

`SearchQuery`

| فیلد | نوع | توضیح |
|---|---|---|
| `tenant` | FK → Tenant, PROTECT, nullable | سازمان |
| `user` | FK → User, CASCADE | جست‌وجوکننده |
| `query_text` | TextField | متن پرسش |
| `created_at` | DateTime | ایندکس `searchquery_created_idx` روی `-created_at` |

`QueryResult`

| فیلد | نوع | توضیح |
|---|---|---|
| `query` | FK → SearchQuery, CASCADE | جست‌وجوی والد |
| `chunk` | FK → DocumentChunk, CASCADE | نتیجه |
| `relevance_score` | Float | امتیاز Rerank |

این دو مدل فقط در `POST /api/query/search/` نوشته می‌شوند. `POST /api/search/` چیزی ذخیره نمی‌کند و چت از این دو جدول استفاده نمی‌کند؛ تاریخچه چت در `ChatAnswer` نگه داشته می‌شود.

## ۹. ChatAnswer و AnswerFeedback

`api/models.py`

`ChatAnswer` — یک پاسخ تولیدشده، برای بازخورد و آموزش آینده:

| فیلد | نوع | توضیح |
|---|---|---|
| `id` | UUIDField, PK | از پیش تولید می‌شود تا در رویداد `meta` به کلاینت برسد |
| `tenant` | FK → Tenant, PROTECT, nullable | سازمان |
| `user` | FK → User, CASCADE | صاحب پاسخ |
| `conversation_id` | CharField(255) | شناسه مکالمه سمت کلاینت (بدون جدول مستقل) |
| `question` | TextField | پرسش کاربر |
| `answer` | TextField | متن کامل پاسخ (در جریان‌سازی، تجمعی) |
| `citations` | JSONField | همان آرایه‌ای که به کلاینت داده شد |
| `is_complete` | Boolean | `False` یعنی جریان نیمه‌کاره قطع/خطا شده و برای آموزش معتبر نیست |
| `created_at` | DateTime | — |

ایندکس‌ها: `(tenant, -created_at)` و `(tenant, conversation_id)`. ترتیب: `-created_at, -id`.

`AnswerFeedback` — رأی یک کاربر روی یک پاسخ:

| فیلد | نوع | توضیح |
|---|---|---|
| `answer` | FK → ChatAnswer, CASCADE | پاسخ مورد نظر |
| `user` | FK → User, CASCADE | بازخورددهنده |
| `tenant` | FK → Tenant, PROTECT, nullable | برای گزارش‌گیری بدون join |
| `is_positive` | Boolean | `True` = مفید |
| `user_comment` | TextField, blank | متن آزاد، حداکثر ۲۰۰۰ کاراکتر در لایه API |
| `created_at` | DateTime | — |

قید یکتایی `unique_feedback_per_user_answer` روی `(answer, user)` — تضمین واقعی «یک بازخورد به‌ازای هر کاربر برای هر پاسخ». بررسی وجود رکورد در View فقط مسیر سریع است؛ در درخواست هم‌زمان، دیتابیس تصمیم نهایی را می‌گیرد و `IntegrityError` به `409` تبدیل می‌شود.

ایندکس‌ها: `(tenant, -created_at)` و `(tenant, is_positive)`.

> چرا به `QueryResult` وصل نشد؟ `QueryResult` یک ردیف «امتیاز ارتباط Chunk با پرسش» است و نه پاسخ مدل؛ نه متن پاسخ دارد و نه شناسه یکتای پاسخ. برای Fine-tuning به جفت «پرسش + پاسخ» نیاز است، پس `ChatAnswer` ساخته شد و بازخورد به آن وصل می‌شود.

## ۱۰. AuditLog

`api/models.py`

| فیلد | نوع | توضیح |
|---|---|---|
| `tenant` | FK → Tenant, PROTECT, nullable | سازمان |
| `user` | FK → User, SET_NULL, nullable | کاربر (با حذف کاربر، لاگ می‌ماند) |
| `action` | CharField(50) | `UPLOAD`، `DELETE`، `SEARCH`، `RAG_QUERY` |
| `timestamp` | DateTime, auto_now_add | ایندکس‌دار |

ایندکس ترکیبی: `(user, -timestamp)` با نام `audit_user_time_idx`. ترتیب: `-timestamp, -id`.

محدودیت: هیچ IP، User-Agent، شناسه سند یا جزئیات دیگری ثبت نمی‌شود.

## ۱۱. RateLimitConfig

| فیلد | نوع | پیش‌فرض |
|---|---|---|
| `member_chat_requests_per_hour` | PositiveInteger | 50 |
| `admin_chat_requests_per_hour` | PositiveInteger | 200 |
| `updated_at` | DateTime | — |

این مدل **Singleton** است: در `save()` مقدار `pk = 1` اجباری می‌شود. throttle مقدار آن را ۶۰ ثانیه در Redis کش می‌کند؛ تغییر مقدار حداکثر تا یک دقیقه بعد اثر می‌گذارد.

## ۱۲. قواعد حذف

| حذف | اثر |
|---|---|
| Tenant | به‌دلیل `PROTECT` روی User/Document/Department/SearchQuery/AuditLog جلوگیری می‌شود |
| User | Document، SearchQuery و QueryResult حذف می‌شوند؛ `AuditLog.user` تهی می‌شود |
| Department | Documentها حذف می‌شوند (CASCADE)؛ `User.department` تهی می‌شود |
| Document | Chunkها و در نتیجه Embeddingها حذف می‌شوند |
| DocumentChunk | Embeddingها و QueryResultها حذف می‌شوند |

نکته: حذف از مسیر API فایل فیزیکی را هم پاک می‌کند (`perform_destroy`). حذف از Django Admin یا shell فایل را روی دیسک باقی می‌گذارد.

## ۱۳. مهاجرت‌ها

| اپ | مهاجرت‌های شاخص |
|---|---|
| `tenants` | `0001_initial` |
| `accounts` | `0002_user_tenant_alter_user_role`، `0003_assign_user_tenants` |
| `departments` | `0002_department_tenant`، `0003_assign_default_tenant`، `0004_alter_department_name_alter_department_tenant_and_more` |
| `documents` | `0003_embedding`، `0005_add_embedding_hnsw_index`، `0006_add_documentchunk_fts_index`، `0011_document_tenant_searchquery_tenant`، `0013_alter_document_file_path` |
| `api` | `0002_ratelimitconfig`، `0003_auditlog_tenant`، `0004_assign_auditlog_tenants`، `0005_chatanswer_answerfeedback_and_more` |

مهاجرت‌های `assign_*` برای مهاجرت داده‌های قدیمی به مدل چند-مستأجری نوشته شده‌اند. در محیط تازه، این‌ها معمولاً کاری انجام نمی‌دهند.

### اجرای مهاجرت

```bash
python manage.py migrate
python manage.py showmigrations
```

در Docker، سرویس `django` هنگام بالا آمدن `migrate --noinput` را اجرا می‌کند. سرویس `celery_worker` این کار را نمی‌کند؛ پس ترتیب بالا آمدن مهم است.

## ۱۴. نکات عملیاتی پایگاه داده

- افزونه `vector` باید در دیتابیس ساخته شود (`CREATE EXTENSION IF NOT EXISTS vector;`). فایل `docker/postgres/init.sql` همین کار را در اولین راه‌اندازی انجام می‌دهد.
- برای تست‌ها، Django از یک دیتابیس Template به نام `enterprise_rag_test_template` استفاده می‌کند که باید از قبل ساخته شده و افزونه در آن نصب باشد.
- ایندکس HNSW در زمان درج هزینه دارد؛ برای بازسازی انبوه، به‌صورت دسته‌ای وارد کنید.
- `VACUUM ANALYZE` دوره‌ای برای حفظ کیفیت برنامه اجرای جست‌وجو مفید است.
