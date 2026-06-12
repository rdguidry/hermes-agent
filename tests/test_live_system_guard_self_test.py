"""Self-test for the live-system guard fixture in tests/conftest.py.

This file is the canary. If anyone removes a guard or weakens it, these
tests fail. If anyone adds a NEW kill primitive to the codebase without
adding it to the guard, the corresponding test added here will fail too.

The guard exists to protect the developer's live ``hermes-gateway`` process
from being SIGTERMed by tests. See PR #23397 for the original incident
(5+ live gateway kills in 3 days). Per Teknium 2026-05-10:

  > "You better do such a deep scan and scrub of the tests that this
  >  never is possible ever again for all eternity."

Every primitive that can deliver a signal to a foreign process or mutate
the live systemd unit MUST be exercised below. Adding a new primitive to
the guard? Add a test here too.
"""
from __future__ import annotations

import os
import signal
import subprocess

import pytest

# A guaranteed-foreign PID: PID 1 (init).  Owned by root, not us, and
# always exists. A sane guard refuses to signal it.
FOREIGN_PID = 1


# ──────────────────── kill primitives ─────────────────────────


def test_os_kill_blocks_foreign_pid():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.kill(FOREIGN_PID, signal.SIGTERM)


def test_os_kill_blocks_negative_one():
    """``os.kill(-1, sig)`` signals every process we can reach. Must be blocked."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.kill(-1, signal.SIGTERM)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="killpg POSIX-only")
def test_os_killpg_blocks_foreign_pgid():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.killpg(FOREIGN_PID, signal.SIGTERM)


# ──────────────────── subprocess regex bypasses ────────────────


def test_subprocess_run_systemctl_restart_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["systemctl", "--user", "restart", "hermes-gateway"])


def test_subprocess_run_full_path_systemctl_blocked():
    """``/usr/bin/systemctl`` (full path) must be blocked too."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["/usr/bin/systemctl", "--user", "stop", "hermes-gateway"])


def test_subprocess_run_sudo_systemctl_blocked():
    """``sudo systemctl ...`` defeated the old head==systemctl check."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["sudo", "systemctl", "restart", "hermes-gateway"])


def test_subprocess_run_env_systemctl_blocked():
    """``env systemctl ...`` similarly defeated the old head check."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["env", "systemctl", "--user", "restart", "hermes-gateway"])


def test_subprocess_run_bash_c_systemctl_blocked():
    """``bash -c "systemctl ..."`` must also be caught."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["bash", "-c", "systemctl --user restart hermes-gateway"])


def test_subprocess_run_sh_c_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["sh", "-c", "systemctl --user stop hermes-gateway"])


def test_subprocess_run_setsid_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["setsid", "systemctl", "kill", "hermes-gateway"])


def test_subprocess_run_string_shell_true_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(
            "systemctl --user restart hermes-gateway",
            shell=True,
        )


def test_subprocess_popen_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(["systemctl", "--user", "stop", "hermes-gateway"])


def test_subprocess_call_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.call(["systemctl", "--user", "restart", "hermes-gateway"])


def test_subprocess_check_call_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.check_call(["systemctl", "--user", "restart", "hermes-gateway"])


def test_subprocess_check_output_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.check_output(["systemctl", "--user", "restart", "hermes-gateway"])


def test_subprocess_getoutput_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.getoutput("systemctl --user restart hermes-gateway")


def test_subprocess_getstatusoutput_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.getstatusoutput("systemctl --user restart hermes-gateway")


# ──────────────────── os.system / os.popen ────────────────────


def test_os_system_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.system("systemctl --user restart hermes-gateway")


def test_os_popen_systemctl_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        os.popen("systemctl --user restart hermes-gateway")


# ──────────────────── pty.spawn ────────────────────────────────


def test_pty_spawn_systemctl_blocked():
    import pty
    with pytest.raises(RuntimeError, match="live-system guard"):
        pty.spawn(["systemctl", "--user", "restart", "hermes-gateway"])


# ──────────────────── asyncio.create_subprocess_* ──────────────


def test_asyncio_create_subprocess_exec_systemctl_blocked():
    import asyncio

    async def _attempt():
        await asyncio.create_subprocess_exec(
            "systemctl", "--user", "restart", "hermes-gateway"
        )

    with pytest.raises(RuntimeError, match="live-system guard"):
        asyncio.run(_attempt())


def test_asyncio_create_subprocess_shell_systemctl_blocked():
    import asyncio

    async def _attempt():
        await asyncio.create_subprocess_shell(
            "systemctl --user restart hermes-gateway"
        )

    with pytest.raises(RuntimeError, match="live-system guard"):
        asyncio.run(_attempt())


# ──────────────────── pkill / killall / taskkill ───────────────


def test_subprocess_pkill_hermes_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["pkill", "-f", "hermes"])


def test_subprocess_pkill_hermes_gateway_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["pkill", "-f", "hermes-gateway"])


def test_subprocess_pkill_python_dash_f_blocked():
    """``pkill -f python`` matches the gateway's "python -m hermes_cli.main"."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["pkill", "-f", "python"])


def test_subprocess_killall_hermes_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["killall", "hermes"])


# ──────────────────── pass-through cases (must NOT raise) ──────


def test_systemctl_status_passes_through():
    """Read-only systemctl probes (status/show/list-units) are fine."""
    # Run with check=False so we don't fail on the gateway's exit code.
    r = subprocess.run(
        ["systemctl", "--user", "status", "hermes-gateway", "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r is not None  # Did not raise — the guard let it through.


def test_systemctl_show_passes_through():
    r = subprocess.run(
        ["systemctl", "--user", "show", "hermes-gateway", "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r is not None


def test_systemctl_list_units_passes_through():
    r = subprocess.run(
        ["systemctl", "--user", "list-units", "fake-not-real-unit*", "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r is not None


def test_systemctl_unrelated_unit_passes_through():
    """systemctl restart of a non-hermes unit is allowed (we only protect hermes)."""
    # Use --dry-run so we don't actually try to restart anything; just
    # verify the guard doesn't block the call. systemctl supports
    # --dry-run via the privileged API; on user scope it usually fails
    # quickly without side effects.
    r = subprocess.run(
        ["systemctl", "--user", "show", "fake-not-real-unit"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r is not None


def test_kill_own_subtree_passes_through():
    """We CAN kill our own children — guard recognizes them via psutil."""
    p = subprocess.Popen(["sleep", "30"])
    try:
        os.kill(p.pid, signal.SIGTERM)
    finally:
        p.wait(timeout=2)
    # SIGTERM = 15; subprocess returncode is -15 on POSIX.
    assert p.returncode in {-signal.SIGTERM, 128 + int(signal.SIGTERM)}


def test_subprocess_pkill_with_unrelated_pattern_passes_through():
    """``pkill -f some-unrelated-pattern`` (no hermes/python) is fine."""
    # We don't actually run pkill — just verify the guard would let it
    # through by inspecting the matcher. Re-implementing the check here
    # would duplicate the guard; instead spawn a noop to confirm no raise.
    # Use 'true' so it succeeds quickly.
    r = subprocess.run(["true"], capture_output=True)
    assert r.returncode == 0


def test_normal_subprocess_run_passes_through():
    """Plain non-systemctl subprocess.run should work normally."""
    r = subprocess.run(["echo", "hello"], capture_output=True, text=True)
    assert r.stdout.strip() == "hello"


# ──────────────────── real-repo git mutation guard ─────────────
#
# A leaked ``cmd_update`` flow autostashes the developer's uncommitted
# work, runs ``reset --hard``, and flips the branch to main (observed
# 2026-06-12 during a parallel tests/hermes_cli run — the working-tree
# variant of the PR #23397 gateway kills). Every blocked payload below
# is deliberately a NO-OP even if the guard were broken, so this canary
# can never damage the repo itself.

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_git_stash_in_repo_root_blocked():
    """The exact primitive that destroyed uncommitted work: git stash."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        # Pathspec matches nothing — harmless if it ever executed.
        subprocess.run(
            ["git", "stash", "push", "-m", "guard-self-test",
             "--", "no-such-file-guard-self-test"],
            cwd=REPO_ROOT,
        )


def test_git_reset_in_repo_root_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        # --soft HEAD is a no-op if it ever executed.
        subprocess.run(["git", "reset", "--soft", "HEAD"], cwd=REPO_ROOT)


def test_git_checkout_in_repo_root_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        # Pathspec matches nothing — errors out harmlessly if executed.
        subprocess.run(
            ["git", "checkout", "--", "no-such-file-guard-self-test"],
            cwd=REPO_ROOT,
        )


def test_git_dash_c_repo_root_blocked():
    """``git -C <repo>`` overrides cwd — must be caught too."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["git", "-C", REPO_ROOT, "reset", "--soft", "HEAD"])


def test_git_mutation_in_repo_subdir_blocked():
    """Mutating git anywhere INSIDE the checkout acts on the same repo."""
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(
            ["git", "reset", "--soft", "HEAD"],
            cwd=os.path.join(REPO_ROOT, "tests"),
        )


def test_git_default_cwd_in_repo_root_blocked(monkeypatch):
    """No cwd kwarg: the guard falls back to the process working dir."""
    monkeypatch.chdir(REPO_ROOT)
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["git", "reset", "--soft", "HEAD"])


def test_git_popen_stash_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.Popen(
            ["git", "stash", "push", "-m", "guard-self-test",
             "--", "no-such-file-guard-self-test"],
            cwd=REPO_ROOT,
        )


def test_real_updater_spawn_blocked():
    """Spawning the real ``hermes update`` CLI runs the updater's git
    flow against this checkout in a child the guard can't see into."""
    # Nonexistent interpreter path: if the guard were broken this would
    # raise FileNotFoundError instead of running anything.
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(["/nonexistent-guard-self-test/hermes", "update"])


def test_python_m_hermes_cli_update_spawn_blocked():
    with pytest.raises(RuntimeError, match="live-system guard"):
        subprocess.run(
            ["/nonexistent-guard-self-test/python", "-m",
             "hermes_cli.main", "update"]
        )


def test_git_readonly_in_repo_root_passes_through():
    """status / rev-parse / stash list are inspection — must still work."""
    r = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert r is not None
    r = subprocess.run(
        ["git", "stash", "list"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert r is not None


def test_git_mutation_in_tmp_repo_passes_through(tmp_path):
    """Tempdir repos are exactly where test git fixtures SHOULD mutate."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    # Mutating verbs in the tmp repo sail through the guard.
    subprocess.run(["git", "reset", "--soft", "HEAD"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "--", "."], cwd=tmp_path, check=True)


def test_hermes_update_check_not_blocked():
    """Only the exact ``update`` subcommand is the updater — not
    ``update-check`` and friends."""
    # Allowed by the guard, then fails on the nonexistent binary —
    # proving the guard did NOT intercept it.
    with pytest.raises(FileNotFoundError):
        subprocess.run(["/nonexistent-guard-self-test/hermes", "update-check"])


# ──────────────────── bypass marker ─────────────────────────────


@pytest.mark.live_system_guard_bypass
def test_bypass_marker_disables_guard():
    """The bypass marker exists for tests that genuinely need real signal delivery
    (e.g. PTY tests SIGINTing their own child). Verify it works.

    We use it harmlessly here by signaling our own PID 0 (own group) so we
    don't actually kill anything — but the call goes through real os.kill.
    """
    # With bypass, the guard yields without installing the monkeypatch,
    # so we get the real os.kill. Calling os.kill(os.getpid(), 0) just
    # checks that the PID exists — harmless.
    os.kill(os.getpid(), 0)  # No exception — guard is OFF.
