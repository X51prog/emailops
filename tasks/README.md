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
- `milestone`: one of the names listed in `tasks/milestones.md`. The board lists each
  column from the lowest version up (`0.7.0` before `0.10.0`), named
  milestones such as `later` last.
- `issue` (optional): the GitHub issue the task comes from; the board links it.
- Done tasks are removed by the release (`tasks.py prune-done`, release
  skill Phase 3c): git history keeps them.
- New task: the id after the highest one any branch ever used, `status: todo`.
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
- `make tasks-serve` (`scripts/task_board.py`): the same board served live on
  `127.0.0.1:8780` (the printed URL carries a random token; leave it running in
  a terminal or Herdr pane). Every refresh re-reads the tasks and the agents
  Herdr runs here and on its saved machines, and the page updates in place
  every 5 seconds. A card with an agent says where it runs; a yellow
  **needs you** chip (agent blocked on a question, or done with its turn)
  focuses that Herdr pane and raises the terminal. Each card shows the first
  two lines of its details; clicking the card (or **Details**) opens them
  rendered as Markdown, with the agent's latest output in a collapsed section. **Open in Herdr** focuses the task's agent if there is
  one, otherwise it creates (or reuses) the task's worktree
  `.claude/worktrees/T-NNNN-slug` on `feature/T-NNNN-slug`, opens a Herdr tab
  there, starts Claude and types `/work-on-task T-NNNN` (not sent).
  The served board also edits: **New task** (title, milestone and Markdown
  details), **New milestone** (appended to `tasks/milestones.md`), a milestone
  picker on each card, and **Delete** (two clicks). Deleting a started task
  hides it from every source but keeps its worktree, branch and agent.
  **Discard worktree** (on a card with a worktree here, or next to the note
  about a deleted task whose worktree remains) removes everything of the task
  on this machine: the card, the Herdr panes inside the worktree, the worktree
  with its uncommitted work, and the local branch. The confirming click names
  what is lost (changed files, commits on no other branch). A pushed branch
  and its PR stay: delete them on GitHub. `make disk-clean ARGS="--apply"`
  frees the build directory the worktree leaves behind. Each edit is one commit on
  `chore/tasks-board` (worktree `.claude/worktrees/tasks-board`, created on
  first use), or on the task's own branch once it is started; a refused commit
  (pre-commit hook) leaves the file as it was. Nothing is pushed: merge
  `chore/tasks-board` through a PR when you want the edits on `main`.
- `python3 scripts/tasks.py artifact <path> --label "eval report"` (from a
  task worktree; `/work-on-task` does it) records a file the session produced.
  The card links the latest one and **Details** lists them; the live board
  serves them (and the files beside them, so an HTML report keeps its assets).
  The list is `.claude/task-artifacts.local.json` in that worktree, gitignored.
- What the board shows per task: the base branch's file, overridden by the
  board branch `chore/tasks-board` (edits made from the board), by the task's
  own worktree (uncommitted edits included) and by a pushed
  `feature/T-NNNN-*` branch with no local worktree (another machine or a
  cloud session); the most advanced status wins, and a deletion on the board
  branch wins over all of them.
