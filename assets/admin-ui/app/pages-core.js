/* Core panel pages: dashboard, settings, users, roles, themes, plugins. Each renders into #page-app from /api/admin/*. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const B = '/api/admin';
  const root = document.getElementById('page-app');
  if (!root) return;

  const card = (title, body, actions) => `<div class="card mb-4"><div class="card-header d-flex justify-content-between align-items-center"><h5 class="card-title mb-0">${title}</h5>${actions || ''}</div>${body}</div>`;
  const fmtDate = (s) => (s ? new Date(s).toLocaleString('fa-IR') : '—');
  const fieldErrors = (form, fields) => {
    form.querySelectorAll('.field-error').forEach((e) => { e.hidden = true; });
    Object.keys(fields || {}).forEach((k) => {
      const e = form.querySelector(`[data-err="${k}"]`);
      if (e) { e.textContent = fields[k]; e.hidden = false; }
    });
  };

  // shared UI helpers for page modules
  Admin.ui = { card, fmtDate, fieldErrors };
  Admin.pages = Admin.pages || {};
  const pages = {
    async dashboard() {
      const d = await api.get(B + '/dashboard');
      const links = d.menu.filter((m) => m.key !== 'dashboard');
      root.innerHTML = `
        <div class="row g-4 mb-4">${d.stats.map((s) => `
          <div class="col-sm-6 col-xl-3"><a href="${esc(s.url)}" class="card h-100 text-decoration-none"><div class="card-body d-flex justify-content-between align-items-center">
            <div><span class="text-heading d-block mb-1">${esc(s.title)}</span><h3 class="mb-0">${s.count}</h3></div>
            <span class="badge bg-label-primary rounded p-2"><i class="ti ${esc(s.icon)} ti-sm"></i></span></div></a></div>`).join('')}</div>
        ${card('دسترسی سریع', `<div class="card-body"><div class="row g-3">${links.map((m) => `
          <div class="col-6 col-md-4 col-xl-3"><a class="btn btn-label-secondary w-100 text-start" href="${esc(m.url)}"><i class="ti ${esc(m.icon)} me-2"></i>${esc(m.title)}</a></div>`).join('')}</div></div>`)}`;
    },

    async settings() {
      const s = await api.get(B + '/settings');
      const f = (k, label, type) => `<div class="col-md-6 mb-3"><label class="form-label">${label}</label>${type === 'ta' ? `<textarea class="form-control" name="${k}" rows="3">${esc(s[k])}</textarea>` : `<input class="form-control" name="${k}" value="${esc(s[k])}">`}</div>`;
      root.innerHTML = card('تنظیمات پایه', `<div class="card-body"><form id="f" novalidate><div class="row">
        ${f('site_title', 'عنوان سایت')}${f('active_theme', 'قالب فعال (قدیمی)')}${f('meta_description', 'توضیحات متا', 'ta')}${f('meta_keywords', 'کلمات کلیدی', 'ta')}${f('default_pages', 'صفحات پیش‌فرض (با ویرگول)')}
        </div><button class="btn btn-primary">ذخیره</button></form></div>`);
      root.querySelector('#f').addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        if (await safe(() => api.put(B + '/settings', data))) toast.ok('تنظیمات ذخیره شد');
      });
    },

    async users() {
      async function render() {
        const users = await api.get(B + '/users');
        root.innerHTML = `<div class="row"><div class="col-lg-8">${card('کاربران', `<div class="table-responsive"><table class="table"><thead><tr><th>#</th><th>نام کاربری</th><th>نقش</th><th>تاریخ ایجاد</th><th></th></tr></thead><tbody>
          ${users.map((u) => `<tr><td>${u.id}</td><td dir="ltr" class="text-end">${esc(u.username)}</td><td>${esc(u.role)}</td><td>${fmtDate(u.created_at)}</td>
          <td>${u.role !== 'administrator' ? `<button class="btn btn-sm btn-icon btn-text-danger del" data-id="${u.id}" data-name="${esc(u.username)}"><i class="ti ti-trash"></i></button>` : ''}</td></tr>`).join('') || '<tr><td colspan="5" class="text-center text-muted">کاربری وجود ندارد</td></tr>'}
          </tbody></table></div>`)}</div>
          <div class="col-lg-4">${card('کاربر جدید', `<div class="card-body"><form id="f" novalidate>
            <div class="mb-3"><label class="form-label">نام کاربری</label><input class="form-control" name="username" dir="ltr"><div class="field-error text-danger small" data-err="username" hidden></div></div>
            <div class="mb-3"><label class="form-label">رمز عبور</label><input class="form-control" type="password" name="password" dir="ltr"><div class="field-error text-danger small" data-err="password" hidden></div></div>
            <div class="mb-3"><label class="form-label">نقش</label><input class="form-control" name="role" value="editor" dir="ltr"></div>
            <button class="btn btn-primary">ایجاد</button></form></div>`)}</div></div>`;
        root.querySelector('#f').addEventListener('submit', async (e) => {
          e.preventDefault();
          fieldErrors(e.target, {});
          try {
            await api.post(B + '/users', Object.fromEntries(new FormData(e.target).entries()));
            toast.ok('کاربر ایجاد شد'); render();
          } catch (ex) { if (ex.fields) fieldErrors(e.target, ex.fields); toast.err(ex.message); }
        });
        root.querySelectorAll('.del').forEach((b) => b.addEventListener('click', async () => {
          if (!(await Admin.confirm(`کاربر «${b.dataset.name}» حذف شود؟`))) return;
          if (await safe(() => api.del(`${B}/users/${b.dataset.id}`))) { toast.ok('کاربر حذف شد'); render(); }
        }));
      }
      await render();
    },

    async roles() {
      async function render() {
        const d = await api.get(B + '/roles');
        const sec = d.sections;
        const row = (r) => `<tr><td>${esc(r.name)}</td><td>${sec.map((s) => `<span class="badge bg-label-${r.permissions[s] ? 'success' : 'secondary'} me-1">${esc(s)}</span>`).join('')}</td></tr>`;
        root.innerHTML = `<div class="row"><div class="col-lg-7">${card('نقش‌ها', `<div class="table-responsive"><table class="table"><thead><tr><th>نقش</th><th>دسترسی‌ها</th></tr></thead><tbody>${d.roles.map(row).join('') || '<tr><td colspan="2" class="text-center text-muted">نقشی تعریف نشده</td></tr>'}</tbody></table></div>
          <div class="card-footer text-muted small">توجه: مسیرهای ادمین فقط با نقش administrator باز می‌شوند؛ جدول نقش‌ها فعلاً در دسترس‌پذیری اعمال نمی‌شود.</div>`)}</div>
          <div class="col-lg-5">${card('ذخیره نقش', `<div class="card-body"><form id="f" novalidate>
            <div class="mb-3"><label class="form-label">نام نقش</label><input class="form-control" name="name" dir="ltr"><div class="field-error text-danger small" data-err="name" hidden></div></div>
            <div class="mb-3">${sec.map((s) => `<div class="form-check"><input class="form-check-input" type="checkbox" id="p_${s}" data-perm="${s}"><label class="form-check-label" for="p_${s}">${esc(s)}</label></div>`).join('')}</div>
            <button class="btn btn-primary">ذخیره</button></form></div>`)}</div></div>`;
        root.querySelector('#f').addEventListener('submit', async (e) => {
          e.preventDefault();
          fieldErrors(e.target, {});
          const permissions = {};
          e.target.querySelectorAll('[data-perm]').forEach((c) => { if (c.checked) permissions[c.dataset.perm] = true; });
          try { await api.put(B + '/roles', { name: e.target.name.value, permissions }); toast.ok('نقش ذخیره شد'); render(); }
          catch (ex) { if (ex.fields) fieldErrors(e.target, ex.fields); toast.err(ex.message); }
        });
      }
      await render();
    },

    async themes() {
      async function render() {
        const d = await api.get(B + '/themes');
        root.innerHTML = card('قالب‌های سایت (سیستم قدیمی)', `<div class="card-body"><div class="row g-3">${d.themes.map((t) => `
          <div class="col-md-4"><div class="card border ${t === d.active ? 'border-primary' : ''}"><div class="card-body d-flex justify-content-between align-items-center">
            <span dir="ltr">${esc(t)}</span>${t === d.active ? '<span class="badge bg-label-success">فعال</span>' : `<button class="btn btn-sm btn-primary act" data-t="${esc(t)}">فعال‌سازی</button>`}</div></div></div>`).join('') || '<p class="text-muted">قالبی یافت نشد</p>'}</div></div>`);
        root.querySelectorAll('.act').forEach((b) => b.addEventListener('click', async () => {
          if (await safe(() => api.post(B + '/themes/activate', { theme: b.dataset.t }))) { toast.ok('قالب فعال شد'); render(); }
        }));
      }
      await render();
    },

    async plugins() {
      async function render() {
        const list = await api.get(B + '/plugins');
        root.innerHTML = card('افزونه‌ها', `<div class="table-responsive"><table class="table"><thead><tr><th>نام</th><th>وضعیت</th><th>بارگذاری</th><th></th></tr></thead><tbody>${list.map((p) => `
          <tr><td dir="ltr" class="text-end">${esc(p.name)}</td><td><span class="badge bg-label-${p.enabled ? 'success' : 'secondary'}">${p.enabled ? 'فعال' : 'غیرفعال'}</span></td>
          <td>${p.loaded ? 'موفق' : 'ناموفق'}${p.needs_restart ? ' <span class="badge bg-label-warning">ثبت مسیرها ناموفق بود؛ لاگ سرور را ببینید</span>' : ''}</td><td><button class="btn btn-sm btn-${p.enabled ? 'label-danger' : 'label-success'} tg" data-n="${esc(p.name)}" data-e="${p.enabled ? 0 : 1}">${p.enabled ? 'غیرفعال‌سازی' : 'فعال‌سازی'}</button></td></tr>`).join('')}</tbody></table></div>
          <div class="card-footer text-muted small">فعال و غیرفعال‌سازی بلافاصله و بدون راه‌اندازی مجدد اعمال می‌شود (صفحه‌ها، API، منو و داشبورد).</div>`);
        root.querySelectorAll('.tg').forEach((b) => b.addEventListener('click', async () => {
          if (await safe(() => api.post(B + '/plugins/toggle', { name: b.dataset.n, enabled: b.dataset.e === '1' }))) { toast.ok('وضعیت افزونه تغییر کرد'); render(); }
        }));
      }
      await render();
    },
  };

  Object.assign(Admin.pages, pages);
})();
