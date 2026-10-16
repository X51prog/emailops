// The tab rail links to the project's GitHub Sponsors page, opened in the
// system browser like every other external link.

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsDialog } from './SettingsDialog';

const openExternal = vi.fn((_url: string) => Promise.resolve());
vi.mock('@tauri-apps/plugin-shell', () => ({ open: (url: string) => openExternal(url) }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('@/i18n', () => ({ useUiLanguage: () => ({ language: 'en', setLanguage: vi.fn(), options: [] }) }));
vi.mock('@/stores/aiStore', () => ({ useAiStore: () => ({ enabled: true, setEnabled: vi.fn() }) }));
vi.mock('@/components/shared/LanguageSelect', () => ({ LanguageSelect: () => null }));
vi.mock('@/components/shared/Select', () => ({ Select: () => null }));
for (const m of [
  './AiDraftsSettings',
  './AiSearchSettings',
  './AiSettings',
  './AiTranslationSettings',
  './CalendarSettings',
  './ClassificationSettings',
  './JunkSettings',
  './LensesSettings',
  './MemorySettings',
  './PrivacySettings',
  './TasksSettings',
]) {
  vi.doMock(m, () => new Proxy({}, { get: () => () => null }));
}

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  openExternal.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('SettingsDialog sponsor link', () => {
  it('opens the GitHub Sponsors page in the browser', () => {
    act(() =>
      root.render(
        <SettingsDialog
          activeAccountId={null}
          currentLayout="split"
          onChangeLayout={() => {}}
          tasksEnabled={false}
          onChangeTasksEnabled={() => {}}
          memoriesEnabled={false}
          onChangeMemoriesEnabled={() => {}}
          lensesEnabled={false}
          onChangeLensesEnabled={() => {}}
          onClose={() => {}}
        />,
      ),
    );
    const link = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('settings:dialog.sponsor'),
    );
    expect(link).toBeDefined();
    act(() => link?.click());
    expect(openExternal).toHaveBeenCalledWith('https://github.com/sponsors/emailops');
  });
});
