# راهنمای کامل API و قابلیت‌های بک‌اند — برای داینامیک‌کردن فرانت‌اند

> **مخاطب:** یک agent (یا توسعه‌دهنده) که باید فرانت‌اند را به بک‌اند این پروژه وصل کند.
> **تاریخ تهیه:** 1 نوامبر 2026 — **مبنا:** خواندن مستقیم سورس (`app/**`) و قالب‌ها.
>
> **وضعیت اعتبارسنجی (صادقانه):** سرور اجرا نشده و به دیتابیس زنده کوئری زده نشده است. همه‌ی رفتارها از روی کد استخراج شده‌اند. فقط قالب سریال‌سازی JSON (Decimal / datetime) با Flask 3.1.3 نصب‌شده در `.venv` به‌صورت عملی بررسی شد. هر جا چیزی «از روی خواندن کد» است و اجرا نشده، همان‌جا نوشته شده است.
> **اگر این سند با `docs/api.md` فرق دارد، این سند معتبرتر است** (چند مورد اختلاف در بخش 10 آمده).

---

## فهرست

1. [خلاصه‌ی ده‌خطی (حتماً بخوانید)](#1-خلاصهی-دهخطی-حتماً-بخوانید)
2. [قراردادهای عمومی](#2-قراردادهای-عمومی)
3. [نقشه‌ی کامل مسیرها](#3-نقشهی-کامل-مسیرها)
4. [API عمومی (ویترین)](#4-api-عمومی-ویترین)
5. [تنظیمات سایت](#5-تنظیمات-سایت)
6. [احراز هویت، کاربران، نقش‌ها، پلاگین‌ها](#6-احراز-هویت-کاربران-نقشها-پلاگینها)
7. [مدیریت محصولات و دسته‌بندی‌ها](#7-مدیریت-محصولات-و-دستهبندیها)
8. [رسانه (تصاویر / فایل‌ها)](#8-رسانه-تصاویر--فایلها)
9. [کش، ردیابی بازدید، قالب‌ساز، مدیریت زبان‌ها](#9-کش-ردیابی-بازدید-قالبساز-مدیریت-زبانها)
10. [فیلترها و محدودیت‌ها — جدول یک‌جا](#10-فیلترها-و-محدودیتها--جدول-یکجا)
11. [آنچه وجود ندارد (شکاف‌ها)](#11-آنچه-وجود-ندارد-شکافها)
12. [باگ‌ها و تله‌های شناسایی‌شده](#12-باگها-و-تلههای-شناساییشده)
13. [دستورالعمل‌های آماده (Recipes)](#13-دستورالعملهای-آماده-recipes)
14. [مدل داده (جدول‌ها)](#14-مدل-داده-جدولها)
15. [پیوست الف: کاتالوگ ویجت‌های قالب‌ساز](#پیوست-الف-کاتالوگ-ویجتهای-قالبساز)
16. [پیوست ب: کلیدهای ترجمه](#پیوست-ب-کلیدهای-ترجمه)

---

## 1. خلاصه‌ی ده‌خطی (حتماً بخوانید)

1. **بک‌اند Flask (async) + MySQL است؛ سمت کلاینت هیچ build-step ندارد.** آدرس توسعه: `http://127.0.0.1:5000`.
2. **JSON فقط از این‌ها می‌آید:** محصولات عمومی، دسته‌بندی‌های عمومی، i18n عمومی، آمار کش، آپلود با `ajax=1`، و API‌های ادمین ردیابی و قالب‌ساز. **بقیه‌ی پنل ادمین (محصول، دسته، کاربر، تنظیمات، رسانه، …) HTML سروری + فرم + redirect است**، نه JSON.
3. **«برند» (Brand) در بک‌اند وجود ندارد** — نه جدول، نه route، نه فیلد. (در کل پروژه، واژه‌ی brand فقط در تنظیم‌های ردیابی مرورگر دیده می‌شود: `browser_family`.) نباید برای آن UI ساخت مگر اینکه بک‌اند اضافه شود.
4. **API محصولات هیچ فیلتر، جست‌وجو، مرتب‌سازی یا صفحه‌بندی ندارد.** فقط 100 محصول `published` تازه‌تر را برمی‌گرداند. فیلتر/مرتب‌سازی باید سمت کلاینت انجام شود (و بالای 100 محصول بی‌صدا بریده می‌شود).
5. **API «محصولات یک دسته» وجود ندارد.** باید از `category_id` در لیست محصولات + درخت دسته‌بندی‌ها کمک گرفت.
6. **API تنظیمات سایت (site_title، meta، …) وجود ندارد.** این مقادیر فقط داخل قالب‌های Jinja با متغیر `settings` در دسترس‌اند (بخش 5).
7. **احراز هویت = کوکی session فلسک + فرم.** لاگین JSON ندارد؛ ادمین‌نشده‌ها به‌جای 401 یک **302 به `/login`** می‌گیرند. CSRF ندارد. CORS ندارد (فقط same-origin یا reverse-proxy).
8. **زبان فقط از پیشوند URL (`/en/...`) تعیین می‌شود**، هرگز از کوکی/session. بدون پیشوند همیشه `fa` است. این عمدی است؛ «اصلاحش» نکنید.
9. **محتوای محصولات/دسته‌ها ترجمه نمی‌شود.** فقط رشته‌های رابط (UI strings) در i18n ترجمه می‌شوند.
10. **هشدار امنیتی:** تمام routeهای `/admin/*` پلاگین‌های `products`، `categories`، `images`، `cache` **بدون هیچ احراز هویتی** باز هستند. همراه با اینکه `product.description` در قالب‌ها با `|safe` چاپ می‌شود، یعنی هر محتوای HTML تزریق‌شده اجرا می‌شود. **هر HTML که از `description` می‌آید را قبل از `innerHTML` sanitize کنید** (مثلاً DOMPurify). این شکاف عمداً در این سند «رفع» نشده؛ تصمیم رفع آن با صاحب پروژه است.

---

## 2. قراردادهای عمومی

### 2.1 آدرس پایه و CORS
- پایه: `http://127.0.0.1:5000` (`main.py`، `debug=True`، reloader روشن).
- CORS هیچ‌جا تنظیم نشده (`flask-cors` در `requirements.txt` نیست). فرانت باید **هم‌مبدأ** سرو شود یا از proxy توسعه (مثل Vite proxy) استفاده کند.
- `credentials: 'same-origin'` را روی هر `fetch` ادمین بگذارید.

### 2.2 سه نوع پاسخ
| نوع | کجا | نکته |
|---|---|---|
| JSON | همه‌ی `/api/*` و چند مسیر ادمین قالب‌ساز | شکل خطا یکدست نیست (بخش 2.5) |
| HTML (Jinja) | تمام صفحات `/admin/*`، `/`، `/product/<slug>`، `/category/<slug>`، `/login` | داده داخل HTML است، نه JSON |
| 302 + flash | همه‌ی POSTهای فرمی ادمین | نتیجه فقط داخل پیام flash در HTML بعدی دیده می‌شود |

### 2.3 قالب سریال‌سازی JSON (بررسی‌شده با Flask 3.1.3)
- `DECIMAL` → **رشته**: `"price": "1500000.00"` (برای محاسبه `Number()` یا کتابخانه‌ی decimal).
- `TIMESTAMP`/`datetime` → **رشته‌ی RFC-822**: `"Mon, 07 Sep 2026 17:15:14 GMT"`. برچسب `GMT` فقط قالب‌بندی فلسک است؛ مقدار همان زمان ذخیره‌شده در DB است. اگر تاریخ جلالی لازم است، سمت کلاینت تبدیل کنید.
- `TINYINT(1)` → عدد `0/1` (نه boolean): `is_active`, `is_deleted`, `is_default`, `is_image`.
- ستون‌های `JSON`/`LONGTEXT` (`extra`, `schema_json`) → **رشته** یا `null` (طبق کامنت خود کد در `theme_builder/plugin.py:_normalize_product`). امن‌ترین کار: `typeof v === 'string' ? JSON.parse(v) : v` داخل try/catch.
- کلیدهای شیء JSON **به ترتیب الفبا** مرتب خروجی می‌آیند (پیش‌فرض فلسک)؛ به ترتیب کلید تکیه نکنید.
- متن فارسی به‌صورت `\uXXXX` escape می‌شود؛ هر parser استاندارد درست می‌خواند.
- ستون‌های زمانی ردیابی (`created_at`, `first_seen`, `last_seen`) **رشته‌ی جلالی** هستند: `"1405/05/05 15:45:23"` (نه RFC-822).

### 2.4 پلاگین‌ها: وجود route وابسته به فعال بودن پلاگین است
- مسیرهای هر پلاگین فقط وقتی ثبت می‌شوند که ردیف آن در جدول `plugins` دارای `enabled=1` باشد. فقط `tracking` در اولین اجرا خودکار فعال می‌شود؛ بقیه باید از `/admin/plugins` (یا مستقیم DB) فعال شوند.
- پلاگین غیرفعال ⇒ مسیرهایش **404 HTML پیش‌فرض Werkzeug** برمی‌گردانند (نه JSON). فرانت باید 404 را «قابلیت غیرفعال است» تفسیر کند.
- پلاگین‌های موجود: `cache`, `categories`, `i18n`, `images`, `products`, `sample_hello`, `theme_builder`, `tracking`.
- وضعیت پلاگین‌ها JSON ندارد (`GET /admin/plugins` فقط HTML است).

### 2.5 شکل خطاها (یکدست نیست)
| وضعیت | بدنه |
|---|---|
| محصول/دسته‌ی عمومی پیدا نشد | `404` + `{"error": "not found"}` |
| تراکنش قالب‌ساز نامعتبر | `400/404` + `{"ok": false, "error": "invalid theme/page"}` |
| آپلود ajax ناموفق | `400` + `{"ok": false, "error": "<پیام فارسی>"}` |
| طرح (design) پیدا نشد | `404` + `{"ok": false}` |
| ردیابی: بازدیدکننده پیدا نشد | `404` + `{"error": "not found"}` |
| پیش‌نمایش قالب‌ساز نامعتبر | `400` + متن ساده `invalid theme/page` (نه JSON) |
| پلاگین غیرفعال / مسیر ناموجود | `404` HTML |
| پارامتر عددی نامعتبر در چند مسیر | **`500` HTML** (بخش 12) |
| خطای DB | **بی‌صدا:** `Database.query` خطا را `print` می‌کند و `None` برمی‌گرداند؛ لیست‌ها خالی (`[]`) می‌شوند، نه خطا |

⇒ **لیست خالی از `/api/products` یعنی «محصولی نیست» یا «DB خراب است»؛ تفاوتشان از روی API معلوم نیست.**

### 2.6 احراز هویت و session
- ورود: `POST /login` با `application/x-www-form-urlencoded` (`username`, `password`). موفق ⇒ `302` به `/dashboard` + کوکی `session` (امضاشده‌ی فلسک: `uid`, `username`, `role`). ناموفق ⇒ **`200` HTML** صفحه‌ی لاگین با پیام flash «نام کاربری یا رمز عبور اشتباه است».
- خروج: `GET /logout` ⇒ `302` به `/login`.
- `@admin_required` یعنی `role == "administrator"` در session. نه جدول `roles`/`permissions` (آن جدول ذخیره می‌شود ولی هرگز اعمال نمی‌شود).
- **بدون session:** مسیر محافظت‌شده ⇒ `302` به `/login` (HTML)، **نه 401**. با `fetch` پیش‌فرض، redirect دنبال می‌شود و شما یک `200 HTML` می‌بینید. تشخیص: `res.headers.get('content-type')` شامل `application/json` نباشد، یا `res.redirected === true`، یا `fetch(url, {redirect: 'manual'})` ⇒ `res.type === 'opaqueredirect'`.
- **کاربر لاگین ولی غیرادمین:** `302` به `/dashboard`.
- endpoint «من کیستم» (`/api/me`) وجود ندارد. برای فهمیدن وضعیت لاگین، به یک API ادمین (مثلاً `/api/admin/site-theme/themes`) درخواست بزنید و نوع پاسخ را بررسی کنید.
- CSRF: **ندارد**. rate-limit/lockout: **ندارد**.
- مدت session: پیش‌فرض فلسک (کوکی session مرورگر؛ `PERMANENT_SESSION_LIFETIME` تنظیم نشده).

### 2.7 رمزگذاری درخواست
- فرم‌های ادمین: `application/x-www-form-urlencoded` (یا `multipart/form-data` برای آپلود).
- JSON فقط در این چند POST خوانده می‌شود: قالب‌ساز (`activate`, `designs`, `preview`). بدنه‌ی نامعتبر JSON به `{}` تبدیل می‌شود (`silent=True`)، نه خطا.
- چک‌باکس: «تیک‌خورده» = وجود کلید با هر مقدار غیرخالی؛ «بدون تیک» = **نبودن کلید**. این برای `is_active`/`is_default` حیاتی است (بخش 12).

### 2.8 کش (سمت سرور، درون‌پردازه‌ای)
- `PluginCache` در حافظه‌ی همان پردازه است؛ بین چند worker/پردازه **مشترک نیست**. TTL پیش‌فرض از `.env` → `CACHE_TTL` (پیش‌فرض 300 ثانیه).
- invalidation دستی و فقط توسط خود پلاگین بعد از نوشتن انجام می‌شود (جزئیات هر endpoint پایین‌تر).
- تغییر دستی دیتابیس بیرون از برنامه، تا انقضای TTL دیده نمی‌شود.

### 2.9 i18n در URL (خلاصه؛ جزئیات در 4.3)
هر مسیری را می‌توان با `/<code>` پیشوند داد (مثلاً `/en/api/products`). سرور در سطح WSGI پیشوند را حذف می‌کند، **به شرط وجود فایل `app/plugins/i18n/locales/<code>.json`**. پیشوند فقط روی `current` در `/api/i18n/languages` و روی صفحات HTML اثر دارد؛ سایر APIها پاسخ یکسان (فارسی) می‌دهند.

---

## 3. نقشه‌ی کامل مسیرها

راهنما — نوع: **J** = JSON، **H** = HTML، **R** = redirect (302). احراز: 🔒 = ادمین، 🔑 = هر کاربر لاگین، **بدون** = بدون هیچ چک احراز (حتی زیر `/admin`).

| متد | مسیر | احراز | نوع | پلاگین/بخش |
|---|---|---|---|---|
| GET | `/` | بدون | H | core (override توسط theme_builder) |
| GET/POST | `/login` | بدون | H / R | core |
| GET | `/logout` | بدون | R | core |
| GET | `/dashboard` | 🔑 | H | core |
| GET/POST | `/admin/settings` | 🔒 | H / R | core |
| GET | `/admin/users` | 🔒 | H | core |
| POST | `/admin/users/create` | 🔒 | R | core |
| POST | `/admin/users/<int:uid>/delete` | 🔒 | R | core |
| GET/POST | `/admin/roles` | 🔒 | H | core |
| GET | `/admin/themes` | 🔒 | H | core (قدیمی) |
| POST | `/admin/themes/activate` | 🔒 | R | core (قدیمی) |
| GET | `/admin/plugins` | 🔒 | H | core |
| POST | `/admin/plugins/toggle` | 🔒 | R | core |
| GET | **`/api/products`** | بدون | **J** | products |
| GET | **`/api/products/<int:pid>`** | بدون | **J** | products |
| GET | `/product/<slug>` | بدون | H | products (override توسط theme_builder) |
| GET | `/admin/products` | **بدون** | H | products |
| GET/POST | `/admin/products/create` | **بدون** | H / R | products |
| GET/POST | `/admin/products/<int:pid>/edit` | **بدون** | H / R | products |
| POST | `/admin/products/<int:pid>/delete` | **بدون** | R | products |
| POST | `/admin/products/<int:pid>/images/add` | **بدون** | R | products |
| POST | `/admin/products/images/<int:img_id>/delete` | **بدون** | R | products |
| GET | **`/api/categories`** | بدون | **J** | categories |
| GET | **`/api/categories/<slug>`** | بدون | **J** | categories |
| GET | `/category/<slug>` | بدون | H | categories |
| GET | `/admin/categories` | **بدون** | H | categories |
| GET/POST | `/admin/categories/create` | **بدون** | H / R | categories |
| GET/POST | `/admin/categories/<int:cid>/edit` | **بدون** | H / R | categories |
| POST | `/admin/categories/<int:cid>/toggle` | **بدون** | R | categories |
| POST | `/admin/categories/<int:cid>/delete` | **بدون** | R | categories (soft delete) |
| POST | `/admin/categories/purge` | **بدون** | R | categories |
| GET | **`/api/i18n/languages`** | بدون | **J** | i18n |
| GET | **`/api/i18n/translate/<code>`** | بدون | **J** | i18n |
| GET | `/lang/<code>` | بدون | R | i18n |
| GET | `/admin/i18n` | 🔒 | H | i18n |
| POST | `/admin/i18n/default/fa` | 🔒 | R | i18n |
| GET/POST | `/admin/i18n/create` | 🔒 | H / R | i18n |
| GET/POST | `/admin/i18n/<code>/edit` | 🔒 | H / R | i18n |
| POST | `/admin/i18n/<code>/delete` | 🔒 | R | i18n |
| GET/POST | `/admin/i18n/<code>/translate` | 🔒 | H / R | i18n |
| GET | `/admin/i18n/<code>/export` | 🔒 | فایل JSON | i18n |
| POST | `/admin/i18n/<code>/seed` | 🔒 | R | i18n |
| GET | `/admin/images` | **بدون** | H | images |
| POST | `/admin/images/upload` | **بدون** | **J** (با `ajax=1`) / R | images |
| POST | `/admin/images/folder/create` | **بدون** | R | images |
| POST | `/admin/images/folder/rename` | **بدون** | R | images |
| POST | `/admin/images/rename` | **بدون** | R | images |
| POST | `/admin/images/delete` | **بدون** | R | images |
| POST | `/admin/images/move` | **بدون** | R | images |
| GET/POST | `/admin/images/edit` | **بدون** | H / R | images |
| GET | `/assets/uploads/<path:filename>` | بدون (عمداً عمومی) | فایل | images |
| GET | `/admin/cache` | **بدون** | H | cache |
| POST | `/admin/cache/clear/<namespace>` | **بدون** | R | cache |
| POST | `/admin/cache/clear` | **بدون** | R | cache |
| POST | `/admin/cache/ttl` | **بدون** | R | cache |
| GET | **`/api/cache/stats`** | **بدون** | **J** | cache |
| POST | **`/api/cache/clear/<namespace>`** | **بدون** | **J** | cache |
| GET | `/admin/tracking`, `/admin/tracking/visitors`, `/admin/tracking/visitor/<int:vid>` | 🔒 | H (پوسته) | tracking |
| GET/POST | `/admin/tracking/settings` | 🔒 | H / R | tracking |
| GET | **`/api/admin/tracking/dashboard`** | 🔒 | **J** | tracking |
| GET | **`/api/admin/tracking/visitors`** | 🔒 | **J** | tracking |
| GET | **`/api/admin/tracking/visitor/<int:vid>`** | 🔒 | **J** | tracking |
| GET | `/admin/site-theme`, `/admin/site-theme/builder/<theme>/<page>` | 🔒 | H (پوسته) | theme_builder |
| GET | **`/api/admin/site-theme/themes`** | 🔒 | **J** | theme_builder |
| POST | **`/api/admin/site-theme/activate`** | 🔒 | **J** | theme_builder |
| GET | **`/api/admin/site-theme/builder/<theme>/<page>`** | 🔒 | **J** | theme_builder |
| POST | `/admin/site-theme/activate` | 🔒 | R | theme_builder (قدیمی) |
| GET | **`/admin/site-theme/builder/<theme>/<page>/designs`** | 🔒 | **J** | theme_builder |
| POST | **`/admin/site-theme/builder/<theme>/<page>/designs`** | 🔒 | **J** | theme_builder |
| GET | **`/admin/site-theme/builder/<theme>/<page>/designs/<id>`** | 🔒 | **J** | theme_builder |
| POST | **`…/designs/<id>/activate`** | 🔒 | **J** | theme_builder |
| POST | **`…/designs/<id>/delete`** | 🔒 | **J** | theme_builder |
| POST | `/admin/site-theme/builder/<theme>/<page>/preview` | 🔒 | H کامل | theme_builder |
| GET | `/theme-assets/<theme>/<path:filename>` | بدون | فایل | theme_builder |
| GET | **`/api/plugins/hello`** | بدون | **J** | sample_hello |

⚠️ **این فهرست کامل است.** هر مسیری که اینجا نیامده وجود ندارد (مثلاً `/api/settings`, `/api/brands`, `/api/products/<slug>`, `/api/me` **وجود ندارند**).

---

## 4. API عمومی (ویترین)

### 4.1 محصولات (`products`)

#### `GET /api/products`
- **پارامتر query: هیچ.** هر پارامتر ارسالی نادیده گرفته می‌شود (`?category=…`, `?page=…`, `?q=…`, `?sort=…` اثری ندارند).
- **فیلتر ثابت سمت سرور:** فقط `status = 'published'`.
- **ترتیب ثابت:** `ORDER BY id DESC` (جدیدترین اول).
- **سقف ثابت:** `LIMIT 100`. صفحه‌بندی وجود ندارد؛ محصول 101ام به بعد هرگز دیده نمی‌شود.
- **کش:** کلید `products:list`، TTL پیش‌فرض (300ثانیه). با هر ایجاد/ویرایش/حذف محصول یا تغییر تصاویر آن بلافاصله پاک و دوباره پر می‌شود. **تغییر دسته‌بندی (نام، حذف، …) کش محصولات را پاک نمی‌کند.**
- **بدنه:** `{"products": [Product, …]}` (در صورت نبود محصول: `{"products": []}`).
- **نکته:** در لیست، `images` ترتیب تضمین‌شده ندارد، و `category` (شیء حل‌شده) و `metatags` **وجود ندارند**؛ فقط `category_id`.

#### `GET /api/products/<int:pid>`
- فقط با **id عددی** (slug پشتیبانی نمی‌شود). `pid` غیرعددی ⇒ 404 HTML.
- محصول ناموجود **یا غیر `published`** ⇒ `404 {"error": "not found"}`.
- بدنه: **خودِ شیء محصول** (بدون wrapper) با سه فیلد اضافه: `images` (مرتب‌شده با `sort_order`)، `category`، `metatags`.
- **کش:** `products:id:<pid>` (محصول draft هم کش می‌شود ولی API آن را 404 می‌کند).

#### شیء Product (فیلدها)
| فیلد | نوع JSON | توضیح |
|---|---|---|
| `id` | int | |
| `name` | string | **نام واقعی**؛ این را نمایش دهید |
| `title` | string | کپی قدیمی `name` برای سازگاری (NOT NULL قدیمی). **نخوانید**؛ در آینده ممکن است حذف شود |
| `slug` | string \| null | یکتا (DB-level)، **ممکن است null باشد** (محصول بدون URL عمومی). بدون slugify ذخیره می‌شود (فارسی/فاصله مجاز) |
| `description` | string \| null | **HTML خام** (`MEDIUMTEXT`). قبل از رندر sanitize کنید |
| `price` | string | Decimal(15,2)، مثال `"1500000.00"`؛ پیش‌فرض `"0.00"` |
| `old_price` | string \| null | قیمت قبلی (برای تخفیف). تخفیف فیلد جدا ندارد؛ `old_price > price` را خودتان محاسبه کنید |
| `stock` | int | موجودی؛ JSON-LD پیش‌فرض: `stock > 0` ⇒ InStock |
| `sku` | string \| null | حداکثر 64 کاراکتر |
| `category_id` | int \| null | شناسه‌ی دسته (ممکن است به دسته‌ی حذف‌شده/غیرفعال اشاره کند) |
| `status` | string | `"published"` یا `"draft"` (رشته‌ی آزاد در DB؛ UI فقط این دو را می‌دهد) |
| `meta_title` | string \| null | ≤191 |
| `meta_description` | string \| null | |
| `meta_keywords` | string \| null | ≤255 |
| `schema_json` | string \| null | JSON-LD خام (ممکن است JSON نامعتبر باشد؛ سرور در آن صورت schema پیش‌فرض می‌سازد) |
| `extra` | string \| null | ستون JSON برای توسعه. **هیچ route‌ای آن را نمی‌نویسد** ⇒ عملاً همیشه `null` |
| `created_at` | string | RFC-822 |
| `images` | `[{url, alt}]` | `url` متنی آزاد است (ببینید 8.5)؛ `alt` ممکن است `""` باشد |

فقط در `GET /api/products/<pid>`:
| فیلد | شکل |
|---|---|
| `category` | `null` یا `{"id", "slug", "title", "parent"?: {"id","slug","title"}}` — `parent` فقط برای زیردسته. این شیء **بدون فیلتر فعال/حذف‌شده** حل می‌شود (دسته‌ی soft-delete شده هم برمی‌گردد). `title` از ستون قدیمی `categories.title` می‌آید که با `name` هم‌گام می‌شود |
| `metatags` | آرایه‌ای از رشته‌های HTML آماده و escape‌شده: `<title>`, `og:title`, `twitter:title`, `description`, `og:description`, `twitter:description`, `keywords`, `og:image`, `twitter:image` (اولین تصویر)، `canonical`, `og:url`, `og:type=product`. **`canonical` و `og:url` مسیر نسبی‌اند** (`/product/<slug>`)، نه URL مطلق. اگر slug نباشد این دو تگ حذف می‌شوند |

مثال (کلیدها الفبایی‌اند، همانند خروجی واقعی):
```json
{
  "category": {"id": 3, "slug": "tower", "title": "برج", "parent": {"id": 1, "slug": "buildings", "title": "ساختمان"}},
  "category_id": 3,
  "created_at": "Mon, 07 Sep 2026 17:15:14 GMT",
  "description": "<p>توضیحات</p>",
  "extra": null,
  "id": 12,
  "images": [{"alt": "نمای جلو", "url": "/assets/uploads/images/a.jpg"}],
  "meta_description": "", "meta_keywords": "", "meta_title": "",
  "metatags": ["<title>برج نمونه</title>", "<meta property=\"og:type\" content=\"product\">"],
  "name": "برج نمونه",
  "old_price": "2000000.00",
  "price": "1500000.00",
  "schema_json": null,
  "sku": "P-12",
  "slug": "sample-tower",
  "status": "published",
  "stock": 5,
  "title": "برج نمونه"
}
```

#### فیلتر/مرتب‌سازی/جست‌وجوی محصولات (باید سمت کلاینت انجام شود)
چون بک‌اند هیچ‌کدام را ندارد، فرانت از همان حداکثر 100 آیتم استفاده می‌کند:
- **بر اساس دسته:** `p.category_id === id`. برای «دسته‌ی والد با زیردسته‌ها»، شناسه‌ی فرزندها را از `/api/categories` (`children[].id`) بگیرید و `category_id ∈ {parent.id, …children.id}` را فیلتر کنید. (توجه: ویجت داینامیک `projects` سرور برعکس، فقط **همان دسته‌ی دقیق** را می‌گیرد و فرزندان را شامل نمی‌شود — بخش 9.3.)
- **قیمت:** `Number(p.price)` (قیمت رشته است). **موجودی:** `p.stock > 0`. **تخفیف‌دار:** `p.old_price && Number(p.old_price) > Number(p.price)`.
- **جست‌وجو:** روی `name`، `sku`، و متن بدون‌تگ `description`.
- **مرتب‌سازی:** جدیدترین = ترتیب پیش‌فرض آرایه (یا `created_at`)، ارزان‌ترین/گران‌ترین = `Number(price)`.
- ⚠️ اگر تعداد محصولات به 100 نزدیک می‌شود، به صاحب پروژه اطلاع دهید؛ باید query param و pagination به بک‌اند اضافه شود (بخش 11).

#### صفحه‌ی HTML محصول: `GET /product/<slug>`
- رندر سروری با JSON-LD (`schema_json` یا schema پیش‌فرض: `@type: Product`، `priceCurrency: "IRR"`).
- اگر پلاگین `theme_builder` فعال باشد و قالب فعال (`active_theme`) صفحه‌ی `product-detail` داشته باشد (فعلاً فقط `conspro`)، با طرح قالب‌ساز رندر می‌شود؛ وگرنه `plugins/products/public.html`.
- **محصول ناموجود ⇒ در عمل `500`**، نه 404 (بخش 12، مورد 1).

---

### 4.2 دسته‌بندی‌ها (`categories`)

دو سطحی (والد ⇢ فرزند)؛ **UI فقط ریشه‌ها را به‌عنوان والد پیشنهاد می‌دهد** (بخش 7.2 برای جزئیات).

#### `GET /api/categories`
- بدون پارامتر query.
- فقط `is_active=1 AND is_deleted=0`.
- **بدنه:** `{"categories": [Root, …]}` که هر `Root` همه‌ی فیلدهای دسته + `children: [Category, …]` (فرزندان فعال) است. فرزندان خودشان `children` ندارند.
- ریشه‌ی **غیرفعال** ⇒ خودش و **همه‌ی فرزندانش (حتی فعال‌ها)** در پاسخ نمی‌آیند.
- ترتیب: ریشه‌ها به ترتیب `id`، فرزندان زیر والدشان (ترتیب داخلی تضمین نشده، عملاً `id`). مرتب‌سازی بر اساس نام را خودتان انجام دهید.
- کش سمت سرور ندارد (هر بار کوئری مستقیم).

#### `GET /api/categories/<slug>`
- `slug` رشته‌ی URL-encoded (فارسی مجاز؛ باید `encodeURIComponent` شود).
- دسته‌ی فعال و حذف‌نشده؛ می‌تواند ریشه **یا** فرزند باشد.
- بدنه: شیء دسته + `children` (فرزندان فعال مستقیم؛ برای یک فرزند `[]`). **شیء `parent` وجود ندارد** — فقط `parent_id`؛ نام والد را از `/api/categories` پیدا کنید.
- ناموجود/غیرفعال/حذف‌شده ⇒ `404 {"error": "not found"}`.

#### شیء Category
| فیلد | نوع | توضیح |
|---|---|---|
| `id` | int | |
| `name` | string | **نام واقعی** — نمایش دهید |
| `title` | string \| null | کپی قدیمی `name`؛ **نخوانید** |
| `slug` | string | یکتا در سطح **برنامه** (نه DB). خودکار از نام ساخته می‌شود: فاصله‌ها → `-`، چند `-` پشت‌سرهم → یکی، حذف `-` ابتدا/انتها؛ حروف فارسی و بزرگ/کوچک **حفظ** می‌شوند. در برخورد، پسوند `-2`, `-3`, … |
| `parent_id` | int \| null | `null` = دسته‌ی اصلی |
| `description` | string \| null | |
| `meta_title`, `meta_description`, `meta_keywords` | string \| null | |
| `schema_json` | string \| null | JSON-LD خام |
| `is_active` | 0/1 | در API عمومی همیشه `1` |
| `is_deleted` | 0/1 | در API عمومی همیشه `0` |
| `created_at` | string | RFC-822 |
| `children` | `[Category]` | فقط در پاسخ‌های بالا |

- **تعداد محصولات هر دسته** در هیچ API نیست؛ خودتان از `/api/products` بشمارید.
- **ثبت slug حاوی `/`** (غیرمعمول ولی ممکن، چون `/` در slug حذف نمی‌شود) مسیر `/api/categories/<slug>` را می‌شکند.

#### صفحه‌ی HTML: `GET /category/<slug>`
رندر سروری با JSON-LD (`CollectionPage`). دسته‌ی ناموجود ⇒ در عمل 500 (بخش 12، مورد 1).

---

### 4.3 چندزبانه (`i18n`)

#### مفاهیم
- **زبان مبدأ = `fa`** (فایل `app/plugins/i18n/locales/fa.json`، 113 کلید). بقیه‌ی زبان‌ها = ترجمه‌های ذخیره‌شده در جدول `i18n_translations`.
- **زبان فقط از پیشوند URL** می‌آید. `/en/...` ⇒ انگلیسی؛ بدون پیشوند ⇒ **همیشه `fa`**، حتی اگر در DB زبان دیگری «پیش‌فرض» علامت خورده باشد (`is_default` فقط یک برچسب در UI ادمین است).
- پیشوند وقتی شناخته می‌شود که **فایل `locales/<code>.json` وجود داشته باشد** (حتی اگر زبان در DB غیرفعال باشد). `/fa/...` هم پیشوند معتبر است و معادل بدون پیشوند.
- **تأثیر پیشوند:** رشته‌های قالب‌های HTML (فیلتر `|_` و `t()`)، `<html lang>`، و فیلد `current` در `/api/i18n/languages`. **داده‌ی محصولات/دسته‌ها/تنظیمات ترجمه نمی‌شود** (تابع `translate_payload` در پلاگین هست ولی هیچ‌جا صدا زده نمی‌شود).
- **ساخت لینک در قالب‌های Jinja:** `lurl('endpoint')` (نه `url_for`). در JS خودتان `/${code}${path}` بسازید.
- ⚠️ کد زبان رزرو: اگر ادمین زبانی با کدی مثل `api`, `admin`, `login`, `lang`, `product`, `category`, `assets` بسازد (regex اجازه می‌دهد)، فایل `locales/<code>.json` ساخته می‌شود و **آن مسیر کلاً به‌عنوان پیشوند زبان بریده می‌شود** و سایت می‌شکند. در UI ساخت زبان این کدها را مسدود کنید.

#### `GET /api/i18n/languages`
```json
{"current": "fa",
 "languages": [{"code": "fa", "name": "Persian", "native_name": "فارسی", "direction": "rtl", "flag": "🇮🇷", "is_default": 1},
               {"code": "en", "name": "English", "native_name": "English", "direction": "ltr", "flag": "🇬🇧", "is_default": 0}]}
```
- فقط زبان‌های `is_active=1`؛ ترتیب: `is_default DESC, name`.
- `current` = زبان **این درخواست** (از پیشوند URL): `GET /en/api/i18n/languages` ⇒ `"current": "en"`.
- `direction` ∈ `{"ltr","rtl"}` (در DB رشته‌ی آزاد؛ ورودی اعتبارسنجی نمی‌شود). `flag` معمولاً ایموجی است (ستون `VARCHAR(8)`؛ URL تصویر جا نمی‌شود).
- ⚠️ **ردیف `fa` ممکن است در DB نباشد** تا وقتی ادمین `/admin/i18n` را باز کند (یا `POST /admin/i18n/default/fa` بزند). فرانت باید اگر `fa` در لیست نبود، آن را **خودش اضافه کند** `{code:'fa', direction:'rtl', native_name:'فارسی'}`.

#### `GET /api/i18n/translate/<code>`
- بدنه: یک شیء **تخت** `{ "nav.home": "Home", … }`.
- ترکیب: ردیف‌های DB آن زبان + محتوای `locales/<code>.json` (بدون بازنویسی ردیف DB).
- ⚠️ **fallback به فارسی در خود API انجام نمی‌شود** (برخلاف docstring کد). برای زبان ترجمه‌نشده/ناقص، فرانت باید **دو درخواست** بزند: `fa` (مبدأ) و زبان هدف، و `{...fa, ...target}` را ادغام کند. فایل `en.json` روی دیسک الان `{}` است.
- کد ناشناخته/غیرفعال ⇒ همچنان `200` با `{}` (نه 404). `fa` ⇒ محتوای `fa.json`.
- کش: 600 ثانیه؛ با ویرایش ادمین بلافاصله پاک می‌شود.
- **aliasها:** در قالب‌های سروری، کلیدی که ترجمه‌ی مستقیم ندارد از «alias»اش پر می‌شود. این منطق در API اعمال **نمی‌شود**؛ ولی هنگام ذخیره از پنل ادمین، مقدار aliasها در DB هم کپی می‌شود. نگاشت (در صورت نیاز پیاده کنید):
  `dashboard.title→nav.dashboard`, `dashboard.settings→settings.title`, `dashboard.users→users.title`, `dashboard.roles→roles.title`, `dashboard.themes→themes.title`, `dashboard.plugins→plugins.title`, `dashboard.limited_access→flash.unauthorized`, `users.col.username→login.username`, `cache.icon_label→cache.title`, `login.submit→nav.login`.
- فهرست کلیدها: پیوست ب.

#### `GET /lang/<code>?next=<path>` (redirect)
- اگر `code` زبان **فعال** در DB باشد: `302` به `/<code><next>`؛ وگرنه `302` به `/`.
- ⚠️ بدون `next`، یا `next=/`، مقصد **`/` بدون پیشوند** است (یعنی فارسی!). برای «صفحه‌ی اصلی انگلیسی» مستقیم به `/en/` بروید، نه `/lang/en`.
- `next` اعتبارسنجی نمی‌شود. اگر با `/<code>` شروع شود، همان‌طور استفاده می‌شود.
- این مسیر چیزی در cookie/session نمی‌نویسد (عمدی).

---

### 4.4 فایل‌ها و دارایی‌ها (Static)

| URL | محتوا | نکته |
|---|---|---|
| `/assets/uploads/<rel>` | فایل‌های آپلودشده توسط ادمین | عمومی. `<rel>` مسیر نسبی داخل `uploads/`. نام فایل‌ها URL-encode شود (نام اصلی فایل، با فاصله/یونیکد حفظ می‌شود) |
| `/assets/<file>` | پوشه‌ی `ASSETS_DIR` (static فلسک) | از `.env` |
| `/theme-assets/<theme>/<path>` | **هر فایل** زیر `templates/themes/<theme>/` | مثال: `/theme-assets/conspro/assets/logo.png`. مسیر نسبت به **ریشه‌ی تم** است، نه فقط `assets/` (در `docs/api.md` اشتباه نوشته شده). `..` مسدود است؛ فایل‌های `.html` قالب تم هم قابل‌دانلودند |
| `/<code>/…` | هر مسیر بالا با پیشوند زبان | پیشوند حذف می‌شود |

- مقدارهای تصویر در تنظیمات ویجت‌ها (مثل `"assets/logo.png"`) **نسبی به تم**‌اند و سرور آن‌ها را به `/theme-assets/<theme>/assets/logo.png` تبدیل می‌کند. مقدار شروع‌شده با `http://`, `https://` یا `/` دست‌نخورده می‌ماند.

### 4.5 `sample_hello`
`GET /api/plugins/hello` ⇒ `{"message": "hello from plugin", "plugin": "sample_hello"}`. فقط نمونه است.

### 4.6 صفحه‌ی اصلی `GET /`
HTML. اگر `theme_builder` فعال باشد و `active_theme` دارای طرح `home` باشد (`conspro` یا `creek`)، با طرح فعال همان تم رندر می‌شود؛ وگرنه `index.html` هسته.

---

## 5. تنظیمات سایت

### 5.1 کلیدهای تنظیمات (جدول `settings`: `key` VARCHAR(64) PK، `value` TEXT)
| کلید | پیش‌فرض | کاربرد |
|---|---|---|
| `site_title` | `شرکت من` | `<title>`، لینک لوگوی متنی، و **نام کوکی ردیابی** (`AT-<slug>`) |
| `meta_description` | `""` | `<meta name="description">` |
| `meta_keywords` | `""` | کلیدواژه‌ها |
| `active_theme` | `default` | تم فعال. مقادیر عملی: `conspro`, `creek`, `construction`؛ فقط `conspro` و `creek` طرح قابل‌ویرایش دارند. هر رشته‌ای پذیرفته می‌شود (وجود پوشه‌ی تم چک نمی‌شود) |
| `default_pages` | `home,about,contact` | رشته‌ی جدا شده با ویرگول از slug صفحات. **هیچ روتی آن را مصرف نمی‌کند** (جدول `pages` هم route ندارد) |
| `cache_ttl` | — | با `/admin/cache/ttl` نوشته می‌شود ولی **هنگام boot خوانده نمی‌شود** (فقط `CACHE_TTL` از `.env`) |
| `tracking_exclude_paths`, `tracking_exclude_methods`, `tracking_status_filter`, `tracking_exclude_uas`, `tracking_ignore_bots` | — | قوانین ردیابی (بخش 9.2) |

### 5.2 خواندن تنظیمات
**هیچ API JSON برای تنظیمات وجود ندارد.** دو راه فعلی:
1. در قالب‌های Jinja: `{{ settings.site_title }}` (همه‌ی ردیف‌های جدول، به‌عنوان dict).
2. افزودن endpoint به بک‌اند (پیشنهاد: `GET /api/settings/public` با کلیدهای امن). اگر فرانت به این نیاز دارد، باید از صاحب پروژه بخواهید — **خودتان بی‌اجازه به هسته اضافه نکنید** (طبق قرارداد پروژه، ویژگی جدید = پلاگین).

### 5.3 نوشتن تنظیمات: `POST /admin/settings` (🔒، فرم، 302 به همان صفحه)
- فیلدها: `site_title`, `meta_description`, `meta_keywords`, `active_theme`, `default_pages`.
- فقط همین 5 کلید ذخیره می‌شوند و فقط اگر کلیدشان در فرم **باشد** (ارسال جزئی مجاز؛ کلید غایب دست‌نخورده می‌ماند). کلیدهای دیگر نادیده گرفته می‌شوند.
- بدون اعتبارسنجی (هیچ حداقل/حداکثری). مقدار `value` نوع `TEXT` (≈64KB).
- بعد از تغییر `site_title`، نام کوکی ردیابی تا `reload_rules()` عوض نمی‌شود (در همان فرایند cache می‌شود).
- راه ایمن‌تر برای تغییر تم: `POST /api/admin/site-theme/activate` (بخش 9.3) که JSON است.

---

## 6. احراز هویت، کاربران، نقش‌ها، پلاگین‌ها

### 6.1 ورود/خروج
جزئیات در 2.6. فیلدها: `username`, `password` (فرم). رمز: PBKDF2-SHA256 با salt ثابت (نکته‌ی امنیتی؛ تغییرش با صاحب پروژه). حساب ادمین پنهان در اولین اجرا خودکار ساخته می‌شود (اطلاعات ورود را از صاحب پروژه بگیرید؛ در این سند نیامده).

### 6.2 `GET /dashboard` (🔑، HTML)
کاشی‌های ورود به پنل از `admin_entry` هر پلاگین فعال: `title`, `icon`, `url`, `order`. (JSON ندارد.) مقادیر فعلی:

| پلاگین | عنوان | url | order |
|---|---|---|---|
| i18n | چند زبانه | `/admin/i18n` | 1 |
| cache | کش | `/admin/cache` | 5 |
| tracking | آمار بازدیدها | `/admin/tracking` | 5 |
| products | محصولات | `/admin/products` | 10 |
| categories | دسته‌بندی‌ها | `/admin/categories` | 11 |
| images | تصاویر | `/admin/images` | 12 |
| theme_builder | قالب سایت | `/admin/site-theme` | 15 |

### 6.3 کاربران
- `GET /admin/users` (🔒، HTML): فقط کاربران با `is_hidden=0`؛ ستون‌ها `id, username, role, created_at`.
- `POST /admin/users/create` (🔒، فرم، 302): `username` (الزامی)، `password` (الزامی)، `role` (پیش‌فرض `editor`؛ UI سه گزینه‌ی `editor`/`author`/`manager` را می‌دهد ولی سرور **هر رشته‌ای** می‌پذیرد، حتی `administrator`).
  - اگر `username` یا `password` خالی باشد: بی‌صدا هیچ کاری نمی‌کند.
  - `INSERT IGNORE`: نام تکراری بی‌صدا نادیده گرفته می‌شود **ولی پیام «کاربر ایجاد شد» باز هم نشان داده می‌شود**.
  - `username` یکتا و ≤64 کاراکتر؛ هیچ قانون پیچیدگی رمز وجود ندارد.
- `POST /admin/users/<uid>/delete` (🔒): حذف مگر `role == administrator` (بی‌صدا).

### 6.4 نقش‌ها
- `GET/POST /admin/roles` (🔒): `POST` با `name` (≤32، یکتا) و چک‌باکس‌های `perm_<section>` برای بخش‌های `settings, users, pages, plugins, products, seo` ⇒ ذخیره به‌شکل JSON `{"settings":1,…}` در جدول `roles`.
- ⚠️ **این نقش‌ها هرگز اعمال نمی‌شوند.** هیچ routeی `AuthManager.can()` را صدا نمی‌زند. سطح دسترسی واقعی فقط «ادمین / غیرادمین» است.

### 6.5 پلاگین‌ها
- `GET /admin/plugins` (🔒، HTML): هر پلاگین `{name, enabled, loaded}`.
- `POST /admin/plugins/toggle` (🔒، فرم): `name`، `enabled` (`"1"` ⇒ فعال؛ هر مقدار دیگر/غایب ⇒ غیرفعال). طبق مستندات پروژه، بدون ری‌استارت اعمال می‌شود.

### 6.6 تم‌ها (قدیمی)
`GET /admin/themes` و `POST /admin/themes/activate` (فرم `theme`) قدیمی و افزونه‌اند؛ برای تم از بخش 9.3 استفاده کنید.

---

## 7. مدیریت محصولات و دسته‌بندی‌ها

> ⚠️ **همه‌ی مسیرهای این بخش هیچ احراز هویتی ندارند** (بخش 1، مورد 10). فرانت نباید به باز بودنشان تکیه کند؛ احتمالاً بعداً `@admin_required` می‌گیرند. همیشه با `credentials: 'same-origin'` و فرض لزوم لاگین بنویسید.
> پاسخ همه‌ی POSTهای این بخش **302 + flash** است (JSON نیست).

### 7.1 محصولات

#### `GET /admin/products` (HTML)
همه‌ی محصولات (با هر `status`)، جدیدترین اول، **سقف 200**، با `img_count`. بدون فیلتر/جست‌وجو/صفحه‌بندی.

#### `POST /admin/products/create` و `POST /admin/products/<pid>/edit`
فرم (`application/x-www-form-urlencoded`)، موفقیت ⇒ `302` به `/admin/products/<id>/edit`.

| فیلد | الزامی | نوع/محدودیت DB | رفتار دقیق |
|---|---|---|---|
| `name` | ✅ | `VARCHAR(191)` | خالی ⇒ ایجاد: پیام خطا + redirect به فرم؛ **ویرایش: بی‌صدا هیچ تغییری ثبت نمی‌شود ولی پیام «ذخیره شد» می‌آید** |
| `slug` | — | `VARCHAR(191)` یکتا | خالی ⇒ ایجاد: `NULL` (بدون URL عمومی؛ خودکار ساخته **نمی‌شود**). ویرایش: **دست‌نخورده** (نمی‌توان پاکش کرد). slugify نمی‌شود: `/ ? #` مسیر را می‌شکنند |
| `sku` | — | `VARCHAR(64)` | خالی ⇒ `""` |
| `category_id` | — | int | خالی ⇒ ایجاد: `NULL`؛ **ویرایش: دست‌نخورده — با ویرایش نمی‌توان دسته را برداشت**. مقدار غیرعددی ⇒ **500** |
| `stock` | — | `INT` | خالی ⇒ `0`. غیرعددی ⇒ **500** |
| `status` | — | `VARCHAR(20)` | غایب ⇒ `"published"` (⚠️ ویرایش بدون این فیلد پیش‌نویس را منتشر می‌کند). UI: `published` / `draft`؛ سرور هر رشته‌ای را می‌پذیرد |
| `price` | — | `DECIMAL(15,2)` | خالی ⇒ `0`. حداکثر 13 رقم صحیح + 2 اعشار |
| `old_price` | — | `DECIMAL(15,2)` | خالی ⇒ ایجاد `NULL`؛ **ویرایش: دست‌نخورده — با ویرایش نمی‌توان پاکش کرد** |
| `description` | — | `MEDIUMTEXT` | HTML خام؛ غایب ⇒ `""` (ویرایش را پاک می‌کند) |
| `meta_title` | — | `VARCHAR(191)` | غایب ⇒ `""` |
| `meta_description` | — | `TEXT` | غایب ⇒ `""` |
| `meta_keywords` | — | `VARCHAR(255)` | غایب ⇒ `""` |
| `schema_json` | — | `LONGTEXT` | خالی ⇒ دست‌نخورده (قابل پاک‌کردن نیست). مقدار باید JSON معتبر باشد وگرنه در نمایش، schema پیش‌فرض جایگزین می‌شود |

نتایج مهم:
- **ویرایش «جایگزینی کامل» است، نه PATCH:** هر فیلد متنی که نفرستید با `""` بازنویسی می‌شود (`description`, `meta_*`, `sku`) و `stock/price` صفر می‌شوند و `status` منتشر می‌شود. **همیشه همه‌ی فیلدها را بفرستید** (مقدار فعلی را از `GET /api/products/<id>` یا فرم بخوانید).
- **slug تکراری:** ایجاد ⇒ پیام خطا؛ **ویرایش ⇒ کل `UPDATE` بی‌صدا شکست می‌خورد و باز هم «ذخیره شد» می‌آید** (هیچ تغییری ثبت نمی‌شود). قبل از ارسال با `/api/products` یکتایی را کلاینتی چک کنید (فقط 100 محصول منتشرشده دیده می‌شود؛ پس کامل نیست).
- ستون `extra` از فرم قابل‌نوشتن نیست.
- `title` (ستون قدیمی) خودکار برابر `name` تنظیم می‌شود.

#### `POST /admin/products/<pid>/delete`
محصول و ردیف‌های `product_images` آن را حذف می‌کند (فایل‌های تصویر دست‌نخورده)؛ وجود محصول چک نمی‌شود؛ همیشه 302 به لیست.

#### تصاویر محصول
- `POST /admin/products/<pid>/images/add`: فیلدها `url` (الزامی بعد از trim؛ ≤500)، `alt` (≤255). `url` اعتبارسنجی نمی‌شود (می‌تواند هر متنی باشد؛ معمولاً `/assets/uploads/...` از رسانه). وجود محصول چک نمی‌شود. `sort_order` قابل‌تنظیم نیست (همیشه 0 ⇒ ترتیب عملاً درج).
- `POST /admin/products/images/<img_id>/delete`: حذف یک ردیف. فایل را حذف نمی‌کند.
- API برای **ترتیب‌دهی مجدد** تصاویر وجود ندارد.

### 7.2 دسته‌بندی‌ها

#### `GET /admin/categories` (HTML)
دسته‌های حذف‌نشده (شامل غیرفعال‌ها)، گروه‌بندی والد/فرزند.

#### `POST /admin/categories/create` و `POST /admin/categories/<cid>/edit`
| فیلد | الزامی | محدودیت | رفتار دقیق |
|---|---|---|---|
| `name` | ✅ | `VARCHAR(191)` | خالی ⇒ **بی‌صدا هیچ کاری نمی‌کند ولی پیام موفقیت می‌آید** |
| `slug` | — | `VARCHAR(191)` | خالی ⇒ خودکار از `name` (قواعد 4.2). همیشه با `-2/-3` یکتا می‌شود (فقط در میان ردیف‌های حذف‌نشده) |
| `parent_id` | — | int | خالی ⇒ دسته‌ی اصلی. غیرعددی ⇒ **500**. فرم فقط ریشه‌ها را نشان می‌دهد. سرور فقط جلوی «والد را فرزندِ فرزندش کردن» را می‌گیرد (`parent_id` را `NULL` می‌کند)؛ جلوی خودِ-والد‌شدن یا ساخت سه‌سطحی را **نمی‌گیرد** (نوه در API دیده نمی‌شود) |
| `description` | — | `TEXT` | |
| `meta_title`, `meta_description`, `meta_keywords` | — | 191 / TEXT / 255 | |
| `schema_json` | — | `LONGTEXT` | خالی ⇒ `NULL` (در ویرایش پاک می‌شود، برخلاف محصول) |
| `is_active` | — | — | **هر مقدار غیرخالی = فعال؛ غایب/خالی = غیرفعال.** ⚠️ ویرایش بدون این فیلد دسته را **غیرفعال** می‌کند. UI مقدار `"1"` یا `""` می‌فرستد |

- **ویرایش هم جایگزینی کامل است** (فیلدهای ارسال‌نشده خالی می‌شوند).
- ایجاد/ویرایش دسته، کش محصولات را **پاک نمی‌کند**.
- `POST /admin/categories/<cid>/toggle` (بدون فیلد): `is_active = 1 - is_active`.
- `POST /admin/categories/<cid>/delete`: **soft delete** — `is_deleted=1, is_active=0` برای خودش و تمام فرزندان مستقیمش. ردیف می‌ماند. API حذف‌نشدن (restore) وجود **ندارد**.
- `POST /admin/categories/purge`: حذف **فیزیکی** دسته‌های soft-delete شده‌ای که «استفاده‌نشده» باشند: نه والد هیچ ردیف دیگری (حتی soft-delete شده) و نه `category_id` هیچ محصولی. ممکن است برای پاک‌شدن والد+فرزند حذف‌شده، دو بار اجرا لازم شود. پیام شمار حذف‌شده‌ها فقط در flash است.
- محصولی که به دسته‌ی حذف‌شده اشاره دارد، `category_id` خود را نگه می‌دارد و `category` در `/api/products/<id>` همچنان حل می‌شود.

---

## 8. رسانه (تصاویر / فایل‌ها)

> ⚠️ هیچ احراز هویتی ندارد (بخش 1، مورد 10). همه‌ی خروجی‌ها (به‌جز آپلود با `ajax=1`) HTML/redirect هستند.
> **API JSON برای لیست‌کردن فایل‌ها وجود ندارد.** مرورگر فایل فقط صفحه‌ی HTML `/admin/images` است.

### 8.1 پایه
- ریشه‌ی ذخیره: پوشه‌ی `uploads/` در ریشه‌ی پروژه؛ عمومی در `/assets/uploads/<rel>`.
- DB جدول `images` قرار است آینه‌ی پوشه باشد ولی **عملاً کار نمی‌کند** (ستون `base64_data` تعریف نشده ⇒ هر upsert بی‌صدا شکست می‌خورد). **از جدول `images` نخوانید.** منبع حقیقت = دیسک.
- پسوندهای «تصویر» (تشخیص ابعاد): `png jpg jpeg gif webp bmp svg`. پسوندهای «متنِ قابل‌ویرایش» در UI: `txt md css js json html`.

### 8.2 `GET /admin/images` — فیلترها (query، همه اختیاری)
| پارامتر | معنی | جزئیات |
|---|---|---|
| `folder` | پوشه‌ی نسبی داخل `uploads` | `""` = ریشه. شامل `..` ⇒ flash خطا + 302 به ریشه. پوشه‌ی ناموجود ⇒ همان |
| `q` | جست‌وجوی زیررشته در **نام فایل** | case-insensitive |
| `ext` | پسوند دقیق | با/بی `.`، به حروف کوچک تبدیل می‌شود؛ مقایسه‌ی برابری (نه زیررشته) |
| `date_from`, `date_to` | بازه‌ی **تاریخ ویرایش فایل (mtime)** | قالب سخت‌گیر `YYYY-MM-DD` (میلادی). `date_to` تا 23:59:59 همان روز **شامل** است. ⚠️ قالب نامعتبر ⇒ **500** |
| `size_min`, `size_max` | بازه‌ی حجم | **به مگابایت** (اعشار مجاز). ⚠️ غیرعددی ⇒ **500** |
| `recursive` | `1` ⇒ فایل‌های همه‌ی زیرپوشه‌ها | وقتی `1` است، فهرست «پوشه‌ها» تولید **نمی‌شود** |

فیلدهای هر فایل (در قالب HTML): `name`, `rel`, `ext`, `size` (بایت), `size_h`, `mtime_h` (`YYYY-MM-DD HH:MM`, زمان محلی سرور), `is_image`, `is_text`, `width`, `height`. هر پوشه: `name`, `rel`, `count` (تعداد بازگشتی فایل). به‌علاوه `used_bytes` و `max_bytes` (سهمیه) در قالب.

کش لیست: کلید `images:list:<folder>:<0|1>`، TTL پیش‌فرض؛ فیلترها روی نتیجه‌ی کش‌شده اعمال می‌شوند. ⚠️ از روی خواندن کد: بعد از **آپلود** و **ساخت پوشه** کش پاک نمی‌شود (کلید ابطال با کلید ذخیره نمی‌خواند)، پس ممکن است تا 300 ثانیه فایل جدید دیده نشود؛ rename/move/delete کل namespace را پاک می‌کنند. (اجرا نشده؛ از کد استنباط شده.)

### 8.3 آپلود: `POST /admin/images/upload` (`multipart/form-data`)
| فیلد | توضیح |
|---|---|
| `files` | یک یا چند فایل (کلید تکراری `files`) |
| `folder` | پوشه‌ی مقصد نسبی؛ خالی = ریشه؛ در صورت نبود ساخته می‌شود |
| `ajax` | `"1"` ⇒ پاسخ JSON (وگرنه 302) |
| `back` | آدرس redirect حالت غیر-ajax (**اعتبارسنجی نمی‌شود**) |

پاسخ موفق: `{"ok": true, "uploaded": [{"name","rel","url","size_h","mtime_h","ext","width","height","is_image"}]}` که `url = "/assets/uploads/<rel>"` (با اسلش آغازین؛ **همین را در `product_images.url` بگذارید**). اگر فایلی نفرستید: `{"ok": true, "uploaded": []}`.
پاسخ خطا `400`: `{"ok": false, "error": "…"}` برای مسیر نامعتبر یا پرشدن سهمیه (پیام فارسی با اندازه‌ها).

قواعد و محدودیت‌ها:
- **هیچ محدودیت پسوند/MIME وجود ندارد** (`.html`, `.js`, `.php` هم پذیرفته می‌شوند). محدودیت لازم است فرانت سمت UI اعمال کند، ولی بک‌اند آن را اجبار نمی‌کند.
- **هیچ سقف حجم برای هر فایل/درخواست** نیست (`MAX_CONTENT_LENGTH` تنظیم نشده).
- **سهمیه‌ی کل پوشه:** `.env` → `ASSETS_DIR_Max_Size` به **گیگابایت** (`0` یا خالی = نامحدود؛ `0.5` = 500MB). اگر `حجم فعلی + حجم ورودی` از آن بگذرد، **کل درخواست** رد می‌شود (حتی فایل‌های کوچک‌تر).
- **برخورد نام:** اگر فایلی همنام باشد، به‌صورت `name-1.ext`, `name-2.ext`, … ذخیره می‌شود (بازنویسی نمی‌شود). نام نهایی را از پاسخ بخوانید.
- نام فایل فقط با `basename` پاک‌سازی می‌شود (فاصله و یونیکد می‌ماند) ⇒ هنگام ساخت URL `encodeURI` کنید.
- اندازه‌ی تصویر از Pillow (در نبود آن از هدر PNG/GIF) خوانده می‌شود؛ ممکن است `width/height` برابر `null` باشد (مثلاً `svg`, `webp` بدون Pillow).

### 8.4 سایر عملیات (همه فرم، 302 به `back` یا `/admin/images`، نتیجه فقط در flash)
| مسیر | فیلدها | رفتار |
|---|---|---|
| `POST /admin/images/folder/create` | `name`, `folder` (والد), `back` | `makedirs`؛ فقط وجود `..` در مسیر چک می‌شود (`name` حاوی `/` پوشه‌ی تودرتو می‌سازد) |
| `POST /admin/images/folder/rename` | `rel`, `new_name` (فقط basename), `back` | خطا اگر پوشه‌ی هم‌نام باشد |
| `POST /admin/images/rename` | `rel`, `new_name`, `back` | اگر مقصد موجود/نام خالی باشد بی‌صدا کاری نمی‌کند |
| `POST /admin/images/delete` | `rel[]` (چندتایی) یا `rel`, `back` | **پوشه‌ها بازگشتی (`rmtree`) و بدون تأیید حذف می‌شوند** |
| `POST /admin/images/move` | `rel[]`/`rel`, `dest` (پوشه‌ی مقصد؛ خالی=ریشه), `back` | اگر در مقصد همنام باشد، آن مورد رد می‌شود |
| `GET /admin/images/edit?rel=` | — | HTML ویرایشگر |
| `POST /admin/images/edit` | `rel`, `content`, `back` | نوشتن UTF-8. **پسوند چک نمی‌شود** (هر فایل زیر `uploads` قابل‌بازنویسی است) |

همه‌ی مسیرها با `_safe_rel/_abs_path` در برابر `..` و خروج از `uploads/` محافظت‌شده‌اند (هر مسیر جدید باید از همین‌ها استفاده کند). **همه‌ی `back`ها بدون اعتبارسنجی هستند (open redirect).**

### 8.5 نکته درباره‌ی `product_images.url`
مقدار آزاد است؛ ممکن است `http(s)://…` یا `/assets/uploads/…` یا (اگر از ستون آینه کپی شده) بدون اسلش آغازین باشد. در فرانت نرمال کنید: اگر با `http` یا `/` شروع نمی‌شود، `/` اول آن بگذارید.

---

## 9. کش، ردیابی بازدید، قالب‌ساز، مدیریت زبان‌ها

### 9.1 کش (`cache`) — ⚠️ بدون احراز هویت
- `GET /api/cache/stats` ⇒ `{"stats": [{"namespace","hits","misses","hit_rate","key_count"}], "total_keys": N}` (`hit_rate` درصد با یک رقم اعشار).
- `POST /api/cache/clear/<namespace>` ⇒ `{"ok": true, "cleared": "<namespace>"}` (هر نام‌فضا بدون اعتبارسنجی).
- فرم‌ها: `POST /admin/cache/clear/<ns>`، `POST /admin/cache/clear` (کل کش)، `POST /admin/cache/ttl` (فیلد `ttl` عدد صحیح؛ حداقل 10؛ غیرعددی ⇒ 300).
- namespaceها: `products`, `images`, `i18n`, `i18n_lang_<code>`, `tracking_geo`, `tracking_visitor`, `tracking_admin`.
- حداکثر 5000 کلید در کل؛ در پرشدن، قدیمی‌ترین (نزدیک‌ترین انقضا) حذف می‌شود.
- TTLهای خاص: دیکشنری ترجمه 600ثانیه، فایل منبع 60ثانیه، زبان پیش‌فرض 30ثانیه، geo-IP 86400، شناسه‌ی بازدیدکننده 3600، پاسخ‌های ادمین ردیابی 86400.

### 9.2 ردیابی بازدید (`tracking`) — 🔒 ادمین

#### چه چیزی ثبت می‌شود
**هر درخواست HTTP به سایت** (از جمله فراخوانی‌های `/api/products` توسط فرانت شما!) مگر اینکه قوانین حذف رد کنند. برای هر درخواست: referrer (`origin`)، مقصد (`destination`؛ برای GET شامل query، و `?` انتهایی در نبود query)، `status_code`، `method`، سه IP، کشور/شهر (MaxMind)، user-agent و `browser_family`/`browser_version`/`device_type`، `user_id` (اگر لاگین)، و بازدیدکننده (کوکی).
- کوکی: نام `AT-<slug(site_title)>` (حروف غیر لاتین حذف می‌شوند؛ عنوان فارسی ⇒ `AT-site`)، `HttpOnly`, `SameSite=Lax`, 1 سال, `path=/`. با JS خوانده نمی‌شود.
- **IP واقعی** = `X-Real-IP` ← اولین `X-Forwarded-For` ← `remote_addr`. پشت reverse proxy باید این هدرها ست شوند. روی `127.0.0.1` کشور/شهر `null` است.
- `device_type` ∈ `mobile | tablet | pc | bot | other`.
- نوشتن در پس‌زمینه (صف + thread) است؛ پاسخ کاربر هرگز منتظر DB نمی‌ماند. صف 10000 تایی؛ پر شود ردیف دور ریخته می‌شود.

#### قوانین حذف (پیش‌فرض‌ها وقتی تنظیم خالی باشد)
`path_patterns` (glob، هر خط یک الگو؛ پیشوند `re:` = regex با `re.search` و بدون حساسیت به حروف؛ مقایسه روی `path` و (برای GET) `full_path` با query):
```
/assets/*  /static/*  /uploads/*  /favicon.ico  /robots.txt  /sitemap*.xml
*/.well-known  */.well-known/*  /*well-known*  /admin/plugins*
/admin/tracking  /admin/tracking/*  /api/admin/*
```
- `method_patterns` پیش‌فرض خالی (هیچ متدی حذف نمی‌شود)؛ هر خط یک متد.
- `status_filter`: `all` (پیش‌فرض) / `success` (200≤کد<400) / `errors` (کد≥400).
- `ua_patterns` پیش‌فرض: `*bot* *crawl* *spider* *slurp* *facebookexternalhit* *headlesschrome* *python-requests* *curl/* *wget/*`.
- `ignore_bots`: پیش‌فرض روشن (`1`)؛ مقادیر truthy: `1,true,yes,on`.
- ⚠️ **مقدار خالی = «پیش‌فرض»**: نمی‌توان با خالی‌کردن فیلد، الگوهای پیش‌فرض مسیر/UA را برداشت. مسیرهای `/assets/*` و `/api/admin/*` در پیش‌فرض‌اند، ولی `/api/products` **حذف نمی‌شود** و ثبت می‌گردد.

#### `POST /admin/tracking/settings` (فرم، 302)
فیلدها: `paths`, `methods`, `status`, `uas` (متن چندخطی) و `bots` (چک‌باکس ⇒ ذخیره‌ی `"1"`/`"0"`). ذخیره در `settings` (کلیدهای بخش 5.1) و پاک‌شدن کش ادمین ردیابی. `GET` همان صفحه HTML است.

#### `GET /api/admin/tracking/dashboard`
```json
{"total_requests": 1234, "total_visitors": 56, "unique_ips": 40,
 "by_country":  [{"country_code":"IR","country_name":"Iran","hits":900}],
 "by_device":   [{"device_type":"pc","hits":700}],
 "by_browser":  [{"browser_family":"Chrome","hits":650}],
 "recent": [{"id":8841,"created_at":"1405/05/05 15:45:23","destination":"/api/products?","status_code":200,
             "ip_remote":"…","ip_forwarded":null,"ip_real":null,"country_code":"IR","country_name":"Iran",
             "browser_family":"Chrome","browser_version":"126.0","device_type":"pc",
             "user_id":null,"visitor_id":7,"cookie_value":"…"}]}
```
- `by_country`: 10 مورد برتر، فقط ردیف‌هایی با `country_code` غیر-NULL. `by_browser`: 10 برتر، بدون `browser_family` خالی. `by_device`: همه (ممکن است شامل `null` باشد). `recent`: 50 ردیف آخر (`id` نزولی).
- `unique_ips` = `COUNT(DISTINCT ip_remote)`.
- ⚠️ **بروزرسانی نیمه‌زنده:** با هر درخواست جدید، کش در جا اصلاح می‌شود (شمارنده‌ها و `recent`)، ولی `recent[].id` برای ردیف‌های تازه **`null`** است تا کش دوباره از DB ساخته شود؛ `unique_ips`/`total_visitors` در این بروزرسانی تغییر نمی‌کنند (با بازدیدکننده‌ی جدید کل کش پاک می‌شود). **`id` را به‌عنوان key یکتا فرض نکنید.**

#### `GET /api/admin/tracking/visitors?page=N`
```json
{"visitors": [{"id":7,"cookie_name":"AT-site","cookie_value":"…","user_id":null,"request_count":31,
               "first_ip_remote":"…","first_ip_forwarded":null,"first_ip_real":null,"first_country":"IR",
               "first_seen":"1405/05/01 10:00:00","last_seen":"1405/05/05 15:45:23"}],
 "page": 1, "per_page": 50, "total": 56}
```
- **تنها پارامتر: `page`** (عدد ≥1؛ مقدار کمتر از 1 ⇒ 1؛ بزرگ‌تر از آخرین صفحه ⇒ لیست خالی). **`per_page` ثابت 50** است. **فیلتر/جست‌وجو/مرتب‌سازی ندارد.** `page=abc` ⇒ **500**.
- ترتیب: `last_seen DESC` (رشته‌ی جلالی صفرپرشده؛ ترتیب لغتی = ترتیب زمانی).
- ⚠️ لیست فقط وقتی بازسازی می‌شود که بازدیدکننده‌ی **جدید** بیاید (یا قوانین ذخیره شوند)؛ `last_seen`/`request_count` بازدیدکنندگان قدیمی تا 24ساعت قدیمی بماند.

#### `GET /api/admin/tracking/visitor/<int:vid>`
`{"visitor": {…همان فیلدهای بالا…}, "requests": [{"id","created_at","method","destination","origin","status_code","ip_remote","ip_forwarded","ip_real","country_code","country_name","city","browser_family","browser_version","device_type","user_id"}]}` — **آخرین 200 درخواست** (`id` نزولی). ناموجود ⇒ `404 {"error":"not found"}`.
- ⚠️ **ریسک داده‌ی کهنه:** وقتی بازدیدکننده‌ی تازه ساخته می‌شود، کش جزئیات‌اش با `request_count: 0` و `requests: []` پر می‌شود و **تا 24 ساعت یا تا پاک‌شدن namespace** همان می‌ماند (حتی اگر درخواست زیاد زده باشد). راه تازه‌سازی: `POST /api/cache/clear/tracking_admin` یا ذخیره‌ی تنظیمات ردیابی. فرانت می‌تواند دکمه‌ی «تازه‌سازی» داشته باشد که اول این را صدا بزند.

### 9.3 قالب‌ساز (`theme_builder`) — 🔒 ادمین

#### مفاهیم
- **تم** = پوشه‌ی زیر `templates/themes/` — الان `conspro`, `creek`, `construction` (فقط اولی و دومی طرح قابل‌ویرایش دارند؛ `construction` طرح ندارد ⇒ صفحه‌ی اصلی به `index.html` هسته برمی‌گردد).
- **صفحه** = `home` (جایگزین `/`) یا `product-detail` (جایگزین `/product/<slug>`، فعلاً فقط `conspro`).
- **طرح (design)** = فایل JSON زیر `designs/<theme>/<page>/` (نه DB). هر صفحه ممکن است چند طرح داشته باشد و یکی «فعال» است (`manifest.json`).
- رندر عمومی و پیش‌نمایش ادمین از **یک** خط لوله استفاده می‌کنند.

#### `GET /api/admin/site-theme/themes`
```json
{"ok": true, "themes": ["conspro","construction","creek"], "active": "conspro",
 "theme_pages": {"conspro": ["home","product-detail"], "construction": [], "creek": ["home"]},
 "page_labels": {"home": "ویرایش صفحه اصلی", "product-detail": "ویرایش صفحه محصول/پروژه"}}
```

#### `POST /api/admin/site-theme/activate`
بدنه `{"theme": "creek"}` ⇒ `{"ok": true, "active": "creek"}`. تم غایب/خالی ⇒ `"default"`. **وجود تم چک نمی‌شود.**

#### `GET /api/admin/site-theme/builder/<theme>/<page>` (bootstrap)
```json
{"ok": true, "catalog": [Widget, …], "design": Design, "designs": [{"id","name","updated_at"}], "needs_sample_product": false}
```
- ⚠️ **اثر جانبی:** اگر طرح فعالی نباشد، یک «طرح پیش‌فرض» (از `defaults` هر ویجت و ترتیب پیش‌فرض) **ساخته و ذخیره و فعال** می‌شود.
- `theme/page` نامعتبر ⇒ `404 {"ok": false, "error": "invalid theme/page"}`.
- `needs_sample_product` فقط برای `product-detail` درست است (پیش‌نمایش به یک محصول نمونه نیاز دارد).
- شیء Widget: `{"type","label","icon","dynamic","fields":[FieldSpec],"defaults":{…}}`. انواع فیلد: `text`, `textarea`, `image`, `url`, `number`, `select`(تعریف شده ولی در هیچ ویجتی استفاده نشده)، `repeater` (با `item_fields`). فهرست کامل: پیوست الف.

#### شیء Design
```json
{"id": "design-70eb8f301b", "theme": "conspro", "page": "home", "name": "طرح پیش‌فرض",
 "created_at": "2026-09-07 17:15:14", "updated_at": "2026-09-07 17:15:14",
 "rows": [{"id": "row-72fa132d", "boxes": [{"id": "box-02081c91", "widget": "header", "settings": {"logo": "assets/logo.png", "menu": [{"label":"خانه","url":"/"}]}}]}]}
```
- `created_at/updated_at` رشته‌ی میلادی `YYYY-MM-DD HH:MM:SS` (سرور).
- سرور تمام `boxes` را **پشت‌سرهم** رندر می‌کند؛ ساختار `rows/boxes` فقط برای ویرایشگر است.
- `settings` هر box **سطحی (shallow)** با `defaults` ویجت ترکیب می‌شود (`{...defaults, ...settings}`)؛ آرایه‌های repeater جایگزین کامل می‌شوند، نه ادغام.
- `widget` ناشناخته بی‌صدا نادیده گرفته می‌شود؛ `rows` اعتبارسنجی نمی‌شود (هر JSON پذیرفته می‌شود).

#### مسیرهای طرح‌ها (همه JSON)
| متد | مسیر | بدنه | پاسخ |
|---|---|---|---|
| GET | `/admin/site-theme/builder/<theme>/<page>/designs` | — | `{"designs":[{id,name,updated_at}] (جدیدترین اول), "active": id\|null}` |
| POST | `…/designs` | `{id?, name, rows, set_active?}` | `{"ok":true,"design":Design}`. بدون `id` ⇒ طرح جدید (`design-<10hex>`)؛ با `id` ⇒ بروزرسانی. `name` خالی ⇒ «طرح بدون‌نام». اولین طرح خودکار فعال می‌شود. `theme/page` نامعتبر ⇒ `400` |
| GET | `…/designs/<id>` | — | `{"ok":true,"design":Design}` یا `404 {"ok":false}` |
| POST | `…/designs/<id>/activate` | — | `{"ok":bool}` (**همیشه 200**، حتی اگر `false`) |
| POST | `…/designs/<id>/delete` | — | `{"ok":bool}`؛ اگر فعال را پاک کنید، اولین طرح باقی‌مانده فعال می‌شود |
| POST | `…/preview` | `{rows, sample_product_slug?}` | **HTML کامل صفحه** (نه JSON) برای `iframe srcdoc`. `sample_product_slug` برای `product-detail` |

- مسیرهای list/get/activate/delete، `theme/page` را در رجیستری **اعتبارسنجی نمی‌کنند** (و برای نام دلخواه پوشه می‌سازند).
- نکته‌ی نام‌گذاری: این طرح‌ها زیر `/admin/...` هستند ولی JSON می‌دهند، و فقط بوت‌استرپ و تم‌ها زیر `/api/admin/...`.
- حذف طرح، ذخیره، فعال‌سازی ⇒ رندر عمومی `/` و `/product/<slug>` فوراً تغییر می‌کند (کش ندارد).

#### ویجت‌های داینامیک (داده‌ی زنده از DB)
| ویجت (تم) | تنظیمات | منبع داده و قواعد دقیق |
|---|---|---|
| `projects` (conspro) / `projects_showcase` (creek) | `heading`, `category_slug`, `limit` | محصولات `published`، ترتیب `created_at DESC`. `limit`: عدد صحیح، **کلمپ به 1..50**، پیش‌فرض 8 (غیرعددی ⇒ 500). `category_slug` خالی ⇒ همه. مقدار پر ⇒ فقط محصولات **همان دسته‌ی دقیق** (فرزندان یک والد شامل **نمی‌شوند**)؛ slug ناموجود ⇒ نتیجه‌ی خالی. هر ردیف: `p.*` + `image_url` (اولین تصویر به‌ترتیب کمترین `id`) + `product_category_slug` + `product_category_name`. لیست دسته‌ها برای فیلتر: همه‌ی دسته‌های فعال/حذف‌نشده (هر دو سطح) به‌ترتیب نام |
| `related_projects` (conspro/product-detail) | `heading`, `limit` | `limit` 1..30 (پیش‌فرض 8). اول محصولات هم‌دسته (غیر از محصول جاری)، اگر خالی بود جدیدترین‌های دیگر |
| `product_main` | `placeholder_image` | از `page_context.product` (محصول جاری) |

#### `GET /theme-assets/<theme>/<path>` — بخش 4.4.

### 9.4 مدیریت زبان‌ها (`i18n`) — 🔒 ادمین، همه فرم/HTML

| مسیر | فیلدهای فرم | قواعد |
|---|---|---|
| `POST /admin/i18n/create` | `code`*, `name`*, `native_name`, `direction` (`ltr`/`rtl`), `flag`, `is_default` (چک‌باکس، مقدار `1`) | `code`: regex `^[a-z][a-z0-9_-]{1,7}$` (2–8 حرف، با حرف کوچک شروع). فایل `locales/<code>.json` (`{}`) ساخته می‌شود. `is_default` زبان پیش‌فرض قبلی را برمی‌دارد. ایجاد روی کد موجود، آن را **به‌روزرسانی** می‌کند و فعال می‌کند |
| `POST /admin/i18n/<code>/edit` | `name`, `native_name`, `direction`, `flag`, `is_active` (`1`), `is_default` (`1`) | ⚠️ چک‌باکس‌های غایب = `0` (ویرایش بدون `is_active` زبان را غیرفعال می‌کند) |
| `POST /admin/i18n/<code>/delete` | — | **`fa` قابل‌حذف نیست**. زبان و تمام ترجمه‌هایش پاک می‌شوند (فایل `.json` پاک نمی‌شود، پس پیشوند همچنان بریده می‌شود) |
| `POST /admin/i18n/<code>/translate` | `k_<translationKey>` برای هر کلید | مقدار خالی ⇒ ردیف ترجمه پاک می‌شود (برمی‌گردد به fallback). aliasها هم‌گام می‌شوند |
| `GET /admin/i18n/<code>/export` | — | دانلود `<code>.json` (دیکشنری ادغام‌شده) |
| `POST /admin/i18n/<code>/seed` | — | کپی همه‌ی رشته‌های فارسی به‌عنوان نقطه‌ی شروع (مقادیر موجود را بازنویسی نمی‌کند) |
| `POST /admin/i18n/default/fa` | — | فارسی را پیش‌فرض می‌کند (و ردیف `fa` را می‌سازد) |

---

## 10. فیلترها و محدودیت‌ها — جدول یک‌جا

| کجا | فیلتر / محدودیت |
|---|---|
| `GET /api/products` | بدون فیلتر · فقط `published` · `id DESC` · **حداکثر 100** · بدون pagination · کش `products:list` |
| `GET /api/products/<id>` | فقط id عددی · `published` وگرنه 404 · کش `products:id:<id>` |
| `GET /api/categories` | بدون پارامتر · فقط فعال+حذف‌نشده · درخت 2 سطحی · ریشه‌ی غیرفعال ⇒ فرزندان هم پنهان · بدون کش |
| `GET /api/categories/<slug>` | فعال+حذف‌نشده · فرزندان فعال مستقیم |
| `GET /api/i18n/languages` | فقط `is_active=1` · `is_default DESC, name` |
| `GET /api/i18n/translate/<code>` | هر کد ⇒ 200 · بدون fallback · کش 600ثانیه |
| پیشوند زبان | وجود `locales/<code>.json` · کد: `^[a-z][a-z0-9_-]{1,7}$` · `fa` بدون پیشوند |
| `GET /admin/products` | حداکثر 200 · همه‌ی status · `id DESC` |
| `GET /admin/images` | `folder, q, ext, date_from, date_to, size_min(MB), size_max(MB), recursive` |
| آپلود | سهمیه‌ی کل `ASSETS_DIR_Max_Size` (GB) · بدون سقف تک‌فایل · بدون فیلتر پسوند · همنام ⇒ `-1`,`-2` |
| `GET /api/admin/tracking/visitors` | فقط `page` · `per_page=50` ثابت · `last_seen DESC` |
| `GET /api/admin/tracking/visitor/<id>` | 200 درخواست آخر |
| `GET /api/admin/tracking/dashboard` | 10 کشور · 10 مرورگر · 50 درخواست اخیر |
| ویجت `projects`/`projects_showcase` | `limit` 1..50 |
| ویجت `related_projects` | `limit` 1..30 |
| کش | TTL حداقل 10ث (فرم) · حداکثر 5000 کلید |
| نام کاربری | ≤64 · یکتا؛ نقش ≤32 |
| `slug` محصول | ≤191 · یکتای DB · بدون slugify |
| `slug` دسته | ≤191 · یکتای برنامه‌ای (`-2`,`-3`) · خودکار از نام |
| قیمت‌ها | `DECIMAL(15,2)` (13 رقم صحیح) |
| `status` محصول | آزاد (≤20)؛ API عمومی فقط `published` |
| تصویر محصول | `url` ≤500 · `alt` ≤255 |

---

## 11. آنچه وجود ندارد (شکاف‌ها)

اگر فرانت به این‌ها نیاز دارد، **باید به صاحب پروژه گزارش شود**؛ در بک‌اند وجود ندارند:

| نیاز | وضعیت | راه‌حل موقت فرانت | پیشنهاد بک‌اند |
|---|---|---|---|
| **برند (Brand)** | هیچ جدول/route | — | پلاگین جدید `brands` |
| تنظیمات سایت (JSON) | ندارد | فقط داخل Jinja | `GET /api/settings/public` |
| فیلتر/جست‌وجو/مرتب‌سازی/pagination محصولات | ندارد | سمت کلاینت روی ≤100 | `?q&category&min_price&max_price&sort&page&per_page` |
| محصولات یک دسته | ندارد | `category_id` از لیست | `GET /api/categories/<slug>/products` |
| محصول با slug (JSON) | ندارد | `/api/products` و جستجوی slug | `GET /api/products/by-slug/<slug>` |
| لیست فایل‌های رسانه (JSON) | ندارد | فقط HTML | `GET /api/admin/images` |
| ورود/«من» JSON | ندارد | فرم + تشخیص redirect | `/api/auth/login`, `/api/auth/me` |
| CRUD محصول/دسته/کاربر/تنظیمات JSON | ندارد | فرم POST + redirect | JSON API با 401/403/422 |
| صفحات ثابت (`pages`) | جدول هست، route نیست | — | CRUD + API |
| ترجمه‌ی محتوای محصول/دسته | ندارد | — | ستون‌ها/جدول ترجمه |
| تعداد محصول هر دسته | ندارد | شمارش کلاینتی | فیلد `product_count` |
| ترتیب‌دهی تصاویر محصول | ندارد | — | `sort_order` قابل‌ویرایش |
| محدودیت واقعی نقش‌ها (RBAC) | ذخیره می‌شود، اعمال نمی‌شود | — | `AuthManager.can()` را به routeها وصل کنید |
| 401/403 JSON، CORS، CSRF | ندارد | proxy همان‌مبدأ | — |
| اعلان نتیجه‌ی POSTهای فرمی | فقط flash داخل HTML | بررسی بعد از reload | پاسخ JSON |

---

## 12. باگ‌ها و تله‌های شناسایی‌شده

(همه از روی خواندن کد/فایل‌ها؛ مورد 1 با نبودن فایل و لاگ‌ها تأیید شد، بقیه اجرا نشده‌اند.)

1. **`/product/<slug>` و `/category/<slug>` برای ناموجود ⇒ 500، نه 404.** هر دو `render_template("404.html")` را صدا می‌زنند ولی `templates/404.html` وجود ندارد ⇒ `TemplateNotFound`. فرانت نباید به 404 از این دو مسیر تکیه کند؛ از `/api/products/<id>` و `/api/categories/<slug>` (که 404 JSON درست می‌دهند) استفاده کند.
2. **ویرایش محصول جایگزینی کامل است** و `status` غایب = منتشر (بخش 7.1). ویرایش با slug تکراری بی‌صدا شکست می‌خورد ولی «ذخیره شد» می‌گوید.
3. **ویرایش دسته بدون `is_active` آن را غیرفعال می‌کند** (7.2). ویرایش زبان بدون `is_active` هم همین‌طور (9.4).
4. **محصول: `category_id`، `old_price`، `slug`، `schema_json` با ویرایش پاک‌نشدنی‌اند** (مقدار خالی نادیده گرفته می‌شود).
5. **پارامتر نامعتبر ⇒ 500** (نه 422): `page=abc` در ردیابی، `date_from/date_to` نامعتبر و `size_min/max` غیرعددی در رسانه، `stock`/`category_id`/`parent_id` غیرعددی در فرم‌ها، `limit` غیرعددی در تنظیمات ویجت. **قبل از ارسال، سمت کلاینت اعتبارسنجی کنید.**
6. **DB خراب ⇒ پاسخ «خالی» به‌جای خطا** (2.5).
7. **`/lang/<code>` بدون `next` ⇒ `/` فارسی** (4.3).
8. **`/api/i18n/translate/<code>` fallback ندارد** و ممکن است `fa` در `languages` نباشد (4.3).
9. **ردیابی:** `recent[].id` می‌تواند `null` باشد؛ جزئیات بازدیدکننده‌ی تازه تا 24ساعت ممکن است `requests: []` باشد؛ لیست بازدیدکنندگان کهنه می‌شود (9.2).
10. **جدول `images` آینه‌ی خراب** (ستون `base64_data` نیست) — از آن نخوانید. کش لیست رسانه بعد از آپلود/ساخت پوشه ممکن است تا 300ثانیه کهنه باشد (8.2).
11. **`description` محصول با `|safe` رندر می‌شود + مسیرهای ادمین باز** ⇒ ریسک XSS؛ همیشه sanitize کنید.
12. **کد زبان رزرو** (`api`, `admin`, …) سایت را می‌شکند (4.3).
13. **تنظیم `cache_ttl`** ذخیره می‌شود ولی هنگام boot خوانده نمی‌شود.
14. **ثبت `active_theme` با هر رشته‌ای** ممکن است (فرم `/admin/settings`)؛ تم ناموجود ⇒ برگشت به `index.html` هسته.
15. **`docs/api.md` در این موارد با کد اختلاف دارد:** `/theme-assets` کل پوشه‌ی تم را سرو می‌کند (نه فقط `assets/`)؛ `fa` ممکن است در `languages` نباشد؛ `/lang/<code>` بدون next به `/` می‌رود.
16. آدرس‌های `back` (رسانه) و `next` (`/lang`) اعتبارسنجی نمی‌شوند (open redirect).
17. **حساب ادمین پیش‌فرض** در اولین اجرا ساخته می‌شود؛ رمز آن را باید صاحب پروژه تغییر دهد (در این سند نیامده).

---

## 13. دستورالعمل‌های آماده (Recipes)

### 13.1 خواندن JSON با بررسی نوع پاسخ (ادمین)
```js
async function adminJson(url, init = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...init });
  const isJson = (res.headers.get('content-type') || '').includes('application/json');
  if (!isJson) throw Object.assign(new Error('not authenticated or not JSON'), { status: res.status, redirected: res.redirected });
  return res.json();
}
```

### 13.2 منوی دسته‌بندی + فیلتر محصولات
```js
const [{ categories }, { products }] = await Promise.all([
  fetch('/api/categories').then(r => r.json()),
  fetch('/api/products').then(r => r.json()),
]);
const idsFor = (cat) => new Set([cat.id, ...(cat.children || []).map(c => c.id)]);
const inCategory = (cat) => products.filter(p => idsFor(cat).has(p.category_id));
const price = (p) => Number(p.price);                       // قیمت رشته است
const onSale = (p) => p.old_price && Number(p.old_price) > price(p);
```

### 13.3 تصویر محصول
```js
const imgUrl = (u) => /^(https?:)?\//.test(u) ? u : '/' + u;   // نرمال‌سازی (8.5)
```

### 13.4 دیکشنری ترجمه با fallback
```js
async function loadI18n(code) {
  const [fa, target] = await Promise.all([
    fetch('/api/i18n/translate/fa').then(r => r.json()),
    code === 'fa' ? {} : fetch(`/api/i18n/translate/${code}`).then(r => r.json()),
  ]);
  return { ...fa, ...target };
}
```

### 13.5 سوییچر زبان
```js
const { languages, current } = await fetch('/api/i18n/languages').then(r => r.json());
if (!languages.some(l => l.code === 'fa')) languages.unshift({ code: 'fa', native_name: 'فارسی', direction: 'rtl' });
const hrefFor = (code, path = '/') => (code === 'fa' ? path : `/${code}${path}`);   // نه /lang/<code>
document.documentElement.dir = languages.find(l => l.code === current)?.direction ?? 'rtl';
```

### 13.6 آپلود تصویر و اتصال به محصول
```js
const fd = new FormData(); fd.append('files', file); fd.append('folder', 'products'); fd.append('ajax', '1');
const up = await fetch('/admin/images/upload', { method: 'POST', body: fd, credentials: 'same-origin' }).then(r => r.json());
if (!up.ok) throw new Error(up.error);
const url = up.uploaded[0].url;                        // "/assets/uploads/products/…"
await fetch(`/admin/products/${pid}/images/add`, {     // پاسخ 302 است؛ نتیجه را با GET مجدد بررسی کنید
  method: 'POST', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ url, alt: 'متن جایگزین' }),
});
```

### 13.7 ویرایش امن محصول (چون جایگزینی کامل است)
```js
// 1) مقدار فعلی را بخوان  2) فقط فیلد لازم را عوض کن  3) همه‌ی فیلدها را بفرست
const cur = await fetch(`/api/products/${pid}`).then(r => r.json());
const body = new URLSearchParams({
  name: cur.name, slug: cur.slug ?? '', sku: cur.sku ?? '', category_id: cur.category_id ?? '',
  stock: cur.stock, status: cur.status, price: cur.price, old_price: cur.old_price ?? '',
  description: cur.description ?? '', meta_title: cur.meta_title ?? '',
  meta_description: cur.meta_description ?? '', meta_keywords: cur.meta_keywords ?? '',
  schema_json: cur.schema_json ?? '',
});
// ... تغییر دلخواه روی body ...
await fetch(`/admin/products/${pid}/edit`, { method: 'POST', credentials: 'same-origin', body });
```
(توجه: محصول draft از `GET /api/products/<id>` برنمی‌گردد؛ برای ویرایش draft داده را از صفحه‌ی `/admin/products/<id>/edit` بگیرید یا JSON ادمین به بک‌اند اضافه شود.)

---

## 14. مدل داده (جدول‌ها)

> `SchemaManager` فقط `CREATE TABLE IF NOT EXISTS` و `ADD COLUMN` انجام می‌دهد؛ نوع ستون‌های موجود تغییر نمی‌کند. هیچ FK وجود ندارد؛ یکپارچگی برعهده‌ی برنامه است.

| جدول | ستون‌ها (نوع) |
|---|---|
| `users` | `id` PK، `username` VARCHAR(64) یکتا، `password_hash` VARCHAR(255)، `role` VARCHAR(32) پیش‌فرض `editor`، `is_hidden` TINYINT، `created_at` |
| `roles` | `id`، `name` VARCHAR(32) یکتا، `permissions` JSON |
| `settings` | `key` VARCHAR(64) PK، `value` TEXT |
| `pages` | `id`، `slug` VARCHAR(128) یکتا، `title`، `content` MEDIUMTEXT، `is_default`، `created_at` (**بدون route**) |
| `plugins` | `id`، `name` VARCHAR(64) یکتا، `enabled` TINYINT |
| `products` | `id`، `title` (قدیمی NOT NULL)، `name` VARCHAR(191) NOT NULL، `slug` VARCHAR(191) یکتا، `description` MEDIUMTEXT، `stock` INT، `old_price` DECIMAL(15,2) NULL، `price` DECIMAL(15,2)=0، `sku` VARCHAR(64)، `category_id` INT NULL، `status` VARCHAR(20)='published'، `meta_title` VARCHAR(191)، `meta_description` TEXT، `meta_keywords` VARCHAR(255)، `schema_json` LONGTEXT، `extra` JSON، `created_at` |
| `product_images` | `id`، `product_id` INT NOT NULL، `url` VARCHAR(500) NOT NULL، `alt` VARCHAR(255)، `sort_order` INT=0، `created_at` |
| `categories` | `id`، `title` (قدیمی)، `parent_id` INT NULL، `name` VARCHAR(191) NOT NULL، `slug` VARCHAR(191) (**یکتا فقط در برنامه**)، `description` TEXT، `meta_*`، `schema_json` LONGTEXT، `is_active` TINYINT=1، `is_deleted` TINYINT=0، `created_at` |
| `i18n_languages` | `id`، `code` VARCHAR(8) یکتا، `name` VARCHAR(64)، `native_name` VARCHAR(64)، `direction` VARCHAR(3)='ltr'، `flag` VARCHAR(8)، `is_default`، `is_active`=1، `created_at` |
| `i18n_translations` | `id`، `lang_code` VARCHAR(8)، `translation_key` VARCHAR(191)، `value` MEDIUMTEXT، `updated_at`؛ یکتا روی `(lang_code, translation_key)` |
| `images` | `id`، `rel_path` VARCHAR(500) یکتا، `file_name`، `folder`، `format`، `size_bytes`، `width`، `height`، `is_image`، `alt`، `url`، `status`، `created_at`، `updated_at` (**آینه‌ی خراب؛ نخوانید**) |
| `tracking_visitors` | `id`، `cookie_name`، `cookie_value`، `first_seen`/`last_seen` VARCHAR(32) **جلالی**، `user_id`، `first_ip_remote/forwarded/real`، `first_country` VARCHAR(8)، `request_count` |
| `tracking_requests` | `id`، `visitor_id`، `user_id`، `created_at` VARCHAR(32) **جلالی**، `origin`/`destination` VARCHAR(500)، `status_code`، `method`، `ip_remote/forwarded/real`، `country_code`، `country_name`، `city`، `user_agent` VARCHAR(500)، `browser_family`، `browser_version`، `device_type` |

فایل‌های غیر-DB: `designs/<theme>/<page>/{manifest.json, design-<id>.json}` (طرح‌ها)، `uploads/**` (رسانه)، `app/plugins/i18n/locales/<code>.json` (زبان‌ها)، `logs/<تاریخ>.log`.

متغیرهای `.env` (**مقادیرشان را هرگز چاپ/ثبت نکنید**): `DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_POOL_SIZE, SECRET_KEY, TEMPLATES_DIR, ASSETS_DIR, ASSETS_DIR_Max_Size, CACHE_TTL`.

---

## پیوست الف: کاتالوگ ویجت‌های قالب‌ساز

(تولیدشده خودکار از `WIDGET_REGISTRIES`/`EXTRA_PAGE_REGISTRIES` در `app/plugins/theme_builder/widgets.py`.)
قالب هر فیلد: `کلید:نوع`. نوع `repeater` آرایه‌ای از آیتم‌هاست که فیلدهای هر آیتم داخل `[ ]` آمده. فیلدهای `image` مقدار نسبی به تم (`assets/…`) یا URL مطلق/`/…` می‌گیرند.

### theme=`conspro` page=`home`

ترتیب پیش‌فرض (seed): `header` → `hero_slider` → `welcome_intro` → `services_showcase` → `counters` → `projects` → `process_steps` → `team` → `testimonials` → `news` → `sponsors_subscribe` → `footer`

| `type` | label | dynamic | فیلدهای settings (کلید:نوع) |
|---|---|---|---|
| `header` | هدر | — | `logo`:image; `phone`:text; `email`:text; `cta_text`:text; `cta_url`:url; `menu`:repeater[`label`:text, `url`:url] |
| `hero_slider` | اسلایدر قهرمان | — | `slides`:repeater[`image`:image, `title`:text, `subtitle`:textarea, `button_text`:text, `button_url`:url] |
| `welcome_intro` | معرفی / خوش‌آمدگویی | — | `title_line1`:text; `title_highlight`:text; `text`:textarea; `services`:repeater[`image`:image, `title`:text, `text`:textarea, `url`:url] |
| `services_showcase` | نمایش خدمات (تمام‌عرض) | — | `heading`:text; `bold_text`:text; `text`:textarea; `button_text`:text; `button_url`:url; `entries`:repeater[`icon_class`:text, `title`:text, `url`:url] |
| `counters` | شمارنده‌ها | — | `heading`:text; `text`:textarea; `entries`:repeater[`number`:number, `suffix`:text, `label`:text] |
| `projects` | پروژه‌ها (داینامیک) | ✅ | `heading`:text; `category_slug`:text; `limit`:number |
| `process_steps` | مراحل کار | — | `heading`:text; `entries`:repeater[`icon_class`:text, `title`:text, `text`:textarea] |
| `team` | اعضای تیم | — | `heading`:text; `members`:repeater[`image`:image, `name`:text, `role`:text, `text`:textarea, `facebook`:url, `twitter`:url, `linkedin`:url] |
| `testimonials` | نظرات مشتریان | — | `heading`:text; `entries`:repeater[`text`:textarea, `name`:text, `role`:text, `rating`:number] |
| `news` | اخبار | — | `heading`:text; `entries`:repeater[`image`:image, `date`:text, `title`:textarea, `text`:textarea, `url`:url] |
| `sponsors_subscribe` | اسپانسرها و فرم اشتراک | — | `logos`:repeater[`image`:image, `url`:url]; `subscribe_heading`:text; `subscribe_text`:textarea |
| `footer` | فوتر | — | `logo`:image; `text`:textarea; `facebook`:url; `twitter`:url; `linkedin`:url; `quick_links`:repeater[`label`:text, `url`:url]; `address`:textarea; `phone`:text; `email`:text; `hours`:text; `copyright_text`:text; `footer_nav`:repeater[`label`:text, `url`:url] |

### theme=`conspro` page=`product-detail`

ترتیب پیش‌فرض (seed): `header` → `page_title_banner` → `product_main` → `related_projects` → `sponsors_subscribe` → `footer`

| `type` | label | dynamic | فیلدهای settings (کلید:نوع) |
|---|---|---|---|
| `header` | هدر | — | `logo`:image; `phone`:text; `email`:text; `cta_text`:text; `cta_url`:url; `menu`:repeater[`label`:text, `url`:url] |
| `page_title_banner` | بنر عنوان صفحه | — | `bg_image`:image; `breadcrumb_home_label`:text; `breadcrumb_current_label`:text |
| `product_main` | محتوای اصلی محصول (داینامیک) | ✅ | `placeholder_image`:image |
| `related_projects` | پروژه‌های مرتبط (داینامیک) | ✅ | `heading`:text; `limit`:number |
| `sponsors_subscribe` | اسپانسرها و فرم اشتراک | — | `logos`:repeater[`image`:image, `url`:url]; `subscribe_heading`:text; `subscribe_text`:textarea |
| `footer` | فوتر | — | `logo`:image; `text`:textarea; `facebook`:url; `twitter`:url; `linkedin`:url; `quick_links`:repeater[`label`:text, `url`:url]; `address`:textarea; `phone`:text; `email`:text; `hours`:text; `copyright_text`:text; `footer_nav`:repeater[`label`:text, `url`:url] |

### theme=`creek` page=`home`

ترتیب پیش‌فرض (seed): `header` → `hero_slider` → `cta_banner` → `services_grid` → `about_history` → `running_projects` → `counters` → `projects_showcase` → `cta_quote` → `team` → `contact_form` → `news_posts` → `testimonials` → `clients_logos` → `footer`

| `type` | label | dynamic | فیلدهای settings (کلید:نوع) |
|---|---|---|---|
| `header` | هدر | — | `logo`:image; `address`:text; `phones`:repeater[`phone`:text]; `facebook`:url; `twitter`:url; `instagram`:url; `telegram`:url; `menu`:repeater[`label`:text, `url`:url] |
| `hero_slider` | اسلایدر قهرمان | — | `slides`:repeater[`image`:image, `title`:text, `subtitle`:textarea, `button_text`:text, `button_url`:url] |
| `cta_banner` | نوار فراخوان کوچک | — | `heading`:text; `button_text`:text; `button_url`:url |
| `services_grid` | شبکه خدمات | — | `heading`:text; `entries`:repeater[`icon_class`:text, `title`:text, `text`:textarea] |
| `about_history` | درباره ما / تاریخچه | — | `heading`:text; `text`:textarea; `bg_image`:image; `highlights`:repeater[`icon_class`:text, `title`:text, `text`:textarea]; `progress_entries`:repeater[`label`:text, `percent`:number] |
| `running_projects` | پروژه های در حال اجرا | — | `heading`:text; `entries`:repeater[`image`:image, `category`:text, `text`:textarea, `url`:url] |
| `counters` | شمارنده‌ها | — | `entries`:repeater[`icon_class`:text, `number`:number, `label`:text] |
| `projects_showcase` | پروژه‌های ما (داینامیک) | ✅ | `heading`:text; `category_slug`:text; `limit`:number |
| `cta_quote` | فراخوان با پس‌زمینه | — | `heading`:textarea; `bg_image`:image; `button_text`:text; `button_url`:url |
| `team` | مدیران اجرایی | — | `heading`:text; `members`:repeater[`image`:image, `name`:text, `role`:text, `text`:textarea] |
| `contact_form` | فرم تماس | — | `heading`:text; `bg_image`:image |
| `news_posts` | اخبار | — | `heading`:text; `entries`:repeater[`image`:image, `title`:textarea, `date`:text, `author`:text, `text`:textarea, `url`:url] |
| `testimonials` | نظرات مشتریان | — | `heading`:text; `bg_image`:image; `entries`:repeater[`image`:image, `text`:textarea, `name`:text] |
| `clients_logos` | لوگوی مشتریان | — | `heading`:text; `entries`:repeater[`image`:image, `url`:url] |
| `footer` | فوتر | — | `logo`:image; `text`:textarea; `quick_links`:repeater[`label`:text, `url`:url]; `address`:textarea; `phones`:repeater[`phone`:text]; `email`:text; `hours`:text; `map_embed_url`:url; `copyright_text`:text; `facebook`:url; `twitter`:url; `instagram`:url; `telegram`:url |

---

## پیوست ب: کلیدهای ترجمه

113 کلید در `fa.json` (و اتحاد با `DEFAULT_KEYS` در کد). گروه‌بندی بر اساس پیشوند:

- **action (15):** `activate, back, cancel, confirm, create, deactivate, delete, edit, logout, next, prev, purge, save, search, submit`
- **cache (12):** `active_keys, clear_all, col.actions, col.hit_rate, col.keys, col.namespace, confirm_clear_all, default_ttl, empty, icon_label, title, ttl_placeholder`
- **category (6):** `add, list.empty, list.title, parent, root, title`
- **dashboard (7):** `limited_access, plugins, roles, settings, themes, title, users`
- **error (2):** `404.body, 404.title`
- **flash (7):** `created, deleted, error, invalid_input, not_found, saved, unauthorized`
- **index (1):** `welcome`
- **login (4):** `password, submit, title, username`
- **nav (10):** `cache, categories, dashboard, home, images, languages, login, logout, products, tracking`
- **plugins (10):** `col.load, col.name, col.status, load.fail, load.ok, status.active, status.inactive, title, toggle.disable, toggle.enable`
- **product (11):** `add, category, detail.not_found, list.empty, list.title, price, sku, status.draft, status.published, stock, title`
- **roles (4):** `create_edit, name_ph, perms_legend, title`
- **settings (7):** `active_theme, default_pages, meta_description, meta_keywords, saved, site_title, title`
- **themes (3):** `activate, active_label, title`
- **tracking (3):** `dashboard, title, visitors`
- **users (11):** `col.date, col.id, col.role, col.username, create, create_new, delete, role.author, role.editor, role.manager, title`

(کلید کامل = `<گروه>.<نام>`؛ مثلاً `nav.home`، `product.status.published`.)
کلیدهای جدید را پلاگین‌ها می‌توانند با `Plugin.register_keys([...])` ثبت کنند؛ فایل `fa.json` را هم می‌توان مستقیم ویرایش کرد (حداکثر 60ثانیه بعد دیده می‌شود).
