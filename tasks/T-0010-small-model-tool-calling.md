---
id: T-0010
title: Tool-calling reliability on small local models
status: todo
milestone: later
pr: null
---

## Context

Models in the ~4–9B class often emit tool calls as plain text or stop at a
narration instead of chaining `search_emails → generate_email_draft`. A
registry-aware text salvager and a one-shot nudge are partial mitigations;
longer term: intent-based preseeded multi-call chains for draft / forward /
reply requests, progressive nudging, and stricter JSON-schema requireds (e.g.
`email_id` for reply drafts).

## Acceptance

- To be defined when the task starts.
