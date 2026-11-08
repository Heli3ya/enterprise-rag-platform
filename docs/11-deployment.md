# ۱۱ — استقرار و بهره‌برداری

این سند نمای فنی استقرار و کارهای روزمره را پوشش می‌دهد. راهنمای گام‌به‌گام سرور (سخت‌افزار، Nginx، HTTPS، آفلاین) در [deploy/DEPLOYMENT.md](../deploy/DEPLOYMENT.md) است.

## ۱. توپولوژی Compose

| سرویس | ایمیج | پورت میزبان | Volume | نقش |
|---|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | — | `postgres_data` | پایگاه داده + بردار |
| `redis` | `redis:7-alpine` | — | `redis_data` | کش و صف |
| `ai_service` | ساخت از `ai_service/Dockerfile` | — | `ai_model_cache`، `eval_reports` | Embedding، Rerank، LLM، ارزیابی |
| `django` | ساخت از `Dockerfile` | `8000` و `18001` | `media_data` | API و Admin |
| `celery_worker` | همان ایمیج Django | — | `media_data` | پردازش اسناد |
| `ollama` | `ollama/ollama` | — | `ollama_data` | LLM محلی (profile) |
| `ollama-model-init` | `ollama/ollama` | — | — | دریافت مدل (profile) |

نکته‌ها:

- `ollama` و `ollama-model-init` فقط با `--profile ollama` اجرا می‌شوند.
- **فرانت‌اند در Compose نیست.** `frontend/` در `.dockerignore` حذف شده و باید جداگانه (Vercel، Node server یا Nginx) مستقر شود.
- پورت `18001:8000` یک نگاشت اضافی است که همان Django را روی پورت دیگری منتشر می‌کند. اگر استفاده نمی‌شود، حذفش کنید.
- PostgreSQL، Redis و AI Service پورت میزبان ندارند؛ این وضعیت مطلوب است.
- `eval_reports` گزارش‌های ارزیابی کیفیت را نگه می‌دارد. اگر پوشهٔ `/app/evaluation/reports` در ایمیج ساخته نشود، Docker آن را با مالک `root` می‌سازد و سرویس (با کاربر `app`) نمی‌تواند بنویسد؛ به همین دلیل این پوشه در `ai_service/Dockerfile` ساخته و `chown` می‌شود. جزئیات در [14-evaluation.md](14-evaluation.md).

## ۲. متغیرهای محیطی

| متغیر | مصرف‌کننده | توضیح |
|---|---|---|
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Django، AI | اتصال پایگاه داده |
| `DJANGO_SECRET_KEY` | Django | اجباری |
| `DJANGO_DEBUG` | Django | در Compose روی `False` ست شده |
| `DJANGO_ALLOWED_HOSTS` | Django | دامنه واقعی را اضافه کنید |
| `CORS_ALLOWED_ORIGINS` | Django | Origin فرانت‌اند |
| `REDIS_CACHE_URL` | Django | پیش‌فرض `redis://redis:6379/1` |
| `CELERY_BROKER_URL` | Django، Celery | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | Django، Celery | `redis://redis:6379/0` |
| `AI_SERVICE_URL` | Django | `http://ai_service:8001` |
| `LLM_PROVIDER` | AI | `ollama` یا `openai_compatible` |
| `LLM_BASE_URL` | AI | آدرس API مدل |
| `LLM_MODEL` | AI | نام مدل |
| `LLM_API_KEY` | AI | در صورت نیاز ارائه‌دهنده |
| `SENTRY_DSN` | Django | اختیاری |
| `SENTRY_FASTAPI_DSN` | AI | اختیاری |
| `HF_HOME` | AI | در Compose `/app/.cache/huggingface` |

`docker-compose.yml` مقادیر شبکه داخلی را برای سرویس‌های Django و Celery بازنویسی می‌کند؛ بنابراین `DB_HOST` و `AI_SERVICE_URL` در `.env` برای اجرای بومی معنا دارند، اما در Compose با مقادیر سرویس‌ها جایگزین می‌شوند.

## ۳. استقرار اولیه

```bash
# 1) تنظیم .env
chmod 600 .env

# 2) اعتبارسنجی بدون Build
bash deploy/setup.sh --check-only

# 3) اجرا
bash deploy/setup.sh --apply

# 4) بررسی
docker compose ps
docker compose logs --tail=100 django ai_service
```

سرویس `django` هنگام شروع این را اجرا می‌کند:

```bash
python manage.py migrate --noinput &&
gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile -
```

`celery_worker` فقط worker را اجرا می‌کند و مهاجرت نمی‌زند. اگر Celery قبل از تکمیل migrate بالا بیاید، ممکن است در اولین وظایف خطای جدول بدهد؛ `depends_on` فعلی فقط سلامت Postgres/Redis/AI را چک می‌کند، نه پایان migrate.

## ۴. عملیات روزمره

```bash
# وضعیت
docker compose ps
docker compose ps -a

# لاگ
docker compose logs -f django
docker compose logs --tail=200 celery_worker
docker compose logs --tail=200 ai_service
docker compose logs --tail=100 postgres redis

# اجرای دستور در کانتینر
docker compose exec django python manage.py migrate
docker compose exec django python manage.py createsuperuser
docker compose exec django python manage.py shell
docker compose exec django python manage.py collectstatic --noinput

# restart
docker compose restart django celery_worker

# بازسازی ایمیج پس از تغییر کد
docker compose build django
docker compose up -d django celery_worker
```

### بررسی سلامت

| سرویس | روش |
|---|---|
| Django | `curl -i http://127.0.0.1:8000/api/docs/` |
| AI | `docker compose exec -T ai_service python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read())"` |
| Postgres | `docker compose exec -T postgres pg_isready -U "$DB_USER"` |
| Redis | `docker compose exec -T redis redis-cli ping` |
| Celery | `docker compose exec celery_worker celery -A config inspect ping` |

`/health` سرویس AI فقط بالا بودن اپ را نشان می‌دهد، نه دسترسی به LLM. برای اطمینان، یک درخواست واقعی `/api/llm/` بفرستید.

## ۵. پشتیبان‌گیری

### پایگاه داده

```bash
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > backup-$(date +%F).dump
```

بازیابی:

```bash
cat backup-2026-01-01.dump | docker compose exec -T postgres \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists'
```

### فایل‌های آپلودی

```bash
docker run --rm \
  -v enterprise-rag-platform_media_data:/data \
  -v "$PWD":/backup \
  alpine tar czf /backup/media-$(date +%F).tar.gz -C /data .
```

نام Volume را با `docker volume ls` تأیید کنید؛ نام دقیق به نام پوشه پروژه بستگی دارد.

### چه چیزهایی باید پشتیبان گرفته شود

- PostgreSQL
- Volume `media_data`
- `.env` در محل امن (نه در همان سرور)
- در استقرار آفلاین: `ai_model_cache` و `ollama_data`

### آزمایش بازیابی

نسخه پشتیبان تا زمانی که یک‌بار بازیابی و تست نشده باشد، قابل اتکا نیست. حداقل فصلی یک بازیابی کامل در محیط آزمایشی انجام دهید.

## ۶. به‌روزرسانی نسخه

```bash
git pull
bash deploy/setup.sh --check-only
docker compose build django
docker compose up -d django celery_worker
docker compose exec django python manage.py migrate
docker compose ps
```

قبل از هر به‌روزرسانی:

1. پشتیبان پایگاه داده و media.
2. بررسی migrationهای جدید (`python manage.py showmigrations`).
3. بررسی تغییرات `.env` یا متغیرهای جدید.
4. آماده بودن مسیر بازگشت (تصویر قبلی را tag کنید).

## ۷. Nginx

`deploy/nginx.conf` یک فایل کامل با بلوک‌های `events` و `http` است، نه یک قطعه `server` برای `sites-available`. آن را مطابق ساختار توزیع خود جای‌گذاری کنید.

رفتار فعلی:

| مسیر | رفتار |
|---|---|
| `/api/documents/` | پروکسی + محدودیت عمومی و محدودیت آپلود |
| `/api/` | پروکسی + محدودیت عمومی |
| `/` | `404` (فرانت‌اند و فایل‌ها افشا نمی‌شوند) |

```bash
sudo nginx -t
sudo systemctl reload nginx
```

برای HTTPS و دامنه، بخش‌های ۱۰ و ۱۱ در [deploy/DEPLOYMENT.md](../deploy/DEPLOYMENT.md) را ببینید.

## ۸. پایش

| منبع | کاربرد |
|---|---|
| `GET /metrics/` | متریک‌های Django و Prometheus |
| Sentry (Django) | خطاهای بک‌اند |
| Sentry (FastAPI) | خطاهای سرویس AI |
| Sentry (Next.js) | خطاهای فرانت‌اند |
| Celery logs | شکست پردازش اسناد |
| `docker compose ps` | سلامت کانتینرها |

هشدارهای پیشنهادی:

- نرخ خطای ۵xx بالاتر از آستانه
- صف Celery با طول فزاینده
- سندهای `Processing` یا `Failed` بیش از حد
- مصرف RAM سرویس AI
- latency جست‌وجو و چت

## ۹. ظرفیت و مقیاس

| منبع | نقطه شروع | گلوگاه |
|---|---|---|
| CPU | ۴ vCPU | استنتاج و Rerank |
| RAM | ۸ GB (LLM ابری) / ۱۶ GB+ (Ollama) | مدل‌های Embedding و Rerank |
| دیسک | ۵۰ GB SSD | اسناد، مدل‌ها، پایگاه داده |
| GPU | اختیاری | تسریع LLM محلی |

مسیرهای افزایش ظرفیت:

1. افزایش workerهای Gunicorn (با پایش RAM).
2. افزایش concurrency سلری و جدا کردن صف.
3. چند replica از `ai_service` (با توجه به مصرف RAM هر replica).
4. کش نتایج پرتکرار در Redis.
5. تنظیم `ef_search` و بازسازی ایندکس HNSW.

## ۱۰. سخت‌سازی Production

- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_SECRET_KEY` یکتا
- [ ] `DJANGO_ALLOWED_HOSTS` = دامنه واقعی
- [ ] `CORS_ALLOWED_ORIGINS` = دامنه فرانت‌اند
- [ ] Django فقط روی `127.0.0.1:8000`
- [ ] حذف نگاشت `18001`
- [ ] HTTPS + HSTS + redirect
- [ ] `/metrics/`، `/api/docs/` و `/api/schema/` محدود
- [ ] پشتیبان‌گیری خودکار و آزمایش‌شده
- [ ] لاگ متمرکز و هشدار
- [ ] محدودیت نرخ متناسب با بار واقعی
- [ ] بررسی دسترسی‌ها با داده واقعی

جزئیات: [08-security.md](08-security.md)

## ۱۱. نکات استقرار فرانت‌اند

- Build تولیدی:

```bash
cd frontend
NEXT_PUBLIC_API_BASE_URL=https://api.example.com/api npm run build
npm run start
```

- `NEXT_PUBLIC_*` در زمان **Build** جایگزین می‌شود؛ تغییر آن بعد از Build اثر ندارد.
- اگر فرانت‌اند و API روی دامنه‌های مختلف هستند، `CORS_ALLOWED_ORIGINS` را دقیق تنظیم کنید.
- برای SSE، بافر شدن پاسخ در پراکسی/CDN را غیرفعال کنید.
- `allowedDevOrigins` در `next.config.ts` فقط برای توسعه است.
