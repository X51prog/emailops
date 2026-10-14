// A row in Spam offers "Not spam" in its ⋮ menu, the same not-spam thread
// action as the reading pane's toolbar; a row anywhere else does not.

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { initI18n } from '@/i18n';
import { useEmailStore } from '@/stores/emailStore';
import type { Email } from '@/types';
import { EmailRow } from './EmailRow';

const base: Email = {
  id: 'email-1',
  accountId: 'acct-1',
  threadId: 'thread-1',
  messageId: null,
  subject: 'Quarterly report',
  sender: 'Ada Example',
  senderEmail: 'ada@example.com',
  recipients: ['me@example.com'],
  cc: [],
  body: 'body',
  snippet: 'snippet',
  timestamp: 1_700_000_000,
  isRead: true,
  triageStatus: null,
  category: 'primary',
  mailbox: 'spam',
  isSent: false,
  isStarred: false,
};

let container: HTMLDivElement;
let root: Root;
const markThreadsNotSpam = vi.fn(async () => undefined);

beforeAll(async () => {
  await initI18n('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  useEmailStore.setState({ markThreadsNotSpam });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function openMenu(email: Email): HTMLElement {
  act(() => {
    root.render(<EmailRow email={email} isSelected={false} onClick={() => {}} />);
  });
  const button = container.querySelector<HTMLButtonElement>('button[aria-label="More actions"]');
  if (!button) throw new Error('kebab button not rendered');
  act(() => {
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  const dropdown = document.body.querySelector<HTMLElement>('div.fixed');
  if (!dropdown) throw new Error('dropdown not rendered');
  return dropdown;
}

const notSpamItem = (dropdown: HTMLElement) =>
  Array.from(dropdown.querySelectorAll('button')).find((b) => b.textContent?.includes('Not spam'));

describe('EmailRow menu: Not spam', () => {
  it('a row in Spam takes its conversation out of Spam', () => {
    const item = notSpamItem(openMenu(base));
    expect(item).toBeDefined();

    act(() => item?.dispatchEvent(new MouseEvent('click', { bubbles: true })));

    expect(markThreadsNotSpam).toHaveBeenCalledWith([{ accountId: 'acct-1', threadId: 'thread-1' }]);
  });

  it('a row in the inbox does not offer it', () => {
    expect(notSpamItem(openMenu({ ...base, mailbox: 'inbox' }))).toBeUndefined();
  });
});
