"""Declarative workflows — chain agent tasks via YAML config (NFR-6).

Workflow file format::

    name: repo-overview
    description: Demo two-step workflow.
    steps:
      - name: stats
        agent_type: operate-monitor
        task_type: repo-stats
        context:
          repository: "{{ context.repository }}"
      - name: verify
        agent_type: operate-monitor
        task_type: repo-stats
        when: "{{ steps.stats.status == 'completed' }}"
        context:
          repository: "{{ steps.stats.output.repository }}"

Template syntax is Jinja2. Available variables in every step:
    `context`    – the request-level context dict
    `steps`      – mapping of `step_name -> {status, output, error, task_id}`

The engine dispatches each step in-process via `execute_agent_task` so the
existing policy / plugin / audit hooks apply uniformly.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from shared.state import AgentTask, TaskStatus, state_manager

logger = logging.getLogger(__name__)

_BUNDLED_DIR = Path(__file__).resolve().parent / "definitions"
_ENV_VAR = "AGENT_WORKFLOWS_PATH"


@dataclass
class WorkflowStep:
    name: str
    agent_type: str
    task_type: str
    context: dict[str, Any] = field(default_factory=dict)
    when: str | None = None


@dataclass
class Workflow:
    name: str
    description: str
    source: str
    steps: list[WorkflowStep] = field(default_factory=list)
    error: str | None = None


class WorkflowRegistry:
    """Discovers, loads, and executes declarative agent workflows."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._loaded = False
        self._env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)

    # --- discovery ------------------------------------------------------
    def _candidate_dirs(self) -> list[Path]:
        dirs: list[Path] = [_BUNDLED_DIR]
        extra = os.environ.get(_ENV_VAR, "").strip()
        if extra:
            for p in extra.split(os.pathsep):
                if p:
                    dirs.append(Path(p))
        return dirs

    def load_all(self) -> None:
        if self._loaded:
            return
        for d in self._candidate_dirs():
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.y*ml")):
                self._load_file(path)
        self._loaded = True
        logger.info("workflow registry loaded: count=%d", len(self._workflows))

    def reload(self) -> None:
        self._workflows.clear()
        self._loaded = False
        self.load_all()

    def _load_file(self, path: Path) -> None:
        wf_name = path.stem
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            name = str(doc.get("name") or wf_name)
            desc = str(doc.get("description") or "")
            steps_raw = doc.get("steps") or []
            steps: list[WorkflowStep] = []
            for i, s in enumerate(steps_raw):
                if not isinstance(s, dict):
                    raise ValueError(f"step {i} not a mapping")
                steps.append(WorkflowStep(
                    name=str(s.get("name") or f"step{i+1}"),
                    agent_type=str(s["agent_type"]),
                    task_type=str(s["task_type"]),
                    context=dict(s.get("context") or {}),
                    when=s.get("when"),
                ))
            self._workflows[name] = Workflow(name=name, description=desc,
                                             source=str(path), steps=steps)
            logger.info("workflow loaded: name=%s steps=%d", name, len(steps))
        except Exception as exc:
            logger.error("workflow load failed: file=%s error=%s", path, exc)
            self._workflows[wf_name] = Workflow(name=wf_name, description="",
                                                source=str(path), error=str(exc))

    # --- accessors ------------------------------------------------------
    @property
    def workflows(self) -> list[Workflow]:
        self.load_all()
        return list(self._workflows.values())

    def get(self, name: str) -> Workflow | None:
        self.load_all()
        return self._workflows.get(name)

    # --- execution ------------------------------------------------------
    def _render(self, value: Any, vars: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._env.from_string(value).render(**vars)
        if isinstance(value, dict):
            return {k: self._render(v, vars) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render(v, vars) for v in value]
        return value

    async def run(self, name: str, context: dict[str, Any]) -> dict[str, Any]:
        from orchestrator.main import execute_agent_task  # lazy: avoid cycle

        wf = self.get(name)
        if wf is None:
            return {"workflow": name, "status": "not-found", "steps": []}
        if wf.error:
            return {"workflow": name, "status": "invalid", "error": wf.error, "steps": []}

        results: dict[str, dict[str, Any]] = {}
        overall = "completed"

        for step in wf.steps:
            vars = {"context": context, "steps": results}

            if step.when:
                try:
                    cond = self._env.from_string(step.when).render(**vars)
                    if str(cond).strip().lower() not in ("true", "1", "yes"):
                        results[step.name] = {"status": "skipped", "task_id": None,
                                              "output": {}, "error": None}
                        continue
                except Exception as exc:
                    results[step.name] = {"status": "skipped", "task_id": None,
                                          "output": {}, "error": f"when: {exc}"}
                    continue

            try:
                rendered_ctx = self._render(step.context, vars)
            except Exception as exc:
                overall = "failed"
                results[step.name] = {"status": "failed", "task_id": None,
                                      "output": {}, "error": f"template: {exc}"}
                break

            task = AgentTask(
                agent_type=step.agent_type,
                task_type=step.task_type,
                context=rendered_ctx,
            )
            await state_manager.create_task(task)
            try:
                await asyncio.wait_for(execute_agent_task(task), timeout=300)
            except asyncio.TimeoutError:
                results[step.name] = {"status": "timeout", "task_id": task.task_id,
                                      "output": {}, "error": "step exceeded 300s"}
                overall = "failed"
                break
            except Exception as exc:
                results[step.name] = {"status": "failed", "task_id": task.task_id,
                                      "output": {}, "error": str(exc)}
                overall = "failed"
                break

            refreshed = await state_manager.get_task(step.agent_type, task.task_id)
            status = refreshed.status.value if refreshed else "unknown"
            results[step.name] = {
                "status": status,
                "task_id": task.task_id,
                "output": (refreshed.output_data if refreshed else {}) or {},
                "error": (refreshed.error if refreshed else None),
            }
            if status != "completed":
                overall = "failed"
                break

        return {"workflow": name, "status": overall, "steps": results}


workflow_registry = WorkflowRegistry()
