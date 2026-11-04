/* Admin API client: fetch wrapper (session cookie + CSRF header), error type, toasts, confirm.
   Framework-free on purpose so the same contract can be reused from React later. */
(function (w) {
  'use strict';

  class ApiError extends Error {
    constructor(status, code, message, fields) {
      super(message || code);
      this.status = status;
      this.code = code;
      this.fields = fields || null;
    }
  }

  const meta = (n) => (document.querySelector('meta[name="' + n + '"]') || {}).content || '';
  const state = { csrf: meta('csrf-token') };

  function toLogin() {
    const next = encodeURIComponent(location.pathname + location.search);
    location.href = '/login?next=' + next;
  }

  async function request(method, url, body, opts) {
    opts = opts || {};
    const headers = { Accept: 'application/json' };
    let payload;
    if (body instanceof FormData) {
      payload = body;
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    if (method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
    let res;
    try {
      res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' });
    } catch (e) {
      throw new ApiError(0, 'network', 'ارتباط با سرور برقرار نشد');
    }
    if (opts.raw) return res;
    let json = null;
    try { json = await res.json(); } catch (e) { /* non-JSON */ }
    if (res.status === 401 && !opts.noRedirect) { toLogin(); throw new ApiError(401, 'unauthorized', 'نشست منقضی شده است'); }
    if (!res.ok || !json || json.ok === false) {
      throw new ApiError(res.status, json && json.error, (json && json.message) || 'خطای ناشناخته (' + res.status + ')', json && json.fields);
    }
    return opts.full ? json : json.data;
  }

  const api = {
    get: (u, o) => request('GET', u, undefined, o),
    post: (u, b, o) => request('POST', u, b === undefined ? {} : b, o),
    put: (u, b, o) => request('PUT', u, b, o),
    del: (u) => request('DELETE', u),
    qs: (obj) => {
      const p = new URLSearchParams();
      Object.keys(obj || {}).forEach((k) => { if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') p.append(k, obj[k]); });
      const s = p.toString();
      return s ? '?' + s : '';
    },
  };

  if (w.toastr) {
    toastr.options = { closeButton: true, progressBar: true, positionClass: 'toast-top-left', rtl: true, timeOut: 4000 };
  }
  const toast = {
    ok: (m) => (w.toastr ? toastr.success(m) : alert(m)),
    err: (m) => (w.toastr ? toastr.error(m) : alert(m)),
    warn: (m) => (w.toastr ? toastr.warning(m) : alert(m)),
  };

  async function confirmBox(text, opts) {
    opts = opts || {};
    if (!w.Swal) return confirm(text);
    const r = await Swal.fire({
      title: opts.title || 'مطمئن هستید؟', text: text, icon: opts.icon || 'warning', showCancelButton: true,
      confirmButtonText: opts.ok || 'بله، انجام شود', cancelButtonText: 'انصراف',
      customClass: { confirmButton: 'btn btn-danger me-3', cancelButton: 'btn btn-label-secondary' }, buttonsStyling: false,
    });
    return r.isConfirmed;
  }

  const esc = (s) => String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /** run an API call, toast the error, return undefined on failure */
  async function safe(fn) {
    try { return await fn(); } catch (e) { if (e instanceof ApiError) toast.err(e.message); else { console.error(e); toast.err('خطای غیرمنتظره'); } }
  }

  /** skeleton placeholders (same markup the server renders in templates/admin_ui/_sk.html) */
  const sk = {
    line: (w, cls) => `<span class="sk ${cls || ''}" style="width:${w || '100%'}"></span>`,
    rows: (rows, cols) => `<table class="table sk-table mb-0"><tbody>${Array.from({ length: rows || 6 }, (_r, i) => `<tr>${Array.from({ length: cols || 4 }, (_c, j) => `<td>${sk.line(j === 0 ? '70%' : (45 + ((i * 7 + j * 13) % 40)) + '%')}</td>`).join('')}</tr>`).join('')}</tbody></table>`,
    cards: (n) => Array.from({ length: n || 4 }, () => `<div class="col-sm-6 col-xl-3"><div class="card"><div class="card-body d-flex justify-content-between"><div class="flex-grow-1">${sk.line('50%')}<div class="mt-2">${sk.line('30%', 'sk-h')}</div></div><span class="sk sk-circle"></span></div></div></div>`).join(''),
  };

  const pad = (n) => String(n).padStart(2, '0');
  const dt = {
    /** "2026-01-15 10:30" / "2026-01-15T10:30:00" / "2026-01-15" -> "1404/10/25 10:30" ('' when empty/invalid) */
    toJalali(str, withTime) {
      const m = String(str || '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
      if (!m) return '';
      const d = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
      const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US-u-ca-persian-nu-latn', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
        .formatToParts(d).map((p) => [p.type, p.value]));
      const day = `${parts.year}/${parts.month}/${parts.day}`;
      return withTime === false ? day : `${day} ${parts.hour}:${parts.minute}`;
    },
    /** Date -> "2026-01-15 10:30" (or "2026-01-15") */
    toGreg(d, withTime) {
      if (!d) return '';
      d = new Date(d.getTime());   // flatpickr-jalali hands out a Jalali-flavoured Date subclass: copy to a plain Gregorian Date
      const day = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
      return withTime === false ? day : `${day} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    },
    /** value of a picker input as Gregorian string ('' = empty) */
    read(el) {
      const fp = el._flatpickr;
      return fp && fp.selectedDates[0] ? dt.toGreg(fp.selectedDates[0], el.dataset.time !== '0') : '';
    },
    init(el) {
      if (!window.flatpickr || el._flatpickr) return;
      const time = el.dataset.time !== '0';
      flatpickr(el, { enableTime: time, time_24hr: true, dateFormat: time ? 'Y/m/d H:i' : 'Y/m/d', locale: 'fa', disableMobile: true, allowInput: false });
    },
  };

  w.Admin = { ApiError, api, toast, confirm: confirmBox, esc, safe, state, toLogin, sk, dt };
})(window);
