# مستندات Enterprise RAG Platform

این پوشه مستندات فنی پروژه را نگه می‌دارد. هر سند مستقل قابل مطالعه است، اما ترتیب پیشنهادی زیر برای افراد جدید در تیم سریع‌ترین مسیر است.

## فهرست اسناد

| # | سند | برای چه کسی | خلاصه |
|---|---|---|---|
| ۰۱ | [01-overview.md](01-overview.md) | همه | پروژه چه کاری می‌کند، اجزا و جریان‌های اصلی |
| ۰۲ | [02-architecture.md](02-architecture.md) | توسعه‌دهنده بک‌اند و معمار | لایه‌ها، مرزهای اعتماد، تصمیمات طراحی |
| ۰۳ | [03-getting-started.md](03-getting-started.md) | توسعه‌دهنده جدید | راه‌اندازی محیط توسعه |
| ۰۴ | [04-api-reference.md](04-api-reference.md) | بک‌اند و فرانت‌اند | قرارداد کامل endpointها |
| ۰۵ | [05-data-model.md](05-data-model.md) | بک‌اند و DBA | مدل داده، ایندکس‌ها، مهاجرت‌ها |
| ۰۶ | [06-document-pipeline.md](06-document-pipeline.md) | بک‌اند و عملیات | آپلود تا ایندکس شدن سند |
| ۰۷ | [07-rag-pipeline.md](07-rag-pipeline.md) | تیم AI و بک‌اند | بازیابی، ادغام، Rerank و Citation |
| ۰۸ | [08-security.md](08-security.md) | همه، به‌ویژه عملیات | احراز هویت، مجوز، چند-مستأجری |
| ۰۹ | [09-frontend.md](09-frontend.md) | فرانت‌اند | ساختار Next.js و جریان توکن |
| ۱۰ | [10-testing.md](10-testing.md) | همه | تست، CI، بارگذاری |
| ۱۱ | [11-deployment.md](11-deployment.md) | عملیات و DevOps | توپولوژی، استقرار، نگهداری |
| ۱۲ | [12-troubleshooting.md](12-troubleshooting.md) | عملیات و توسعه‌دهنده | خطاهای رایج و راه‌حل |
| ۱۳ | [13-known-issues.md](13-known-issues.md) | همه | محدودیت‌ها و بدهی فنی |
| ۱۴ | [14-evaluation.md](14-evaluation.md) | تیم AI و کیفیت | سنجش وفاداری و دقت پاسخ، دیتاست مرجع، گزارش |
| — | [CONTRIBUTING.md](CONTRIBUTING.md) | مشارکت‌کننده | قواعد کد، تست و PR |

## مسیرهای مطالعه پیشنهادی

**توسعه‌دهنده جدید بک‌اند**

1. [01-overview.md](01-overview.md)
2. [03-getting-started.md](03-getting-started.md)
3. [02-architecture.md](02-architecture.md)
4. [05-data-model.md](05-data-model.md)
5. [04-api-reference.md](04-api-reference.md)

**توسعه‌دهنده فرانت‌اند**

1. [01-overview.md](01-overview.md)
2. [04-api-reference.md](04-api-reference.md)
3. [09-frontend.md](09-frontend.md)
4. [08-security.md](08-security.md) بخش احراز هویت

**تیم عملیات / DevOps**

1. [11-deployment.md](11-deployment.md)
2. [deploy/DEPLOYMENT.md](../deploy/DEPLOYMENT.md)
3. [08-security.md](08-security.md)
4. [12-troubleshooting.md](12-troubleshooting.md)

**تیم داده / AI**

1. [06-document-pipeline.md](06-document-pipeline.md)
2. [07-rag-pipeline.md](07-rag-pipeline.md)
3. [05-data-model.md](05-data-model.md)
4. [14-evaluation.md](14-evaluation.md)

## قواعد نگهداری مستندات

- هر تغییر در رفتار API، مدل داده، پارامترهای پردازش یا پیکربندی باید در همان Pull Request مستند شود.
- مستندات باید رفتار **فعلی کد** را توصیف کنند، نه نقشه راه.
- برای ایده‌ها و کارهای آینده از [13-known-issues.md](13-known-issues.md) یا Issue tracker استفاده کنید.
- نمونه‌ها نباید شامل Secret، رمز واقعی یا توکن باشند.
- مسیرها و نام فایل‌ها را دقیقاً مطابق مخزن بنویسید (حساس به حروف در Linux).
