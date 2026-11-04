/* Site theme: pick the active frontend theme and open the visual builder per page. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;

  Admin.pages.site_theme = async function (root) {
    async function render() {
      const d = await api.get('/api/admin/site-theme/themes');
      root.innerHTML = Admin.ui.card('قالب سایت', `<div class="card-body">
        <p class="text-muted">قالب فعال روی سایت برای همه کاربران اعمال می‌شود. برای قالب‌هایی که ویرایشگر دارند، هر صفحهٔ قابل‌ویرایش دکمهٔ جدای خودش را دارد.</p>
        <div class="row g-4">${d.themes.map((t) => `<div class="col-md-4"><div class="card border ${t === d.active ? 'border-primary' : ''}"><div class="card-body">
          <div class="d-flex justify-content-between mb-3"><strong dir="ltr">${esc(t)}</strong>${t === d.active ? '<span class="badge bg-label-success">فعال</span>' : ''}</div>
          <div class="d-grid gap-2">${t === d.active ? '' : `<button class="btn btn-label-primary act" data-t="${esc(t)}">فعال‌سازی</button>`}
          ${(d.theme_pages[t] || []).map((p) => `<a class="btn btn-primary" href="/admin/site-theme/builder/${encodeURIComponent(t)}/${encodeURIComponent(p)}">${esc(d.page_labels[p] || p)}</a>`).join('') || '<span class="text-muted small text-center">ویرایشگر ندارد</span>'}
          </div></div></div></div>`).join('') || '<p class="text-muted">هیچ قالبی در templates/themes یافت نشد.</p>'}</div></div>`);
      root.querySelectorAll('.act').forEach((b) => b.addEventListener('click', async () => {
        if (await safe(() => api.post('/api/admin/site-theme/activate', { theme: b.dataset.t }))) { toast.ok('قالب فعال شد'); render(); }
      }));
    }
    await render();
  };
})();
