// "Not junk" on a message filed in Spam takes the conversation out of Spam
// (the not-spam thread action); elsewhere it only records the correction.

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({
  setJunkFeedback: vi.fn(async () => undefined),
  getJunkVerdicts: vi.fn(async () => []),
}));

import { initI18n } from '@/i18n';
import * as api from '@/lib/api';
import { useEmailStore } from '@/stores/emailStore';
import { useJunkStore } from '@/stores/junkStore';
import type { JunkVerdict } from '@/types';
import { JunkBanner } from './JunkBanner';

let container: HTMLDivElement;
let root: Root;
const markThreadsNotSpam = vi.fn(async () => undefined);

beforeAll(async () => {
  await initI18n('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  useEmailStore.setState({ markThreadsNotSpam });
  useJunkStore.setState({
    loadVerdicts: async () => {},
    verdictsByEmail: {
      e2: {
        emailId: 'e2',
        band: 'junk',
        primaryKind: 'spam',
        reasons: [],
        userOverride: null,
      } as unknown as JunkVerdict,
    },
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const notJunkButton = () =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Not junk') as HTMLButtonElement;

async function renderBanner(mailbox: string) {
  await act(async () => root.render(<JunkBanner emailId="e2" accountId="a1" threadId="t2" mailbox={mailbox} />));
}

describe('JunkBanner not junk', () => {
  it('in Spam it takes the conversation out of Spam', async () => {
    await renderBanner('spam');

    await act(async () => notJunkButton().click());

    expect(markThreadsNotSpam).toHaveBeenCalledWith([{ accountId: 'a1', threadId: 't2' }]);
    expect(api.setJunkFeedback).not.toHaveBeenCalled();
  });

  it('outside Spam it only records the correction', async () => {
    await renderBanner('inbox');

    await act(async () => notJunkButton().click());

    expect(api.setJunkFeedback).toHaveBeenCalledWith('a1', 'e2', false);
    expect(markThreadsNotSpam).not.toHaveBeenCalled();
  });
});
