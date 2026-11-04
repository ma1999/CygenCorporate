"""Widget catalog for the theme builder.

Each theme that supports the page builder registers a dict of widget
definitions in ``WIDGET_REGISTRIES[theme_name]``. A widget definition:

    {
        "label": "...",            # shown in the admin palette
        "icon": "...",             # emoji shown in the admin palette
        "template": "plugins/theme_builder/widgets/conspro/xxx.html",
        "fields": [...],           # field-spec list, drives the generic settings form
        "defaults": {...},         # default settings (also the seed content)
        "dynamic": False,          # True => has a data_provider
        "data_provider": callable(db, settings) -> awaitable[dict] | None,
    }

Field-spec item:
    {"key": "title", "type": "text", "label": "عنوان"}
    {"key": "entries", "type": "repeater", "label": "موارد", "item_fields": [...]}

Field types: text, textarea, image, url, number, select (with "options").
"""
from __future__ import annotations

T_TEXT = "text"
T_TEXTAREA = "textarea"
T_IMAGE = "image"
T_URL = "url"
T_NUMBER = "number"
T_SELECT = "select"
T_REPEATER = "repeater"


async def _projects_data(db, settings, page_context=None):
    """Dynamic data provider for the 'projects' widget: reads live
    products/categories rows instead of static settings content."""
    limit = int(settings.get("limit") or 8)
    limit = max(1, min(limit, 50))
    category_slug = (settings.get("category_slug") or "").strip()

    categories = await db.query(
        "SELECT id, name, slug FROM categories "
        "WHERE is_active=1 AND is_deleted=0 ORDER BY name"
    ) or []

    base_sql = (
        "SELECT p.*, pi.url AS image_url, c.slug AS product_category_slug, "
        "c.name AS product_category_name FROM products p "
        "LEFT JOIN product_images pi ON pi.product_id = p.id "
        "AND pi.id = (SELECT MIN(id) FROM product_images WHERE product_id = p.id) "
        "LEFT JOIN categories c ON c.id = p.category_id "
        "WHERE p.status='published' "
    )
    if category_slug:
        cat_row = next((c for c in categories if c["slug"] == category_slug), None)
        params = (cat_row["id"], limit) if cat_row else (-1, limit)
        products = await db.query(
            base_sql + "AND p.category_id=%s ORDER BY p.created_at DESC LIMIT %s",
            params,
        ) or []
    else:
        products = await db.query(
            base_sql + "ORDER BY p.created_at DESC LIMIT %s",
            (limit,),
        ) or []

    return {"projects_categories": categories, "projects_products": products}


async def _related_projects_data(db, settings, page_context=None):
    """Dynamic data provider for 'related_projects' on a product-detail
    page: other published products, preferring the same category as the
    product currently being viewed (from page_context), excluding it."""
    page_context = page_context or {}
    current = page_context.get("product") or {}
    limit = int(settings.get("limit") or 8)
    limit = max(1, min(limit, 30))
    exclude_id = current.get("id") or -1
    category_id = current.get("category_id")

    base_sql = (
        "SELECT p.*, pi.url AS image_url FROM products p "
        "LEFT JOIN product_images pi ON pi.product_id = p.id "
        "AND pi.id = (SELECT MIN(id) FROM product_images WHERE product_id = p.id) "
        "WHERE p.status='published' AND p.id != %s "
    )
    if category_id:
        rows = await db.query(
            base_sql + "AND p.category_id=%s ORDER BY p.created_at DESC LIMIT %s",
            (exclude_id, category_id, limit),
        ) or []
    else:
        rows = []
    if not rows:
        rows = await db.query(
            base_sql + "ORDER BY p.created_at DESC LIMIT %s",
            (exclude_id, limit),
        ) or []
    return {"related_products": rows}


WIDGET_REGISTRIES = {
    "conspro": {
        "header": {
            "label": "هدر", "icon": "🧭", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/header.html",
            "fields": [
                {"key": "logo", "type": T_IMAGE, "label": "لوگو"},
                {"key": "phone", "type": T_TEXT, "label": "شماره تماس"},
                {"key": "email", "type": T_TEXT, "label": "ایمیل"},
                {"key": "cta_text", "type": T_TEXT, "label": "متن دکمه تماس"},
                {"key": "cta_url", "type": T_URL, "label": "لینک دکمه تماس"},
                {"key": "menu", "type": T_REPEATER, "label": "منو", "item_fields": [
                    {"key": "label", "type": T_TEXT, "label": "عنوان"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "logo": "assets/logo.png",
                "phone": "0912 345 67 89",
                "email": "conspro@mail.com",
                "cta_text": "ارتباط با ما",
                "cta_url": "#",
                "menu": [
                    {"label": "خانه", "url": "/"},
                    {"label": "درباره ما", "url": "#"},
                    {"label": "خدمات", "url": "#"},
                    {"label": "پروژه ها", "url": "#"},
                    {"label": "فروشگاه", "url": "#"},
                    {"label": "بلاگ", "url": "#"},
                    {"label": "تماس با ما", "url": "#"},
                ],
            },
        },
        "hero_slider": {
            "label": "اسلایدر قهرمان", "icon": "🖼️", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/hero_slider.html",
            "fields": [
                {"key": "slides", "type": T_REPEATER, "label": "اسلایدها", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "subtitle", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "button_text", "type": T_TEXT, "label": "متن دکمه"},
                    {"key": "button_url", "type": T_URL, "label": "لینک دکمه"},
                ]},
            ],
            "defaults": {
                "slides": [
                    {
                        "image": "assets/images/main-slider/image-1.jpg",
                        "title": "بهترین شرکت جهان در ساخت و ساز",
                        "subtitle": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده",
                        "button_text": "آشنایی بیشتر", "button_url": "#",
                    },
                    {
                        "image": "assets/images/main-slider/image-2.jpg",
                        "title": "بهترین شرکت جهان در ساخت و ساز",
                        "subtitle": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده",
                        "button_text": "آشنایی بیشتر", "button_url": "#",
                    },
                ],
            },
        },
        "welcome_intro": {
            "label": "معرفی / خوش‌آمدگویی", "icon": "👋", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/welcome_intro.html",
            "fields": [
                {"key": "title_line1", "type": T_TEXT, "label": "عنوان (خط اول)"},
                {"key": "title_highlight", "type": T_TEXT, "label": "عنوان (برجسته)"},
                {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                {"key": "services", "type": T_REPEATER, "label": "کارت‌های خدمات", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "title_line1": "به وب سایت ما",
                "title_highlight": "خوش آمدید",
                "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم است و برای شرایط فعلی تکنولوژی مورد نیاز و کاربردهای متنوع با هدف بهبود ابزارهای کاربردی",
                "services": [
                    {"image": "assets/services-1.jpg", "title": "طراحی و ساخت",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون", "url": "#"},
                    {"image": "assets/services-2.jpg", "title": "ساخت و ساز عمومی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون", "url": "#"},
                    {"image": "assets/services-3.jpg", "title": "کار تیمی عالی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون", "url": "#"},
                ],
            },
        },
        "services_showcase": {
            "label": "نمایش خدمات (تمام‌عرض)", "icon": "🛠️", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/services_showcase.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "bold_text", "type": T_TEXT, "label": "زیرعنوان پررنگ"},
                {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                {"key": "button_text", "type": T_TEXT, "label": "متن دکمه"},
                {"key": "button_url", "type": T_URL, "label": "لینک دکمه"},
                {"key": "entries", "type": T_REPEATER, "label": "آیتم‌ها", "item_fields": [
                    {"key": "icon_class", "type": T_TEXT, "label": "کلاس آیکون"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "heading": "آنچه ارائه می دهیم",
                "bold_text": "ما انواع خدمات ساخت و ساز را ارائه می دهیم.",
                "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون",
                "button_text": "مشاهده تمامی خدمات", "button_url": "#",
                "entries": [
                    {"icon_class": "flaticon-helmet-1", "title": "ساخت و ساز", "url": "#"},
                    {"icon_class": "flaticon-tool", "title": "جداسازی", "url": "#"},
                    {"icon_class": "flaticon-paint-bucket", "title": "نقاشی", "url": "#"},
                    {"icon_class": "flaticon-shovel-1", "title": "معماری", "url": "#"},
                    {"icon_class": "flaticon-tool", "title": "کف و رو سازی", "url": "#"},
                    {"icon_class": "flaticon-paint-bucket", "title": "نوسازی", "url": "#"},
                ],
            },
        },
        "counters": {
            "label": "شمارنده‌ها", "icon": "🔢", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/counters.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                {"key": "entries", "type": T_REPEATER, "label": "شمارنده‌ها", "item_fields": [
                    {"key": "number", "type": T_NUMBER, "label": "عدد"},
                    {"key": "suffix", "type": T_TEXT, "label": "پسوند (مثلاً +)"},
                    {"key": "label", "type": T_TEXT, "label": "برچسب"},
                ]},
            ],
            "defaults": {
                "heading": "شرکت ساخت و ساز با خدمات باکیفیت",
                "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان",
                "entries": [
                    {"number": 864, "suffix": "", "label": "مشتری راضی"},
                    {"number": 1236, "suffix": "", "label": "پروژه های اجرا شده"},
                    {"number": 2783, "suffix": "", "label": "کارگر ماهر"},
                    {"number": 57, "suffix": "+", "label": "برنده جایزه"},
                ],
            },
        },
        "projects": {
            "label": "پروژه‌ها (داینامیک)", "icon": "🏗️", "dynamic": True,
            "template": "plugins/theme_builder/widgets/conspro/projects.html",
            "data_provider": _projects_data,
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "category_slug", "type": T_TEXT, "label": "اسلاگ دسته‌بندی (خالی = همه)"},
                {"key": "limit", "type": T_NUMBER, "label": "تعداد"},
            ],
            "defaults": {"heading": "پروژه های اخیر", "category_slug": "", "limit": 8},
        },
        "process_steps": {
            "label": "مراحل کار", "icon": "🧩", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/process_steps.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "مراحل", "item_fields": [
                    {"key": "icon_class", "type": T_TEXT, "label": "کلاس آیکون"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                ]},
            ],
            "defaults": {
                "heading": "پروسه کاری ما",
                "entries": [
                    {"icon_class": "flaticon-light-bulb", "title": "ایجاد ایده جذاب",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده"},
                    {"icon_class": "flaticon-school-material", "title": "ایجاد طرح",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده"},
                    {"icon_class": "flaticon-roulette-with-button", "title": "پایان توسعه",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده"},
                ],
            },
        },
        "team": {
            "label": "اعضای تیم", "icon": "👥", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/team.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "members", "type": T_REPEATER, "label": "اعضا", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "name", "type": T_TEXT, "label": "نام"},
                    {"key": "role", "type": T_TEXT, "label": "سمت"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "facebook", "type": T_URL, "label": "فیسبوک"},
                    {"key": "twitter", "type": T_URL, "label": "توییتر"},
                    {"key": "linkedin", "type": T_URL, "label": "لینکدین"},
                ]},
            ],
            "defaults": {
                "heading": "اعضای ما",
                "members": [
                    {"image": "assets/team-1.jpg", "name": "تونی استارک", "role": "بنیان گذار",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و",
                     "facebook": "#", "twitter": "#", "linkedin": "#"},
                    {"image": "assets/team-2.jpg", "name": "استیو راجرز", "role": "بنیان گذار",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و",
                     "facebook": "#", "twitter": "#", "linkedin": "#"},
                    {"image": "assets/team-3.jpg", "name": "امیلیا کلارک", "role": "بنیان گذار",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و",
                     "facebook": "#", "twitter": "#", "linkedin": "#"},
                    {"image": "assets/team-4.jpg", "name": "جان اسنو", "role": "بنیان گذار",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و",
                     "facebook": "#", "twitter": "#", "linkedin": "#"},
                ],
            },
        },
        "testimonials": {
            "label": "نظرات مشتریان", "icon": "💬", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/testimonials.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "نظرات", "item_fields": [
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "name", "type": T_TEXT, "label": "نام"},
                    {"key": "role", "type": T_TEXT, "label": "سمت"},
                    {"key": "rating", "type": T_NUMBER, "label": "امتیاز (۱ تا ۵)"},
                ]},
            ],
            "defaults": {
                "heading": "مشتریان ما را دوست دارند!",
                "entries": [
                    {"text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم",
                     "name": "اولیور کوئین", "role": "طراح UI/UX ارشد", "rating": 5},
                    {"text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم",
                     "name": "اولیور کوئین", "role": "طراح UI/UX ارشد", "rating": 5},
                    {"text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم",
                     "name": "اولیور کوئین", "role": "طراح UI/UX ارشد", "rating": 5},
                ],
            },
        },
        "news": {
            "label": "اخبار", "icon": "📰", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/news.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "اخبار", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "date", "type": T_TEXT, "label": "تاریخ"},
                    {"key": "title", "type": T_TEXTAREA, "label": "عنوان"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "heading": "آخرین اخبار",
                "entries": [
                    {"image": "assets/news-1.jpg", "date": "24 آبان 1399",
                     "title": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان", "url": "#"},
                    {"image": "assets/news-2.jpg", "date": "24 آبان 1399",
                     "title": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان", "url": "#"},
                    {"image": "assets/news-3.jpg", "date": "24 آبان 1399",
                     "title": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان", "url": "#"},
                ],
            },
        },
        "sponsors_subscribe": {
            "label": "اسپانسرها و فرم اشتراک", "icon": "✉️", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/sponsors_subscribe.html",
            "fields": [
                {"key": "logos", "type": T_REPEATER, "label": "لوگوهای اسپانسر", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
                {"key": "subscribe_heading", "type": T_TEXT, "label": "عنوان اشتراک"},
                {"key": "subscribe_text", "type": T_TEXTAREA, "label": "متن اشتراک"},
            ],
            "defaults": {
                "logos": [
                    {"image": "assets/1.png", "url": "#"},
                    {"image": "assets/2.png", "url": "#"},
                    {"image": "assets/3.png", "url": "#"},
                    {"image": "assets/4.png", "url": "#"},
                    {"image": "assets/5.png", "url": "#"},
                ],
                "subscribe_heading": "مشترک شوید!",
                "subscribe_text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده",
            },
        },
        "footer": {
            "label": "فوتر", "icon": "🦶", "dynamic": False,
            "template": "plugins/theme_builder/widgets/conspro/footer.html",
            "fields": [
                {"key": "logo", "type": T_IMAGE, "label": "لوگو"},
                {"key": "text", "type": T_TEXTAREA, "label": "متن معرفی"},
                {"key": "facebook", "type": T_URL, "label": "فیسبوک"},
                {"key": "twitter", "type": T_URL, "label": "توییتر"},
                {"key": "linkedin", "type": T_URL, "label": "لینکدین"},
                {"key": "quick_links", "type": T_REPEATER, "label": "دسترسی سریع", "item_fields": [
                    {"key": "label", "type": T_TEXT, "label": "عنوان"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
                {"key": "address", "type": T_TEXTAREA, "label": "آدرس"},
                {"key": "phone", "type": T_TEXT, "label": "تلفن"},
                {"key": "email", "type": T_TEXT, "label": "ایمیل"},
                {"key": "hours", "type": T_TEXT, "label": "ساعات کاری"},
                {"key": "copyright_text", "type": T_TEXT, "label": "متن کپی‌رایت"},
                {"key": "footer_nav", "type": T_REPEATER, "label": "لینک‌های پایین فوتر", "item_fields": [
                    {"key": "label", "type": T_TEXT, "label": "عنوان"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "logo": "assets/footer-logo.png",
                "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله",
                "facebook": "#", "twitter": "#", "linkedin": "#",
                "quick_links": [
                    {"label": "خانه", "url": "/"},
                    {"label": "درباره ما", "url": "#"},
                    {"label": "خدمات", "url": "#"},
                    {"label": "فروشگاه", "url": "#"},
                    {"label": "بلاگ", "url": "#"},
                    {"label": "تماس", "url": "#"},
                ],
                "address": "تبریز، چهارراه آبرسان، فلکه دانشگاه، برج بلور، طبقه 456",
                "phone": "(880) 1723801729",
                "email": "consproinc@gmail.com",
                "hours": "9:00 ق.ظ - 5:00 ب.ظ جمعه تعطیل",
                "copyright_text": "کلیه حقوق این وب‌سایت محفوظ است.",
                "footer_nav": [
                    {"label": "دسترسی به وب میل", "url": "#"},
                    {"label": "قوانین و مقررات", "url": "#"},
                    {"label": "حریم شخصی", "url": "#"},
                ],
            },
        },
    },
    "creek": {
        "header": {
            "label": "هدر", "icon": "🧭", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/header.html",
            "fields": [
                {"key": "logo", "type": T_IMAGE, "label": "لوگو"},
                {"key": "address", "type": T_TEXT, "label": "آدرس"},
                {"key": "phones", "type": T_REPEATER, "label": "شماره‌های تماس", "item_fields": [
                    {"key": "phone", "type": T_TEXT, "label": "شماره"},
                ]},
                {"key": "facebook", "type": T_URL, "label": "فیسبوک"},
                {"key": "twitter", "type": T_URL, "label": "توییتر"},
                {"key": "instagram", "type": T_URL, "label": "اینستاگرام"},
                {"key": "telegram", "type": T_URL, "label": "تلگرام"},
                {"key": "menu", "type": T_REPEATER, "label": "منو", "item_fields": [
                    {"key": "label", "type": T_TEXT, "label": "عنوان"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "logo": "assets/logo-151x44.png",
                "address": "تبریز، خیابان ولیعصر، ساختمان گلستان، طبقه 576",
                "phones": [{"phone": "(800) 123-0045"}, {"phone": "(800) 123-0045"}],
                "facebook": "#", "twitter": "#", "instagram": "#", "telegram": "#",
                "menu": [
                    {"label": "خانه", "url": "/"},
                    {"label": "درباره ما", "url": "#"},
                    {"label": "خدمات", "url": "#"},
                    {"label": "پروژه ها", "url": "#"},
                    {"label": "بلاگ", "url": "#"},
                    {"label": "تماس", "url": "#"},
                ],
            },
        },
        "hero_slider": {
            "label": "اسلایدر قهرمان", "icon": "🖼️", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/hero_slider.html",
            "fields": [
                {"key": "slides", "type": T_REPEATER, "label": "اسلایدها", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "subtitle", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "button_text", "type": T_TEXT, "label": "متن دکمه"},
                    {"key": "button_url", "type": T_URL, "label": "لینک دکمه"},
                ]},
            ],
            "defaults": {
                "slides": [
                    {"image": "assets/images/slider-slide-1-1920x1080.jpg", "title": "از آغاز تا پایان",
                     "subtitle": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و",
                     "button_text": "مشاهده پروژه های اخیر", "button_url": "#"},
                    {"image": "assets/images/slider-slide-2-1920x1080.jpg", "title": "تخفیف های تابستانی",
                     "subtitle": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از",
                     "button_text": "مشاهده پروژه های اخیر", "button_url": "#"},
                    {"image": "assets/images/slider-slide-3-1920x1080.jpg", "title": "رویا از شما، ساختن با ما",
                     "subtitle": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده",
                     "button_text": "مشاهده پروژه های اخیر", "button_url": "#"},
                ],
            },
        },
        "cta_banner": {
            "label": "نوار فراخوان کوچک", "icon": "📣", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/cta_banner.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "متن"},
                {"key": "button_text", "type": T_TEXT, "label": "متن دکمه"},
                {"key": "button_url", "type": T_URL, "label": "لینک دکمه"},
            ],
            "defaults": {
                "heading": "خدمات سریع و مطمئن برای پروژه شما!",
                "button_text": "بیشتر بخوانید", "button_url": "#",
            },
        },
        "services_grid": {
            "label": "شبکه خدمات", "icon": "🛠️", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/services_grid.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "خدمات", "item_fields": [
                    {"key": "icon_class", "type": T_TEXT, "label": "کلاس آیکون"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                ]},
            ],
            "defaults": {
                "heading": "خدمات ما",
                "entries": [
                    {"icon_class": "linear-icon-pencil-ruler", "title": "خدمات پیش ساختی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"icon_class": "linear-icon-users", "title": "خدمات پیمانکاری",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"icon_class": "linear-icon-wall", "title": "خدمات ساخت و ساز",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"icon_class": "linear-icon-apartment", "title": "مدیریت ساخت و ساز",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"icon_class": "linear-icon-home4", "title": "طراحی سه بعدی ساختمان",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"icon_class": "linear-icon-pencil-ruler2", "title": "طراحی نقشه ساختمان",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                ],
            },
        },
        "about_history": {
            "label": "درباره ما / تاریخچه", "icon": "📜", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/about_history.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                {"key": "bg_image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
                {"key": "highlights", "type": T_REPEATER, "label": "نکات کلیدی", "item_fields": [
                    {"key": "icon_class", "type": T_TEXT, "label": "کلاس آیکون"},
                    {"key": "title", "type": T_TEXT, "label": "عنوان"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                ]},
                {"key": "progress_entries", "type": T_REPEATER, "label": "نوارهای پیشرفت", "item_fields": [
                    {"key": "label", "type": T_TEXT, "label": "برچسب"},
                    {"key": "percent", "type": T_NUMBER, "label": "درصد"},
                ]},
            ],
            "defaults": {
                "heading": "تاریخچه ما",
                "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم است",
                "bg_image": "assets/images/bg-image-1.jpg",
                "highlights": [
                    {"icon_class": "linear-icon-menu3", "title": "20 سال تجربه",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از"},
                    {"icon_class": "linear-icon-users2", "title": "تیم اختصاصی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان"},
                ],
                "progress_entries": [
                    {"label": "ساخت و ساز", "percent": 49},
                    {"label": "مدیریت پروژه", "percent": 29},
                    {"label": "مدلسازی سه بعدی", "percent": 86},
                ],
            },
        },
        "running_projects": {
            "label": "پروژه های در حال اجرا", "icon": "🚧", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/running_projects.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "پروژه‌ها", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "category", "type": T_TEXT, "label": "دسته"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "heading": "پروژه های در حال اجرا",
                "entries": [
                    {"image": "assets/project-1-652x491.jpg", "category": "سلامتی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است.", "url": "#"},
                    {"image": "assets/project-2-652x491.jpg", "category": "آموزشی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است.", "url": "#"},
                    {"image": "assets/project-3-652x491.jpg", "category": "تجاری",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است.", "url": "#"},
                ],
            },
        },
        "counters": {
            "label": "شمارنده‌ها", "icon": "🔢", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/counters.html",
            "fields": [
                {"key": "entries", "type": T_REPEATER, "label": "شمارنده‌ها", "item_fields": [
                    {"key": "icon_class", "type": T_TEXT, "label": "کلاس آیکون"},
                    {"key": "number", "type": T_NUMBER, "label": "عدد"},
                    {"key": "label", "type": T_TEXT, "label": "برچسب"},
                ]},
            ],
            "defaults": {
                "entries": [
                    {"icon_class": "linear-icon-coffee-cup", "number": 50, "label": "سال تجربه"},
                    {"icon_class": "linear-icon-cube", "number": 74, "label": "پروژه اجرا شده"},
                    {"icon_class": "linear-icon-chevrons-expand-horizontal", "number": 15, "label": "شرکای تجاری"},
                    {"icon_class": "linear-icon-mustache-glasses", "number": 147, "label": "مشتری راضی"},
                ],
            },
        },
        "projects_showcase": {
            "label": "پروژه‌های ما (داینامیک)", "icon": "🏗️", "dynamic": True,
            "template": "plugins/theme_builder/widgets/creek/projects_showcase.html",
            "data_provider": _projects_data,
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "category_slug", "type": T_TEXT, "label": "اسلاگ دسته‌بندی (خالی = همه)"},
                {"key": "limit", "type": T_NUMBER, "label": "تعداد"},
            ],
            "defaults": {"heading": "پروژه های ما", "category_slug": "", "limit": 8},
        },
        "cta_quote": {
            "label": "فراخوان با پس‌زمینه", "icon": "📢", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/cta_quote.html",
            "fields": [
                {"key": "heading", "type": T_TEXTAREA, "label": "عنوان"},
                {"key": "bg_image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
                {"key": "button_text", "type": T_TEXT, "label": "متن دکمه"},
                {"key": "button_url", "type": T_URL, "label": "لینک دکمه"},
            ],
            "defaults": {
                "heading": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم\nلورم ایپسوم متن ساختگی با تولید سادگی",
                "bg_image": "assets/images/bg-image-8.jpg",
                "button_text": "تماس با ما", "button_url": "#",
            },
        },
        "team": {
            "label": "مدیران اجرایی", "icon": "👥", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/team.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "members", "type": T_REPEATER, "label": "اعضا", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "name", "type": T_TEXT, "label": "نام"},
                    {"key": "role", "type": T_TEXT, "label": "سمت"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                ]},
            ],
            "defaults": {
                "heading": "مدیران اجرایی",
                "members": [
                    {"image": "assets/calvin-fitzerald-418x315.jpg", "name": "تونی استارک", "role": "رئیس",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"image": "assets/taylor-wilson-418x315.jpg", "name": "اولیور کوئین", "role": "مدیر اجرایی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                    {"image": "assets/josh-wagner-418x315.jpg", "name": "جان اسنو", "role": "مدیر طراحی",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است."},
                ],
            },
        },
        "contact_form": {
            "label": "فرم تماس", "icon": "✉️", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/contact_form.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "bg_image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
            ],
            "defaults": {"heading": "ارتباط با ما", "bg_image": "assets/images/bg-image-3.jpg"},
        },
        "news_posts": {
            "label": "اخبار", "icon": "📰", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/news_posts.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "اخبار", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "title", "type": T_TEXTAREA, "label": "عنوان"},
                    {"key": "date", "type": T_TEXT, "label": "تاریخ"},
                    {"key": "author", "type": T_TEXT, "label": "نویسنده"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "heading": "اخبار جدید",
                "entries": [
                    {"image": "assets/home-post-1-418x315.jpg", "title": "لورم ایپسوم متن ساختگی با",
                     "date": "20 شهریور 1398", "author": "جان اسنو",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است.", "url": "#"},
                    {"image": "assets/home-post-2-418x315.jpg", "title": "لورم ایپسوم متن ساختگی با",
                     "date": "20 شهریور 1398", "author": "جان اسنو",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است.", "url": "#"},
                    {"image": "assets/home-post-3-418x315.jpg", "title": "لورم ایپسوم متن ساختگی",
                     "date": "20 شهریور 1398", "author": "جان اسنو",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است.", "url": "#"},
                ],
            },
        },
        "testimonials": {
            "label": "نظرات مشتریان", "icon": "💬", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/testimonials.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "bg_image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
                {"key": "entries", "type": T_REPEATER, "label": "نظرات", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "text", "type": T_TEXTAREA, "label": "متن"},
                    {"key": "name", "type": T_TEXT, "label": "نام"},
                ]},
            ],
            "defaults": {
                "heading": "آنچه مردم می گویند",
                "bg_image": "assets/images/bg-image-2.jpg",
                "entries": [
                    {"image": "assets/benedict-arnold-120x120.jpg",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم است",
                     "name": "تونی استارک"},
                    {"image": "assets/deborah-quagmire-120x120.jpg",
                     "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم است",
                     "name": "جان اسنو"},
                ],
            },
        },
        "clients_logos": {
            "label": "لوگوی مشتریان", "icon": "🏢", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/clients_logos.html",
            "fields": [
                {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                {"key": "entries", "type": T_REPEATER, "label": "لوگوها", "item_fields": [
                    {"key": "image", "type": T_IMAGE, "label": "تصویر"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
            ],
            "defaults": {
                "heading": "مشتریان ما",
                "entries": [
                    {"image": "assets/company-1-126x102.png", "url": "#"},
                    {"image": "assets/company-2-134x102.png", "url": "#"},
                    {"image": "assets/company-3-132x102.png", "url": "#"},
                    {"image": "assets/company-4-126x102.png", "url": "#"},
                ],
            },
        },
        "footer": {
            "label": "فوتر", "icon": "🦶", "dynamic": False,
            "template": "plugins/theme_builder/widgets/creek/footer.html",
            "fields": [
                {"key": "logo", "type": T_IMAGE, "label": "لوگو"},
                {"key": "text", "type": T_TEXTAREA, "label": "متن معرفی"},
                {"key": "quick_links", "type": T_REPEATER, "label": "فهرست", "item_fields": [
                    {"key": "label", "type": T_TEXT, "label": "عنوان"},
                    {"key": "url", "type": T_URL, "label": "لینک"},
                ]},
                {"key": "address", "type": T_TEXTAREA, "label": "آدرس"},
                {"key": "phones", "type": T_REPEATER, "label": "تلفن‌ها", "item_fields": [
                    {"key": "phone", "type": T_TEXT, "label": "شماره"},
                ]},
                {"key": "email", "type": T_TEXT, "label": "ایمیل"},
                {"key": "hours", "type": T_TEXT, "label": "ساعات کاری"},
                {"key": "map_embed_url", "type": T_URL, "label": "لینک نقشه (اختیاری)"},
                {"key": "copyright_text", "type": T_TEXT, "label": "متن کپی‌رایت"},
                {"key": "facebook", "type": T_URL, "label": "فیسبوک"},
                {"key": "twitter", "type": T_URL, "label": "توییتر"},
                {"key": "instagram", "type": T_URL, "label": "اینستاگرام"},
                {"key": "telegram", "type": T_URL, "label": "تلگرام"},
            ],
            "defaults": {
                "logo": "assets/logo-inverse-151x44.png",
                "text": "لورم ایپسوم متن ساختگی با تولید سادگی نامفهوم از صنعت چاپ و با استفاده از طراحان گرافیک است. چاپگرها و متون بلکه روزنامه و مجله در ستون و سطرآنچنان که لازم است",
                "quick_links": [
                    {"label": "اخبار صنعت", "url": "#"},
                    {"label": "پروژه های در حال اجرا", "url": "#"},
                    {"label": "خدمات ما", "url": "#"},
                    {"label": "تماس", "url": "#"},
                ],
                "address": "تبریز، خیابان ولیعصر، جنب بانک ملت، ساختمان گلستان، طبقه 756",
                "phones": [{"phone": "(800) 123-0045"}, {"phone": "(800) 123-0045"}],
                "email": "info@sample.com",
                "hours": "شنبه تا پنج‌شنبه: 10 صبح الی 8 شب",
                "map_embed_url": "",
                "copyright_text": "کلیه حقوق این وب‌سایت محفوظ است.",
                "facebook": "#", "twitter": "#", "instagram": "#", "telegram": "#",
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Pages other than "home". Kept as a separate dict (rather than restructuring
# WIDGET_REGISTRIES[theme] into WIDGET_REGISTRIES[theme][page]) so the large,
# already-working "home" registries above don't need touching. Widgets that
# are identical across pages (header/footer/chrome) are literally reused —
# same dict object, same template — from the theme's home registry.
# ---------------------------------------------------------------------------
EXTRA_PAGE_REGISTRIES = {
    "conspro": {
        "product-detail": {
            "header": WIDGET_REGISTRIES["conspro"]["header"],
            "page_title_banner": {
                "label": "بنر عنوان صفحه", "icon": "🏷️", "dynamic": False,
                "template": "plugins/theme_builder/widgets/conspro/page_title_banner.html",
                "fields": [
                    {"key": "bg_image", "type": T_IMAGE, "label": "تصویر پس‌زمینه"},
                    {"key": "breadcrumb_home_label", "type": T_TEXT, "label": "برچسب خانه در بردکرامب"},
                    {"key": "breadcrumb_current_label", "type": T_TEXT, "label": "برچسب صفحه فعلی در بردکرامب"},
                ],
                "defaults": {
                    "bg_image": "assets/images/background/2.jpg",
                    "breadcrumb_home_label": "خانه",
                    "breadcrumb_current_label": "پروژه ها",
                },
            },
            "product_main": {
                "label": "محتوای اصلی محصول (داینامیک)", "icon": "📦", "dynamic": True,
                "template": "plugins/theme_builder/widgets/conspro/product_main.html",
                "fields": [
                    {"key": "placeholder_image", "type": T_IMAGE, "label": "تصویر پیش‌فرض (وقتی محصول عکس ندارد)"},
                ],
                "defaults": {"placeholder_image": "assets/project-single.jpg"},
            },
            "related_projects": {
                "label": "پروژه‌های مرتبط (داینامیک)", "icon": "🏗️", "dynamic": True,
                "template": "plugins/theme_builder/widgets/conspro/related_projects.html",
                "data_provider": _related_projects_data,
                "fields": [
                    {"key": "heading", "type": T_TEXT, "label": "عنوان"},
                    {"key": "limit", "type": T_NUMBER, "label": "تعداد"},
                ],
                "defaults": {"heading": "پروژه های مرتبط", "limit": 8},
            },
            "sponsors_subscribe": WIDGET_REGISTRIES["conspro"]["sponsors_subscribe"],
            "footer": WIDGET_REGISTRIES["conspro"]["footer"],
        },
    },
}

# Order the factory-default design is seeded in for a given theme/page.
DEFAULT_ROW_ORDER = {
    "conspro": [
        "header", "hero_slider", "welcome_intro", "services_showcase",
        "counters", "projects", "process_steps", "team", "testimonials",
        "news", "sponsors_subscribe", "footer",
    ],
    "creek": [
        "header", "hero_slider", "cta_banner", "services_grid", "about_history",
        "running_projects", "counters", "projects_showcase", "cta_quote",
        "team", "contact_form", "news_posts", "testimonials", "clients_logos",
        "footer",
    ],
}

EXTRA_ROW_ORDER = {
    "conspro": {
        "product-detail": [
            "header", "page_title_banner", "product_main", "related_projects",
            "sponsors_subscribe", "footer",
        ],
    },
}


def get_registry(theme: str, page: str = "home") -> dict:
    if page == "home":
        return WIDGET_REGISTRIES.get(theme, {})
    return EXTRA_PAGE_REGISTRIES.get(theme, {}).get(page, {})


def default_row_order(theme: str, page: str = "home") -> list:
    if page == "home":
        return DEFAULT_ROW_ORDER.get(theme, [])
    return EXTRA_ROW_ORDER.get(theme, {}).get(page, [])


def pages_for_theme(theme: str) -> list:
    """Every page this theme has a widget catalog for, 'home' first."""
    pages = ["home"] if theme in WIDGET_REGISTRIES else []
    pages += list(EXTRA_PAGE_REGISTRIES.get(theme, {}).keys())
    return pages


def widget_catalog_json(theme: str, page: str = "home") -> list:
    """Palette data for the admin builder UI: label/icon/fields/defaults
    per widget type, in a JSON-serializable shape (no callables)."""
    out = []
    for key, wdef in get_registry(theme, page).items():
        out.append({
            "type": key,
            "label": wdef["label"],
            "icon": wdef["icon"],
            "dynamic": bool(wdef.get("dynamic")),
            "fields": wdef["fields"],
            "defaults": wdef["defaults"],
        })
    return out
