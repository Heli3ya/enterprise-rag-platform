# ارزیابی کیفیت پاسخ (RAG Evaluation)

این سند سیستم سنجش کیفیت پاسخ‌های LLM را توضیح می‌دهد: چرا ساخته شده، هر معیار چگونه محاسبه می‌شود، چگونه اجرا شود و خروجی چه شکلی است.

هدف اصلی، پاسخ به یک سؤال است: **آیا مدل به متن بازیابی‌شده وفادار است یا از خودش می‌سازد؟**

---

## ۱. جایگاه در معماری

```
┌──────────────┐   ۱. سؤال    ┌────────────────────┐
│  Dataset     │ ───────────► │  EvaluationRunner  │
│  (JSONL)     │              │  (ai_service)      │
└──────────────┘              └─────────┬──────────┘
                                        │
                    ۲. بازیابی  ◄───────┤ (همان فرمول hybrid + rerank)
                                        ▼
                              ┌────────────────────┐
                              │  PostgreSQL        │
                              │  chunks + vectors  │
                              └─────────┬──────────┘
                                        │
                    ۳. ساخت prompt ─────┤ (بایت‌به‌بایت همان prompt چت)
                                        ▼
                              ┌────────────────────┐
                              │  LLM (Ollama)      │
                              └─────────┬──────────┘
                                        │ ۴. پاسخ
                                        ▼
                              ┌────────────────────┐
                              │  Metrics + Judge   │
                              └─────────┬──────────┘
                                        │
                                        ▼
                              report_<run>.json / .csv
```

نکتهٔ کلیدی: ارزیابی **داخل میکروسرویس FastAPI** اجرا می‌شود، نه در Django. دلیلش این است که:

- مدل embedding و reranker همان‌جا در حافظه بارگذاری شده‌اند؛ فراخوانی دوباره از Django یعنی هزینهٔ شبکه و سریال‌سازی برای هر chunk.
- سرویس AI از قبل دسترسی مستقیم و محدود به PostgreSQL دارد (`db.py`) و همان کوئری برداری را اجرا می‌کند.
- ارزیابی یک کار سنگین و طولانی است و نباید workerهای gunicorn مربوط به ترافیک کاربر را اشغال کند.

---

## ۲. چرا کتابخانهٔ `ragas` نصب نشد؟

صورت مسئله «ragas **یا ابزارهای مشابه**» را مجاز کرده بود. `ragas` در این محیط نصب نشد چون:

- تصویر `ai_service` به `datasets`، `langchain`، `pandas` و `openai` نیاز پیدا می‌کند (چند صد مگابایت اضافه).
- نسخهٔ pinned این وابستگی‌ها با `sentence-transformers` و `torch` در تضاد نسخه‌ای قرار می‌گیرد.
- در محیط بسته (air-gapped) اصلاً قابل نصب نیست.

به‌جای آن، **تعریف دقیق همان چهار معیار RAGAS** در `ai_service/evaluation/metrics.py` پیاده شد؛ همان روش LLM-as-Judge، همان فرمول‌ها، همان بازهٔ ۰ تا ۱. اگر روزی `ragas` نصب شود، آداپتور `evaluation/ragas_backend.py` با `AI_EVAL_BACKEND=ragas` فعال می‌شود و **قالب گزارش تغییر نمی‌کند**.

---

## ۳. معیارها

هر معیار عددی بین ۰ و ۱ برمی‌گرداند و فیلد `method` نشان می‌دهد با چه روشی حساب شده است.

### ۳.۱ Faithfulness — وفاداری (اصلی‌ترین سیگنال توهم)

1. پاسخ به گزاره‌ها شکسته می‌شود. **پیش‌فرض: برش قطعی بر اساس مرز جمله‌ها** (`split_statements`)، نه تولید گزاره با LLM.
2. هر گزاره در برابر context بازیابی‌شده داوری می‌شود (`verify_statements`).
3. `score = تعداد گزاره‌های پشتیبانی‌شده / کل گزاره‌ها`

```
پاسخ: "مرخصی سالانه ۲۶ روز است. سقف انتقال ۵ روز است."
گزاره‌ها: ["مرخصی سالانه ۲۶ روز است", "سقف انتقال ۵ روز است"]
داوری:    [true, true]  →  faithfulness = 1.0
```

**چرا برش قطعی، نه تولید گزاره با LLM؟** با مدل کوچک محلی (۳B) آزمایش شد: از یک جملهٔ صحیح، ده «گزاره» ساخت که هشت‌تای آن‌ها بازگویی همان جمله بود، و بعد نیمی از همان بازگویی‌ها را «پشتیبانی‌نشده» علامت زد. نتیجه: امتیاز ۰٫۶ برای پاسخی که کاملاً درست بود. برش بر اساس جمله، قطعی و رایگان است و برای پاسخ‌های یک تا پنج جمله‌ای دقیق‌تر عمل می‌کند. اگر مدل داور قوی‌تر دارید، `AI_EVAL_LLM_DECOMPOSITION=1` رفتار اصلی RAGAS را فعال می‌کند.

پیش از هر معیار، نشانگرهای ارجاع (`[95]`) از متن حذف می‌شوند؛ وگرنه مدل داور جمله‌ای مثل «اطلاعات از [95] است» می‌سازد و آن را بی‌پشتوانه می‌شمارد.

اگر مدل داور پاسخ JSON معتبر ندهد یا تعداد داوری‌ها با تعداد گزاره‌ها نخواند، نتیجه دور ریخته و مسیر واژگانی جایگزین می‌شود.

### ۳.۲ Answer Relevancy — مرتبط بودن پاسخ

1. از روی پاسخ، ۳ سؤال تولید می‌شود که آن پاسخ جوابشان است.
2. سؤال‌ها و سؤال اصلی embed می‌شوند.
3. `score = میانگین شباهت کسینوسی`

پاسخ مبهم یا منحرف، سؤال‌های بی‌ربط تولید می‌کند و امتیاز می‌افتد.

### ۳.۳ Context Precision — دقت بازیابی

هر chunk بازیابی‌شده داوری می‌شود که «برای رسیدن به پاسخ مرجع مفید بود یا نه»، سپس میانگین دقت در رتبه‌ها (Average Precision) حساب می‌شود:

```
AP = (Σ precision@k برای رتبه‌های مرتبط) / تعداد chunkهای مرتبط
```

chunk مفید در رتبهٔ ۱ امتیاز کامل می‌گیرد؛ همان chunk در رتبهٔ ۵ امتیاز کمتری می‌گیرد. این معیار مستقیماً کیفیت retriever را می‌سنجد، نه LLM را.

### ۳.۴ Answer Correctness — دقت نسبت به پاسخ مرجع

ترکیب وزن‌دار، هم‌وزن‌بندی RAGAS:

```
score = 0.75 × token_F1(پاسخ, پاسخ_مرجع) + 0.25 × شباهت_کسینوسی
```

`token_F1` کاملاً قطعی و بدون LLM است، بنابراین این معیار حتی وقتی مدل داور در دسترس نیست عدد معتبر می‌دهد.

### ۳.۵ حالت افت (Fallback)

اگر LLM داور پاسخ JSON معتبر ندهد یا در دسترس نباشد، هر معیار به پیاده‌سازی واژگانی قطعی برمی‌گردد و:

- `method` به `lexical` یا `embedding` تغییر می‌کند،
- `fallback_reason` در جزئیات ثبت می‌شود،
- `summary.methods` تعداد امتیازهای هر روش را می‌شمارد.

بنابراین یک اجرای تخریب‌شده هرگز شبیه یک اجرای سالم گزارش نمی‌شود.

---

## ۴. مجموعه‌دادهٔ مرجع

`ai_service/evaluation/dataset.jsonl` — یک JSON در هر خط:

```json
{
  "id": "hr-01",
  "question": "How many annual leave days do full-time employees receive each year?",
  "ground_truth": "Full-time employees receive 26 working days of paid annual leave per calendar year.",
  "reference_contexts": ["Full-time employees accrue 26 working days of paid annual leave per calendar year."],
  "document": "hr-leave-policy.txt",
  "tags": ["hr", "leave"]
}
```

| فیلد | اجباری | کاربرد |
|---|---|---|
| `question` | ✅ | سؤالی که به pipeline داده می‌شود |
| `ground_truth` | ✅ | پاسخ مرجع برای `context_precision` و `answer_correctness` |
| `id` | ➖ | شناسهٔ پایدار (پیش‌فرض `q-NNN`) |
| `reference_contexts` | ➖ | قطعه‌های اصلی سند؛ برای بازبینی انسانی |
| `document` | ➖ | نام فایل مبدأ |
| `tags` | ➖ | برش گزارش بر اساس موضوع |

وضعیت فعلی: **۵۷ نمونه** روی **۶ سند** سازمانی (مرخصی، امنیت اطلاعات، سفر، خرید، دورکاری، آنبوردینگ).

### ۴.۱ اسناد نمونه

`ai_service/evaluation/corpus/` شامل شش سیاست سازمانی نمونه است. بدون این اسناد، retriever چیزی برای یافتن ندارد و ارزیابی بی‌معناست. برای درج آن‌ها:

```bash
docker compose exec django python manage.py seed_evaluation_corpus \
    --tenant "Default Organization" \
    --department "Knowledge Base" \
    --user heliya
```

خروجی، scope آمادهٔ اجرا را چاپ می‌کند:

```
Evaluation scope: tenant_id=1 department_ids=3
```

این دستور idempotent است (سند موجود را رد می‌کند) و با `--reset` سند را حذف و دوباره ایندکس می‌کند. برخلاف مسیر عادی آپلود، اینجا همه‌چیز **همگام** انجام می‌شود تا بلافاصله قابل استفاده باشد.

> دقت: اسناد در یک دپارتمان مشخص درج می‌شوند، چون بازیابی در این پروژه همیشه به دپارتمان کاربر محدود است.

---

## ۵. اجرا

### ۵.۱ خط فرمان (ساده‌ترین راه)

```bash
# اعتبارسنجی دیتاست و scope، بدون هیچ فراخوانی LLM
docker compose exec ai_service python -m evaluation --list-dataset
docker compose exec ai_service python -m evaluation \
    --tenant-id 1 --department-ids 3 --dry-run

# اجرای واقعی روی ۵ نمونه
docker compose exec ai_service python -m evaluation \
    --tenant-id 1 --department-ids 3 --limit 5

# فقط دو معیار، روی نمونه‌های مشخص
docker compose exec ai_service python -m evaluation \
    --tenant-id 1 --department-ids 3 \
    --sample-ids hr-01,it-05 \
    --metrics faithfulness,context_precision
```

کد خروج: `0` موفق و همهٔ آستانه‌ها پاس، `1` خطا، `2` آرگومان نامعتبر، `3` اجرا موفق ولی حداقل یک معیار زیر آستانه. کد `3` برای استفاده در CI طراحی شده است.

### ۵.۲ Endpoint داخلی

| متد | مسیر | کار |
|---|---|---|
| `POST` | `/api/eval/run/` | شروع اجرا در پس‌زمینه، پاسخ `202` با `job_id` |
| `GET` | `/api/eval/jobs/` | فهرست اجراهای اخیر |
| `GET` | `/api/eval/jobs/{job_id}/` | وضعیت و پیشرفت |
| `GET` | `/api/eval/jobs/{job_id}/report/` | گزارش کامل JSON |
| `GET` | `/api/eval/jobs/{job_id}/report.csv` | همان گزارش به‌صورت CSV |
| `GET` | `/api/eval/dataset/` | خلاصهٔ دیتاست |
| `GET` | `/api/eval/config/` | پیکربندی غیرحساس + وضعیت زمان‌بند |

```bash
docker compose exec ai_service python - <<'PY'
import json, urllib.request

body = json.dumps({
    "tenant_id": 1,
    "department_ids": [3],
    "limit": 5,
    "metrics": ["faithfulness", "answer_relevancy"],
}).encode()

request = urllib.request.Request(
    "http://127.0.0.1:8001/api/eval/run/",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(json.load(urllib.request.urlopen(request, timeout=30)))
PY
```

پاسخ:

```json
{
  "job_id": "9f2c1ab4d7e0",
  "status": "queued",
  "dataset_samples": 57,
  "scope": {
    "tenant_id": 1,
    "department_ids": [3],
    "metrics": ["faithfulness", "answer_relevancy"],
    "limit": 5,
    "top_k": 5
  },
  "status_url": "/api/eval/jobs/9f2c1ab4d7e0/"
}
```

اگر اجرای دیگری در جریان باشد، پاسخ `409` است. فقط یک اجرا هم‌زمان مجاز است، چون مدل روی CPU از قبل پشت `inference_lock` سریال شده و اجرای موازی فقط هر دو را کند می‌کند.

### ۵.۳ اجرای زمان‌بندی‌شده

```env
AI_EVAL_SCHEDULE_HOURS=24     # 0 = خاموش (پیش‌فرض)
AI_EVAL_SCHEDULE_LIMIT=10     # هر شب ۱۰ نمونه، نه ۵۷ تا
AI_EVAL_TENANT_ID=1
AI_EVAL_DEPARTMENT_IDS=3
```

یک thread دیمن هر ۳۰ ثانیه ساعت را چک می‌کند (به‌جای یک `sleep` طولانی، تا خاموش‌شدن سرویس فوری باشد). اگر اجرایی در جریان باشد یا مدل‌ها هنوز لود نشده باشند، آن نوبت رد می‌شود و در `last_error`/لاگ ثبت می‌شود. وضعیت در `GET /api/eval/config/` زیر کلید `schedule` و در `/api/status/` زیر `evaluation` دیده می‌شود.

### ۵.۴ محافظت

اگر `AI_EVAL_TOKEN` ست شود، همهٔ مسیرهای `/api/eval/*` هدر `X-Eval-Token` را با مقایسهٔ `hmac.compare_digest` می‌خواهند و در غیر این صورت `401` می‌دهند. خالی بودن توکن یعنی «باز»، که فقط چون سرویس داخلی است پذیرفتنی است.

---

## ۶. خروجی

### ۶.۰ نمونهٔ واقعی (تأیید‌شده روی همین استقرار)

اجرا روی نمونهٔ `hr-01` («مرخصی سالانه چند روز است؟») با مدل `qwen2.5:3b`:

| معیار | امتیاز | روش |
|---|---|---|
| faithfulness | **1.00** | llm (برش جمله) |
| answer_relevancy | **0.978** | llm |
| answer_correctness | **0.855** | mixed (token_f1 = 0.815، شباهت معنایی = 0.975) |
| context_precision | **1.00** | llm (chunk اول و دوم مرتبط، سه chunk بعدی نامرتبط) |

`summary.passed = true`. زمان: حدود ۵ دقیقه برای یک نمونه با سه معیار.

پاسخ تولیدشده:

```text
[95] Full-time employees receive 26 working days of paid annual leave per calendar year.
```

### ۶.۱ ساختار JSON

```json
{
  "report_version": 1,
  "run_id": "20261107T153012Z-9f2c1a",
  "started_at": "2026-11-07T15:30:12+00:00",
  "finished_at": "2026-11-07T15:38:44+00:00",
  "duration_seconds": 512.3,
  "backend": "internal",
  "backend_note": null,
  "config": {
    "tenant_id": 1,
    "department_ids": [3],
    "metrics": ["faithfulness", "answer_relevancy", "context_precision", "answer_correctness"],
    "top_k": 5,
    "limit": 5,
    "triggered_by": "api",
    "dataset_path": "/app/evaluation/dataset.jsonl"
  },
  "dataset": {"samples": 5, "documents": ["..."], "document_count": 6, "tags": ["..."], "with_reference_contexts": 5, "ids": ["hr-01"]},
  "judge": {"provider": "ollama", "model": "qwen2.5:3b"},
  "summary": {
    "faithfulness": {
      "mean": 0.87, "median": 1.0, "min": 0.5, "max": 1.0,
      "count": 5, "methods": {"llm": 5},
      "threshold": 0.8, "passed": true
    },
    "answer_relevancy": {"mean": 0.74, "...": "...", "threshold": 0.7, "passed": true},
    "context_precision": {"mean": 0.62, "...": "...", "threshold": 0.6, "passed": true},
    "answer_correctness": {"mean": 0.69, "...": "..."},
    "passed": true,
    "checks_run": 3,
    "checks_passed": 3
  },
  "samples": [
    {
      "id": "hr-01",
      "question": "...",
      "ground_truth": "...",
      "document": "hr-leave-policy.txt",
      "tags": ["hr", "leave"],
      "answer": "... [12]",
      "contexts": [
        {"chunk_id": 12, "document_id": 7, "document_title": "hr-leave-policy.txt",
         "chunk_index": 0, "score": 0.93, "rerank_score": 0.71, "preview": "..."}
      ],
      "scores": {
        "faithfulness": {"score": 1.0, "method": "llm", "statements": 2, "supported": 2,
                         "verdicts": [{"statement": "...", "supported": true}]},
        "answer_correctness": {"score": 0.81, "method": "mixed", "token_f1": 0.75, "semantic_similarity": 0.99}
      },
      "latency_ms": {"retrieval": 120, "generation": 48210, "scoring": 21033, "total": 69363},
      "error": null
    }
  ],
  "report_paths": {
    "json": "/app/evaluation/reports/report_20261107T153012Z-9f2c1a.json",
    "csv": "/app/evaluation/reports/report_20261107T153012Z-9f2c1a.csv",
    "summary": "/app/evaluation/reports/latest_summary.json"
  }
}
```

### ۶.۲ ساختار CSV

یک سطر برای هر نمونه:

```
id,question,ground_truth,answer,contexts_count,top_document,
faithfulness,answer_relevancy,context_precision,answer_correctness,
faithfulness_method,latency_ms,error
```

### ۶.۳ فایل‌های کنار گزارش

- `latest.json` — کپی آخرین گزارش کامل (برای داشبورد)
- `latest_summary.json` — فقط خلاصه (سبک، برای مانیتورینگ)
- گزارش‌های قدیمی‌تر از `AI_EVAL_KEEP_REPORTS` (پیش‌فرض ۳۰) خودکار حذف می‌شوند تا volume بی‌نهایت رشد نکند.

گزارش‌ها روی volume نام‌دار `eval_reports` در `/app/evaluation/reports` ذخیره می‌شوند، پس با rebuild ایمیج از بین نمی‌روند.

---

## ۷. پیکربندی

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `AI_EVAL_BACKEND` | `internal` | `internal` یا `ragas` |
| `AI_EVAL_TOKEN` | خالی | کلید مشترک `/api/eval/*` |
| `AI_EVAL_TENANT_ID` | خالی | scope پیش‌فرض |
| `AI_EVAL_DEPARTMENT_IDS` | خالی | مثل `1,3` |
| `AI_EVAL_METRICS` | همه | زیرمجموعهٔ معیارها |
| `AI_EVAL_TOP_K` | `5` | تعداد chunk ورودی به LLM |
| `AI_EVAL_JUDGE_TIMEOUT` | `180` | ثانیه، برای هر فراخوانی داور |
| `AI_EVAL_JUDGE_RETRIES` | `1` | تلاش دوباره برای JSON نامعتبر |
| `AI_EVAL_LLM_DECOMPOSITION` | `0` | `1` = شکستن پاسخ به گزاره با LLM (رفتار اصلی RAGAS) |
| `AI_EVAL_MAX_SAMPLES` | `0` | سقف نمونه در هر اجرا (۰ = همه) |
| `AI_EVAL_SCHEDULE_HOURS` | `0` | فاصلهٔ اجرای خودکار |
| `AI_EVAL_SCHEDULE_LIMIT` | `10` | تعداد نمونه در اجرای زمان‌بندی‌شده |
| `AI_EVAL_MIN_FAITHFULNESS` | `0.80` | آستانهٔ قبولی |
| `AI_EVAL_MIN_ANSWER_RELEVANCY` | `0.70` | آستانهٔ قبولی |
| `AI_EVAL_MIN_CONTEXT_PRECISION` | `0.60` | آستانهٔ قبولی |
| `AI_EVAL_KEEP_REPORTS` | `30` | تعداد گزارش نگهداری‌شده |

---

## ۸. زمان اجرا و بهینه‌سازی

روی CPU، تولید یک پاسخ با `qwen2.5:3b` می‌تواند ۳۰ تا ۱۲۰ ثانیه طول بکشد و هر معیار داور ۱ تا ۳ فراخوانی LLM دیگر می‌خواهد. یعنی هر نمونه تقریباً **۲ تا ۵ دقیقه**.

| تعداد نمونه | معیارها | زمان تقریبی |
|---|---|---|
| ۵ | faithfulness + context_precision | ۱۰ تا ۲۰ دقیقه |
| ۱۰ | همه | ۳۰ تا ۵۰ دقیقه |
| ۵۷ | همه | چند ساعت |

راهکارهای عملی:

1. **برای شروع** `--limit 5` بزنید، نه کل دیتاست.
2. **برای اجرای شبانه** `AI_EVAL_SCHEDULE_LIMIT=10` بگذارید تا هر شب یک برش ارزیابی شود.
3. **برای اجرای کامل** از GPU یا یک مدل داور قوی‌تر روی endpoint سازگار با OpenAI استفاده کنید (`LLM_PROVIDER=openai_compatible`).
4. اگر فقط می‌خواهید سرعت را ببینید و کیفیت داور مهم نیست، `AI_EVAL_METRICS=answer_correctness` بگذارید؛ این معیار هیچ فراخوانی LLM ندارد.

بهینه‌سازی‌هایی که در کد اعمال شده‌اند:

- embedding سؤال کش می‌شود (`lru_cache` روی `encode_query_cached`).
- contextها قبل از ارسال به داور به ۱۲۰۰ کاراکتر بریده می‌شوند.
- گزاره‌های faithfulness حداکثر ۱۰ عدد و در **یک** فراخوانی داوری می‌شوند (نه یکی‌یکی).
- اجرا در thread جدا و پشت یک قفل تک‌اجرایی است تا با ترافیک چت رقابت نکند.
- گزارش کامل روی دیسک می‌ماند و فقط خلاصه در حافظه نگه داشته می‌شود.

---

## ۹. تست‌ها

| فایل | پوشش |
|---|---|
| `ai_service/test_evaluation.py` | ۳۸ تست: بارگذاری و اعتبارسنجی دیتاست، پارس JSON داور، فرمول هر چهار معیار، برش جمله، حذف نشانگر ارجاع، fallback، نوشتن گزارش، بریدن گزارش‌های قدیمی، رجیستری job و رد اجرای هم‌زمان |
| `tests/test_eval_prompt_parity.py` | یکسان بودن بایت‌به‌بایت prompt ارزیابی با prompt تولید |
| `tests/test_seed_evaluation_corpus.py` | درج، idempotency و `--reset` دستور seed |

```bash
docker compose exec ai_service python -m pytest test_evaluation.py -q
docker compose exec django python -m pytest tests/test_eval_prompt_parity.py \
    tests/test_seed_evaluation_corpus.py -q
```

---

## ۱۰. محدودیت‌های شناخته‌شده

- **داور همان مدل تولید است.** در این استقرار `qwen2.5:3b` هم پاسخ می‌سازد و هم داوری می‌کند. با همین مدل، تفکیک گزاره با LLM نتیجهٔ نادرست داد (امتیاز ۰٫۶ برای پاسخ درست)، به همین دلیل برش قطعی جمله پیش‌فرض شد و امتیاز به ۱٫۰ رسید. برای ارزیابی معتبر، مدل داور باید مستقل و قوی‌تر باشد.
- **`answer_correctness` واژگانی است.** `token_F1` پاسخ‌های طولانی را جریمه می‌کند؛ عدد آن را باید در کنار `faithfulness` خواند، نه به‌تنهایی.
- **رجیستری job در حافظه است.** با `--workers 1` (پیش‌فرض uvicorn) درست کار می‌کند. اگر سرویس را چند-نمونه‌ای کردید، رجیستری باید به Redis منتقل شود.
- **scope دستی است.** ارزیابی خودش tenant/department را کشف نمی‌کند؛ باید صریح داده شود.
- **دیتاست انگلیسی است** چون اسناد نمونه انگلیسی‌اند. برای محتوای فارسی باید نمونه‌ها بازنویسی شوند؛ خود موتور معیارها زبان‌مستقل است (مدل embedding چندزبانه است).
- **`latest.csv` ساخته نمی‌شود.** فقط `latest.json` و `latest_summary.json` به‌روزرسانی می‌شوند؛ CSV هر اجرا نام یکتای خودش را دارد.
