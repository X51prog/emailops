#!/usr/bin/env python3
"""Validate the task files under tasks/ and render them as a live HTML board.

Every task is one Markdown file, tasks/T-NNNN-slug.md, with a frontmatter block
(id, title, status, milestone, pr) and a free-form body. The files are the
source of truth; there is no generated index in git, so agents working on
different tasks in different worktrees never touch the same file.

Usage:
  tasks.py check
      Validate the task files of this checkout (milestones must be listed in
      tasks/milestones.md). Exit 1 on any error.
  tasks.py prune-done
      git rm the done tasks of this checkout; the release skill runs it so a
      release commit drops the tasks it shipped.
  tasks.py html [--out PATH]
      Build the board and write one self-contained page. Default output:
      <main checkout>/tasks/index.html (gitignored). Read-only otherwise.
      The board layers, per task, the most advanced status from: the base branch
      (TASK_BASE), the board's own branch (chore/tasks-board: milestone edits and
      deletions made from the live board), the task's own worktree (feature/T-NNNN-*,
      uncommitted edits included) and a pushed feature/T-NNNN-* branch with no local
      worktree (another machine or a cloud session). Other worktrees are ignored:
      each carries a stale copy of every task. Task worktrees add their activity
      (branch, last commit, dirty files, commits ahead of origin/main, minutes since
      the last change, and whether an agent is on it).

  The live board (scripts/task_board.py, make tasks-serve) renders the same page.
"""

# The URL handler runs macOS /usr/bin/python3 (3.9): keep annotations lazy.
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

STATUSES = ("todo", "doing", "review", "done", "dropped")
# Merge order across worktrees: a later status means more progress.
RANK = {"todo": 0, "doing": 1, "review": 2, "dropped": 3, "done": 4}
FIELDS = ("id", "title", "status", "milestone", "pr")
ID_RE = re.compile(r"^T-\d{4}$")
MAIN = "main"  # label of the base branch's tasks
BOARD = "tasks-board"  # label and worktree dir of the branch the live board writes to
BOARD_BRANCH = "chore/tasks-board"
TASK_BRANCH_RE = re.compile(r"^(?:feature|fix|refactor)/(T-\d{4})-")
TASK_PATH_RE = re.compile(r"/\.claude/worktrees/(T-\d{4})-[^/]*(?:/|$)")
NEEDS_YOU = ("blocked", "done")  # Herdr states where the agent waits for the user
RELOAD_SECONDS = 20
ACTIVE_MINUTES = 10  # a worktree changed this recently counts as having an agent on it
POLL_SECONDS = 5  # the served page re-reads the board this often
TASK_BASE = "chore/sdlc-automation"  # TODO: origin/main once this branch is merged (work-on-task lives there)


@dataclass
class Task:
    id: str
    title: str
    status: str
    milestone: str
    pr: int | None
    body: str
    file: str
    worktree: str
    issue: int | None = None  # optional GitHub issue number


@dataclass
class WorktreeInfo:
    name: str
    branch: str
    last_commit: str
    dirty: int
    ahead: int
    idle_min: int  # minutes since the last change (dirty file or commit)
    agent: bool
    remote: bool = False  # a pushed branch with no local worktree


@dataclass
class AgentInfo:
    machine: str  # where the agent runs: this computer's name or a Herdr machine label
    machine_id: str | None  # Herdr machine id, None for this computer
    status: str  # Herdr: idle | working | blocked | done | unknown
    pane_id: str


def parse_task(text, file, worktree):
    """Parse one task file. Raises ValueError on a malformed file."""
    if not text.startswith("---\n"):
        raise ValueError(f"{file}: missing frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{file}: unterminated frontmatter")
    meta = {}
    for line in text[4:end].splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                raise ValueError(f"{file}: bad frontmatter line {line!r}")
            meta[key.strip()] = value.strip()
    missing = [f for f in FIELDS if f not in meta]
    if missing:
        raise ValueError(f"{file}: missing {', '.join(missing)}")
    pr, issue = (number(meta.get(k, "null"), k, file) for k in ("pr", "issue"))
    return Task(
        id=meta["id"],
        title=meta["title"],
        status=meta["status"],
        milestone=meta["milestone"],
        pr=pr,
        body=text[end + 5 :].lstrip("\n"),
        file=file,
        worktree=worktree,
        issue=issue,
    )


def number(value, key, file):
    if value in ("", "null"):
        return None
    if value.isdigit():
        return int(value)
    raise ValueError(f"{file}: {key} must be a number or null, got {value!r}")


def parse_milestones(text):
    """Milestone names from tasks/milestones.md: one "- name" list item each. Pure."""
    return [line[2:].strip() for line in text.splitlines() if line.startswith("- ") and line[2:].strip()]


def set_field(text, key, value):
    """The task file text with one frontmatter field replaced. Pure."""
    end = text.find("\n---\n", 4)
    head, n = re.subn(rf"^{re.escape(key)}:.*$", f"{key}: {value}", text[:end], count=1, flags=re.M)
    if not n:
        raise ValueError(f"no {key} field")
    return head + text[end:]


def prune_done(tasks):
    """Files of the done tasks, which a release removes. Pure."""
    return [t.file for t in tasks if t.status == "done"]


def validate(tasks, milestones=None):
    """Errors for one checkout's tasks; milestones, when given, is the allowed list. Pure."""
    errors = []
    seen = set()
    for t in tasks:
        if not ID_RE.match(t.id):
            errors.append(f"{t.file}: id {t.id!r} is not T-NNNN")
        if not t.file.startswith(t.id + "-"):
            errors.append(f"{t.file}: file name must start with {t.id}-")
        if t.status not in STATUSES:
            errors.append(f"{t.file}: status {t.status!r} is not one of {', '.join(STATUSES)}")
        if t.status in ("review", "done") and t.pr is None:
            errors.append(f"{t.file}: status {t.status} needs a pr number")
        if milestones is not None and t.milestone not in milestones:
            errors.append(f"{t.file}: milestone {t.milestone!r} is not in tasks/milestones.md")
        if t.id in seen:
            errors.append(f"{t.file}: duplicate id {t.id}")
        seen.add(t.id)
    return errors


def merge(tasks, deleted=()):
    """One task per id. Pure.

    The most advanced status wins; on a tie the task's own worktree beats the
    board branch, which beats the base. A task deleted on the board is dropped
    unless its own worktree (or branch) still carries it.
    """

    def key(t):
        return RANK.get(t.status, -1), {MAIN: 0, BOARD: 1}.get(t.worktree, 2)

    best = {}
    for t in tasks:
        if t.id in deleted and t.worktree in (MAIN, BOARD):
            continue
        cur = best.get(t.id)
        if cur is None or key(t) > key(cur):
            best[t.id] = t
    return [best[k] for k in sorted(best)]


def is_active(idle_min, has_process):
    """A claude process in the worktree, or a change in the last few minutes. Pure.

    The process check alone misses most agents: a session keeps the cwd it was
    launched in, so one started from the main checkout that then created its
    worktree still reports the main checkout.
    """
    return has_process or idle_min < ACTIVE_MINUTES


def deep_link(task_id, repo):
    """claude-cli:// link that opens Claude Code with /work-on-task typed in (not sent)."""
    return f"claude-cli://open?q={quote('/work-on-task ' + task_id, safe='')}&repo={quote(repo, safe='')}"


def task_of_path(path):
    """The task id of a path inside a task worktree (.claude/worktrees/T-NNNN-slug), else None. Pure."""
    m = TASK_PATH_RE.search(path)
    return m.group(1) if m else None


def needs_you(status):
    return status in NEEDS_YOU


def agents_by_task(entries):
    """Task id -> AgentInfo from (machine label, machine id, Herdr agent) entries. Pure.

    An agent belongs to the task whose worktree is its working directory; when
    two share a task, the one waiting for the user wins, then a working one.
    """
    order = {"blocked": 4, "done": 3, "working": 2, "idle": 1}
    found = {}
    for machine, machine_id, a in entries:
        task_id = task_of_path(a.get("foreground_cwd") or a.get("cwd") or "")
        if task_id is None:
            continue
        info = AgentInfo(machine=machine, machine_id=machine_id, status=a.get("agent_status", "unknown"), pane_id=a["pane_id"])
        cur = found.get(task_id)
        if cur is None or order.get(info.status, 0) > order.get(cur.status, 0):
            found[task_id] = info
    return found


def render_html(tasks, worktrees, repo, generated, warnings=(), token=None, milestones=(), agents=None):
    """The board as one self-contained page; with a token, the live page tasks.py serve returns. Pure."""
    e = html.escape
    milestones = list(milestones) + sorted({t.milestone for t in tasks} - set(milestones))
    agents = agents or {}
    columns = []
    for status in STATUSES:
        cards = []
        for t in (t for t in tasks if t.status == status):
            wt = worktrees.get(t.worktree)
            meta = [f'<span class="pill">{e(t.milestone)}</span>']
            if t.pr is not None:
                meta.append(f'<a class="pill" href="https://github.com/{e(repo)}/pull/{t.pr}" target="_blank" rel="noopener">#{t.pr}</a>')
            if t.issue is not None:
                meta.append(f'<a class="pill" href="https://github.com/{e(repo)}/issues/{t.issue}" target="_blank" rel="noopener">issue #{t.issue}</a>')
            ag = agents.get(t.id)
            live = ""
            if ag is not None:
                state = '<span class="agent">● agent active</span>' if ag.status == "working" else f'<span class="state">{e(ag.status)}</span>'
                chips = [f'<span class="pill">on {e(ag.machine)}</span>', state]
                if needs_you(ag.status):
                    chips.append(f'<button class="chip needs" data-focus="{e(t.id)}">needs you</button>' if token else '<span class="chip needs">needs you</span>')
                live = f'<div class="live">{"".join(chips)}</div>'
            activity = ""
            if wt is not None and t.worktree not in (MAIN, BOARD) and t.status in ("doing", "review"):
                if wt.remote:
                    activity = (
                        f'<div class="wt"><span class="pill">remote branch (another machine or the cloud)</span><code>{e(wt.branch)}</code>'
                        f"<span>{e(wt.last_commit)}</span><span>{wt.ahead} ahead of origin/main</span></div>"
                    )
                else:
                    agent = '<span class="agent">● agent active</span>' if wt.agent and ag is None else ""
                    activity = (
                        f'<div class="wt">{agent}<code>{e(wt.branch)}</code>'
                        f"<span>{e(wt.last_commit)}</span>"
                        f"<span>{wt.dirty} changed · {wt.ahead} ahead of origin/main · last change {wt.idle_min} min ago</span></div>"
                    )
            command = f'claude "/work-on-task {t.id}"'
            if token:
                launch = f'<button class="btn primary" data-launch="{e(t.id)}">Open in Herdr</button>'
            else:
                launch = f'<a class="btn primary" href="{e(deep_link(t.id, repo))}">Open in Claude</a>'
            cards.append(
                f'<article class="card" id="{e(t.id)}" data-milestone="{e(t.milestone)}"{' data-agent="1"' if ag else ""} '
                f'data-text="{e((t.id + " " + t.title + " " + t.body).lower())}">'
                f'<header><span class="tid">{e(t.id)}</span>{"".join(meta)}</header>'
                f'<h3>{e(t.title)}</h3>{live}{activity}'
                f'<div class="actions">{launch}'
                f'<button class="btn" data-copy="{e(command)}">Copy command</button>'
                f'<button class="btn" data-open="{e(t.id)}">Details</button></div>'
                f'<pre class="body" hidden>{e(t.body)}</pre></article>'
            )
        columns.append(
            f'<section class="col" data-status="{status}"><h2>{status} <span class="count">{len(cards)}</span></h2>'
            f'{"".join(cards) or "<p class=empty>—</p>"}</section>'
        )
    options = "".join(f'<option value="{e(m)}">{e(m)}</option>' for m in milestones)
    notes = "".join(f'<p class="warn">{e(w)}</p>' for w in warnings)
    return PAGE.format(
        generated=e(generated),
        options=options,
        notes=notes,
        columns="".join(columns),
        token=json.dumps(token or ""),
        refresh=(SERVE_JS % (POLL_SECONDS * 1000)) if token else (STATIC_JS % (RELOAD_SECONDS * 1000)),
    )


# Static file: regenerated by a hook whenever an agent edits a task; reload to pick it up, but not mid-typing.
STATIC_JS = "setInterval(() => { if (document.activeElement !== q) location.reload(); }, %d);"

# Served page: swap in a fresh board without losing scroll, filter or the open panel.
SERVE_JS = """setInterval(async () => {
  if (document.activeElement === q) return;
  try {
    const r = await fetch("/?token=" + TOKEN, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    for (const sel of [".board", "#notes", ".gen"]) document.querySelector(sel).innerHTML = doc.querySelector(sel).innerHTML;
    apply();
    if (!panel.hidden) openTask(readHash().open);
  } catch (err) { document.querySelector(".gen").textContent = "Board server unreachable (" + err.message + ")"; }
}, %d);"""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EmailOps Tasks</title>
<style>
:root {{ --bg:#f6f7f9; --panel:#fff; --text:#1c2024; --muted:#646b75; --line:#dfe3e8; --accent:#2f6fde; --ok:#1f8a4c; --warn:#b26b00; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121417; --panel:#1b1e23; --text:#e6e8eb; --muted:#9aa1ab; --line:#2c3138; --accent:#6b9cf5; --ok:#4cc27e; --warn:#e3a33b; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.45 -apple-system, system-ui, sans-serif; }}
.top {{ display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; padding:12px 16px; border-bottom:1px solid var(--line); background:var(--panel); position:sticky; top:0; z-index:2; }}
.top h1 {{ font-size:16px; margin:0; }}
.top .gen {{ color:var(--muted); margin-left:auto; }}
input, select {{ font:inherit; padding:5px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); }}
.warn {{ margin:8px 16px 0; color:var(--warn); }}
.board {{ display:grid; grid-template-columns:repeat(5, minmax(220px, 1fr)); gap:12px; padding:16px; overflow-x:auto; }}
@media (max-width: 760px) {{ .board {{ grid-template-columns:1fr; }} }}
.col h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 8px; }}
.count {{ font-weight:400; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px; margin-bottom:10px; }}
.card header {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; }}
.tid {{ font:12px ui-monospace, monospace; color:var(--muted); }}
.pill {{ font-size:11px; padding:1px 6px; border:1px solid var(--line); border-radius:999px; color:var(--muted); text-decoration:none; }}
.card h3 {{ font-size:14px; margin:6px 0; }}
.wt {{ display:flex; flex-direction:column; gap:2px; font-size:12px; color:var(--muted); margin-bottom:6px; }}
.wt code {{ color:var(--text); }}
.agent {{ color:var(--ok); font-weight:600; }}
.live {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; font-size:12px; margin-bottom:6px; }}
.state {{ color:var(--muted); }}
.chip.needs {{ font:600 11px inherit; padding:1px 8px; border-radius:999px; border:1px solid #d4a800; background:#f5c518; color:#1c2024; cursor:pointer; }}
.actions {{ display:flex; gap:6px; flex-wrap:wrap; }}
.btn {{ font:12px inherit; padding:4px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); cursor:pointer; text-decoration:none; }}
.btn.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
.empty {{ color:var(--muted); }}
.hidden {{ display:none; }}
#panel {{ position:fixed; top:0; right:0; bottom:0; width:min(560px, 100%); background:var(--panel); border-left:1px solid var(--line); padding:16px; overflow:auto; z-index:3; box-shadow:-8px 0 24px rgba(0,0,0,.15); }}
#panel pre {{ white-space:pre-wrap; font:13px/1.5 ui-monospace, monospace; }}
</style></head>
<body>
<div class="top"><h1>Tasks</h1>
<select id="ms"><option value="">All milestones</option>{options}</select>
<input id="q" type="search" placeholder="Search">
<span class="gen">Generated {generated}</span></div>
<div id="notes">{notes}</div>
<main class="board">{columns}</main>
<aside id="panel" hidden><button class="btn" id="close">Close</button><h2 id="ptitle"></h2><pre id="pbody"></pre>
<h3 id="pouth" hidden>Agent output</h3><pre id="pout" hidden></pre></aside>
<script>
const TOKEN = {token};
const ms = document.getElementById("ms"), q = document.getElementById("q"), panel = document.getElementById("panel");
function readHash() {{ const p = new URLSearchParams(location.hash.slice(1)); return {{ ms: p.get("ms") || "", q: p.get("q") || "", open: p.get("open") || "" }}; }}
function writeHash(open) {{ const p = new URLSearchParams(); if (ms.value) p.set("ms", ms.value); if (q.value) p.set("q", q.value); if (open) p.set("open", open); history.replaceState(null, "", "#" + p); }}
function apply() {{
  const term = q.value.toLowerCase();
  document.querySelectorAll(".col").forEach(col => {{
    let n = 0;
    col.querySelectorAll(".card").forEach(c => {{
      const show = (!ms.value || c.dataset.milestone === ms.value) && (!term || c.dataset.text.includes(term));
      c.classList.toggle("hidden", !show); if (show) n++;
    }});
    col.querySelector(".count").textContent = n;
  }});
}}
function openTask(id) {{
  const card = document.getElementById(id); if (!card) return;
  document.getElementById("ptitle").textContent = id + " · " + card.querySelector("h3").textContent;
  document.getElementById("pbody").textContent = card.querySelector(".body").textContent;
  panel.hidden = false; writeHash(id);
  const pout = document.getElementById("pout"), live = Boolean(TOKEN && card.dataset.agent);
  pout.hidden = document.getElementById("pouth").hidden = !live;
  if (live) fetch("/output?token=" + TOKEN + "&task=" + id, {{ cache: "no-store" }}).then(r => r.text()).then(t => {{ pout.textContent = t; }}, () => {{ pout.textContent = "Agent output unavailable"; }});
}}
function post(path, b, label) {{
  b.textContent = "…";
  return fetch(path + (path.includes("?") ? "&" : "?") + "token=" + TOKEN, {{ method: "POST" }}).then(r => r.json()).then(j => {{
    b.textContent = j.ok ? "✓" : "Failed"; b.title = j.error || "";
    setTimeout(() => b.textContent = label, 2500);
    return j;
  }}, () => {{ b.textContent = "Failed"; }});
}}
const s = readHash(); ms.value = s.ms; q.value = s.q; apply(); if (s.open) openTask(s.open);
ms.onchange = q.oninput = () => {{ apply(); writeHash(panel.hidden ? "" : readHash().open); }};
document.getElementById("close").onclick = () => {{ panel.hidden = true; writeHash(""); }};
document.addEventListener("click", ev => {{
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.open) openTask(b.dataset.open);
  if (b.dataset.launch) post("/open?task=" + b.dataset.launch, b, "Open in Herdr");
  if (b.dataset.focus) post("/focus?task=" + b.dataset.focus, b, "needs you");
  if (b.dataset.copy) navigator.clipboard.writeText(b.dataset.copy).then(() => {{ b.textContent = "Copied"; setTimeout(() => b.textContent = "Copy command", 1500); }}, () => {{ b.textContent = "Copy failed"; }});
}});
{refresh}
</script></body></html>
"""


# --- I/O ------------------------------------------------------------------


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def main_root():
    return Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent


def read_tasks(checkout, label, pattern="T-*.md"):
    """Tasks of one checkout (from disk) plus parse errors (as strings)."""
    tasks, errors = [], []
    for path in sorted((checkout / "tasks").glob(pattern)):
        try:
            tasks.append(parse_task(path.read_text(encoding="utf-8"), path.name, label))
        except ValueError as err:
            errors.append(str(err))
    return tasks, errors


def read_ref_tasks(ref, label, prefix="T-"):
    """Tasks committed on a git ref plus parse errors."""
    tasks, errors = [], []
    for name in git("ls-tree", "--name-only", ref, "tasks/").split():
        file = name.removeprefix("tasks/")
        if file.startswith(prefix) and file.endswith(".md"):
            try:
                tasks.append(parse_task(git("show", f"{ref}:{name}"), file, label))
            except ValueError as err:
                errors.append(str(err))
    return tasks, errors


def worktrees():
    """(path, branch) of every worktree; the main checkout first."""
    out, path, result = git("worktree", "list", "--porcelain"), None, []
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = Path(line[9:]), "(detached)"
        elif line.startswith("branch "):
            branch = line[7:].removeprefix("refs/heads/")
        elif not line and path is not None:
            result.append((path, branch))
            path = None
    return result


def claude_cwds():
    """Working directories of running claude processes, by binary name."""
    proc = subprocess.run(["lsof", "-a", "-c", "claude", "-d", "cwd", "-Fn"], capture_output=True, text=True)
    # lsof exits 1 when nothing matches; that is "no agents", not a failure.
    if proc.returncode not in (0, 1):
        raise OSError(proc.stderr.strip() or f"lsof exited {proc.returncode}")
    return [Path(line[1:]) for line in proc.stdout.splitlines() if line.startswith("n")]


def owner_of(cwd, paths):
    """The deepest worktree path containing cwd (the main checkout contains the others)."""
    hits = [p for p in paths if cwd == p or p in cwd.parents]
    return max(hits, key=lambda p: len(p.parts), default=None)


def activity(path, branch, label, has_process, now):
    def out(*args):
        try:
            return git(*args, cwd=path)
        except subprocess.CalledProcessError:
            return ""

    status = out("status", "--porcelain").splitlines()
    ahead = out("rev-list", "--count", "origin/main..HEAD").strip()
    commit_time = out("log", "-1", "--format=%ct").strip()
    times = [int(commit_time)] if commit_time.isdigit() else []
    for line in status:
        # "XY path" or "XY old -> new"; a deleted file has no mtime.
        try:
            times.append((path / line[3:].split(" -> ")[-1].strip('"')).stat().st_mtime)
        except OSError:
            pass
    idle_min = int((now - max(times)) // 60) if times else 10**6
    return WorktreeInfo(
        name=label,
        branch=branch,
        last_commit=out("log", "-1", "--format=%cr · %s").strip(),
        dirty=len(status),
        ahead=int(ahead) if ahead.isdigit() else 0,
        idle_min=idle_min,
        agent=is_active(idle_min, has_process),
    )


def remote_activity(ref, now):
    """WorktreeInfo for a pushed task branch nobody has checked out here."""
    commit_time, summary = git("log", "-1", "--format=%ct%n%cr · %s", ref).split("\n", 1)
    return WorktreeInfo(
        name=ref,
        branch=ref.removeprefix("origin/"),
        last_commit=summary.strip(),
        dirty=0,
        ahead=int(git("rev-list", "--count", f"origin/main..{ref}").strip()),
        idle_min=int((now - int(commit_time)) // 60),
        agent=False,
        remote=True,
    )


def collect():
    """(main checkout, merged tasks, worktree infos, milestones, warnings) as they are right now."""
    root = main_root()
    now = time.time()
    tasks, warnings = [], []

    def add(found, label):
        tasks.extend(found[0])
        warnings.extend(f"{label}: {err}" for err in found[1])

    add(read_ref_tasks(TASK_BASE, MAIN), TASK_BASE)
    milestones = parse_milestones(git("show", f"{TASK_BASE}:tasks/milestones.md"))
    deleted = set()
    board = root / ".claude" / "worktrees" / BOARD
    if board.exists():
        base = git("merge-base", "HEAD", TASK_BASE, cwd=board).strip()
        for line in git("diff", "--name-status", base, "--", "tasks/", cwd=board).splitlines():
            change, name = line.split("\t")[0], line.split("\t")[-1]
            file = name.removeprefix("tasks/")
            if change == "D" and file.startswith("T-"):
                deleted.add(file[:6])
            elif file.startswith("T-"):
                add(read_tasks(board, BOARD, file), BOARD)
        milestones = read_milestones(board)

    trees = worktrees()
    try:
        cwds = claude_cwds()
    except OSError as err:
        warnings.append(f"lsof unavailable, live agents not shown: {err}")
        cwds = []
    busy = {owner_of(c, [p for p, _ in trees]) for c in cwds}
    infos = {}
    for path, branch in trees:
        m = TASK_BRANCH_RE.match(branch)
        if m:
            add(read_tasks(path, path.name, f"{m.group(1)}-*.md"), path.name)
            infos[path.name] = activity(path, branch, path.name, path in busy, now)
    local = {b for _, b in trees}
    refs = git("for-each-ref", "--format=%(refname:short)", *(f"refs/remotes/origin/{k}/T-*" for k in ("feature", "fix", "refactor")))
    for ref in refs.split():
        branch = ref.removeprefix("origin/")
        m = TASK_BRANCH_RE.match(branch)
        if m and branch not in local:
            add(read_ref_tasks(ref, ref, m.group(1)), ref)
            infos[ref] = remote_activity(ref, now)
    return root, merge(tasks, deleted), infos, milestones, warnings


def repo_slug():
    url = git("remote", "get-url", "origin").strip()
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        raise ValueError(f"cannot read owner/repo from origin {url!r}")
    return m.group(1)


def read_milestones(checkout):
    path = checkout / "tasks" / "milestones.md"
    return parse_milestones(path.read_text(encoding="utf-8")) if path.exists() else []


def cmd_check():
    tasks, errors = read_tasks(Path.cwd(), MAIN)
    errors += validate(tasks, read_milestones(Path.cwd()))
    for err in errors:
        print(err, file=sys.stderr)
    print(f"{len(tasks)} tasks, {len(errors)} errors")
    return 1 if errors else 0


def build_page(token=None, agents=None, warnings=()):
    """(main checkout, page) built from collect()."""
    root, tasks, infos, milestones, found_warnings = collect()
    stamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S" if token else "%d/%m/%Y %H:%M")
    page = render_html(tasks, infos, repo_slug(), stamp, [*warnings, *found_warnings], token, milestones, agents)
    return root, page


def cmd_html(out):
    root, page = build_page()
    target = Path(out) if out else root / "tasks" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, target)  # never leave a half-written page for the auto-reload to pick up
    print(target.as_uri())
    return 0


def cmd_prune_done():
    """git rm the done tasks of this checkout (the release skill runs it before its commit)."""
    tasks, errors = read_tasks(Path.cwd(), MAIN)
    if errors:
        raise ValueError("; ".join(errors))
    files = prune_done(tasks)
    for f in files:
        git("rm", "-q", f"tasks/{f}")
        print(f"removed tasks/{f}")
    print(f"{len(files)} done tasks pruned")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("prune-done")
    html_p = sub.add_parser("html")
    html_p.add_argument("--out")
    args = parser.parse_args()
    if args.cmd == "prune-done":
        return cmd_prune_done()
    return cmd_check() if args.cmd == "check" else cmd_html(args.out)


if __name__ == "__main__":
    sys.exit(main())
