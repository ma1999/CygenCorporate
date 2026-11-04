# API بک‌اند برای فرانت (Next.js) — `docs/frontend-api.md`

> **مخاطب:** agent / توسعه‌دهنده‌ی فرانت. این سند **مستقل** است؛ برای وصل‌کردن فرانت به چیز دیگری نیاز ندارید.
> **مبنا:** همه‌ی نمونه‌پاسخ‌ها خروجی **واقعی** سرور (Flask + MySQL) روی داده‌ی نمونه‌ی `scripts/seed_demo.py` هستند (برای خوانایی کوتاه شده‌اند؛ هر جا کوتاه شده با `…` مشخص است).
> **تاریخ:** 1 نوامبر 2026 · **نسخه‌ی سند:** 1.1 (شامل همه‌ی قابلیت‌های P0/P1 و P2)

---

## فهرست
1. [راه‌اندازی](#1-راهاندازی) · 2. [قراردادهای مشترک](#2-قراردادهای-مشترک) · 3. [مرجع endpointها](#3-مرجع-endpointها) · 4. [نگاشت نوع‌های فرانت ← API](#4-نگاشت-نوعهای-فرانت--فیلد-api) · 5. [نگاشت صفحه‌ها](#5-نگاشت-صفحهها--endpointها) · 6. [Revalidate](#6-revalidate-به‌روزرسانی-فوری-فرانت) · 7. [رشته‌های رابط](#7-رشتههای-رابط-i18n) · 8. [راهنمای پنل ادمین](#8-راهنمای-پنل-ادمین) · 9. [انحراف‌ها و فرض‌ها](#9-انحرافها-و-فرضها) · 10. [محدودیت‌ها](#10-محدودیتها-و-اشکالهای-شناختهشده-وضعیت-seed) · 11. [چک‌لیست یکپارچه‌سازی](#11-چکلیست-یکپارچهسازی-فرانت) · 12. [Changelog](#12-changelog)

---

## 1. راه‌اندازی

### 1.1 آدرس‌ها
| محیط | آدرس پایه‌ی API |
|---|---|
| توسعه | `http://127.0.0.1:5000/api/public` (اجرا: `python main.py`) |
| تولید | `https://<دامنه‌ی-بک‌اند>/api/public` |

همه‌ی endpointها بدون احراز هویت و بدون کوکی‌اند (به‌جز پنل ادمین که به فرانت مربوط نیست). نیازی به پیشوند زبان یا کوکی نیست؛ **زبان فقط «داده» است** (بخش 2.1).

### 1.2 متغیرهای محیطی لازم در **فرانت**
| متغیر | مقدار | کاربرد |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:5000/api/public` | fetch سمت **سرور** (SSR/SSG/route handler) |
| `NEXT_PUBLIC_API_BASE_URL` | آدرس عمومی همان API | fetch سمت **مرورگر** (فرم تماس، جستجوی زنده) |
| `REVALIDATE_SECRET` | همان مقدار `FRONTEND_REVALIDATE_SECRET` بک‌اند | اعتبارسنجی webhook (بخش 6) |

### 1.3 متغیرهای محیطی لازم در **بک‌اند** (`.env`؛ نمونه: `.env.example`)
`PUBLIC_BASE_URL` (مبدأ URLهای مطلق رسانه؛ خالی = از درخواست)، `CORS_ALLOWED_ORIGINS` (origin فرانت‌ها با ویرگول؛ **خالی = CORS خاموش**)، `FRONTEND_REVALIDATE_URL` + `FRONTEND_REVALIDATE_SECRET` (webhook)، `PUBLIC_API_CACHE_TTL` (پیش‌فرض 30)، `DOCUMENT_ALLOWED_EXTENSIONS`، `DOCUMENT_MAX_SIZE_MB` (50)، `DOCUMENT_STORAGE_DIR`، `INQUIRY_RATE_PER_HOUR` (5) / `INQUIRY_RATE_PER_DAY` (20)، `SMTP_*`، `DB_POOL_WAIT`.

### 1.4 CORS
فقط روی `/api/public/*`. `Access-Control-Allow-Origin` همان origin درخواست است (اگر در `CORS_ALLOWED_ORIGINS` باشد؛ هرگز `*`)، متدها `GET, POST, OPTIONS`، هدر `Content-Type`، **بدون credentials**. preflight با `204` پاسخ داده می‌شود. fetchهای سمت سرور CORS نمی‌خواهند.

### 1.5 تصاویر در `next.config`
همه‌ی URLهای رسانه **مطلق** و روی دامنه‌ی بک‌اند‌اند (`{PUBLIC_BASE_URL}/assets/uploads/...`):
```ts
images: { remotePatterns: [{ protocol: 'https', hostname: '<دامنه-بک‌اند>', pathname: '/assets/uploads/**' }] }
```
(در توسعه: `http` + `127.0.0.1` + `port: '5000'`.) لوگوی SVG با `next/image` باید `unoptimized` یا `dangerouslyAllowSVG` باشد؛ فایل‌های SVG با هدر CSP `sandbox` سرو می‌شوند.

### 1.6 فرم تماس و IP واقعی کاربر
rate limit بر اساس IP است: `X-Real-IP` ← `X-Forwarded-For` (اولین) ← `remote_addr`. اگر فرم را از **route handler سمت سرور** Next می‌فرستید، IP بازدیدکننده را در همین هدرها forward کنید؛ وگرنه همه‌ی کاربران یک IP (IP سرور فرانت) حساب می‌شوند و به سقف 5 درخواست/ساعت می‌خورند. اگر مستقیم از مرورگر (با CORS) می‌فرستید، چیزی لازم نیست.

---

## 2. قراردادهای مشترک

### 2.1 انواع
```ts
type I18nText = { fa: string; [lang: string]: string };          // fa همیشه هست ("" اگر خالی)؛ زبان‌های دیگر فقط وقتی غیرخالی‌اند
type I18nList = { fa: string[]; [lang: string]: string[] };      // fa همیشه آرایه (ممکن است [])
type Media = { url: string; alt: I18nText; width: number | null; height: number | null; mime: string | null } | null;
type Seo = { title: I18nText; description: I18nText; keywords: I18nText; og_image: Media; noindex: boolean };
type Meta = { total: number; page: number; per_page: number; total_pages: number };   // total_pages = 0 وقتی total = 0
```
- فرانت: `text[locale] ?? text.fa`. هیچ فیلد I18n هرگز `null` نیست. کلیدهای زبان = زبان‌های **فعال** (`site.languages.active`).
- `Seo` مقدار **مؤثر** است: بک‌اند fallback را ساخته (عنوان ← نام؛ توضیح ← توضیح کوتاه/کامل (≤200 نویسه)؛ `og_image` ← کاور). فرانت fallback نسازد.
- متن‌ها **متن ساده** (بدون HTML) هستند؛ پاراگراف‌ها در `description` با `\n` جدا می‌شوند و در `paragraphs` آرایه‌اند.

### 2.2 قالب JSON
کلیدها `snake_case`؛ boolean واقعی؛ عدد، عدد؛ زمان‌ها ISO-8601 UTC با `Z` (`2026-09-07T17:15:14Z`)؛ فیلد اختیاری بدون مقدار `null`؛ آرایه‌ی خالی `[]`؛ ترتیب آرایه‌ها معنادار و از `sort_order` پنل؛ `id` عددی؛ مسیرهای عمومی با **slug**. لیست‌ها: `{"<نام‌جمع>": [...], "meta": Meta}`.

### 2.3 خطاها
```json
{"ok": false, "error": "not_found", "message": "Product not found", "fields": {"email": {"code": "invalid_email"}}}
```
`error` کد ماشینی ثابت است: `not_found` (404) · `bad_request` (400 / 405 / 413) · `validation_failed` (422، با `fields`) · `rate_limited` (429، با `Retry-After`) · `unavailable` (503، خطای دیتابیس) · `server_error` (500). `message` انگلیسی و برای توسعه‌دهنده است؛ متن کاربر را از i18n خودتان بسازید. **همه‌ی خطاها (حتی 404/405/500 پیش‌فرض) زیر `/api/public/` JSON‌اند.** خطای DB هرگز «لیست خالی» نمی‌شود (503) تا صفحه‌ی خالی کش نشود.

نمونه‌ی واقعی 404، 503 و 422:
```json
// HTTP 404
{"ok": false, "error": "not_found", "message": "Product not found"}
```
```json
// HTTP 503
{"ok": false, "error": "unavailable", "message": "Database unavailable"}
```
```json
// HTTP 422
{
  "ok": false,
  "error": "validation_failed",
  "message": "Validation failed",
  "fields": {
    "full_name": {"code": "too_short", "min": 3},
    "email": {"code": "invalid_email"},
    "phone": {"code": "too_short", "min": 8},
    "subject": {"code": "too_short", "min": 4},
    "message": {"code": "too_short", "min": 15}
  }
}
```

### 2.4 پارامترهای ورودی
بک‌اند **clamp** می‌کند و خطا نمی‌دهد: `page<1 ⇒ 1`، `page=abc ⇒ 1`، `per_page` خارج از `1..100` ⇒ نزدیک‌ترین مقدار. پارامتر ناشناخته نادیده گرفته می‌شود. فقط مقدار نامعتبر **enum** (`sort`، `types`، `include`، `type`) ⇒ `400 bad_request`. بدنه‌ی POST حداکثر 64KB و باید JSON-object باشد.

### 2.5 کش
هر `GET` موفق: `ETag` + `If-None-Match ⇒ 304`؛ `Cache-Control: public, max-age=30, stale-while-revalidate=300`. خطاها `no-store`اند. `/health` هم `no-store` است. پاسخ‌ها در بک‌اند ≤30s (`PUBLIC_API_CACHE_TTL`) کش می‌شوند و **با هر تغییر محتوا فوراً پاک می‌شوند** (تک‌پردازه). اگر چند worker اجرا می‌کنید `PUBLIC_API_CACHE_TTL=0` بگذارید.

### 2.6 URLهای مطلق
هر URL تصویر/دانلود مطلق است. مبدأ: `PUBLIC_BASE_URL` یا (اگر خالی) `X-Forwarded-Proto`/`X-Forwarded-Host` یا خود درخواست. URL بیرونی (`https://…`) دست‌نخورده می‌ماند.

---

## 3. مرجع endpointها
پایه: `{API_BASE_URL}` = `/api/public`. «تگ‌ها» = تگ‌های revalidate مرتبط (بخش 6).

### فهرست کامل endpointها
| متد | مسیر | کاربرد | تگ revalidate |
|---|---|---|---|
| GET | `/health` | سلامت + DB (بدون کش) | — |
| GET | `/site` | هویت، برندینگ، رنگ، تماس، سئو، تحلیل، اسلات‌های تصویر، `page_meta`، زبان‌ها، **`maintenance`، `features`، `captcha`** | `site` |
| GET | `/navigation` | **منوی هدر/فوتر (قابل‌ویرایش)** | `navigation` |
| GET | `/categories` · `/categories/<slug>` | درخت دسته‌ها / جزئیات | `categories`, `category:<slug>` |
| GET | `/brands` · `/brands/<slug>` | برندها | `brands` |
| GET | `/tags` | تگ‌های محصول | `tags` |
| GET | `/products` · `/products/<slug>` | کاتالوگ (فیلتر/facets/جستجو) / جزئیات (+`?preview=`) | `products`, `product:<slug>` |
| GET | `/documents/<id>/download` | دانلود فایل سند (محصول/گواهینامه) | `products`, `company` |
| GET | `/projects` · `/projects/<slug>` · `/project-sectors` | پروژه‌ها (+`?preview=`) | `projects`, `project:<slug>`, `project-sectors` |
| GET | `/articles` · `/articles/<slug>` · `/article-categories` | اخبار/مقالات (+`?preview=`) | `articles`, `article:<slug>`, `article-categories` |
| GET | `/services` · **`/services/<slug>`** | خدمات + مراحل فرایند / جزئیات یک خدمت | `services`, `service:<slug>` |
| GET | `/faq` | پرسش‌های متداول | `faq` |
| GET | `/company` | آمار، گاه‌شمار، تیم، گواهینامه‌ها، صنایع، نظرات، دفاتر | `company` |
| POST | `/inquiries` | فرم تماس/استعلام (honeypot، rate limit، **کپچای اختیاری**) | — |
| POST | **`/track`** | **ثبت بازدید صفحه‌ی فرانت (اختیاری؛ پیش‌فرض خاموش)** | — |
| GET | `/search` | جستجوی یکپارچه | — |
| GET | `/home` | تجمیعی صفحه‌ی اصلی | `products`, `projects`, `articles`, `company`, `categories` |
| GET | `/sitemap` | همه‌ی slugهای منتشرشده (شامل `services`) | `sitemap` |
| GET | `/redirects` | slug قدیمی ← جدید (301) | — |
| GET | `/api/i18n/translate/<code>` | رشته‌های رابط (مسیر قدیمی، **خارج** از `/api/public`) | `i18n` |

### 3.1 `GET /health`
بدون کش. DB خراب ⇒ `503 {"ok": false, "db": false}`.
```bash
curl -s http://127.0.0.1:5000/api/public/health
```
```json
// HTTP 200
{"ok": true, "db": true, "version": "dev", "time": "2026-11-01T06:56:42Z"}
```

### 3.2 `GET /site` — تنظیمات سایت · تگ: `site`
هویت، برندینگ، رنگ‌ها، تماس، اجتماعی، سئو، تحلیل، **همه‌ی 11 اسلات تصویر** (`media`؛ اسلات خالی `null`، کلید همیشه هست)، **متای 9 صفحه‌ی ثابت** (`page_meta`: `home, about, products, services, projects, news, contact, faq, search`) و زبان‌ها. مقادیر داخلی استعلام (`inquiry_*`) هرگز.
```bash
curl -s http://127.0.0.1:5000/api/public/site
```
```json
// HTTP 200
{
  "site": {
    "name": {"fa": "آریا صنعت پویا", "en": "Arya Sanat Precision Dynamics"},
    "short_name": {"fa": "آریا صنعت"},
    "legal_name": {"fa": ""},
    "tagline": {"fa": "unreachable test", "en": "Precision engineering"},
    "logo_subtitle": {"fa": "ASPD ENGINEERING GROUP"},
    "alternate_name": null,
    "site_url": "https://example-frontend.test",
    "branding": {
      "logo_light": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
        "alt": {"fa": "لوگو", "en": "Logo"},
        "width": null,
        "height": null,
        "mime": "image/svg+xml"
      },
      "logo_dark": null,
      "logo_mark": null,
      "favicon": {
        "ico": null,
        "svg": null,
        "png_32": "http://127.0.0.1:5000/assets/uploads/generated/favicon-32.png",
        "png_192": "http://127.0.0.1:5000/assets/uploads/generated/favicon-192.png",
        "png_512": "http://127.0.0.1:5000/assets/uploads/generated/favicon-512.png",
        "apple_touch": "http://127.0.0.1:5000/assets/uploads/generated/apple-touch-180.png"
      },
      "og_default_image": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/hero.jpg",
        "alt": {"fa": "تصویر اشتراک"},
        "width": 1600,
        "height": 900,
        "mime": "image/jpeg"
      },
      "theme_color": "#0b4f8a"
    },
    "theme": {
      "primary": "#0b4f8a",
      "primary_hover": "#083d6b",
      "accent": "#c27803",
      "secondary": "#0f172a",
      "dark_surface": "#09111f"
    },
    "contact": {
      "phone": "+98 21 8865 4200",
      "phone_tel": "+982188654200",
      "email": "demo@example.com",
      "address": {"fa": "تهران، خیابان نمونه", "en": "Tehran, Sample St."},
      "working_hours": {"fa": "شنبه تا چهارشنبه ۸ تا ۱۷"},
      "map": {
        "lat": 35.7742,
        "lng": 51.4128,
        "embed_url": "https://www.google.com/maps/embed?pb=1",
        "label": {"fa": "دفتر مرکزی"}
      }
    },
    "address_structured": {"street": null, "city": null, "region": null, "postal_code": null, "country_code": "IR"},
    "social": [
      {
        "platform": "linkedin",
        "url": "https://linkedin.com/company/demo",
        "label": {"fa": ""}
      }
    ],
    "header_badges": ["ISO 9001:2015", "IEC 61508 SIL-3", "… (+1 more)"],
    "search_suggestions": {
      "fa": ["DEMO-AS-FCV-940", "کوریولیس"],
      "en": ["DEMO-AS-FCV-940", "Coriolis"]
    },
    "seo": {
      "default_title": {"fa": "آریا صنعت پویا | مهندسی تجهیزات دقیق"},
      "default_description": {"fa": "طراح و تولیدکننده تجهیزات کنترل سیالات و ابزار دقیق."},
      "default_keywords": {"fa": ""},
      "title_template": "{title} | {site_name}",
      "robots_index": true,
      "twitter_handle": null,
      "verification": {"google": null, "bing": null}
    },
    "analytics": {"ga4_id": "G-ABC12345", "gtm_id": null, "track": false},
    "maintenance": {"enabled": false, "message": {"fa": ""}},
    "features": {"inquiry_form": true, "search": true, "news": true, "projects": true, "services": true, "faq": true},
    "captcha": {"provider": null, "site_key": null},
    "media": {
      "home.hero": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/hero.jpg",
        "alt": {"fa": "کارخانه"},
        "width": 1600,
        "height": 900,
        "mime": "image/jpeg"
      },
      "home.intro": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/intro.jpg",
        "alt": {"fa": ""},
        "width": 1200,
        "height": 800,
        "mime": "image/jpeg"
      },
      "home.capabilities": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cap.jpg",
        "alt": {"fa": ""},
        "width": 1200,
        "height": 800,
        "mime": "image/jpeg"
      },
      "…": "8 more keys"
    },
    "page_meta": {
      "home": {
        "title": {"fa": "خانه | آریا صنعت پویا"},
        "description": {
          "fa": "طراح و تولیدکننده تجهیزات کنترل سیالات، ابزار دقیق، سامانه‌های اتوماسیون اسکادا و تابلوهای هوشمند صنعتی مطابق با استانداردهای بین‌المللی."
        },
        "keywords": {"fa": ""},
        "og_image": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/hero.jpg",
          "alt": {"fa": "تصویر اشتراک"},
          "width": 1600,
          "height": 900,
          "mime": "image/jpeg"
        },
        "noindex": false
      },
      "about": {
        "title": {"fa": "درباره ما | آریا صنعت پویا"},
        "description": {
          "fa": "آشنایی با بیش از ربع قرن تجربه مهندسی، آزمایشگاه‌های کالیبراسیون ISO 17025 و زیرساخت‌های تولید دقیق آریا صنعت پویا."
        },
        "keywords": {"fa": ""},
        "og_image": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/hero.jpg",
          "alt": {"fa": "تصویر اشتراک"},
          "width": 1600,
          "height": 900,
          "mime": "image/jpeg"
        },
        "noindex": false
      },
      "products": {
        "title": {"fa": "کاتالوگ محصولات و تجهیزات صنعتی | آریا صنعت پویا"},
        "description": {
          "fa": "بررسی مشخصات فنی، مدل‌ها و مستندات مهندسی شیرآلات کنترلی، ترانسمیترهای ابزار دقیق، کنترلرهای PLC و تابلوهای هوشمند صنعتی."
        },
        "keywords": {"fa": ""},
        "og_image": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/hero.jpg",
          "alt": {"fa": "تصویر اشتراک"},
          "width": 1600,
          "height": 900,
          "mime": "image/jpeg"
        },
        "noindex": false
      },
      "…": "6 more keys"
    },
    "languages": {
      "default": "fa",
      "active": [
        {"code": "fa", "name": "Persian", "native_name": "فارسی", "direction": "rtl", "flag": "🇮🇷"},
        {"code": "en", "name": "English", "native_name": "English", "direction": "ltr", "flag": "🇬🇧"}
      ]
    }
  },
  "updated_at": "2026-11-01T06:56:40Z"
}
```
**فیلدهای کنترلی (همیشه حاضر):**
- `site.maintenance = {enabled: boolean, message: I18nText}` — اگر `enabled` بود فرانت **صفحه‌ی تعمیر** با `message` نشان بدهد (خود API در حالت تعمیر هم کار می‌کند؛ فقط فرانت تصمیم می‌گیرد).
- `site.features = {inquiry_form, search, news, projects, services, faq}` (همه boolean، پیش‌فرض `true`) — `false` ⇒ بخش را از منو/صفحه‌ی اصلی/sitemap فرانت پنهان و صفحه را 404 کنید.
- `site.captcha = {provider: "turnstile"|"hcaptcha"|null, site_key: string|null}` — اگر `provider` غیر `null` بود ویجت را با `site_key` رندر کنید و توکن را در `captcha_token` بفرستید (بخش 3.14). سکرت هرگز بیرون نمی‌آید.
- `site.analytics = {ga4_id, gtm_id, track}` — `track=true` یعنی مالک ثبت بازدید سرور را روشن کرده (بخش 3.20).

نکته‌ها: `site_url` فقط بعد از ذخیره در پنل مقدار دارد (`null` = تنظیم نشده)؛ `favicon.png_*` از `favicon_png` ≥512px ساخته می‌شود؛ `languages.active` همیشه `fa` را دارد؛ `page_meta[x].title/description` اگر در پنل خالی باشد از رشته‌های ورودی‌شده‌ی `web.seo.*` و سپس `seo.default_*` پر می‌شود.

### 3.3 `GET /categories` و `GET /categories/<slug>` · تگ: `categories`, `category:<slug>`
`include_empty=0|1` (پیش‌فرض 1). درخت: ریشه‌ها با `children`. `product_count` = محصولات **منتشرشده** در دسته و فرزندان مستقیمش. ریشه‌ی غیرفعال ⇒ فرزندانش هم پنهان. مرتب بر اساس `sort_order, id`.
```bash
curl -s "http://127.0.0.1:5000/api/public/categories?include_empty=0"
curl -s "http://127.0.0.1:5000/api/public/categories/demo-control-valves"
```
```json
// HTTP 200
{
  "categories": [
    {
      "id": 19,
      "slug": "demo-flow-control",
      "parent_slug": null,
      "name": {"fa": "کنترل سیالات", "en": "Flow Control"},
      "short_description": {"fa": "شیرآلات و تجهیزات کنترل جریان", "en": "Valves and flow-control equipment"},
      "icon": "Gauge",
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cat1.jpg",
        "alt": {"fa": "کنترل سیالات", "en": "Flow control"},
        "width": 1000,
        "height": 600,
        "mime": "image/jpeg"
      },
      "standards": ["IEC 60534", "ASME B16.34"],
      "product_count": 3,
      "sort_order": 1,
      "children": [
        {
          "id": 20,
          "slug": "demo-control-valves",
          "parent_slug": "demo-flow-control",
          "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"},
          "short_description": {"fa": "شیرهای کنترل پنوماتیک", "en": "Pneumatic control valves"},
          "icon": "Cpu",
          "cover": {
            "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cat2.jpg",
            "alt": {"fa": ""},
            "width": 1000,
            "height": 600,
            "mime": "image/jpeg"
          },
          "standards": ["IEC 60534"],
          "product_count": 1,
          "sort_order": 1
        }
      ]
    }
  ]
}
```
```json
// HTTP 200
{
  "category": {
    "id": 20,
    "slug": "demo-control-valves",
    "parent_slug": "demo-flow-control",
    "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"},
    "short_description": {"fa": "شیرهای کنترل پنوماتیک", "en": "Pneumatic control valves"},
    "icon": "Cpu",
    "cover": {
      "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cat2.jpg",
      "alt": {"fa": ""},
      "width": 1000,
      "height": 600,
      "mime": "image/jpeg"
    },
    "standards": ["IEC 60534"],
    "product_count": 1,
    "sort_order": 1,
    "description": {"fa": ""},
    "key_highlights": {"fa": []},
    "parent": {
      "slug": "demo-flow-control",
      "name": {"fa": "کنترل سیالات", "en": "Flow Control"}
    },
    "children": [],
    "seo": {
      "title": {"fa": "شیرآلات کنترلی", "en": "Control Valves"},
      "description": {"fa": "شیرهای کنترل پنوماتیک", "en": "Pneumatic control valves"},
      "keywords": {"fa": ""},
      "og_image": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cat2.jpg",
        "alt": {"fa": ""},
        "width": 1000,
        "height": 600,
        "mime": "image/jpeg"
      },
      "noindex": false
    },
    "updated_at": "2026-11-01T06:54:51Z"
  }
}
```

### 3.4 `GET /brands` و `GET /brands/<slug>` · تگ: `brands`
`page`, `per_page` (پیش‌فرض 50). فقط فعال.
```json
// HTTP 200
{
  "brands": [
    {
      "id": 3,
      "slug": "demo-aspd",
      "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
      "description": {"fa": "برند نمونه", "en": "Sample brand"},
      "logo": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
        "alt": {"fa": "لوگو", "en": "Logo"},
        "width": null,
        "height": null,
        "mime": "image/svg+xml"
      },
      "website_url": "https://example.com",
      "product_count": 2
    }
  ],
  "meta": {"total": 1, "page": 1, "per_page": 50, "total_pages": 1}
}
```
```json
// HTTP 200
{
  "brand": {
    "id": 3,
    "slug": "demo-aspd",
    "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
    "description": {"fa": "برند نمونه", "en": "Sample brand"},
    "logo": {
      "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
      "alt": {"fa": "لوگو", "en": "Logo"},
      "width": null,
      "height": null,
      "mime": "image/svg+xml"
    },
    "website_url": "https://example.com",
    "product_count": 2,
    "seo": {
      "title": {"fa": "آریا صنعت", "en": "Arya Sanat"},
      "description": {"fa": "برند نمونه", "en": "Sample brand"},
      "keywords": {"fa": ""},
      "og_image": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
        "alt": {"fa": "لوگو", "en": "Logo"},
        "width": null,
        "height": null,
        "mime": "image/svg+xml"
      },
      "noindex": false
    }
  }
}
```

### 3.5 `GET /tags?category=<slug>` · تگ: `tags`
فقط تگ‌هایی که حداقل یک محصول منتشرشده دارند (با `category`: در همان دسته و فرزندانش).
```json
// HTTP 200
{
  "tags": [
    {
      "slug": "sil-3",
      "label": {"fa": "SIL-3", "en": "SIL-3"},
      "product_count": 1
    },
    {
      "slug": "abzar-dghygh",
      "label": {"fa": "ابزار دقیق", "en": "Instrumentation"},
      "product_count": 2
    },
    {
      "slug": "kntrl",
      "label": {"fa": "کنترل", "en": "Control"},
      "product_count": 1
    }
  ]
}
```

### 3.6 `GET /products` — فهرست/فیلتر/جستجو
| پارامتر | معنی |
|---|---|
| `q` | جستجوی نرمال‌شده (`ي/ی`، `ك/ک`، ارقام فارسی=عربی=لاتین، ZWNJ) روی کد مدل، SKU، نام/زیرعنوان/توضیح کوتاه **همه‌ی زبان‌ها**، تگ‌ها، گواهی‌ها، برند، کد مدل‌های variant. چندکلمه = AND. رتبه: کد مدل دقیق > شروع نام > شامل بودن |
| `category` | slug؛ شامل فرزندان |
| `brand` | slug برند |
| `tag` | slug تگ؛ چندتا با ویرگول ⇒ AND |
| `featured`, `is_new` | `1` |
| `sort` | `featured` (پیش‌فرض؛ شاخص‌ها اول سپس کد مدل) · `name` (بر اساس `lang`) · `model_code` · `newest` · `manual` |
| `lang` | `fa`/`en` فقط برای `sort=name` و رتبه‌ی `q` |
| `page`, `per_page` | پیش‌فرض 12، سقف 100 |
| `facets` | `1` ⇒ شمارنده‌ها؛ هر وجه با اعمال **همه‌ی فیلترهای دیگر به‌جز خودش** شمرده می‌شود (فقط مقادیر >0) |
```bash
curl -s "http://127.0.0.1:5000/api/public/products?category=demo-flow-control&facets=1&per_page=6&sort=name&lang=en"
```
```json
// HTTP 200
{
  "products": [
    {
      "id": 90,
      "slug": "demo-as-fcv-940",
      "model_code": "DEMO-AS-FCV-940",
      "name": {"fa": "شیر کنترل جریان ۹۴۰", "en": "Flow Control Valve 940"},
      "subtitle": {"fa": "سری حرفه‌ای SIL-3", "en": "Professional SIL-3 series"},
      "short_description": {"fa": "شیر کنترل پنوماتیک با دقت بالا.", "en": "High-accuracy pneumatic control valve."},
      "featured": true,
      "is_new": true,
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
        "alt": {"fa": "نمای جلو", "en": "Front view"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      "category": {
        "slug": "demo-control-valves",
        "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"}
      },
      "brand": {
        "slug": "demo-aspd",
        "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
        "logo": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
          "alt": {"fa": "لوگو", "en": "Logo"},
          "width": null,
          "height": null,
          "mime": "image/svg+xml"
        }
      },
      "tags": [
        {"slug": "sil-3", "label": {"fa": "SIL-3", "en": "SIL-3"}},
        {
          "slug": "abzar-dghygh",
          "label": {"fa": "ابزار دقیق", "en": "Instrumentation"}
        },
        "… (+1 more)"
      ],
      "certifications": ["IEC 60534", "SIL-3"],
      "updated_at": "2026-11-01T06:50:41Z"
    },
    {
      "id": 91,
      "slug": "demo-as-pt-210",
      "model_code": "DEMO-AS-PT-210",
      "name": {"fa": "ترانسمیتر فشار ۲۱۰", "en": "Pressure Transmitter 210"},
      "subtitle": {"fa": "کاتالوگ", "en": "Instrumentation"},
      "short_description": {"fa": "ترانسمیتر فشار هوشمند.", "en": "Smart pressure transmitter."},
      "featured": true,
      "is_new": false,
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p2a.jpg",
        "alt": {"fa": "ترانسمیتر", "en": "Transmitter"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      "category": {
        "slug": "demo-flow-control",
        "name": {"fa": "کنترل سیالات", "en": "Flow Control"}
      },
      "brand": {
        "slug": "demo-aspd",
        "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
        "logo": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
          "alt": {"fa": "لوگو", "en": "Logo"},
          "width": null,
          "height": null,
          "mime": "image/svg+xml"
        }
      },
      "tags": [
        {
          "slug": "abzar-dghygh",
          "label": {"fa": "ابزار دقیق", "en": "Instrumentation"}
        }
      ],
      "certifications": ["IEC 61508"],
      "updated_at": "2026-11-01T06:54:59Z"
    }
  ],
  "meta": {"total": 3, "page": 1, "per_page": 2, "total_pages": 2},
  "facets": {
    "categories": [
      {"slug": "demo-flow-control", "count": 3},
      {"slug": "demo-control-valves", "count": 1}
    ],
    "brands": [{"slug": "demo-aspd", "count": 2}],
    "tags": [
      {"slug": "abzar-dghygh", "count": 2},
      {"slug": "kntrl", "count": 1},
      "… (+1 more)"
    ]
  }
}
```
نکته‌ها: فقط محصول **منتشرشده** و دارای `model_code` و `slug` (پیش‌نویس، زمان‌بندی‌شده‌ی آینده و غیرفعال هرگز). قیمت/موجودی/`old_price` هرگز برگردانده نمی‌شوند. اگر فیلتر به چیزی اشاره کند که وجود ندارد (`category=zzz`) نتیجه‌ی خالی است، نه خطا.

### 3.7 `GET /products/<slug>` — جزئیات · تگ: `products`, `product:<slug>`
پاسخ: `{"product": ProductDetail}` (=`ProductCard` + فیلدهای زیر). slug فارسی را `encodeURIComponent` کنید. `?related_limit=3` (1..12): هم‌دسته (بدون خودش) سپس بقیه، با ترتیب `featured`. `images[0]` = `cover`. ناموجود/پیش‌نویس/زمان‌بندی‌نشده ⇒ 404 JSON.
```bash
curl -s "http://127.0.0.1:5000/api/public/products/demo-as-fcv-940?related_limit=2"
```
```json
// HTTP 200
{
  "product": {
    "id": 90,
    "slug": "demo-as-fcv-940",
    "model_code": "DEMO-AS-FCV-940",
    "name": {"fa": "شیر کنترل جریان ۹۴۰", "en": "Flow Control Valve 940"},
    "subtitle": {"fa": "سری حرفه‌ای SIL-3", "en": "Professional SIL-3 series"},
    "short_description": {"fa": "شیر کنترل پنوماتیک با دقت بالا.", "en": "High-accuracy pneumatic control valve."},
    "featured": true,
    "is_new": true,
    "cover": {
      "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
      "alt": {"fa": "نمای جلو", "en": "Front view"},
      "width": 1000,
      "height": 750,
      "mime": "image/jpeg"
    },
    "category": {
      "slug": "demo-control-valves",
      "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"}
    },
    "brand": {
      "slug": "demo-aspd",
      "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
      "logo": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
        "alt": {"fa": "لوگو", "en": "Logo"},
        "width": null,
        "height": null,
        "mime": "image/svg+xml"
      }
    },
    "tags": [
      {"slug": "sil-3", "label": {"fa": "SIL-3", "en": "SIL-3"}},
      {
        "slug": "abzar-dghygh",
        "label": {"fa": "ابزار دقیق", "en": "Instrumentation"}
      },
      "… (+1 more)"
    ],
    "certifications": ["IEC 60534", "SIL-3"],
    "updated_at": "2026-11-01T06:50:41Z",
    "sku": "DEMO-SKU-940",
    "description": {
      "fa": "این شیر برای کنترل دقیق جریان در صنایع نفت و گاز طراحی شده است.\n\nدارای گواهی SIL-3.",
      "en": "Designed for precise flow control in oil & gas.\n\nSIL-3 certified."
    },
    "features": {
      "fa": ["دقت ±۰٫۵٪", "بدنه استیل ۳۱۶", "… (+3 more)"],
      "en": ["±0.5% accuracy", "316 stainless body", "… (+3 more)"]
    },
    "images": [
      {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
        "alt": {"fa": "نمای جلو", "en": "Front view"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1b.jpg",
        "alt": {"fa": "نمای کناری", "en": "Side view"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      "… (+1 more)"
    ],
    "specifications": [
      {
        "label": {"fa": "فشار کاری", "en": "Working pressure"},
        "value": {"fa": "تا ۱۶۰ بار", "en": "Up to 160 bar"}
      },
      {
        "label": {"fa": "دما", "en": "Temperature"},
        "value": {"fa": "‎-۴۰ تا ۴۲۵ درجه", "en": "-40 to 425 °C"}
      },
      "… (+3 more)"
    ],
    "variants": [
      {
        "model_code": "DEMO-AS-FCV-940-S2",
        "name": {"fa": "مدل S2", "en": "Model S2"},
        "configuration": {"fa": "فلنجی", "en": "Flanged"},
        "operating_range": {"fa": "۰ تا ۱۶۰ بار", "en": "0–160 bar"},
        "application": {"fa": "گاز", "en": "Gas"}
      },
      {
        "model_code": "DEMO-AS-FCV-940-S4",
        "name": {"fa": "مدل S4", "en": "Model S4"},
        "configuration": {"fa": "ولد", "en": "Welded"},
        "operating_range": {"fa": "۰ تا ۱۰۰ بار", "en": "0–100 bar"},
        "application": {"fa": "نفت", "en": "Oil"}
      }
    ],
    "documents": [
      {
        "id": 35,
        "type": "datasheet",
        "title": {"fa": "دیتاشیت", "en": "Datasheet"},
        "revision": "Rev 4.2",
        "updated_at": "2026-11-01T06:50:42Z",
        "files": {
          "fa": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/35/download?lang=fa",
            "view_url": "http://127.0.0.1:5000/api/public/documents/35/download?lang=fa&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 590,
            "size_label": "590 B"
          },
          "en": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/35/download?lang=en",
            "view_url": "http://127.0.0.1:5000/api/public/documents/35/download?lang=en&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 590,
            "size_label": "590 B"
          }
        }
      },
      {
        "id": 36,
        "type": "manual",
        "title": {"fa": "راهنمای نصب", "en": "Installation manual"},
        "revision": "2026",
        "updated_at": "2026-11-01T06:50:42Z",
        "files": {
          "fa": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/36/download?lang=fa",
            "view_url": "http://127.0.0.1:5000/api/public/documents/36/download?lang=fa&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 600,
            "size_label": "600 B"
          },
          "en": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/36/download?lang=en",
            "view_url": "http://127.0.0.1:5000/api/public/documents/36/download?lang=en&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 600,
            "size_label": "600 B"
          }
        }
      }
    ],
    "category_path": [
      {
        "slug": "demo-flow-control",
        "name": {"fa": "کنترل سیالات", "en": "Flow Control"}
      },
      {
        "slug": "demo-control-valves",
        "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"}
      }
    ],
    "related": [
      {
        "id": 91,
        "slug": "demo-as-pt-210",
        "model_code": "DEMO-AS-PT-210",
        "name": {"fa": "ترانسمیتر فشار ۲۱۰", "en": "Pressure Transmitter 210"},
        "subtitle": {"fa": "کاتالوگ", "en": "Instrumentation"},
        "short_description": {"fa": "ترانسمیتر فشار هوشمند.", "en": "Smart pressure transmitter."},
        "featured": true,
        "is_new": false,
        "cover": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p2a.jpg",
          "alt": {"fa": "ترانسمیتر", "en": "Transmitter"},
          "width": 1000,
          "height": 750,
          "mime": "image/jpeg"
        },
        "category": {
          "slug": "demo-flow-control",
          "name": {"fa": "کنترل سیالات", "en": "Flow Control"}
        },
        "brand": {
          "slug": "demo-aspd",
          "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
          "logo": {
            "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
            "alt": {"fa": "لوگو", "en": "Logo"},
            "width": null,
            "height": null,
            "mime": "image/svg+xml"
          }
        },
        "tags": [
          {
            "slug": "abzar-dghygh",
            "label": {"fa": "ابزار دقیق", "en": "Instrumentation"}
          }
        ],
        "certifications": ["IEC 61508"],
        "updated_at": "2026-11-01T06:54:59Z"
      }
    ],
    "seo": {
      "title": {"fa": "شیر کنترل جریان ۹۴۰", "en": "Flow Control Valve 940"},
      "description": {"fa": "شیر کنترل پنوماتیک با دقت بالا.", "en": "High-accuracy pneumatic control valve."},
      "keywords": {"fa": ""},
      "og_image": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
        "alt": {"fa": "نمای جلو", "en": "Front view"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      "noindex": false
    },
    "created_at": "2026-11-01T06:50:41Z",
    "published_at": "2026-11-01T06:50:41Z"
  }
}
```

### 3.8 `GET /documents/<id>/download?lang=<code>&inline=0|1` — دانلود فایل
فایل هر سند (محصول **یا** گواهینامه‌ی شرکت). `lang` اختیاری: فایل همان زبان ← `fa` ← اولین فایل. `inline=1` فقط برای PDF/تصویر (وگرنه attachment). هدرها: `Content-Disposition: attachment; filename*=UTF-8''<نام اصلی>`، `Content-Type` درست، `Content-Length`، `X-Content-Type-Options: nosniff`، `Cache-Control: public, max-age=3600`. `HEAD` و `Range` (206) پشتیبانی می‌شود. شمارنده‌ی دانلود فقط با `GET` بدون `Range` افزایش می‌یابد. سند/فایل ناموجود، `is_public=false`، یا مالک منتشرنشده ⇒ 404 JSON. `download_url` و `view_url` را از `documents[].files[lang]` بردارید؛ URL را خودتان نسازید.
```bash
curl -OJ "http://127.0.0.1:5000/api/public/documents/1/download?lang=en"
```

### 3.9 پروژه‌ها · تگ: `projects`, `project:<slug>`, `project-sectors`
`GET /projects?sector=&q=&featured=1&sort=newest|manual&page=&per_page=` (پیش‌فرض 12؛ `newest` = سال بهره‌برداری نزولی)، `GET /projects/<slug>?related_limit=2`، `GET /project-sectors` (فقط بخش‌هایی که پروژه‌ی منتشرشده دارند).
```json
// HTTP 200
{
  "projects": [
    {
      "id": 5,
      "slug": "demo-power-plant",
      "title": {"fa": "نیروگاه نمونه", "en": "Sample Power Plant"},
      "sector": {"slug": "energy", "label": {"fa": "انرژی", "en": "Energy"}},
      "location": {"fa": "تهران", "en": "Tehran"},
      "completion_year": 2024,
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/proj1.jpg",
        "alt": {"fa": "نیروگاه", "en": "Plant"},
        "width": 1400,
        "height": 800,
        "mime": "image/jpeg"
      },
      "short_description": {"fa": "تأمین تجهیزات کنترلی.", "en": "Control equipment supply."},
      "featured": true,
      "highlight_metric": {
        "label": {"fa": "کاهش مصرف", "en": "Energy saving"},
        "value": {"fa": "۱۲٪", "en": "12%"}
      },
      "updated_at": "2026-11-01T06:50:42Z"
    }
  ],
  "meta": {"total": 2, "page": 1, "per_page": 1, "total_pages": 2}
}
```
```json
// HTTP 200
{
  "project": {
    "id": 5,
    "slug": "demo-power-plant",
    "title": {"fa": "نیروگاه نمونه", "en": "Sample Power Plant"},
    "sector": {"slug": "energy", "label": {"fa": "انرژی", "en": "Energy"}},
    "location": {"fa": "تهران", "en": "Tehran"},
    "completion_year": 2024,
    "cover": {
      "url": "http://127.0.0.1:5000/assets/uploads/demo_local/proj1.jpg",
      "alt": {"fa": "نیروگاه", "en": "Plant"},
      "width": 1400,
      "height": 800,
      "mime": "image/jpeg"
    },
    "short_description": {"fa": "تأمین تجهیزات کنترلی.", "en": "Control equipment supply."},
    "featured": true,
    "highlight_metric": {
      "label": {"fa": "کاهش مصرف", "en": "Energy saving"},
      "value": {"fa": "۱۲٪", "en": "12%"}
    },
    "updated_at": "2026-11-01T06:50:42Z",
    "client": {"fa": "شرکت برق", "en": "Power Co."},
    "challenge": {"fa": "فشار بالا.", "en": "High pressure."},
    "solution": {"fa": "شیرهای SIL-3.", "en": "SIL-3 valves."},
    "gallery": [
      {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/proj1.jpg",
        "alt": {"fa": "گالری ۱", "en": "Gallery 1"},
        "width": 1400,
        "height": 800,
        "mime": "image/jpeg"
      },
      "… (+1 more)"
    ],
    "impact_metrics": [
      {
        "label": {"fa": "کاهش مصرف", "en": "Energy saving"},
        "value": {"fa": "۱۲٪", "en": "12%"}
      },
      "… (+1 more)"
    ],
    "specifications": [
      {
        "label": {"fa": "ظرفیت", "en": "Capacity"},
        "value": {"fa": "۵۰۰ مگاوات", "en": "500 MW"}
      }
    ],
    "products": [
      {
        "id": 90,
        "slug": "demo-as-fcv-940",
        "model_code": "DEMO-AS-FCV-940",
        "name": {"fa": "شیر کنترل جریان ۹۴۰", "en": "Flow Control Valve 940"},
        "subtitle": {"fa": "سری حرفه‌ای SIL-3", "en": "Professional SIL-3 series"},
        "short_description": {"fa": "شیر کنترل پنوماتیک با دقت بالا.", "en": "High-accuracy pneumatic control valve."},
        "featured": true,
        "is_new": true,
        "cover": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
          "alt": {"fa": "نمای جلو", "en": "Front view"},
          "width": 1000,
          "height": 750,
          "mime": "image/jpeg"
        },
        "category": {
          "slug": "demo-control-valves",
          "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"}
        },
        "brand": {
          "slug": "demo-aspd",
          "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
          "logo": {
            "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
            "alt": {"fa": "لوگو", "en": "Logo"},
            "width": null,
            "height": null,
            "mime": "image/svg+xml"
          }
        },
        "tags": [
          {"slug": "sil-3", "label": {"fa": "SIL-3", "en": "SIL-3"}},
          "… (+2 more)"
        ],
        "certifications": ["IEC 60534", "… (+1 more)"],
        "updated_at": "2026-11-01T06:50:41Z"
      },
      "… (+1 more)"
    ],
    "related_projects": [
      {
        "id": 6,
        "slug": "demo-desalination",
        "title": {"fa": "نمک‌زدایی نمونه", "en": "Sample Desalination"},
        "sector": {
          "slug": "water",
          "label": {"fa": "آب و نمک‌زدایی", "en": "Water & Desalination"}
        },
        "location": {"fa": "بوشهر", "en": "Bushehr"},
        "completion_year": 2023,
        "cover": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/proj2.jpg",
          "alt": {"fa": ""},
          "width": 1400,
          "height": 800,
          "mime": "image/jpeg"
        },
        "short_description": {"fa": "خط تصفیه.", "en": "Treatment line."},
        "featured": false,
        "highlight_metric": null,
        "updated_at": "2026-11-01T06:50:42Z"
      }
    ],
    "seo": {
      "title": {"fa": "نیروگاه نمونه", "en": "Sample Power Plant"},
      "description": {"fa": "تأمین تجهیزات کنترلی.", "en": "Control equipment supply."},
      "keywords": {"fa": ""},
      "og_image": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/proj1.jpg",
        "alt": {"fa": "نیروگاه", "en": "Plant"},
        "width": 1400,
        "height": 800,
        "mime": "image/jpeg"
      },
      "noindex": false
    }
  }
}
```
```json
// HTTP 200
{
  "sectors": [
    {
      "slug": "energy",
      "label": {"fa": "انرژی", "en": "Energy"},
      "project_count": 1
    },
    {
      "slug": "water",
      "label": {"fa": "آب و نمک‌زدایی", "en": "Water & Desalination"},
      "project_count": 1
    }
  ]
}
```

### 3.10 اخبار و مقالات · تگ: `articles`, `article:<slug>`, `article-categories`
`GET /articles?category=&q=&featured=1&page=&per_page=` (`published_at` نزولی؛ فقط `published_at ≤ now`)، `GET /articles/<slug>?related_limit=3`، `GET /article-categories`. `reading_time_minutes` اگر در پنل خالی باشد خودکار (≈200 کلمه/دقیقه، حداقل 1) است. `sections[].anchor` یکتا در مقاله.
```json
// HTTP 200
{
  "articles": [
    {
      "id": 11,
      "slug": "demo-valve-selection",
      "title": {"fa": "راهنمای انتخاب شیر کنترل", "en": "Control valve selection guide"},
      "excerpt": {"fa": "چکیده راهنمای انتخاب شیر کنترل", "en": "Excerpt of Control valve selection guide"},
      "category": {
        "slug": "engineering",
        "label": {"fa": "مهندسی", "en": "Engineering"}
      },
      "published_at": "2026-10-31T06:50:42Z",
      "reading_time_minutes": 1,
      "author": {
        "name": {"fa": "تیم مهندسی", "en": "Engineering team"},
        "role": {"fa": "مهندس", "en": "Engineer"}
      },
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/art1.jpg",
        "alt": {"fa": "مقاله", "en": "Article"},
        "width": 1200,
        "height": 700,
        "mime": "image/jpeg"
      },
      "featured": true,
      "updated_at": "2026-11-01T06:50:42Z"
    }
  ],
  "meta": {"total": 3, "page": 1, "per_page": 1, "total_pages": 3}
}
```
```json
// HTTP 200
{
  "article": {
    "id": 11,
    "slug": "demo-valve-selection",
    "title": {"fa": "راهنمای انتخاب شیر کنترل", "en": "Control valve selection guide"},
    "excerpt": {"fa": "چکیده راهنمای انتخاب شیر کنترل", "en": "Excerpt of Control valve selection guide"},
    "category": {
      "slug": "engineering",
      "label": {"fa": "مهندسی", "en": "Engineering"}
    },
    "published_at": "2026-10-31T06:50:42Z",
    "reading_time_minutes": 1,
    "author": {
      "name": {"fa": "تیم مهندسی", "en": "Engineering team"},
      "role": {"fa": "مهندس", "en": "Engineer"}
    },
    "cover": {
      "url": "http://127.0.0.1:5000/assets/uploads/demo_local/art1.jpg",
      "alt": {"fa": "مقاله", "en": "Article"},
      "width": 1200,
      "height": 700,
      "mime": "image/jpeg"
    },
    "featured": true,
    "updated_at": "2026-11-01T06:50:42Z",
    "sections": [
      {
        "anchor": "introduction",
        "heading": {"fa": "مقدمه", "en": "Introduction"},
        "paragraphs": {
          "fa": [
            "پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول. پاراگراف اول.",
            "… (+1 more)"
          ],
          "en": [
            "First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph. First paragraph."
          ]
        }
      },
      "… (+1 more)"
    ],
    "related": [
      {
        "id": 12,
        "slug": "demo-sil-intro",
        "title": {"fa": "مقدمه‌ای بر SIL", "en": "An introduction to SIL"},
        "excerpt": {"fa": "چکیده مقدمه‌ای بر SIL", "en": "Excerpt of An introduction to SIL"},
        "category": {
          "slug": "engineering",
          "label": {"fa": "مهندسی", "en": "Engineering"}
        },
        "published_at": "2026-10-30T06:50:42Z",
        "reading_time_minutes": 1,
        "author": {
          "name": {"fa": "تیم مهندسی", "en": "Engineering team"},
          "role": {"fa": "مهندس", "en": "Engineer"}
        },
        "cover": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/art1.jpg",
          "alt": {"fa": "مقاله", "en": "Article"},
          "width": 1200,
          "height": 700,
          "mime": "image/jpeg"
        },
        "featured": false,
        "updated_at": "2026-11-01T06:50:42Z"
      }
    ],
    "seo": {
      "title": {"fa": "راهنمای انتخاب شیر کنترل", "en": "Control valve selection guide"},
      "description": {"fa": "چکیده راهنمای انتخاب شیر کنترل", "en": "Excerpt of Control valve selection guide"},
      "keywords": {"fa": ""},
      "og_image": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/art1.jpg",
        "alt": {"fa": "مقاله", "en": "Article"},
        "width": 1200,
        "height": 700,
        "mime": "image/jpeg"
      },
      "noindex": false
    }
  }
}
```
```json
// HTTP 200
{
  "categories": [
    {
      "slug": "engineering",
      "label": {"fa": "مهندسی", "en": "Engineering"},
      "article_count": 2
    },
    {
      "slug": "innovation",
      "label": {"fa": "نوآوری", "en": "Innovation"},
      "article_count": 0
    },
    {
      "slug": "standards",
      "label": {"fa": "استانداردها", "en": "Standards"},
      "article_count": 0
    },
    "… (+1 more)"
  ]
}
```

### 3.11 خدمات · تگ: `services`
```json
// HTTP 200
{
  "services": [
    {
      "id": 5,
      "slug": "demo-integration",
      "icon": "Settings",
      "title": {"fa": "یکپارچه‌سازی", "en": "Integration"},
      "short_description": {"fa": "خدمت یکپارچه‌سازی", "en": "Service Integration"},
      "description": {"fa": "توضیح یکپارچه‌سازی", "en": "About Integration"},
      "deliverables": {
        "fa": ["گزارش", "… (+1 more)"],
        "en": ["Report", "… (+1 more)"]
      },
      "industries": {"fa": ["نفت"], "en": ["Oil"]}
    },
    "… (+1 more)"
  ],
  "process_steps": [
    {
      "step_number": "01",
      "title": {"fa": "مطالعه", "en": "Study"},
      "description": {"fa": "مرحله مطالعه", "en": "Step Study"}
    },
    "… (+4 more)"
  ]
}
```
`step_number` از ترتیب مراحل فعال ساخته می‌شود (`01`, `02`, …).

`GET /services/<slug>` ⇒ `{"service": {...کارت خدمت..., "seo": Seo, "updated_at": ISO}}`؛ خدمت غیرفعال/ناموجود ⇒ 404. (فرانت فعلی صفحه‌ی جزئیات خدمت ندارد؛ برای صفحه‌ی آینده یا ابتدای sitemap آماده است.)
```bash
curl -s http://127.0.0.1:5000/api/public/services/demo-integration
```
```json
// HTTP 200
{
  "service": {
    "id": 5,
    "slug": "demo-integration",
    "icon": "Settings",
    "title": {"fa": "یکپارچه‌سازی", "en": "Integration"},
    "short_description": {"fa": "خدمت یکپارچه‌سازی", "en": "Service Integration"},
    "description": {"fa": "توضیح یکپارچه‌سازی", "en": "About Integration"},
    "deliverables": {"fa": ["گزارش", "گواهی"], "en": ["Report", "Certificate"]},
    "industries": {"fa": ["نفت"], "en": ["Oil"]},
    "seo": {
      "title": {"fa": "یکپارچه‌سازی", "en": "Integration"},
      "description": {"fa": "خدمت یکپارچه‌سازی", "en": "Service Integration"},
      "keywords": {"fa": ""},
      "og_image": null,
      "noindex": false
    },
    "updated_at": "2026-11-01T06:50:42Z"
  }
}
```

### 3.12 پرسش‌های متداول · تگ: `faq`
فقط دسته‌هایی که پرسش فعال دارند؛ `items` مرتب بر اساس دسته سپس ترتیب.
```json
// HTTP 200
{
  "categories": [
    {
      "slug": "engineering",
      "label": {"fa": "مهندسی", "en": "Engineering"},
      "count": 1
    },
    "… (+3 more)"
  ],
  "items": [
    {
      "id": 9,
      "category": {
        "slug": "engineering",
        "label": {"fa": "مهندسی", "en": "Engineering"}
      },
      "question": {"fa": "آیا شیرها SIL-3 هستند؟", "en": "Q0"},
      "answer": {"fa": "بله، گواهی دارند.", "en": "A0"}
    },
    "… (+3 more)"
  ]
}
```

### 3.13 محتوای شرکت · تگ: `company`
`?include=stats,timeline,team,certifications,industries,testimonials,offices` (پیش‌فرض همه؛ مقدار ناشناخته ⇒ 400). `certifications[].document` همان شکل `ProductDocument` یا `null`. `phone_tel` و `coordinates_label` سمت سرور ساخته می‌شوند.
```json
// HTTP 200
{
  "stats": [
    {
      "id": 9,
      "value": 27,
      "suffix": {"fa": "+"},
      "label": {"fa": "سال تجربه", "en": "Years of experience"},
      "sublabel": {"fa": "زیر سال تجربه"}
    },
    "… (+3 more)"
  ],
  "certifications": [
    {
      "id": 5,
      "code": "DEMO ISO 9001:2015",
      "title": {"fa": "گواهی DEMO ISO 9001:2015", "en": "Certificate DEMO ISO 9001:2015"},
      "issuer": {"fa": "صادرکننده", "en": "Issuer"},
      "description": {"fa": "توضیح", "en": "Description"},
      "logo": null,
      "document": {
        "id": 37,
        "type": "certificate",
        "title": {"fa": "گواهینامه", "en": "Certificate"},
        "revision": "2025",
        "updated_at": "2026-11-01T06:50:43Z",
        "files": {
          "fa": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=fa",
            "view_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=fa&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 591,
            "size_label": "591 B"
          },
          "en": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=en",
            "view_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=en&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 591,
            "size_label": "591 B"
          }
        }
      }
    },
    "… (+1 more)"
  ],
  "offices": [
    {
      "id": 5,
      "title": {"fa": "دفتر مرکزی", "en": "Head office"},
      "address": {"fa": "تهران، خیابان نمونه", "en": "Tehran, Sample St."},
      "phone": "+98 21 8865 4200",
      "phone_tel": "+982188654200",
      "email": "demo@example.com",
      "hours": {"fa": "۸ تا ۱۷", "en": "8–17"},
      "lat": 35.7742,
      "lng": 51.4128,
      "coordinates_label": "35.7742° N, 51.4128° E",
      "is_primary": true
    },
    "… (+1 more)"
  ]
}
```

### 3.14 `POST /inquiries` — فرم تماس · بدنه: JSON
| فیلد | الزامی | قانون (همان zod فرانت) |
|---|---|---|
| `full_name` | ✅ | trim، 3..160 |
| `email` | ✅ | ایمیل معتبر، ≤200 |
| `phone` | ✅ | 8..60؛ ارقام فارسی/عربی/لاتین و `+ - ( ) .` و فاصله |
| `company` | — | ≤160 |
| `subject` | ✅ | 4..240 |
| `product_code` | — | ≤80 (اگر با `model_code` محصولی بخواند، به آن وصل می‌شود) |
| `message` | ✅ | 15..5000 |
| `locale` | — | `fa`/`en` (پیش‌فرض `fa`) |
| `website` | — | **honeypot**: پر باشد ⇒ `201` ظاهری و ذخیره نمی‌شود. در فرم یک input مخفی با این نام بگذارید و خالی بفرستید |
| `captcha_token` | فقط وقتی `site.captcha.provider ≠ null` | توکن Turnstile/hCaptcha (`cf-turnstile-response` / `h-captcha-response`)، ≤4096 نویسه. نبودش ⇒ `422 captcha_token: required`؛ رد شدن ⇒ `422 captcha_token: invalid_value`؛ سرویس کپچا در دسترس نباشد ⇒ `503 unavailable` (دور زده نمی‌شود). توکن تک‌مصرف است و فقط بعد از معتبر شدن بقیه‌ی فیلدها بررسی می‌شود |

کدهای خطای فیلد: `required`، `too_short` (با `min`)، `too_long` (با `max`)، `invalid_email`، `invalid_value`. موفق: `201 {"ok": true, "reference_code": "ASPD-2026-0001"}` — شماره‌ی رهگیری ترتیبی و اتمی (`<PREFIX>-<سال>-<4رقم>`). تجاوز از 5/ساعت یا 20/روز برای هر IP ⇒ `429` + `Retry-After` (ثانیه).
```bash
curl -s -X POST http://127.0.0.1:5000/api/public/inquiries -H "Content-Type: application/json" \
  -d '{"full_name":"علی رضایی","email":"ali@example.com","phone":"+98 21 8865 4200","subject":"درخواست قیمت","message":"لطفاً قیمت و زمان تحویل را اعلام کنید.","product_code":"DEMO-AS-FCV-940","locale":"fa"}'
```
```json
// HTTP 201
{"ok": true, "reference_code": "ASPD-2026-1021"}
```

### 3.15 `GET /search?q=&limit=20&types=products,projects,articles,pages`
`q` خالی/کوتاه‌تر از 2 نویسه ⇒ `200` با همه‌چیز خالی. `limit` هر گروه 1..50. جستجو در **همه‌ی زبان‌ها** (کاربر انگلیسی می‌تواند کد فارسی بزند). `pages` از `page_meta` (about, products, services, projects, contact, faq).
```bash
curl -s "http://127.0.0.1:5000/api/public/search?q=%DB%B9%DB%B4%DB%B0&limit=3"
```
```json
// HTTP 200
{
  "query": "۹۴۰",
  "totals": {"products": 1, "projects": 0, "articles": 0, "pages": 0, "all": 1},
  "products": [
    {
      "id": 90,
      "slug": "demo-as-fcv-940",
      "model_code": "DEMO-AS-FCV-940",
      "name": {"fa": "شیر کنترل جریان ۹۴۰", "en": "Flow Control Valve 940"},
      "subtitle": {"fa": "سری حرفه‌ای SIL-3", "en": "Professional SIL-3 series"},
      "short_description": {"fa": "شیر کنترل پنوماتیک با دقت بالا.", "en": "High-accuracy pneumatic control valve."},
      "featured": true,
      "is_new": true,
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
        "alt": {"fa": "نمای جلو", "en": "Front view"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      "category": {
        "slug": "demo-control-valves",
        "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"}
      },
      "brand": {
        "slug": "demo-aspd",
        "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
        "logo": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
          "alt": {"fa": "لوگو", "en": "Logo"},
          "width": null,
          "height": null,
          "mime": "image/svg+xml"
        }
      },
      "tags": [
        {"slug": "sil-3", "label": {"fa": "SIL-3", "en": "SIL-3"}},
        "… (+2 more)"
      ],
      "certifications": ["IEC 60534", "… (+1 more)"],
      "updated_at": "2026-11-01T06:50:41Z"
    }
  ],
  "projects": [],
  "articles": [],
  "pages": []
}
```

### 3.16 `GET /home?featured_products=4&projects=3&articles=3` (هر کدام 1..12)
تجمیعی برای کاهش round-trip صفحه‌ی اصلی؛ شکل‌ها همان کارت‌ها. `featured_products`/`featured_projects` اگر کمتر از N بودند با جدیدترین‌ها پر می‌شوند.
```json
// HTTP 200
{
  "featured_products": [
    {
      "id": 90,
      "slug": "demo-as-fcv-940",
      "model_code": "DEMO-AS-FCV-940",
      "name": {"fa": "شیر کنترل جریان ۹۴۰", "en": "Flow Control Valve 940"},
      "subtitle": {"fa": "سری حرفه‌ای SIL-3", "en": "Professional SIL-3 series"},
      "short_description": {"fa": "شیر کنترل پنوماتیک با دقت بالا.", "en": "High-accuracy pneumatic control valve."},
      "featured": true,
      "is_new": true,
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
        "alt": {"fa": "نمای جلو", "en": "Front view"},
        "width": 1000,
        "height": 750,
        "mime": "image/jpeg"
      },
      "category": {
        "slug": "demo-control-valves",
        "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"}
      },
      "brand": {
        "slug": "demo-aspd",
        "name": {"fa": "آریا صنعت", "en": "Arya Sanat"},
        "logo": {
          "url": "http://127.0.0.1:5000/assets/uploads/demo_local/brand-logo.svg",
          "alt": {"fa": "لوگو", "en": "Logo"},
          "width": null,
          "height": null,
          "mime": "image/svg+xml"
        }
      },
      "tags": [
        {"slug": "sil-3", "label": {"fa": "SIL-3", "en": "SIL-3"}},
        "… (+2 more)"
      ],
      "certifications": ["IEC 60534", "… (+1 more)"],
      "updated_at": "2026-11-01T06:50:41Z"
    }
  ],
  "categories": [
    {
      "id": 19,
      "slug": "demo-flow-control",
      "parent_slug": null,
      "name": {"fa": "کنترل سیالات", "en": "Flow Control"},
      "short_description": {"fa": "شیرآلات و تجهیزات کنترل جریان", "en": "Valves and flow-control equipment"},
      "icon": "Gauge",
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cat1.jpg",
        "alt": {"fa": "کنترل سیالات", "en": "Flow control"},
        "width": 1000,
        "height": 600,
        "mime": "image/jpeg"
      },
      "standards": ["IEC 60534", "… (+1 more)"],
      "product_count": 3,
      "sort_order": 1,
      "children": [
        {
          "id": 20,
          "slug": "demo-control-valves",
          "parent_slug": "demo-flow-control",
          "name": {"fa": "شیرآلات کنترلی", "en": "Control Valves"},
          "short_description": {"fa": "شیرهای کنترل پنوماتیک", "en": "Pneumatic control valves"},
          "icon": "Cpu",
          "cover": {
            "url": "http://127.0.0.1:5000/assets/uploads/demo_local/cat2.jpg",
            "alt": {"fa": ""},
            "width": 1000,
            "height": 600,
            "mime": "image/jpeg"
          },
          "standards": ["IEC 60534"],
          "product_count": 1,
          "sort_order": 1
        }
      ]
    }
  ],
  "featured_projects": [
    {
      "id": 5,
      "slug": "demo-power-plant",
      "title": {"fa": "نیروگاه نمونه", "en": "Sample Power Plant"},
      "sector": {"slug": "energy", "label": {"fa": "انرژی", "en": "Energy"}},
      "location": {"fa": "تهران", "en": "Tehran"},
      "completion_year": 2024,
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/proj1.jpg",
        "alt": {"fa": "نیروگاه", "en": "Plant"},
        "width": 1400,
        "height": 800,
        "mime": "image/jpeg"
      },
      "short_description": {"fa": "تأمین تجهیزات کنترلی.", "en": "Control equipment supply."},
      "featured": true,
      "highlight_metric": {
        "label": {"fa": "کاهش مصرف", "en": "Energy saving"},
        "value": {"fa": "۱۲٪", "en": "12%"}
      },
      "updated_at": "2026-11-01T06:50:42Z"
    }
  ],
  "latest_articles": [
    {
      "id": 11,
      "slug": "demo-valve-selection",
      "title": {"fa": "راهنمای انتخاب شیر کنترل", "en": "Control valve selection guide"},
      "excerpt": {"fa": "چکیده راهنمای انتخاب شیر کنترل", "en": "Excerpt of Control valve selection guide"},
      "category": {
        "slug": "engineering",
        "label": {"fa": "مهندسی", "en": "Engineering"}
      },
      "published_at": "2026-10-31T06:50:42Z",
      "reading_time_minutes": 1,
      "author": {
        "name": {"fa": "تیم مهندسی", "en": "Engineering team"},
        "role": {"fa": "مهندس", "en": "Engineer"}
      },
      "cover": {
        "url": "http://127.0.0.1:5000/assets/uploads/demo_local/art1.jpg",
        "alt": {"fa": "مقاله", "en": "Article"},
        "width": 1200,
        "height": 700,
        "mime": "image/jpeg"
      },
      "featured": true,
      "updated_at": "2026-11-01T06:50:42Z"
    }
  ],
  "stats": [
    {
      "id": 9,
      "value": 27,
      "suffix": {"fa": "+"},
      "label": {"fa": "سال تجربه", "en": "Years of experience"},
      "sublabel": {"fa": "زیر سال تجربه"}
    },
    "… (+3 more)"
  ],
  "industries": [
    {
      "id": 7,
      "icon": "Flame",
      "title": {"fa": "نفت و گاز", "en": "Oil & Gas"},
      "description": {"fa": "توضیح نفت و گاز"}
    },
    "… (+2 more)"
  ],
  "certifications": [
    {
      "id": 5,
      "code": "DEMO ISO 9001:2015",
      "title": {"fa": "گواهی DEMO ISO 9001:2015", "en": "Certificate DEMO ISO 9001:2015"},
      "issuer": {"fa": "صادرکننده", "en": "Issuer"},
      "description": {"fa": "توضیح", "en": "Description"},
      "logo": null,
      "document": {
        "id": 37,
        "type": "certificate",
        "title": {"fa": "گواهینامه", "en": "Certificate"},
        "revision": "2025",
        "updated_at": "2026-11-01T06:50:43Z",
        "files": {
          "fa": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=fa",
            "view_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=fa&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 591,
            "size_label": "591 B"
          },
          "en": {
            "download_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=en",
            "view_url": "http://127.0.0.1:5000/api/public/documents/37/download?lang=en&inline=1",
            "format": "PDF",
            "mime": "application/pdf",
            "size_bytes": 591,
            "size_label": "591 B"
          }
        }
      }
    },
    "… (+1 more)"
  ],
  "testimonials": [
    {
      "id": 5,
      "quote": {"fa": "عالی بود", "en": "Excellent"},
      "author_name": {"fa": "مشتری 0", "en": "Customer 0"},
      "author_role": {"fa": "مدیر", "en": "Manager"},
      "organization": {"fa": "شرکت", "en": "Company"},
      "sector": {"fa": "انرژی", "en": "Energy"},
      "photo": null
    },
    "… (+1 more)"
  ],
  "offices": [
    {
      "id": 5,
      "title": {"fa": "دفتر مرکزی", "en": "Head office"},
      "address": {"fa": "تهران، خیابان نمونه", "en": "Tehran, Sample St."},
      "phone": "+98 21 8865 4200",
      "phone_tel": "+982188654200",
      "email": "demo@example.com",
      "hours": {"fa": "۸ تا ۱۷", "en": "8–17"},
      "lat": 35.7742,
      "lng": 51.4128,
      "coordinates_label": "35.7742° N, 51.4128° E",
      "is_primary": true
    },
    "… (+1 more)"
  ]
}
```

### 3.17 `GET /sitemap`
فقط منتشرشده‌ها؛ `noindex` حذف می‌شود؛ بدون صفحه‌بندی. `products[].images` برای sitemap تصویری.
```json
// HTTP 200
{
  "site_url": "https://example-frontend.test",
  "pages": [
    {"path": "/", "updated_at": "2026-11-01T06:56:40Z"},
    {"path": "/about", "updated_at": "2026-11-01T06:56:40Z"},
    "… (+6 more)"
  ],
  "categories": [
    {"slug": "demo-flow-control", "updated_at": "2026-11-01T06:54:21Z"},
    {"slug": "demo-control-valves", "updated_at": "2026-11-01T06:54:51Z"}
  ],
  "products": [
    {
      "slug": "demo-as-fcv-940",
      "updated_at": "2026-11-01T06:50:41Z",
      "images": [
        "http://127.0.0.1:5000/assets/uploads/demo_local/p1a.jpg",
        "http://127.0.0.1:5000/assets/uploads/demo_local/p1b.jpg",
        "… (+1 more)"
      ]
    },
    {
      "slug": "demo-as-pt-210",
      "updated_at": "2026-11-01T06:54:59Z",
      "images": ["http://127.0.0.1:5000/assets/uploads/demo_local/p2a.jpg"]
    },
    "… (+1 more)"
  ],
  "projects": [
    {"slug": "demo-power-plant", "updated_at": "2026-11-01T06:50:42Z"},
    {"slug": "demo-desalination", "updated_at": "2026-11-01T06:50:42Z"}
  ],
  "articles": [
    {"slug": "demo-valve-selection", "updated_at": "2026-11-01T06:50:42Z"},
    {"slug": "demo-sil-intro", "updated_at": "2026-11-01T06:50:42Z"},
    "… (+1 more)"
  ],
  "services": [
    {"slug": "demo-integration", "updated_at": "2026-11-01T06:50:42Z"},
    {"slug": "demo-calibration", "updated_at": "2026-11-01T06:50:42Z"}
  ]
}
```
`robots.txt`: اگر `site.seo.robots_index` برابر `false` بود `Disallow: /` و `noindex` بدهید.

### 3.18 `GET /redirects?type=product|category|brand|project|article&slug=<old>`
بعد از تغییر slug در پنل، slug قدیمی ⇒ `{"redirect_to": "<new-slug>"}` وگرنه 404. فرانت در 404 جزئیات یک بار این endpoint را صدا بزند و 301 بدهد.
```json
// HTTP 404
{"ok": false, "error": "not_found", "message": "No redirect for this slug"}
```

### 3.19 `GET /navigation` — منوی قابل‌ویرایش · تگ: `navigation`
`{"header": [...], "footer": [...], "updated_at": ISO}`؛ هر آیتم `{id, label: I18nText, href: string|null, new_tab: boolean, children: [آیتم‌ها]}` (حداکثر دو سطح؛ فرزندان همیشه `children: []` دارند). `href` می‌تواند مسیر داخلی (`/products`)، `https://…`، `mailto:`، `tel:` یا `#بخش` باشد. آیتم بدون `href` = **عنوان گروه** (مثلاً ستون فوتر) و فقط وقتی می‌آید که زیرمنوی فعال دارد. آیتم/والد غیرفعال نمی‌آید. ترتیب = ترتیب پنل. **آرایه‌ی خالی = از منوی داخلی فرانت استفاده کنید.** دسته‌های محصول جزو منو نیستند (از `/categories`).
```bash
curl -s http://127.0.0.1:5000/api/public/navigation
```
```json
// HTTP 200
{
  "header": [
    {
      "id": 1,
      "label": {"fa": "خانه", "en": "Home"},
      "href": "/",
      "new_tab": false,
      "children": []
    },
    {
      "id": 2,
      "label": {"fa": "درباره ما", "en": "About"},
      "href": "/about",
      "new_tab": false,
      "children": []
    },
    "… (+6 more)"
  ],
  "footer": [
    {
      "id": 9,
      "label": {"fa": "درباره ما", "en": "About"},
      "href": "/about",
      "new_tab": false,
      "children": []
    },
    {
      "id": 10,
      "label": {"fa": "محصولات", "en": "Products"},
      "href": "/products",
      "new_tab": false,
      "children": []
    },
    "… (+1 more)"
  ],
  "updated_at": "2026-11-01T06:50:40Z"
}
```

### 3.20 `POST /track` — ثبت بازدید صفحه‌ی فرانت (اختیاری)
ردیاب بک‌اند فقط درخواست‌های Flask را می‌بیند، نه صفحاتی که Next رندر می‌کند. پیش‌فرض **خاموش** است (فقط GA/GTM)؛ مالک در `/admin/site-settings` ← «پیشرفته» روشنش می‌کند. فرانت فقط وقتی `site.analytics.track === true` این endpoint را (ترجیحاً از مرورگر با `navigator.sendBeacon`/fetch) صدا بزند.

بدنه‌ی JSON (≤8KB): `path` (الزامی، با `/` شروع شود، ≤500، بدون فاصله، نه `//`) · `referrer` (اختیاری ≤500) · `locale` (`fa`/`en`) · `visitor_id` (اختیاری؛ `[A-Za-z0-9_-]{8,64}`، شناسه‌ی کوکی خودِ فرانت). موفق: **`204` بدون بدنه** (وقتی خاموش است هم `204` ولی ذخیره نمی‌شود، پس بدون شرط می‌توان صدایش زد). خطا: `422` با `fields`، `400` JSON خراب، `413`، `429` (240 درخواست/دقیقه/IP). IP خام ذخیره نمی‌شود (فقط هش)، ربات‌ها ثبت نمی‌شوند، داده‌ها بعد از `TRACK_RETENTION_DAYS` (180) پاک می‌شوند. گزارش در `/admin/frontend-visits`. CORS مثل بقیه.
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5000/api/public/track -H "Content-Type: application/json" \
  -d '{"path":"/products/as-fcv-940","referrer":"https://google.com/","locale":"fa","visitor_id":"vis_abc12345"}'
```
```json
// HTTP 422
{
  "ok": false,
  "error": "validation_failed",
  "message": "Validation failed",
  "fields": {"path": {"code": "invalid_value"}}
}
```

### 3.21 پیش‌نمایش پیش‌نویس — `?preview=<token>`
ادمین در فرم ویرایش **محصول/پروژه/مقاله** دکمه‌ی «پیش‌نمایش پیش‌نویس» دارد که به `{site.site_url}/<مسیر صفحه>?preview=<token>` می‌رود (لازم است `site_url` در تنظیمات پر باشد). فرانت باید پارامتر `preview` را به endpoint جزئیات بدهد:
`GET /products/<slug>?preview=<token>` · `GET /projects/<slug>?preview=<token>` · `GET /articles/<slug>?preview=<token>`.
- توکن امضاشده، **به یک آیتم و یک نوع** محدود و کوتاه‌عمر (`PREVIEW_TOKEN_TTL`، پیش‌فرض 1 ساعت) است؛ با آن فقط همان یک پیش‌نویس/زمان‌بندی‌شده خوانده می‌شود (slug باید مطابق باشد). توکن نامعتبر/منقضی/نوع دیگر ⇒ `400 bad_request`؛ slug نامطابق ⇒ `404`.
- پاسخ **هرگز کش نمی‌شود** (`Cache-Control: private, no-store`، بدون `ETag`) و `X-Robots-Tag: noindex, nofollow` دارد. فرانت هم در حالت preview از `fetch(..., {cache: 'no-store'})` استفاده کند و صفحه را `noindex` کند.
- لیست‌ها و sitemap هرگز پیش‌نویس را نشان نمی‌دهند؛ لینک دانلود سند یک محصول منتشرنشده تا انتشار 404 است.
```bash
curl -s "http://127.0.0.1:5000/api/public/products/demo-draft-product?preview=<token-از-پنل>"
```

### 3.22 افزودنی‌های `/api/i18n/translate/<code>` (بخش 7)

---

## 4. نگاشت نوع‌های فرانت ← فیلد API

«کارت» = فیلد در لیست؛ «جزئیات» = فقط در endpoint جزئیات.

| نوع فرانت | فیلد فرانت | فیلد API | تفاوت / نکته |
|---|---|---|---|
| **Product** | `id` | `id` | عدد (فرانت رشته می‌داند ولی فقط برای `key`) |
| | `slug`, `modelCode` | `slug`, `model_code` | |
| | `categorySlug` | `category.slug` | `category` می‌تواند `null` باشد |
| | `name`, `subtitle`, `shortDescription` | `name`, `subtitle`, `short_description` | I18nText |
| | `description` | `description` (جزئیات) | متن ساده با `\n` |
| | `images: string[]` | `images[].url` (جزئیات) / `cover.url` (کارت) | `Media` با `alt` (برای `<Image alt>`) |
| | `featured`, `isNew` | `featured`, `is_new` | |
| | `tags: {fa[],en[]}` | `tags: [{slug, label: I18nText}]` | ساختار عوض شده؛ فیلتر با `tag=<slug>` |
| | `features` | `features` (جزئیات) | I18nList |
| | `specifications[{label,value}]` | `specifications[{label,value}]` | همان |
| | `variants[].modelCode / operatingRange` | `variants[].model_code / operating_range` | |
| | `documents[].fileSize` | `documents[].files[lang].size_label` | |
| | `documents[].format` | `documents[].files[lang].format` | هر زبان فایل جدا دارد |
| | `documents[].type / revision / title / id` | همان نام‌ها | `type` ∈ datasheet, manual, certificate, cad, brochure, other |
| | (دانلود) | `files[lang].download_url` / `view_url` | به‌جای `.txt` ساختگی |
| | `certifications` | `certifications: string[]` | |
| | (جدید) | `brand`, `sku`, `category_path`, `related`, `seo`, `created_at`, `published_at`, `updated_at` | |
| **ProductCategory** | `coverImage` | `cover.url` | `Media` یا `null` |
| | `iconName` | `icon` | `Gauge, Cpu, Activity, Zap` |
| | `keyHighlights` | `key_highlights` (جزئیات) | I18nList |
| | `standards` | `standards` | `string[]` |
| | `shortDescription`, `description` | `short_description`, `description` (جزئیات) | |
| | (جدید) | `parent_slug`, `product_count`, `children`, `seo` | |
| **Service** | `iconName` | `icon` | `Settings, ShieldCheck, Compass, Cpu, Wrench, Award` |
| | `shortDescription` | `short_description` | |
| | `deliverables`, `industries` | همان | I18nList |
| **ServiceStep** | `stepNumber` | `step_number` | `"01"` |
| **Project** | `category` (enum) | `sector.slug` | |
| | `categoryLabel` | `sector.label` | I18nText |
| | `clientSector` | `client` | نام سازمان کارفرما (جزئیات) |
| | `completionYear: string` | `completion_year: number` | |
| | `coverImage`, `gallery: string[]` | `cover.url`, `gallery[].url` | |
| | `impactMetrics`, `specifications` | `impact_metrics`, `specifications` | |
| | `relatedProductSlugs` | `products[].slug` | کارت کامل محصول (فقط منتشرشده) |
| | (جدید) | `highlight_metric`, `related_projects`, `featured`, `seo` | |
| **Article** | `category` (enum), `categoryLabel` | `category.slug`, `category.label` | |
| | `publishedAt` | `published_at` | ISO |
| | `readingTimeMinutes` | `reading_time_minutes` | |
| | `author{name,role}` | `author{name,role}` | I18nText |
| | `coverImage` | `cover.url` | |
| | `sections[].id` | `sections[].anchor` | |
| | `sections[].paragraphs` | `sections[].paragraphs` | I18nList |
| **Testimonial** | `authorName`, `authorRole` | `author_name`, `author_role` | + `photo` |
| **TimelineEvent** | `year,title,description` | همان | |
| **TeamMember** | `name,role,qualification,bio` | همان | + `photo` |
| **Certification** | `code,title,issuer,description` | همان | + `logo`, `document` (قابل‌دانلود) |
| **IndustryItem** | `iconName` | `icon` | `Flame, Droplets, Factory, FlaskConical, Zap, Cpu` |
| **CompanyStat** | `numericValue` | `value` | |
| **FaqItem** | `category` (enum), `categoryLabel` | `category.slug`, `category.label` | |
| **ContactOffice** | `coordinatesLabel` | `coordinates_label` | |
| | `phone`, `email`, `hours` | `phone`, `email`, `hours` | + `phone_tel`, `lat`, `lng`, `is_primary` |
| **ContactInquiryPayload** | `fullName`, `productCode` | `full_name`, `product_code` | بقیه هم‌نام (`email, phone, company, subject, message, locale`) |
| **UnifiedSearchResults** | `pages[].slug / href` | `pages[].page_key / path` | |
| | `totalCount` | `totals.all` | + `totals.products/projects/articles/pages` |

---

## 5. نگاشت صفحه‌ها ← endpointها
| صفحه | endpointها |
|---|---|
| Layout (Header/Footer/`<head>`/JSON-LD) | `GET /site` (+`maintenance`/`features`/`captcha`/`analytics.track`)، **`GET /navigation`**، `GET /categories?include_empty=0`، `GET /products?featured=1&per_page=1`، رشته‌های i18n |
| `/` | `GET /home` + `GET /site` + i18n |
| `/about` | `GET /company` + `GET /site` + i18n |
| `/products` | `GET /products?facets=1…`، `GET /categories`، `GET /tags`، `GET /brands` |
| `/products/category/[slug]` | `GET /categories/<slug>`، `GET /products?category=<slug>` |
| `/products/[slug]` | `GET /products/<slug>`؛ دانلود: `files[lang].download_url` |
| `/services` | `GET /services`، `GET /company?include=industries` |
| `/services/[slug]` (اختیاری) | `GET /services/<slug>` |
| `/projects`, `/projects/[slug]` | `GET /projects`، `GET /project-sectors`، `GET /projects/<slug>` |
| `/news`, `/news/[slug]` | `GET /articles`، `GET /article-categories`، `GET /articles/<slug>` + `site.site_url` برای لینک اشتراک |
| `/faq` | `GET /faq` |
| `/contact` | `GET /company?include=offices`، `GET /site`، `POST /inquiries` (+`captcha_token` اگر `site.captcha.provider`) |
| `/search` | `GET /search`؛ پیشنهادها: `site.search_suggestions` |
| `sitemap.xml` / `robots.txt` | `GET /sitemap` (شامل `services`)، `site.seo.robots_index` |
| صفحه‌ی تعمیر | `site.maintenance` |
| هر صفحه (ثبت بازدید، اختیاری) | `POST /track` اگر `site.analytics.track` |
| حالت preview (پنل ← فرانت) | `GET /products|projects|articles/<slug>?preview=<token>` |
| 404 | i18n؛ در 404 جزئیات: `GET /redirects` |

---

## 6. Revalidate (به‌روزرسانی فوری فرانت)

با **هر تغییر محتوا** بک‌اند به فرانت خبر می‌دهد (اگر `FRONTEND_REVALIDATE_URL` و `FRONTEND_REVALIDATE_SECRET` تنظیم باشند؛ وگرنه بی‌صدا غیرفعال).

```
POST <FRONTEND_REVALIDATE_URL>
Content-Type: application/json
X-Revalidate-Secret: <FRONTEND_REVALIDATE_SECRET>

{"event": "content.changed", "tags": ["products", "product:as-fcv-940", "sitemap", "search"], "at": "2026-11-01T08:00:00Z"}
```
- ناهمگام (از thread جدا؛ پاسخ پنل منتظر نمی‌ماند)، timeout 3s، 3 تلاش با backoff، شکست فقط لاگ می‌شود. چند رویداد در 2 ثانیه در **یک** درخواست (اجتماع تگ‌ها) ادغام می‌شوند. آخرین نتیجه در `/admin/revalidate` دیده می‌شود.
- route دریافت‌کننده (`app/api/revalidate/route.ts`): هدر `X-Revalidate-Secret` را با `REVALIDATE_SECRET` مقایسه کنید (نابرابر ⇒ 401)، سپس برای هر تگ `revalidateTag(tag)`؛ تگ `*` = همه. fetchها را با همین تگ‌ها برچسب بزنید: `fetch(url, { next: { tags: ['products', `product:${slug}`] } })`.

| تگ | چه زمانی | هم‌زمان با |
|---|---|---|
| `site` | تنظیمات سایت، `page_meta`، اسلات‌های تصویر، اجتماعی، **زبان‌ها** | |
| `i18n` | هر تغییر رشته‌ی رابط / زبان | `site` (برای زبان‌ها) |
| `categories`, `category:<slug>` | دسته | `products`, `sitemap`, `search` |
| `products`, `product:<slug>` | محصول/مشخصات/مدل‌ها/تصاویر/اسناد/تگ‌ها | `sitemap`, `search` |
| `brands`, `tags` | برند / تگ | `products`, `search` |
| `projects`, `project:<slug>`, `project-sectors` | پروژه/بخش | `sitemap`, `search` |
| `articles`, `article:<slug>`, `article-categories` | مقاله/موضوع | `sitemap`, `search` |
| `services`, `service:<slug>`, `faq`, `company` | | |
| `navigation` | هر تغییر منوی هدر/فوتر | |
| `sitemap`, `search` | انتشار/لغو/تغییر slug هر موجودیت جستجوپذیر | |
| `*` | دکمه‌ی «پاک‌کردن کش فرانت» در پنل | |

تغییر slug ⇒ تگ‌های slug **قدیم و جدید** هر دو ارسال می‌شود.

---

## 7. رشته‌های رابط (i18n)

- فرانت **310 کلید** دارد (`src/locales/{fa,en}.json`)؛ در بک‌اند با پیشوند **`web.`** (مثل `web.nav.home`, `web.contact.validation.nameMin`) و کنار کلیدهای پنل ادمین (بدون تداخل) ذخیره می‌شوند. مقدارها (از جمله `{shown}` و `{query}`) دست‌نخورده‌اند.
- **وضعیت import:** ورودی‌گیر آماده و با فایل‌های واقعی فرانت (`front-locales/fa.json`, `en.json`، هرکدام 310 کلید) تست شده است. روی دیتابیس **واقعی** اجرا کنید (یک بار؛ تکرار بی‌اثر است):
  ```bash
  python main.py import_ui_strings --lang fa --file front-locales/fa.json --prefix web.
  python main.py import_ui_strings --lang en --file front-locales/en.json --prefix web.   # زبان en باید در /admin/i18n ساخته شده باشد
  ```
  یا در پنل: `/admin/i18n/<code>/import` (آپلود JSON). حالت پیش‌فرض `missing` (ویرایش‌های ادمین بازنویسی نمی‌شود)؛ `overwrite` فقط با تأیید صریح.
- **خواندن:** `GET /api/i18n/translate/<code>` (مسیر قدیمی، نه `/api/public`) با پارامترهای اختیاری:
  `prefix=web.` فقط این کلیدها · `strip_prefix=1` حذف پیشوند (`nav.home`) · `fallback=1` پر کردن ترجمه‌نشده‌ها از `fa`. پاسخ `{key: value}` تخت است؛ `ETag`/`304` دارد. بدون پارامتر **دقیقاً مثل قبل**.
  ```bash
  curl -s "http://127.0.0.1:5000/api/i18n/translate/en?prefix=web.&strip_prefix=1&fallback=1"
  ```
  این endpoint CORS ندارد؛ فقط سمت سرور فراخوانی شود. تگ revalidate: `i18n`.
- **ویرایش:** `/admin/i18n/<code>/translate?prefix=web.` (گروه‌بندی بر اساس پیشوند؛ برای `fa` هم از لینک «رشته‌های سایت (web.*)» در `/admin/i18n`).

---

## 8. راهنمای پنل ادمین

ورود: `/login` (کاربر پیش‌فرض `admin` / `admin123` — **حتماً عوض شود**). همه‌ی مسیرهای `/admin/*` فقط برای `administrator`.

| می‌خواهم … | کجا |
|---|---|
| نام/لوگو/آیکن/رنگ/تماس/اجتماعی/سئو/GA/اسلات‌های تصویر/متای صفحات | `/admin/site-settings` (تب‌ها) |
| محصول (+ مشخصات، مدل‌ها، تصاویر، تگ‌ها) | `/admin/products` |
| سند/PDF/نقشه‌ی محصول | `/admin/products/<id>/edit` ← «مدیریت اسناد» (`/admin/documents/product/<id>`) |
| تگ‌های محصول | `/admin/product-tags` |
| دسته‌ها / برندها | `/admin/categories` · `/admin/brands` |
| پروژه‌ها / بخش‌های صنعتی | `/admin/projects` · `/admin/project-sectors` |
| مقالات / موضوعات | `/admin/articles` · `/admin/article-categories` |
| خدمات / مراحل فرایند | `/admin/services` · `/admin/service-steps` |
| پرسش‌های متداول / دسته‌ها | `/admin/faq` · `/admin/faq-categories` |
| آمار، گاه‌شمار، تیم، گواهینامه‌ها (+سند)، صنایع، نظرات، دفاتر | `/admin/company` |
| استعلام‌های فرم تماس (وضعیت، یادداشت، CSV) | `/admin/inquiries` |
| منوی هدر/فوتر | `/admin/navigation` |
| حالت تعمیر، کلیدهای نمایش بخش‌ها، ثبت بازدید فرانت، **کاتالوگ سازمانی** (مخفی‌کردن قیمت/موجودی در فرم محصول) | `/admin/site-settings` ← تب «پیشرفته» |
| گزارش بازدید صفحات فرانت | `/admin/frontend-visits` (فقط وقتی ثبت بازدید روشن است) |
| پیش‌نمایش پیش‌نویس محصول/پروژه/مقاله | دکمه‌ی «پیش‌نمایش پیش‌نویس» در فرم ویرایش |
| کپچا | فقط از `.env` (`CAPTCHA_PROVIDER`, `CAPTCHA_SECRET`, `CAPTCHA_SITE_KEY`) |
| رشته‌های رابط و زبان‌ها | `/admin/i18n` |
| وضعیت webhook / پاک‌کردن کش فرانت | `/admin/revalidate` |
| کتابخانه‌ی رسانه | `/admin/images` (در فرم‌ها دکمه‌ی «انتخاب از کتابخانه») |

نکات: هر فیلد ترجمه‌پذیر تب زبان دارد (`fa` الزامی؛ نقطه‌ی زرد = ترجمه‌ی ناقص). فیلد غایب در فرم = دست‌نخورده؛ خالی‌فرستادن صریح = پاک‌کردن. پیام «ذخیره شد» فقط بعد از ذخیره‌ی واقعی؛ در خطا مقادیر حفظ می‌شوند. محصول بدون `model_code` منتشر نمی‌شود. HTML پشتیبانی نمی‌شود (تگ‌ها حذف می‌شوند).

---

## 9. انحراف‌ها و فرض‌ها

| # | موضوع | تصمیم / دلیل |
|---|---|---|
| 1 | ذخیره‌ی ترجمه | به‌جای جدول `content_translations` از ستون‌های JSON `<field>_i18n` استفاده شد (ساده‌تر، بدون join/N+1). ستون‌های قدیمی (`name`, `description`, `meta_*`, `title`) همچنان برابر `fa` هم‌گام می‌مانند. مهاجرت idempotent است و ستون قدیمی را دست نمی‌زند |
| 2 | شکل جزئیات محصول | `GET /products/<slug>` ⇒ `{"product": …}` (هم‌شکل با `category/project/article/brand`) |
| 3 | محصولات قدیمی بدون `model_code` | در `/api/public/products*` **دیده نمی‌شوند** تا ادمین کد مدل بدهد؛ API قدیمی `/api/products` تغییری نکرده. در پنل ستون «⚠ بدون کد» هشدار می‌دهد |
| 4 | وضعیت پیش‌فرض محصول/پروژه/مقاله‌ی جدید | `draft` |
| 5 | `meta.total_pages` | `0` وقتی `total=0` |
| 6 | کش فایل‌های `/assets/uploads/*` | `max-age=86400` (نه `immutable`)، چون فایل با همان نام می‌تواند بعد از حذف دوباره آپلود شود؛ SVG با CSP `sandbox` |
| 7 | سهمیه‌ی اسناد | `ASSETS_DIR_Max_Size` مجموع `uploads/` + اسناد را محدود می‌کند؛ سقف هر فایل `DOCUMENT_MAX_SIZE_MB` |
| 8 | facets | کامل (هر وجه بدون فیلتر خودش)؛ فقط مقادیر >0 |
| 9 | کش API | درون‌پردازه‌ای، TTL پیش‌فرض 30s، با هر نوشتن پاک می‌شود. چند worker ⇒ `PUBLIC_API_CACHE_TTL=0` (یا Redis در آینده) |
| 10 | rate limit استعلام | شمارنده‌ی درون‌پردازه + شمارش ردیف‌های DB همان IP؛ IP از `X-Real-IP` / `X-Forwarded-For` (قابل جعل اگر بک‌اند پشت پروکسی مورد اعتماد نیست) |
| 11 | ایمیل اعلان | با `SMTP_HOST` فعال؛ گیرنده‌ها در `/admin/site-settings` (تب «استعلام»)؛ بدون SMTP فقط ذخیره + هشدار در پنل |
| 12 | اتصال DB | `Database._conn()` وقتی پول پر است تا `DB_POOL_WAIT` (10s) منتظر می‌ماند (قبلاً بلافاصله خطا می‌داد) |
| 13 | افزونه‌های جدید | `auto_enable`: پلاگین جدید و پلاگین‌های `products/categories/i18n/images/cache` روی **دیتابیس تازه** فعال می‌شوند؛ ردیف موجود `plugins` (فعال یا غیرفعال) هرگز تغییر نمی‌کند |
| 14 | P2 | **همه انجام شد:** ریدایرکت slug، پیش‌نمایش پیش‌نویس (`?preview=`)، منوی قابل‌ویرایش (`/navigation`)، `POST /track` (پیش‌فرض خاموش؛ تصمیم مالک «فقط GA/GTM» حفظ شد)، حالت تعمیر، کلیدهای ویژگی (`site.features`)، «کاتالوگ سازمانی» (فقط پنل)، کپچا (Turnstile/hCaptcha، اختیاری)، `GET /services/<slug>` |
| 14a | کپچا | فعال‌شدنش با `.env` است (نه پنل)؛ روشن باشد توکن **الزامی** می‌شود؛ خرابی سرویس کپچا ⇒ 503 (fail-closed) |
| 14b | `site.features` | فقط «پرچم» است و سمت بک‌اند اعمال نمی‌شود (API بخش‌های خاموش را همچنان می‌دهد)؛ پنهان‌کردن با فرانت |
| 14c | preview | دانلود سند محصول منتشرنشده در preview هم 404 است؛ توکن 1 ساعت اعتبار دارد (`PREVIEW_TOKEN_TTL`) |
| 15 | ⚠️ تغییر رفتار موجود | `@admin_required` روی `/admin/products*`, `/admin/categories*`, `/admin/images*`, `/admin/cache*`, `POST /api/cache/clear/<ns>`, `GET /api/cache/stats`؛ بدون session ⇒ 302 به `/login`. مصرف‌کننده‌ی بدون-session برای این مسیرها شناسایی نشد (کدی در مخزن نبود). `/api/products*`, `/api/categories*`, `/api/i18n/*`, `/assets/uploads/*` عمومی ماندند |

---

## 10. محدودیت‌ها و اشکال‌های شناخته‌شده؛ وضعیت seed
- **رابط ادمین (JS):** تب‌های زبان، repeater، جابه‌جایی ردیف و انتخابگر رسانه با JS ساده نوشته شده؛ رندر سروری همه‌ی صفحات تست شده ولی **در مرورگر واقعی اجرا نشده**. قبل از استفاده‌ی عملیاتی یک بار دستی امتحان کنید.
- **اشکال قدیمی (دست نخورده):** `/product/<slug>` و `/category/<slug>` برای slug ناموجود قالب `404.html` را می‌خواهند که در مخزن نیست (500). تعمیر آن به عهده‌ی صاحب پروژه است.
- جدول `images` (آینه‌ی دیسک) همچنان خراب است (`base64_data`)؛ انتخابگر رسانه از دیسک می‌خواند و به آن وابسته نیست.
- جستجو با `LIKE` روی `search_text` است (بدون FULLTEXT)؛ برای ده‌ها هزار محصول کند می‌شود.
- slug دسته‌ها در DB فعلی UNIQUE است ولی روی دیتابیس تازه (ادغام `declare_schema`) فقط در سطح برنامه تضمین می‌شود (رفتار قبلی).
- منوی پیش‌فرض (`/navigation`) هنگام اولین بوت با لینک‌های اصلی سایت seed می‌شود (قابل‌ویرایش/حذف در `/admin/navigation`؛ پس از حذف دوباره ساخته نمی‌شود).
- ثبت بازدید (`/track`) فقط شمارش ساده است (بازدید/بازدیدکننده/صفحات/ارجاع‌دهنده)؛ جایگزین GA نیست.
- **seed:** `python scripts/seed_demo.py` داده‌ی **نمونه**ی ساختگی می‌سازد (دسته‌ها/برند/3 محصول با PDF/پروژه/مقاله/…؛ همه با پیشوند `demo-`/`DEMO-`)؛ `python scripts/seed_demo.py --remove` دقیقاً همان‌ها را پاک می‌کند. بخش‌های صنعتی/موضوعات/دسته‌های FAQ پیش‌فرض (seed ثابت پلاگین‌ها) **واقعی‌اند** و با `--remove` پاک نمی‌شوند. هیچ محتوای واقعی شرکت وارد نشده است.
- تست‌ها: `python -m unittest discover -s tests -v` (واحد) و `tests/test_api.py` (یکپارچه؛ فقط روی MySQL loopback اجرا می‌شود) و `python scripts/smoke_public_api.py [--base URL]`.

---

## 11. چک‌لیست یکپارچه‌سازی فرانت
1. env ها (`API_BASE_URL`, `NEXT_PUBLIC_API_BASE_URL`, `REVALIDATE_SECRET`) + `images.remotePatterns`؛ در بک‌اند `CORS_ALLOWED_ORIGINS` و `PUBLIC_BASE_URL`.
2. لایه‌ی fetch مشترک با `next: { tags }`، تبدیل `snake_case → camelCase`، `pick(text, locale)`، مدیریت خطا بر اساس `error` (503 ⇒ صفحه‌ی خطا، نه کش).
3. **layout:** `GET /site` (هدر/فوتر/متا/JSON-LD/`theme`/favicon/`media`) + `GET /categories` + i18n (`import_ui_strings` اجرا شده باشد).
4. دسته‌ها و محصولات: `/categories`, `/products` (+facets/filter/sort/صفحه‌بندی)، `/products/<slug>` (+دانلود اسناد، `related`، JSON-LD از `brand`/`sku`)، `/tags`, `/brands`.
5. `/home`، سپس `/company` (about, services-industries, contact-offices).
6. پروژه‌ها، مقالات، خدمات، FAQ.
7. `POST /inquiries` (honeypot `website`، نمایش `reference_code`، نگاشت کدهای خطا به i18n، مدیریت 429 با `Retry-After`).
8. `/search` + `site.search_suggestions`.
9. `sitemap.xml` از `/sitemap`، `robots.txt` از `site.seo.robots_index`، ریدایرکت 301 از `/redirects`.
10. route ‏`/api/revalidate` + تست دستی از `/admin/revalidate`.
11. **منو و پرچم‌ها:** `GET /navigation` (خالی ⇒ منوی داخلی)، `site.features` (پنهان‌کردن بخش‌ها)، `site.maintenance` (صفحه‌ی تعمیر).
12. **کپچا:** اگر `site.captcha.provider` غیر `null` بود ویجت + `captcha_token` در فرم تماس.
13. **پیش‌نمایش:** پذیرفتن `?preview=` در صفحات جزئیات محصول/پروژه/مقاله و عبور آن به API با `cache: 'no-store'` و `noindex`.
14. **ثبت بازدید (اختیاری):** اگر `site.analytics.track` بود `POST /track` از مرورگر.
15. اجرای `scripts/smoke_public_api.py --base <آدرس>` برای اطمینان از شکل‌ها.

---

## 12. Changelog
- **1.1 — 1 نوامبر 2026:** افزودن موارد P2: `GET /navigation`، `GET /services/<slug>` (+`services` در `/sitemap`)، `POST /track`، پیش‌نمایش پیش‌نویس (`?preview=`)، کپچای اختیاری (`captcha_token`، `site.captcha`)، `site.maintenance`، `site.features`، `site.analytics.track`، حالت «کاتالوگ سازمانی» در پنل، تگ‌های `navigation` و `service:<slug>`. هیچ فیلد/endpoint قبلی حذف یا تغییر شکل نداده است (فقط کلیدهای جدید افزوده شد).
- **1.0 — 1 نوامبر 2026:** پیاده‌سازی کامل P0 (زیرساخت، تنظیمات سایت، i18n، دسته‌ها، برندها، محصولات با اسناد/دانلود/facets، رسانه، ⚠️ احراز هویت) و P1 (پروژه‌ها، مقالات، خدمات، FAQ، شرکت، استعلام، جستجو، home/sitemap، revalidate) + ریدایرکت slug از P2.
