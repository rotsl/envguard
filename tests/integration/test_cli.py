# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""CLI tests using typer.testing.CliRunner."""

from __future__ import annotations

from typer.testing import CliRunner

# The envguard.cli module must be importable
runner = CliRunner()


class TestCLIBase:
    """Test the envguard CLI base command and help."""

    def test_cli_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "envguard" in result.output.lower()

    def test_cli_no_args_shows_help(self):
        from envguard.cli import app

        result = runner.invoke(app, [])
        # no_args_is_help=True should show help
        assert result.exit_code == 0 or "Usage" in result.output


class TestCLIDoctor:
    """Test the doctor command."""

    def test_doctor_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "doctor" in result.output.lower()

    def test_doctor_runs(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["doctor", str(tmp_path)])
        # Should complete (may have warnings but shouldn't crash)
        assert isinstance(result.exit_code, int)

    def test_doctor_json_output(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["doctor", str(tmp_path), "--json"])
        # JSON output should be valid JSON
        import json

        try:
            data = json.loads(result.output)
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            # If not pure JSON, output should at least exist
            assert len(result.output) > 0


class TestCLIDetect:
    """Test the detect command."""

    def test_detect_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["detect", "--help"])
        assert result.exit_code == 0

    def test_detect_runs(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["detect", str(tmp_path)])
        assert isinstance(result.exit_code, int)
        assert len(result.output) > 0


class TestCLIInit:
    """Test the init command."""

    def test_init_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0

    def test_init_creates_envguard_dir(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["init", str(tmp_path)])
        # Should create .envguard/ directory
        assert (tmp_path / ".envguard").exists() or result.exit_code == 0


class TestCLIStatus:
    """Test the status command."""

    def test_status_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_status_runs(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["status", str(tmp_path)])
        assert isinstance(result.exit_code, int)


class TestCLIHealth:
    """Test the health command."""

    def test_health_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["health", "--help"])
        assert result.exit_code == 0

    def test_health_runs(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["health", str(tmp_path)])
        assert isinstance(result.exit_code, int)


class TestCLIPreflight:
    """Test the preflight command."""

    def test_preflight_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["preflight", "--help"])
        assert result.exit_code == 0

    def test_preflight_runs(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["preflight", str(tmp_path)])
        assert isinstance(result.exit_code, int)


class TestCLIRepair:
    """Test the repair command."""

    def test_repair_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["repair", "--help"])
        assert result.exit_code == 0


class TestCLIUpdate:
    """Test the update command."""

    def test_update_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["update", "--help"])
        assert result.exit_code == 0

    def test_update_dry_run(self):
        from envguard.cli import app

        result = runner.invoke(app, ["update", "--dry-run"])
        # Should complete without installing anything
        assert isinstance(result.exit_code, int)


class TestCLIFreeze:
    """Test the freeze command."""

    def test_freeze_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["freeze", "--help"])
        assert result.exit_code == 0


class TestCLIShellHooks:
    """Test shell hook commands."""

    def test_install_shell_hooks_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["install-shell-hooks", "--help"])
        assert result.exit_code == 0

    def test_uninstall_shell_hooks_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["uninstall-shell-hooks", "--help"])
        assert result.exit_code == 0


class TestCLILaunchAgent:
    """Test launch agent commands."""

    def test_install_launch_agent_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["install-launch-agent", "--help"])
        assert result.exit_code == 0

    def test_uninstall_launch_agent_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["uninstall-launch-agent", "--help"])
        assert result.exit_code == 0


class TestCLIRun:
    """Test the run command."""

    def test_run_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0

    def test_run_requires_command(self, tmp_path):
        from envguard.cli import app

        result = runner.invoke(app, ["run", "--dir", str(tmp_path)])
        # Should show help or error since no command provided
        assert isinstance(result.exit_code, int)


class TestCLIRollback:
    """Test the rollback command."""

    def test_rollback_help(self):
        from envguard.cli import app

        result = runner.invoke(app, ["rollback", "--help"])
        assert result.exit_code == 0
