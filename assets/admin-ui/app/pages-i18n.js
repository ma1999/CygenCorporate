/* i18n admin: languages list, create/edit form, translation editor, JSON import. Sub-page is derived from the URL. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const B = '/api/admin/i18n';

  Admin.pages.i18n = async function (root) {
    const seg = location.pathname.replace(/\/+$/, '').split('/').filter(Boolean).slice(2); // after admin/i18n
    if (!seg.length) return list(root);
    if (seg[0] === 'create') return form(root, null);
    if (seg[1] === 'edit') return form(root, seg[0]);
    if (seg[1] === 'translate') return translate(root, seg[0]);
    if (seg[1] === 'import') return importer(root, seg[0]);
    throw new Error('صفحه یافت نشد');
  };

  async function list(root) {
    async function render() {
      const d = await api.get(B);
      root.innerHTML = Admin.ui.card(`زبان‌ها <small class="text-muted">(${d.total_keys} کلید ترجمه)</small>`, `<div class="table-responsive"><table class="table align-middle">
        <thead><tr><th>زبان</th><th>کد</th><th>جهت</th><th>ترجمه‌ها</th><th>وضعیت</th><th></th></tr></thead><tbody>
        ${d.languages.map((l) => { const pct = d.total_keys ? Math.min(100, Math.round(((d.stats[l.code] || 0) / d.total_keys) * 100)) : 0; return `<tr>
          <td>${esc(l.flag || '')} ${esc(l.native_name || l.name)} <small class="text-muted">${esc(l.name)}</small> ${l.is_default ? '<span class="badge bg-label-primary">پیش‌فرض</span>' : ''}</td>
          <td dir="ltr" class="text-end">${esc(l.code)}</td><td>${l.direction}</td>
          <td style="min-width:140px"><div class="progress mb-1"><div class="progress-bar" style="width:${pct}%"></div></div><small>${d.stats[l.code] || 0} / ${d.total_keys}</small></td>
          <td><span class="badge bg-label-${l.is_active ? 'success' : 'secondary'}">${l.is_active ? 'فعال' : 'غیرفعال'}</span></td>
          <td class="text-nowrap"><a class="btn btn-sm btn-label-primary" href="/admin/i18n/${esc(l.code)}/translate">ترجمه</a>
            <a class="btn btn-sm btn-icon btn-text-secondary" href="/admin/i18n/${esc(l.code)}/edit" title="ویرایش"><i class="ti ti-edit"></i></a>
            <a class="btn btn-sm btn-icon btn-text-secondary" href="/admin/i18n/${esc(l.code)}/import" title="ورود از JSON"><i class="ti ti-file-import"></i></a>
            <a class="btn btn-sm btn-icon btn-text-secondary" href="${B}/${esc(l.code)}/export" title="خروجی JSON"><i class="ti ti-download"></i></a>
            ${l.code !== d.source_lang ? `<button class="btn btn-sm btn-icon btn-text-secondary seed" data-c="${esc(l.code)}" title="کپی کلیدها از مبدأ"><i class="ti ti-copy"></i></button>
            <button class="btn btn-sm btn-icon btn-text-danger del" data-c="${esc(l.code)}" data-n="${esc(l.name)}" title="حذف"><i class="ti ti-trash"></i></button>` : ''}</td></tr>`; }).join('') || '<tr><td colspan="6" class="text-center text-muted">زبانی ثبت نشده</td></tr>'}
        </tbody></table></div>`, `<div class="d-flex gap-2"><button class="btn btn-label-secondary" id="def-fa">فارسی = پیش‌فرض</button><a class="btn btn-primary" href="/admin/i18n/create"><i class="ti ti-plus me-1"></i>زبان جدید</a></div>`);
      root.querySelector('#def-fa').addEventListener('click', async () => { if (await safe(() => api.post(B + '/default/fa'))) { toast.ok('فارسی به‌عنوان زبان پیش‌فرض تنظیم شد'); render(); } });
      root.querySelectorAll('.del').forEach((b) => b.addEventListener('click', async () => {
        if (!(await Admin.confirm(`زبان «${b.dataset.n}» و همهٔ ترجمه‌هایش حذف شود؟`))) return;
        if (await safe(() => api.del(`${B}/${b.dataset.c}`))) { toast.ok('زبان حذف شد'); render(); }
      }));
      root.querySelectorAll('.seed').forEach((b) => b.addEventListener('click', async () => {
        if (!(await Admin.confirm('همهٔ کلیدهای زبان مبدأ (بدون بازنویسی موجودها) به این زبان کپی شوند؟', { icon: 'question', ok: 'کپی شود' }))) return;
        const r = await safe(() => api.post(`${B}/${b.dataset.c}/seed`));
        if (r) { toast.ok(`${r.copied} کلید کپی شد`); render(); }
      }));
    }
    await render();
  }

  async function form(root, code) {
    const l = code ? await api.get(`${B}/${code}`) : { code: '', name: '', native_name: '', direction: 'ltr', flag: '', is_default: false, is_active: true };
    root.innerHTML = Admin.ui.card(code ? `ویرایش زبان ${esc(l.name)}` : 'زبان جدید', `<div class="card-body"><form id="f" novalidate><div class="row">
      <div class="col-md-4 mb-3"><label class="form-label">کد زبان</label><input class="form-control" name="code" dir="ltr" value="${esc(l.code)}" ${code ? 'disabled' : ''} placeholder="en"><div class="field-error text-danger small" data-err="code" hidden></div></div>
      <div class="col-md-4 mb-3"><label class="form-label">نام (انگلیسی)</label><input class="form-control" name="name" dir="ltr" value="${esc(l.name)}"><div class="field-error text-danger small" data-err="name" hidden></div></div>
      <div class="col-md-4 mb-3"><label class="form-label">نام بومی</label><input class="form-control" name="native_name" value="${esc(l.native_name)}"></div>
      <div class="col-md-4 mb-3"><label class="form-label">جهت</label><select class="form-select" name="direction"><option value="ltr" ${l.direction === 'ltr' ? 'selected' : ''}>چپ‌به‌راست</option><option value="rtl" ${l.direction === 'rtl' ? 'selected' : ''}>راست‌به‌چپ</option></select></div>
      <div class="col-md-4 mb-3"><label class="form-label">پرچم (ایموجی)</label><input class="form-control" name="flag" value="${esc(l.flag || '')}"></div>
      <div class="col-md-4 mb-3 pt-4"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="is_default" id="d" ${l.is_default ? 'checked' : ''}><label class="form-check-label" for="d">پیش‌فرض</label></div>
        ${code ? `<div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="is_active" id="a" ${l.is_active ? 'checked' : ''}><label class="form-check-label" for="a">فعال</label></div>` : ''}</div>
      </div><button class="btn btn-primary">ذخیره</button> <a class="btn btn-outline-secondary" href="/admin/i18n">بازگشت</a></form></div>`);
    const f = root.querySelector('#f');
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      Admin.ui.fieldErrors(f, {});
      const data = { code: f.code.value.trim(), name: f.name.value.trim(), native_name: f.native_name.value.trim(), direction: f.direction.value, flag: f.flag.value.trim(), is_default: f.is_default.checked };
      if (code) data.is_active = f.is_active.checked;
      try {
        await (code ? api.put(`${B}/${code}`, data) : api.post(B, data));
        toast.ok('زبان ذخیره شد'); location.href = '/admin/i18n';
      } catch (ex) { if (ex.fields) Admin.ui.fieldErrors(f, ex.fields); toast.err(ex.message); }
    });
  }

  async function translate(root, code) {
    const prefix = new URLSearchParams(location.search).get('prefix') || '';
    const d = await api.get(`${B}/${code}/translate${api.qs({ prefix })}`);
    const dirty = {};
    let q = '';
    const PER = 80;
    let pageNo = 1;
    const filtered = () => d.keys.filter((k) => !q || k.key.toLowerCase().includes(q) || (k.source || '').toLowerCase().includes(q) || (k.value || '').toLowerCase().includes(q));
    const grouped = () => {
      const g = {};
      filtered().slice((pageNo - 1) * PER, pageNo * PER).forEach((k) => (g[k.group] = g[k.group] || []).push(k));
      return g;
    };
    function body() {
      const g = grouped();
      return Object.keys(g).map((grp) => `<div class="card mb-3"><div class="card-header"><h6 class="mb-0" dir="ltr">${esc(grp)}</h6></div><div class="table-responsive"><table class="table table-sm align-middle mb-0"><tbody>
        ${g[grp].map((k) => `<tr><td style="width:28%" dir="ltr" class="text-end small text-muted">${esc(k.key)}</td><td style="width:32%" class="small">${esc(k.source)}</td>
        <td><textarea class="form-control form-control-sm tr" rows="1" data-k="${esc(k.key)}" dir="${d.lang.direction}" ${d.is_source ? '' : ''}>${esc(dirty[k.key] !== undefined ? dirty[k.key] : k.value)}</textarea></td></tr>`).join('')}
        </tbody></table></div></div>`).join('') || '<p class="text-center text-muted">موردی یافت نشد</p>';
    }
    root.innerHTML = `<div class="d-flex flex-wrap gap-2 justify-content-between align-items-center mb-3">
        <h4 class="mb-0">ترجمه به ${esc(d.lang.native_name || d.lang.name)}</h4>
        <div class="d-flex gap-2"><select class="form-select" id="pfx" style="width:auto"><option value="">همهٔ کلیدها</option>${d.prefixes.map((p) => `<option ${p === d.prefix ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select>
          <input class="form-control" id="q" placeholder="جستجو..." style="width:200px"><a class="btn btn-outline-secondary" href="/admin/i18n">بازگشت</a></div></div>
      <div id="rows"></div><div id="pager" class="d-flex justify-content-center align-items-center gap-2 mb-3"></div>
      <div class="form-sticky-actions d-flex gap-2"><button class="btn btn-primary" id="save"><i class="ti ti-device-floppy me-1"></i>ذخیره ترجمه‌ها</button><span class="align-self-center text-muted small" id="cnt"></span></div>`;
    const rows = root.querySelector('#rows');
    const paint = () => {
      rows.innerHTML = body();
      const pages = Math.max(1, Math.ceil(filtered().length / PER));
      pageNo = Math.min(pageNo, pages);
      root.querySelector('#pager').innerHTML = `<button class="btn btn-sm btn-outline-secondary" data-pg="-1" ${pageNo <= 1 ? 'disabled' : ''}>قبلی</button><span class="small text-muted">صفحه ${pageNo} از ${pages} · ${filtered().length} کلید</span><button class="btn btn-sm btn-outline-secondary" data-pg="1" ${pageNo >= pages ? 'disabled' : ''}>بعدی</button>`;
    };
    root.querySelector('#pager').addEventListener('click', (e) => {
      const b = e.target.closest('[data-pg]'); if (!b) return;
      pageNo += parseInt(b.dataset.pg, 10); paint(); window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    paint();
    rows.addEventListener('input', (e) => {
      const t = e.target.closest('.tr'); if (!t) return;
      dirty[t.dataset.k] = t.value;
      window.onbeforeunload = () => true;
      root.querySelector('#cnt').textContent = `${Object.keys(dirty).length} تغییر ذخیره‌نشده`;
    });
    let timer;
    root.querySelector('#q').addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { q = e.target.value.trim().toLowerCase(); pageNo = 1; paint(); }, 250); });
    root.querySelector('#pfx').addEventListener('change', (e) => { location.search = e.target.value ? '?prefix=' + encodeURIComponent(e.target.value) : ''; });
    root.querySelector('#save').addEventListener('click', async () => {
      if (!Object.keys(dirty).length) return toast.warn('تغییری برای ذخیره نیست');
      const r = await safe(() => api.put(`${B}/${code}/translate`, { prefix: d.prefix, values: dirty }));
      if (r) { window.onbeforeunload = null; toast.ok(`${r.saved} ترجمه ذخیره شد`); setTimeout(() => location.reload(), 600); }
    });
  }

  async function importer(root, code) {
    const lang = await api.get(`${B}/${code}`);
    root.innerHTML = Admin.ui.card(`ورود ترجمه از JSON — ${esc(lang.native_name || lang.name)}`, `<div class="card-body"><form id="f" novalidate>
      <div class="mb-3"><label class="form-label">فایل JSON (تو در تو، حداکثر ۲ مگابایت)</label><input class="form-control" type="file" name="file" accept=".json,application/json"><div class="field-error text-danger small" data-err="file" hidden></div></div>
      <div class="mb-3"><label class="form-label">پیشوند کلیدها</label><input class="form-control" name="prefix" value="web." dir="ltr"></div>
      <div class="mb-3"><label class="form-label">حالت</label><select class="form-select" name="mode"><option value="missing">فقط کلیدهای جدید</option><option value="overwrite">بازنویسی موجودها</option></select></div>
      <div class="mb-3 form-check"><input class="form-check-input" type="checkbox" name="confirm_overwrite" id="co" value="1"><label class="form-check-label" for="co">بازنویسی ترجمه‌های موجود را تأیید می‌کنم</label><div class="field-error text-danger small" data-err="confirm_overwrite" hidden></div></div>
      <button class="btn btn-primary">ورود</button> <a class="btn btn-outline-secondary" href="/admin/i18n">بازگشت</a></form></div>`);
    const f = root.querySelector('#f');
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      Admin.ui.fieldErrors(f, {});
      try {
        const r = await api.post(`${B}/${code}/import`, new FormData(f));
        toast.ok(`وارد شد: ${r.added} جدید، ${r.updated} به‌روز، ${r.skipped} ردشده${r.ignored ? `، ${r.ignored} نادیده` : ''}`);
        setTimeout(() => { location.href = `/admin/i18n/${code}/translate?prefix=${encodeURIComponent(r.prefix || '')}`; }, 900);
      } catch (ex) { if (ex.fields) Admin.ui.fieldErrors(f, ex.fields); toast.err(ex.message); }
    });
  }
})();
