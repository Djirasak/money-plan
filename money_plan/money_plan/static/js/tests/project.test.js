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

  describe('live password rule', () => {
    const mount = () => {
      document.body.innerHTML = `
        <form>
          <input id="p1" autocomplete="new-password" />
          <div data-password-rules data-mismatch-text="no match" data-ok-text="met" data-bad-text="not met">
            <ul><li data-rule="length" data-min="8" data-state="idle"><span data-rule-status></span></li></ul>
          </div>
          <input id="p2" autocomplete="new-password" />
        </form>`;
      document.dispatchEvent(new Event('DOMContentLoaded'));
      const type = (id, value) => {
        const input = document.getElementById(id);
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const item = document.querySelector('[data-rule="length"]');
      return { type, item };
    };

    it('stays neutral until something is typed', () => {
      expect(mount().item.dataset.state).toBe('idle');
    });

    it('is red under 8 characters and green from 8', () => {
      const { type, item } = mount();
      type('p1', '1234567');
      expect(item.dataset.state).toBe('bad');
      expect(item.querySelector('[data-rule-status]').textContent).toBe('not met');
      type('p1', '12345678');
      expect(item.dataset.state).toBe('ok');
      expect(item.querySelector('[data-rule-status]').textContent).toBe('met');
      type('p1', '');
      expect(item.dataset.state).toBe('idle');
    });

    it('counts characters, not bytes, so Thai works', () => {
      const { type, item } = mount();
      type('p1', 'รหัสผ่านใหม่');
      expect(item.dataset.state).toBe('ok');
    });

    it('shows a message as soon as the confirmation differs, and hides it when it matches', () => {
      const { type } = mount();
      const message = () => document.querySelector('[role="alert"]');
      type('p1', 'abcdefgh1');
      type('p2', 'abc');
      expect(message().hidden).toBe(false);
      expect(message().textContent).toBe('no match');
      expect(document.getElementById('p2').getAttribute('aria-invalid')).toBe('true');
      type('p2', 'abcdefgh1');
      expect(message().hidden).toBe(true);
      type('p1', 'changed-after');
      expect(message().hidden).toBe(false);
    });

    it('says nothing while the confirmation is still empty', () => {
      const { type } = mount();
      type('p1', 'abcdefgh1');
      expect(document.querySelector('[role="alert"]').hidden).toBe(true);
    });
  });

  it('copies a link with the copy button and says so in the tooltip', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    document.body.innerHTML =
      '<div><input readonly value="x" data-select-on-focus /><button data-copy="https://x.test/t/abc" data-copied="Copied" title="Copy link"></button></div>';
    document.querySelector('button').click();
    await flush();
    expect(writeText).toHaveBeenCalledWith('https://x.test/t/abc');
    expect(document.querySelector('button').getAttribute('title')).toBe('Copied');
  });

  it('selects a read-only link when it is focused', () => {
    document.body.innerHTML = '<input readonly value="https://x.test" data-select-on-focus />';
    const input = document.querySelector('input');
    const select = vi.spyOn(input, 'select');
    input.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    expect(select).toHaveBeenCalled();
  });

  it('shows the chosen file name next to a custom file button, and the empty text again when cleared', () => {
    document.body.innerHTML =
      '<div data-file-input><input type="file" id="f" /><span data-file-name data-empty="No file chosen">No file chosen</span></div>';
    const input = document.getElementById('f');
    const label = document.querySelector('[data-file-name]');
    const file = new File(['{}'], 'plan.json', { type: 'application/json' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    expect(label.textContent).toBe('plan.json');
    Object.defineProperty(input, 'files', { value: [], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    expect(label.textContent).toBe('No file chosen');
  });

  it('submits the form at once when a photo is picked, but not for other file inputs', () => {
    document.body.innerHTML = `
      <form id="a"><input type="file" id="auto" data-auto-submit /></form>
      <form id="b"><input type="file" id="plain" /></form>`;
    const submitA = vi.fn();
    const submitB = vi.fn();
    document.getElementById('a').requestSubmit = submitA;
    document.getElementById('b').requestSubmit = submitB;
    const pick = (id) => {
      const input = document.getElementById(id);
      Object.defineProperty(input, 'files', { value: [new File(['x'], 'p.jpg')], configurable: true });
      input.dispatchEvent(new Event('change', { bubbles: true }));
    };
    pick('plain');
    expect(submitB).not.toHaveBeenCalled();
    pick('auto');
    expect(submitA).toHaveBeenCalledOnce();
  });
});
