/**
 * Minimal, dependency-free internationalisation layer.
 *
 * Keys are the English source strings, so a missing translation degrades
 * to readable English instead of a raw key such as `chat.send`. That keeps
 * the UI usable even when a new string has not been translated yet.
 */

export type Locale = "en" | "fa";

export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_STORAGE_KEY = "app_locale";

export const LOCALES: { value: Locale; label: string; short: string }[] = [
	{ value: "en", label: "English", short: "EN" },
	{ value: "fa", label: "فارسی", short: "FA" },
];

export function isLocale(value: unknown): value is Locale {
	return value === "en" || value === "fa";
}

export function localeDirection(locale: Locale): "ltr" | "rtl" {
	return locale === "fa" ? "rtl" : "ltr";
}

/** Persian translations keyed by the English source string. */
const FA: Record<string, string> = {
	// -- shared ------------------------------------------------------
	"Enterprise RAG Platform": "پلتفرم RAG سازمانی",
	"Document Knowledge Base & Enterprise RAG":
		"پایگاه دانش اسناد و RAG سازمانی",
	"Logged in as": "وارد شده به عنوان",
	"Log out": "خروج",
	"Upload Document": "بارگذاری سند",
	"Chat Assistant": "دستیار گفتگو",
	"Ask questions about your enterprise documents":
		"درباره اسناد سازمانی خود سؤال بپرسید",
	"Type your question...": "سؤال خود را بنویسید...",
	Send: "ارسال",
	"Sending...": "در حال ارسال...",
	You: "شما",
	Assistant: "دستیار",
	"Press Enter to send · Shift + Enter for a new line":
		"برای ارسال Enter بزنید · برای خط جدید Shift + Enter",
	Sources: "منابع",
	"Hello! I am your Enterprise RAG Assistant. How can I help you?":
		"سلام! من دستیار RAG سازمانی شما هستم. چطور می‌توانم کمک کنم؟",
	"Sorry, an error occurred:": "متأسفم، خطایی رخ داد:",
	"An unexpected error occurred.": "یک خطای غیرمنتظره رخ داد.",
	"An error occurred during the chat.": "خطایی در گفتگو رخ داد.",
	"Streaming response is not available.":
		"پاسخ جریانی در دسترس نیست.",
	"An unexpected error occurred": "یک خطای غیرمنتظره رخ داد",

	// -- preferences / header ---------------------------------------
	Language: "زبان",
	"Theme": "پوسته",
	"Switch to English": "تغییر به انگلیسی",
	"Switch to Persian": "تغییر به فارسی",
	"Switch to dark mode": "تغییر به حالت تاریک",
	"Switch to light mode": "تغییر به حالت روشن",
	"Language and theme": "زبان و پوسته",

	// -- login -------------------------------------------------------
	Login: "ورود",
	"Sign in to Enterprise RAG Platform": "ورود به پلتفرم RAG سازمانی",
	Username: "نام کاربری",
	Password: "گذرواژه",
	"Logging in...": "در حال ورود...",
	"Invalid username or password.": "نام کاربری یا گذرواژه نادرست است.",
	"Your account cannot access this organization.":
		"حساب شما به این سازمان دسترسی ندارد.",
	"Please enter both username and password.":
		"نام کاربری و گذرواژه را وارد کنید.",
	"Cannot reach the server. Make sure the backend is running, and try again.":
		"اتصال به سرور برقرار نشد. مطمئن شوید بک‌اند در حال اجراست و دوباره تلاش کنید.",
	"The server is temporarily unavailable. Please try again in a moment.":
		"سرور موقتاً در دسترس نیست. لحظه‌ای بعد دوباره تلاش کنید.",
	"Login failed. Please try again.": "ورود ناموفق بود. دوباره تلاش کنید.",
	"The login response did not contain valid access and refresh tokens.":
		"پاسخ ورود، توکن‌های معتبر دسترسی و تازه‌سازی نداشت.",
	"The user role returned by the server is invalid.":
		"نقش کاربری بازگشتی از سرور معتبر نیست.",
	"Login succeeded, but loading your profile failed. Please try again.":
		"ورود موفق بود، اما بارگذاری پروفایل انجام نشد. دوباره تلاش کنید.",

	// -- auth guard --------------------------------------------------
	"Checking authentication...": "در حال بررسی احراز هویت...",
	"Connection problem": "مشکل اتصال",
	"Try again": "تلاش دوباره",
	"The server is temporarily unavailable. Please try again.":
		"سرور موقتاً در دسترس نیست. دوباره تلاش کنید.",
	"Cannot reach the server. Check that the backend is running and try again.":
		"اتصال به سرور برقرار نشد. بررسی کنید بک‌اند در حال اجرا باشد و دوباره تلاش کنید.",

	// -- admin -------------------------------------------------------
	"Admin Dashboard": "داشبورد مدیریت",
	"Loading dashboard...": "در حال بارگذاری داشبورد...",
	"Could not load dashboard data. Please try again.":
		"بارگذاری داده‌های داشبورد انجام نشد. دوباره تلاش کنید.",
	"No dashboard data is available.": "داده‌ای برای نمایش وجود ندارد.",
	"Total documents": "کل اسناد",
	"Total file volume": "حجم کل فایل‌ها",
	"Total searches": "کل جست‌وجوها",
	Documents: "اسناد",
	User: "کاربر",
	Department: "دپارتمان",
	"Search query": "عبارت جست‌وجو",
	Date: "تاریخ",
	"Recent searches": "جست‌وجوهای اخیر",
	"Search analytics": "تحلیل جست‌وجو",

	// -- document uploader -------------------------------------------
	"Only PDF, Word (.doc/.docx), and TXT files are allowed.":
		"فقط فایل‌های PDF، Word (.doc/.docx) و TXT مجاز هستند.",
	"Please select a file before uploading.":
		"پیش از بارگذاری، یک فایل انتخاب کنید.",
	"Please select a department.": "یک دپارتمان انتخاب کنید.",
	"Please enter a document title.": "عنوان سند را وارد کنید.",
	"Document uploaded successfully.": "سند با موفقیت بارگذاری شد.",
	"Document deleted successfully.": "سند با موفقیت حذف شد.",
	"Are you sure you want to delete this document?":
		"از حذف این سند مطمئن هستید؟",
	"Enter document title": "عنوان سند را وارد کنید",
	"Loading departments...": "در حال بارگذاری دپارتمان‌ها...",
	"Select a department": "یک دپارتمان انتخاب کنید",
	"Choose a document file": "انتخاب فایل سند",
	"Selected file": "فایل انتخاب‌شده",
	"Uploading...": "در حال بارگذاری...",
	"Upload progress": "پیشرفت بارگذاری",
	Refresh: "بازخوانی",
	"Refreshing...": "در حال بازخوانی...",
	"Deleting...": "در حال حذف...",
	Delete: "حذف",
	Pending: "در انتظار",
	Processed: "پردازش‌شده",
	Processing: "در حال پردازش",
	Failed: "ناموفق",
	Indexed: "ایندکس‌شده",
	"Chunk {index}": "بخش {index}",
	"Open source": "باز کردن منبع",
	"Open citation": "باز کردن ارجاع",
	Retry: "تلاش دوباره",
	"Back to workspace": "بازگشت به میزکار",
	"Document usage and search activity": "میزان استفاده از اسناد و فعالیت جست‌وجو",
	"Documents by department": "اسناد به تفکیک دپارتمان",
	"Number of uploaded documents in each department":
		"تعداد اسناد بارگذاری‌شده در هر دپارتمان",
	"No department data available.": "داده‌ای برای دپارتمان‌ها وجود ندارد.",
	"Searches by department": "جست‌وجوها به تفکیک دپارتمان",
	"Share of recorded searches by department":
		"سهم هر دپارتمان از جست‌وجوهای ثبت‌شده",
	"No recorded searches by department yet.":
		"هنوز جست‌وجویی برای دپارتمان‌ها ثبت نشده است.",
	"Latest {count} records": "{count} رکورد آخر",
	"In the document": "در سند",
	"Cited passage": "بخش ارجاع‌شده",
	"Highlighted:": "هایلایت‌شده:",
	"No search history is available yet.": "هنوز تاریخچه جست‌وجویی وجود ندارد.",
	"Loading the document text...": "در حال بارگذاری متن سند...",
	"Show the cited passage instead": "نمایش بخش ارجاع‌شده به جای آن",
	"Document title": "عنوان سند",
	"Select department": "انتخاب دپارتمان",
	"Your documents": "اسناد شما",
	"No documents yet": "هنوز سندی وجود ندارد",
	"Drag and drop or browse": "فایل را بکشید یا انتخاب کنید",
	"Choose file": "انتخاب فایل",

	// -- citation panel ----------------------------------------------
	"Could not load this citation.": "بارگذاری این منبع انجام نشد.",
	"Could not load the document.": "بارگذاری سند انجام نشد.",
	"Could not open the file.": "باز کردن فایل انجام نشد.",
	"Copying is not available in this browser.":
		"کپی در این مرورگر در دسترس نیست.",
	"Close source panel": "بستن پنل منبع",
	"Citation source": "منبع ارجاع",
	"Loading citation...": "در حال بارگذاری منبع...",
	"No keyword match in this file — the answer came from a semantic match.":
		"تطابق کلیدواژه‌ای در این فایل نبود — پاسخ از تطابق معنایی آمده است.",
	File: "فایل",
	Type: "نوع",
	"Copy text": "کپی متن",
	Copied: "کپی شد",
	"Open original file": "باز کردن فایل اصلی",
	"Opening...": "در حال باز کردن...",
	Source: "منبع",
	"Matched passage": "بخش مطابق",
	"Document preview": "پیش‌نمایش سند",
	Close: "بستن",

	// -- answer feedback ---------------------------------------------
	"Was this answer helpful?": "آیا این پاسخ مفید بود؟",
	"Rate this answer": "به این پاسخ امتیاز دهید",
	Helpful: "مفید بود",
	"Not helpful": "مفید نبود",
	"Saving your feedback...": "در حال ثبت بازخورد...",
	"Thanks for your feedback.": "از بازخورد شما سپاسگزاریم.",
	"What went wrong with this answer?": "این پاسخ چه مشکلی داشت؟",
	"Optional — your note helps us improve the answers.":
		"اختیاری — یادداشت شما به بهبود پاسخ‌ها کمک می‌کند.",
	"Missing information, wrong source, unclear wording...":
		"اطلاعات ناقص، منبع نادرست، بیان نامشخص...",
	Cancel: "انصراف",
	"Saving...": "در حال ثبت...",
	"Submit feedback": "ثبت بازخورد",
	"This answer is no longer available.": "این پاسخ دیگر در دسترس نیست.",
	"Your session has expired. Please sign in again.":
		"نشست شما منقضی شده است. دوباره وارد شوید.",
	"You do not have access to rate this answer.":
		"شما اجازه ثبت بازخورد برای این پاسخ را ندارید.",
	"That feedback could not be saved. Please try again.":
		"این بازخورد ذخیره نشد. دوباره تلاش کنید.",
	"Too many feedback attempts. Please try again later.":
		"تعداد تلاش‌های بازخورد زیاد بود. بعداً دوباره تلاش کنید.",
	"Could not reach the server. Please try again.":
		"اتصال به سرور برقرار نشد. دوباره تلاش کنید.",
	"Could not send your feedback. Please try again.":
		"ارسال بازخورد انجام نشد. دوباره تلاش کنید.",

	// -- cold start / empty state -----------------------------------
	"Your department has no documents yet": "دپارتمان شما هنوز سندی ندارد",
	"The assistant answers only from documents in your department. Add the first one to get real answers — until then it answers from the platform guide.":
		"دستیار فقط از اسناد دپارتمان شما پاسخ می‌دهد. اولین سند را اضافه کنید تا پاسخ‌های واقعی بگیرید؛ تا آن زمان پاسخ‌ها بر پایه راهنمای پلتفرم است.",
	"Upload your first document": "آپلود اولین سند",
	"Ask the assistant how to use the platform":
		"از دستیار درباره نحوه استفاده از پلتفرم بپرسید",
	"Already uploaded a file? Indexing takes a few moments.":
		"قبلاً فایلی آپلود کرده‌اید؟ پردازش چند لحظه زمان می‌برد.",
	"Refresh status": "بروزرسانی وضعیت",
	"No document in your department covers this topic yet.":
		"در حال حاضر سندی مرتبط با این موضوع در دپارتمان شما یافت نشد.",
	"The assistant answers only from documents in your department. Upload the first one, or ask how the platform works.":
		"دستیار فقط از اسناد دپارتمان شما پاسخ می‌دهد. اولین سند را آپلود کنید یا بپرسید پلتفرم چطور کار می‌کند.",
	"Ask how the platform works": "بپرسید پلتفرم چطور کار می‌کند",
	"Nothing in your knowledge base matched this question. Try different words, or upload a document that covers it.":
		"هیچ سندی در پایگاه دانش شما با این پرسش مطابقت نداشت. کلمات دیگری را امتحان کنید یا سندی مرتبط آپلود کنید.",
	"Try a different wording": "با کلمات دیگر بپرسید",
	"Upload a document": "آپلود یک سند",
	"System guide": "راهنمای سیستمی",
	"Managed by the platform": "مدیریت‌شده توسط پلتفرم",

	// -- admin quality dashboard -------------------------------------
	"Answer quality trend": "روند کیفیت پاسخ‌ها",
	"Satisfaction rate per period, with the number of ratings behind it":
		"درصد رضایت در هر بازه، همراه با تعداد بازخوردهای پشت آن",
	"Reporting window": "بازه گزارش",
	"{count} days": "{count} روز",
	"Satisfaction rate": "درصد رضایت",
	"Positive ratings ÷ ratings received":
		"بازخورد مثبت ÷ کل بازخوردهای دریافتی",
	"Ratings received": "بازخوردهای دریافتی",
	"Thumbs up {positive} · thumbs down {negative}":
		"مثبت {positive} · منفی {negative}",
	"Answers with a negative verdict": "پاسخ‌های با بازخورد منفی",
	"{count} of them left a comment": "{count} مورد از آن‌ها نظر نوشته‌اند",
	"Rating coverage": "پوشش بازخورد",
	"Ratings ÷ answers delivered ({count})":
		"بازخورد ÷ پاسخ‌های ارائه‌شده ({count})",
	"No ratings in this window yet. The trend appears as soon as users rate an answer.":
		"در این بازه هنوز بازخوردی ثبت نشده است. روند به‌محض ثبت اولین بازخورد نمایش داده می‌شود.",
	"Quality by department": "کیفیت به تفکیک دپارتمان",
	"Worst first — where the wrong answers come from":
		"بدترین‌ها اول — اینجا مشخص می‌شود پاسخ‌های اشتباه از کجا آمده‌اند",
	"{count} ratings": "{count} بازخورد",
	"{count} negative": "{count} منفی",
	"Could not load the quality metrics. Please try again.":
		"بارگذاری شاخص‌های کیفیت انجام نشد. دوباره تلاش کنید.",
	"Answers rated thumbs down": "پاسخ‌هایی که بازخورد منفی گرفته‌اند",
	"Read what went wrong, with the question, the answer and the user's comment":
		"ببینید چه چیزی اشتباه بوده: پرسش، پاسخ و نظر کاربر",
	"{count} in total": "{count} مورد در کل",
	"Search feedback": "جست‌وجوی بازخورد",
	"Search the question, the answer or the comment":
		"جست‌وجو در پرسش، پاسخ یا نظر کاربر",
	"All departments": "همه دپارتمان‌ها",
	"With a comment only": "فقط دارای نظر",
	"No thumbs-down in this window. Either quality is fine or nobody is rating.":
		"در این بازه بازخورد منفی ثبت نشده است؛ یا کیفیت مناسب است یا کسی بازخورد نمی‌دهد.",
	"Could not load the feedback list. Please try again.":
		"بارگذاری فهرست بازخوردها انجام نشد. دوباره تلاش کنید.",
	"User comment": "نظر کاربر",
	"No comment": "بدون نظر",
	"Show the answer": "نمایش پاسخ",
	"{count} citations": "{count} منبع",
	"Showing {from}–{to} of {total}": "نمایش {from}–{to} از {total}",
	"Previous": "قبلی",
	"Next": "بعدی",
	"Question": "پرسش",
	"Answer": "پاسخ",
};

/**
 * Translate an English source string.
 *
 * `{name}` placeholders are replaced from `vars`. Unknown strings fall back
 * to the English source so the UI never shows a missing-key marker.
 */
export function translate(
	locale: Locale,
	text: string,
	vars?: Record<string, string | number>,
): string {
	const template = locale === "fa" ? FA[text] || text : text;

	if (!vars) {
		return template;
	}

	return template.replace(/\{(\w+)\}/g, (match, key: string) => {
		const value = vars[key];
		return value === undefined ? match : String(value);
	});
}

export function hasTranslation(locale: Locale, text: string): boolean {
	return locale === "en" ? true : Boolean(FA[text]);
}
