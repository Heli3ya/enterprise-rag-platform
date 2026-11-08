# Enterprise RAG Platform

پلتفرم سازمانی جست‌وجو و پرسش‌وپاسخ هوشمند روی اسناد داخلی، با جداسازی داده بین سازمان‌ها (multi-tenant) و کنترل دسترسی در سطح دپارتمان.

این مخزن شامل سه بخش اصلی است: بک‌اند Django، سرویس استنتاج FastAPI و رابط کاربری Next.js.

## قابلیت‌های اصلی

- **مدیریت اسناد:** آپلود PDF، Word و TXT با محدودیت ۵ مگابایت و بررسی نوع واقعی فایل (MIME).
- **پردازش خودکار:** استخراج متن، تکه‌بندی توکنی، تولید Embedding و ایندکس برداری به‌صورت غیرهم‌زمان با Celery.
- **جست‌وجوی ترکیبی:** ترکیب جست‌وجوی معنایی (pgvector) و جست‌وجوی کلیدواژه‌ای PostgreSQL، سپس Rerank با Cross-Encoder.
- **پاسخ مبتنی بر سند (RAG):** تولید پاسخ با ارجاع به شماره Chunk و بازگرداندن Citation معتبر.
- **پاسخ جریانی:** پخش توکن‌به‌توکن پاسخ با Server-Sent Events.
- **چند-مستأجری:** جداسازی Tenant در مدل داده، احراز هویت، کوئری‌ها و لایه بازیابی.
- **مدیریت و نظارت:** پنل تحلیلی ادمین، Audit Log، محدودیت نرخ درخواست، متریک‌های Prometheus و Sentry.

## پشته فناوری

| لایه | فناوری |
|---|---|
| بک‌اند | Django 6.0، Django REST Framework 3.17، SimpleJWT، drf-spectacular |
| پایگاه داده | PostgreSQL 16 + pgvector |
| صف و کش | Redis 7 + Celery 5.6 |
| سرویس AI | FastAPI، sentence-transformers، Cross-Encoder، Ollama یا OpenAI-compatible |
| فرانت‌اند | Next.js 16، React 19، Tailwind CSS 4، Recharts |
| استقرار | Docker Compose، Gunicorn، Nginx |
| پایش | Prometheus، Sentry |

## معماری کلی

```text
Browser (Next.js :3000)
        |
        |  HTTP / SSE
        v
    Nginx :80
        |
        v
 Django API :8000  ──────────────>  PostgreSQL 16 + pgvector
        |                                  ^
        |  HTTP داخلی                      |
        v                                  |
 FastAPI AI Service :8001 ─────────────────┘
        |
        +──> Embedding model (multilingual-e5-small)
        +──> Reranker (mmarco-mMiniLMv2)
        +──> LLM (Ollama / OpenAI-compatible)

 Django ──> Redis (cache DB 1, Celery broker DB 0) <── Celery Worker
```

جزئیات بیشتر: [docs/02-architecture.md](docs/02-architecture.md)

## شروع سریع (Docker)

پیش‌نیاز: Docker Engine و Docker Compose v2.

```bash
# 1) فایل .env را در ریشه پروژه بساز (مقادیر نمونه)
cat > .env <<'EOF'
DB_NAME=enterprise_rag
DB_USER=enterprise_rag_user
DB_PASSWORD=change-me
DB_HOST=postgres
DB_PORT=5432
DJANGO_SECRET_KEY=change-me-to-a-long-random-value
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,django
CORS_ALLOWED_ORIGINS=http://localhost:3000
LLM_PROVIDER=ollama
LLM_BASE_URL=http://ollama:11434/api
LLM_MODEL=qwen2.5:3b
LLM_API_KEY=
EOF

# 2) اعتبارسنجی تنظیمات
bash deploy/setup.sh --check-only

# 3) ساخت تصاویر و اجرای سرویس‌ها
bash deploy/setup.sh --apply
```

سپس:

```bash
docker compose ps
curl -i http://127.0.0.1:8000/api/docs/
```

ساخت اولین کاربر ادمین و داده پایه:

```bash
docker compose exec django python manage.py createsuperuser
docker compose exec django python manage.py shell
```

```python
from tenants.models import Tenant
from departments.models import Department
from accounts.models import User

tenant = Tenant.objects.create(name="Acme")
dept = Department.objects.create(tenant=tenant, name="IT")
user = User.objects.get(username="admin")
user.tenant = tenant
user.department = dept
user.role = "Admin"
user.save()
```

اجرای فرانت‌اند:

```bash
cd frontend
echo 'NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api' > .env.local
npm install
npm run dev
```

راهنمای کامل نصب محلی: [docs/03-getting-started.md](docs/03-getting-started.md)

## ساختار مخزن

```text
.
├── config/              تنظیمات، URLها، Celery و WSGI/ASGI
├── accounts/            کاربر سفارشی و احراز هویت JWT چند-مستأجری
├── tenants/             مدل Tenant و میان‌افزار Tenant
├── departments/         دپارتمان‌ها و API مربوطه
├── documents/           اسناد، Chunkها، Embeddingها، پردازش و استخراج متن
├── api/                 جست‌وجو، RAG، چت، Audit Log و تحلیل ادمین
├── ai_service/          سرویس FastAPI برای Embedding، Vector Search، Rerank و LLM
├── frontend/            اپلیکیشن Next.js
├── tests/               تست‌های یکپارچه و امنیتی
├── deploy/              اسکریپت نصب، Nginx و راهنمای استقرار
├── docker/              فایل‌های init پایگاه داده
├── Dockerfile           ایمیج Django
└── docker-compose.yml   توپولوژی سرویس‌ها
```

## مستندات

| سند | موضوع |
|---|---|
| [docs/README.md](docs/README.md) | فهرست و مسیرهای مطالعه |
| [docs/01-overview.md](docs/01-overview.md) | معرفی، قابلیت‌ها و جریان‌های اصلی |
| [docs/02-architecture.md](docs/02-architecture.md) | معماری، مرزهای اعتماد و تصمیمات طراحی |
| [docs/03-getting-started.md](docs/03-getting-started.md) | نصب و راه‌اندازی محیط توسعه |
| [docs/04-api-reference.md](docs/04-api-reference.md) | مرجع کامل API |
| [docs/05-data-model.md](docs/05-data-model.md) | مدل داده، ایندکس‌ها و مهاجرت‌ها |
| [docs/06-document-pipeline.md](docs/06-document-pipeline.md) | چرخه پردازش سند |
| [docs/07-rag-pipeline.md](docs/07-rag-pipeline.md) | بازیابی، ادغام امتیازها، Rerank و Citation |
| [docs/08-security.md](docs/08-security.md) | احراز هویت، مجوزها، چند-مستأجری و سخت‌سازی |
| [docs/09-frontend.md](docs/09-frontend.md) | ساختار و رفتار فرانت‌اند |
| [docs/10-testing.md](docs/10-testing.md) | تست، CI و بارگذاری |
| [docs/11-deployment.md](docs/11-deployment.md) | استقرار و بهره‌برداری |
| [docs/12-troubleshooting.md](docs/12-troubleshooting.md) | عیب‌یابی خطاهای رایج |
| [docs/13-known-issues.md](docs/13-known-issues.md) | محدودیت‌ها و بدهی فنی شناخته‌شده |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | قواعد مشارکت و توسعه |

## وضعیت پروژه

این مستندات بر اساس کد موجود در مخزن نوشته شده‌اند و رفتار فعلی سیستم را توصیف می‌کنند. مواردی که به‌عنوان محدودیت یا بدهی فنی شناسایی شده‌اند در [docs/13-known-issues.md](docs/13-known-issues.md) فهرست شده‌اند.

> برای محیط Production، پیش از هر چیز [docs/08-security.md](docs/08-security.md) و [deploy/DEPLOYMENT.md](deploy/DEPLOYMENT.md) را بخوانید.
