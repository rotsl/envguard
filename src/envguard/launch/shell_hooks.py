# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Shell hook management - automatic preflight suggestions on directory change."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


logger = get_logger(__name__)

# Start / end markers used in shell RC files to delineate envguard blocks
_HOOK_START = "# envguard start"
_HOOK_END = "# envguard end"

# Hook function definitions per shell
SHELL_CONFIGS: dict[str, dict[str, str]] = {
    "zsh": {
        "rc_file": ".zshrc",
        "hook_function": "envguard_chpwd",
        "hook_type": "chpwd_functions",
        "hook_content": """\
# envguard: automatic preflight on directory change
envguard_chpwd() {
    if [[ -d ".envguard" ]]; then
        if ! command -v envguard &>/dev/null; then
            return
        fi
        local _envguard_state="$HOME/.envguard/cache/chpwd_$(pwd | tr '/' '_')"
        if [[ -f "$_envguard_state" ]]; then
            local _last_checked
            _last_checked="$(cat "$_envguard_state" 2>/dev/null || echo 0)"
            local _now
            _now="$(date +%s)"
            # Re-check every 300 seconds (5 minutes)
            if (( _now - _last_checked < 300 )); then
                return
            fi
        fi
        echo "[envguard] Detected .envguard/ - run 'envguard preflight' to verify your environment"
        date +%s > "$_envguard_state" 2>/dev/null
    fi
}
# Register the hook (avoid duplicates)
if [[ -z "${chpwd_functions[(r)envguard_chpwd]}" ]]; then
    chpwd_functions=(${chpwd_functions[@]} envguard_chpwd)
fi
""",
    },
    "bash": {
        "rc_file": ".bashrc",
        "hook_function": "envguard_prompt_command",
        "hook_type": "PROMPT_COMMAND",
        "hook_content": """\
# envguard: automatic preflight on directory change
_envguard_old_pwd=""
envguard_prompt_command() {
    local _new_pwd="$(pwd)"
    if [[ "$_envguard_old_pwd" != "$_new_pwd" ]]; then
        _envguard_old_pwd="$_new_pwd"
        if [[ -d ".envguard" ]]; then
            if ! command -v envguard &>/dev/null; then
                return
            fi
            local _envguard_state="$HOME/.envguard/cache/bash_chpwd_$(pwd | tr '/' '_')"
            if [[ -f "$_envguard_state" ]]; then
                local _last_checked
                _last_checked="$(cat "$_envguard_state" 2>/dev/null || echo 0)"
                local _now
                _now="$(date +%s)"
                if (( _now - _last_checked < 300 )); then
                    return
                fi
            fi
            echo "[envguard] Detected .envguard/ - run 'envguard preflight' to verify your environment"
            date +%s > "$_envguard_state" 2>/dev/null
        fi
    fi
}
# Register the hook
if [[ -z "$(echo $PROMPT_COMMAND | grep -o 'envguard_prompt_command')" ]]; then
    if [[ -n "$PROMPT_COMMAND" ]]; then
        PROMPT_COMMAND="$PROMPT_COMMAND; envguard_prompt_command"
    else
        PROMPT_COMMAND="envguard_prompt_command"
    fi
fi
""",
    },
}


class ShellHookManager:
    """Manage shell integration hooks for envguard.

    Supports zsh and bash.  Hooks detect when the user enters a directory
    containing ``.envguard/`` and suggest running ``envguard preflight``.
    """

    def __init__(self, user_home: Path | None = None) -> None:
        if user_home is not None:
            self.user_home = user_home.resolve()
        else:
            self.user_home = Path.home()

        # Ensure cache directory exists
        self._cache_dir = self.user_home / ".envguard" / "cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get_hook_content(self, shell: str) -> str:
        """Generate the hook script content for *shell*.

        Args:
            shell: Shell name (``"zsh"`` or ``"bash"``).

        Returns:
            The hook script as a string, or an empty string if the shell
            is not supported.
        """
        config = SHELL_CONFIGS.get(shell)
        if config is None:
            logger.warning("Unsupported shell: %s", shell)
            return ""
        return config["hook_content"]

    def install_hooks(self, shell: str | None = None) -> dict:
        """Install shell hooks for automatic preflight suggestions.

        Args:
            shell: Shell to install for.  If ``None``, auto-detects the
                current shell.

        Returns:
            Dict with ``installed_for``, ``rc_file``, and ``success`` keys.
        """
        if shell is None:
            shell = self.detect_shell()

        rc_path = self.get_rc_file_path(shell)
        if rc_path is None:
            return {
                "installed_for": shell,
                "rc_file": None,
                "success": False,
            }

        # Already installed?
        if self.is_installed(shell):
            return {
                "installed_for": shell,
                "rc_file": str(rc_path),
                "success": True,
            }

        # Ensure the rc file exists
        rc_path.touch(exist_ok=True)

        # Backup
        self._backup_rc_file(rc_path)

        content = self.get_hook_content(shell)
        if not content:
            return {
                "installed_for": shell,
                "rc_file": str(rc_path),
                "success": False,
            }

        success = self._append_to_rc(rc_path, content)

        if success:
            logger.info("Installed envguard hooks for %s in %s", shell, rc_path)
        else:
            logger.error("Failed to install hooks in %s", rc_path)

        return {
            "installed_for": shell,
            "rc_file": str(rc_path),
            "success": success,
        }

    def uninstall_hooks(self, shell: str | None = None) -> dict:
        """Remove envguard hooks from a shell RC file.

        Args:
            shell: Shell to uninstall from.  If ``None``, auto-detects.

        Returns:
            Dict with ``uninstalled_from``, ``success`` keys.
        """
        if shell is None:
            shell = self.detect_shell()

        rc_path = self.get_rc_file_path(shell)
        if rc_path is None:
            return {
                "uninstalled_from": shell,
                "success": False,
            }

        if not rc_path.is_file():
            return {
                "uninstalled_from": shell,
                "success": True,
            }

        success = self._remove_from_rc(rc_path)

        if success:
            logger.info("Removed envguard hooks from %s", rc_path)
        else:
            logger.error("Failed to remove hooks from %s", rc_path)

        return {
            "uninstalled_from": shell,
            "success": success,
        }

    def detect_shell(self) -> str:
        """Detect the current shell from the ``SHELL`` environment variable.

        Returns ``"bash"`` or ``"zsh"`` (falls back to ``"bash"``).
        """
        shell_path = os.environ.get("SHELL", "")
        if "zsh" in shell_path:
            return "zsh"
        return "bash"

    def is_installed(self, shell: str) -> bool:
        """Check whether envguard hooks are present in the shell's RC file.

        Args:
            shell: Shell name.

        Returns:
            ``True`` if the hook block is found in the RC file.
        """
        rc_path = self.get_rc_file_path(shell)
        if rc_path is None or not rc_path.is_file():
            return False

        try:
            content = rc_path.read_text(encoding="utf-8")
        except OSError:
            return False

        return _HOOK_START in content and _HOOK_END in content

    def get_rc_file_path(self, shell: str) -> Path | None:
        """Return the path to the shell's RC file.

        Args:
            shell: Shell name (``"zsh"`` or ``"bash"``).

        Returns:
            Path to the RC file, or ``None`` if the shell is not supported.
        """
        config = SHELL_CONFIGS.get(shell)
        if config is None:
            return None
        return self.user_home / config["rc_file"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _backup_rc_file(self, rc_path: Path) -> Path:
        """Create a timestamped backup of *rc_path*.

        Returns:
            Path to the backup file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = rc_path.with_suffix(f"{rc_path.suffix}.envguard-backup-{timestamp}")

        try:
            shutil.copy2(str(rc_path), str(backup))
            logger.debug("Backed up %s to %s", rc_path, backup)
        except OSError as exc:
            logger.warning("Could not back up %s: %s", rc_path, exc)

        return backup

    def _append_to_rc(self, rc_path: Path, content: str) -> bool:
        """Append the envguard hook block to *rc_path*.

        The block is delimited by ``_HOOK_START`` and ``_HOOK_END`` markers.
        """
        block = f"{_HOOK_START}\n{content}{_HOOK_END}\n"

        try:
            with open(rc_path, "a", encoding="utf-8") as fh:
                fh.write("\n")
                fh.write(block)
            return True
        except OSError as exc:
            logger.error("Failed to write to %s: %s", rc_path, exc)
            return False

    @staticmethod
    def _remove_from_rc(rc_path: Path) -> bool:
        """Remove the envguard block from *rc_path*.

        Everything between ``_HOOK_START`` and ``_HOOK_END`` (inclusive) is
        removed.
        """
        try:
            content = rc_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Cannot read %s: %s", rc_path, exc)
            return False

        lines = content.splitlines(True)  # Keep line endings
        new_lines: list[str] = []
        in_block = False

        for line in lines:
            if _HOOK_START in line:
                in_block = True
                continue
            if _HOOK_END in line:
                in_block = False
                continue
            if not in_block:
                new_lines.append(line)

        try:
            rc_path.write_text("".join(new_lines), encoding="utf-8")
            return True
        except OSError as exc:
            logger.error("Cannot write %s: %s", rc_path, exc)
            return False
