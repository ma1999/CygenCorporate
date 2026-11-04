/* Documents attached to an owner (product, certification, ...): one file per language, multipart upload. */
(function () {
  'use strict';
  const { api, toast, esc } = Admin;

  Admin.pages.documents = async function (root) {
    const parts = location.pathname.split('/').filter(Boolean); // admin documents <type> <id>
    const base = `/api/admin/documents/${parts[2]}/${parts[3]}`;

    async function render() {
      const d = await api.get(base);
      const L = d.languages;
      const form = (doc) => {
        const id = doc ? doc.id : 'new';
        return `<form class="doc-form" data-id="${doc ? doc.id : ''}" enctype="multipart/form-data" novalidate>
          <div class="row">
            ${L.map((l) => `<div class="col-md-6 mb-3"><label class="form-label">عنوان (${esc(l.native_name || l.code)})${l.code === 'fa' ? ' <span class="text-danger">*</span>' : ''}</label>
              <input class="form-control" name="title__${l.code}" dir="${l.direction}" value="${doc ? esc(doc.title[l.code] || '') : ''}"></div>`).join('')}
            <div class="col-md-3 mb-3"><label class="form-label">نوع</label><select class="form-select" name="type">${d.doc_types.map((t) => `<option value="${t.value}" ${doc && doc.doc_type === t.value ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}</select></div>
            <div class="col-md-3 mb-3"><label class="form-label">ویرایش (revision)</label><input class="form-control" name="revision" dir="ltr" value="${doc ? esc(doc.revision || '') : ''}"></div>
            <div class="col-md-3 mb-3"><label class="form-label">ترتیب</label><input class="form-control" type="number" name="sort_order" dir="ltr" value="${doc ? doc.sort_order : 0}"></div>
            <div class="col-md-3 mb-3"><label class="form-label d-block">عمومی</label><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="is_public" value="1" ${!doc || doc.is_public ? 'checked' : ''}></div></div>
            ${L.map((l) => { const f = doc && doc.files[l.code]; return `<div class="col-md-6 mb-3"><label class="form-label">فایل (${esc(l.native_name || l.code)})</label>
              ${f ? `<div class="small mb-1"><i class="ti ti-file me-1"></i><span dir="ltr">${esc(f.filename)}</span> <span class="text-muted">(${esc(f.size_label)} · ${esc(f.format || '')} · ${f.downloads} دانلود)</span>
                <div class="form-check d-inline-block ms-2"><input class="form-check-input" type="checkbox" name="remove__${l.code}" value="1" id="rm_${id}_${l.code}"><label class="form-check-label text-danger" for="rm_${id}_${l.code}">حذف</label></div></div>` : ''}
              <input class="form-control" type="file" name="file__${l.code}"></div>`; }).join('')}
          </div>
          <button class="btn btn-primary">${doc ? 'ذخیره' : 'افزودن سند'}</button>
          ${doc ? `<button type="button" class="btn btn-label-danger ms-2 del" data-id="${doc.id}">حذف سند</button>` : ''}
        </form>`;
      };
      root.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3"><h4 class="mb-0">اسناد ${esc(d.owner_label)}: ${esc(d.owner_title)}</h4><a class="btn btn-outline-secondary" href="${esc(d.back)}">بازگشت</a></div>
        <p class="text-muted">حداکثر حجم هر فایل ${d.max_mb} مگابایت · فرمت‌های مجاز: <span dir="ltr">${d.allowed.join(', ')}</span></p>
        ${d.docs.map((doc) => Admin.ui.card(`${esc(doc.title.fa || '#' + doc.id)} <span class="badge bg-label-secondary ms-2">${esc(doc.doc_type)}</span>`, `<div class="card-body">${form(doc)}</div>`)).join('')}
        ${Admin.ui.card('سند جدید', `<div class="card-body">${form(null)}</div>`)}`;

      root.querySelectorAll('.doc-form').forEach((f) => f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = f.dataset.id;
        const fd = new FormData(f);
        if (!f.is_public.checked) fd.set('is_public', '0');
        const btn = f.querySelector('button:not([type=button])');
        btn.disabled = true;
        try {
          await api.post(id ? `/api/admin/documents/${id}/save` : base, fd);
          toast.ok(id ? 'سند ذخیره شد' : 'سند اضافه شد');
          render();
        } catch (ex) { toast.err(ex.message); btn.disabled = false; }
      }));
      root.querySelectorAll('.del').forEach((b) => b.addEventListener('click', async () => {
        if (!(await Admin.confirm('سند و فایل‌های آن حذف شود؟'))) return;
        try { await api.del(`/api/admin/documents/${b.dataset.id}`); toast.ok('سند حذف شد'); render(); } catch (ex) { toast.err(ex.message); }
      }));
    }
    await render();
  };
})();
