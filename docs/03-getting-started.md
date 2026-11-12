# ۰۳ — راه‌اندازی محیط توسعه

دو مسیر دارید: اجرای کامل با Docker (توصیه‌شده) یا اجرای محلی سرویس‌ها برای توسعه و دیباگ.

## ۱. پیش‌نیازها

| ابزار | نسخه پیشنهادی | کاربرد |
|---|---|---|
| Python | 3.13 | Django، Celery و سرویس AI |
| Node.js | 20 یا بالاتر | Next.js |
| PostgreSQL | 16 + pgvector | پایگاه داده |
| Redis | 7 | کش و صف |
| Docker + Compose v2 | جدید | مسیر توصیه‌شده |
| libmagic | — | تشخیص MIME فایل (الزامی برای `python-magic`) |

### نکته Windows

`python-magic` به کتابخانه `libmagic` نیاز دارد. در لینوکس با `apt install libmagic1` نصب می‌شود. در ویندوز ساده‌ترین راه استفاده از Docker است؛ در اجرای بومی می‌توانید از بسته `python-magic-bin` استفاده کنید، اما نسخه و سازگاری آن را جداگانه بررسی کنید. بدون این کتابخانه، آپلود سند با خطای import شکست می‌خورد.

## ۲. مسیر A — اجرای کامل با Docker

### ۲.۱. ساخت `.env`

فایل `.env` در ریشه پروژه (کنار `manage.py`) قرار می‌گیرد.

```dotenv
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

SENTRY_DSN=
SENTRY_FASTAPI_DSN=
```

> `DJANGO_SECRET_KEY` اجباری است. اگر خالی باشد، Django با خطای پیکربندی بالا نمی‌آید.

### ۲.۲. اعتبارسنجی و اجرا

```bash
bash deploy/setup.sh --check-only
bash deploy/setup.sh --apply
```

`--apply` تصاویر را می‌سازد، PostgreSQL و Redis را بالا می‌آورد و در صورت انتخاب Ollama، مدل را دریافت می‌کند. اولین اجرا می‌تواند طولانی باشد.

### ۲.۳. بررسی سلامت

```bash
docker compose ps
docker compose logs --tail=100 django ai_service
curl -i http://127.0.0.1:8000/api/docs/
```

پاسخ موفق `ai_service` را می‌توانید از داخل کانتینر ببینید:

```bash
docker compose exec -T ai_service \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=5).read().decode())"
```

## ۳. مسیر B — اجرای محلی

### ۳.۱. پایگاه داده

```sql
CREATE DATABASE enterprise_rag;
\c enterprise_rag
CREATE EXTENSION IF NOT EXISTS vector;
```

اگر کاربر جداگانه می‌سازید:

```sql
CREATE USER enterprise_rag_user WITH PASSWORD 'change-me';
GRANT ALL PRIVILEGES ON DATABASE enterprise_rag TO enterprise_rag_user;
```

### ۳.۲. بک‌اند

```bash
python -m venv venv
source venv/Scripts/activate     # Git Bash روی Windows
# source venv/bin/activate       # Linux / macOS

pip install --upgrade pip
pip install -r requirements-django.txt

python manage.py migrate
python manage.py check

# دپارتمان‌های موجود را به سند راهنمای شروع سرد مجهز می‌کند (idempotent)
python manage.py seed_onboarding_docs

python manage.py runserver 8000
```

برای اجرای بومی، در `.env` مقادیر زیر را به سرویس‌های محلی اشاره دهید:

```dotenv
DB_HOST=127.0.0.1
REDIS_CACHE_URL=redis://127.0.0.1:6379/1
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
AI_SERVICE_URL=http://127.0.0.1:8001
```

### ۳.۳. Celery Worker

```bash
celery -A config worker --loglevel=info
# ویندوز:
celery -A config worker --loglevel=info --pool=solo
```

بدون worker، سند در وضعیت `Pending` می‌ماند.

### ۳.۴. سرویس AI

سرویس باید از داخل پوشه `ai_service` اجرا شود، چون importها نسبی هستند (`from db import ...`).

```bash
cd ai_service
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8001
```

اولین اجرا مدل‌های Embedding و Reranker را دانلود می‌کند (چند صد مگابایت). تا زمان آماده شدن مدل، `/health` ممکن است پاسخ ندهد، چون مدل‌ها قبل از بالا آمدن اپ بارگذاری می‌شوند.

### ۳.۵. فرانت‌اند

```bash
cd frontend
npm install
```

فایل `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api
```

```bash
npm run dev
```

سپس `http://localhost:3000`.

> آدرس پایه باید شامل `/api` باشد؛ کلاینت مسیرهایی مثل `/auth/login/` را نسبت به آن می‌سازد. `ChatWindow` در صورت نبود متغیر، مقدار `http://127.0.0.1:8000/api` را پیش‌فرض می‌گذارد، اما برای بقیه درخواست‌ها بهتر است صریح تنظیم شود.

## ۴. ساخت داده اولیه

پس از migrate:

```bash
python manage.py createsuperuser
```

سپس در Django shell:

```python
from tenants.models import Tenant
from departments.models import Department
from accounts.models import User

tenant = Tenant.objects.create(name="Acme")
dept = Department.objects.create(tenant=tenant, name="IT")

user = User.objects.get(username="admin")
user.tenant = tenant
user.department = dept
user.role = "Admin"          # برای دسترسی به تحلیل و Audit
user.save()
```

برای ساخت کاربر عضو:

```python
User.objects.create_user(
    username="member1",
    password="a-strong-password",
    tenant=tenant,
    department=dept,
    role="Member",
)
```

### نکته درباره نقش‌ها

مدل `User` فقط `Admin` را در `ROLE_CHOICES` دارد، اما مقدار پیش‌فرض `Member` است. در عمل هر دو مقدار استفاده می‌شوند؛ `Member` در choices تعریف نشده و این موضوع در Django Admin می‌تواند گمراه‌کننده باشد. جزئیات در [13-known-issues.md](13-known-issues.md).

## ۵. بررسی سریع عملکرد

```bash
# ورود
curl -s -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'

# پروفایل
curl -s http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# لیست دپارتمان‌ها
curl -s http://127.0.0.1:8000/api/departments/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# آپلود سند
curl -s -X POST http://127.0.0.1:8000/api/documents/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -F "title=Employee Handbook" \
  -F "department=1" \
  -F "file_path=@./sample.pdf"

# وضعیت سند
curl -s http://127.0.0.1:8000/api/documents/1/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# جست‌وجو
curl -s -X POST http://127.0.0.1:8000/api/query/search/ \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"query_text":"policy for remote work","top_k":5}'
```

## ۶. دستورات روزمره

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
python manage.py test            # یا pytest
python manage.py shell
python manage.py collectstatic
```

```bash
cd frontend
npm run lint
npm run build
npx playwright test
```

## ۷. مشکلات رایج در راه‌اندازی

| نشانه | علت احتمالی | راه‌حل |
|---|---|---|
| `ImproperlyConfigured` یا خطای SECRET_KEY | `.env` نبود یا کلید خالی | `DJANGO_SECRET_KEY` را ست کنید |
| `could not open extension control file "vector"` | pgvector نصب نیست | از ایمیج `pgvector/pgvector:pg16` استفاده کنید |
| `No module named magic` | libmagic نصب نیست | Docker یا نصب libmagic |
| سند در `Pending` می‌ماند | Celery worker اجرا نمی‌شود | worker را بالا بیاورید و Redis را بررسی کنید |
| `Connection refused` در جست‌وجو | سرویس AI بالا نیست | `uvicorn main:app --port 8001` |
| ۴۰۱ با پیام سازمان | کاربر Tenant ندارد یا Tenant غیرفعال است | در shell به کاربر Tenant اختصاص دهید |
| ۴۰۳ هنگام آپلود | دپارتمان مقصد با دپارتمان کاربر یکی نیست | دپارتمان درست را انتخاب کنید یا Admin شوید |

فهرست کامل: [12-troubleshooting.md](12-troubleshooting.md)
