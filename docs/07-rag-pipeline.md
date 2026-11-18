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

### شروع سرد: وقتی چیزی برای بازیابی نیست

دو دروازه پیش از هر فراخوانی شبکه‌ای وجود دارد. هر دو در `api/services.py` هستند و نتیجه‌شان یکسان است: **صفر فراخوانی AI**.

| دروازه | بررسی | هزینه | پوشش |
|---|---|---|---|
| `department_has_searchable_content` | `EXISTS` روی `DocumentChunk` | یک کوئری ایندکس‌شده | دپارتمان بدون Chunk |
| نتیجه خالی `hybrid_search` | لیست نتایج `[]` | صفر | دپارتمان پر، ولی بی‌ربط |

دروازه اول لازم است چون `semantic_search` پیش از جست‌وجو یک Embedding برای پرسش می‌سازد؛ در دپارتمان خالی این کار نتیجه‌ای ندارد ولی هزینه و تأخیر دارد. یک `EXISTS ... LIMIT 1` این هزینه را کامل حذف می‌کند.

بررسی روی **Chunk** انجام می‌شود نه روی Document: سندی که هنوز `Pending` است Chunk ندارد و عملاً نمی‌تواند پاسخ دهد.

هر سه فیلتر `DocumentChunk` در این فایل دو شرط اضافه هم دارند: `.exclude(document__status=ARCHIVED_STATUS)` و `is_active=True`. نسخه‌های قدیمی سند (`Archived`) Chunk خود را نگه می‌دارند تا تاریخچه از بین نرود، پس بدون شرط اول دروازهٔ شروع سرد و هر دو مسیر بازیابی آن‌ها را «محتوای قابل جست‌وجو» می‌دیدند. شرط دوم لایهٔ دائمی‌تر است: به `status` سند کاری ندارد و خودِ Chunk را می‌سنجد، پس اگر نسخه‌ای از آرشیو بیرون بیاید، متنش برمی‌گردد ولی Chunkهای کنارگذاشته‌شده نه.

همین دروازه در دو endpoint فقط-جست‌وجو هم اعمال می‌شود: `POST /api/search/` و `POST /api/query/search/`. این دو مدل زبانی را صدا نمی‌زنند، اما `hybrid_search` پیش از جست‌وجو یک Embedding برای پرسش می‌سازد؛ در دپارتمان خالی آن رفت‌وبرگشت به AI service نتیجه‌اش تغییرناپذیر است. پاسخ همان `results: []` قبلی است و در `/api/query/search/` ردیف `SearchQuery` با صفر نتیجه همچنان ثبت می‌شود تا آمار جست‌وجو کامل بماند.

خروجی هر دو حالت یکسان است:

```python
{"type": "no_documents", "reason": EMPTY_DEPARTMENT | NO_MATCHING_CHUNKS, "message": NO_DOCUMENTS_MESSAGE}
{"type": "done"}
```

قواعد مهم:

- `reason` ماشین‌خوان است تا رابط کاربری بین «سند آپلود کن» و «پرسش را جور دیگری بپرس» تفکیک کند.
- جریان **همیشه** با `done` تمام می‌شود؛ بدون آن نشانگر «در حال فکر کردن» در کلاینت هرگز خاموش نمی‌شود.
- هیچ ردیفی در `ChatAnswer` نوشته نمی‌شود: پاسخ خالی برای آموزش بی‌ارزش است و `answer_id` نباید قابل ثبت بازخورد باشد.
- در `/api/query/ask/` همین اطلاعات در بدنه پاسخ با `no_documents`، `reason` و `answer_id: null` برمی‌گردد.

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
  AND d.status <> 'Archived'
  AND c.is_active
ORDER BY e.embedding_vector <=> %s::vector
LIMIT %s
```

هر دو شرط پیش از `ORDER BY` گذاشته شده‌اند تا سطرهای منسوخ پیش از محاسبهٔ فاصله حذف شوند؛ اگر بعد از `LIMIT` فیلتر می‌شدند، نسخه‌های `Archived` سهمیهٔ `limit` را می‌خوردند و ممکن بود نسخهٔ جاری بیرون بیفتد.

سپس Django نتایج را **دوباره از دیتابیس** می‌خواند و فقط Chunkهایی را می‌پذیرد که:

- `document.tenant_id == tenant_id`
- `document.department_id == department_id`
- `document.department.tenant_id == tenant_id`
- `document.status != Archived`
- `chunk.is_active` (Chunk کنارگذاشته‌شده هرگز به LLM نمی‌رسد)

آخرین شرط «دفاع در عمق» است: سرویس AI هم `Archived` و Chunkهای غیرفعال را حذف می‌کند، ولی فیلتر دوم در Django تضمین می‌کند اگر سرویس AI نسخهٔ قدیمی کوئری را اجرا کند یا کش شود، سند منسوخ باز هم به LLM نرسد.

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
- `.exclude(document__status=ARCHIVED_STATUS)` و `is_active=True`، با همان استدلال مسیر معنایی.
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

### تلهٔ min-max: امتیاز نسبی، نه مطلق

نرمال‌سازی **نسبی** است: بهترین نتیجهٔ هر کوئری همیشه `1.0` می‌شود، حتی اگر بدترین نتیجهٔ ممکن باشد. اگر جست‌وجوی برداری فقط یک Chunk برگرداند، `max == min` و آن یک Chunk هم `1.0` می‌گیرد → امتیاز نهایی `0.7`.

یعنی امتیاز ادغام به این سؤال جواب نمی‌دهد که «آیا چیزی مرتبط هست؟»؛ فقط می‌گوید «بهترینِ این کوئری». بدون یک سیگنال مطلق، بی‌ربط‌ترین Chunk هم به مدل می‌رسد و مدل از روی آن جواب می‌سازد. به همین دلیل امتیاز خام معنایی (`1 - distance`) جدا نگه داشته می‌شود و در پایان یک **آستانهٔ مطلق** اعمال می‌شود.

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

### آستانهٔ ارتباط (Relevance Floor)

```python
if reranked_by_model:
    score_key, floor = "rerank_score", RAG_MIN_RERANK_SCORE
else:
    score_key, floor = "semantic_similarity", RAG_MIN_SEMANTIC_SIMILARITY

literal = query.strip().casefold()

kept = [
    item for item in reranked_results
    if item.get(score_key, 0.0) >= floor
    or (len(literal) >= 3 and literal in item["content"].casefold())
]
```

اگر هیچ نتیجه‌ای از آستانه رد نشود، لیست خالی برمی‌گردد و مسیر `no_match` فعال می‌شود: همان پیام «سندی یافت نشد»، بدون فراخوانی مدل زبانی.

### استثنای تطابق لفظی

یک نتیجه‌ای که متن پرسش عیناً داخلش آمده، هرگز «بی‌ربط» نیست — حتی اگر Cross-Encoder امتیاز منفی بدهد.

این استثنا از یک باگ واقعی آمد: پرسش «بلبرینگ» از یک CSV قیمت، با تطابق دقیق کلمه در سلول، امتیاز Reranker `-1.248` گرفت و آستانهٔ `-1.0` آن را انداخت؛ نتیجه: «هیچ سندی در دانش شما یافت نشد» برای کلمه‌ای که کاربر با چشم خودش در سند می‌بیند. دلیلش این است که Cross-Encoder عمدتاً روی نثر انگلیسی آموزش دیده و یک ردیف جدول فارسی (`| بلبرینگ | 45 | یورو |`) برایش متن کوتاه و بی‌بافت است.

قواعد استثنا:

- مقایسه بدون حساسیت به حروف است (`casefold` در دو طرف).
- پرسش کوتاه‌تر از ۳ کاراکتر مستثنا نمی‌شود؛ «a» تقریباً در هر متنی هست و استثنا کردنش آستانه را عملاً خاموش می‌کند.
- فقط همان نتیجه‌ای که متن پرسش را دارد نگه داشته می‌شود؛ بقیه همچنان با آستانه سنجیده می‌شوند.
- هر بار که نتیجه‌ای این‌طور نجات پیدا کند، در لاگ ثبت می‌شود (`Kept N result(s) below the … floor …`) تا اگر شمارش بالا رفت، نشانهٔ کالیبراسیون اشتباه باشد نه رفتار درست.

دو تنظیم جدا، چون دو مقیاس جدا:

| مسیر | سیگنال | پیش‌فرض | معنی |
|---|---|---|---|
| Reranker فعال | `rerank_score` (logit) | `-1.0` | آستانهٔ مطلق روی امتیاز Cross-Encoder |
| Reranker خاموش | `semantic_similarity` (کسینوسی) | `0.0` | عملاً خاموش |

**چرا پیش‌فرض مسیر دوم صفر است:** کسینوسی `multilingual-e5-small` فشرده است (۰٫۷۱ تا ۰٫۹۲ روی پیکرهٔ همین پروژه). آستانه‌ای که متن بی‌ربط را بیندازد، بازنویسی مرتبط را هم می‌اندازد. پس به‌جای یک عدد بی‌پشتوانه، رفتار قبلی حفظ شده و تنظیمش به اندازه‌گیری روی دادهٔ خودتان سپرده شده است.

**چرا `-1.0` و نه `0.0`:** جدول کالیبراسیون روی همین استک، با همین پایپ‌لاین:

| نوع | امتیاز |
|---|---|
| مرتبط، تطابق دقیق | `+6.59` |
| مرتبط، بازنویسی فارسی | `+5.56` |
| مرتبط، بازنویسی انگلیسی | `+1.10` |
| مرتبط، بازنویسی فارسی (ضعیف) | `-0.35` |
| مرتبط، تطابق لفظی در یک ردیف جدول فارسی | `-1.25` |
| بی‌ربط | `-2.13` / `-2.18` / `-3.56` / `-5.46` |

شکافی که باید حفظ شود بین `-0.35` و `-2.13` است. `0.0` آن بازنویسی فارسی را می‌انداخت و این یک محصول فارسی‌محور است؛ `-1.0` وسط شکاف با یک logit حاشیه در دو طرف است. هر دو مقدار با `RAG_MIN_RERANK_SCORE` و `RAG_MIN_SEMANTIC_SIMILARITY` قابل تغییرند.

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
