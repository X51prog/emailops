import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as api from '@/lib/api';
import { calendarColorMap, FALLBACK_CALENDAR_COLORS, hiddenCalendarIds, visibleEvents } from '@/lib/calendarColor';
import { errorText, isAuthError } from '@/lib/errors';
import { useLogStore } from '@/stores/logStore';
import type { Calendar, CalendarEvent } from '@/types';

/**
 * Events and calendar registry of one account over a visible range, with the
 * on-open / on-switch `sync_calendar_now` refresh. Shared by the full
 * calendar view and the day-agenda panel. Every async path is
 * generation-guarded so a slow answer for a previous account or range never
 * lands over the current one.
 */
export function useCalendarData(selectedAccountId: string | null, rangeStart: number, rangeEnd: number) {
  const addLog = useLogStore((s) => s.addLog);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsReauth, setNeedsReauth] = useState(false);
  const [isReauthing, setIsReauthing] = useState(false);

  // Load events for the visible range. Guarded against stale responses.
  const fetchIdRef = useRef(0);
  const loadEvents = useCallback(
    async (accountId: string, start: number, end: number) => {
      const fetchId = ++fetchIdRef.current;
      setIsLoading(true);
      try {
        const result = await api.getCalendarEvents(accountId, start, end);
        if (fetchIdRef.current !== fetchId) return;
        setEvents(result);
        setIsLoading(false);
      } catch (e) {
        if (fetchIdRef.current !== fetchId) return;
        setIsLoading(false);
        const msg = errorText(e);
        setError(msg);
        addLog('error', 'sync', `Failed to load calendar events: ${msg}`);
      }
    },
    [addLog],
  );

  useEffect(() => {
    if (!selectedAccountId) {
      setEvents([]);
      return;
    }
    void loadEvents(selectedAccountId, rangeStart, rangeEnd);
  }, [selectedAccountId, rangeStart, rangeEnd, loadEvents]);

  // The account's calendar registry: colours and the show/hide toggles.
  // Reloaded after each sync, which is what refreshes colours and picks up
  // newly shared calendars.
  const loadCalendars = useCallback(
    async (accountId: string) => {
      try {
        setCalendars(await api.getCalendars(accountId));
      } catch (e) {
        // Non-fatal: without the registry every event falls back to a palette
        // colour and nothing is hidden, so the calendar still renders.
        addLog('error', 'sync', `Failed to load calendars: ${errorText(e)}`);
      }
    },
    [addLog],
  );

  useEffect(() => {
    if (!selectedAccountId) {
      setCalendars([]);
      return;
    }
    void loadCalendars(selectedAccountId);
  }, [selectedAccountId, loadCalendars]);

  const colorMap = useMemo(() => calendarColorMap(calendars), [calendars]);
  const colorFor = useCallback(
    (calendarId: string) => colorMap.get(calendarId) ?? FALLBACK_CALENDAR_COLORS[0],
    [colorMap],
  );
  const hidden = useMemo(() => hiddenCalendarIds(calendars), [calendars]);
  const shownEvents = useMemo(() => visibleEvents(events, hidden), [events, hidden]);

  // Optimistic toggle: flip locally first so the grid re-filters instantly,
  // then persist. On failure reload the registry so the UI never keeps a
  // toggle the DB rejected.
  const toggleCalendar = useCallback(
    async (calendar: Calendar) => {
      if (!selectedAccountId) return;
      const next = !calendar.isVisible;
      setCalendars((current) =>
        current.map((c) => (c.providerCalendarId === calendar.providerCalendarId ? { ...c, isVisible: next } : c)),
      );
      try {
        await api.setCalendarVisible(selectedAccountId, calendar.providerCalendarId, next);
      } catch (e) {
        addLog('error', 'sync', `Failed to update calendar visibility: ${errorText(e)}`);
        void loadCalendars(selectedAccountId);
      }
    },
    [selectedAccountId, addLog, loadCalendars],
  );

  // Keep the latest range in a ref so a finishing sync reloads what's visible now.
  const rangeRef = useRef({ rangeStart, rangeEnd });
  rangeRef.current = { rangeStart, rangeEnd };

  // Sync on open / account switch, and via the manual Refresh button.
  // Generation-guarded: a sync that finishes after a newer one started (e.g.
  // the previous account's slow sync landing after an account switch) must not
  // reload its events over the current account's, nor touch banner state.
  const syncIdRef = useRef(0);
  const runSync = useCallback(
    async (accountId: string) => {
      const syncId = ++syncIdRef.current;
      setIsSyncing(true);
      setError(null);
      setNeedsReauth(false);
      try {
        const stored = await api.syncCalendarNow(accountId);
        addLog('success', 'sync', `Calendar synced (${stored} events)`);
        if (syncIdRef.current !== syncId) return;
        const { rangeStart: start, rangeEnd: end } = rangeRef.current;
        await loadEvents(accountId, start, end);
        await loadCalendars(accountId);
      } catch (e) {
        const msg = errorText(e);
        addLog('error', 'sync', `Calendar sync failed: ${msg}`);
        if (syncIdRef.current !== syncId) return;
        // Auth-class failures get the friendly banner + inline re-auth button;
        // the raw provider message only goes to the output panel.
        if (isAuthError(e, msg)) {
          setNeedsReauth(true);
        } else {
          setError(msg);
        }
      } finally {
        if (syncIdRef.current === syncId) setIsSyncing(false);
      }
    },
    [addLog, loadEvents, loadCalendars],
  );

  // Inline re-auth from the banner: run the OAuth flow for the selected
  // account, then sync again so granted access is visible immediately.
  const runReauth = useCallback(async () => {
    if (!selectedAccountId) return;
    setIsReauthing(true);
    try {
      await api.reauthenticateAccount(selectedAccountId);
      addLog('success', 'account', 'Account re-authenticated');
      setNeedsReauth(false);
      await runSync(selectedAccountId);
    } catch (e) {
      const msg = errorText(e);
      setError(msg);
      addLog('error', 'account', `Re-authentication failed: ${msg}`);
    } finally {
      setIsReauthing(false);
    }
  }, [selectedAccountId, addLog, runSync]);

  useEffect(() => {
    if (!selectedAccountId) return;
    void runSync(selectedAccountId);
  }, [selectedAccountId, runSync]);

  return {
    events,
    setEvents,
    calendars,
    isLoading,
    isSyncing,
    error,
    setError,
    needsReauth,
    setNeedsReauth,
    isReauthing,
    colorFor,
    shownEvents,
    toggleCalendar,
    runSync,
    runReauth,
  };
}
