// The list's Unread toggle reaches the backend on every list path, so the
// count, the pages and the background refetches all describe the same set.

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Email } from '@/types';

vi.mock('@/lib/api', () => ({
  getEmails: vi.fn(async () => []),
  getEmailCount: vi.fn(async () => 0),
  getFilteredEmails: vi.fn(async () => ({ emails: [], totalCount: -1, threadLatestAt: {} })),
  listThreadSnoozes: vi.fn(async () => []),
  applyThreadAction: vi.fn(async () => ({ failed: [] })),
}));

import * as api from '@/lib/api';
import { useEmailStore } from './emailStore';

function unreadRow(id: string): Email {
  return { id, accountId: 'acc', threadId: `t-${id}`, isRead: false, timestamp: 1, subject: id } as Email;
}

describe('the Unread toggle', () => {
  beforeEach(() => {
    useEmailStore.setState({ unreadOnly: false, searchQuery: null, emails: [], hasMore: true, totalCount: 0 });
    vi.clearAllMocks();
  });

  it('asks the mailbox list and its count for unread rows only', async () => {
    useEmailStore.getState().setUnreadOnly(true);

    await useEmailStore.getState().fetchEmails('acc', null, [], false, 'sent');

    expect(api.getEmails).toHaveBeenCalledWith('acc', 50, 0, 'sent', true);
    expect(api.getEmailCount).toHaveBeenCalledWith('acc', 'sent', true);
  });

  it('asks the next page for unread rows only', async () => {
    useEmailStore.getState().setUnreadOnly(true);
    useEmailStore.setState({ emails: [unreadRow('a')], hasMore: true, totalCount: 2 });

    await useEmailStore.getState().loadMoreEmails('acc', null, [], 'inbox');

    expect(api.getEmails).toHaveBeenCalledWith('acc', 50, 1, 'inbox', true);
  });

  it('narrows a sidebar filter to unread conversations', async () => {
    useEmailStore.getState().setUnreadOnly(true);
    useEmailStore.setState({ searchQuery: 'from:bob@acme.com' });

    await useEmailStore.getState().fetchEmails('acc', null, [], false, 'inbox');

    const window = vi.mocked(api.getFilteredEmails).mock.calls[0]?.[8];
    expect(window).toMatchObject({ unreadOnly: true });
  });

  it('survives a reset for another account', () => {
    useEmailStore.getState().setUnreadOnly(true);

    useEmailStore.getState().reset();

    expect(useEmailStore.getState().unreadOnly).toBe(true);
  });

  it('keeps a conversation marked read on screen until the list reloads', async () => {
    useEmailStore.getState().setUnreadOnly(true);
    useEmailStore.setState({ emails: [unreadRow('a')], listScope: 'inbox' });

    await useEmailStore.getState().setThreadsRead([{ accountId: 'acc', threadId: 't-a' }], true);

    const rows = useEmailStore.getState().emails;
    expect(rows.map((e) => e.id)).toEqual(['a']);
    expect(rows[0]?.isRead).toBe(true);
  });
});
