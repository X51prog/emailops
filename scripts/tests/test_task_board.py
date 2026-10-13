"""The live board server: request authorization and launching tasks in Herdr."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from task_board import (  # noqa: E402
    agent_name,
    artifact_target,
    authorized,
    pick_workspace,
    read_args,
    task_worktree,
    terminal_of,
)
from tasks import Task, render_html  # noqa: E402


def task(id="T-0001", status="todo"):
    return Task(id=id, title="A task", status=status, milestone="0.7.0", pr=None, body="Body.\n", file=f"{id}-a-task.md", worktree="main")


def render(tasks, **kw):
    return render_html(tasks, {}, repo="owner/repo", generated="13/10/2026 10:00", **kw)


# --- Herdr launcher -------------------------------------------------------


def test_agent_name_is_a_valid_herdr_name():
    assert agent_name("T-0007") == "t-0007"


def test_pick_workspace_prefers_the_focused_one_with_the_repo_label():
    ws = [
        {"workspace_id": "w1", "label": "emailopsv2", "focused": False},
        {"workspace_id": "w2", "label": "other", "focused": True},
        {"workspace_id": "w3", "label": "emailopsv2", "focused": True},
    ]
    assert pick_workspace(ws, "emailopsv2") == "w3"


def test_pick_workspace_falls_back_to_the_first_match():
    ws = [{"workspace_id": "w2", "label": "other", "focused": True}, {"workspace_id": "w4", "label": "emailopsv2", "focused": False}]
    assert pick_workspace(ws, "emailopsv2") == "w4"


def test_pick_workspace_without_a_match_is_none():
    assert pick_workspace([{"workspace_id": "w2", "label": "other", "focused": True}], "emailopsv2") is None


def test_task_worktree_is_named_after_the_task_file():
    path, branch = task_worktree("T-0002-chat-app-control-tools.md", pathlib.Path("/repo"))
    assert path == pathlib.Path("/repo/.claude/worktrees/T-0002-chat-app-control-tools")
    assert branch == "feature/T-0002-chat-app-control-tools"


def test_served_page_launches_through_the_server():
    html = render([task()], token="tok123")
    assert 'data-launch="T-0001"' in html
    assert "Open in Herdr" in html
    assert "claude-cli://" not in html
    assert '"tok123"' in html


def test_served_page_refreshes_in_place_instead_of_reloading():
    html = render([task()], token="tok123")
    assert "location.reload()" not in html
    assert "DOMParser" in html


# --- authorized -----------------------------------------------------------


def req(method="GET", path="/?token=tok", host="127.0.0.1:8780", origin=None):
    headers = {"Host": host}
    if origin:
        headers["Origin"] = origin
    return authorized(method, path, headers, token="tok", port=8780)


def test_get_with_the_token_on_localhost_is_allowed():
    assert req()
    assert req(host="localhost:8780")


def test_missing_or_wrong_token_is_refused():
    assert not req(path="/")
    assert not req(path="/?token=nope")


def test_foreign_host_header_is_refused():
    # DNS rebinding: a page on evil.example resolving to 127.0.0.1 still sends its own Host.
    assert not req(host="evil.example:8780")


def test_post_needs_a_local_origin():
    assert req("POST", "/open?token=tok&task=T-0001", origin="http://127.0.0.1:8780")
    assert not req("POST", "/open?token=tok&task=T-0001")
    assert not req("POST", "/open?token=tok&task=T-0001", origin="https://evil.example")




# --- terminal_of ------------------------------------------------------------


def test_terminal_of_walks_up_from_the_herdr_client_to_its_app():
    procs = {
        2187: (2186, "/Users/u/.local/bin/herdr"),
        2186: (878, "herdr"),
        878: (877, "-/bin/zsh"),
        877: (741, "/usr/bin/login"),
        741: (1, "/Applications/cmux.app/Contents/MacOS/cmux"),
        1: (0, "/sbin/launchd"),
    }
    assert terminal_of(procs) == "/Applications/cmux.app"


def test_terminal_of_without_herdr_is_none():
    assert terminal_of({1: (0, "/sbin/launchd")}) is None


# --- read_args --------------------------------------------------------------


def test_an_idle_agent_is_read_with_its_scrollback():
    assert read_args("idle") == ("--source", "recent-unwrapped", "--lines", "80")
    assert read_args("done") == ("--source", "recent-unwrapped", "--lines", "80")


def test_a_busy_or_blocked_agent_is_read_from_its_screen():
    # Herdr refuses scrollback while the agent is not idle; the screen shows the pending question.
    for status in ("working", "blocked", "unknown"):
        assert read_args(status) == ("--source", "visible")


def test_the_token_may_come_from_the_board_cookie():
    # A report's relative assets (css, images) are fetched without the URL token.
    assert authorized("GET", "/a/T-0001/0/style.css", {"Host": "127.0.0.1:8780", "Cookie": "x=1; board=tok"}, token="tok", port=8780)
    assert not authorized("GET", "/a/T-0001/0/style.css", {"Host": "127.0.0.1:8780", "Cookie": "board=nope"}, token="tok", port=8780)


# --- artifact_target --------------------------------------------------------


def test_artifact_target_serves_the_file_and_its_siblings():
    base = "/w/reports/run1/index.html"
    assert artifact_target(base, "index.html") == pathlib.Path("/w/reports/run1/index.html")
    assert artifact_target(base, "assets/style.css") == pathlib.Path("/w/reports/run1/assets/style.css")


def test_artifact_target_refuses_to_leave_the_artifact_folder():
    for rel in ("../secret.txt", "assets/../../x", "/etc/passwd", ""):
        try:
            artifact_target("/w/reports/run1/index.html", rel)
        except ValueError:
            continue
        raise AssertionError(f"served {rel!r}")
