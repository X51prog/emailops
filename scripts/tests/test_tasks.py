"""The task files under tasks/: parsing, validation, merging across worktrees, the HTML board."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tasks import (  # noqa: E402
    Task,
    WorktreeInfo,
    agent_name,
    authorized,
    deep_link,
    is_active,
    merge,
    parse_task,
    pick_workspace,
    render_html,
    task_worktree,
    validate,
)


def task_text(id="T-0001", title="A task", status="todo", milestone="0.7.0", pr="null", body="Body.\n"):
    return f"---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\npr: {pr}\n---\n\n{body}"


def task(id="T-0001", status="todo", pr=None, title="A task", body="Body.\n", worktree="main"):
    return Task(id=id, title=title, status=status, milestone="0.7.0", pr=pr, body=body, file=f"{id}-a-task.md", worktree=worktree)


# --- parse_task -----------------------------------------------------------


def test_parse_reads_frontmatter_and_body():
    t = parse_task(task_text(pr="161", body="Context.\n"), "T-0001-a-task.md", "main")
    assert (t.id, t.title, t.status, t.milestone, t.pr, t.body) == ("T-0001", "A task", "todo", "0.7.0", 161, "Context.\n")


def test_parse_null_pr_is_none():
    assert parse_task(task_text(pr="null"), "T-0001-a-task.md", "main").pr is None


def test_parse_without_frontmatter_raises():
    try:
        parse_task("# no frontmatter\n", "T-0001-x.md", "main")
    except ValueError as e:
        assert "frontmatter" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_parse_non_numeric_pr_raises():
    try:
        parse_task(task_text(pr="abc"), "T-0001-a-task.md", "main")
    except ValueError as e:
        assert "pr" in str(e)
    else:
        raise AssertionError("expected ValueError")


# --- validate -------------------------------------------------------------


def test_valid_tasks_have_no_errors():
    assert validate([task("T-0001"), task("T-0002", status="done", pr=12)]) == []


def test_unknown_status_is_an_error():
    assert any("status" in e for e in validate([task(status="blocked")]))


def test_duplicate_ids_are_an_error():
    errors = validate([task("T-0001"), task("T-0001")])
    assert any("duplicate" in e for e in errors)


def test_review_or_done_without_pr_is_an_error():
    for status in ("review", "done"):
        assert any("pr" in e for e in validate([task(status=status, pr=None)])), status


def test_file_name_must_start_with_the_id():
    t = task("T-0001")
    t.file = "T-0002-a-task.md"
    assert any("file name" in e for e in validate([t]))


def test_malformed_id_is_an_error():
    assert any("id" in e for e in validate([task(id="0001")]))


# --- merge ----------------------------------------------------------------


def test_most_advanced_status_wins_across_worktrees():
    merged = merge([task(status="todo", worktree="main"), task(status="doing", worktree="wt-a")])
    assert len(merged) == 1
    assert (merged[0].status, merged[0].worktree) == ("doing", "wt-a")


def test_done_beats_doing():
    merged = merge([task(status="doing", worktree="wt-a"), task(status="done", pr=3, worktree="main")])
    assert merged[0].status == "done"


def test_tie_prefers_the_non_main_worktree():
    merged = merge([task(status="doing", worktree="main"), task(status="doing", worktree="wt-a")])
    assert merged[0].worktree == "wt-a"


def test_dropped_is_kept_when_nothing_else_moved():
    assert merge([task(status="dropped")])[0].status == "dropped"


def test_a_task_only_in_one_worktree_is_kept():
    merged = merge([task("T-0001"), task("T-0002", worktree="wt-a")])
    assert [t.id for t in merged] == ["T-0001", "T-0002"]


# --- deep_link ------------------------------------------------------------


def test_deep_link_encodes_the_prompt_and_repo():
    assert deep_link("T-0001", "owner/repo") == "claude-cli://open?q=%2Fwork-on-task%20T-0001&repo=owner%2Frepo"


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


# --- render_html ----------------------------------------------------------


def render(tasks, worktrees=None, **kw):
    return render_html(tasks, worktrees or {}, repo="owner/repo", generated="13/10/2026 10:00", **kw)


def test_html_escapes_title_and_body():
    html = render([task(title="<b>x</b>", body="<script>alert(1)</script>")])
    assert "<b>x</b>" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_html_carries_the_deep_link_and_copy_command():
    html = render([task()])
    assert "claude-cli://open?q=%2Fwork-on-task%20T-0001&amp;repo=owner%2Frepo" in html
    assert 'claude &quot;/work-on-task T-0001&quot;' in html


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


def test_html_auto_refreshes_and_shows_generation_time():
    html = render([task()])
    # A timed location.reload() keeps the URL hash (filter, search, open task); a meta refresh would too, but cannot pause while the reader is typing.
    assert "location.reload()" in html
    assert "13/10/2026 10:00" in html


def test_html_contains_no_absolute_paths():
    wt = {"wt-a": WorktreeInfo(name="wt-a", branch="feature/T-0001-x", last_commit="2h ago · feat: x", dirty=2, ahead=1, idle_min=3, agent=True)}
    html = render([task(status="doing", worktree="wt-a")], wt)
    assert "/Users/" not in html
    assert "/home/" not in html


def test_html_shows_worktree_branch_and_live_agent():
    wt = {"wt-a": WorktreeInfo(name="wt-a", branch="feature/T-0001-x", last_commit="2h ago · feat: x", dirty=2, ahead=1, idle_min=3, agent=True)}
    html = render([task(status="doing", worktree="wt-a")], wt)
    assert "feature/T-0001-x" in html
    assert "agent active" in html


def test_html_links_the_pr():
    assert "https://github.com/owner/repo/pull/42" in render([task(status="review", pr=42)])


def test_html_reports_a_warning():
    assert "lsof unavailable" in render([task()], warnings=["lsof unavailable"])


def test_html_hides_worktree_activity_for_a_task_nobody_started():
    # Every worktree branched off main carries every todo task; only a started one is that worktree's work.
    wt = {"wt-a": WorktreeInfo(name="wt-a", branch="feature/other-work", last_commit="1h ago · x", dirty=0, ahead=3, idle_min=3, agent=True)}
    html = render([task(status="todo", worktree="wt-a")], wt)
    assert "feature/other-work" not in html
    assert "agent active" not in html


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


# --- is_active ------------------------------------------------------------


def test_a_claude_process_in_the_worktree_means_active():
    assert is_active(idle_min=500, has_process=True)


def test_a_recent_change_means_active_even_without_a_process_there():
    # A session launched from the main checkout keeps that cwd after it creates its worktree.
    assert is_active(idle_min=4, has_process=False)


def test_an_old_change_and_no_process_is_idle():
    assert not is_active(idle_min=45, has_process=False)


def test_html_shows_minutes_since_last_change():
    wt = {"wt-a": WorktreeInfo(name="wt-a", branch="feature/T-0001-x", last_commit="2h ago · feat: x", dirty=2, ahead=1, idle_min=7, agent=False)}
    assert "last change 7 min ago" in render([task(status="doing", worktree="wt-a")], wt)
