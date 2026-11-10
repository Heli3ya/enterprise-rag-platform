# ۰۹ — فرانت‌اند

## ۱. پشته

| مورد | نسخه / انتخاب |
|---|---|
| Next.js | 16.4.3 (App Router) |
| React | 19.2.8 |
| زبان | TypeScript 5 |
| استایل | Tailwind CSS 4 |
| نمودار | Recharts 3 |
| HTTP | Axios 1.20 |
| آیکون/UI | کامپوننت‌های داخلی، بدون کتابخانه UI |
| پایش | Sentry (`@sentry/nextjs`) |
| لینت/فرمت | Biome 2.5 |
| تست E2E | Playwright 1.64 |

## ۲. ساختار

```text
frontend/
├── app/
│   ├── layout.tsx          ریشه، AuthProvider، فونت و استایل
│   ├── page.tsx            صفحه اصلی (آپلود + چت) — محافظت‌شده
│   ├── login/page.tsx      ورود
│   ├── admin/page.tsx      داشبورد تحلیلی — فقط Admin
│   └── globals.css
├── components/
│   ├── AuthProvider.tsx    Context کاربر و localStorage
│   ├── withAuth.tsx        HOC محافظت از صفحات
│   ├── ChatWindow.tsx      چت جریانی و مدیریت Citation
│   ├── AnswerContent.tsx   رندر پاسخ با مارکرهای کلیک‌پذیر `[n]`
│   ├── CitationList.tsx    کارت‌های منابع زیر پاسخ
│   ├── CitationPanel.tsx   کشوی منبع: متن Chunk + هایلایت + فایل اصلی
│   ├── HighlightedText.tsx رندر بازه‌های هایلایت با <mark>
│   ├── DocumentUploader.tsx آپلود، لیست و حذف سند
│   └── Button.tsx
├── lib/api.ts              کلاینت Axios، refresh، authorizedFetch، openAuthenticatedFile
├── lib/citations.ts        تایپ‌ها و parseAnswerSegments
├── lib/highlight.ts        اعتبارسنجی و برش بازه‌های هایلایت
├── e2e/                    تست‌های Playwright
└── sentry.*.config.ts      پیکربندی Sentry
```

## ۳. مسیرها

| مسیر | دسترسی | محتوا |
|---|---|---|
| `/login` | عمومی | فرم ورود؛ پس از موفقیت: Admin → `/admin`، Member → `/` |
| `/` | نیازمند ورود | آپلود سند، لیست اسناد، پنجره چت |
| `/admin` | فقط Admin | آمار سند و جست‌وجو، نمودار دپارتمان، جست‌وجوهای اخیر |

`/admin` در سمت کلاینت با `GET /auth/me/` بررسی می‌کند و در صورت نقش غیر Admin، به `/` هدایت می‌کند. این محافظت UX است، نه امنیت؛ کنترل واقعی در بک‌اند انجام می‌شود.

## ۴. جریان احراز هویت

```text
LoginPage
  ├─ POST /auth/login/ {username, password}
  ├─ ذخیره access_token و refresh_token در localStorage
  ├─ GET /auth/me/
  ├─ اعتبارسنجی role ∈ {Admin, Member}
  ├─ ذخیره user در localStorage و Context
  └─ redirect بر اساس نقش
```

`withAuth` در هر بار mount:

1. وجود `access_token` را بررسی می‌کند؛ نبود آن → `/login`.
2. `GET /auth/me/` را صدا می‌زند.
3. در موفقیت `setUser` و ادامه رندر.
4. در خطا توکن‌ها و user را پاک و به `/login` هدایت می‌کند.

### مدیریت توکن در `lib/api.ts`

- `baseURL` از `NEXT_PUBLIC_API_BASE_URL`.
- در Request Interceptor: اگر توکن تا ۶۰ ثانیه دیگر منقضی شود، از قبل refresh می‌کند.
- `refreshPromise` از ارسال چند refresh هم‌زمان جلوگیری می‌کند.
- در Response Interceptor: روی `401` یک‌بار refresh و درخواست اصلی را تکرار می‌کند؛ اگر refresh شکست بخورد، توکن‌ها پاک و به `/login` می‌رود.
- درخواست‌های `/auth/login/` و `/auth/refresh/` از این چرخه مستثنی هستند.

> توکن‌ها در `localStorage` نگه‌داری می‌شوند. این ساده‌ترین پیاده‌سازی است اما در برابر XSS آسیب‌پذیر است. گزینه امن‌تر، کوکی `HttpOnly` است.

### خروج از حساب

در UI فعلی دکمه خروج وجود ندارد. `clearUser` فقط `user` را از Context و localStorage پاک می‌کند و توکن‌ها را حذف نمی‌کند. برای خروج کامل باید توکن‌ها هم پاک شوند.

## ۵. ChatWindow

- `conversation_id` یک‌بار در mount با `Date.now()` و رشته تصادفی ساخته می‌شود.
- درخواست با `fetch` مستقیم (نه Axios) به `${API_BASE_URL}/chat/ask/` ارسال می‌شود، چون به stream نیاز دارد؛ اما از `authorizedFetch` در `lib/api.ts` استفاده می‌کند تا refresh توکن و یک retry روی `401` هم پوشش داده شود.
- بدنه با `ReadableStream` خوانده و بر اساس جداکننده `\n\n` به رویدادها تقسیم می‌شود.
- `event:` و `data:` استخراج و بر اساس نوع پردازش می‌شوند.
- در `error` یک استثنا پرتاب می‌شود و پیام خطا در UI نمایش داده می‌شود.

### Clickable Citations

سه قطعه درگیرند:

| قطعه | نقش |
| --- | --- |
| `lib/citations.ts` | `parseAnswerSegments` متن پاسخ را به تکه‌های متن و مارکر `[n]` می‌شکند؛ `indexCitations` نقشه `chunk_id → Citation` می‌سازد |
| `AnswerContent.tsx` | مارکرهایی که Citation متناظر دارند را به دکمه تبدیل می‌کند؛ مارکر بی‌منبع (مثلاً `[999]` اختراعی) متن ساده می‌ماند |
| `CitationPanel.tsx` | کشوی سمت راست با دو تب: «In the document» (متن کل سند از `/documents/{id}/preview/?q=`) و «Cited passage» (خودِ Chunk از `/documents/chunks/{id}/?q=`) |
| `HighlightedText.tsx` + `lib/highlight.ts` | بازه‌های `highlights` را به `<mark>` تبدیل می‌کنند؛ بازه نامعتبر یا خارج از متن نادیده گرفته می‌شود |

نکات پیاده‌سازی:

- شماره‌گذاری منابع ۱..N **نیست**؛ همان `chunk_id` است تا با `[n]` داخل متن یکی باشد.
- متن کامل Chunk از سرور خوانده می‌شود، نه از `snippet`؛ `snippet` فقط پیش‌نمایش کارت منبع و حالت بارگذاری است.
- هایلایت در بک‌اند محاسبه می‌شود (`documents/highlighting.py`)، چون همان توکن‌بندی و نرمال‌سازی جست‌وجو را دارد. فرانت‌اند فقط رشته را با offsetها می‌بُرد.
- کشو روی تب «In the document» باز می‌شود و بعد از لود متن، خودکار تا اولین `<mark>` اسکرول می‌کند (`scrollTop` روی کانتینر، نه `scrollIntoView`، تا صفحه اصلی جابه‌جا نشود).
- برای PDF و DOCX که مرورگر رندر مستقیم ندارد، همین تب متن استخراج‌شده را نشان می‌دهد؛ «Open original file» همیشه فایل خام را در تب جدید باز می‌کند.
- `file_url` و `preview_url` نسبت به ریشه API هستند (`/documents/30/file/`)، پس فرانت‌اند `API_BASE_URL` را جلویشان می‌گذارد. اگر با `/api` برمی‌گشتند، درخواست به `/api/api/...` می‌رفت و `404` می‌داد.
- `ChatWindow` سؤال هر پاسخ را در `message.question` نگه می‌دارد و هنگام کلیک روی منبع، آن را به کشو می‌دهد؛ بدون این، سرور نمی‌داند چه چیزی را هایلایت کند.
- زیر متن، خط «Highlighted: …» واژه‌های واقعاً پیداشده را نشان می‌دهد؛ اگر تطابق صرفاً معنایی باشد این خط نمایش داده نمی‌شود.
- بستن کشو با کلید `Escape`، کلیک روی پس‌زمینه، یا دکمه Close.
- دانلود فایل اصلی از `openAuthenticatedFile` استفاده می‌کند: چون لینک ساده نمی‌تواند هدر `Authorization` بفرستد، فایل با `fetch` گرفته و به‌صورت Blob در تب جدید باز می‌شود؛ اگر مرورگر popup را بلاک کند، دانلود جایگزین می‌شود.

### Answer Feedback (👍/👎)

| قطعه | نقش |
| --- | --- |
| `lib/feedback.ts` | `submitAnswerFeedback` روی `authorizedFetch`؛ نگاشت کد وضعیت به دلیل قابل ترجمه؛ حافظه‌ی محدود از پاسخ‌های امتیازداده‌شده |
| `AnswerFeedback.tsx` | دکمه‌های 👍/👎، فرم دلیل، ماشین حالت `idle → submitting → done / error` |
| `ChatWindow.tsx` | رویداد `meta` را می‌خواند و `answerId` را روی همان پیام نگه می‌دارد |

- `answer_id` فقط از رویداد `meta` می‌آید. تا وقتی نرسیده ویجت رندر نمی‌شود، تا هیچ‌وقت دکمه‌ی بی‌عمل روی صفحه نباشد.
- 👍 با یک کلیک و یک درخواست ثبت می‌شود. 👎 اول کادر دلیل را باز می‌کند و بعد یک درخواست می‌فرستد؛ دلیل اختیاری است چون سرور هم `user_comment` را با `allow_blank` می‌پذیرد.
- `409` خطا نیست: یعنی همین کاربر قبلاً به همین پاسخ رأی داده است. UI آن را «موفق» تلقی می‌کند تا حالت نهایی در هر دو مسیر یکسان باشد و کاربر بی‌دلیل retry نکند.
- `400/401/403/404/429/5xx/network` به دلیل‌های مجزا نگاشت می‌شوند و متن خطا از `i18n` می‌آید، نه از سرور؛ بنابراین با تغییر زبان، خطا هم دوباره ترجمه می‌شود.
- پس از موفقیت هر دو دکمه `disabled` می‌شوند و پیام «از بازخورد شما سپاسگزاریم.» با `role="status"` نمایش داده می‌شود — بدون رفرش صفحه و بدون از دست رفتن اسکرول یا تاریخچه‌ی چت.
- `localStorage` (کلید `chat_feedback_rated`، حداکثر ۲۰۰ شناسه، قدیمی‌ترین حذف می‌شود) فقط یک راهنمای UI است تا بعد از رفرش دکمه‌ها برنگردند؛ منبع حقیقت همان `UniqueConstraint` سرور است.
- پاسخِ ناتمام (`isStreaming`) یا ناموفق (`failed`) اصلاً دکمه نمی‌گیرد: یا رکوردی ذخیره نشده، یا `is_complete=False` است و نباید وارد داده‌ی آموزش شود.
- ارسال با یک `ref` قفل می‌شود (`inFlight`)، چون دو کلیک در یک tick هر دو `phase` قدیمی را می‌خوانند و دو درخواست می‌فرستند.
- حداکثر طول متن دلیل در هر دو سمت ۲۰۰۰ کاراکتر است (`MAX_COMMENT_LENGTH` ↔ `FeedbackCreateSerializer`).

## ۶. DocumentUploader

- دپارتمان‌ها: `GET /departments/`
- اسناد: `GET /documents/`
- آپلود: `POST /documents/` با `FormData` شامل `title`، `department`، `file_path`
- حذف: `DELETE /documents/{id}/delete/`
- پذیرش فایل در سمت کلاینت: `.pdf`، `.doc`، `.docx`، `.txt`
- نمایش اندازه فایل و وضعیت سند
- پس از آپلود، لیست دوباره خوانده می‌شود

اعتبارسنجی سمت کلاینت فقط برای تجربه کاربری است؛ مرجع نهایی، Serializer بک‌اند است.

## ۷. داشبورد ادمین

- `GET /auth/me/` برای بررسی نقش
- `GET /admin/analytics/` برای داده
- کارت‌های خلاصه: تعداد سند، حجم کل، تعداد جست‌وجو
- نمودار میله‌ای/دایره‌ای با Recharts بر اساس دپارتمان
- جدول ۱۰ جست‌وجوی اخیر

اگر API خطا بدهد، پیام خطا و دکمه تلاش مجدد نمایش داده می‌شود.

## ۸. متغیرهای محیطی

| متغیر | الزامی | توضیح |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | توصیه‌شده | باید شامل `/api` باشد، مثلاً `http://127.0.0.1:8000/api` |
| `NEXT_PUBLIC_SENTRY_DSN` | اختیاری | DSN سمت کلاینت |
| `SENTRY_AUTH_TOKEN` | اختیاری | آپلود Source Map در Build |

فایل `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api
```

## ۹. اسکریپت‌ها

```bash
npm run dev      # اجرای توسعه روی :3000
npm run build    # Build تولیدی
npm run start    # اجرای Build
npm run lint     # Biome check
npx playwright test
```

## ۱۰. تست E2E

- `e2e/homepage.spec.ts`
- `e2e/full-user-flow.spec.ts`
- `e2e/chat-feedback.spec.ts` — سه مسیر: 👎 با دلیل، 👍 تک‌کلیکی، و خطای سرور با فعال‌شدن دوباره‌ی دکمه‌ها

Playwright سرور توسعه را خودش بالا می‌آورد (`webServer`)، `baseURL` روی `http://127.0.0.1:3000` است و در CI دو بار retry می‌کند.

پیش‌نیاز اجرای موفق: بک‌اند و سرویس AI در دسترس، و یک کاربر معتبر برای سناریوی ورود.

## ۱۱. نکات توسعه

- همه صفحات تعاملی `"use client"` هستند؛ این پروژه از Server Component برای داده‌گیری استفاده نمی‌کند.
- استایل‌ها با کلاس‌های Tailwind و بدون فایل CSS اختصاصی نوشته شده‌اند.
- برای اضافه کردن صفحه محافظت‌شده:

```tsx
function MyPage() { /* ... */ }
export default withAuth(MyPage);
```

- برای مسیر فقط-Admin، علاوه بر `withAuth`، نقش را از `useAuth()` بررسی کنید و در بک‌اند هم مجوز را اعمال کنید.
- پیام‌های خطا را به کاربر نشان دهید؛ `console.error` تنها کافی نیست.
