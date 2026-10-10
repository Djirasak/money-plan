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
 * Choices.js: nicer <select> dropdowns. Opt out with data-choices="off".
 * Selects with many options (e.g. months) get a search box. The original
 * <select> keeps working and still fires "change".
 */
(() => {
  // Building the dropdown DOM for long lists is slow, so do it when idle.
  const BIG_LIST = 24;
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 50));

  /*
   * Keep the dropdown list on screen. It floats (position: fixed) at the control, so a
   * scrolling dialog or an overflow:hidden card can never clip it, and it opens upwards
   * when there is more room above than below.
   */
  const float = (el, choices) => {
    const container = choices.containerOuter.element;
    const list = () => container.querySelector('.choices__list--dropdown');
    const place = () => {
      const menu = list();
      if (!menu) return;
      const box = container.getBoundingClientRect();
      const below = window.innerHeight - box.bottom - 12;
      const above = box.top - 12;
      const up = below < 200 && above > below;
      const room = Math.max(120, up ? above : below);
      menu.style.position = 'fixed';
      menu.style.left = `${box.left}px`;
      menu.style.width = `${box.width}px`;
      menu.style.marginTop = '0';
      menu.style.top = up ? 'auto' : `${box.bottom + 6}px`;
      menu.style.bottom = up ? `${window.innerHeight - box.top + 6}px` : 'auto';
      const items = menu.querySelector('.choices__list[role="listbox"]');
      const search = menu.querySelector('.choices__input');
      if (items) items.style.maxHeight = `${Math.min(300, room - (search ? 64 : 12))}px`;
    };
    const watch = () => {
      place();
      window.addEventListener('scroll', place, true);
      window.addEventListener('resize', place);
    };
    const unwatch = () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
    el.addEventListener('showDropdown', watch);
    el.addEventListener('hideDropdown', unwatch);
  };

  const enhance = (el) => {
    const { searchPlaceholder, noResults, noChoices } = document.body.dataset;
    const choices = new Choices(el, {
      searchEnabled: el.options.length > 12,
      shouldSort: false,
      itemSelectText: '',
      allowHTML: false,
      searchPlaceholderValue: searchPlaceholder,
      noResultsText: noResults,
      noChoicesText: noChoices,
    });
    float(el, choices);
  };

  const init = (root = document) => {
    if (!window.Choices) return;
    for (const el of root.querySelectorAll('select:not([data-choices="off"])')) {
      if (el.dataset.choicesReady || el.multiple) continue;
      el.dataset.choicesReady = 'true';
      if (el.options.length > BIG_LIST) idle(() => enhance(el));
      else enhance(el);
    }
  };

  document.addEventListener('DOMContentLoaded', () => init());
  document.addEventListener('htmx:afterSwap', (event) => init(event.target));
})();

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
 * Light/dark theme. The initial theme is applied by an inline script in <head>;
 * this wires the toggle button(s), remembers the choice and keeps ARIA in sync.
 */
(() => {
  const root = document.documentElement;
  const sync = () => {
    const dark = root.dataset.theme === 'dark';
    for (const button of document.querySelectorAll('[data-theme-toggle]')) {
      button.setAttribute('aria-checked', String(dark));
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0d0e1b' : '#f6f7fb');
  };
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-theme-toggle]');
    if (!button) return;
    const since = Busy.show(); // brief feedback so the switch never feels like a glitch
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try {
      localStorage.setItem('theme', root.dataset.theme);
    } catch (e) { /* storage blocked: the choice just won't persist */ }
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
    } catch (e) {
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

/*
 * Visual style toggle: "classic" (default) or "minimal" (shadcn tokens, <html data-ui="shadcn">).
 */
(() => {
  const root = document.documentElement;
  const sync = () => {
    const minimal = root.dataset.ui === 'shadcn';
    for (const button of document.querySelectorAll('[data-ui-toggle]')) {
      button.setAttribute('aria-checked', String(minimal));
    }
  };
  document.addEventListener('click', (event) => {
    if (!event.target.closest('[data-ui-toggle]')) return;
    const minimal = root.dataset.ui !== 'shadcn';
    if (minimal) root.dataset.ui = 'shadcn';
    else delete root.dataset.ui;
    try {
      localStorage.setItem('ui', minimal ? 'shadcn' : 'classic');
    } catch (e) { /* storage blocked: the choice just won't persist */ }
    sync();
  });
  sync();
})();
