"""Plugin architecture (NFR-6).

Discovers user-provided Python plugins at startup and routes
``(agent_type, task_type)`` pairs to them, allowing third parties or
operators to extend agent capabilities without modifying core
orchestrator code.

A plugin is any module placed in:
    1. ``agents/src/plugins/``  (bundled),  or
    2. any directory listed in the env var ``AGENT_PLUGINS_PATH``
       (colon- or os.pathsep-separated).

Each plugin module must expose a ``PLUGIN`` dict:

    PLUGIN = {
        "name":         "my-plugin",        # required, unique
        "version":      "1.0.0",            # required
        "description":  "...",              # required
        "author":       "...",              # optional
        "handlers": [
            {
                "agent_type": "code-build",       # exact match
                "task_type":  "my-task",          # substring match (case-insensitive)
                "function":   my_handler,         # async (task, context) -> dict
            },
            ...
        ],
    }

Handler signature: ``async def handler(task: AgentTask, context: dict) -> dict``.
The orchestrator wraps publish & state updates, so the handler only needs
to do its work and return an output dict.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger()


HandlerFn = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class PluginHandler:
    agent_type: str
    task_type_pattern: str
    function: HandlerFn
    plugin_name: str


@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    author: str
    module_path: str
    handler_count: int
    handlers: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None


class PluginRegistry:
    """Discovers, loads, and routes to user-provided plugins."""

    def __init__(self) -> None:
        self._handlers: list[PluginHandler] = []
        self._plugins: dict[str, PluginInfo] = {}
        self._loaded = False

    @property
    def plugins(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

    def _discovery_paths(self) -> list[Path]:
        paths: list[Path] = []
        # Bundled plugins next to this file
        bundled = Path(__file__).parent
        if bundled.is_dir():
            paths.append(bundled)
        # User-supplied paths
        env = os.environ.get("AGENT_PLUGINS_PATH", "")
        for p in env.split(os.pathsep):
            p = p.strip()
            if p and Path(p).is_dir():
                paths.append(Path(p))
        return paths

    def load_all(self) -> None:
        """Idempotently discover and load all plugins."""
        if self._loaded:
            return
        for root in self._discovery_paths():
            for py in sorted(root.glob("*.py")):
                if py.name.startswith("_") or py.name == "registry.py":
                    continue
                self._load_module(py)
        self._loaded = True
        logger.info("plugin registry loaded",
                    plugin_count=len(self._plugins),
                    handler_count=len(self._handlers))

    def _load_module(self, py: Path) -> None:
        mod_name = f"agent_plugin_{py.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            manifest = getattr(module, "PLUGIN", None)
            if not isinstance(manifest, dict):
                return  # not a plugin
            name = manifest.get("name") or py.stem
            if name in self._plugins:
                logger.info("plugin already registered, skipping",
                            name=name, path=str(py))
                return
            info = PluginInfo(
                name=name,
                version=manifest.get("version", "0.0.0"),
                description=manifest.get("description", ""),
                author=manifest.get("author", ""),
                module_path=str(py),
                handler_count=0,
            )
            for h in manifest.get("handlers") or []:
                fn = h.get("function")
                if not callable(fn):
                    continue
                handler = PluginHandler(
                    agent_type=str(h.get("agent_type", "")).strip(),
                    task_type_pattern=str(h.get("task_type", "")).strip().lower(),
                    function=fn,
                    plugin_name=name,
                )
                if not handler.agent_type or not handler.task_type_pattern:
                    continue
                self._handlers.append(handler)
                info.handlers.append({
                    "agent_type": handler.agent_type,
                    "task_type": handler.task_type_pattern,
                })
                info.handler_count += 1
            self._plugins[name] = info
            logger.info("plugin loaded", name=name,
                        version=info.version, handlers=info.handler_count)
        except Exception as e:
            logger.error("plugin load failed", path=str(py), error=str(e),
                         trace=traceback.format_exc()[:500])
            self._plugins[py.stem] = PluginInfo(
                name=py.stem, version="0", description="", author="",
                module_path=str(py), handler_count=0, error=str(e),
            )

    def resolve(self, agent_type: str, task_type: str) -> PluginHandler | None:
        """Return the first plugin handler matching (agent_type, task_type)."""
        tt = (task_type or "").lower()
        for h in self._handlers:
            if h.agent_type == agent_type and h.task_type_pattern in tt:
                return h
        return None


plugin_registry = PluginRegistry()
