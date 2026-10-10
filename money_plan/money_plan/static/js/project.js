/* Project specific Javascript. Vanilla JS only — no jQuery. */

/*
 * Global submit-button handling.
 *
 * On every form submit, all submit buttons of the form are disabled (to block
 * double submits) and the clicked one shows a spinner. Add
 * data-loading-text="Saving..." to a button to change the text shown
 * beside the spinner; by default the button keeps its own text, and icon-only
 * buttons show just the spinner.
 */
(() => {
  const SPINNER =
    '<svg class="size-5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity=".3" stroke-width="3"/>' +
    '<path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>';

  const lock = (form, submitter) => {
    const buttons = form.querySelectorAll('button:not([type="button"]), input[type="submit"]');
    for (const button of buttons) {
      button.disabled = true;
    }
    const target = submitter || form.querySelector('button[type="submit"], button:not([type])');
    if (target && target.tagName === 'BUTTON' && !('original' in target.dataset)) {
      const text = target.dataset.loadingText ?? target.textContent.trim();
      target.dataset.original = target.innerHTML;
      target.setAttribute('aria-busy', 'true');
      target.innerHTML = text
        ? `<span class="inline-flex items-center gap-2">${SPINNER}<span>${text}</span></span>`
        : SPINNER;
    }
  };

  const unlock = () => {
    for (const button of document.querySelectorAll('button[data-original]')) {
      button.innerHTML = button.dataset.original;
      button.removeAttribute('aria-busy');
      delete button.dataset.original;
    }
    for (const button of document.querySelectorAll('button:disabled')) {
      button.disabled = false;
    }
  };

  document.addEventListener('submit', (event) => {
    const { target: form, submitter } = event;
    if (!(form instanceof HTMLFormElement) || form.method === 'dialog') return;
    // Wait until the browser has built the form data: a disabled submitter
    // (e.g. name="action" value="delete") would otherwise not be sent.
    setTimeout(() => {
      if (!event.defaultPrevented) lock(form, submitter);
    }, 0);
  });

  // Coming back via the back button restores the page from bfcache.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) unlock();
  });
})();

/*
 * Basecoat selects: submit the surrounding form when a select marked data-auto-submit changes
 * (Basecoat dispatches a bubbling "change" CustomEvent on the .select root).
 */
document.addEventListener('change', (event) => {
  const select = event.target instanceof Element && event.target.closest('.select[data-auto-submit]');
  if (select) select.closest('form')?.requestSubmit();
});

/*
 * Busy overlay: a grey screen with a spinner. Forms marked data-busy show it on
 * submit (e.g. switching language reloads the page), so nothing looks frozen.
 */
const Busy = (() => {
  const el = () => document.getElementById('busy-overlay');
  return {
    show() {
      const overlay = el();
      if (overlay) overlay.hidden = false;
      return performance.now();
    },
    hide(since = 0, minMs = 0) {
      const wait = Math.max(0, minMs - (performance.now() - since));
      setTimeout(() => {
        const overlay = el();
        if (overlay) overlay.hidden = true;
      }, wait);
    },
  };
})();

document.addEventListener('submit', (event) => {
  const form = event.target;
  if (form instanceof HTMLFormElement && 'busy' in form.dataset) {
    setTimeout(() => {
      if (!event.defaultPrevented) Busy.show();
    }, 0);
  }
});
window.addEventListener('pageshow', (event) => {
  if (event.persisted) Busy.hide();
});

/*
 * Light/dark theme (Basecoat/shadcn convention: class "dark" on <html>). The initial theme is
 * applied by an inline script in <head>; this wires the toggle button(s), remembers the choice
 * and keeps ARIA in sync.
 */
(() => {
  const root = document.documentElement;
  const sync = () => {
    const dark = root.classList.contains('dark');
    for (const button of document.querySelectorAll('[data-theme-toggle]')) {
      button.setAttribute('aria-checked', String(dark));
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0a0a0a' : '#ffffff');
  };
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-theme-toggle]');
    if (!button) return;
    const since = Busy.show(); // brief feedback so the switch never feels like a glitch
    const dark = !root.classList.contains('dark');
    root.classList.toggle('dark', dark);
    try {
      localStorage.setItem('theme', dark ? 'dark' : 'light');
    } catch { /* storage blocked: the choice just won't persist */ }
    sync();
    Busy.hide(since, 220);
  });
  sync();
})();

/*
 * Dialogs: [data-open-dialog="id"] opens, [data-close-dialog] closes, a click on the
 * backdrop closes, and [data-auto-open-id] re-opens a dialog whose form had errors.
 * [data-confirm-delete] fills the shared delete-confirmation dialog.
 */
(() => {
  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-open-dialog]');
    if (opener) {
      document.getElementById(opener.dataset.openDialog)?.showModal();
      return;
    }
    const closer = event.target.closest('[data-close-dialog]');
    if (closer) {
      closer.closest('dialog')?.close();
      return;
    }
    const del = event.target.closest('[data-confirm-delete]');
    if (del) {
      const dialog = document.getElementById('confirm-delete');
      dialog.querySelector('[data-delete-field]').value = del.dataset.deleteId;
      const form = dialog.querySelector('form');
      if (del.dataset.deleteUrl) form.setAttribute('action', del.dataset.deleteUrl);
      else form.removeAttribute('action');
      dialog.querySelector('[data-delete-label]').textContent = del.dataset.deleteName;
      dialog.showModal();
      return;
    }
    if (event.target instanceof HTMLDialogElement) event.target.close(); // backdrop
  });
  document.addEventListener('DOMContentLoaded', () => {
    const id = document.querySelector('[data-auto-open-id]')?.dataset.autoOpenId;
    if (id) document.getElementById(id)?.showModal();
    for (const dialog of document.querySelectorAll('dialog[data-auto-open]')) dialog.showModal();
    // an edit dialog lives on its own URL: closing it returns to the list
    for (const dialog of document.querySelectorAll('dialog[data-return-url]')) {
      dialog.addEventListener('close', () => { location.href = dialog.dataset.returnUrl; });
    }
  });
})();

/*
 * Reorder lists: press and hold a card (touch) or just drag it (mouse). Each item needs
 * data-sort-id / data-sort-name; the list needs data-sortable + data-reorder-url + data-moved.
 * The grip button is the keyboard alternative: focus it and press ArrowUp / ArrowDown.
 */
(() => {
  const csrf = () => {
    try {
      return JSON.parse(document.body.getAttribute('hx-headers') || '{}')['X-CSRFToken'] || '';
    } catch {
      return '';
    }
  };

  const save = (list) => {
    const body = new URLSearchParams();
    for (const item of list.querySelectorAll('[data-sort-id]')) body.append('ids', item.dataset.sortId);
    return fetch(list.dataset.reorderUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  };

  const announce = (list, item) => {
    const items = [...list.querySelectorAll('[data-sort-id]')];
    const text = (list.dataset.moved || '')
      .replace('{name}', item.dataset.sortName)
      .replace('{pos}', String(items.indexOf(item) + 1))
      .replace('{total}', String(items.length));
    const region = document.getElementById('reorder-status');
    if (region) region.textContent = text;
  };

  document.addEventListener('DOMContentLoaded', () => {
    for (const list of document.querySelectorAll('[data-sortable]')) {
      if (window.Sortable) {
        window.Sortable.create(list, {
          draggable: '[data-sort-id]',
          filter: 'button:not([data-reorder-handle]), a, [data-no-sort]',
          preventOnFilter: false,
          delay: 250, // press and hold...
          delayOnTouchOnly: true, // ...on touch screens only, so scrolling still works
          touchStartThreshold: 6,
          animation: 160,
          onEnd: (event) => {
            if (event.oldIndex !== event.newIndex) save(list);
          },
        });
      }
      list.addEventListener('keydown', (event) => {
        const handle = event.target.closest('[data-reorder-handle]');
        if (!handle || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        const item = handle.closest('[data-sort-id]');
        const sibling = event.key === 'ArrowUp' ? item.previousElementSibling : item.nextElementSibling;
        if (!sibling || !sibling.matches('[data-sort-id]')) return;
        if (event.key === 'ArrowUp') list.insertBefore(item, sibling);
        else list.insertBefore(sibling, item);
        handle.focus();
        announce(list, item);
        save(list);
      });
    }
  });
})();
