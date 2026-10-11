import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

// project.js registers document/window listeners when loaded, so it is imported once
// and every test just swaps the document body.
beforeAll(async () => {
  await import('../project.js');
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 5));

describe('project.js', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    document.documentElement.className = '';
    HTMLDialogElement.prototype.showModal = function showModal() {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function close() {
      this.removeAttribute('open');
    };
  });

  it('locks submit buttons and shows a spinner on submit', async () => {
    document.body.innerHTML =
      '<form><button type="submit" data-loading-text="Saving...">Save</button></form>';
    const form = document.querySelector('form');
    const event = new Event('submit', { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'submitter', { value: form.querySelector('button') });
    form.dispatchEvent(event);
    await flush();
    const button = form.querySelector('button');
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.textContent).toContain('Saving...');
  });

  it('toggles the dark theme and persists the choice', () => {
    document.body.innerHTML =
      '<meta name="theme-color" content="#ffffff"><button data-theme-toggle aria-checked="false"></button>';
    document.querySelector('[data-theme-toggle]').click();
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(localStorage.getItem('theme')).toBe('dark');
    expect(document.querySelector('[data-theme-toggle]').getAttribute('aria-checked')).toBe('true');
  });

  it('opens and closes dialogs via data attributes', () => {
    document.body.innerHTML = `
      <button data-open-dialog="d">open</button>
      <dialog id="d"><button data-close-dialog>close</button></dialog>`;
    document.querySelector('[data-open-dialog]').click();
    expect(document.getElementById('d').hasAttribute('open')).toBe(true);
    document.querySelector('[data-close-dialog]').click();
    expect(document.getElementById('d').hasAttribute('open')).toBe(false);
  });

  it('fills the shared delete-confirmation dialog', () => {
    document.body.innerHTML = `
      <button data-confirm-delete data-delete-id="7" data-delete-name="Rent" data-delete-url="/del/">x</button>
      <dialog id="confirm-delete">
        <form><input data-delete-field><span data-delete-label></span></form>
      </dialog>`;
    document.querySelector('[data-confirm-delete]').click();
    const dialog = document.getElementById('confirm-delete');
    expect(dialog.querySelector('[data-delete-field]').value).toBe('7');
    expect(dialog.querySelector('[data-delete-label]').textContent).toBe('Rent');
    expect(dialog.querySelector('form').getAttribute('action')).toBe('/del/');
    expect(dialog.hasAttribute('open')).toBe(true);
  });

  it('reorders a list with the keyboard and saves the new order', () => {
    const fetchMock = vi.fn(() => Promise.resolve({}));
    vi.stubGlobal('fetch', fetchMock);
    document.body.innerHTML = `
      <div id="reorder-status"></div>
      <ul data-sortable data-reorder-url="/reorder/" data-moved="{name} {pos}/{total}">
        <li data-sort-id="1" data-sort-name="A"><button data-reorder-handle></button></li>
        <li data-sort-id="2" data-sort-name="B"><button data-reorder-handle></button></li>
      </ul>`;
    document.dispatchEvent(new Event('DOMContentLoaded'));
    const second = document.querySelector('[data-sort-id="2"] button');
    second.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    const ids = [...document.querySelectorAll('[data-sort-id]')].map((li) => li.dataset.sortId);
    expect(ids).toEqual(['2', '1']);
    expect(document.getElementById('reorder-status').textContent).toBe('B 1/2');
    expect(fetchMock).toHaveBeenCalledWith('/reorder/', expect.objectContaining({ method: 'POST' }));
  });

  it('picks a colour theme, remembers it, and indigo clears the attribute', () => {
    document.documentElement.removeAttribute('data-color');
    document.body.innerHTML = `
      <button data-color-choice="indigo" aria-checked="false"></button>
      <button data-color-choice="rose" aria-checked="false"></button>`;
    const [indigo, rose] = document.querySelectorAll('[data-color-choice]');
    rose.click();
    expect(document.documentElement.dataset.color).toBe('rose');
    expect(localStorage.getItem('color')).toBe('rose');
    expect(rose.getAttribute('aria-checked')).toBe('true');
    expect(indigo.getAttribute('aria-checked')).toBe('false');
    indigo.click();
    expect(document.documentElement.dataset.color).toBeUndefined();
    expect(indigo.getAttribute('aria-checked')).toBe('true');
  });

  it('ignores a colour that is not in the list', () => {
    document.documentElement.removeAttribute('data-color');
    document.body.innerHTML = '<button data-color-choice="hotpink"></button>';
    document.querySelector('button').click();
    expect(document.documentElement.dataset.color).toBeUndefined();
  });
});
