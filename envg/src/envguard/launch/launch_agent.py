# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""macOS LaunchAgent management for scheduled update checks."""

from __future__ import annotations

import contextlib
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


logger = get_logger(__name__)


class LaunchAgentManager:
    """Manage a macOS LaunchAgent for periodic envguard update checks.

    The LaunchAgent plist is installed to ``~/Library/LaunchAgents/`` and
    uses ``launchctl`` to load / unload the scheduled job.
    """

    BUNDLE_ID = "com.envguard.update"
    PLIST_NAME = "com.envguard.update.plist"

    def __init__(self) -> None:
        self._home = Path.home()

    # ------------------------------------------------------------------
    # Plist generation
    # ------------------------------------------------------------------

    def generate_plist(
        self,
        envguard_path: str,
        interval_hours: int = 24,
    ) -> str:
        """Generate a launchd property-list XML string.

        Args:
            envguard_path: Absolute path to the ``envguard`` executable.
            interval_hours: How often (in hours) the agent should run.

        Returns:
            A well-formed plist XML document as a string.
        """
        interval_seconds = interval_hours * 3600

        # Build the plist structure using ElementTree
        plist_el = ET.Element("plist", version="1.0")
        dict_el = ET.SubElement(plist_el, "dict")

        def _add_key_value(parent: ET.Element, key: str, value: str) -> None:
            ET.SubElement(parent, "key").text = key
            ET.SubElement(parent, "string").text = value

        def _add_key_true(parent: ET.Element, key: str) -> None:
            ET.SubElement(parent, "key").text = key
            ET.SubElement(parent, "true")

        def _add_key_int(parent: ET.Element, key: str, value: int) -> None:
            ET.SubElement(parent, "key").text = key
            ET.SubElement(parent, "integer").text = str(value)

        def _add_key_array_of_strings(parent: ET.Element, key: str, values: list[str]) -> None:
            ET.SubElement(parent, "key").text = key
            arr = ET.SubElement(parent, "array")
            for v in values:
                ET.SubElement(arr, "string").text = v

        # Label
        _add_key_value(dict_el, "Label", self.BUNDLE_ID)

        # ProgramArguments
        _add_key_array_of_strings(
            dict_el,
            "ProgramArguments",
            [envguard_path, "update", "--check"],
        )

        # StartInterval (seconds)
        _add_key_int(dict_el, "StartInterval", interval_seconds)

        # WorkingDirectory
        _add_key_value(dict_el, "WorkingDirectory", str(self._home))

        # StandardOutPath
        log_dir = self._home / ".envguard" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _add_key_value(
            dict_el,
            "StandardOutPath",
            str(log_dir / "update-stdout.log"),
        )

        # StandardErrorPath
        _add_key_value(
            dict_el,
            "StandardErrorPath",
            str(log_dir / "update-stderr.log"),
        )

        # RunAtLoad - run once immediately on load
        _add_key_true(dict_el, "RunAtLoad")

        # EnvironmentVariables - set PATH so envguard can be found
        env_dict = ET.SubElement(dict_el, "dict")
        ET.SubElement(env_dict, "key").text = "PATH"
        current_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        ET.SubElement(env_dict, "string").text = current_path
        ET.SubElement(env_dict, "key").text = "HOME"
        ET.SubElement(env_dict, "string").text = str(self._home)

        # Pretty-print with proper XML declaration
        ET.indent(plist_el, space="    ")
        xml_str = ET.tostring(plist_el, encoding="unicode", xml_declaration=True)
        # Ensure the XML declaration uses the proper format
        if not xml_str.startswith("<?xml"):
            xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
        return xml_str

    # ------------------------------------------------------------------
    # Install / uninstall / status
    # ------------------------------------------------------------------

    def install(self, envguard_path: str) -> dict:
        """Install and load the LaunchAgent.

        Args:
            envguard_path: Absolute path to the ``envguard`` executable.

        Returns:
            Dict with ``plist_path``, ``loaded``, and ``success`` keys.
        """
        plist_path = self.get_plist_path()
        plist_dir = plist_path.parent

        # Create LaunchAgents directory if needed
        plist_dir.mkdir(parents=True, exist_ok=True)

        # Generate and write the plist
        plist_content = self.generate_plist(envguard_path)
        try:
            plist_path.write_text(plist_content, encoding="utf-8")
            logger.info("Wrote plist to %s", plist_path)
        except OSError as exc:
            logger.error("Failed to write plist: %s", exc)
            return {
                "plist_path": str(plist_path),
                "loaded": False,
                "success": False,
            }

        # Load via launchctl
        loaded = self._launchctl_load(plist_path)

        return {
            "plist_path": str(plist_path),
            "loaded": loaded,
            "success": loaded,
        }

    def uninstall(self) -> dict:
        """Unload and remove the LaunchAgent.

        Returns:
            Dict with ``plist_path``, ``unloaded``, and ``success`` keys.
        """
        plist_path = self.get_plist_path()

        if not plist_path.exists():
            return {
                "plist_path": str(plist_path),
                "unloaded": True,
                "success": True,
            }

        # Unload via launchctl
        unloaded = self._launchctl_unload(plist_path)

        # Remove the plist file
        removed = False
        if unloaded or not self._launchctl_is_loaded(self.BUNDLE_ID):
            try:
                plist_path.unlink()
                removed = True
                logger.info("Removed plist %s", plist_path)
            except OSError as exc:
                logger.error("Failed to remove plist: %s", exc)

        return {
            "plist_path": str(plist_path),
            "unloaded": unloaded,
            "success": unloaded and removed,
        }

    def is_installed(self) -> bool:
        """Check whether the LaunchAgent plist exists on disk."""
        return self.get_plist_path().exists()

    def get_status(self) -> dict:
        """Query the current status of the LaunchAgent.

        Returns a dict with:
        - ``installed`` (bool): plist exists
        - ``loaded`` (bool): loaded in launchctl
        - ``pid`` (int | None): PID of running instance, if any
        - ``exit_status`` (int | None): last exit status
        """
        installed = self.is_installed()
        loaded = self._launchctl_is_loaded(self.BUNDLE_ID) if installed else False

        pid: int | None = None
        exit_status: int | None = None

        if loaded:
            pid, exit_status = self._launchctl_get_service_info(self.BUNDLE_ID)

        return {
            "installed": installed,
            "loaded": loaded,
            "pid": pid,
            "exit_status": exit_status,
        }

    def get_plist_path(self) -> Path:
        """Return the path to the LaunchAgent plist file."""
        return self._home / "Library" / "LaunchAgents" / self.PLIST_NAME

    def get_log_paths(self) -> dict[str, str]:
        """Return paths to the LaunchAgent's stdout and stderr log files."""
        log_dir = self._home / ".envguard" / "logs"
        return {
            "stdout": str(log_dir / "update-stdout.log"),
            "stderr": str(log_dir / "update-stderr.log"),
        }

    # ------------------------------------------------------------------
    # Internal: launchctl helpers
    # ------------------------------------------------------------------

    def _launchctl_load(self, plist_path: Path) -> bool:
        """Load a plist into launchctl.

        Handles both macOS Ventura+ (``bootstrap``) and older (``load``)
        launchctl syntax.
        """
        # Try the modern launchctl syntax first (macOS 11+)
        for args in (
            ["bootstrap", str(self._home / "Library" / "LaunchAgents"), str(plist_path)],
            ["load", str(plist_path)],  # Legacy fallback
        ):
            try:
                proc = subprocess.run(
                    ["launchctl", *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if proc.returncode == 0:
                    logger.info("LaunchAgent loaded via: launchctl %s", " ".join(args))
                    return True
                logger.debug(
                    "launchctl %s returned %d: %s",
                    " ".join(args),
                    proc.returncode,
                    proc.stderr.strip(),
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                logger.debug("launchctl not available: %s", exc)

        return False

    def _launchctl_unload(self, plist_path: Path) -> bool:
        """Unload a plist from launchctl."""
        for args in (
            ["bootout", f"gui/{os.getuid()}/{self.BUNDLE_ID}"],
            ["unload", str(plist_path)],
        ):
            try:
                proc = subprocess.run(
                    ["launchctl", *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if proc.returncode == 0:
                    logger.info("LaunchAgent unloaded via: launchctl %s", " ".join(args))
                    return True
                # bootout may fail with "not found" which is still fine
                if "not found" in proc.stderr.lower():
                    return True
                logger.debug(
                    "launchctl %s returned %d: %s",
                    " ".join(args),
                    proc.returncode,
                    proc.stderr.strip(),
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                logger.debug("launchctl not available: %s", exc)
        return False

    @staticmethod
    def _launchctl_is_loaded(bundle_id: str) -> bool:
        """Check whether a service is loaded in launchctl."""
        try:
            proc = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{bundle_id}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _launchctl_get_service_info(bundle_id: str) -> tuple[int | None, int | None]:
        """Get PID and exit status for a loaded service.

        Returns:
            A ``(pid, exit_status)`` tuple.  Both may be ``None`` if the
            information is not available.
        """
        try:
            proc = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{bundle_id}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                return None, None

            pid: int | None = None
            exit_status: int | None = None

            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("pid"):
                    # Format: "pid = 12345"
                    _, _, val = line.partition("=")
                    with contextlib.suppress(ValueError):
                        pid = int(val.strip())
                if "status" in line.lower() and "exit" in line.lower():
                    # Try to extract exit code
                    for token in line.split():
                        try:
                            exit_status = int(token)
                        except ValueError:
                            continue

            return pid, exit_status
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None, None
