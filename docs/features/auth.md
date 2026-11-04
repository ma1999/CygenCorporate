# Feature: Authentication, users & roles

## Relevant files

- `app/core/auth.py` — `AuthManager`, password hashing
- `app/core/decorators.py` — `login_required`, `admin_required`
- `app/core/routes.py` — `/login`, `/logout`, `/admin/users`, `/admin/roles`
- `main.py` — `resetpass` CLI command

## Responsibilities

Session-based login for a small, flat user model: every user has exactly
one `role` string, and the only role the app currently checks for anything
is the literal string `"administrator"`.

## Data flow

1. `POST /login` → `AuthManager.login(username, password)` looks up the
   user by username, verifies the password, and on success calls
   `session.clear()` then sets `session["uid"]`, `session["username"]`,
   `session["role"]`.
2. `AuthManager.current_user()` / `is_admin()` / `logout()` are `staticmethod`s
   that read/clear the Flask `session` — there is no server-side session
   store beyond Flask's signed cookie (`SECRET_KEY` from `.env`).
3. `login_required` / `admin_required` (in `decorators.py`) wrap async view
   functions; on failure they flash a message and redirect to `core.login`
   or `core.dashboard`, using `i18n`'s `url_for_lang` if that plugin is
   loaded so the redirect preserves the current language prefix.
4. On every boot, `AuthManager.ensure_admin()` inserts a hidden
   (`is_hidden=1`) `administrator` user (`admin` / `admin123`) if no
   administrator row exists yet.

## Important rules

- **Password hashing uses a single hard-coded salt** shared by every user
  (`hashlib.pbkdf2_hmac("sha256", password, <constant salt>, 100_000)` in
  `hash_password`). This is a real weakness (all users share one salt, so a
  precomputed table targeting that salt would work across the whole user
  base) — noted here for awareness, not silently patched, since changing
  the hashing scheme would invalidate every existing password hash in the
  database.
- **The `roles`/`permissions` system is not enforced.** `/admin/roles`
  lets an admin create a named role with a `permissions` JSON blob, and
  `AuthManager.can(permission)` exists to check
  `session.get("permissions", {}).get(permission)` — but nothing in
  `login()` ever populates `session["permissions"]`, and no route anywhere
  calls `.can()`. In practice there are exactly two effective access
  levels: `administrator` (passes `admin_required`) and everyone else
  (blocked by `admin_required`, allowed by `login_required`). Don't assume
  creating a "roles" row grants any actual permission.
- The hidden admin account (`is_hidden=1`) is excluded from
  `/admin/users`'s listing (`WHERE is_hidden=0`) and from deletion
  (`admin_users_delete` won't delete a `role='administrator'` row anyway).
- `main.py resetpass <username>` is the only way to reset a password
  without going through the (session-based) admin UI — useful when locked
  out.

## Dependencies

- `flask.session` (cookie-based, signed with `SECRET_KEY`).
- `app/core/decorators.py` soft-depends on the `i18n` plugin for
  language-preserving redirects (degrades to plain `url_for` if `i18n`
  isn't present).

## Things that must not break

- `ensure_admin()` must keep running on every boot — it's the only
  guaranteed way to get a first admin account into a fresh database.
- `session.clear()` on login must stay in place — it prevents session
  fixation / stale role data from a previous login persisting across users
  on a shared browser.
- Many plugins' `/admin/*` routes do **not** use `admin_required` at all
  (see [api.md](../api.md) and the plugin-specific docs) — don't assume
  every admin-looking route in this codebase actually checks
  `current_user`/`is_admin()`.


## Update: previously open admin routes are now gated

`/admin/products*`, `/admin/categories*`, `/admin/images*` (+ `/admin/media/browse`), `/admin/cache*`,
`POST /api/cache/clear/<ns>` and `GET /api/cache/stats` now use `@admin_required` (anonymous ⇒ 302 to `/login`).
All new admin routes (site settings, brands, projects, articles, services, FAQ, company, inquiries, documents,
revalidate, i18n import) are `@admin_required` too. Public read endpoints (`/api/products*`, `/api/categories*`,
`/api/i18n/*`, `/assets/uploads/*`, `/api/public/*`) remain open. `tests/test_api.py::AuthOnAdminRoutes` pins this.
