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

  const enhance = (el) => {
    const { searchPlaceholder, noResults, noChoices } = document.body.dataset;
    new Choices(el, {
      searchEnabled: el.options.length > 12,
      shouldSort: false,
      itemSelectText: '',
      allowHTML: false,
      searchPlaceholderValue: searchPlaceholder,
      noResultsText: noResults,
      noChoicesText: noChoices,
    });
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
