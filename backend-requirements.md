# شرح کار بک‌اند — داینامیک‌سازی کامل فرانت‌اند (Next.js)

> **نوع سند:** دستور کار پیاده‌سازی (Implementation Brief). مکمل `backend-doc.md` است، نه جایگزین آن.
> **تاریخ:** 1 نوامبر 2026.
> **مبنا:** خواندن کامل سورس فرانت (`src/**`) و `backend-doc.md`. هیچ endpointی اجرا نشده؛ هر رفتاری که به «بک‌اند فعلی» نسبت داده شده از `backend-doc.md` نقل شده است.
> **کار شما (agent بک‌اند):** همه‌ی موارد این سند را پیاده‌سازی کنید، سپس طبق بخش 12 یک سند API نهایی برای agent فرانت تولید کنید. فرانت بعداً فقط بر اساس آن سند وصل می‌شود؛ پس هر چیزی که بنویسید باید با اجرای واقعی سرور راستی‌آزمایی شده باشد.

---

## فهرست

0. [خلاصه‌ی اجرایی](#0-خلاصهی-اجرایی)
1. [زمینه: فرانت چه چیزی است و چه چیزی هاردکد است](#1-زمینه)
2. [قواعد کار (اجباری)](#2-قواعد-کار-اجباری)
3. [تصمیم‌های معماری (از قبل گرفته‌شده)](#3-تصمیمهای-معماری)
4. [نقشه‌ی صفحات فرانت ← داده‌ی داینامیک](#4-نقشهی-صفحات-فرانت--دادهی-داینامیک)
5. [قرارداد مشترک API](#5-قرارداد-مشترک-api)
6. [ماژول‌ها (مشخصات تفصیلی)](#6-ماژولها)
   - 6.1 تنظیمات سایت · 6.2 برندها · 6.3 دسته‌بندی‌ها · 6.4 محصولات · 6.5 پروژه‌ها · 6.6 اخبار/مقالات · 6.7 خدمات · 6.8 FAQ · 6.9 محتوای شرکت · 6.10 استعلام‌ها (فرم تماس) · 6.11 جستجو · 6.12 تجمیعی‌ها (home, sitemap, health) · 6.13 رشته‌های رابط (i18n) · 6.14 رسانه و فایل‌ها · 6.15 Revalidation · 6.16 موارد P2
7. [الزامات پنل ادمین (مشترک)](#7-الزامات-پنل-ادمین-مشترک)
8. [امنیت و سخت‌سازی](#8-امنیت-و-سختسازی)
9. [کش و کارایی](#9-کش-و-کارایی)
10. [اولویت‌بندی و فازها](#10-اولویتبندی-و-فازها)
11. [معیار پذیرش و تست](#11-معیار-پذیرش-و-تست)
12. [خروجی نهایی: سند API برای فرانت](#12-خروجی-نهایی-سند-api-برای-فرانت)
- [پیوست الف: انواع داده‌ی فرانت (مرجع)](#پیوست-الف-انواع-دادهی-فرانت-مرجع)
- [پیوست ب: اسلات‌های تصویر، آیکن‌ها و کلیدهای تنظیمات](#پیوست-ب-اسلاتهای-تصویر-آیکنها-و-کلیدهای-تنظیمات)
- [پیوست ج: متغیرهای محیطی جدید](#پیوست-ج-متغیرهای-محیطی-جدید)

---

## 0. خلاصه‌ی اجرایی

1. **فرانت** یک سایت معرفی شرکت صنعتی (بدون خرید آنلاین، بدون قیمت/موجودی/سبد) با **Next.js 16 (App Router) + React 19 + TypeScript** و **دو زبانه (fa/en)** است. **تمام محتوای آن الان داخل سورس هاردکد است** (`src/data/*.ts`, `src/locales/*.json`). هدف: هر چیزی که ممکن است تغییر کند از بک‌اند بیاید.
2. بک‌اند فعلی فقط این‌ها را دارد: محصول/دسته (تک‌زبانه، با فیلد تجاری price/stock)، رشته‌های رابط (i18n)، رسانه، کش، ردیابی، قالب‌ساز. **بخش بزرگی از نیاز فرانت وجود ندارد:** تنظیمات سایت (نام/لوگو/آیکن/متا) به‌صورت JSON، برند، محتوای چندزبانه، مشخصات فنی/مدل‌ها/اسناد محصول، پروژه، خبر/مقاله، خدمات، FAQ، محتوای «درباره‌ی ما»، ثبت فرم تماس، جستجو، فایل‌های PDF قابل‌دانلود.
3. **معماری مصوب:** namespace جدید **`/api/public/*`** (JSON، فقط‌خواندنی به‌جز ثبت استعلام) + مدیریت محتوا از طریق **پنل ادمین Jinja موجود** (فرم‌ها). endpointهای قدیمی (`/api/products`, `/api/categories`, `/api/i18n/*`) **بدون تغییر** می‌مانند.
4. **چندزبانه‌شدن محتوا** مهم‌ترین تغییر ساختاری است: هر فیلد متنی قابل‌نمایش در پاسخ به‌صورت **`{"fa": "...", "en": "..."}`** برمی‌گردد (بخش 3.2). فرانت همین شکل را دارد و زبان را خودش (با کوکی) تعیین می‌کند.
5. **URL تصاویر/فایل‌ها باید مطلق باشد** (`https://api.example.com/assets/...`)، چون فرانت روی origin دیگری سرو می‌شود (بخش 3.4).
6. **هیچ HTML در فیلدهای جدید ذخیره/نمایش نمی‌شود**؛ فقط متن ساده (بخش 3.5).
7. **فایل‌های دانلودی** (PDF، STEP، DWG، …) موجودیت واقعی با آپلود، اعتبارسنجی پسوند/حجم و endpoint دانلود شمارش‌دار می‌شوند (بخش 6.4.6). فرانت الان یک `.txt` ساختگی در مرورگر می‌سازد.
8. **برند (Brand)** را خواسته‌ی مالک پروژه است؛ در UI فعلی فرانت جایی ندارد ولی باید ساخته شود تا در محصول/JSON-LD/فیلتر استفاده شود (بخش 6.2).
9. فرانت پس از تغییر محتوا باید **فوراً** به‌روز شود: بک‌اند باید یک **webhook ناهمگام (revalidate)** به فرانت بزند (بخش 6.15).
10. دو مورد **تغییر رفتار موجود** با علامت ⚠️ در بخش 8 آمده (احراز هویت مسیرهای باز ادمین، اعتبارسنجی آپلود). فقط همین‌ها استثنا از قاعده‌ی «بدون شکستن موجود» هستند.

---

## 1. زمینه

### 1.1 فرانت (فقط آنچه برای شما مهم است)
- **پشته:** Next.js 16.4 App Router، React 19، TS strict، Tailwind 4، `next/image`، `react-hook-form` + `zod`. فرانت **هنوز هیچ fetch به بک‌اند ندارد.**
- **صفحات** (همه SSR/SSG با صفحه‌های جزئیات پویا): `/`, `/about`, `/products`, `/products/category/[slug]`, `/products/[slug]`, `/services`, `/projects`, `/projects/[slug]`, `/news`, `/news/[slug]`, `/faq`, `/contact`, `/search`, 404، `sitemap.xml`, `robots.txt`.
- **زبان:** `fa` (RTL، پیش‌فرض) و `en` (LTR). فرانت زبان را با **کوکی `aspd_locale`** می‌خواند، نه با پیشوند URL. بنابراین `/api/public/*` نباید به پیشوند زبان یا کوکی تکیه کند. فقط این دو زبان در فرانت پیاده شده‌اند.
- **تاریخ:** فرانت ISO را می‌گیرد و خودش به جلالی/میلادی تبدیل می‌کند (پس API فقط ISO بدهد).
- **باقیمانده‌ی قالب قدیمی در فرانت (حذف می‌شود، به شما ربطی ندارد جز اینکه جایگزینش را بسازید):** route‌های `POST /api/contact` (Postgres + drizzle)، `GET /api/search`، `GET /api/health`. ثبت استعلام و جستجو به بک‌اند شما منتقل می‌شود.

### 1.2 ماتریس: فرانت چه می‌خواهد ← بک‌اند فعلی چه دارد

| نیاز فرانت | وضعیت بک‌اند (طبق `backend-doc.md`) | اقدام |
|---|---|---|
| نام سایت، لوگو، فاوآیکن، رنگ‌ها، تماس، شبکه‌های اجتماعی، متای پیش‌فرض، تصاویر ثابت صفحات | فقط `site_title/meta_description/meta_keywords`، آن‌هم فقط داخل Jinja (بخش 5 آن سند) | **6.1** |
| محتوای دوزبانه (نام/توضیح محصول و دسته و …) | «محتوای محصول/دسته ترجمه نمی‌شود» (4.3) | **3.2 + همه‌ی ماژول‌ها** |
| برند | وجود ندارد (جدول/route ندارد) | **6.2** |
| دسته: آیکن، تصویر کاور، لیست استانداردها، شاخصه‌ها، تعداد محصول | فقط name/slug/parent/description/meta | **6.3** |
| محصول: کد مدل، زیرعنوان، توضیح کوتاه، ویژگی‌ها، **مشخصات فنی، مدل‌ها/پیکربندی‌ها، اسناد قابل‌دانلود**، تگ، گواهی‌ها، شاخص/جدید | فقط name/slug/description(HTML)/price/stock/sku/…؛ بدون هیچ‌کدام از این‌ها | **6.4** |
| فیلتر/جست‌وجو/مرتب‌سازی/صفحه‌بندی محصولات | ندارد (حداکثر 100 محصول) | **6.4** |
| پروژه‌ها، اخبار/مقالات، خدمات، FAQ | وجود ندارد | **6.5–6.8** |
| آمار شرکت، گاه‌شمار، تیم، گواهینامه‌ها، صنایع، نظرات مشتریان، دفاتر | وجود ندارد | **6.9** |
| ثبت فرم تماس/استعلام | وجود ندارد | **6.10** |
| جستجوی یکپارچه (محصول/پروژه/مقاله/صفحه) | وجود ندارد | **6.11** |
| رشته‌های رابط (~330 کلید) | i18n دارد (113 کلید پنل ادمین)، API هست ولی fallback ندارد | **6.13** |
| به‌روزرسانی فوری فرانت پس از تغییر محتوا | ندارد | **6.15** |
| JSON خطا، CORS، 401/403 درست | ندارد (HTML/redirect/500) | **5 + 8** |

---

## 2. قواعد کار (اجباری)

1. **هر قابلیت = یک پلاگین** (قرارداد پروژه، `backend-doc.md` بخش 5.2). برای گسترش `products` و `categories` در همان پلاگین‌ها کار کنید؛ بقیه پلاگین جدیدند (پیشنهاد نام: `site_settings`, `brands`, `projects`, `articles`, `services`, `faq`, `company`, `inquiries`, `public_api`). تقسیم دقیق با شماست ولی شکل API و رفتار پنل ثابت است.
2. **فقط افزودنی (additive):** ستون/جدول جدید با `SchemaManager` (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN`). معنی و شکل هیچ endpoint/فیلد موجودی تغییر نکند. باید سالم بمانند: `/api/products`, `/api/categories`, `/api/i18n/*`, قالب‌ساز و تم‌های `conspro/creek/construction`، تمام صفحات فعلی پنل. تنها استثناها: بخش 8 (⚠️).
3. **هر route ادمین جدید `@admin_required`** باشد.
4. **ورودی نامعتبر هرگز 500 نباشد.** در `/api/public/*` همیشه JSON با 400/404/422/429. (اشکال موجود: `page=abc` ⇒ 500؛ این رفتار نباید در کد جدید تکرار شود.)
5. **خطای DB را از «نتیجه‌ی خالی» جدا کنید** (در بک‌اند فعلی `Database.query` خطا را قورت می‌دهد و `[]` می‌دهد). در `/api/public/*` خطای DB ⇒ `503` JSON، نه لیست خالی؛ وگرنه فرانت صفحه‌ی خالی را کش می‌کند.
6. **Migration امن:** idempotent (دو بار اجرا بی‌اثر)، بدون حذف داده. داده‌ی فعلی محصولات/دسته‌ها باید حفظ و به‌عنوان ترجمه‌ی `fa` منتقل شود (3.2).
7. **پیام‌های پنل صادق باشند:** در فرم‌های جدید «ذخیره شد» فقط پس از ذخیره‌ی واقعی؛ خطا (slug تکراری، فیلد الزامی، فایل نامعتبر) با پیام خطا و حفظ مقادیر وارد‌شده. (اشکال موجود: ویرایش با slug تکراری بی‌صدا شکست می‌خورد ولی «ذخیره شد» می‌گوید.)
8. **ویرایش جایگزینی کورکورانه نباشد:** در فرم‌های جدید، فیلد غایب = دست‌نخورده؛ پاک‌کردن فقط با خالی‌فرستادن صریح فیلد حاضر. (اشکال موجود: ویرایش دسته بدون `is_active` آن را غیرفعال می‌کند.)
9. **هیچ مقدار `.env`/رمز/توکنی** در لاگ، پاسخ یا سند چاپ نشود.
10. **اگر نکته‌ای مبهم بود:** بهترین گزینه را انتخاب کنید و در سند نهایی زیر «انحراف‌ها و فرض‌ها» بنویسید. فقط در صورت مانع واقعی از مالک بپرسید.
11. **تست:** هر جا زیرساخت تست دارید، برای منطق (فیلتر محصولات، جستجو، شماره‌ی رهگیری، اعتبارسنجی آپلود، تبدیل ترجمه) تست بنویسید؛ در هر حال یک اسکریپت smoke (بخش 11).

---

## 3. تصمیم‌های معماری

### 3.1 جدا بودن API عمومی از API قدیمی
- همه‌ی endpointهای جدید زیر **`/api/public/`**. دلیل: شکل پاسخ قدیمی (فیلد `name` رشته، Decimal رشته‌ای، RFC-822، 0/1، `description` HTML) با نیاز دوزبانه/تمیز فرانت ناسازگار است و تغییرش مصرف‌کنندگان فعلی را می‌شکند.
- `/api/public/*` **فقط** محتوای منتشرشده را برمی‌گرداند. پیش‌نویس، غیرفعال، حذف‌شده، یادداشت‌های داخلی، ایمیل/آی‌پی استعلام‌ها و هر داده‌ی داخلی هرگز.
- به لیست حذف پیش‌فرض ردیابی (`path_patterns`، بخش 9.2 `backend-doc.md`) اضافه کنید: `/api/public/*`؛ وگرنه هر رندر سرور فرانت یک «بازدید» ثبت می‌کند و آمار آلوده می‌شود. (نکته‌ی تکمیلی: بخش 6.16.)

### 3.2 مدل محتوای چندزبانه
**شکل خروجی (الزامی):**
```ts
type I18nText = { fa: string; en?: string; [lang: string]: string | undefined };   // کلید fa همیشه هست
type I18nList = { fa: string[]; en?: string[]; [lang: string]: string[] | undefined };
```
- **`fa` همیشه حاضر است.** برای فیلد الزامی غیرخالی؛ برای فیلد اختیاری ممکن است `""` (یا `[]`) باشد. هیچ فیلد i18n هرگز `null` نیست.
- زبان‌های دیگر **فقط وقتی مقدار غیرخالی دارند** در شیء می‌آیند (کلید خالی/null ندهید). فرانت `text[locale] ?? text.fa` می‌کند.
- کلیدها = کد زبان‌های `i18n_languages` با `is_active=1`. فرانت فقط `fa` و `en` را پیاده کرده؛ زبان‌های دیگر نادیده گرفته می‌شوند (ولی بودنشان خطا نیست).
- زبان فقط **داده** است؛ endpointهای `/api/public/*` به پیشوند URL، کوکی یا هدر `Accept-Language` وابسته نباشند. (پارامتر اختیاری `lang` در بعضی endpointها فقط برای **مرتب‌سازی/رتبه‌بندی جستجو** است، نه فیلتر خروجی.)
- **در پنل ادمین:** هر فیلد ترجمه‌پذیر تب/سطر برای هر زبان فعال دارد؛ `fa` الزامی (برای فیلدهای الزامی)، بقیه اختیاری.
- **ذخیره‌سازی (پیشنهاد، نه الزام):** جدول عمومی `content_translations(entity_type, entity_id, field, lang_code, value MEDIUMTEXT)` با کلید یکتا روی چهار ستون اول؛ فیلدهای لیستی به‌صورت JSON آرایه. ستون‌های قدیمی (`products.name`, `categories.name`, …) **برابر مقدار `fa` هم‌گام بمانند** تا کد قدیمی و `/api/products` بشکنند و مرتب‌سازی فارسی ساده بماند. مهاجرت داده‌ی فعلی: مقدار ستون‌ها ⇒ ترجمه‌ی `fa`.
- فیلدهای غیرمتنی/خنثی از زبان (کد مدل، slug، سال، لیست استانداردها مثل `IEC 60534`، ایمیل، تلفن) i18n **نیستند**.

### 3.3 قرارداد JSON
- کلیدها **snake_case**. (فرانت لایه‌ی نگاشت به camelCase دارد.)
- Boolean واقعی (`true/false`)، نه `0/1`. عدد، عدد؛ نه رشته (Decimal رشته‌ای فقط در API قدیمی).
- زمان‌ها **ISO-8601 UTC با `Z`**: `"2026-09-07T17:15:14Z"` (نه RFC-822). تاریخ‌های انتشار مقاله/پروژه: همان ISO کامل.
- فیلد اختیاری بدون مقدار: `null` (به‌جز I18n که قاعده‌ی 3.2 دارد). آرایه‌ی خالی `[]`.
- ترتیب آرایه‌ها معنادار و **مستند** است (از `sort_order`)؛ به ترتیب کلیدهای شیء تکیه نمی‌شود.
- `id` عددی. برای مسیرهای عمومی **slug** کلید است (نه id).
- لیست‌ها: `{"<نام‌جمع>": [...], "meta": {"total", "page", "per_page", "total_pages"}}`.
- خطا (همه‌ی `/api/public/*`، حتی 404/405/500 پیش‌فرض Flask باید JSON شوند):
```json
{"ok": false, "error": "not_found", "message": "Product not found", "fields": {"email": {"code": "invalid_email"}}}
```
  `error` کد ماشینی ثابت (`not_found`, `validation_failed`, `rate_limited`, `bad_request`, `unavailable`, `server_error`)، `message` انگلیسی برای توسعه‌دهنده، `fields` فقط در 422. فرانت متن کاربر را از i18n خودش می‌سازد؛ پس **کد** مهم است، نه `message`.
  وضعیت‌ها: 400 پارامتر بد، 404، 422 اعتبارسنجی بدنه، 429 با `Retry-After`، 503 خطای DB.
- **پارامترهای صفحه‌بندی را clamp کنید**، خطا ندهید: `page<1⇒1`، `per_page` خارج از 1..100 ⇒ مقدار پیش‌فرض/سقف. پارامتر ناشناخته نادیده گرفته شود.

### 3.4 URL رسانه: همیشه مطلق
فرانت روی origin دیگری (مثلاً `localhost:3000` یا دامنه‌ی اصلی) است و بک‌اند روی origin خودش. مسیر نسبی `/assets/uploads/x.jpg` در فرانت به 404 می‌خورد، و برای OG/JSON-LD/`next/image` مطلق لازم است.
- **همه‌ی فیلدهای URL رسانه در `/api/public/*` مطلق باشند:** `{PUBLIC_BASE_URL}/assets/uploads/...`.
- `PUBLIC_BASE_URL` از `.env` (بند پیوست ج)؛ در نبودش از `request.host_url` (با احترام به `X-Forwarded-Proto/Host`).
- نرمال‌سازی 8.5 `backend-doc.md` (اسلش ابتدایی) را سمت سرور اعمال کنید؛ مقدار `http(s)://` بیرونی دست‌نخورده می‌ماند.
- شیء رسانه:
```ts
type Media = { url: string; alt: I18nText; width: number | null; height: number | null; mime: string | null } | null;
```
  `alt` همیشه شیء I18nText است (`{"fa": ""}` وقتی خالی). `width/height` از Pillow در صورت وجود وگرنه `null`.
- (فرانت وظیفه‌ی `images.remotePatterns` را خودش انجام می‌دهد؛ دامنه‌ی بک‌اند باید پایدار و ترجیحاً HTTPS باشد.)

### 3.5 متن ساده، نه HTML
همه‌ی فیلدهای متنی **جدید** (توضیحات، ویژگی‌ها، پاراگراف مقاله، …) **متن ساده** هستند. پاراگراف‌ها با خط خالی جدا می‌شوند و API آن‌ها را به **آرایه‌ی پاراگراف** (برای فیلدهای `*_paragraphs`) یا رشته با `\n` (برای `description` ساده) برمی‌گرداند. فرانت با React متن را escape می‌کند. در فرم‌های ادمین بنویسید «HTML پشتیبانی نمی‌شود». (نتیجه: ریسک XSS ناشی از `description` HTML در مسیرهای جدید صفر است.)
- توجه: ستون قدیمی `products.description` (HTML) دست‌نخورده می‌ماند؛ **فیلد جدید `description` در `/api/public/*` از ترجمه‌ی `fa` همان ستون ساخته می‌شود** ولی هنگام مهاجرت برچسب‌های HTML آن را به متن ساده تبدیل کنید (tag strip + `<br>/<p>` ⇒ `\n`)، اصل ستون قدیمی را دست نزنید.

### 3.6 slug
- برای موجودیت‌های **جدید** و برای فیلد slug در فرم‌های جدید: `^[a-z0-9]+(?:-[a-z0-9]+)*$`، حداکثر 120 کاراکتر، **یکتا با UNIQUE index در DB**، تولید خودکار از (نام انگلیسی ← کد مدل ← ترنسلیتریشن فارسی ← `item-<id>`)، و قابل‌ویرایش دستی با اعتبارسنجی و پیام خطای واضح.
- slug محصولات/دسته‌های **فعلی** (ممکن است فارسی یا با فاصله باشند) تغییر نکند و API همان را برمی‌گرداند (کلاینت `encodeURIComponent` می‌کند). فقط در فرم ویرایش، اگر slug عوض شد اعتبارسنجی بالا اعمال شود.
- تغییر slug ⇒ ثبت در `slug_history` (برای ریدایرکت 301، بخش 6.16).

### 3.7 انتشار
موجودیت‌های محتوایی (`products`, `projects`, `articles`) فیلد `status ∈ {draft, published}` و `published_at` (قابل‌تنظیم) دارند. **نمایش عمومی:** `status='published' AND (published_at IS NULL OR published_at <= now)` ⇒ انتشار زمان‌بندی‌شده رایگان. بقیه (`services`, `faq`, `company_*`, `brands`, …) فیلد `is_active`.

### 3.8 CORS
- در فرانت، fetchهای سمت سرور (SSR) بین‌سرور هستند و CORS نمی‌خواهند، ولی **فرم تماس و جستجوی زنده از مرورگر** می‌آیند.
- فقط روی `/api/public/*`: هدرهای CORS با `.env` → `CORS_ALLOWED_ORIGINS` (لیست جداشده با ویرگول؛ **خالی = هیچ هدری ارسال نشود**)، متدهای `GET, POST, OPTIONS`، هدر `Content-Type`، **بدون credentials**. به `OPTIONS` (preflight) با 204 پاسخ دهید. `Access-Control-Allow-Origin` باید همان origin درخواست باشد (در صورت وجود در لیست)، نه `*`.
- `flask-cors` در `requirements.txt` نیست؛ یا آن را اضافه کنید یا `after_request` سبک بنویسید.

---

## 4. نقشه‌ی صفحات فرانت ← داده‌ی داینامیک

| صفحه (مسیر) | چه چیزی الان هاردکد است | endpoint |
|---|---|---|
| **Layout** (Header/Footer، `<head>`، JSON-LD سازمان) | نام، شعار، لوگوی SVG، فاوآیکن (ندارد)، تلفن/ایمیل/آدرس، شبکه‌های اجتماعی، نشان‌های ISO بالای هدر، دسته‌های منو، «محصول شاخص» منو، رنگ‌ها، URL سایت، متای پیش‌فرض | `GET /site`, `GET /categories`, `GET /products?featured=1&per_page=1`, i18n |
| **Home** `/` | تصاویر hero/intro/capabilities، آمار، دسته‌ها، محصولات شاخص (4)، پروژه‌ها (3)، مقالات (3)، صنایع، گواهینامه‌ها، نظرات، دفاتر | `GET /home` (تجمیعی) + `/site` + i18n |
| **About** `/about` | آمار، گاه‌شمار، تیم، گواهینامه‌ها، تصویر دفتر مرکزی، متن‌ها | `GET /company` + `/site` + i18n |
| **Products** `/products` | لیست محصولات، دسته‌ها با شمارنده، تگ‌ها، فیلتر (جستجو/دسته/تگ/شاخص)، مرتب‌سازی (شاخص/الفبا/کد)، «نمایش بیشتر» (6 تایی) | `GET /products` (+facets), `/categories`, `/tags`, `/brands` |
| **Category** `/products/category/[slug]` | اطلاعات دسته، شاخصه‌ها، استانداردها، محصولات دسته، دسته‌های دیگر | `GET /categories/<slug>`, `GET /products?category=` |
| **Product** `/products/[slug]` | همه‌ی فیلدهای محصول، 3 تب (مشخصات، مدل‌ها، **اسناد**)، **دانلود فایل**، مرتبط‌ها (3)، JSON-LD | `GET /products/<slug>`, `GET /documents/<id>/download` |
| **Services** `/services` | 6 خدمت، 5 مرحله‌ی فرایند، صنایع | `GET /services`, `GET /company` (industries) |
| **Projects** `/projects` | لیست + فیلتر بخش صنعتی | `GET /projects`, `GET /project-sectors` |
| **Project** `/projects/[slug]` | همه‌ی فیلدها، گالری، دستاوردها، محصولات به‌کاررفته، پروژه‌های مشابه (2) | `GET /projects/<slug>` |
| **News** `/news` | لیست، فیلتر موضوع، جستجو، صفحه‌بندی (4 تایی) | `GET /articles`, `GET /article-categories` |
| **Article** `/news/[slug]` | بخش‌ها (TOC)، نویسنده، زمان مطالعه، مرتبط‌ها (3)، لینک اشتراک با دامنه | `GET /articles/<slug>` + `site.site_url` |
| **FAQ** `/faq` | پرسش‌ها، دسته‌ها | `GET /faq` |
| **Contact** `/contact` | دفاتر، ساعات کاری، شبکه‌های اجتماعی، **نقشه (الان SVG ساختگی)**، **ثبت فرم** | `GET /company` (offices), `/site`, **`POST /inquiries`** |
| **Search** `/search` | جستجو در محصول/پروژه/مقاله/صفحات، **کلیدواژه‌های پیشنهادی (6 تا، هاردکد)** | `GET /search`, `site.search_suggestions` |
| **sitemap.xml / robots.txt** | همه‌ی slugها با `lastModified=now` | `GET /sitemap`, `site.seo.robots_index` |
| **404** | متن‌ها | i18n |

---

## 5. قرارداد مشترک API

- پایه: `{PUBLIC_BASE_URL}/api/public`. بدون احراز هویت، بدون کوکی (به‌جز دانلود، که آن هم بدون کوکی است).
- همه‌ی پاسخ‌ها `Content-Type: application/json; charset=utf-8`، به‌جز دانلود فایل.
- **هدرهای کش (GET):** `ETag` (هش بدنه) + پشتیبانی از `If-None-Match` ⇒ `304`؛ `Cache-Control: public, max-age=30, stale-while-revalidate=300`. (فرانت اصلی را با revalidation کنترل می‌کند؛ این هدرها برای CDN/مرورگر است.)
- هر `GET` لیستی سقف بدنه دارد؛ فیلدهای سنگین (`description`, `sections`, …) فقط در **جزئیات** می‌آیند.

### 5.1 شاخص endpointها

| متد | مسیر | فاز | بخش |
|---|---|---|---|
| GET | `/site` | P0 | 6.1 |
| GET | `/categories` · `/categories/<slug>` | P0 | 6.3 |
| GET | `/brands` · `/brands/<slug>` | P0 | 6.2 |
| GET | `/tags` | P0 | 6.4 |
| GET | `/products` · `/products/<slug>` | P0 | 6.4 |
| GET | `/documents/<id>/download` | P0 | 6.4.6 |
| GET | `/health` | P0 | 6.12 |
| GET | `/projects` · `/projects/<slug>` · `/project-sectors` | P1 | 6.5 |
| GET | `/articles` · `/articles/<slug>` · `/article-categories` | P1 | 6.6 |
| GET | `/services` | P1 | 6.7 |
| GET | `/faq` | P1 | 6.8 |
| GET | `/company` | P1 | 6.9 |
| POST | `/inquiries` | P1 | 6.10 |
| GET | `/search` | P1 | 6.11 |
| GET | `/home` · `/sitemap` | P1 | 6.12 |
| — | افزودنی‌های `/api/i18n/translate/<code>` | P0 | 6.13 |
| — | webhook revalidate | P1 | 6.15 |

### 5.2 شکل‌های مشترک (کارت‌ها)
در همه‌ی لیست‌ها و تجمیعی‌ها یکسان‌اند (تعریف دقیق فیلدها در بخش هر ماژول):

- **CategoryCard** · **ProductCard** · **ProjectCard** · **ArticleCard** · **Seo**:
```ts
type Seo = { title: I18nText; description: I18nText; keywords: I18nText; og_image: Media; noindex: boolean };
```
  مقدار **مؤثر** را بسازید: اگر `meta_title`/`meta_description` برای زبانی خالی بود، از نام/توضیح کوتاه همان زبان؛ `og_image` اگر خالی بود از تصویر کاور؛ نه اینکه فرانت fallback بسازد. `keywords` ممکن است `{"fa": ""}` باشد.

---

## 6. ماژول‌ها

### 6.1 تنظیمات سایت (`site_settings`) — P0

**هدف:** هر چیزی که هویت و ظاهر سایت را می‌سازد و الان هاردکد است. **شامل 4 بخش:** (الف) تنظیمات عمومی، (ب) متای هر صفحه‌ی ثابت، (ج) اسلات‌های تصویر ثابت، (د) شبکه‌های اجتماعی.

**چرا جدا از `settings` فعلی؟** جدول `settings` (key/TEXT) فقط 5 کلید فرم دارد و ترجمه ندارد. جدول/ساختار جدید (مثلاً `site_settings` با ستون JSON یا جدول key/value نوع‌دار + ترجمه‌ها) بسازید؛ `settings` فعلی را دست نزنید. `site_title/meta_description/meta_keywords` فعلی را **به‌عنوان مقدار اولیه‌ی `fa`** برای `site_name`/`seo.default_description`/`seo.default_keywords` مهاجرت دهید.

#### الف) فیلدهای تنظیمات (همه با اعتبارسنجی؛ لیست کامل کلیدها در پیوست ب)

| گروه | فیلد | نوع | i18n | یادداشت |
|---|---|---|---|---|
| هویت | `name` | text | ✅ الزامی | هدر، فوتر، `siteName` متا، JSON-LD |
| | `short_name`, `legal_name`, `tagline` | text | ✅ | `tagline` در نوار بالای هدر |
| | `logo_subtitle` | text | ✅ | الان `ASPD ENGINEERING GROUP` زیر لوگو |
| | `alternate_name` | text | — | JSON-LD `alternateName` |
| | `site_url` | URL مطلق الزامی | — | آدرس عمومی **فرانت** (بدون اسلش پایانی)؛ برای canonical، sitemap، لینک اشتراک، JSON-LD |
| برندینگ | `logo_light` | تصویر | alt ✅ | لوگو روی پس‌زمینه‌ی روشن (هدر) |
| | `logo_dark` | تصویر | alt ✅ | روی پس‌زمینه‌ی تیره (فوتر)؛ نبود ⇒ فرانت از `logo_light` |
| | `logo_mark` | تصویر مربع | — | آیکن/JSON-LD `logo` |
| | `favicon_ico`, `favicon_svg`, `favicon_png` (≥512px), `apple_touch_icon` | تصویر | — | اگر Pillow هست از `favicon_png` اندازه‌های 32/192/512/180 را خودکار بسازید و در `favicon` برگردانید |
| | `og_default_image` | تصویر | alt ✅ | OG پیش‌فرض (الان `hero-facility.jpg`) |
| | `theme_color` | hex | — | `<meta name="theme-color">` |
| رنگ‌ها | `theme_primary`, `theme_primary_hover`, `theme_accent`, `theme_secondary`, `theme_dark_surface` | hex (`#rrggbb`) | — | الان در CSS: `#0b4f8a`, `#083d6b`, `#c27803`, `#0f172a`, `#09111f`. اعتبارسنجی hex، پیش‌نمایش رنگ در فرم |
| تماس | `phone` | text | — | `phone_tel` (فقط `+` و رقم) را سرور بسازد |
| | `email` | email | — | |
| | `address` | textarea | ✅ | |
| | `working_hours` | text | ✅ | |
| | `map_lat`, `map_lng` | float | — | اعتبارسنجی بازه |
| | `map_embed_url` | URL | — | فقط `https` و فهرست‌سفید دامنه (google.com/maps، openstreetmap.org، neshan.org، balad.ir) |
| | `map_label` | text | ✅ | |
| آدرس ساختاریافته (JSON-LD) | `address_street` (✅ i18n), `address_city` (✅), `address_region`, `address_postal_code`, `address_country_code` (ISO-3166 alpha-2، پیش‌فرض `IR`) | | | الان در `JsonLd.tsx` هاردکد (`Tehran`, `IR`) |
| هدر | `header_badges` | لیست متن (مثل `ISO 9001:2015`) | — | الان رشته‌ی `ISO 9001:2015 • IEC 61508 SIL-3 • ISO/IEC 17025` هاردکد در نوار بالا |
| جستجو | `search_suggestions` | لیست متن | ✅ (لیست i18n) | 6 کلیدواژه‌ی پیشنهادی صفحه‌ی جستجو (الان per-locale هاردکد) |
| سئو | `seo_default_title`, `seo_default_description`, `seo_default_keywords` | text | ✅ | |
| | `seo_title_template` | رشته با جاگذار `{title}` و `{site_name}` | — | پیش‌فرض `{title} \| {site_name}` (همان الگوی فعلی فرانت) |
| | `robots_index` | bool | — | `false` ⇒ فرانت `noindex` + `Disallow: /` (برای staging) |
| | `twitter_handle` | text | — | |
| | `google_site_verification`, `bing_site_verification` | text | — | |
| تحلیل | `ga4_measurement_id` | `G-XXXX` | — | با regex اعتبارسنجی |
| | `gtm_container_id` | `GTM-XXXX` | — | با regex اعتبارسنجی |
| استعلام (**فقط ادمین، هرگز در API عمومی**) | `inquiry_notify_emails`, `inquiry_reference_prefix` | | | بخش 6.10 |

#### ب) متای هر صفحه‌ی ثابت (`page_meta`)
کلیدها (ثابت، توسط کد تعریف می‌شوند): `home`, `about`, `products`, `services`, `projects`, `news`, `contact`, `faq`, `search`. هر کدام: `title` ✅، `description` ✅، `keywords` ✅، `og_image` (تصویر)، `noindex`. مقدار اولیه: از کلیدهای i18n فرانت (`seo.homeTitle` …) که در 6.13 وارد می‌شوند یا از `seo_default_*`.

#### ج) اسلات‌های تصویر ثابت (`media_slots`)
تصاویر داخل صفحات که الان مسیر هاردکد دارند. هر اسلات: تصویر + `alt` i18n. لیست ثابت در پیوست ب (`home.hero`, `home.intro`, `home.capabilities`, `about.hq`, `product.placeholder`, …). صفحه‌ی ادمین «تصاویر ثابت سایت» با انتخابگر رسانه.

#### د) شبکه‌های اجتماعی (`social_links`)
آرایه‌ی مرتب: `platform` (از لیست: `linkedin, instagram, telegram, whatsapp, youtube, twitter, facebook, aparat, eitaa, bale, rubika, github`)، `url` (https/tg/mailto، اعتبارسنجی)، `label` ✅ (اختیاری)، `sort_order`، `is_active`.

#### endpoint: `GET /api/public/site`
```json
{
  "site": {
    "name": {"fa": "آریا صنعت پویا", "en": "Arya Sanat Precision Dynamics"},
    "short_name": {"fa": "آریا صنعت"}, "legal_name": {"fa": "..."}, "tagline": {"fa": "..."}, "logo_subtitle": {"fa": "ASPD ENGINEERING GROUP"},
    "alternate_name": "ASPD Group",
    "site_url": "https://aryasanat-corp.ir",
    "branding": {
      "logo_light": {"url": "https://api.example.com/assets/uploads/brand/logo.svg", "alt": {"fa": "..."}, "width": null, "height": null, "mime": "image/svg+xml"},
      "logo_dark": null, "logo_mark": null,
      "favicon": {"ico": "https://.../favicon.ico", "svg": null, "png_32": null, "png_192": null, "png_512": null, "apple_touch": null},
      "og_default_image": null, "theme_color": "#0b4f8a"
    },
    "theme": {"primary": "#0b4f8a", "primary_hover": "#083d6b", "accent": "#c27803", "secondary": "#0f172a", "dark_surface": "#09111f"},
    "contact": {
      "phone": "+98 21 8865 4200", "phone_tel": "+982188654200", "email": "engineering@aryasanat-corp.ir",
      "address": {"fa": "..."}, "working_hours": {"fa": "..."},
      "map": {"lat": 35.7742, "lng": 51.4128, "embed_url": null, "label": {"fa": "..."}}
    },
    "address_structured": {"street": {"fa": "...", "en": "..."}, "city": {"fa": "تهران", "en": "Tehran"}, "region": null, "postal_code": null, "country_code": "IR"},
    "social": [{"platform": "linkedin", "url": "https://...", "label": {"fa": ""}}],
    "header_badges": ["ISO 9001:2015", "IEC 61508 SIL-3", "ISO/IEC 17025"],
    "search_suggestions": {"fa": ["AS-FCV-940", "کوریولیس"], "en": ["AS-FCV-940", "Coriolis"]},
    "seo": {"default_title": {"fa": "..."}, "default_description": {"fa": "..."}, "default_keywords": {"fa": ""},
            "title_template": "{title} | {site_name}", "robots_index": true, "twitter_handle": null,
            "verification": {"google": null, "bing": null}},
    "analytics": {"ga4_id": null, "gtm_id": null},
    "media": {"home.hero": {"url": "...", "alt": {"fa": ""}, "width": null, "height": null, "mime": "image/jpeg"}, "home.intro": null},
    "page_meta": {"home": {"title": {"fa": "..."}, "description": {"fa": "..."}, "keywords": {"fa": ""}, "og_image": null, "noindex": false}},
    "languages": {"default": "fa", "active": [{"code": "fa", "name": "Persian", "native_name": "فارسی", "direction": "rtl", "flag": "🇮🇷"}]}
  },
  "updated_at": "2026-11-01T08:00:00Z"
}
```
- اسلات خالی ⇒ `null` (کلید حاضر). همه‌ی کلیدهای `media` و `page_meta` **همیشه** حاضرند.
- `languages.active` فقط زبان‌های فعال؛ **ردیف `fa` را در صورت نبود در `i18n_languages` همین‌جا بسازید و اینجا همیشه بیاورید** (اشکال موجود 4.3).
- مقادیر **داخلی** (`inquiry_*`) هرگز.
- پنل: `/admin/site-settings` با تب‌ها (هویت، برندینگ، رنگ‌ها، تماس، اجتماعی، سئو، تصاویر ثابت، تحلیل). تغییر ⇒ revalidate با تگ `site`.

---

### 6.2 برندها (`brands`) — P0 (خواسته‌ی مالک)

| فیلد | نوع | i18n | یادداشت |
|---|---|---|---|
| `id`, `slug` (یکتا، قاعده‌ی 3.6) | | | |
| `name` | text الزامی | ✅ | |
| `description` | متن ساده | ✅ | |
| `logo` | تصویر | alt ✅ | |
| `website_url` | URL | — | |
| `sort_order`, `is_active` | | | |
| `meta_title/description/keywords`, `og_image` | | ✅ | ⇒ `seo` مؤثر |

- محصول `brand_id` اختیاری دارد.
- **حذف برند:** اگر محصولی به آن اشاره دارد، حذف ممنوع و پیام روشن (یا `brand_id` محصولات `NULL` شود، با تأیید ادمین).
- **API:**
  - `GET /brands` ⇒ `{"brands": [{id, slug, name, description, logo, website_url, product_count}], "meta": …}` (فقط فعال، به ترتیب `sort_order`).
  - `GET /brands/<slug>` ⇒ همان + `seo`.
  - فیلتر محصولات: `GET /products?brand=<slug>`.
- **وضعیت UI فرانت:** جایی برای برند ندارد؛ فقط JSON-LD محصول `brand` را الان با نام شرکت پر می‌کند. فرانت بعداً برند را (در صورت وجود) در کارت/جزئیات/فیلتر و JSON-LD نشان می‌دهد. نبودِ برند روی محصول = «برند = خود سایت».

---

### 6.3 دسته‌بندی‌ها (گسترش پلاگین `categories`) — P0

دو سطحی (والد ⇢ فرزند) همان‌طور که هست. UI فعلی فرانت «تخت» است (فقط دسته‌های اصلی در منو/کارت‌ها)؛ فرانت **ریشه‌ها** را نشان می‌دهد و فرزندان را اختیاری.

**ستون/جدول‌های جدید (additive):**

| فیلد | نوع | i18n | یادداشت |
|---|---|---|---|
| `name` | text الزامی | ✅ | ستون قدیمی `name` = مقدار `fa` (هم‌گام) |
| `short_description` | متن ساده | ✅ | کارت‌ها/منو |
| `description` | متن ساده | ✅ | ستون قدیمی ⇒ ترجمه‌ی `fa` (HTML‌زدایی شده) |
| `icon` | رشته | — | نام آیکن lucide از فهرست پیوست ب (فعلاً `Gauge, Cpu, Activity, Zap`)؛ نامعتبر ⇒ رد |
| `cover_image` | تصویر | alt ✅ | |
| `standards` | لیست رشته | — | مثل `IEC 60534`, `ASME B16.34` (مستقل از زبان) |
| `key_highlights` | لیست متن | ✅ | «شاخصه‌های مهندسی» |
| `sort_order` | int | — | ترتیب نمایش (الان ترتیب `id` است) |
| `og_image`, `noindex` | | | + `meta_*` قدیمی ⇒ ترجمه‌پذیر |

**API**
- `GET /categories?include_empty=0|1` ⇒ **درخت** ریشه‌ها:
```ts
type CategoryCard = { id; slug; parent_slug: string | null; name: I18nText; short_description: I18nText; icon: string | null;
                      cover: Media; standards: string[]; product_count: number; sort_order: number };
// پاسخ: { categories: (CategoryCard & { children: CategoryCard[] })[] }
```
  فقط فعال و حذف‌نشده؛ ریشه‌ی غیرفعال ⇒ فرزندانش هم پنهان (مثل رفتار فعلی). `product_count` = تعداد محصولات **منتشرشده** در دسته **و فرزندان مستقیم**. `include_empty` پیش‌فرض `1`.
- `GET /categories/<slug>` ⇒ `{ "category": CategoryCard & { description, key_highlights: I18nList, parent: {slug,name}|null, children: CategoryCard[], seo, updated_at } }`. ناموجود/غیرفعال ⇒ 404 JSON.
- ترتیب: `sort_order ASC, id ASC` (نه ترتیب تضمین‌نشده‌ی فعلی).
- **کش:** هر ایجاد/ویرایش/حذف/toggle دسته، کش `products` را هم پاک کند (اشکال موجود: پاک نمی‌شود).

---

### 6.4 محصولات (گسترش پلاگین `products`) — P0

**اصل:** سایت معرفی شرکت است؛ فیلدهای `price/old_price/stock/sku` در ستون‌ها **می‌مانند** (API قدیمی) ولی **در `/api/public/*` اصلاً برنگردانید** (به‌جز `sku` اختیاری). پیشنهاد P2: تنظیم «حالت کاتالوگ سازمانی» که این فیلدها را از فرم ادمین پنهان می‌کند.

#### 6.4.1 فیلدهای محصول

| فیلد | نوع | i18n | یادداشت |
|---|---|---|---|
| `slug` | قاعده‌ی 3.6 | — | **الزامی برای انتشار** |
| `model_code` | text ≤80، **ایندکس‌شده** | — | مثل `AS-FCV-940`؛ الزامی برای انتشار |
| `name` | text الزامی | ✅ | ستون قدیمی ⇒ `fa` |
| `subtitle` | text | ✅ | |
| `short_description` | متن ساده | ✅ | کارت و متای توضیح |
| `description` | متن ساده، چندپاراگرافی | ✅ | ستون قدیمی (HTML) ⇒ `fa` پس از HTML‌زدایی |
| `features` | لیست متن | ✅ | «ویژگی‌ها و مزایای کلیدی» (5 مورد معمول) |
| `category_id` | int | — | **قابل‌پاک‌شدن** (نه مثل رفتار فعلی) |
| `brand_id` | int | — | 6.2 |
| `tags` | M2M تگ | — | 6.4.2 |
| `certifications` | لیست رشته | — | مثل `IEC 60534`, `SIL-3` (مستقل از زبان) |
| `is_featured` | bool | — | «شاخص» (کارت پررنگ، ترتیب، صفحه‌ی اصلی) |
| `is_new` | bool | — | نشان «نسل جدید» |
| `sort_order` | int | — | |
| `status`, `published_at` | 3.7 | — | |
| `meta_title/description/keywords`, `og_image`, `noindex` | | ✅ (متا) | ⇒ `seo` مؤثر |
| `sku` | text | — | اختیاری؛ داخل جستجو |
| `updated_at` | auto | — | **ستون جدید** (الان فقط `created_at` هست)؛ با هر تغییر خودِ محصول یا زیرمجموعه‌هایش (specs/variants/docs/images/tags) به‌روز شود؛ برای sitemap و ETag |

**ستون جستجو:** `search_text` (نرمال‌شده، بخش 6.11) را هر بار ذخیره‌ی محصول و تغییر زیرمجموعه‌ها بازسازی کنید.

#### 6.4.2 تگ‌ها (`product_tags`)
`slug` (یکتا)، `label` ✅ (الزامی `fa`)، `sort_order`. اتصال M2M. در فرم محصول: ورودی تگ با autocomplete و **ایجاد در لحظه** (برچسب `fa` الزامی). حذف تگ: از همه‌ی محصولات جدا می‌شود (با تأیید).
`GET /tags?category=<slug>` ⇒ `{"tags": [{"slug","label","product_count"}]}` (فقط تگ‌هایی که حداقل یک محصول منتشرشده دارند؛ در صورت `category` فقط در همان دسته).

#### 6.4.3 مشخصات فنی (`product_specs`)
ردیف‌های مرتب: `label` ✅، `value` ✅ (هر دو متن کوتاه؛ `value` ممکن است در دو زبان یکسان باشد). تعداد معمول 3 تا 8. در پنل: repeater با افزودن/حذف/**جابه‌جایی** ردیف.

#### 6.4.4 مدل‌ها / پیکربندی‌ها (`product_variants`)
`model_code` (متن، مستقل از زبان، مثل `AS-FCV-940-S2`)، `name` ✅، `configuration` ✅، `operating_range` ✅، `application` ✅، `sort_order`. repeater در پنل.

#### 6.4.5 تصاویر (`product_images` — گسترش)
- جدول موجود: `url, alt, sort_order`؛ **ارتقا:** `alt` ⇒ i18n، `sort_order` واقعاً قابل‌تنظیم (drag/ترتیب دستی)، **اولین تصویر = کاور**.
- افزودن از **انتخابگر رسانه** (کتابخانه‌ی موجود `/admin/images`) یا آپلود مستقیم. ذخیره‌ی مسیر نسبی؛ API مطلقش می‌کند (3.4).
- تصویر نبودن محصول مجاز است (`images: []`، `cover: null`)؛ فرانت placeholder (اسلات `product.placeholder`) می‌گذارد.

#### 6.4.6 اسناد و فایل‌های قابل‌دانلود (`product_documents`) ← **«فایل‌ها و PDFها»**

**مدل:** یک سند = عنوان i18n + نوع + ویرایش (revision) + **یک فایل به‌ازای هر زبان** (حداقل یکی).

| فیلد سند | نوع | یادداشت |
|---|---|---|
| `type` | enum | `datasheet, manual, certificate, cad, brochure, other` |
| `title` | text ✅ | الزامی `fa` |
| `revision` | text ≤32 | مثل `Rev 4.2`, `2026` |
| `sort_order`, `is_public` | | `is_public=false` ⇒ در API عمومی نمی‌آید (آماده‌ی آینده) |

| فیلد فایل (به‌ازای زبان) | |
|---|---|
| `lang_code` | زبان فایل (`fa`, `en`) |
| فایل | آپلود multipart؛ نام اصلی (`original_filename`)، `mime`، `size_bytes`، `sha256` ذخیره شود |
| `format_label` | پیش‌فرض از پسوند (`PDF`, `STEP`, `DWG`, `ZIP`)، قابل‌override با متن کوتاه (مثل `STEP / DWG`) |
| `download_count` | شمارنده |

**قواعد آپلود (سخت‌گیرانه؛ فقط مسیر اسناد):**
- پسوند مجاز (فهرست‌سفید، قابل‌تغییر با `DOCUMENT_ALLOWED_EXTENSIONS`): `pdf, zip, step, stp, igs, iges, dwg, dxf, doc, docx, xls, xlsx, ppt, pptx, csv, txt, png, jpg, jpeg, webp`.
- **هرگز** قابل‌اجرا/اسکریپت: `html, htm, js, mjs, php, py, sh, bat, cmd, exe, dll, svg, …` (رد با 422/پیام فارسی).
- سقف حجم هر فایل: `DOCUMENT_MAX_SIZE_MB` (پیش‌فرض 50). بالاتر ⇒ رد قبل از ذخیره‌ی کامل.
- اعتبارسنجی محتوا برای `pdf` (شروع `%PDF-`)، `zip` (امضای `PK`)، تصاویر (Pillow) — عدم تطابق ⇒ رد.
- **ذخیره‌سازی خارج از `uploads/`** (مثلاً `storage/documents/<yyyy>/<uuid>.<ext>`) تا از مسیر عمومی `/assets/uploads/` دور زده نشود؛ نام ذخیره‌شده تصادفی، نام اصلی فقط در DB.
- حذف سند/فایل ⇒ حذف فیزیکی فایل از دیسک.
- (سهمیه‌ی کل `ASSETS_DIR_Max_Size` برای اسناد هم اعمال شود یا سهمیه‌ی جدا؛ تصمیم با شما، در سند نهایی بنویسید.)

**دانلود:** `GET /api/public/documents/<int:id>/download?lang=<code>&inline=0|1`
- `lang` اختیاری: فایل همان زبان؛ نبود ⇒ `fa` ⇒ اولین فایل موجود.
- `Content-Disposition: attachment; filename*=UTF-8''<نام اصلی>`؛ `inline=1` فقط برای `pdf` و تصاویر ⇒ `inline`. `Content-Type` درست، `Content-Length`، `X-Content-Type-Options: nosniff`، `Cache-Control: public, max-age=3600`. پشتیبانی `HEAD`. Range اختیاری.
- سند/فایل ناموجود، یا `is_public=false`، یا مالکِ سند (محصول منتشرنشده / گواهینامه‌ی غیرفعال) ⇒ 404 JSON. این endpoint برای اسناد هر مالکی کار می‌کند (محصول و گواهینامه‌ی شرکت، بخش 6.9).
- `download_count` را افزایش دهید (فقط `GET` بدون `Range`، ترجیحاً ناهمگام).
- **لازم نیست احراز هویت**.

#### 6.4.7 پاسخ‌های API

**`GET /api/public/products`**

| پارامتر | معنی |
|---|---|
| `q` | جستجو (نرمال‌شده، 6.11) روی کد مدل، sku، نام/زیرعنوان/توضیح‌کوتاه همه‌ی زبان‌ها، تگ‌ها، گواهی‌ها، نام برند، کد مدل‌های variant |
| `category` | slug؛ **شامل فرزندان** |
| `brand` | slug برند |
| `tag` | slug تگ (چندتا با ویرگول ⇒ AND) |
| `featured` | `1` ⇒ فقط شاخص‌ها |
| `is_new` | `1` ⇒ فقط جدیدها |
| `sort` | `featured` (پیش‌فرض: شاخص‌ها اول، بعد `model_code` صعودی) · `name` (بر اساس نام زبان `lang`) · `model_code` · `newest` (`published_at` نزولی) · `manual` (`sort_order, id`) |
| `lang` | `fa`/`en` فقط برای `sort=name` (ترتیب‌دهی محلی) و رتبه‌بندی `q`؛ پیش‌فرض `fa` |
| `page`, `per_page` | پیش‌فرض 12، سقف 100 |
| `facets` | `1` ⇒ شمارنده‌ها (پایین) |

```json
{
  "products": [ProductCard, …],
  "meta": {"total": 8, "page": 1, "per_page": 12, "total_pages": 1},
  "facets": {"categories": [{"slug": "flow-control-valves", "count": 2}], "brands": [{"slug": "...", "count": 1}], "tags": [{"slug": "sil-3", "count": 3}]}
}
```
`facets` (فقط با `facets=1`): هر وجه با اعمال **همه‌ی فیلترهای دیگر به‌جز خودش** شمارش شود (تا «همه‌ی دسته‌ها (N)» و شمارنده‌ی هر دسته درست باشد). اگر پیاده‌سازی کامل سخت است، حداقل شمارنده‌ی کلِ هر وجه روی کل محصولات منتشرشده و آن را در «انحراف‌ها» بنویسید.

```ts
type ProductCard = {
  id: number; slug: string; model_code: string;
  name: I18nText; subtitle: I18nText; short_description: I18nText;
  featured: boolean; is_new: boolean;
  cover: Media;
  category: { slug: string; name: I18nText } | null;
  brand: { slug: string; name: I18nText; logo: Media } | null;
  tags: { slug: string; label: I18nText }[];
  certifications: string[];
  updated_at: string;
};
```

**`GET /api/public/products/<slug>`** (فقط `slug`، نه id؛ slug فارسی با URL-encode):
```ts
type ProductDetail = ProductCard & {
  sku: string | null;
  description: I18nText;                       // متن ساده با \n بین پاراگراف‌ها
  features: I18nList;
  images: Media[];                             // مرتب؛ images[0] = cover
  specifications: { label: I18nText; value: I18nText }[];
  variants: { model_code: string; name: I18nText; configuration: I18nText; operating_range: I18nText; application: I18nText }[];
  documents: ProductDocument[];
  category_path: { slug: string; name: I18nText }[];   // ریشه ← برگ (برای breadcrumb)
  related: ProductCard[];                      // هم‌دسته (بدون خودش) سپس بقیه، با sort=featured؛ ?related_limit=3 (1..12)
  seo: Seo;
  created_at: string; published_at: string | null;
};
type ProductDocument = {
  id: number; type: "datasheet" | "manual" | "certificate" | "cad" | "brochure" | "other";
  title: I18nText; revision: string | null; updated_at: string;
  files: { [lang: string]: { download_url: string; view_url: string | null; format: string; mime: string; size_bytes: number; size_label: string } };
};
```
- `download_url` **مطلق** و به endpoint دانلود (6.4.6) اشاره دارد (`...?lang=<lang>`). `view_url` (با `inline=1`) فقط برای PDF/تصویر، وگرنه `null`. `size_label` مثل `"2.4 MB"` (واحد انگلیسی، ارقام لاتین).
- محصول ناموجود/`draft`/زمان‌بندی‌نشده ⇒ 404 JSON `{"ok":false,"error":"not_found"}`.

**مهاجرت داده‌ی فعلی:** هر محصول موجود: `name/description/meta_*` ⇒ ترجمه‌ی `fa`؛ `model_code` خالی (ادمین باید پر کند — محصول بدون `model_code` منتشر **نشود**، یا حداقل در پنل هشدار بدهد)؛ بقیه‌ی فیلدهای جدید خالی.

---

### 6.5 پروژه‌ها (`projects`) — P1

| فیلد | نوع | i18n | یادداشت |
|---|---|---|---|
| `slug` | 3.6 | — | |
| `title` | text الزامی | ✅ | |
| `sector_id` | FK به `project_sectors` | — | الزامی |
| `client` | text | ✅ | نام کارفرما (در فرانت زیر برچسب «بخش صنعتی کارفرما» نشان داده می‌شود) |
| `location` | text | ✅ | |
| `completion_year` | int (میلادی، 1900..2100) | — | فرانت تبدیل جلالی را خودش می‌کند |
| `cover_image` | تصویر | alt ✅ | |
| `gallery` | [{image, alt ✅, sort}] | | |
| `short_description` | متن ساده | ✅ | |
| `challenge`, `solution` | متن ساده | ✅ | |
| `impact_metrics` | [{label ✅, value ✅, sort}] | | «دستاوردهای کمی» (معمولاً 3) |
| `specifications` | [{label ✅, value ✅, sort}] | | «شناسنامه فنی» |
| `products` | M2M مرتب به محصولات | — | «تجهیزات به‌کاررفته» (مرتب) |
| `is_featured`, `sort_order` | | | صفحه‌ی اصلی |
| `status`, `published_at`, `meta_*`, `og_image`, `noindex` | | | |

**`project_sectors`:** `slug`، `label` ✅ (مثل «آب و نمک‌زدایی»)، `sort_order`. (الان 5 مقدار enum: `energy, water, petrochemical, pharma, manufacturing` ⇒ به‌عنوان رکوردهای seed.)

**API**
- `GET /projects?sector=<slug>&q=&featured=1&sort=newest|manual&page=&per_page=` (پیش‌فرض `per_page=12`، `sort=newest` = `completion_year DESC, id DESC`) ⇒ `{"projects":[ProjectCard], "meta"}`.
```ts
type ProjectCard = { id; slug; title: I18nText; sector: {slug; label: I18nText}; location: I18nText; completion_year: number | null;
                     cover: Media; short_description: I18nText; featured: boolean;
                     highlight_metric: { label: I18nText; value: I18nText } | null;   // اولین impact_metrics
                     updated_at: string };
```
- `GET /projects/<slug>` ⇒ `{"project": ProjectCard & {client, challenge, solution, gallery: Media[], impact_metrics: {label,value}[], specifications: {label,value}[], products: ProductCard[], related_projects: ProjectCard[], seo}}`. `related_projects`: هم‌بخش اول، بعد بقیه؛ `?related_limit=2` (1..12). `products` فقط **منتشرشده‌ها** را شامل شود.
- `GET /project-sectors` ⇒ `{"sectors":[{"slug","label","project_count"}]}` (فقط بخش‌هایی که پروژه‌ی منتشرشده دارند).

---

### 6.6 اخبار و مقالات (`articles`) — P1

| فیلد | نوع | i18n | یادداشت |
|---|---|---|---|
| `slug` | 3.6 | — | |
| `title`, `excerpt` | text / متن ساده | ✅ | |
| `category_id` | FK به `article_categories` | — | الزامی |
| `published_at` | datetime | — | الزامی برای انتشار؛ آینده ⇒ زمان‌بندی (3.7) |
| `reading_time_minutes` | int اختیاری | — | خالی ⇒ **خودکار** از مجموع کلمات (≈200 کلمه/دقیقه، حداقل 1) |
| `author_name`, `author_role` | text | ✅ | نویسنده‌ی درون‌خطی (جدول نویسنده لازم نیست) |
| `cover_image` | تصویر | alt ✅ | |
| `is_featured` | bool | — | «مقاله‌ی ویژه» |
| `sections` | مرتب | | هر بخش: `anchor` (slug یکتا در مقاله؛ خودکار از عنوان)، `heading` ✅، `paragraphs` (لیست پاراگراف ✅؛ در پنل: textarea با خط خالی بین پاراگراف‌ها) |
| `status`, `meta_*`, `og_image`, `noindex` | | | |

**`article_categories`:** `slug`, `label` ✅, `sort_order` (seed: `engineering, innovation, standards, corporate`).

**API**
- `GET /articles?category=<slug>&q=&featured=1&page=&per_page=` (پیش‌فرض `per_page=12`؛ **`published_at DESC`**؛ فقط `published_at <= now`) ⇒ `{"articles":[ArticleCard], "meta"}`.
```ts
type ArticleCard = { id; slug; title: I18nText; excerpt: I18nText; category: {slug; label: I18nText};
                     published_at: string; reading_time_minutes: number;
                     author: {name: I18nText; role: I18nText}; cover: Media; featured: boolean; updated_at: string };
```
- `GET /articles/<slug>` ⇒ `{"article": ArticleCard & {sections: {anchor: string; heading: I18nText; paragraphs: I18nList}[], related: ArticleCard[], seo}}`؛ `related` = جدیدترین‌های دیگر (`?related_limit=3`).
- `GET /article-categories` ⇒ `{"categories":[{"slug","label","article_count"}]}`.

---

### 6.7 خدمات (`services`) — P1

**`services`:** `slug`، `icon` (نام lucide از لیست پیوست ب: `Settings, ShieldCheck, Compass, Cpu, Wrench, Award`)، `title` ✅، `short_description` ✅، `description` ✅ (متن ساده)، `deliverables` (لیست متن ✅)، `industries` (لیست متن ✅)، `sort_order`، `is_active`، `meta_*`.
**`service_process_steps`:** `title` ✅، `description` ✅، `sort_order` (سراسری برای صفحه‌ی خدمات؛ 5 مرحله).

`GET /services` ⇒ (بدون صفحه‌بندی؛ هر دو لیست کامل و مرتب)
```json
{"services": [{"id": 1, "slug": "...", "icon": "Compass", "title": {"fa": "..."}, "short_description": {"fa": "..."}, "description": {"fa": "..."},
               "deliverables": {"fa": ["..."]}, "industries": {"fa": ["..."]}}],
 "process_steps": [{"step_number": "01", "title": {"fa": "..."}, "description": {"fa": "..."}}]}
```
`step_number` را سرور از ترتیب بسازد (`01`، `02`، …). فرانت صفحه‌ی جزئیات خدمت ندارد؛ در صورت لزوم بعداً `GET /services/<slug>` اضافه می‌شود (اکنون لازم نیست).

---

### 6.8 پرسش‌های متداول (`faq`) — P1

**`faq_categories`:** `slug`, `label` ✅, `sort_order` (seed: `engineering, documentation, support, corporate`). **`faq_items`:** `category_id`، `question` ✅، `answer` ✅ (متن ساده)، `sort_order`، `is_active`.

`GET /faq` ⇒ `{"categories":[{"slug","label","count"}], "items":[{"id","category":{"slug","label"},"question":I18nText,"answer":I18nText}]}` (کل لیست، مرتب بر اساس `category.sort_order, item.sort_order`).

---

### 6.9 محتوای شرکت (`company`) — P1

یک پلاگین با 7 مجموعه‌ی ساده، هرکدام مرتب با `sort_order` و `is_active`، و یک پنل `/admin/company` با تب‌ها.

| مجموعه | فیلدها (i18n ✅) |
|---|---|
| **stats** (آمار؛ 4 مورد معمول) | `value` (عدد، شمارنده‌ی انیمیشنی)، `suffix` ✅ (مثل `+ سال`، `+`، ` مترمربع`)، `label` ✅، `sublabel` ✅ |
| **timeline** (گاه‌شمار) | `year` (متن ≤8، میلادی، مثل `2005`)، `title` ✅، `description` ✅ |
| **team** (مدیران) | `name` ✅، `role` ✅، `qualification` ✅، `bio` ✅، `photo` (تصویر اختیاری؛ الان ندارد) |
| **certifications** (گواهینامه‌ها) | `code` (متن مستقل از زبان، مثل `ISO 9001:2015`)، `title` ✅، `issuer` ✅، `description` ✅، `logo` (اختیاری)، `document` (فایل PDF اختیاری با همان قواعد 6.4.6؛ گواهی قابل‌دانلود) |
| **industries** (صنایع هدف) | `icon` (از لیست پیوست ب: `Flame, Droplets, Factory, FlaskConical, Zap, Cpu`)، `title` ✅، `description` ✅ |
| **testimonials** (نظرات) | `quote` ✅، `author_name` ✅، `author_role` ✅، `organization` ✅، `sector` ✅، `photo` (اختیاری) |
| **offices** (دفاتر) | `title` ✅، `address` ✅، `phone`، `email`، `hours` ✅، `lat`, `lng` (اختیاری)، `is_primary` (یکی) |

`GET /company?include=stats,timeline,team,certifications,industries,testimonials,offices` (پیش‌فرض: همه) ⇒
```json
{"stats": [{"id": 1, "value": 27, "suffix": {"fa": "+ سال", "en": "+ Yrs"}, "label": {"fa": "..."}, "sublabel": {"fa": "..."}}],
 "timeline": [{"year": "1998", "title": {"fa": "..."}, "description": {"fa": "..."}}],
 "team": [{"id": 1, "name": {"fa": "..."}, "role": {"fa": "..."}, "qualification": {"fa": "..."}, "bio": {"fa": "..."}, "photo": null}],
 "certifications": [{"id": 1, "code": "ISO 9001:2015", "title": {"fa": "..."}, "issuer": {"fa": "..."}, "description": {"fa": "..."}, "logo": null, "document": null}],
 "industries": [{"id": 1, "icon": "Zap", "title": {"fa": "..."}, "description": {"fa": "..."}}],
 "testimonials": [{"id": 1, "quote": {"fa": "..."}, "author_name": {"fa": "..."}, "author_role": {"fa": "..."}, "organization": {"fa": "..."}, "sector": {"fa": "..."}, "photo": null}],
 "offices": [{"id": 1, "title": {"fa": "..."}, "address": {"fa": "..."}, "phone": "+98 21 8865 4200", "phone_tel": "+982188654200", "email": "x@y.ir", "hours": {"fa": "..."}, "lat": 35.7742, "lng": 51.4128, "coordinates_label": "35.7742° N, 51.4128° E", "is_primary": true}]}
```
- `document` در certifications (در صورت وجود) همان شکل سند در 6.4.6 را دارد: `{"id", "type", "title", "revision", "updated_at", "files": {"<lang>": {...}}}` (برای `null` وقتی گواهی فایل ندارد).
  **پیاده‌سازی:** مدل سند و فایل 6.4.6 را **یک‌بار و مشترک** بسازید (پیشنهاد: جدول `documents` با ستون‌های `owner_type` ∈ `product`/`certification` و `owner_id`، و جدول `document_files`). دانلود هر دو از همان `GET /documents/<id>/download` است؛ همه‌ی قواعد آپلود/اعتبارسنجی 6.4.6 برای هر دو مالک یکسان اعمال می‌شود.
- `coordinates_label` را سرور از `lat/lng` بسازد (`N/S`, `E/W`).

---

### 6.10 استعلام‌ها / فرم تماس (`inquiries`) — P1

فرانت فرم را با `react-hook-form + zod` اعتبارسنجی می‌کند؛ **بک‌اند باید قوانین را عیناً تکرار کند** (اعتماد به کلاینت ممنوع).

**`POST /api/public/inquiries`** (`Content-Type: application/json`):

| فیلد | الزامی | قانون |
|---|---|---|
| `full_name` | ✅ | trim، 3..160 |
| `email` | ✅ | ایمیل معتبر، ≤200 |
| `phone` | ✅ | trim، 8..60 (بدون الزام قالب خاص؛ ارقام فارسی/عربی/لاتین، `+ - ( ) فاصله`) |
| `company` | — | ≤160 |
| `subject` | ✅ | 4..240 |
| `product_code` | — | ≤80 (کد مدل؛ اگر با `model_code` محصولی منطبق بود `product_id` را ذخیره کنید) |
| `message` | ✅ | 15..5000 |
| `locale` | — | `fa`/`en`، پیش‌فرض `fa` |
| `website` | — | **honeypot**؛ اگر پر بود ⇒ `201` ظاهری و **ذخیره نشود** (ربات را آگاه نکنید) |

- **پاسخ موفق** `201`: `{"ok": true, "reference_code": "ASPD-2026-0001"}`.
  - **شماره‌ی رهگیری:** `<PREFIX>-<سال میلادی>-<شمارنده‌ی 4 رقمی صفرپر>`، **ترتیبی و اتمی** (شمارنده‌ی سالانه در DB با قفل/تراکنش؛ نه تصادفی مثل نمونه‌ی فعلی فرانت که برخورد دارد). `PREFIX` از تنظیمات (`inquiry_reference_prefix`، پیش‌فرض `INQ`). یکتا با UNIQUE index.
- **اعتبارسنجی ناموفق** `422`: `{"ok": false, "error": "validation_failed", "fields": {"email": {"code": "invalid_email"}, "message": {"code": "too_short", "min": 15}}}`. کدها: `required`, `too_short` (با `min`), `too_long` (با `max`), `invalid_email`, `invalid_value`. (متن کاربر را فرانت از i18n می‌سازد.)
- **Rate limit:** پیش‌فرض 5 درخواست/ساعت/IP و 20 درخواست/روز/IP (قابل‌تنظیم با `.env`)؛ تجاوز ⇒ `429` + `Retry-After`. **IP واقعی** مطابق 9.2 `backend-doc.md` (`X-Real-IP` ← `X-Forwarded-For` ← `remote_addr`). (چون فرانت ممکن است سمت سرور فراخوانی کند، آن هدرها را باید forward کند؛ در سند نهایی بنویسید.)
- حداکثر اندازه‌ی بدنه 64KB؛ بدنه‌ی غیر JSON ⇒ 400.
- **ذخیره:** جدول `inquiries` با فیلدهای بالا + `reference_code`, `status`, `ip`, `user_agent`, `created_at`, `handled_by`, `internal_note`, `answered_at`. (ip/ua فقط داخلی.)
- **اعلان ایمیلی** (اگر SMTP تنظیم شده؛ ناهمگام و بدون شکستن پاسخ): به `inquiry_notify_emails`. رمز SMTP فقط `.env`. نبود SMTP ⇒ فقط ذخیره، هشدار در پنل.
- **پنل `/admin/inquiries`:** لیست با جست‌وجو/فیلتر (وضعیت، بازه‌ی تاریخ، کد محصول)، صفحه‌بندی، نمایش جزئیات، تغییر وضعیت (`new`, `in_progress`, `answered`, `closed`, `spam`)، یادداشت داخلی، **خروجی CSV**، شمارنده‌ی «جدید» روی کاشی داشبورد. حذف فقط ادمین، با تأیید.
- **هرگز** در `/api/public/*` اطلاعات استعلام‌ها بازگردانده نشود.
- P2: توکن کپچا (Turnstile/hCaptcha) با فیلد اختیاری `captcha_token`.

---

### 6.11 جستجو — P1

**`GET /api/public/search?q=<text>&limit=20&types=products,projects,articles,pages`**

```json
{"query": "کوریولیس",
 "totals": {"products": 1, "projects": 0, "articles": 1, "pages": 0, "all": 2},
 "products": [ProductCard], "projects": [ProjectCard], "articles": [ArticleCard],
 "pages": [{"page_key": "about", "path": "/about", "title": I18nText, "description": I18nText}]}
```
- `q` خالی/کوتاه‌تر از 2 نویسه ⇒ `200` با همه‌ی لیست‌ها خالی و `totals` صفر (نه خطا). `limit` هر گروه 1..50 (پیش‌فرض 20).
- **جستجو در همه‌ی زبان‌ها** (نتیجه به زبان درخواست محدود نمی‌شود؛ کاربر انگلیسی ممکن است کد فارسی بزند).
- **نرمال‌سازی (الزامی، چون فارسی است):** هم روی query و هم روی `search_text` ذخیره‌شده: lower-case، تبدیل `ي→ی`، `ك→ک`، حذف ZWNJ/کشیده/اعراب، یکسان‌سازی ارقام فارسی/عربی/لاتین، فشرده‌سازی فاصله‌ها. escape کاراکترهای `% _ \` برای LIKE.
- **محدوده:**
  - محصولات: `model_code, sku`، نام/زیرعنوان/توضیح‌کوتاه همه‌ی زبان‌ها، تگ‌ها، گواهی‌ها، نام برند، `model_code` مدل‌ها.
  - پروژه‌ها: عنوان، توضیح کوتاه، محل، برچسب بخش.
  - مقالات: عنوان، چکیده، برچسب موضوع.
  - صفحات: از `page_meta` (عنوان/توضیح همه‌ی زبان‌ها) برای `about, products, services, projects, contact, faq`.
- رتبه‌بندی ساده: تطابق دقیق `model_code` > شروع نام > شامل بودن. (فقط منتشرشده‌ها.)
- پیاده‌سازی با `LIKE` روی ستون `search_text` کافی است؛ FULLTEXT اختیاری.

---

### 6.12 تجمیعی‌ها: `home`، `sitemap`، `health` — P1/P0

**`GET /api/public/home?featured_products=4&projects=3&articles=3`** (برای کاهش round-trip صفحه‌ی اصلی؛ همه‌ی شکل‌ها همان کارت‌ها)
```jsonc
{"featured_products": [ProductCard],        // is_featured، sort=featured؛ اگر کمتر از N بود با جدیدترین‌ها پر شود
 "categories": [CategoryCard],               // فقط ریشه‌ها، ترتیب sort_order
 "featured_projects": [ProjectCard],         // is_featured؛ اگر کمتر بود با جدیدترین‌ها پر شود
 "latest_articles": [ArticleCard],
 "stats": [...], "industries": [...], "certifications": [...], "testimonials": [...], "offices": [...]}   // همان شکل 6.9
```
سقف‌ها: هرکدام 1..12.

**`GET /api/public/sitemap`** (فقط منتشرشده‌ها؛ بدون صفحه‌بندی)
```json
{"site_url": "https://aryasanat-corp.ir",
 "pages": [{"path": "/", "updated_at": "..."}],
 "categories": [{"slug": "...", "updated_at": "..."}],
 "products": [{"slug": "...", "updated_at": "...", "images": ["https://..."]}],
 "projects": [{"slug": "...", "updated_at": "..."}],
 "articles": [{"slug": "...", "updated_at": "..."}]}
```
`pages[].updated_at` = آخرین تغییر `page_meta`/محتوای مرتبط یا `site.updated_at`. محصولات/پروژه/مقاله‌ی `noindex` را **حذف** کنید.

**`GET /api/public/health`** ⇒ `{"ok": true, "db": true, "version": "<git sha یا نسخه>", "time": "..."}`؛ DB خراب ⇒ `503 {"ok": false, "db": false}`. بدون کش.

---

### 6.13 رشته‌های رابط (i18n) — P0

فرانت ≈330 رشته‌ی رابط دارد (عنوان‌ها، دکمه‌ها، متن صفحه‌ی اصلی/درباره، پیام‌های اعتبارسنجی، …) در دو فایل JSON تودرتو با گروه‌های: `brand, seo, nav, common, home, about, products, services, projects, news, contact, faq, search, footer, notFound`. این‌ها باید از همان سیستم i18n موجود (پنل `/admin/i18n/<code>/translate`) قابل‌ویرایش شوند.

**⚠️ تداخل نام:** کلیدهای فرانت با کلیدهای پنل ادمین فعلی هم‌نام‌اند (`nav.home`, `nav.products`, `product.*`, `settings.*`, …) با معنای متفاوت. **پیشوند اجباری `web.`** بگذارید: `web.nav.home`، `web.home.heroTitle`، `web.contact.validation.nameMin`. کلیدهای پنل ادمین را دست نزنید.

**افزودنی‌ها (additive، API فعلی نشکند):**
1. **ورود (import) از JSON تودرتو:**
   - دستور مدیریتی/اسکریپت `import_ui_strings --lang fa --file fa.json --prefix web. [--mode missing|overwrite]` و **دکمه‌ی آپلود در پنل** `/admin/i18n/<code>/import`.
   - JSON تودرتو را به کلید نقطه‌دار تخت تبدیل می‌کند (`{"nav":{"home":"x"}}` ⇒ `web.nav.home`)، مقدارها را با `{shown}`/`{query}` دست‌نخورده نگه می‌دارد.
   - پیش‌فرض `missing` (فقط کلیدهای موجود‌نبوده؛ ویرایش‌های ادمین بازنویسی نشود). `overwrite` فقط با تأیید صریح.
   - کلیدها را ثبت کنید (`Plugin.register_keys`/معادل) تا در پنل ترجمه ظاهر شوند و **گروه‌بندی بر اساس پیشوند** نمایش داده شوند (≈330 کلید یک‌جا ناخوانا می‌شود).
   - **ورودی:** دو فایل `fa.json` و `en.json` فرانت (`src/locales/`) که مالک پروژه همراه این سند می‌دهد. اگر در دسترس نبود، importer را بسازید و با JSON نمونه تست کنید.
2. **افزودنی‌های `GET /api/i18n/translate/<code>`** (پارامترهای جدید اختیاری):
   - `prefix=web.` ⇒ فقط کلیدهای دارای این پیشوند.
   - `strip_prefix=1` ⇒ پیشوند از کلیدها حذف شود (`nav.home`).
   - `fallback=1` ⇒ کلیدهای ترجمه‌نشده از `fa` پر شوند (در حال حاضر API fallback ندارد؛ بخش 4.3 `backend-doc.md`).
   - `ETag`/`304`.
   - رفتار بدون پارامتر **عیناً مثل قبل**.
3. **ردیف `fa` در `i18n_languages` هنگام boot ساخته شود** (اشکال موجود: ممکن است نباشد).
4. **تغییر ترجمه ⇒ revalidate با تگ `i18n`** (6.15).

---

### 6.14 رسانه و فایل‌ها — P0/P1

1. **URL مطلق** (3.4) و نرمال‌سازی مسیر.
2. **انتخابگر رسانه برای فرم‌های ادمین** (modal): نیاز به **API داخلی ادمین** `GET /admin/media/browse?folder=&q=&ext=&page=` (🔒، JSON: `{"folders":[...], "files":[{"name","rel","url","size","ext","width","height","is_image","mtime"}], "page", "total"}`) + آپلود درون modal (همان `POST /admin/images/upload` با `ajax=1`). منبع حقیقت = دیسک (جدول `images` خراب است؛ نخوانید، 8.1 `backend-doc.md`).
3. **سربرگ‌های کش برای فایل‌های رسانه** (`/assets/uploads/*`): `Cache-Control: public, max-age=31536000, immutable` (نام فایل هرگز بازنویسی نمی‌شود؛ پسوند `-1/-2`) — فقط اگر ویرایش متنی `/admin/images/edit` فایل‌های تصویری را بازنویسی نمی‌کند؛ در غیر این صورت `max-age=86400`.
4. **SVG:** مجاز برای لوگو؛ پاسخ SVG با `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox` سرو شود (جلوگیری از اسکریپت در صورت باز شدن مستقیم).
5. **اسناد قابل‌دانلود** جدا از رسانه‌ی عمومی (6.4.6).
6. **ابعاد تصویر** در پاسخ‌ها (`width/height`) در صورت وجود Pillow.
7. alt متن i18n برای هر تصویری که در موجودیت‌ها استفاده می‌شود (در خود موجودیت، نه در کتابخانه).

---

### 6.15 Revalidation (به‌روزرسانی فوری فرانت) — P1

فرانت (Next.js) پاسخ‌ها را کش می‌کند. با هر تغییر محتوا، بک‌اند باید به فرانت خبر دهد.

- `.env`: `FRONTEND_REVALIDATE_URL` (مثلاً `https://aryasanat-corp.ir/api/revalidate`)، `FRONTEND_REVALIDATE_SECRET`. هر کدام نبود ⇒ ویژگی غیرفعال (بی‌صدا؛ هشدار در پنل).
- **درخواست:** `POST <URL>` با `Content-Type: application/json`، هدر `X-Revalidate-Secret: <secret>`، بدنه:
```json
{"event": "content.changed", "tags": ["products", "product:as-fcv-940", "sitemap"], "at": "2026-11-01T08:00:00Z"}
```
- **ناهمگام و غیرمسدودکننده** (thread/صف؛ پاسخ ادمین منتظر آن نماند)، timeout 3 ثانیه، 3 بار تلاش با backoff، شکست فقط لاگ (نه خطا). چند رویداد در 2 ثانیه ⇒ **ادغام** در یک درخواست (اجتماع تگ‌ها).
- **کاتالوگ تگ‌ها (ثابت؛ فرانت بر اساس آن fetch را برچسب می‌زند):**

| تگ | چه زمانی |
|---|---|
| `site` | تنظیمات سایت، `page_meta`، اسلات‌های تصویر، شبکه‌های اجتماعی |
| `i18n` | هر تغییر رشته‌ی رابط / زبان‌ها |
| `categories`, `category:<slug>` | تغییر دسته (و **همچنین** `products` و `sitemap`) |
| `products`, `product:<slug>` | تغییر محصول/مشخصات/مدل‌ها/تصاویر/اسناد/تگ‌ها (و `sitemap`، `search`) |
| `brands`, `tags` | |
| `projects`, `project:<slug>`, `project-sectors` | |
| `articles`, `article:<slug>`, `article-categories` | |
| `services`, `faq`, `company` | |
| `sitemap` | انتشار/لغو انتشار/تغییر slug هر موجودیت |
| `search` | هر تغییر روی موجودیت‌های قابل‌جستجو |
| `*` | دکمه‌ی دستی «پاک‌کردن کش فرانت» در پنل ادمین |

- تغییر `slug` ⇒ تگ‌های **slug قدیم و جدید** هر دو.
- ثبت نتیجه‌ی آخرین تلاش (وضعیت HTTP/زمان) برای نمایش در پنل.

---

### 6.16 موارد P2 (بعد از P0/P1؛ فقط اگر زمان بود)

| مورد | شرح |
|---|---|
| **ریدایرکت slug** | جدول `slug_history(entity_type, old_slug, entity_id)`؛ `GET /api/public/redirects?type=product&slug=<old>` ⇒ `{"redirect_to": "<new-slug>"}` یا 404؛ فرانت ریدایرکت 301 می‌زند. |
| **پیش‌نمایش پیش‌نویس** | پارامتر `preview=<token>` (توکن امضاشده‌ی کوتاه‌عمر که ادمین از پنل می‌گیرد) روی `GET /products/<slug>` و بقیه‌ی جزئیات‌ها، محتوای draft را برمی‌گرداند (بدون کش). |
| **منوی قابل‌ویرایش** | `GET /navigation` ⇒ منوهای هدر/فوتر (لیبل i18n، `href`، فرزندان، ترتیب، نمایش/عدم‌نمایش). فعلاً منو در کد ثابت و دسته‌ها پویاست. |
| **ردیابی بازدید فرانت** | ردیاب فعلی فقط درخواست‌های Flask را می‌بیند؛ بازدید واقعی صفحات Next دیده نمی‌شود. اگر داشبورد آمار لازم است: `POST /api/public/track` (path, referrer, locale + شناسه‌ی بازدیدکننده که فرانت کوکی خودش را می‌فرستد) یا استفاده از تحلیل خارجی (`ga4/gtm` در 6.1). **تصمیم مالک؛ پیش‌فرض: فقط GA/GTM.** |
| **حالت تعمیر** | `site.maintenance = {enabled, message}` ⇒ فرانت صفحه‌ی تعمیر نشان می‌دهد. |
| **کلیدهای ویژگی** | `site.features = {inquiry_form, search, news, projects, services, faq}` برای پنهان‌کردن بخش‌ها. |
| **کاتالوگ سازمانی در ادمین** | تنظیمی که `price/old_price/stock` را از فرم محصول پنهان می‌کند. |
| **کپچا** | `captcha_token` برای `POST /inquiries`. |
| **GET /services/<slug>** | اگر صفحه‌ی جزئیات خدمت اضافه شد. |

---

## 7. الزامات پنل ادمین (مشترک)

برای **همه‌ی** موجودیت‌های بخش 6 (پنل Jinja با همان سبک/RTL/i18n موجود؛ کاشی در `/dashboard` از `admin_entry`):

1. **لیست:** جست‌وجو (نام/slug)، فیلتر (وضعیت، دسته/بخش/…)، مرتب‌سازی، **صفحه‌بندی** (نه سقف ثابت)، شمارنده، وضعیت (پیش‌نویس/منتشرشده/زمان‌بندی‌شده).
2. **فرم ایجاد/ویرایش:**
   - **تب زبان** برای هر فیلد ترجمه‌پذیر؛ `fa` الزامی؛ نشانگر «ترجمه‌ی ناقص» (چه زبانی خالی است).
   - **slug خودکار** با پیش‌نمایش، اعتبارسنجی یکتایی همان‌جا، پیام خطای روشن.
   - **انتخابگر رسانه** برای تصاویر (6.14)، پیش‌نمایش تصویر، alt هر زبان.
   - **repeater** برای مشخصات/مدل‌ها/اسناد/بخش‌ها/متریک‌ها/گالری با افزودن، حذف، **جابه‌جایی** (drag یا بالا/پایین).
   - شمارنده‌ی کاراکتر برای `meta_title` (≈60) و `meta_description` (≈160)، پیش‌نمایش snippet گوگل (اختیاری ولی مطلوب).
   - دکمه‌ی «مشاهده در سایت» (URL = `site.site_url` + مسیر) و «ذخیره و ادامه»/«ذخیره و بستن».
3. **حذف:** با تأیید؛ برای موجودیت‌های دارای وابسته (دسته با محصول، برند با محصول، بخش پروژه با پروژه) یا ممنوع با پیام یا انتقال/جداسازی صریح.
4. **ایمنی داده:** قواعد 7 و 8 بخش 2 (پیام صادق، فیلد غایب = دست‌نخورده). تغییرات چندجدولی (محصول + مشخصات + تصاویر) **در یک تراکنش**.
5. **اعتبارسنجی سمت سرور** برای همه‌ی فیلدها (طول، نوع، hex، URL، enum)؛ خطاها کنار هر فیلد.
6. بعد از هر نوشتن موفق: ابطال کش داخلی (بخش 9) + رویداد revalidate (6.15).
7. کاشی‌های داشبورد جدید: تنظیمات سایت، برندها، پروژه‌ها، مقالات، خدمات، سوالات متداول، درباره‌ی شرکت، استعلام‌ها (با شمارنده‌ی «جدید»).

---

## 8. امنیت و سخت‌سازی

### ⚠️ تغییر رفتار موجود (دو مورد؛ همان‌ها که قاعده‌ی «بدون شکستن» را نقض می‌کنند)
1. **احراز هویت مسیرهای باز ادمین:** `@admin_required` برای تمام `/admin/products*`, `/admin/categories*`, `/admin/images*`, `/admin/cache*` و `POST /api/cache/clear/<ns>`, `GET /api/cache/stats` (طبق جدول بخش 3 `backend-doc.md` الان بدون هیچ چک هستند). دلیل: محتوای اصلی سایت حالا از اینجا می‌آید. بدون session ⇒ همان رفتار فعلی ادمین (302 به `/login`). مصرف‌کنندگان بدون-session این مسیرها باید قبل از اعمال شناسایی شوند (در سند نهایی گزارش دهید).
   - مسیر `GET /assets/uploads/*` و همه‌ی `GET /api/products*`, `/api/categories*`, `/api/i18n/*`, `/api/public/*` **عمومی می‌مانند**.
2. **آپلود:** مسیرهای **جدید** (اسناد، تصاویر داخل فرم‌های جدید) فهرست‌سفید پسوند + سقف حجم دارند (6.4.6). کتابخانه‌ی رسانه‌ی فعلی `/admin/images/upload` دست‌نخورده می‌ماند (ویرایشگر متنی تم‌ها به آن وابسته است) — فقط بعد از بند 1 ادمین‌-فقط می‌شود.

### سایر موارد
- **پارامترهای ورودی** همه‌ی endpointهای جدید با اعتبارسنجی نوع/محدوده (صفر 500).
- **SQL injection:** فقط query پارامتری؛ جستجوی LIKE با escape.
- **Open redirect:** `back`/`next` در پنل‌های **جدید** فقط مسیر داخلی (`/…` بدون `//`). (اصلاح موارد قدیمی اختیاری.)
- **اندازه‌ی بدنه:** POST عمومی ≤64KB؛ آپلود ادمین طبق سقف‌ها.
- **هیچ داده‌ی داخلی** در `/api/public/*` (ایمیل/آی‌پی استعلام، یادداشت داخلی، `sha256`، مسیر فایل روی دیسک، پیش‌نویس‌ها).
- **CORS** محدود (3.8). **Rate limit** استعلام (6.10).
- **Secrets** فقط `.env`؛ هرگز در پاسخ/لاگ.
- **SVG:** CSP sandbox (6.14).
- **ردیابی:** `/api/public/*` از ثبت خارج شود (3.1).

---

## 9. کش و کارایی

- `PluginCache` فعلی **درون‌پردازه‌ای** است و بین workerها مشترک نیست. برای `/api/public/*`: یا TTL کوتاه (≤30 ثانیه)، یا بدون کش بک‌اند وقتی کوئری ارزان است، یا کش مشترک (Redis) اگر چند worker دارید. در سند نهایی بنویسید چه کردید. مبنا: revalidate سمت فرانت فوری است؛ کش کهنه‌ی بک‌اند آن را بی‌اثر می‌کند.
- **ابطال کش:** هر نوشتن روی هر جدول مرتبط (حتی جداول فرزند و M2M و تغییر دسته) کش مربوط را پاک کند.
- **N+1 ممنوع:** لیست محصولات/پروژه/مقاله را با چند کوئری دسته‌ای (IN) بسازید (ترجمه‌ها، تگ‌ها، تصاویر کاور، دسته، برند).
- **ایندکس‌ها:** `slug` یکتا در هر جدول؛ `(status, published_at)`؛ `(category_id, status)`؛ `(is_featured, sort_order)`؛ `model_code`؛ `(entity_type, entity_id, field, lang_code)` یکتا در ترجمه‌ها؛ `search_text` (FULLTEXT اختیاری).
- `GET /products` با `per_page=100` و ترجمه‌ها باید زیر چند صد میلی‌ثانیه روی داده‌ی نمونه جواب دهد.
- فشرده‌سازی gzip را reverse proxy انجام می‌دهد (لازم نیست در Flask).

---

## 10. اولویت‌بندی و فازها

| فاز | محتوا | چرا |
|---|---|---|
| **P0** | زیرساخت مشترک (blueprint `/api/public`، خطاهای JSON، CORS، ETag، URL مطلق، `/health`) · 6.1 تنظیمات سایت · 6.13 i18n (import + افزودنی‌ها) · 6.3 دسته‌ها · 6.2 برندها · 6.4 محصولات (کامل: تگ/مشخصات/مدل‌ها/تصاویر/**اسناد و دانلود**/فیلتر/facets) · 6.14 رسانه · بند ⚠️ 1 و 2 بخش 8 | بدون این‌ها هدر/فوتر/متا/کاتالوگ داینامیک نمی‌شود |
| **P1** | 6.5 پروژه‌ها · 6.6 مقالات · 6.7 خدمات · 6.8 FAQ · 6.9 شرکت · 6.10 استعلام‌ها · 6.11 جستجو · 6.12 `home` و `sitemap` · 6.15 revalidate · سند نهایی | بقیه‌ی صفحات |
| **P2** | 6.16 | بهبودها |

**ترتیب پیشنهادی داخل P0:** زیرساخت ← i18n (چون همه به مدل ترجمه وابسته‌اند) ← site_settings ← categories ← brands ← products. اگر کار در چند مرحله تحویل می‌شود، سند نهایی را بعد از هر فاز به‌روز کنید و بخش‌های انجام‌نشده را با «⏳ پیاده‌سازی نشده» علامت بزنید.

**seed دمو (الزامی، idempotent):** اسکریپتی که حداقل داده‌ی نمونه بسازد تا فرانت تست شود: تنظیمات سایت پیش‌فرض، 2 دسته (یکی با فرزند)، 1 برند، 3 تگ، 3 محصول (یکی کامل با 5 مشخصه، 2 مدل، 2 سند با فایل PDF نمونه‌ی فارسی و انگلیسی، 3 تصویر)، 5 بخش پروژه، 2 پروژه، 4 موضوع مقاله، 3 مقاله (با بخش‌ها)، 2 خدمت + 5 مرحله، 4 FAQ، آمار/گاه‌شمار/تیم/گواهی/صنعت/نظر/دفتر، چند استعلام نمونه. (محتوای کامل فعلی فرانت جداگانه در صورت لزوم توسط مالک export می‌شود؛ این seed فقط برای تست است.)

---

## 11. معیار پذیرش و تست

**Definition of Done**
1. همه‌ی endpointهای بخش 5.1 با **شکل دقیق** این سند پاسخ می‌دهند (کلیدها، نوع‌ها، `null` در برابر خالی، I18n با `fa`).
2. همه‌ی خطاها JSON با کد ماشینی (حتی 404/405/500 پیش‌فرض زیر `/api/public/`). هیچ ورودی نامعتبری 500 نمی‌دهد (حداقل: `page=abc`, `per_page=-1`, `sort=zzz`, JSON خراب، slug با کاراکتر عجیب).
3. هیچ داده‌ی پیش‌نویس/غیرفعال/زمان‌بندی‌نشده/داخلی در پاسخ‌ها نیست.
4. URL رسانه‌ها مطلق‌اند.
5. هر پنل ادمین: ایجاد، ویرایش، حذف، ترتیب‌دهی، اعتبارسنجی، پیام صادق (دستی تست شود).
6. **رگرسیون:** `GET /api/products`, `/api/products/<id>`, `/api/categories`, `/api/categories/<slug>`, `/api/i18n/languages`, `/api/i18n/translate/<code>` (بدون پارامتر جدید)، صفحه‌ی `/`، `/product/<slug>`، قالب‌ساز و پنل‌های فعلی دقیقاً مثل قبل (به‌جز بند ⚠️).
7. Migration دوبار اجرا ⇒ بدون خطا و بدون تکرار؛ داده‌ی قبلی محصولات/دسته‌ها حفظ و در `fa` موجود.
8. آپلود سند: پسوند ممنوع رد، حجم بیش از سقف رد، PDF جعلی (محتوا ≠ `%PDF-`) رد، دانلود با نام فارسی درست، `download_count` افزایش.
9. استعلام: اعتبارسنجی هر فیلد، honeypot، rate limit (429)، شماره‌ی رهگیری ترتیبی بدون برخورد در 50 ثبت هم‌زمان.
10. جستجو: `ي/ی`، `ك/ک`، ارقام فارسی/لاتین (`۹۴۰` = `940`)، کد مدل دقیق.
11. revalidate: با URL نمونه (مثلاً سرور محلی) رویداد را ارسال و گزارش می‌کند؛ شکست آن پاسخ ادمین را نمی‌شکند.
12. **سند نهایی (بخش 12)** تحویل شده و نمونه‌پاسخ‌های آن از اجرای واقعی است.

**اسکریپت smoke:** `scripts/smoke_public_api.py` (یا معادل): با seed دمو همه‌ی endpointها را صدا بزند و شکل را بررسی کند (کلیدهای الزامی، نوع، `fa` در I18n، URL مطلق) و کد خروج غیرصفر در خطا بدهد. دستورهای curl نمونه را در سند نهایی بیاورید.

---

## 12. خروجی نهایی: سند API برای فرانت

پس از اتمام، فایل **`docs/frontend-api.md`** را (فارسی، مثل `backend-doc.md`) تولید کنید. این سند را مالک مستقیماً به agent فرانت می‌دهد، که فقط بر اساس آن فرانت را وصل می‌کند و **به این سند شرح کار یا کد بک‌اند دسترسی ندارد**. پس باید مستقل و دقیق باشد. ساختار الزامی:

1. **راه‌اندازی:** آدرس پایه‌ی توسعه/تولید، متغیرهای محیطی لازم در **فرانت** (`API_BASE_URL` سمت سرور، `NEXT_PUBLIC_API_BASE_URL` سمت مرورگر، `REVALIDATE_SECRET`)، تنظیم CORS، دامنه‌ی تصاویر برای `next.config` (`images.remotePatterns`)، نیاز به forward هدرهای IP برای فرم تماس.
2. **قراردادهای مشترک:** انواع (`I18nText`, `I18nList`, `Media`, `Seo`, کارت‌ها)، قالب خطا و کدها، صفحه‌بندی، ISO، `null` در برابر خالی، سیاست کش/ETag.
3. **مرجع endpointها:** برای هر endpoint — مسیر، متد، پارامترها (نوع، پیش‌فرض، سقف)، **نمونه‌ی درخواست curl**، **نمونه‌ی پاسخ واقعی** (از اجرای سرور، نه ساختگی)، خطاهای ممکن، تگ‌های revalidate مرتبط، نکته‌ها.
4. **جدول نگاشت نوع‌های فرانت ← فیلد API:** برای هر نوع در پیوست الف (Product, ProductCategory, Project, Article, Service, ServiceStep, FaqItem, CompanyStat, TimelineEvent, TeamMember, Certification, IndustryItem, Testimonial, ContactOffice, ContactInquiryPayload, UnifiedSearchResults) یک ستون «فیلد فرانت» و ستون «فیلد API»، به‌همراه هر تفاوت (مثل `categorySlug` ⇒ `category.slug`، `coverImage` ⇒ `cover.url`، `iconName` ⇒ `icon`، `tags` از `{fa[],en[]}` ⇒ `[{slug,label}]`، `documents[].fileSize/format` ⇒ `files[lang]`، `clientSector` ⇒ `client`، `publishedAt` ⇒ `published_at`، …).
5. **جدول نگاشت صفحه‌ها ← endpointها** (مثل بخش 4 این سند، ولی با شکل نهایی).
6. **تگ‌های revalidate** (جدول کامل و فرمت درخواست webhook، تا فرانت route دریافت‌کننده را بسازد).
7. **رشته‌های رابط:** وضعیت import (چند کلید برای هر زبان)، پیشوند `web.`، نحوه‌ی فراخوانی `translate` با `prefix/strip_prefix/fallback`.
8. **راهنمای پنل ادمین** برای مالک: هر چیز را کجا ویرایش کنم (نقشه‌ی «چه چیزی ← کدام صفحه‌ی ادمین»).
9. **انحراف‌ها و فرض‌ها:** هر جایی که از این سند عدول کردید (و دلیلش)؛ هر ویژگی P2 که انجام نشد؛ تصمیم‌های کش، سهمیه‌ی اسناد، facets (کامل/ساده)، SMTP.
10. **محدودیت‌ها و اشکال‌های شناخته‌شده**، وضعیت داده‌ی seed (چه چیزی نمونه است و چه چیزی واقعی).
11. **چک‌لیست یکپارچه‌سازی فرانت:** ترتیب پیشنهادی وصل‌کردن (layout/site ← دسته‌ها ← محصولات ← …).
12. **Changelog** و تاریخ.

---

## پیوست الف: انواع داده‌ی فرانت (مرجع)

(از `src/types/index.ts` فرانت؛ برای ساخت جدول نگاشت بخش 12 بند 4. `BilingualText = {fa, en}` و `BilingualList = {fa: string[], en: string[]}` معادل `I18nText/I18nList` این سند هستند.)

```ts
Product { id, slug, modelCode, categorySlug, name, subtitle, shortDescription, description: Bilingual;
          images: string[]; featured: boolean; isNew?: boolean; tags: BilingualList; features: BilingualList;
          specifications: {label, value: Bilingual}[];
          variants: {modelCode: string; name, configuration, operatingRange, application: Bilingual}[];
          documents: {id, title: Bilingual, type: "datasheet"|"manual"|"certificate"|"cad", format: string, fileSize: string, revision: string}[];
          certifications: string[] }
ProductCategory { id, slug, name, shortDescription, description: Bilingual, coverImage: string,
                  iconName: "Gauge"|"Cpu"|"Activity"|"Zap", standards: string[], keyHighlights: BilingualList }
Service { id, slug, iconName: "Settings"|"ShieldCheck"|"Compass"|"Cpu"|"Wrench"|"Award", title, shortDescription, description: Bilingual,
          deliverables: BilingualList, industries: BilingualList }
ServiceStep { stepNumber: string, title, description: Bilingual }
Project { id, slug, title: Bilingual, category: "energy"|"water"|"petrochemical"|"pharma"|"manufacturing", categoryLabel: Bilingual,
          clientSector, location: Bilingual, completionYear: string, coverImage: string, gallery: string[],
          shortDescription, challenge, solution: Bilingual, impactMetrics: {label,value}[], specifications: {label,value}[],
          relatedProductSlugs: string[] }
Article { id, slug, title, excerpt: Bilingual, category: "engineering"|"innovation"|"standards"|"corporate", categoryLabel: Bilingual,
          publishedAt: string(ISO), readingTimeMinutes: number, author: {name, role: Bilingual}, coverImage: string, featured: boolean,
          sections: {id: string, heading: Bilingual, paragraphs: BilingualList}[] }
Testimonial { id, quote, authorName, authorRole, organization, sector: Bilingual }
TimelineEvent { year: string, title, description: Bilingual }
TeamMember { id, name, role, qualification, bio: Bilingual }
Certification { code: string, title, issuer, description: Bilingual }
IndustryItem { id, iconName: "Flame"|"Droplets"|"Factory"|"FlaskConical"|"Zap"|"Cpu", title, description: Bilingual }
CompanyStat { id, numericValue: number, suffix, label, sublabel: Bilingual }
FaqItem { id, category: "engineering"|"documentation"|"support"|"corporate", categoryLabel, question, answer: Bilingual }
ContactOffice { id, title, address: Bilingual, phone: string, email: string, hours: Bilingual, coordinatesLabel: string }
ContactInquiryPayload { fullName, email, phone, company?, subject, productCode?, message, locale: "fa"|"en" }
UnifiedSearchResults { query, products: Product[], projects: Project[], articles: Article[], pages: {slug, href, title, description: Bilingual}[], totalCount }
```
دو نکته: (۱) فرانت `id` را رشته‌ی دلخواه (`prod-1`) می‌داند ولی فقط برای `key` در React؛ عدد کافی است. (۲) `Project.clientSector` در UI زیر برچسب «بخش صنعتی کارفرما» نمایش داده می‌شود ولی مقدارش **نام سازمان کارفرماست**؛ در API نام `client` است.

---

## پیوست ب: اسلات‌های تصویر، آیکن‌ها و کلیدهای تنظیمات

### اسلات‌های تصویر ثابت (`site.media`) — همه‌ی کلیدها همیشه حاضر (مقدار `null` در نبود)
| کلید | کجا استفاده می‌شود | مقدار فعلی (هاردکد در فرانت) |
|---|---|---|
| `home.hero` | پس‌زمینه‌ی hero صفحه‌ی اصلی | `/images/hero-facility.jpg` |
| `home.intro` | تصویر معرفی شرکت | `/images/about-hq.jpg` |
| `home.capabilities` | تصویر «توانمندی‌ها» | `/images/lab-calibration.jpg` |
| `about.hq` | تصویر صفحه‌ی «درباره‌ی ما» | `/images/about-hq.jpg` |
| `product.placeholder` | تصویر جایگزین محصول بدون تصویر | `/images/prod-valve.jpg` |
| `og.products`, `og.projects`, `og.news`, `og.services`, `og.contact`, `og.about` | تصویر OG پیش‌فرض هر صفحه‌ی لیست (یا همان `page_meta[x].og_image`؛ اگر پیاده‌سازی `page_meta.og_image` کافی است این‌ها لازم نیست) | — |

(تصاویر کنونی فرانت: `public/images/{hero-facility, about-hq, lab-calibration, prod-valve, prod-sensor, prod-plc, prod-switchgear, prod-drive, project-energy, project-petro}.jpg`. این‌ها داده‌ی نمونه‌اند و در صورت نیاز مالک آپلود می‌کند.)

### فهرست آیکن‌های مجاز (نام lucide-react، فرانت از همین‌ها نگاشت می‌کند)
- دسته‌ها: `Gauge, Cpu, Activity, Zap`
- خدمات: `Settings, ShieldCheck, Compass, Cpu, Wrench, Award`
- صنایع: `Flame, Droplets, Factory, FlaskConical, Zap, Cpu`
در فرم ادمین dropdown با همین فهرست (قابل‌گسترش با یک ثابت در کد). نام ناشناخته ⇒ رد؛ فرانت هم برای نام ناشناخته آیکن پیش‌فرض دارد.

### کلیدهای ثابت `page_meta`
`home, about, products, services, projects, news, contact, faq, search`

### نشان‌های (پلتفرم) شبکه‌های اجتماعی
`linkedin, instagram, telegram, whatsapp, youtube, twitter, facebook, aparat, eitaa, bale, rubika, github`

---

## پیوست ج: متغیرهای محیطی جدید

(نام‌ها پیشنهادی‌اند؛ در سند نهایی نام نهایی و پیش‌فرض را بنویسید. **مقادیر واقعی را هرگز ثبت نکنید.**)

| متغیر | پیش‌فرض | کاربرد |
|---|---|---|
| `PUBLIC_BASE_URL` | از `request.host_url` | ساخت URL مطلق رسانه/دانلود |
| `CORS_ALLOWED_ORIGINS` | خالی (غیرفعال) | origin‌های فرانت، با ویرگول |
| `FRONTEND_REVALIDATE_URL` | خالی (غیرفعال) | مقصد webhook |
| `FRONTEND_REVALIDATE_SECRET` | خالی | هدر `X-Revalidate-Secret` |
| `DOCUMENT_ALLOWED_EXTENSIONS` | فهرست 6.4.6 | پسوندهای مجاز اسناد |
| `DOCUMENT_MAX_SIZE_MB` | `50` | سقف هر فایل سند |
| `DOCUMENT_STORAGE_DIR` | `storage/documents` | مسیر ذخیره (خارج از `uploads/`) |
| `INQUIRY_RATE_PER_HOUR` / `INQUIRY_RATE_PER_DAY` | `5` / `20` | محدودیت استعلام به‌ازای IP |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | خالی (غیرفعال) | اعلان ایمیلی استعلام |
| `PUBLIC_API_CACHE_TTL` | `30` | TTL کش درون‌پردازه‌ای `/api/public/*` (ثانیه؛ `0` = بدون کش) |
