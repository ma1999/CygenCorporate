/* Categories: two-level tree list with toggle / soft-delete / purge. Create & edit use the generic entity form. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const B = '/api/admin/categories';

  Admin.pages.categories = async function (root) {
    async function render() {
      const rows = await api.get(B);
      const subs = {};
      rows.filter((r) => r.parent_id).forEach((r) => (subs[r.parent_id] = subs[r.parent_id] || []).push(r));
      const tops = rows.filter((r) => !r.parent_id);
      const line = (r, child) => `<tr>
        <td class="${child ? 'ps-5' : 'fw-semibold'}">${child ? '<i class="ti ti-corner-down-left me-1 text-muted"></i>' : ''}<a href="/admin/categories/${r.id}/edit">${esc(r.name)}</a></td>
        <td dir="ltr" class="text-end text-muted">${esc(r.slug || '—')}</td>
        <td>${r.sort_order || 0}</td>
        <td><div class="form-check form-switch"><input class="form-check-input tg" type="checkbox" data-id="${r.id}" ${r.is_active ? 'checked' : ''}></div></td>
        <td class="text-nowrap">
          <a class="btn btn-sm btn-icon btn-text-secondary" href="/admin/categories/${r.id}/edit" title="ویرایش"><i class="ti ti-edit"></i></a>
          ${child ? '' : `<a class="btn btn-sm btn-icon btn-text-secondary" href="/admin/categories/create?parent_id=${r.id}" title="زیردستهٔ جدید"><i class="ti ti-plus"></i></a>`}
          <button class="btn btn-sm btn-icon btn-text-danger del" data-id="${r.id}" data-name="${esc(r.name)}" title="حذف"><i class="ti ti-trash"></i></button>
        </td></tr>`;
      root.innerHTML = Admin.ui.card('دسته‌بندی‌ها', `<div class="table-responsive"><table class="table table-hover">
          <thead><tr><th>نام</th><th>Slug</th><th>ترتیب</th><th>فعال</th><th></th></tr></thead>
          <tbody>${tops.map((t) => line(t, false) + (subs[t.id] || []).map((s) => line(s, true)).join('')).join('') || '<tr><td colspan="5" class="text-center text-muted">دسته‌بندی‌ای وجود ندارد</td></tr>'}</tbody></table></div>`,
        `<div class="d-flex gap-2"><button class="btn btn-label-secondary" id="purge"><i class="ti ti-eraser me-1"></i>پاکسازی حذف‌شده‌های بلااستفاده</button>
         <a class="btn btn-primary" href="/admin/categories/create"><i class="ti ti-plus me-1"></i>دسته‌بندی جدید</a></div>`);

      root.querySelectorAll('.tg').forEach((el) => el.addEventListener('change', async () => {
        const r = await safe(() => api.post(`${B}/${el.dataset.id}/toggle`));
        if (r) toast.ok('وضعیت تغییر کرد'); else el.checked = !el.checked;
      }));
      root.querySelectorAll('.del').forEach((b) => b.addEventListener('click', async () => {
        if (!(await Admin.confirm(`دسته‌بندی «${b.dataset.name}» و زیردسته‌هایش حذف شوند؟ (از دیتابیس باقی می‌مانند)`))) return;
        if (await safe(() => api.del(`${B}/${b.dataset.id}`))) { toast.ok('دسته‌بندی حذف شد'); render(); }
      }));
      root.querySelector('#purge').addEventListener('click', async () => {
        if (!(await Admin.confirm('دسته‌بندی‌های حذف‌شدهٔ بلااستفاده برای همیشه پاک شوند؟'))) return;
        const r = await safe(() => api.post(`${B}/purge`));
        if (r) { r.removed ? toast.ok(`${r.removed} دسته‌بندی پاک شد`) : toast.warn('موردی برای پاکسازی وجود نداشت'); render(); }
      });
    }
    await render();
  };
})();
