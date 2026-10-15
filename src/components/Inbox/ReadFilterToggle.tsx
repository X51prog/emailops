import { useTranslation } from 'react-i18next';
import { useEmailStore } from '@/stores/emailStore';

/** All / Unread segmented toggle of the list header. It flips the store's
 *  session flag; `useEmails` refetches the list when it changes. */
export function ReadFilterToggle() {
  const { t } = useTranslation(['inbox']);
  const unreadOnly = useEmailStore((s) => s.unreadOnly);
  const setUnreadOnly = useEmailStore((s) => s.setUnreadOnly);

  const options = [
    { value: false, label: t('inbox:readFilter.all') },
    { value: true, label: t('inbox:readFilter.unread') },
  ];
  return (
    <div
      role="radiogroup"
      aria-label={t('inbox:readFilter.aria')}
      className="flex items-center rounded-lg border border-gray-200 p-0.5 text-xs font-medium"
    >
      {options.map(({ value, label }) => {
        const checked = unreadOnly === value;
        return (
          <button
            key={label}
            type="button"
            role="radio"
            aria-checked={checked}
            onClick={() => setUnreadOnly(value)}
            className={`px-2 py-1 rounded-md transition-colors ${
              checked ? 'bg-primary-50 text-primary-700' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
