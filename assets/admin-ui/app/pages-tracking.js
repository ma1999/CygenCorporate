/* Visitor tracking: dashboard, visitors list, visitor detail, exclude-rule settings. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const B = '/api/admin/tracking';
  const dt = (s) => (s ? new Date(s).toLocaleString('fa-IR') : '—');
  const code = (v) => `<code class="small" dir="ltr">${esc(v || '-')}</code>`;
  const badge = (c) => `<span class="badge bg-${c >= 500 ? 'danger' : c >= 400 ? 'warning' : c >= 300 ? 'info' : 'success'}">${esc(c || 0)}</span>`;
  const list = (title, items, left, color) => Admin.ui.card(title, `<ul class="list-group list-group-flush">${(items || []).map((i) => `<li class="list-group-item d-flex justify-content-between"><span>${esc(left(i))}</span><strong class="text-${color}">${i.hits}</strong></li>`).join('') || '<li class="list-group-item text-muted">داده‌ای موجود نیست</li>'}</ul>`);
  const reqRow = (r, withMethod) => `<tr><td>${r.id}</td><td class="text-nowrap">${dt(r.created_at)}</td>${withMethod ? `<td>${esc(r.method || '')}</td>` : ''}
      <td><a href="${esc(r.destination || '#')}" target="_blank" dir="ltr">${esc((r.destination || '').slice(0, 60))}</a></td>${withMethod ? `<td class="small text-muted" dir="ltr">${esc((r.origin || '-').slice(0, 40))}</td>` : ''}
      <td>${badge(r.status_code)}</td><td>${code(r.ip_remote)}</td><td>${code(r.ip_forwarded)}</td><td>${code(r.ip_real)}</td>
      <td>${esc(r.country_name || '-')}${withMethod ? ' / ' + esc(r.city || '-') : ' (' + esc(r.country_code || '-') + ')'}</td><td>${esc((r.browser_family || '') + ' ' + (r.browser_version || ''))}</td><td>${esc(r.device_type || '')}</td><td>${r.user_id || '-'}</td>
      ${withMethod ? '' : `<td><a href="/admin/tracking/visitor/${r.visitor_id}">${esc(((r.cookie_value || '') + '…').slice(0, 9))}</a></td>`}</tr>`;

  Admin.pages.tracking_dashboard = async function (root) {
    const d = await api.get(B + '/dashboard');
    const stat = (t, v, icon) => `<div class="col-sm-4"><div class="card"><div class="card-body d-flex justify-content-between align-items-center"><div><span class="d-block mb-1">${t}</span><h3 class="mb-0">${v ?? 0}</h3></div><span class="badge bg-label-primary rounded p-2"><i class="ti ${icon} ti-sm"></i></span></div></div></div>`;
    root.innerHTML = `<div class="d-flex justify-content-between align-items-center mb-3"><h4 class="mb-0">آمار بازدیدها</h4>
        <div class="d-flex gap-2"><a class="btn btn-label-secondary" href="/admin/tracking/visitors">بازدیدکنندگان</a><a class="btn btn-label-secondary" href="/admin/tracking/settings">تنظیمات ردگیری</a></div></div>
      <div class="row g-4 mb-4">${stat('کل درخواست‌ها', d.total_requests, 'ti-arrows-exchange')}${stat('بازدیدکنندگان', d.total_visitors, 'ti-users')}${stat('IPهای یکتا', d.unique_ips, 'ti-world')}</div>
      <div class="row g-4 mb-4"><div class="col-md-4">${list('کشورها', d.by_country, (c) => `${c.country_name || '?'} (${c.country_code || '-'})`, 'primary')}</div>
        <div class="col-md-4">${list('دستگاه‌ها', d.by_device, (x) => x.device_type || '?', 'success')}</div>
        <div class="col-md-4">${list('مرورگرها', d.by_browser, (b) => b.browser_family || '?', 'warning')}</div></div>
      ${Admin.ui.card('آخرین درخواست‌ها', `<div class="table-responsive"><table class="table table-sm"><thead><tr><th>#</th><th>زمان</th><th>مقصد</th><th>وضعیت</th><th>IP Remote</th><th>IP XFF</th><th>IP X-Real</th><th>کشور</th><th>مرورگر</th><th>دستگاه</th><th>کاربر</th><th>کلید</th></tr></thead><tbody>
        ${(d.recent || []).map((r) => reqRow(r, false)).join('') || '<tr><td colspan="12" class="text-center text-muted">هنوز درخواستی ثبت نشده</td></tr>'}</tbody></table></div>`)}`;
  };

  Admin.pages.tracking_visitors = async function (root) {
    let page = parseInt(new URLSearchParams(location.search).get('page') || '1', 10) || 1;
    async function render() {
      const d = await api.get(B + '/visitors' + api.qs({ page }));
      const pages = Math.max(1, Math.ceil(d.total / d.per_page));
      root.innerHTML = Admin.ui.card(`بازدیدکنندگان (${d.total})`, `<div class="table-responsive"><table class="table table-hover"><thead><tr><th>#</th><th>کوکی</th><th>کاربر</th><th>درخواست‌ها</th><th>IP</th><th>کشور</th><th>اولین</th><th>آخرین</th><th></th></tr></thead><tbody>
        ${d.visitors.map((v) => `<tr><td>${v.id}</td><td>${code(v.cookie_name + ' = ' + (v.cookie_value || '').slice(0, 10) + '…')}</td><td>${v.user_id || '-'}</td><td>${v.request_count || 0}</td>
          <td>${code(v.first_ip_real || v.first_ip_forwarded || v.first_ip_remote)}</td><td>${esc(v.first_country || '-')}</td><td class="text-nowrap">${dt(v.first_seen)}</td><td class="text-nowrap">${dt(v.last_seen)}</td>
          <td><a class="btn btn-sm btn-primary" href="/admin/tracking/visitor/${v.id}">جزئیات</a></td></tr>`).join('') || '<tr><td colspan="9" class="text-center text-muted">بازدیدکننده‌ای ثبت نشده</td></tr>'}
        </tbody></table></div><div class="card-footer d-flex justify-content-between"><a class="btn btn-outline-secondary" href="/admin/tracking">بازگشت</a>
        <div class="btn-group"><button class="btn btn-sm btn-outline-secondary" id="prev" ${page <= 1 ? 'disabled' : ''}>قبلی</button><span class="btn btn-sm disabled">${page} / ${pages}</span><button class="btn btn-sm btn-outline-secondary" id="next" ${page >= pages ? 'disabled' : ''}>بعدی</button></div></div>`);
      root.querySelector('#prev').addEventListener('click', () => { page--; render(); });
      root.querySelector('#next').addEventListener('click', () => { page++; render(); });
    }
    await render();
  };

  Admin.pages.tracking_visitor = async function (root) {
    const vid = location.pathname.split('/').filter(Boolean).pop();
    const d = await api.get(`${B}/visitor/${vid}`);
    const v = d.visitor;
    const row = (k, val) => `<dt class="col-sm-3">${k}</dt><dd class="col-sm-9">${val}</dd>`;
    root.innerHTML = `<div class="d-flex justify-content-between align-items-center mb-3"><h4 class="mb-0">بازدیدکننده #${v.id}</h4><a class="btn btn-outline-secondary" href="/admin/tracking/visitors">بازگشت</a></div>
      ${Admin.ui.card('مشخصات', `<div class="card-body"><dl class="row mb-0">
        ${row('کوکی', code(v.cookie_name + ' = ' + v.cookie_value))}${row('کاربر لاگین', esc(v.user_id || '—'))}${row('تعداد درخواست', v.request_count || 0)}
        ${row('IPها', `${code(v.first_ip_remote)} ${code(v.first_ip_forwarded)} ${code(v.first_ip_real)}`)}${row('کشور اولیه', esc(v.first_country || '-'))}
        ${row('اولین بازدید', dt(v.first_seen))}${row('آخرین بازدید', dt(v.last_seen))}</dl></div>`)}
      ${Admin.ui.card('درخواست‌ها (۲۰۰ مورد آخر)', `<div class="table-responsive"><table class="table table-sm"><thead><tr><th>#</th><th>زمان</th><th>روش</th><th>مقصد</th><th>مبدأ</th><th>وضعیت</th><th>Remote</th><th>XFF</th><th>X-Real</th><th>کشور/شهر</th><th>مرورگر</th><th>دستگاه</th><th>کاربر</th></tr></thead><tbody>
        ${d.requests.map((r) => reqRow(r, true)).join('') || '<tr><td colspan="13" class="text-center text-muted">درخواستی نیست</td></tr>'}</tbody></table></div>`)}`;
  };

  Admin.pages.tracking_settings = async function (root) {
    const d = await api.get(B + '/settings');
    const c = d.current;
    root.innerHTML = Admin.ui.card('تنظیمات ردگیری (قواعد استثنا)', `<div class="card-body"><form id="f" novalidate>
      <div class="mb-3"><label class="form-label">مسیرها (path globs) — یک الگو در هر خط</label><textarea class="form-control" name="paths" rows="8" dir="ltr">${esc(c.paths)}</textarea></div>
      <div class="mb-3"><label class="form-label">روش‌های HTTP (یکی در هر خط)</label><textarea class="form-control" name="methods" rows="3" dir="ltr" placeholder="OPTIONS">${esc(c.methods)}</textarea><div class="form-text">خالی = همهٔ روش‌ها ردگیری می‌شوند.</div></div>
      <div class="mb-3"><label class="form-label">فیلتر کد وضعیت</label><select class="form-select" name="status"><option value="all" ${c.status === 'all' ? 'selected' : ''}>همه</option><option value="success" ${c.status === 'success' ? 'selected' : ''}>فقط موفق (2xx/3xx)</option><option value="errors" ${c.status === 'errors' ? 'selected' : ''}>فقط خطاها (4xx/5xx)</option></select></div>
      <div class="mb-3 form-check form-switch"><input class="form-check-input" type="checkbox" name="bots" id="bots" ${['1', 'on', 'true', 'yes'].includes(c.bots) ? 'checked' : ''}><label class="form-check-label" for="bots">نادیده گرفتن ربات‌ها</label></div>
      <div class="mb-3"><label class="form-label">الگوهای User-Agent (برای حذف)</label><textarea class="form-control" name="uas" rows="6" dir="ltr">${esc(c.uas)}</textarea></div>
      <button class="btn btn-primary">ذخیره</button> <a class="btn btn-outline-secondary" href="/admin/tracking">بازگشت</a></form></div>`);
    root.querySelector('#f').addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = e.target;
      if (await safe(() => api.put(B + '/settings', { paths: f.paths.value, methods: f.methods.value, status: f.status.value, bots: f.bots.checked, uas: f.uas.value }))) toast.ok('تنظیمات ردگیری ذخیره شد');
    });
  };
})();
