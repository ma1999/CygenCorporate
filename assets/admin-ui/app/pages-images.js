/* File manager for uploads/: folders, upload (drag & drop), rename, move, delete (bulk), text editor, filters. */
(function () {
  'use strict';
  const { api, toast, esc, safe } = Admin;
  const B = '/api/admin/images';

  Admin.pages.images = async function (root) {
    const f = { folder: new URLSearchParams(location.search).get('folder') || '', q: '', ext: '', recursive: '' };
    const sel = new Set();

    async function render() {
      sel.clear();
      let d;
      try { d = await api.get(B + api.qs(f)); } catch (e) { if (f.folder) { f.folder = ''; return render(); } throw e; }
      const parts = f.folder ? f.folder.split('/') : [];
      const quota = d.max_bytes ? Math.min(100, Math.round((d.used_bytes / d.max_bytes) * 100)) : null;
      root.innerHTML = `
        <div class="card mb-3"><div class="card-body d-flex flex-wrap gap-3 align-items-center justify-content-between">
          <nav><ol class="breadcrumb mb-0"><li class="breadcrumb-item"><a href="#" data-f="">uploads</a></li>${parts.map((p, i) => `<li class="breadcrumb-item"><a href="#" data-f="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</a></li>`).join('')}</ol></nav>
          <div class="d-flex flex-wrap gap-2">
            <input class="form-control" id="q" placeholder="جستجوی نام..." style="width:180px" value="${esc(f.q)}">
            <input class="form-control" id="ext" placeholder="پسوند" style="width:90px" dir="ltr" value="${esc(f.ext)}">
            <div class="form-check form-switch align-self-center"><input class="form-check-input" type="checkbox" id="rec" ${f.recursive ? 'checked' : ''}><label class="form-check-label" for="rec">زیرپوشه‌ها</label></div>
            <button class="btn btn-label-secondary" id="newf"><i class="ti ti-folder-plus me-1"></i>پوشهٔ جدید</button>
            <label class="btn btn-primary mb-0"><i class="ti ti-upload me-1"></i>آپلود<input type="file" id="up" multiple hidden></label>
          </div></div>
          ${quota !== null ? `<div class="px-4 pb-3"><div class="progress"><div class="progress-bar ${quota > 90 ? 'bg-danger' : ''}" style="width:${quota}%"></div></div><small class="text-muted"><span dir="ltr">${esc(d.used_h)}</span> از <span dir="ltr">${esc(d.max_h)}</span></small></div>` : `<div class="px-4 pb-3 text-muted small">حجم مصرفی: <span dir="ltr">${esc(d.used_h)}</span></div>`}
        </div>
        <div id="drop" class="border border-dashed rounded p-3 text-center text-muted mb-3">فایل‌ها را اینجا رها کنید</div>
        <div class="card"><div class="card-header d-flex gap-2 align-items-center"><h5 class="mb-0 me-auto">${d.files.length} فایل · ${d.folders.length} پوشه</h5>
          <button class="btn btn-sm btn-label-secondary" id="move" disabled>انتقال</button><button class="btn btn-sm btn-label-danger" id="bulkdel" disabled>حذف انتخاب‌شده‌ها</button></div>
        <div class="table-responsive"><table class="table table-hover align-middle"><thead><tr><th style="width:36px"><input type="checkbox" class="form-check-input" id="all"></th><th></th><th>نام</th><th>اندازه</th><th>ابعاد</th><th>تاریخ</th><th></th></tr></thead><tbody>
          ${d.parent || f.folder ? `<tr><td></td><td><i class="ti ti-arrow-back-up"></i></td><td colspan="5"><a href="#" data-f="${esc(d.parent)}">بالاتر</a></td></tr>` : ''}
          ${d.folders.map((x) => `<tr><td><input type="checkbox" class="form-check-input sel" data-rel="${esc(x.rel)}"></td><td><i class="ti ti-folder text-warning fs-4"></i></td>
            <td><a href="#" data-f="${esc(x.rel)}">${esc(x.name)}</a> <small class="text-muted">(${x.count})</small></td><td></td><td></td><td></td>
            <td class="text-nowrap"><button class="btn btn-sm btn-icon btn-text-secondary rn" data-rel="${esc(x.rel)}" data-name="${esc(x.name)}" data-dir="1" title="تغییر نام"><i class="ti ti-pencil"></i></button></td></tr>`).join('')}
          ${d.files.map((x) => `<tr><td><input type="checkbox" class="form-check-input sel" data-rel="${esc(x.rel)}"></td>
            <td>${x.is_image ? `<img src="${esc(x.url)}" style="width:44px;height:44px;object-fit:cover;border-radius:6px" loading="lazy">` : '<i class="ti ti-file fs-3"></i>'}</td>
            <td><a href="${esc(x.url)}" target="_blank" dir="ltr">${esc(x.name)}</a></td><td dir="ltr" class="text-end">${esc(x.size_h)}</td>
            <td dir="ltr" class="text-end">${x.width ? x.width + '×' + x.height : '—'}</td><td>${esc(x.mtime_h)}</td>
            <td class="text-nowrap"><button class="btn btn-sm btn-icon btn-text-secondary cp" data-u="${esc(x.url)}" title="کپی آدرس"><i class="ti ti-copy"></i></button>
              ${x.is_text ? `<button class="btn btn-sm btn-icon btn-text-secondary ed" data-rel="${esc(x.rel)}" title="ویرایش متن"><i class="ti ti-edit"></i></button>` : ''}
              <button class="btn btn-sm btn-icon btn-text-secondary rn" data-rel="${esc(x.rel)}" data-name="${esc(x.name)}" title="تغییر نام"><i class="ti ti-pencil"></i></button>
              <button class="btn btn-sm btn-icon btn-text-danger dl" data-rel="${esc(x.rel)}" title="حذف"><i class="ti ti-trash"></i></button></td></tr>`).join('')}
          ${!d.files.length && !d.folders.length ? '<tr><td colspan="7" class="text-center text-muted">پوشه خالی است</td></tr>' : ''}
        </tbody></table></div></div>`;

      const go = (folder) => { f.folder = folder; render(); };
      root.querySelectorAll('[data-f]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); go(a.dataset.f); }));
      const refreshSel = () => { root.querySelector('#bulkdel').disabled = root.querySelector('#move').disabled = sel.size === 0; };
      root.querySelectorAll('.sel').forEach((c) => c.addEventListener('change', () => { c.checked ? sel.add(c.dataset.rel) : sel.delete(c.dataset.rel); refreshSel(); }));
      root.querySelector('#all').addEventListener('change', (e) => root.querySelectorAll('.sel').forEach((c) => { c.checked = e.target.checked; c.dispatchEvent(new Event('change')); }));

      let t;
      const filt = () => { clearTimeout(t); t = setTimeout(() => { f.q = root.querySelector('#q').value.trim(); f.ext = root.querySelector('#ext').value.trim(); f.recursive = root.querySelector('#rec').checked ? '1' : ''; render(); }, 350); };
      ['#q', '#ext'].forEach((s) => root.querySelector(s).addEventListener('input', filt));
      root.querySelector('#rec').addEventListener('change', filt);

      const upload = async (files) => {
        if (!files.length) return;
        const fd = new FormData();
        fd.append('folder', f.folder);
        [...files].forEach((x) => fd.append('files', x));
        if (await safe(() => api.post(B + '/upload', fd))) { toast.ok(`${files.length} فایل آپلود شد`); render(); }
      };
      root.querySelector('#up').addEventListener('change', (e) => upload(e.target.files));
      const drop = root.querySelector('#drop');
      ['dragover', 'dragenter'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('bg-label-primary'); }));
      ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('bg-label-primary'); }));
      drop.addEventListener('drop', (e) => upload(e.dataTransfer.files));

      const ask = async (title, value) => {
        const r = await Swal.fire({ title, input: 'text', inputValue: value || '', showCancelButton: true, confirmButtonText: 'تأیید', cancelButtonText: 'انصراف',
          customClass: { confirmButton: 'btn btn-primary me-3', cancelButton: 'btn btn-label-secondary' }, buttonsStyling: false });
        return r.isConfirmed ? r.value.trim() : null;
      };
      root.querySelector('#newf').addEventListener('click', async () => {
        const name = await ask('نام پوشهٔ جدید');
        if (name && await safe(() => api.post(B + '/folder', { folder: f.folder, name }))) { toast.ok('پوشه ایجاد شد'); render(); }
      });
      root.querySelectorAll('.rn').forEach((b) => b.addEventListener('click', async () => {
        const name = await ask('نام جدید', b.dataset.name);
        if (name && name !== b.dataset.name && await safe(() => api.post(b.dataset.dir ? B + '/folder/rename' : B + '/rename', { rel: b.dataset.rel, new_name: name }))) { toast.ok('نام تغییر کرد'); render(); }
      }));
      const del = async (rels) => {
        if (!(await Admin.confirm(`${rels.length} مورد حذف شود؟ این کار قابل بازگشت نیست.`))) return;
        const r = await safe(() => api.post(B + '/delete', { rels }));
        if (r) { r.errors.forEach((m) => toast.err(m)); toast.ok(`${r.deleted} مورد حذف شد`); render(); }
      };
      root.querySelectorAll('.dl').forEach((b) => b.addEventListener('click', () => del([b.dataset.rel])));
      root.querySelector('#bulkdel').addEventListener('click', () => del([...sel]));
      root.querySelector('#move').addEventListener('click', async () => {
        const opts = ['', ...d.all_folders.map((x) => (typeof x === 'string' ? x : x.rel || x.path || ''))].filter((v, i, a) => a.indexOf(v) === i);
        const r = await Swal.fire({ title: 'انتقال به پوشه', input: 'select', inputOptions: Object.fromEntries(opts.map((o) => [o, o || '(ریشه)'])), showCancelButton: true,
          confirmButtonText: 'انتقال', cancelButtonText: 'انصراف', customClass: { confirmButton: 'btn btn-primary me-3', cancelButton: 'btn btn-label-secondary' }, buttonsStyling: false });
        if (!r.isConfirmed) return;
        const res = await safe(() => api.post(B + '/move', { rels: [...sel], dest: r.value }));
        if (res) { res.errors.forEach((m) => toast.err(m)); toast.ok(`${res.moved} مورد منتقل شد`); render(); }
      });
      root.querySelectorAll('.cp').forEach((b) => b.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(location.origin + b.dataset.u); toast.ok('آدرس کپی شد'); } catch (e) { toast.warn(b.dataset.u); }
      }));
      root.querySelectorAll('.ed').forEach((b) => b.addEventListener('click', async () => {
        const doc = await safe(() => api.get(B + '/text' + api.qs({ rel: b.dataset.rel })));
        if (!doc) return;
        const r = await Swal.fire({ title: doc.rel, html: '<textarea id="txt" class="form-control" rows="16" dir="ltr"></textarea>', width: 800, showCancelButton: true, confirmButtonText: 'ذخیره', cancelButtonText: 'انصراف',
          didOpen: () => { document.getElementById('txt').value = doc.content; }, preConfirm: () => document.getElementById('txt').value,
          customClass: { confirmButton: 'btn btn-primary me-3', cancelButton: 'btn btn-label-secondary' }, buttonsStyling: false });
        if (r.isConfirmed && await safe(() => api.put(B + '/text', { rel: doc.rel, content: r.value }))) { toast.ok('فایل ذخیره شد'); render(); }
      }));
    }
    await render();
  };
})();
