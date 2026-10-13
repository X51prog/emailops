# Tasks

The roadmap's work items, one Markdown file per task. These files are the
source of truth for what is planned, in progress and done; `ROADMAP.md` is the
prose overview.

## Format

One file per task, named after its id and a short slug (for example
`tasks/T-0001-qwen-3-6-27b-catalog.md`):

```markdown
---
id: T-0001
title: Short imperative title
status: todo
milestone: 0.7.0
pr: null
issue: null
---

## Context

Why the task exists and what it touches.

## Acceptance

- What must be true when it is done.
```

- `status`: `todo` → `doing` → `review` → `done`, or `dropped`.
- `review` and `done` need `pr` (the PR number).
- `milestone`: one of the names listed in `tasks/milestones.md`.
- `issue` (optional): the GitHub issue the task comes from; the board links it.
- Done tasks are removed by the release (`tasks.py prune-done`, release
  skill Phase 3c): git history keeps them.
- New task: next free id, `status: todo`.
- Work on a task in its own worktree and only edit that task's file there, so
  parallel branches never conflict. `/work-on-task T-NNNN` does this.

## Commands

- `make tasks-check`: validate the files (also runs in the pre-commit hook).
- `make tasks-html`: write the live board to `tasks/index.html` in the main
  checkout (gitignored) and print its `file://` URL. It reads every worktree,
  so a task in progress elsewhere shows as `doing` with its branch and whether
  a Claude session is running there. A Claude Code hook regenerates it after
  each task edit; the page reloads itself every 20 seconds.
- The board's **Open in Claude** button is a `claude-cli://` deep link that
  opens a terminal with `/work-on-task T-NNNN` typed in. **Copy command** puts
  the same command on the clipboard when the link handler is not registered.
- `make tasks-serve`: the same board served live on `127.0.0.1:8780` (the
  printed URL carries a random token; leave it running in a terminal or Herdr
  pane). Every refresh re-reads the worktrees, so it needs no hook, and the page
  updates in place every 5 seconds. **Open in Herdr** focuses the task's agent
  if Herdr already runs one, otherwise it creates (or reuses) the task's
  worktree `.claude/worktrees/T-NNNN-slug` on `feature/T-NNNN-slug`, opens a
  Herdr tab there, starts Claude and types `/work-on-task T-NNNN` (not sent).
