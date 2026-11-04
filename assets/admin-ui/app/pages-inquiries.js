/* Inquiries: filterable list (+CSV export) and a detail page with status / internal note. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const B = '/api/admin/inquiries';
  const BADGE = { new: 'danger', in_progress: 'warning', answered: 'success', closed: 'secondary', spam: 'dark' };

  Admin.pages.inquiries = async function (root) {
    const f = { q: '', status: '', product_code: '', date_from: '', date_to: '', page: 1 };
    async function render() {
      const res = await api.get(B + api.qs(f), { full: true });
      const m = res.meta;
      root.innerHTML = `
        ${m.smtp ? '' : '<div class="alert alert-warning">ارسال ایمیل (SMTP) تنظیم نشده است؛ استعلام‌ها فقط ذخیره می‌شوند.</div>'}
        ${Admin.ui.card(`استعلام‌ها <span class="badge bg-label-danger ms-2">${m.new_count} جدید</span>`, `
          <div class="card-body border-bottom"><form id="flt" class="row g-2">
            <div class="col-md-3"><input class="form-control" name="q" placeholder="نام، ایمیل، موضوع، کد..." value="${esc(f.q)}"></div>
            <div class="col-md-2"><select class="form-select" name="status"><option value="">همهٔ وضعیت‌ها</option>${m.statuses.map((s) => `<option value="${s.value}" ${f.status === s.value ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}</select></div>
            <div class="col-md-2"><input class="form-control" name="product_code" placeholder="کد محصول" value="${esc(f.product_code)}" dir="ltr"></div>
            <div class="col-md-2"><input class="form-control js-d" type="text" name="date_from" placeholder="از تاریخ" value="${esc(Admin.dt.toJalali(f.date_from, false))}" data-time="0" dir="ltr" autocomplete="off"></div>
            <div class="col-md-2"><input class="form-control js-d" type="text" name="date_to" placeholder="تا تاریخ" value="${esc(Admin.dt.toJalali(f.date_to, false))}" data-time="0" dir="ltr" autocomplete="off"></div>
            <div class="col-md-1"><button class="btn btn-primary w-100"><i class="ti ti-search"></i></button></div></form></div>
          <div class="table-responsive"><table class="table table-hover"><thead><tr><th>کد</th><th>تاریخ</th><th>نام</th><th>موضوع</th><th>محصول</th><th>وضعیت</th><th></th></tr></thead><tbody>
          ${res.data.map((r) => `<tr><td dir="ltr" class="text-end">${esc(r.reference_code)}</td><td>${Admin.ui.fmtDate(r.created_at)}</td>
            <td>${esc(r.full_name)}<br><small class="text-muted" dir="ltr">${esc(r.email)}</small></td><td>${esc(r.subject || '—')}</td><td dir="ltr" class="text-end">${esc(r.product_code || '—')}</td>
            <td><span class="badge bg-label-${BADGE[r.status] || 'secondary'}">${esc((m.statuses.find((s) => s.value === r.status) || {}).label || r.status)}</span></td>
            <td><a class="btn btn-sm btn-text-secondary" href="/admin/inquiries/${r.id}">مشاهده</a></td></tr>`).join('') || '<tr><td colspan="7" class="text-center text-muted">موردی یافت نشد</td></tr>'}
          </tbody></table></div>
          <div class="card-footer d-flex justify-content-between align-items-center"><span class="text-muted">${m.total} مورد</span>
            <div class="btn-group"><button class="btn btn-sm btn-outline-secondary" id="prev" ${m.page <= 1 ? 'disabled' : ''}>قبلی</button>
            <span class="btn btn-sm disabled">${m.page} / ${m.total_pages || 1}</span>
            <button class="btn btn-sm btn-outline-secondary" id="next" ${m.page >= m.total_pages ? 'disabled' : ''}>بعدی</button></div></div>`,
          `<a class="btn btn-label-secondary" id="csv" href="${B}/export.csv${api.qs({ q: f.q, status: f.status, product_code: f.product_code, date_from: f.date_from, date_to: f.date_to })}"><i class="ti ti-download me-1"></i>خروجی CSV</a>`)}`;
      root.querySelectorAll('.js-d').forEach((el) => Admin.dt.init(el));
      root.querySelector('#flt').addEventListener('submit', (e) => {
        e.preventDefault();
        ['q', 'status', 'product_code'].forEach((k) => { f[k] = e.target[k].value.trim(); });
        ['date_from', 'date_to'].forEach((k) => { f[k] = Admin.dt.read(e.target[k]); });
        f.page = 1; render();
      });
      root.querySelector('#prev').addEventListener('click', () => { f.page--; render(); });
      root.querySelector('#next').addEventListener('click', () => { f.page++; render(); });
    }
    await render();
  };

  Admin.pages.inquiry = async function (root) {
    const id = location.pathname.split('/').filter(Boolean).pop();
    const d = await api.get(`${B}/${id}`);
    const r = d.inquiry;
    const row = (k, v, ltr) => `<dt class="col-sm-3">${k}</dt><dd class="col-sm-9"${ltr ? ' dir="ltr" style="text-align:right"' : ''}>${esc(v || '—')}</dd>`;
    root.innerHTML = `<div class="row"><div class="col-lg-8">${Admin.ui.card(`استعلام ${esc(r.reference_code)}`, `<div class="card-body"><dl class="row mb-0">
        ${row('نام', r.full_name)}${row('ایمیل', r.email, 1)}${row('تلفن', r.phone, 1)}${row('شرکت', r.company)}${row('موضوع', r.subject)}${row('کد محصول', r.product_code, 1)}
        ${row('زبان', r.locale, 1)}${row('تاریخ', r.created_at ? new Date(r.created_at).toLocaleString('fa-IR') : '')}
        <dt class="col-sm-3">پیام</dt><dd class="col-sm-9" style="white-space:pre-wrap">${esc(r.message)}</dd></dl></div>`,
      `<a class="btn btn-outline-secondary" href="/admin/inquiries">بازگشت</a>`)}</div>
      <div class="col-lg-4">${Admin.ui.card('پیگیری', `<div class="card-body"><form id="f">
        <div class="mb-3"><label class="form-label">وضعیت</label><select class="form-select" name="status">${d.statuses.map((s) => `<option value="${s.value}" ${r.status === s.value ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}</select></div>
        <div class="mb-3"><label class="form-label">یادداشت داخلی</label><textarea class="form-control" rows="5" name="internal_note">${esc(r.internal_note)}</textarea></div>
        <button class="btn btn-primary">ذخیره</button> <button type="button" class="btn btn-label-danger" id="del">حذف</button></form>
        ${r.handled_by ? `<small class="text-muted d-block mt-3">آخرین رسیدگی: ${esc(r.handled_by)}</small>` : ''}</div>`)}</div></div>`;
    root.querySelector('#f').addEventListener('submit', async (e) => {
      e.preventDefault();
      if (await safe(() => api.put(`${B}/${id}`, { status: e.target.status.value, internal_note: e.target.internal_note.value }))) toast.ok('ذخیره شد');
    });
    root.querySelector('#del').addEventListener('click', async () => {
      if (!(await Admin.confirm('این استعلام حذف شود؟'))) return;
      if (await safe(() => api.del(`${B}/${id}`))) { toast.ok('استعلام حذف شد'); location.href = '/admin/inquiries'; }
    });
  };
})();
