"""Thin Python wrapper around the agent-browser CLI.

agent-browser is a stateful CLI: ``open`` loads a page into the current session,
then ``snapshot``, ``click``, ``scroll``, etc. operate on that session.

All commands are executed via ``npx agent-browser ...`` in a subprocess so the
Python backend stays async-friendly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class SnapshotNode:
    """One node from the accessibility-tree snapshot."""

    role: str
    text: str
    ref: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[SnapshotNode] = field(default_factory=list)


class AgentBrowserService:
    """Async wrapper that shells out to ``npx agent-browser``."""

    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    async def run(self, *args: str, timeout: float | None = None) -> str:
        """Run an agent-browser sub-command and return stdout."""
        cmd = ["npx", "agent-browser", *args]
        effective_timeout = timeout or self._timeout
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
            if proc.returncode != 0:
                err_text = stderr.decode(errors="replace").strip()
                logger.warning("agent-browser %s failed (rc=%d): %s", args[0], proc.returncode, err_text[:300])
                return ""
            return stdout.decode(errors="replace")
        except asyncio.TimeoutError:
            logger.warning("agent-browser %s timed out after %.0fs", args[0], effective_timeout)
            return ""
        except FileNotFoundError:
            logger.error("npx not found – is Node.js installed?")
            return ""

    async def open(self, url: str) -> bool:
        """Navigate to *url*.  Returns True on success."""
        out = await self.run("open", url, "--headless")
        return bool(out.strip())

    async def snapshot(self) -> str:
        """Return the accessibility-tree snapshot of the current page."""
        return await self.run("snapshot")

    async def click(self, selector: str) -> bool:
        out = await self.run("click", selector)
        return bool(out.strip())

    async def fill(self, selector: str, text: str) -> bool:
        out = await self.run("fill", selector, text)
        return bool(out.strip())

    async def scroll(self, direction: str = "down", px: int = 600) -> bool:
        out = await self.run("scroll", direction, str(px))
        return bool(out.strip())

    async def press(self, key: str) -> bool:
        out = await self.run("press", key)
        return bool(out.strip())

    async def get_text(self, selector: str) -> str:
        return (await self.run("get", "text", selector)).strip()

    async def get_url(self) -> str:
        return (await self.run("get", "url")).strip()

    async def close(self) -> None:
        await self.run("close")

    # ------------------------------------------------------------------
    # Snapshot parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_links(snapshot_text: str) -> list[dict[str, str]]:
        """Extract ``{text, ref}`` dicts for every link in the snapshot."""
        links: list[dict[str, str]] = []
        for line in snapshot_text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- link "):
                continue
            text_match = re.search(r'"([^"]*)"', stripped)
            ref_match = re.search(r'\[ref=(\w+)\]', stripped)
            if text_match:
                links.append({
                    "text": text_match.group(1),
                    "ref": ref_match.group(1) if ref_match else "",
                })
        return links

    @staticmethod
    def parse_static_texts(snapshot_text: str) -> list[str]:
        """Return all StaticText values from a snapshot."""
        texts: list[str] = []
        for line in snapshot_text.splitlines():
            stripped = line.strip()
            if "StaticText" not in stripped:
                continue
            match = re.search(r'"([^"]*)"', stripped)
            if match:
                texts.append(match.group(1))
        return texts

    @staticmethod
    def extract_link_url_from_ref(snapshot_text: str, ref: str) -> str | None:
        """Given a ref like 'e6', find the href if embedded in the snapshot.

        agent-browser snapshots don't always include href — for that we
        navigate and read the URL.  This is a best-effort helper.
        """
        pattern = re.compile(rf'\[ref={re.escape(ref)}\]')
        for line in snapshot_text.splitlines():
            if pattern.search(line):
                href_match = re.search(r'href="([^"]+)"', line)
                if href_match:
                    return href_match.group(1)
        return None
