/* System pages: cache, revalidate (frontend link), frontend visits report. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;

  Admin.pages.cache = async function (root) {
    async function render() {
      const d = await api.get('/api/admin/cache');
      root.innerHTML = `<div class="row"><div class="col-lg-8">${Admin.ui.card(`کش (${d.total_keys} کلید)`, `<div class="table-responsive"><table class="table"><thead><tr><th>Namespace</th><th>کلیدها</th><th>Hit</th><th>Miss</th><th>نرخ Hit</th><th></th></tr></thead><tbody>
        ${d.stats.map((s) => `<tr><td dir="ltr" class="text-end">${esc(s.namespace)}</td><td>${s.key_count}</td><td>${s.hits}</td><td>${s.misses}</td><td>${s.hit_rate}%</td>
          <td><button class="btn btn-sm btn-label-danger clr" data-ns="${esc(s.namespace)}">پاک‌سازی</button></td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-muted">آماری ثبت نشده</td></tr>'}
        </tbody></table></div>`, '<button class="btn btn-danger" id="clr-all"><i class="ti ti-trash me-1"></i>پاک‌سازی کل کش</button>')}</div>
        <div class="col-lg-4">${Admin.ui.card('TTL پیش‌فرض', `<div class="card-body"><form id="ttl"><label class="form-label">ثانیه (حداقل ۱۰)</label>
          <input class="form-control mb-3" type="number" name="ttl" min="10" value="${d.ttl}" dir="ltr"><button class="btn btn-primary">ذخیره</button></form></div>`)}</div></div>`;
      root.querySelectorAll('.clr').forEach((b) => b.addEventListener('click', async () => {
        if (await safe(() => api.post(`/api/admin/cache/clear/${encodeURIComponent(b.dataset.ns)}`))) { toast.ok(`کش «${b.dataset.ns}» پاک شد`); render(); }
      }));
      root.querySelector('#clr-all').addEventListener('click', async () => {
        if (!(await Admin.confirm('کل کش پاک شود؟'))) return;
        if (await safe(() => api.post('/api/admin/cache/clear'))) { toast.ok('کل کش پاک شد'); render(); }
      });
      root.querySelector('#ttl').addEventListener('submit', async (e) => {
        e.preventDefault();
        if (await safe(() => api.put('/api/admin/cache/ttl', { ttl: e.target.ttl.value }))) toast.ok('TTL ذخیره شد');
      });
    }
    await render();
  };

  Admin.pages.revalidate = async function (root) {
    async function render() {
      const d = await api.get('/api/admin/revalidate');
      const yes = (v) => `<span class="badge bg-label-${v ? 'success' : 'danger'}">${v ? 'بله' : 'خیر'}</span>`;
      root.innerHTML = Admin.ui.card('اتصال به فرانت‌اند (Revalidate)', `<div class="card-body"><dl class="row">
        <dt class="col-sm-3">فعال</dt><dd class="col-sm-9">${yes(d.enabled)}</dd>
        <dt class="col-sm-3">آدرس تنظیم شده</dt><dd class="col-sm-9">${yes(d.has_url)} <span dir="ltr">${esc(d.host)}</span></dd>
        <dt class="col-sm-3">Secret تنظیم شده</dt><dd class="col-sm-9">${yes(d.has_secret)}</dd>
        <dt class="col-sm-3">CORS مجاز</dt><dd class="col-sm-9" dir="ltr" style="text-align:right">${d.cors.map(esc).join('<br>') || '—'}</dd>
        <dt class="col-sm-3">Base URL</dt><dd class="col-sm-9" dir="ltr" style="text-align:right">${esc(d.base_url)}</dd>
        <dt class="col-sm-3">آخرین ارسال</dt><dd class="col-sm-9"><pre class="mb-0" dir="ltr">${d.last ? esc(JSON.stringify(d.last, null, 2)) : '—'}</pre></dd></dl>
        <p class="text-muted small">مقادیر از .env خوانده می‌شوند (FRONTEND_REVALIDATE_URL / SECRET، CORS_ALLOWED_ORIGINS، PUBLIC_BASE_URL).</p>
        <button class="btn btn-primary" id="flush"><i class="ti ti-refresh me-1"></i>پاک‌سازی کش فرانت</button></div>`);
      root.querySelector('#flush').addEventListener('click', async () => {
        const r = await safe(() => api.post('/api/admin/revalidate/flush'));
        if (r) { (r.frontend ? toast.ok : toast.warn)(r.message); render(); }
      });
    }
    await render();
  };

  Admin.pages.visits = async function (root) {
    let days = 14;
    async function render() {
      const d = await api.get('/api/admin/frontend-visits?days=' + days);
      const maxV = Math.max(1, ...d.daily.map((x) => x.views));
      root.innerHTML = `${d.enabled ? '' : '<div class="alert alert-warning">ثبت بازدید فرانت غیرفعال است.</div>'}
        <div class="row g-4 mb-4"><div class="col-sm-4"><div class="card"><div class="card-body"><span class="d-block mb-1">بازدید ${days} روز اخیر</span><h3 class="mb-0">${d.totals.views}</h3></div></div></div>
        <div class="col-sm-4"><div class="card"><div class="card-body"><span class="d-block mb-1">بازدیدکنندهٔ یکتا</span><h3 class="mb-0">${d.totals.visitors}</h3></div></div></div>
        <div class="col-sm-4"><div class="card"><div class="card-body"><label class="form-label">بازه (روز)</label><select class="form-select" id="days">${[7, 14, 30, 90].map((n) => `<option ${n === days ? 'selected' : ''}>${n}</option>`).join('')}</select><small class="text-muted">نگهداری: ${d.retention} روز</small></div></div></div></div>
        <div class="row"><div class="col-lg-6">${Admin.ui.card('روزانه', `<div class="table-responsive"><table class="table table-sm"><thead><tr><th>روز</th><th>بازدید</th><th>یکتا</th><th style="width:40%"></th></tr></thead><tbody>
          ${d.daily.map((x) => `<tr><td dir="ltr">${esc(String(x.d).slice(0, 10))}</td><td>${x.views}</td><td>${x.visitors}</td><td><div class="progress"><div class="progress-bar" style="width:${Math.round((x.views / maxV) * 100)}%"></div></div></td></tr>`).join('') || '<tr><td colspan="4" class="text-center text-muted">داده‌ای نیست</td></tr>'}</tbody></table></div>`)}</div>
        <div class="col-lg-6">${Admin.ui.card('پربازدیدترین صفحات', `<div class="table-responsive"><table class="table table-sm"><tbody>${d.top_paths.map((x) => `<tr><td dir="ltr" class="text-end">${esc(x.path)}</td><td>${x.views}</td></tr>`).join('') || '<tr><td class="text-center text-muted">داده‌ای نیست</td></tr>'}</tbody></table></div>`)}
        ${Admin.ui.card('ارجاع‌دهنده‌ها', `<div class="table-responsive"><table class="table table-sm"><tbody>${d.top_refs.map((x) => `<tr><td dir="ltr" class="text-end">${esc(x.referrer)}</td><td>${x.views}</td></tr>`).join('') || '<tr><td class="text-center text-muted">داده‌ای نیست</td></tr>'}</tbody></table></div>`)}</div></div>`;
      root.querySelector('#days').addEventListener('change', (e) => { days = parseInt(e.target.value, 10); render(); });
    }
    await render();
  };
  Admin.pages.company = async function (root) {
    const items = await api.get('/api/admin/company');
    root.innerHTML = Admin.ui.card('درباره‌ی شرکت', `<div class="card-body"><p class="text-muted">محتوای صفحهٔ «درباره ما»، صفحهٔ اصلی و تماس. هر بخش را از کارت مربوط ویرایش کنید؛ تغییرات فوراً به فرانت اطلاع داده می‌شود.</p>
      <div class="row g-4">${items.map((it) => `<div class="col-6 col-md-3"><a href="${esc(it.path)}" class="card border h-100 text-decoration-none"><div class="card-body"><h6 class="mb-1">${esc(it.label)}</h6><span class="text-muted">${it.count} مورد</span></div></a></div>`).join('')}</div></div>`);
  };
})();
