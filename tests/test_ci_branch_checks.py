"""Event/trust boundary regressions for #481; never cancel release work."""
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_branch_checks", ROOT / "scripts/ci_branch_checks.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def pull(sha="abc", repo="owner/repo", state="open"):
    return {"state": state, "head": {"sha": sha, "repo": {"full_name": repo}}}


@pytest.mark.parametrize("event,ref", [("pull_request", "refs/pull/1/merge"), ("workflow_call", "refs/heads/feature"),
                                      ("workflow_dispatch", "refs/heads/feature"), ("push", "refs/heads/main"),
                                      ("push", "refs/tags/v1")])
def test_pr_release_and_other_events_always_run_without_api(event, ref):
    def forbidden(_):
        pytest.fail("must not query branch PRs")
    assert ci.run_checks(event, ref, "abc", "owner/repo", forbidden)


@pytest.mark.parametrize("rows,expected", [([], True), ([pull()], False), ([pull(sha="old")], True),
                                         ([pull(repo="fork/repo")], True), ([pull(state="closed")], True)])
def test_only_same_repository_exact_open_pr_head_suppresses_push(rows, expected):
    assert ci.run_checks("push", "refs/heads/fix/a&b", "abc", "owner/repo", lambda url: rows) is expected


def test_lookup_failure_runs_branch_checks():
    def broken(_):
        raise OSError("offline")
    assert ci.run_checks("push", "refs/heads/feature", "abc", "owner/repo", broken)


def test_workflow_routing_keeps_existing_jobs_and_release_gate():
    workflow = yaml.load((ROOT / ".github/workflows/tester.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    for name in ("pytest", "security", "ha-tillagg"):
        assert jobs[name]["needs"] == "route"
        assert "needs.route.outputs.run_checks == 'true'" in jobs[name]["if"]
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_call"}
    release = yaml.load((ROOT / ".github/workflows/docker.yml").read_text(), Loader=yaml.BaseLoader)
    assert release["jobs"]["bygg"]["needs"] == "tester"
    assert "concurrency" not in workflow  # no active work cancelled
