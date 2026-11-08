# ۱۲ — عیب‌یابی

## ۱. جدول سریع

| نشانه | علت احتمالی | اولین اقدام |
|---|---|---|
| `ImproperlyConfigured` / `SECRET_KEY` | `.env` نبود یا کلید خالی | `DJANGO_SECRET_KEY` را ست کنید |
| `password authentication failed` | رمز یا کاربر DB نادرست | `.env` و کاربر Postgres را هم‌خوان کنید |
| `type "vector" does not exist` | افزونه pgvector نصب نیست | از ایمیج pgvector استفاده یا `CREATE EXTENSION vector` |
| `No module named 'magic'` | libmagic نصب نیست | Docker یا نصب libmagic |
| سند در `Pending` می‌ماند | Celery یا Redis کار نمی‌کند | وضعیت worker و صف را بررسی کنید |
| سند در `Processing` می‌ماند | batch Embedding شکست خورده | لاگ Celery و سرویس AI |
| سند `Failed` می‌شود | نوع فایل، متن خالی یا خطای استخراج | لاگ worker و نوع فایل |
| جست‌وجو `502` می‌دهد | AI Service در دسترس نیست | `/health` و لاگ AI |
| پاسخ خالی از جست‌وجو | کاربر دپارتمان ندارد یا سند Indexed نیست | `/auth/me/` و وضعیت سند |
| `401` با پیام سازمان | کاربر Tenant ندارد یا Tenant غیرفعال | تخصیص Tenant در shell |
| `403` هنگام آپلود | دپارتمان مقصد با کاربر هم‌خوان نیست | دپارتمان درست یا نقش Admin |
| `429` | محدودیت نرخ | مقدار throttle و Nginx را بررسی کنید |
| SSE تکه‌تکه نمی‌رسد | بافر پراکسی | بافر را غیرفعال کنید |
| تست: Template DB نیست | دیتابیس تست ساخته نشده | `createdb ... enterprise_rag_test_template` |

## ۲. پیکربندی و بالا آمدن

### Django بالا نمی‌آید

```bash
docker compose logs --tail=200 django
```

موارد رایج:

- `DJANGO_SECRET_KEY` خالی است. `settings.py` مقدار پیش‌فرض ندارد.
- `DB_HOST` اشتباه است. در Compose باید `postgres` باشد.
- migration با خطا متوقف شده است.

بررسی پیکربندی بدون اجرای سرور:

```bash
docker compose run --rm django python manage.py check
```

### سرویس AI بالا نمی‌آید یا unhealthy است

```bash
docker compose ps -a
docker compose logs --tail=300 ai_service
```

دلایل رایج:

- دانلود مدل‌های Hugging Face در اولین اجرا (چند صد مگابایت). Healthcheck با `start_period: 10m` تنظیم شده، اما در شبکه کند ممکن است بیشتر طول بکشد.
- کمبود RAM هنگام بارگذاری `SentenceTransformer` و `CrossEncoder`.
- نبود دسترسی به Hugging Face در محیط بسته.

بررسی دستی:

```bash
docker compose exec -T ai_service \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=5).read().decode())"
```

### Ollama و مدل

```bash
docker compose --profile ollama logs --tail=200 ollama
docker compose --profile ollama logs --tail=200 ollama-model-init
```

- نام مدل در `LLM_MODEL` باید با مدلی که pull شده یکی باشد.
- `LLM_BASE_URL` در Compose باید `http://ollama:11434/api` باشد.
- فضای دیسک را بررسی کنید.

## ۳. پایگاه داده

### اتصال برقرار نمی‌شود

```bash
docker compose exec -T postgres pg_isready -U "$DB_USER" -d "$DB_NAME"
docker compose logs --tail=100 postgres
```

- `DB_HOST=postgres` (نه `localhost`) در Compose.
- رمز در `.env` و `POSTGRES_PASSWORD` باید یکی باشد.
- اگر Volume را از نسخه قبلی دارید و رمز را عوض کرده‌اید، Postgres رمز قدیمی را نگه می‌دارد. در محیط توسعه می‌توانید Volume را پاک کنید؛ در Production رمز را از داخل دیتابیس تغییر دهید.

### افزونه vector

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

```bash
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -c "\dx"
```

اگر ایمیج `postgres` معمولی استفاده کرده‌اید، pgvector ندارد. از `pgvector/pgvector:pg16` استفاده کنید.

### مهاجرت‌ها

```bash
docker compose exec django python manage.py showmigrations
docker compose exec django python manage.py migrate --plan
```

اگر migration در حالت ناسازگار است، قبل از هر کاری از دیتابیس پشتیبان بگیرید.

## ۴. پردازش سند

### سند در `Pending` می‌ماند

1. آیا worker اجرا می‌شود؟

```bash
docker compose ps celery_worker
docker compose logs --tail=100 celery_worker
```

2. آیا Redis پاسخ می‌دهد؟

```bash
docker compose exec -T redis redis-cli ping
```

3. آیا وظیفه در صف است؟

```bash
docker compose exec -T redis redis-cli -n 0 llen celery
```

4. آیا `transaction.on_commit` اجرا شده؟ اگر آپلود در یک تراکنش شکست خورده باشد، وظیفه ارسال نمی‌شود.

### سند `Failed` می‌شود

```bash
docker compose logs --tail=300 celery_worker | grep -i "document"
```

دلایل رایج:

- MIME پشتیبانی‌نشده
- PDF اسکن‌شده بدون متن
- فایل `.doc` قدیمی (python-docx از آن پشتیبانی کامل نمی‌کند)
- خطای شبکه به سرویس AI
- نبود libmagic (در مرحله آپلود، نه پردازش)

### سند در `Processing` گیر کرده

یعنی `generate_embedding_batch` شکست خورده و retryها تمام شده‌اند. لاگ را ببینید و سپس پردازش را دوباره اجرا کنید:

```bash
docker compose exec django python manage.py shell -c \
  "from documents.tasks import process_document; process_document.delay(<ID>)"
```

## ۵. جست‌وجو و RAG

### `502` از endpointهای جست‌وجو

```bash
docker compose logs --tail=200 django | grep -i "ai_service\|connection"
```

- `AI_SERVICE_URL` باید در Compose `http://ai_service:8001` باشد.
- سرویس AI ممکن است در حال بارگذاری مدل باشد.
- زمان‌بندی: `timeout=60` برای Embedding و Rerank، `timeout=120` برای LLM.

### نتیجه خالی

به ترتیب بررسی کنید:

1. `GET /api/auth/me/` → آیا `department_id` مقدار دارد؟
2. آیا سند در همان دپارتمان است؟
3. آیا `status == "Indexed"` است؟
4. آیا `Embedding` برای Chunkها وجود دارد؟
5. آیا `POST /api/vector-search/` مستقیم نتیجه می‌دهد؟

```python
from documents.models import Document, DocumentChunk, Embedding

Document.objects.filter(status="Indexed").count()
DocumentChunk.objects.count()
Embedding.objects.count()
```

### پاسخ LLM خالی یا خطا

```bash
docker compose exec -T ai_service python -c \
  "from llm_client import LLMClient; print(LLMClient().generate('Say OK'))"
```

- `LLM_PROVIDER` فقط `ollama` یا `openai_compatible` است.
- `LLM_BASE_URL` برای Ollama باید به `/api` ختم شود.
- برای ارائه‌دهنده سازگار با OpenAI، `LLM_BASE_URL` معمولاً به `/v1` ختم می‌شود.
- خطای 429 از ارائه‌دهنده به `RuntimeError("LLM rate limit exceeded")` تبدیل می‌شود.

### Citation خالی است

- LLM ممکن است شناسه‌ها را با فرمت دیگری نوشته باشد؛ فقط `[123]` شناسایی می‌شود.
- Chunk ارجاع‌شده ممکن است به Tenant یا دپارتمان دیگری تعلق داشته باشد و فیلتر شود.
- اگر پاسخ بدون citation باشد، `citations` خالی است.

## ۶. احراز هویت و مجوز

| کد | پیام | معنا |
|---|---|---|
| 401 | `Your account is not assigned to an organization.` | `User.tenant` خالی است |
| 401 | `Your organization is inactive.` | `Tenant.is_active=False` |
| 403 | `Your account is not assigned to an organization.` | مسیر View بدون Tenant |
| 403 | `Your organization is inactive or unavailable.` | Tenant غیرفعال در View |
| 403 | `You cannot upload documents to another organization.` | دپارتمان از Tenant دیگر |
| 403 | `You cannot upload documents to this department.` | کاربر عضو دپارتمان نیست |
| 403 | `Department membership is required.` | کاربر دپارتمان ندارد |

رفع:

```bash
docker compose exec django python manage.py shell
```

```python
from accounts.models import User
u = User.objects.get(username="user1")
u.tenant_id = 1
u.department_id = 1
u.save()
```

### توکن منقضی

Access پنج دقیقه اعتبار دارد. فرانت‌اند با Axios خودکار refresh می‌کند، اما مسیر چت (`fetch` مستقیم) این کار را نمی‌کند. اگر چت `401` داد، صفحه را reload کنید یا توکن را دستی refresh کنید.

## ۷. محدودیت نرخ

`429` می‌تواند از سه جا بیاید:

1. `ChatUserRateThrottle` — ۵۰/۲۰۰ در ساعت
2. `django-ratelimit` — ۱۰ آپلود در ساعت
3. Nginx — ۱۰ r/s یا ۲ POST/دقیقه

تشخیص:

- بدنه `{"detail":"Request was throttled..."}` → DRF
- بدنه `{"detail":"Upload rate limit exceeded..."}` → ratelimit
- پاسخ HTML یا `429` بدون بدنه JSON → Nginx

تنظیم چت:

```python
from api.models import RateLimitConfig
c = RateLimitConfig.objects.get(pk=1)
c.member_chat_requests_per_hour = 100
c.save()
```

حداکثر ۶۰ ثانیه بعد اثر می‌گذارد (کش).

## ۸. SSE و چت

### پاسخ یک‌جا می‌رسد

پراکسی یا CDN پاسخ را بافر می‌کند. برای Nginx:

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 360s;
```

### رویدادها درست parse نمی‌شوند

- هر رویداد با یک خط خالی (`\n\n`) جدا می‌شود.
- `data:` ممکن است در چند خط بیاید؛ کلاینت فعلی آن‌ها را به هم می‌چسباند.
- JSON باید با `ensure_ascii=False` ساخته شود (در بک‌اند همین‌طور است).

### `error` بدون `done`

طبیعی است؛ در خطا فقط `error` ارسال می‌شود.

## ۹. فرانت‌اند

| نشانه | علت | راه‌حل |
|---|---|---|
| صفحه سفید بعد از ورود | `NEXT_PUBLIC_API_BASE_URL` غلط | باید شامل `/api` باشد |
| CORS error | Origin در `CORS_ALLOWED_ORIGINS` نیست | Origin دقیق را اضافه کنید |
| ریدایرکت بی‌پایان به `/login` | `/auth/me/` خطا می‌دهد | Network tab و توکن را بررسی کنید |
| Build خطای env | متغیر در زمان Build ست نشده | قبل از `npm run build` ست کنید |
| Sentry خطا می‌دهد | DSN نامعتبر | DSN را خالی یا معتبر کنید |

## ۱۰. تست

```bash
# ساخت Template
createdb -h localhost -U postgres -T template0 enterprise_rag_test_template
psql -h localhost -U postgres -d enterprise_rag_test_template -c "CREATE EXTENSION vector;"

# اجرا
pytest -x -q
```

اگر تست‌ها به سرویس AI وابسته‌اند، mock را بررسی کنید؛ تست‌های واحد نباید شبکه بزنند.

## ۱۱. جمع‌آوری اطلاعات برای گزارش خطا

هنگام باز کردن Issue یا پرسیدن سؤال، این‌ها را ضمیمه کنید:

```bash
docker compose ps
docker compose logs --tail=200 django celery_worker ai_service
python manage.py check
python manage.py showmigrations
```

و مشخص کنید:

- نسخه کد (commit)
- سیستم‌عامل و نسخه Docker
- مرحله‌ای که خطا رخ می‌دهد
- پاسخ کامل HTTP (بدون توکن و Secret)

## ۱۲. سلامت سرویس AI و خطاهای ۵۰۳

از این نسخه، سرویس AI مدل‌ها را در پس‌زمینه بارگذاری می‌کند و دو endpoint جدا دارد:

| مسیر | معنا |
|---|---|
| `GET /health` | زنده بودن پروسه؛ تا زمانی که مدل‌ها لود شوند هم `200` می‌دهد |
| `GET /ready` | آماده بودن مدل‌ها؛ تا قبل از آن `503` |
| `GET /api/status/` | وضعیت مدل‌ها، دیتابیس و تنظیمات LLM |

سلامت کل سامانه از سمت Django:

```bash
curl -s http://localhost:8000/api/health/
```

پاسخ نمونه:

```json
{
  "status": "ok",
  "database": "connected",
  "ai_service": {"status": "connected", "detail": "models are ready"}
}
```

اگر `ai_service.status` برابر `unavailable` باشد، جست‌وجو و چت با **503** و پیام روشن پاسخ می‌دهند (نه 500). برای بررسی:

```bash
docker compose ps ai_service
docker compose logs --tail=100 ai_service
docker compose exec ai_service python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())"
```

### چت با پیام «The language model is unavailable» پاسخ می‌دهد

یعنی سرویس AI سالم است ولی LLM در دسترس نیست. اگر از Ollama استفاده می‌کنید:

```bash
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama list
docker compose exec ollama ollama pull qwen2.5:3b
```

اگر `LLM_BASE_URL` روی سرویس بیرونی تنظیم شده، دسترسی کانتینر `ai_service` به آن آدرس را بررسی کنید.

### اجرا روی سیستم کم‌حافظه

- `AI_ENABLE_RERANKER=0`: حافظه کمتری مصرف می‌شود؛ جست‌وجو با امتیاز ترکیبی (vector + keyword) ادامه پیدا می‌کند.
- `AI_TORCH_THREADS=2` و `OMP_NUM_THREADS=2`: جلوگیری از اشغال کل CPU.
- `AI_MODEL_LOAD_TIMEOUT`: حداکثر انتظار درخواست‌ها برای آماده شدن مدل‌ها.
- `AI_OFFLINE=1`: جلوگیری از هرگونه تماس با HuggingFace (مدل‌ها باید از قبل cache شده باشند).

### Django بدون انتظار برای AI بالا می‌آید

وابستگی `depends_on` سرویس `django` به `ai_service` از `service_healthy` به `service_started` تغییر کرده است؛ بنابراین ورود، آپلود و داشبورد مدیریت حتی وقتی مدل‌ها در حال لود هستند کار می‌کنند.

### خطاهای ورود

| وضعیت | پیام | معنا |
|---|---|---|
| `400` | `Username and password are required.` | فیلد خالی |
| `401` | `Invalid username or password.` | رمز یا نام کاربری نادرست |
| `401` | `This account is deactivated...` | کاربر غیرفعال است |
| `403` | `Your account is not assigned to an organization.` | کاربر Tenant ندارد |
| `403` | `Your organization is inactive...` | Tenant غیرفعال است |
| بدون پاسخ | `Cannot reach the server...` | بک‌اند بالا نیست یا آدرس API اشتباه است |

عمر توکن دسترسی به‌صورت پیش‌فرض ۳۰ دقیقه است (`JWT_ACCESS_TOKEN_MINUTES`) و توکن refresh هفت روز (`JWT_REFRESH_TOKEN_DAYS`).
