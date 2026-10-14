import { describe, expect, it } from 'vitest';

import { threadMailboxState } from './EmailView';

const m = (mailbox: string) => ({ mailbox });

describe('threadMailboxState', () => {
  it.each([
    ['inbox only', [m('inbox')], { inInbox: true, archived: false, inSpam: false }],
    ['archived only', [m('archive')], { inInbox: false, archived: true, inSpam: false }],
    ['spam only, no detector verdict needed', [m('spam')], { inInbox: false, archived: false, inSpam: true }],
    ['inbox and spam', [m('inbox'), m('spam')], { inInbox: true, archived: false, inSpam: true }],
    ['sent and trash', [m('sent'), m('trash')], { inInbox: false, archived: false, inSpam: false }],
  ])('%s', (_name, emails, expected) => {
    expect(threadMailboxState(emails)).toEqual(expected);
  });
});
