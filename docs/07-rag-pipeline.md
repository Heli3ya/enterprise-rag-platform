# ۰۷ — خط لوله بازیابی و RAG

## ۱. نقطه ورودها

| Endpoint | تابع | ذخیره تاریخچه | Rerank |
|---|---|---|---|
| `POST /api/search/` | `semantic_search_view` → `hybrid_search` | خیر | بله (درون hybrid) |
| `POST /api/query/search/` | `search_query_view` → `hybrid_search` | بله | بله |
| `POST /api/query/ask/` | `rag_query_view` → `generate_rag_answer` | خیر | بله |
| `POST /api/chat/ask/` | `chat_ask_view` → `generate_rag_stream` | خیر | بله |

همه این مسیرها ابتدا `_tenant_required_response` را صدا می‌زنند: کاربر باید Tenant داشته باشد و Tenant فعال باشد.

## ۲. پیش‌نیاز: دپارتمان

```python
def get_user_department_id(user):
    if user is None or not user.is_authenticated:
        return None
    if user.tenant_id is None:
        return None
    return user.department_id
```

اگر کاربر دپارتمان نداشته باشد، `hybrid_search` بلافاصله لیست خالی برمی‌گرداند. یعنی **کاربر بدون دپارتمان نمی‌تواند جست‌وجو کند**، حتی اگر Admin باشد.

## ۳. بازیابی معنایی

`api/services.py` → `semantic_search`

```python
requests.post(
    f"{AI_SERVICE_URL}/api/vector-search/",
    json={
        "query": query,
        "tenant_id": tenant_id,
        "allowed_department_ids": [department_id],
        "limit": limit,
    },
)
```

سرویس AI کوئری زیر را اجرا می‌کند:

```sql
SELECT e.chunk_id, c.content, c.chunk_index,
       d.id, d.title, d.department_id,
       e.embedding_vector <=> %s::vector AS distance
FROM documents_embedding e
JOIN documents_documentchunk c ON e.chunk_id = c.id
JOIN documents_document d ON c.document_id = d.id
WHERE d.tenant_id = %s
  AND d.department_id = ANY(%s)
ORDER BY e.embedding_vector <=> %s::vector
LIMIT %s
```

سپس Django نتایج را **دوباره از دیتابیس** می‌خواند و فقط Chunkهایی را می‌پذیرد که:

- `document.tenant_id == tenant_id`
- `document.department_id == department_id`
- `document.department.tenant_id == tenant_id`

محتوای نمایش‌داده‌شده هم از دیتابیس می‌آید، نه از پاسخ سرویس AI. این کار جلوی دستکاری یا نشت محتوا از سرویس AI را می‌گیرد.

امتیاز معنایی: `1 - distance` (شباهت کسینوسی).

## ۴. بازیابی کلیدواژه‌ای

`keyword_search`

```python
SearchQuery(query, config="simple")
SearchVector("content", config="simple")
SearchRank(...)
```

- فیلتر Tenant و دپارتمان مثل مسیر معنایی.
- محدود به همان `limit`.
- ترتیب نزولی بر اساس `rank`.

پیکربندی `simple` انتخاب شده تا رفتار زبان‌محور (stemming) اعمال نشود و برای متن فارسی/چندزبانه قابل پیش‌بینی بماند. هزینه‌اش این است که شکل‌های صرفی کلمه به هم نگاشت نمی‌شوند.

## ۵. نرمال‌سازی و ادغام

### نرمال‌سازی min-max

```python
(score - min) / (max - min)
```

اگر همه امتیازها برابر باشند، همه `1.0` می‌شوند. اگر لیست خالی باشد، دیکشنری خالی برمی‌گردد.

### فرمول ادغام

```python
score = 0.7 * semantic_score + 0.3 * keyword_score
if query.lower() in content.lower():
    score += 0.2
```

- Chunkهایی که فقط در یکی از دو مسیر آمده‌اند، امتیاز صفر در مسیر دیگر می‌گیرند.
- پاداش ۰٫۲ برای تطابق مستقیم عبارت، به نتایج دقیق (کد، نام، شماره) کمک می‌کند.
- تعداد اولیه هر مسیر `limit * 3` است تا پس از ادغام، کاندید کافی وجود داشته باشد.

## ۶. Rerank

```python
rerank_candidates = fused_results[:5]
reranked_results = rerank_results(query, rerank_candidates)
```

- فقط **۵ کاندید برتر** ادغام‌شده به Rerank می‌روند (عدد ثابت در کد).
- هر متن به ۵۰۰ کاراکتر اول بریده می‌شود.
- سرویس AI با Cross-Encoder `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` امتیاز می‌دهد.
- نگاشت امتیاز بر اساس **متن** انجام می‌شود، نه شناسه؛ بنابراین اگر دو Chunk متن یکسان داشته باشند، یک امتیاز می‌گیرند.
- خروجی نهایی بر اساس `rerank_score` نزولی مرتب و به `limit` بریده می‌شود.

### پیامد مهم

اگر `top_k` بزرگ‌تر از ۵ باشد (تا ۵۰ مجاز است)، در عمل حداکثر ۵ نتیجه برمی‌گردد، چون فقط ۵ کاندید Rerank می‌شوند. برای تغییر این رفتار باید `rerank_candidates = fused_results[:5]` پارامتردار شود.

## ۷. ساخت Prompt

```python
context_parts.append(f"[{chunk_id}]\n{content}")
```

Prompt شامل:

- نقش: دستیار پرسش‌وپاسخ اسناد سازمانی
- محدودیت: فقط از context استفاده کن
- پرسش کاربر
- context با شناسه Chunk
- قواعد ارجاع: بعد از هر جمله، شناسه Chunk در براکت، بدون اختراع شناسه

Prompt به `/api/llm/` یا `/api/llm/stream/` فرستاده می‌شود. ارائه‌دهنده با `LLM_PROVIDER` انتخاب می‌شود:

- `ollama` → `POST {LLM_BASE_URL}/generate`
- `openai_compatible` → `POST {LLM_BASE_URL}/chat/completions`

## ۸. استخراج و اعتبارسنجی Citation

```python
re.findall(r"\[(\d+)\]", answer)
```

- شناسه‌ها یکتا و مرتب می‌شوند.
- `build_citations` آن‌ها را با دیتابیس تطبیق می‌دهد و فقط Chunkهای مجاز را برمی‌گرداند.
- اگر کاربر دپارتمان داشته باشد، فیلتر دپارتمان اعمال می‌شود. اگر نداشته باشد (مثلاً Admin بدون دپارتمان)، فیلتر دپارتمان اعمال نمی‌شود و محدوده Tenant کافی است.
- شناسه‌های اختراعی LLM بی‌صدا حذف می‌شوند؛ بنابراین ممکن است پاسخ دارای `[999]` باشد اما `citations` خالی بماند.

شکل Citation:

```json
{
  "document_id": 12,
  "title": "Employee Handbook",
  "filename": "handbook.pdf",
  "department": "IT",
  "chunk_id": 340,
  "chunk_index": 7,
  "snippet": "Employees may work remotely up to two days per week..."
}
```

`title`، `chunk_index` و `snippet` اضافه شده‌اند تا UI بتواند بدون درخواست دوم، کارت منبع و پیش‌نمایش را نشان دهد. متن کاملِ Chunk از `GET /api/documents/chunks/{chunk_id}/` خوانده می‌شود.

### نکته طراحی: شماره‌گذاری منابع

مدل، **شناسه Chunk** را در براکت می‌گذارد (`[340]`)، نه شماره ترتیبی منبع. بنابراین فهرست منابع هم همان عدد را نشان می‌دهد و منابع را ۱..N شماره‌گذاری نمی‌کند. اگر این دو از هم جدا می‌شدند، `[340]` در متن به کارت پنجم اشاره می‌کرد و کاربر گم می‌شد.

## ۹. جریان SSE

`chat_ask_view` یک `StreamingHttpResponse` با `text/event-stream` برمی‌گرداند.

| رویداد | داده | معنا |
|---|---|---|
| `token` | `{"content": "..."}` | تکه متن پاسخ |
| `citations` | آرایه Citation | منابع پاسخ کامل |
| `error` | `{"error": "..."}` | خطا در بازیابی یا LLM |
| `done` | `{}` | پایان موفق |

ترتیب معمول: چند `token`، سپس `citations`، سپس `done`.

نکات پیاده‌سازی:

- `requests` با `stream=True` و `timeout=(10, 360)` به سرویس AI وصل می‌شود.
- پاسخ LLM به‌صورت متن خام خوانده و همان‌جا به رویداد `token` تبدیل می‌شود.
- در خطا، رویداد `error` ارسال می‌شود؛ در این حالت `done` ارسال نمی‌شود.
- اگر سندی پیدا نشود، تنها یک رویداد `error` با پیام «No relevant documents were found.» می‌آید.

### مصرف در کلاینت

```javascript
const response = await fetch(`${API_BASE_URL}/chat/ask/`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({ question, conversation_id }),
});
```

سپس بدنه را به‌صورت stream بخوانید و بلوک‌های `event:` / `data:` را جدا کنید.

## ۱۰. هزینه و تأخیر

| مرحله | هزینه تقریبی | توضیح |
|---|---|---|
| Embedding پرسش | کم | با `lru_cache` برای پرسش‌های تکراری کش می‌شود |
| Vector search | متوسط | بسته به حجم و `ef_search` |
| Keyword search | کم تا متوسط | GIN index |
| Rerank | متوسط | فراخوانی مدل Cross-Encoder |
| LLM | زیاد | وابسته به مدل و طول context |

گلوگاه اصلی، `Semaphore(1)` در سرویس AI است: Embedding، Vector Search (فقط encode) و Rerank به‌صورت سریالی اجرا می‌شوند.

## ۱۱. پارامترهای قابل تنظیم

| پارامتر | محل | پیش‌فرض |
|---|---|---|
| وزن معنایی | `api/services.py` → `0.7 * semantic_score` | ۰٫۷ |
| وزن کلیدواژه | `api/services.py` → `0.3 * keyword_score` | ۰٫۳ |
| پاداش تطابق مستقیم | `api/services.py` → `score += 0.2` | ۰٫۲ |
| ضریب کاندید اولیه | `initial_limit = limit * 3` | ۳ |
| تعداد کاندید Rerank | `fused_results[:5]` | ۵ |
| برش متن Rerank | `result["content"][:500]` | ۵۰۰ کاراکتر |
| `top_k` | Serializer | ۵ (حداکثر ۵۰) |
| محدودیت چت | `RateLimitConfig` | ۵۰ / ۲۰۰ در ساعت |

## ۱۲. دیباگ

### بررسی مستقیم سرویس AI

```bash
curl -s -X POST http://127.0.0.1:8001/api/embed/ \
  -H "Content-Type: application/json" \
  -d '{"texts":["hello"]}' | head -c 200
```

```bash
curl -s -X POST http://127.0.0.1:8001/api/vector-search/ \
  -H "Content-Type: application/json" \
  -d '{"query":"policy","tenant_id":1,"allowed_department_ids":[1],"limit":5}'
```

### بررسی داده

```python
from documents.models import Document, DocumentChunk, Embedding

Document.objects.filter(status="Indexed").count()
DocumentChunk.objects.count()
Embedding.objects.count()
```

اگر تعداد Embedding کمتر از Chunk است، سند در وضعیت `Processing` می‌ماند یا batchی شکست خورده است.

### بررسی خروجی خالی

1. آیا کاربر `department_id` دارد؟
2. آیا سند در همان دپارتمان و Tenant است؟
3. آیا وضعیت سند `Indexed` است؟
4. آیا سرویس AI به دیتابیس دسترسی دارد؟ (`GET /api/db/test/`)
5. آیا `AI_SERVICE_URL` درست است؟

## ۱۳. محدودیت‌های شناخته‌شده

- جست‌وجو فقط در دپارتمان کاربر انجام می‌شود؛ اسناد `is_public` دپارتمان‌های دیگر در مرحله بازیابی برنمی‌گردند، هرچند فیلتر نهایی View آن‌ها را مجاز می‌داند.
- Rerank فقط روی ۵ کاندید اجرا می‌شود.
- `top_k` بزرگ‌تر از ۵ عملاً محدود می‌شود.
- `/api/search/` امتیاز ادغام‌شده را برمی‌گرداند، نه امتیاز Rerank.
- تاریخچه مکالمه ذخیره نمی‌شود.

## ۱۴. سنجش کیفیت

کیفیت همین pipeline با یک سیستم ارزیابی خودکار اندازه‌گیری می‌شود: faithfulness (وفاداری پاسخ به context)، answer relevancy، context precision و answer correctness. جزئیات، دیتاست مرجع و قالب گزارش در [14-evaluation.md](14-evaluation.md) آمده است.
