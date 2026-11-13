"""Model Context Protocol (MCP) gateway for the RUTHAMBHARA film studio.

The same tool registry is exposed three ways:

* JSON-RPC 2.0 over HTTP (``POST /mcp``) — mounted by :mod:`src.web.server`
* JSON-RPC 2.0 over stdio — ``python -m src.mcp_server`` or ``python main.py mcp``
* Python — :data:`mcp_registry` is importable by agents and the CLI

Tools are thin, guarded wrappers around :mod:`src.services`, so an external
agent (Claude Desktop, Cursor, CrewAI, LangGraph...) can read the screenplay,
query the GraphRAG index, trigger render runs and inspect quality gates without
knowing anything about this codebase.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.config import settings

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ruthambhara-film-studio"
SERVER_VERSION = settings.version


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Any]
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"tags": self.tags},
        }


class MCPRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, MCPTool] = {}
        self.calls = 0
        self.errors = 0

    # ── registration ─────────────────────────────────────────────────────
    def register(
        self,
        name: str,
        description: str,
        schema: Optional[dict] = None,
        tags: Optional[list[str]] = None,
    ) -> Callable[[Callable[[dict], Any]], Callable[[dict], Any]]:
        def decorator(fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
            self._tools[name] = MCPTool(
                name=name,
                description=description,
                input_schema=schema or {"type": "object", "properties": {}},
                handler=fn,
                tags=tags or [],
            )
            return fn

        return decorator

    def add(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[MCPTool]:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [tool.to_dict() for tool in self._tools.values()]

    # ── invocation ───────────────────────────────────────────────────────
    def call(self, name: str, arguments: Optional[dict] = None) -> dict:
        from src.services import studio

        self.calls += 1
        tool = self._tools.get(name)
        if not tool:
            self.errors += 1
            raise KeyError(f"unknown tool: {name}")
        arguments = arguments or {}
        guard = studio.guardrails.check_tool_call(name, arguments)
        studio.audit.record("mcp.tool_call", "agent", name, json.dumps(arguments)[:300],
                            outcome="ok" if guard.allowed else "blocked")
        if not guard.allowed:
            self.errors += 1
            raise PermissionError(f"guardrail blocked {name}: {guard.issues}")
        try:
            result = tool.handler(arguments)
        except Exception:
            self.errors += 1
            raise
        return {
            "content": [{"type": "text", "text": _dumps(result)}],
            "structuredContent": result if isinstance(result, dict) else {"result": result},
            "isError": False,
        }

    def stats(self) -> dict:
        return {"tools": len(self._tools), "calls": self.calls, "errors": self.errors}


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


mcp_registry = MCPRegistry()


# ─────────────────────────────────────────────────────────────────────────────
# Tools — screenplay & knowledge
# ─────────────────────────────────────────────────────────────────────────────


@mcp_registry.register(
    "script.catalog",
    "Return the parsed screenplay: acts, sequences, shots, cast and music themes.",
    {"type": "object", "properties": {}},
    tags=["screenplay", "read"],
)
def _script_catalog(args: dict) -> dict:
    from src.services import studio

    catalog = studio.script.catalog()
    return {
        key: catalog[key]
        for key in (
            "title", "telugu_title", "runtime", "runtime_minutes", "languages",
            "aspect_ratio", "total_acts", "total_sequences", "total_shots",
        )
    } | {
        "cast": catalog["cast"][:8],
        "music_themes": catalog["music_themes"],
        "acts": [
            {
                "number": act["number"],
                "subtitle": act["english_subtitle"],
                "sequences": [
                    {
                        "number": seq["number"],
                        "name": seq["english_name"],
                        "telugu_name": seq["telugu_name"],
                        "shots": len(seq["shots"]),
                    }
                    for seq in act["sequences"]
                ],
            }
            for act in catalog["acts"]
        ],
    }


@mcp_registry.register(
    "script.search",
    "Semantic + graph retrieval over the screenplay (GraphRAG).",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language or Telugu query"},
            "k": {"type": "integer", "default": 6, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    },
    tags=["rag", "graphrag"],
)
def _script_search(args: dict) -> dict:
    from src.services import studio

    studio.index()
    return studio.rag.search(str(args["query"]), k=int(args.get("k", 6)))


@mcp_registry.register(
    "script.ask",
    "Ask a grounded question about the screenplay and receive an answer with citations.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "k": {"type": "integer", "default": 6},
        },
        "required": ["question"],
    },
    tags=["rag", "llm"],
)
def _script_ask(args: dict) -> dict:
    from src.services import studio

    return studio.ask(str(args["question"]), k=int(args.get("k", 6)))


# ─────────────────────────────────────────────────────────────────────────────
# Tools — production
# ─────────────────────────────────────────────────────────────────────────────


@mcp_registry.register(
    "pipeline.run",
    "Start an end-to-end film production run in the background; returns a run id.",
    {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["sample", "analysis", "full"], "default": "sample"},
            "mode": {"type": "string", "enum": ["hybrid", "parallel", "sequential"], "default": "hybrid"},
            "language": {"type": "string", "default": "te"},
            "max_shots": {"type": "integer", "default": 12},
            "sample_sequences": {"type": "integer", "default": 3},
            "render_media": {"type": "boolean", "default": True},
            "render_video": {"type": "boolean", "default": True},
        },
    },
    tags=["pipeline", "write"],
)
def _pipeline_run(args: dict) -> dict:
    from src.services import studio

    run = studio.pipeline.submit(args)
    return {
        "run_id": run["id"],
        "status": run["status"],
        "events_url": f"/api/runs/{run['id']}/events",
        "poll_url": f"/api/runs/{run['id']}",
    }


@mcp_registry.register(
    "pipeline.status",
    "Fetch a run record, including progress, stage, artifacts and quality gate.",
    {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    tags=["pipeline", "read"],
)
def _pipeline_status(args: dict) -> dict:
    from src.services import studio

    run = studio.pipeline.get(str(args["run_id"]))
    if not run:
        raise KeyError(f"run not found: {args['run_id']}")
    result = run.get("result") or {}
    return {
        "id": run["id"],
        "status": run["status"],
        "stage": run.get("stage"),
        "progress": run.get("progress"),
        "error": run.get("error"),
        "elapsed_sec": result.get("elapsed_sec"),
        "quality": result.get("quality"),
        "agents": result.get("agents"),
        "artifacts": result.get("artifacts"),
        "events": len(run.get("events", [])),
    }


@mcp_registry.register(
    "pipeline.list",
    "List the most recent production runs.",
    {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}}},
    tags=["pipeline", "read"],
)
def _pipeline_list(args: dict) -> dict:
    from src.services import studio

    return {"runs": studio.pipeline.list(limit=int(args.get("limit", 10)))}


# ─────────────────────────────────────────────────────────────────────────────
# Tools — observability & governance
# ─────────────────────────────────────────────────────────────────────────────


@mcp_registry.register(
    "quality.report",
    "Return the quality gate for a run (or the latest run when omitted).",
    {"type": "object", "properties": {"run_id": {"type": "string"}}},
    tags=["quality", "read"],
)
def _quality_report(args: dict) -> dict:
    from src.services import studio

    run_id = args.get("run_id")
    if not run_id:
        latest = studio.pipeline.list(limit=1)
        if not latest:
            return {"status": "no_runs"}
        run_id = latest[0]["id"]
    run = studio.pipeline.get(str(run_id)) or {}
    result = run.get("result") or {}
    return {"run_id": run_id, "status": run.get("status"), "quality": result.get("quality", {})}


@mcp_registry.register(
    "providers.status",
    "Report which free/premium AI providers are available right now.",
    {"type": "object", "properties": {}},
    tags=["observability"],
)
def _providers_status(args: dict) -> dict:
    from src.services import studio

    return studio.providers.status(refresh=True)


@mcp_registry.register(
    "evals.summary",
    "Summarise recorded pipeline evaluations and export fine-tuning data.",
    {"type": "object", "properties": {"export": {"type": "boolean", "default": False}}},
    tags=["evaluation", "mlops"],
)
def _evals_summary(args: dict) -> dict:
    from src.services import studio

    summary = studio.evals.summary()
    if args.get("export"):
        summary["finetune"] = studio.evals.export_finetune()
    return summary


@mcp_registry.register(
    "memory.recall",
    "Recall agent/semantic memories relevant to a query.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "default": 5},
            "scope": {"type": "string"},
        },
        "required": ["query"],
    },
    tags=["memory"],
)
def _memory_recall(args: dict) -> dict:
    from src.services import studio

    return {
        "memories": studio.memory.recall(
            str(args["query"]), k=int(args.get("k", 5)), scope=args.get("scope")
        )
    }


@mcp_registry.register(
    "graph.spec",
    "Return the LangGraph DAG (nodes, edges, repair loop) used by the pipeline.",
    {"type": "object", "properties": {}},
    tags=["agents", "langgraph"],
)
def _graph_spec(args: dict) -> dict:
    from src.graph_engine import film_graph_runner
    from src.models.schemas import PipelineMode

    return film_graph_runner.spec(PipelineMode.HYBRID)


@mcp_registry.register(
    "dashboard.snapshot",
    "Full studio snapshot used by the dashboard.",
    {"type": "object", "properties": {}},
    tags=["observability", "dashboard"],
)
def _dashboard_snapshot(args: dict) -> dict:
    from src.services import studio

    snapshot = studio.snapshot()
    snapshot.pop("models", None)
    return snapshot


# ─────────────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0
# ─────────────────────────────────────────────────────────────────────────────


def _result(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def handle_request(payload: dict) -> dict:
    """Dispatch one JSON-RPC request. Never raises."""
    request_id = payload.get("id")
    method = str(payload.get("method", ""))
    params = payload.get("params") or {}

    if method in {"initialize", "mcp.initialize"}:
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
                "prompts": {"listChanged": False},
            },
        })

    if method in {"ping", "mcp.ping"}:
        return _result(request_id, {})

    if method in {"tools/list", "mcp.tools/list"}:
        return _result(request_id, {"tools": mcp_registry.list_tools()})

    if method in {"tools/call", "mcp.tools/call"}:
        name = params.get("name") or params.get("tool")
        try:
            return _result(request_id, mcp_registry.call(str(name), params.get("arguments") or {}))
        except KeyError as exc:
            return _error(request_id, -32601, str(exc))
        except PermissionError as exc:
            return _error(request_id, -32003, "guardrail_blocked", str(exc))
        except Exception as exc:  # noqa: BLE001 - JSON-RPC boundary
            return _error(request_id, -32603, f"{type(exc).__name__}: {exc}")

    if method in {"resources/list", "mcp.resources/list"}:
        return _result(request_id, {"resources": [
            {
                "uri": "ruthambhara://screenplay/catalog",
                "name": "Screenplay catalog",
                "mimeType": "application/json",
            },
            {
                "uri": "ruthambhara://runs/latest",
                "name": "Latest production run",
                "mimeType": "application/json",
            },
        ]})

    if method in {"prompts/list", "mcp.prompts/list"}:
        return _result(request_id, {"prompts": []})

    if method.startswith("notifications/"):
        return {"jsonrpc": "2.0"}

    return _error(request_id, -32601, f"method not found: {method}")


def handle_http(payload: dict | list) -> dict | list:
    """Handle a single request or a batch (HTTP transport)."""
    if isinstance(payload, list):
        return [handle_request(item) for item in payload]
    return handle_request(payload)


# ─────────────────────────────────────────────────────────────────────────────
# stdio transport
# ─────────────────────────────────────────────────────────────────────────────


def serve_stdio() -> None:
    """Line-delimited JSON-RPC over stdin/stdout (MCP stdio transport)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            response: Any = _error(None, -32700, "parse error", str(exc))
        else:
            response = handle_http(payload)
        if response is None:
            continue
        # Notifications intentionally produce no response.
        if isinstance(response, dict) and "id" not in response:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover - transport entry point
    serve_stdio()
