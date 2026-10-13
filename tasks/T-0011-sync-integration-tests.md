---
id: T-0011
title: Email-sync integration testing
status: todo
milestone: later
pr: null
---

## Context

The provider mock-server harness (Gmail / Outlook / IMAP cassettes) is in
place; expand coverage to large first-sync (>10k messages), partial-batch
failures + resume, history-id resets, attachment-only deltas, Outlook
delta-token expiry, label / folder rename across runs, and rate-limit backoff.
Goal: every regression caught by running `make demo` against a real account is
reproducible in CI from a cassette.

## Acceptance

- To be defined when the task starts.
