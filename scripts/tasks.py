#!/usr/bin/env python3
"""Validate the task files under tasks/ and render them as a live HTML board.

Every task is one Markdown file, tasks/T-NNNN-slug.md, with a frontmatter block
(id, title, status, milestone, pr) and a free-form body. The files are the
source of truth; there is no generated index in git, so agents working on
different tasks in different worktrees never touch the same file.

Usage:
  tasks.py check
      Validate the task files of this checkout. Exit 1 on any error.
  tasks.py html [--out PATH]
      Read tasks/ from every worktree of the repo (uncommitted edits included),
      keep the most advanced status of each task, add per-worktree activity
      (branch, last commit, dirty files, commits ahead of origin/main, minutes since
      the last change, and whether an agent is on it: a claude process inside it or a
      change in the last 10 minutes) and write one self-contained page. Default output:
      <main checkout>/tasks/index.html (gitignored). Read-only otherwise. When the
      emailops-task:// handler is installed (make task-handler), "Open" goes to Herdr.
  tasks.py open-in-herdr URL
      Handle an emailops-task://open?task=T-NNNN link: focus the task's agent if
      Herdr already runs one, otherwise create (or reuse) the task's worktree,
      open a Herdr tab there, start Claude and type /work-on-task T-NNNN without
      sending it. Starting in the worktree, not the main checkout, means the
      session sees the repo's skills whatever branch the main checkout is on.
"""

# The URL handler runs macOS /usr/bin/python3 (3.9): keep annotations lazy.
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

STATUSES = ("todo", "doing", "review", "done", "dropped")
# Merge order across worktrees: a later status means more progress.
RANK = {"todo": 0, "doing": 1, "review": 2, "dropped": 3, "done": 4}
FIELDS = ("id", "title", "status", "milestone", "pr")
ID_RE = re.compile(r"^T-\d{4}$")
MAIN = "main"  # label of the main checkout
RELOAD_SECONDS = 20
ACTIVE_MINUTES = 10  # a worktree changed this recently counts as having an agent on it
SCHEME = "emailops-task"
TASK_BASE = "chore/sdlc-automation"  # TODO: origin/main once this branch is merged (work-on-task lives there)
HANDLER_APP = Path.home() / "Applications" / "EmailOps Task Handler.app"  # installed by make task-handler


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


@dataclass
class WorktreeInfo:
    name: str
    branch: str
    last_commit: str
    dirty: int
    ahead: int
    idle_min: int  # minutes since the last change (dirty file or commit)
    agent: bool


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
    pr = meta["pr"]
    if pr in ("", "null"):
        pr = None
    elif pr.isdigit():
        pr = int(pr)
    else:
        raise ValueError(f"{file}: pr must be a number or null, got {pr!r}")
    return Task(
        id=meta["id"],
        title=meta["title"],
        status=meta["status"],
        milestone=meta["milestone"],
        pr=pr,
        body=text[end + 5 :].lstrip("\n"),
        file=file,
        worktree=worktree,
    )


def validate(tasks):
    """Errors for one checkout's tasks. Pure."""
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
        if t.id in seen:
            errors.append(f"{t.file}: duplicate id {t.id}")
        seen.add(t.id)
    return errors


def merge(tasks):
    """One task per id: the most advanced status wins; on a tie, a worktree beats main. Pure."""
    best = {}
    for t in tasks:
        cur = best.get(t.id)
        if cur is None or (RANK.get(t.status, -1), t.worktree != MAIN) > (RANK.get(cur.status, -1), cur.worktree != MAIN):
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


def herdr_link(task_id):
    """emailops-task:// link, handled by open-in-herdr once make task-handler installed it."""
    return f"{SCHEME}://open?task={task_id}"


def task_from_url(url):
    """The task id in an emailops-task:// link. Pure.

    Any web page can fire the scheme, so anything but one well-formed id is refused.
    """
    parts = urlsplit(url)
    ids = parse_qs(parts.query).get("task", [])
    if parts.scheme != SCHEME or parts.netloc != "open" or len(ids) != 1 or not ID_RE.match(ids[0]):
        raise ValueError(f"not a task link: {url!r}")
    return ids[0]


def task_worktree(file_name, root):
    """(path, branch) of a task's worktree, named after its file: T-0002-slug.md. Pure."""
    stem = Path(file_name).stem
    return root / ".claude" / "worktrees" / stem, f"feature/{stem}"


def agent_name(task_id):
    """Herdr agent name for a task (names are lowercase)."""
    return task_id.lower()


def pick_workspace(workspaces, label):
    """Id of the Herdr workspace labelled after the repo, the focused one first. Pure."""
    hits = [w for w in workspaces if w["label"] == label]
    hits.sort(key=lambda w: not w["focused"])
    return hits[0]["workspace_id"] if hits else None


def render_html(tasks, worktrees, repo, generated, warnings=(), launcher="claude"):
    """The board as one self-contained page. Pure."""
    e = html.escape
    milestones = sorted({t.milestone for t in tasks})
    columns = []
    for status in STATUSES:
        cards = []
        for t in (t for t in tasks if t.status == status):
            wt = worktrees.get(t.worktree)
            meta = [f'<span class="pill">{e(t.milestone)}</span>']
            if t.pr is not None:
                meta.append(f'<a class="pill" href="https://github.com/{e(repo)}/pull/{t.pr}" target="_blank" rel="noopener">#{t.pr}</a>')
            activity = ""
            # Every worktree off main carries every todo task: only a started one is that worktree's work.
            if wt is not None and t.worktree != MAIN and t.status in ("doing", "review"):
                agent = '<span class="agent">● agent active</span>' if wt.agent else ""
                activity = (
                    f'<div class="wt">{agent}<code>{e(wt.branch)}</code>'
                    f"<span>{e(wt.last_commit)}</span>"
                    f"<span>{wt.dirty} changed · {wt.ahead} ahead of origin/main · last change {wt.idle_min} min ago</span></div>"
                )
            command = f'claude "/work-on-task {t.id}"'
            open_href, open_label = (herdr_link(t.id), "Open in Herdr") if launcher == "herdr" else (deep_link(t.id, repo), "Open in Claude")
            cards.append(
                f'<article class="card" id="{e(t.id)}" data-milestone="{e(t.milestone)}" '
                f'data-text="{e((t.id + " " + t.title + " " + t.body).lower())}">'
                f'<header><span class="tid">{e(t.id)}</span>{"".join(meta)}</header>'
                f'<h3>{e(t.title)}</h3>{activity}'
                f'<div class="actions"><a class="btn primary" href="{e(open_href)}">{open_label}</a>'
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
        reload_ms=RELOAD_SECONDS * 1000,
    )


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
{notes}
<main class="board">{columns}</main>
<aside id="panel" hidden><button class="btn" id="close">Close</button><h2 id="ptitle"></h2><pre id="pbody"></pre></aside>
<script>
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
}}
const s = readHash(); ms.value = s.ms; q.value = s.q; apply(); if (s.open) openTask(s.open);
ms.onchange = q.oninput = () => {{ apply(); writeHash(panel.hidden ? "" : readHash().open); }};
document.getElementById("close").onclick = () => {{ panel.hidden = true; writeHash(""); }};
document.addEventListener("click", ev => {{
  const b = ev.target.closest("button"); if (!b) return;
  if (b.dataset.open) openTask(b.dataset.open);
  if (b.dataset.copy) navigator.clipboard.writeText(b.dataset.copy).then(() => {{ b.textContent = "Copied"; setTimeout(() => b.textContent = "Copy command", 1500); }}, () => {{ b.textContent = "Copy failed"; }});
}});
// Regenerated by a hook whenever an agent edits a task; reload to pick it up, but not mid-typing.
setInterval(() => {{ if (document.activeElement !== q) location.reload(); }}, {reload_ms});
</script></body></html>
"""


# --- I/O ------------------------------------------------------------------


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def main_root():
    return Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent


def read_tasks(checkout, label):
    """Tasks of one checkout plus parse errors (as strings)."""
    tasks, errors = [], []
    for path in sorted((checkout / "tasks").glob("T-*.md")):
        try:
            tasks.append(parse_task(path.read_text(encoding="utf-8"), path.name, label))
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


def repo_slug():
    url = git("remote", "get-url", "origin").strip()
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        raise ValueError(f"cannot read owner/repo from origin {url!r}")
    return m.group(1)


def cmd_check():
    tasks, errors = read_tasks(Path.cwd(), MAIN)
    errors += validate(tasks)
    for err in errors:
        print(err, file=sys.stderr)
    print(f"{len(tasks)} tasks, {len(errors)} errors")
    return 1 if errors else 0


def cmd_html(out):
    root = main_root()
    trees = worktrees()
    warnings = []
    try:
        cwds = claude_cwds()
    except OSError as err:
        warnings.append(f"lsof unavailable, live agents not shown: {err}")
        cwds = []
    paths = [p for p, _ in trees]
    busy = {owner_of(c, paths) for c in cwds}
    found, infos = [], {}
    for path, branch in trees:
        label = MAIN if path == root else path.name
        tasks, errors = read_tasks(path, label)
        found += tasks
        warnings += [f"{label}: {err}" for err in errors]
        if tasks:
            infos[label] = activity(path, branch, label, path in busy, time.time())
    launcher = "herdr" if HANDLER_APP.exists() else "claude"
    page = render_html(merge(found), infos, repo_slug(), datetime.now().strftime("%d/%m/%Y %H:%M"), warnings, launcher)
    target = Path(out) if out else root / "tasks" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, target)  # never leave a half-written page for the auto-reload to pick up
    print(target.as_uri())
    return 0


def herdr(*args):
    """Run a Herdr CLI command and return its JSON reply."""
    # The URL handler runs with launchd's PATH, which lacks the default install dir.
    exe = shutil.which("herdr") or str(Path.home() / ".local" / "bin" / "herdr")
    proc = subprocess.run([exe, *map(str, args)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"herdr {' '.join(map(str, args))}: {proc.stderr.strip() or proc.returncode}")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def cmd_open_in_herdr(url):
    task_id = task_from_url(url)
    os.chdir(Path(__file__).resolve().parent)  # the URL handler starts in /
    root = main_root()
    trees = worktrees()
    files = {t.file for path, _ in trees for t in read_tasks(path, path.name)[0] if t.id == task_id}
    if len(files) != 1:
        raise ValueError(f"task {task_id}: expected one file across worktrees, found {sorted(files) or 'none'}")
    name = agent_name(task_id)
    try:
        herdr("agent", "focus", name)
        return 0  # that task already has a live agent
    except RuntimeError:
        pass
    path, branch = task_worktree(files.pop(), root)
    cwd = next((p for p, b in trees if b == branch), None)
    if cwd is None:
        if subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], capture_output=True).returncode == 0:
            git("worktree", "add", str(path), branch)  # the branch outlived its worktree
        else:
            git("worktree", "add", "-b", branch, str(path), TASK_BASE)
        cwd = path
    ws = pick_workspace(herdr("workspace", "list")["result"]["workspaces"], root.name)
    if ws is None:
        made = herdr("workspace", "create", "--cwd", cwd, "--label", root.name, "--focus")["result"]
    else:
        made = herdr("tab", "create", "--workspace", ws, "--cwd", cwd, "--label", task_id, "--focus")["result"]
        herdr("workspace", "focus", ws)
    pane = made["root_pane"]["pane_id"]
    herdr("agent", "start", name, "--kind", "claude", "--pane", pane)
    herdr("pane", "send-text", pane, f"/work-on-task {task_id}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    html_p = sub.add_parser("html")
    html_p.add_argument("--out")
    open_p = sub.add_parser("open-in-herdr")
    open_p.add_argument("url")
    args = parser.parse_args()
    if args.cmd == "open-in-herdr":
        return cmd_open_in_herdr(args.url)
    return cmd_check() if args.cmd == "check" else cmd_html(args.out)


if __name__ == "__main__":
    sys.exit(main())
