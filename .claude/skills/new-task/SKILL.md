---
name: new-task
description: Create a roadmap task in tasks/ from a plain request — draft its title, context and acceptance in English, pick the milestone, and commit it on the task board's branch (chore/tasks-board) with the next free id, so it shows on the live board right away. Use when the user says "create a task for …", "crea una tarea para …", "add … to the roadmap/backlog", or types /new-task.
argument-hint: <what the task is about> [milestone]
---

# Create a task

The request is the argument or the user's message. The task lands as
`tasks/<id>-<slug>.md` on `chore/tasks-board`, the branch the live board
commits to; `tasks/README.md` documents the format.

## 1. Draft

- **Title**: one line, English, at most 120 characters, saying what gets
  built or fixed ("Per-account AI model selection"), not how.
- **Body**, in English Markdown:

  ```markdown
  ## Context

  <what and why, from the user's words: 1–4 sentences>

  ## Acceptance

  - <criteria the user gave, one per line; otherwise:>
  - To be defined when the task starts.
  ```

  Add only facts the user gave or you checked in the repo. Do not invent
  scope, estimates or acceptance criteria: `/work-on-task` drafts and agrees
  those when the work starts.
- The file is tracked. Never put real names, email addresses, subjects or
  message text in it: paraphrase to a synthetic equivalent (CLAUDE.md,
  Privacy First).
- **Milestone**: the one the user named; otherwise `later`. It must be listed
  in `tasks/milestones.md` of the board worktree
  (`.claude/worktrees/tasks-board/tasks/milestones.md` under the main
  checkout, or the checkout's own `tasks/milestones.md` before the board
  worktree exists). If the named one is missing, ask whether to create it
  (the board's **New milestone**) or use another; that is the only question
  worth stopping for.
- **Duplicates**: compare with the existing titles
  (`grep -h '^title:' tasks/T-*.md .claude/worktrees/tasks-board/tasks/T-*.md`
  from the main checkout). If one already covers the request, show it and
  ask instead of creating a second.

## 2. Create

Several requests in one message → one task each.

1. Run the `privacy-reviewer` subagent with the title and body as `text`;
   apply every `LEAK` fix and ask about every `UNSURE`.
2. Write the body to a scratch file and run, from the repo root of the
   current checkout:

   ```bash
   python3 scripts/task_board.py new --title "<title>" --milestone <milestone> --body-file <scratch file>
   ```

   It prints `<id> tasks/<id>-<slug>.md (...)`. It brings the board branch
   up to date when its earlier edits are merged, picks the id after the
   highest one any branch ever used, and commits the file; the pre-commit
   hook runs `tasks-check`. A non-zero exit prints the reason: report it,
   do not retry around it. If `scripts/task_board.py` does not exist, this
   checkout's branch predates the board: say so.

## 3. Report

One line per task: id, title, milestone. It is committed on
`chore/tasks-board`, not pushed, and the live board shows it within a few
seconds. Do not start the work: offer `/work-on-task T-NNNN` or the board's
**Open in Herdr** in one line. To undo, the board's **Delete** removes it.
