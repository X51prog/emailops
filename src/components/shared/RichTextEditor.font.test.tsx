// The compose toolbar offers a font picker that names the font of the text at
// the cursor. Applying a font to a selection is covered on the schema side
// (`composeEditorExtensions.test.ts`), where the selection can be set directly.

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ currentPlatform: () => 'macos' }));

import { initI18n } from '@/i18n';
import { RichTextEditor } from './RichTextEditor';

let container: HTMLDivElement;
let root: Root;

beforeAll(async () => {
  await initI18n('en');
});

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(value: string) {
  act(() => root.render(<RichTextEditor value={value} onChange={() => {}} />));
}

function fontPicker(): HTMLSelectElement {
  const select = container.querySelector<HTMLSelectElement>('select[aria-label="Font"]');
  if (!select) throw new Error('font picker not found');
  return select;
}

describe('RichTextEditor font picker', () => {
  it('offers the default font and a set of email-safe fonts', () => {
    render('<p>Hello</p>');

    const labels = Array.from(fontPicker().options).map((option) => option.textContent);
    expect(labels[0]).toBe('Default font');
    expect(labels).toContain('Arial');
    expect(labels).toContain('Georgia');
    expect(labels).toContain('Times New Roman');
  });

  it('shows the default font for unstyled text', () => {
    render('<p>Hello</p>');

    expect(fontPicker().selectedOptions[0]?.textContent).toBe('Default font');
  });

  it('names the font of the text at the cursor', () => {
    render('<p><span style="font-family: Georgia, serif">Hello</span></p>');

    expect(fontPicker().selectedOptions[0]?.textContent).toBe('Georgia');
  });
});
