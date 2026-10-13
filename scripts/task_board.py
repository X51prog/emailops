#!/usr/bin/env python3
"""Serve the task board live on 127.0.0.1 and act on it through Herdr.

Usage:
  task_board.py [--port N]
      Print the board's URL (a random token in it guards every request) and
      serve it until Ctrl+C. Each refresh re-reads the tasks (see tasks.py) and
      the coding agents Herdr runs here and on its saved machines; the page
      swaps in the new board every few seconds. From the page:
      - Open in Herdr: focus the task's agent, or create (or reuse) the task's
        worktree, open a Herdr tab there, start Claude and type
        /work-on-task T-NNNN without sending it. Starting in the worktree, not
        the main checkout, means the session sees the repo's skills whatever
        branch the main checkout is on.
      - needs you: focus the agent waiting for input and raise the terminal
        app Herdr runs in.
      - Details: the agent's latest output.
"""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tasks import ID_RE, TASK_BASE, agents_by_task, build_page, collect, git, worktrees

PORT = 8780
FETCH_SECONDS = 60  # how often the server fetches origin, to see task branches pushed elsewhere
OUTPUT_LINES = 80


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


def authorized(method, path, headers, token, port):
    """Whether a request may reach the served board. Pure.

    Any page open in the browser can send requests to 127.0.0.1, and the board can
    start agents: require the URL token, a local Host (a rebound DNS name keeps its
    own), and on POST a local Origin.
    """
    local = {f"127.0.0.1:{port}", f"localhost:{port}"}
    given = parse_qs(urlsplit(path).query).get("token", [""])[0]
    if headers.get("Host") not in local or not hmac.compare_digest(given, token):
        return False
    return method != "POST" or headers.get("Origin", "").removeprefix("http://") in local


def read_args(status):
    """herdr agent read arguments for an agent in this state. Pure.

    Herdr captures scrollback only while the agent is idle; otherwise read the
    screen, which for a blocked agent shows the question it waits on.
    """
    if status in ("idle", "done"):
        return ("--source", "recent-unwrapped", "--lines", str(OUTPUT_LINES))
    return ("--source", "visible")


def terminal_of(procs):
    """The .app that hosts the Herdr client, from {pid: (ppid, command)}. Pure."""
    for pid, (_, command) in procs.items():
        if Path(command).name != "herdr":
            continue
        seen = set()
        while pid in procs and pid not in seen:
            seen.add(pid)
            pid, command = procs[pid]
            if ".app/Contents/MacOS/" in command:
                return command.split(".app/Contents/MacOS/")[0] + ".app"
    return None


# --- I/O ------------------------------------------------------------------


def herdr(*args, raw=False):
    """Run a Herdr CLI command and return its JSON reply (or its text with raw)."""
    exe = shutil.which("herdr") or str(Path.home() / ".local" / "bin" / "herdr")
    proc = subprocess.run([exe, *map(str, args)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"herdr {' '.join(map(str, args))}: {proc.stderr.strip() or proc.returncode}")
    if raw:
        return proc.stdout
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def on_machine(machine_id, *args):
    return ("--machine", machine_id, *args) if machine_id else args


def local_machine():
    try:
        return subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return socket.gethostname()


def live_agents():
    """(task id -> AgentInfo, warnings) from Herdr here and on its enabled saved machines."""
    try:
        entries = [(local_machine(), None, a) for a in herdr("agent", "list")["result"]["agents"]]
        machines = herdr("machine", "list", "--json")
    except (OSError, RuntimeError) as err:
        return {}, [f"Herdr unavailable, live agents not shown: {err}"]
    warnings = []
    for m in machines:
        if not m.get("enabled"):
            continue
        try:
            entries += [(m["label"], m["id"], a) for a in herdr("--machine", m["id"], "agent", "list")["result"]["agents"]]
        except RuntimeError as err:
            warnings.append(f"Herdr machine {m['label']} unreachable: {err}")
    return agents_by_task(entries), warnings


def agent_of(task_id):
    agent = live_agents()[0].get(task_id)
    if agent is None:
        raise ValueError(f"no live agent for {task_id}")
    return agent


def raise_terminal():
    """Bring the app that hosts the Herdr client to the front (best effort: it may be closed)."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, check=True).stdout
    procs = {}
    for line in out.splitlines():
        pid, ppid, command = line.split(None, 2)
        procs[int(pid)] = (int(ppid), command)
    app = terminal_of(procs)
    if app:
        subprocess.run(["open", "-a", app], check=True)


def focus(task_id):
    agent = agent_of(task_id)
    herdr(*on_machine(agent.machine_id, "agent", "focus", agent.pane_id))
    raise_terminal()


def agent_output(task_id):
    agent = agent_of(task_id)
    return herdr(*on_machine(agent.machine_id, "agent", "read", agent.pane_id, *read_args(agent.status)), raw=True)


def open_in_herdr(task_id):
    if not ID_RE.match(task_id):
        raise ValueError(f"not a task id: {task_id!r}")
    if task_id in live_agents()[0]:
        return focus(task_id)
    root, tasks, *_ = collect()
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"no task {task_id}")
    path, branch = task_worktree(task.file, root)
    cwd = next((p for p, b in worktrees() if b == branch), None)
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
    herdr("agent", "start", agent_name(task_id), "--kind", "claude", "--pane", pane)
    herdr("pane", "send-text", pane, f"/work-on-task {task_id}")
    raise_terminal()


def fetch_forever():
    """Keep origin's task branches current, so work pushed from elsewhere shows up."""
    stop = threading.Event()
    while not stop.wait(FETCH_SECONDS):
        proc = subprocess.run(["git", "fetch", "-q", "--prune", "origin"], capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"git fetch: {proc.stderr.strip()}", file=sys.stderr)


def serve(port):
    token = secrets.token_urlsafe(16)
    actions = {"/open": open_in_herdr, "/focus": focus}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, kind):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def task(self):
            return parse_qs(urlsplit(self.path).query).get("task", [""])[0]

        def do_GET(self):
            route = urlsplit(self.path).path
            if not authorized("GET", self.path, self.headers, token, port) or route not in ("/", "/output"):
                return self.reply(404, "not found", "text/plain")
            try:
                if route == "/output":
                    return self.reply(200, agent_output(self.task()), "text/plain; charset=utf-8")
                agents, warnings = live_agents()
                self.reply(200, build_page(token, agents, warnings)[1], "text/html; charset=utf-8")
            except (subprocess.CalledProcessError, OSError, ValueError, RuntimeError) as err:
                print(f"GET {route}: {err}", file=sys.stderr)
                self.reply(500, f"failed: {err}", "text/plain")

        def do_POST(self):
            route = urlsplit(self.path).path
            if not authorized("POST", self.path, self.headers, token, port) or route not in actions:
                return self.reply(404, "not found", "text/plain")
            try:
                actions[route](self.task())
                self.reply(200, json.dumps({"ok": True}), "application/json")
            except (ValueError, RuntimeError, subprocess.CalledProcessError) as err:
                print(f"POST {route} {self.task()}: {err}", file=sys.stderr)
                self.reply(200, json.dumps({"ok": False, "error": str(err)}), "application/json")

        def log_message(self, *args):
            pass  # the page polls every few seconds; errors are printed where they happen

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=fetch_forever, daemon=True).start()
    print(f"http://127.0.0.1:{port}/?token={token}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=PORT)
    return serve(parser.parse_args().port)


if __name__ == "__main__":
    sys.exit(main())
