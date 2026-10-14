"""The task files under tasks/: parsing, validation, merging across worktrees, the HTML board."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tasks import (  # noqa: E402
    AgentInfo,
    Task,
    WorktreeInfo,
    deep_link,
    is_active,
    add_artifact,
    add_milestone,
    agents_by_task,
    edit_location,
    excerpt,
    merge,
    milestone_key,
    new_task_text,
    next_id,
    needs_you,
    parse_milestones,
    parse_task,
    prune_done,
    render_html,
    render_markdown,
    set_field,
    slugify,
    task_of_path,
    validate,
)


def task_text(id="T-0001", title="A task", status="todo", milestone="0.7.0", pr="null", body="Body.\n"):
    return f"---\nid: {id}\ntitle: {title}\nstatus: {status}\nmilestone: {milestone}\npr: {pr}\n---\n\n{body}"


def task(id="T-0001", status="todo", pr=None, title="A task", body="Body.\n", worktree="main", milestone="0.7.0"):
    return Task(id=id, title=title, status=status, milestone=milestone, pr=pr, body=body, file=f"{id}-a-task.md", worktree=worktree)


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


def test_parse_reads_an_optional_issue():
    assert parse_task(task_text() + "", "T-0001-a-task.md", "main").issue is None
    text = task_text().replace("pr: null\n", "pr: null\nissue: 42\n")
    assert parse_task(text, "T-0001-a-task.md", "main").issue == 42


def test_parse_non_numeric_issue_raises():
    text = task_text().replace("pr: null\n", "pr: null\nissue: soon\n")
    try:
        parse_task(text, "T-0001-a-task.md", "main")
    except ValueError as e:
        assert "issue" in str(e)
    else:
        raise AssertionError("expected ValueError")


# --- milestones -------------------------------------------------------------


def test_parse_milestones_reads_the_list_items():
    assert parse_milestones("# Milestones\n\nIntro.\n\n- 0.7.0\n- later\n") == ["0.7.0", "later"]


def test_a_milestone_missing_from_the_list_is_an_error():
    assert any("milestone" in e for e in validate([task()], milestones=["later"]))
    assert validate([task()], milestones=["0.7.0"]) == []


def test_add_milestone_appends_a_list_item():
    assert add_milestone("# Milestones\n\n- 0.7.0\n- later\n", "0.8.0") == "# Milestones\n\n- 0.7.0\n- later\n- 0.8.0\n"


def test_add_milestone_rejects_a_duplicate_or_a_bad_name():
    for name in ("later", "", "a b", "../x", "x" * 40, "<b>"):
        try:
            add_milestone("- later\n", name)
        except ValueError:
            continue
        raise AssertionError(f"accepted {name!r}")


# --- artifacts ----------------------------------------------------------------


def test_add_artifact_puts_the_newest_first():
    entries = add_artifact([], "/w/a.html", "eval report", "13/10/2026 10:00")
    entries = add_artifact(entries, "/w/b.png", "screenshot", "13/10/2026 10:05")
    assert [e["path"] for e in entries] == ["/w/b.png", "/w/a.html"]


def test_re_adding_an_artifact_moves_it_to_the_top_with_the_new_label():
    entries = add_artifact(add_artifact([], "/w/a.html", "old", "t1"), "/w/b.png", "shot", "t2")
    entries = add_artifact(entries, "/w/a.html", "eval report", "t3")
    assert entries[0] == {"path": "/w/a.html", "label": "eval report", "at": "t3"}
    assert len(entries) == 2


def test_add_artifact_keeps_the_last_twenty():
    entries = []
    for i in range(25):
        entries = add_artifact(entries, f"/w/{i}.txt", str(i), "t")
    assert len(entries) == 20
    assert entries[0]["path"] == "/w/24.txt"


# --- edit_location ------------------------------------------------------------


def test_a_task_nobody_started_is_edited_on_the_board_branch():
    assert edit_location(task(worktree="main")) == "tasks-board"
    assert edit_location(task(worktree="tasks-board")) == "tasks-board"


def test_a_task_in_progress_is_edited_in_its_own_worktree():
    assert edit_location(task(status="doing", worktree="T-0001-x")) == "T-0001-x"


def test_a_task_on_a_remote_branch_cannot_be_edited_here():
    try:
        edit_location(task(status="doing", worktree="origin/feature/T-0001-x"))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


# --- set_field / prune_done -------------------------------------------------


def test_set_field_rewrites_one_frontmatter_line():
    out = set_field(task_text(milestone="0.7.0", body="milestone: 0.7.0 in the body\n"), "milestone", "0.8.0")
    assert "\nmilestone: 0.8.0\n" in out
    assert out.endswith("milestone: 0.7.0 in the body\n")


def test_set_field_on_a_missing_key_raises():
    try:
        set_field(task_text(), "owner", "x")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_prune_done_lists_only_done_task_files():
    tasks = [task("T-0001", status="done", pr=3), task("T-0002", status="review", pr=4), task("T-0003")]
    assert prune_done(tasks) == ["T-0001-a-task.md"]


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


def test_on_a_tie_the_task_worktree_beats_the_board_and_the_board_beats_main():
    merged = merge([task(worktree="main"), task(worktree="tasks-board"), task(worktree="T-0001-x")])
    assert merged[0].worktree == "T-0001-x"
    assert merge([task(worktree="main"), task(worktree="tasks-board")])[0].worktree == "tasks-board"


def test_a_task_deleted_on_the_board_is_gone():
    assert merge([task("T-0001"), task("T-0002")], deleted={"T-0001"}) == [task("T-0002")]


def test_a_task_deleted_on_the_board_is_gone_even_while_in_progress():
    # Deleting from the board is the developer's call; a worktree or pushed branch does not bring it back.
    tasks = [task(worktree="main"), task(status="doing", worktree="T-0001-x"), task(status="review", worktree="origin/feature/T-0001-x")]
    assert merge(tasks, deleted={"T-0001"}) == []


def test_a_task_only_in_one_worktree_is_kept():
    merged = merge([task("T-0001"), task("T-0002", worktree="wt-a")])
    assert [t.id for t in merged] == ["T-0001", "T-0002"]


# --- deep_link ------------------------------------------------------------


def test_deep_link_encodes_the_prompt_and_repo():
    assert deep_link("T-0001", "owner/repo") == "claude-cli://open?q=%2Fwork-on-task%20T-0001&repo=owner%2Frepo"


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


def test_served_card_lets_you_change_the_milestone():
    html = render([task()], token="tok", milestones=["0.7.0", "0.8.0"])
    assert '<select class="msel" data-task="T-0001">' in html
    assert '<option value="0.7.0" selected>' in html
    assert 'id="newms"' in html


def test_any_task_can_be_deleted_from_the_served_board():
    assert 'data-delete="T-0001"' in render([task()], token="tok")
    assert 'data-delete="T-0001"' in render([task(status="doing", worktree="T-0001-x")], token="tok")


def test_card_shows_the_start_of_the_details():
    html = render([task(body="## Context\n\nFirst **line** here.\nSecond line.\n")])
    assert '<p class="excerpt">First line here. Second line.</p>' in html


def test_details_are_rendered_as_markdown():
    html = render([task(body="## Context\n\n- one\n")])
    assert "<h3>Context</h3>" in html
    assert "<li>one</li>" in html


def test_agent_output_starts_collapsed():
    html = render([task()], token="tok")
    assert '<details id="poutd">' in html


def test_todo_column_is_twice_as_wide():
    assert "grid-template-columns:minmax(360px, 2fr) repeat(4, minmax(180px, 1fr))" in render([task()])


def test_served_board_can_create_a_task():
    assert 'id="newtask"' in render([task()], token="tok")
    assert 'id="newtask"' not in render([task()])


def test_static_page_has_no_edit_controls():
    html = render([task()])
    assert "data-delete" not in html
    assert 'class="msel"' not in html
    assert 'id="newms"' not in html


def test_card_links_the_latest_artifact_through_the_server():
    arts = {"T-0001": [{"path": "/w/reports/run 1/index.html", "label": "eval report", "at": "t"}]}
    html = render([task()], token="tok", artifacts=arts)
    assert 'href="/a/T-0001/0/index.html"' in html
    assert "eval report" in html


def test_static_card_links_the_artifact_as_a_file():
    arts = {"T-0001": [{"path": "/w/reports/run 1/index.html", "label": "eval report", "at": "t"}]}
    assert 'href="file:///w/reports/run%201/index.html"' in render([task()], artifacts=arts)


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


def test_html_links_the_issue():
    t = task()
    t.issue = 77
    assert "https://github.com/owner/repo/issues/77" in render([t])


def test_html_offers_milestones_that_have_no_task_yet():
    assert '<option value="0.8.0">' in render([task()], milestones=["0.7.0", "0.8.0"])


def test_html_reports_a_warning():
    assert "lsof unavailable" in render([task()], warnings=["lsof unavailable"])


def test_html_hides_worktree_activity_for_a_task_nobody_started():
    # Every worktree branched off main carries every todo task; only a started one is that worktree's work.
    wt = {"wt-a": WorktreeInfo(name="wt-a", branch="feature/other-work", last_commit="1h ago · x", dirty=0, ahead=3, idle_min=3, agent=True)}
    html = render([task(status="todo", worktree="wt-a")], wt)
    assert "feature/other-work" not in html
    assert "agent active" not in html


# --- live agents --------------------------------------------------------


def test_task_of_path_reads_the_task_worktree():
    assert task_of_path("/u/repo/.claude/worktrees/T-0003-anonymize-copy-thread") == "T-0003"
    assert task_of_path("/u/repo/.claude/worktrees/T-0003-anonymize/src-tauri") == "T-0003"
    assert task_of_path("/u/repo/.claude/worktrees/forward-whole-thread") is None
    assert task_of_path("/u/repo") is None


def agent(status="working", cwd="/u/repo/.claude/worktrees/T-0001-x", pane="w1:p1"):
    return {"agent_status": status, "cwd": cwd, "foreground_cwd": cwd, "pane_id": pane}


def test_agents_by_task_maps_each_agent_to_its_task_and_machine():
    found = agents_by_task([("Laptop", None, agent()), ("remote-box", "m1", agent("idle", "/r/.claude/worktrees/T-0002-y", "w2:p3"))])
    assert found == {
        "T-0001": AgentInfo(machine="Laptop", machine_id=None, status="working", pane_id="w1:p1"),
        "T-0002": AgentInfo(machine="remote-box", machine_id="m1", status="idle", pane_id="w2:p3"),
    }


def test_agents_outside_a_task_worktree_are_ignored():
    assert agents_by_task([("Laptop", None, agent(cwd="/u/repo"))]) == {}


def test_when_two_agents_share_a_task_the_one_needing_you_wins():
    found = agents_by_task([("Laptop", None, agent("working", pane="w1:p1")), ("Laptop", None, agent("blocked", pane="w1:p2"))])
    assert found["T-0001"].pane_id == "w1:p2"


def test_blocked_and_done_need_you():
    assert [s for s in ("idle", "working", "blocked", "done", "unknown") if needs_you(s)] == ["blocked", "done"]


def test_card_shows_where_the_agent_runs_and_a_needs_you_chip():
    a = AgentInfo(machine="remote-box", machine_id="m1", status="blocked", pane_id="w2:p3")
    html = render([task(status="doing", worktree="T-0001-x")], agents={"T-0001": a}, token="tok")
    assert "on remote-box" in html
    assert 'data-focus="T-0001"' in html
    assert 'data-agent="1"' in html


def test_card_without_a_waiting_agent_has_no_needs_you_chip():
    a = AgentInfo(machine="Laptop", machine_id=None, status="working", pane_id="w1:p1")
    html = render([task(status="doing", worktree="T-0001-x")], agents={"T-0001": a}, token="tok")
    assert "data-focus" not in html
    assert "agent active" in html


def test_card_from_a_remote_branch_says_so():
    wt = {"origin/feature/T-0001-x": WorktreeInfo(name="origin/feature/T-0001-x", branch="feature/T-0001-x", last_commit="1h ago · x", dirty=0, ahead=2, idle_min=60, agent=False, remote=True)}
    html = render([task(status="doing", worktree="origin/feature/T-0001-x")], wt)
    assert "remote branch" in html


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


# --- render_markdown -------------------------------------------------------


def test_markdown_headings_paragraphs_and_lists():
    out = render_markdown("## Context\n\nSome text\nwrapped.\n\n- a\n- b\n\n1. x\n2. y\n")
    assert out == "<h3>Context</h3><p>Some text\nwrapped.</p><ul><li>a</li><li>b</li></ul><ol><li>x</li><li>y</li></ol>"


def test_markdown_inline_code_bold_italic():
    assert render_markdown("Use `a<b>` and **bold** and *it*.") == "<p>Use <code>a&lt;b&gt;</code> and <strong>bold</strong> and <em>it</em>.</p>"


def test_markdown_code_block_is_kept_verbatim_and_escaped():
    assert render_markdown("```\n**x** <y>\n```\n") == "<pre><code>**x** &lt;y&gt;</code></pre>"


def test_markdown_escapes_raw_html():
    assert "<script>" not in render_markdown("<script>alert(1)</script>")


def test_markdown_links_only_http():
    assert render_markdown("[docs](https://e.com/a?b=1&c=2)") == '<p><a href="https://e.com/a?b=1&amp;c=2" target="_blank" rel="noopener">docs</a></p>'
    assert "href" not in render_markdown("[x](javascript:alert(1))")


# --- excerpt ----------------------------------------------------------------


def test_excerpt_takes_the_first_two_text_lines_without_markup():
    body = "## Context\n\nAdd the `GGUF` file as a\n**chat** option for [Macs](https://e.com).\nThird line.\n"
    assert excerpt(body) == "Add the GGUF file as a chat option for Macs."


def test_excerpt_skips_list_markers_and_empty_bodies():
    assert excerpt("## A\n\n- first\n- second\n") == "first second"
    assert excerpt("") == ""


# --- new tasks ----------------------------------------------------------------


def test_slugify():
    assert slugify("Qwen 3.6 27B in the embedded catalog!") == "qwen-3-6-27b-in-the-embedded-catalog"
    assert slugify("Ñandú café") == "nandu-cafe"
    assert len(slugify("word " * 30)) <= 40


def test_next_id_follows_the_highest_ever_used():
    assert next_id(["T-0001", "T-0012", "T-0003"]) == "T-0013"
    assert next_id([]) == "T-0001"


def test_new_task_text_parses_back():
    text = new_task_text("T-0013", "Do a thing", "0.7.0", "")
    t = parse_task(text, "T-0013-do-a-thing.md", "main")
    assert (t.id, t.title, t.status, t.milestone, t.pr) == ("T-0013", "Do a thing", "todo", "0.7.0", None)
    assert "## Acceptance" in t.body


def test_new_task_text_keeps_the_given_body():
    t = parse_task(new_task_text("T-0013", "Do a thing", "0.7.0", "Why.\r\n"), "T-0013-x.md", "main")
    assert t.body == "Why.\n"


def test_new_task_title_must_be_one_short_line():
    import pytest

    for bad in ("", "  ", "a\nb", "x" * 121):
        with pytest.raises(ValueError):
            new_task_text("T-0013", bad, "0.7.0", "")


# --- milestone order ----------------------------------------------------------


def test_milestones_sort_by_version_then_named_ones_last():
    names = ["later", "0.10.0", "0.7.0", "1.0", "0.7.1", "backlog"]
    assert sorted(names, key=milestone_key) == ["0.7.0", "0.7.1", "0.10.0", "1.0", "backlog", "later"]


def test_a_leading_v_is_still_a_version():
    assert sorted(["later", "v0.7.0", "0.6.16"], key=milestone_key) == ["0.6.16", "v0.7.0", "later"]


def test_column_lists_tasks_from_the_lowest_milestone_up():
    tasks = [task("T-0001", milestone="later"), task("T-0002", milestone="0.10.0"), task("T-0003", milestone="0.7.0"), task("T-0004", milestone="0.7.0")]
    html = render(tasks)
    order = sorted(["T-0001", "T-0002", "T-0003", "T-0004"], key=lambda i: html.index(f'id="{i}"'))
    assert order == ["T-0003", "T-0004", "T-0002", "T-0001"]
