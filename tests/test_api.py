"""End-to-end tests for the FastAPI studio API, dashboard and MCP transport."""
from __future__ import annotations

import time


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["script_exists"] is True


def test_root_lists_dashboard(client):
    payload = client.get("/").json()
    assert payload["dashboard"] == "/dashboard"
    assert any("mcp" in endpoint for endpoint in payload["endpoints"])


def test_dashboard_is_self_contained(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert "RUTHAMBHARA" in html
    assert "GraphRAG console" in html
    assert "/api/dashboard" in html
    # Guard against an accidental str.format() of the CSS/JS braces.
    assert "{app_name}" not in html


def test_studio_snapshot(client):
    payload = client.get("/api/dashboard").json()
    for key in ("config", "script", "pipeline", "providers", "agents", "evals", "rag", "mcp"):
        assert key in payload, f"snapshot missing {key}"
    assert len(payload["agents"]) == 8


def test_graph_spec(client):
    payload = client.get("/api/graph").json()
    assert len(payload["nodes"]) >= 8
    assert payload["engine"] in {"langgraph", "builtin"}
    assert payload["entry"]


def test_script_catalog(client):
    payload = client.get("/api/script").json()
    assert payload["title"] == "RUTHAMBHARA"
    assert payload["total_acts"] >= 6
    assert payload["total_sequences"] >= 30


def test_legacy_endpoints(client):
    assert client.get("/script").status_code == 200
    scenes = client.get("/scenes").json()
    assert scenes["total_shots"] > 0
    models = client.get("/models").json()
    assert "llm" in models["categories"]


def test_graphrag_ask(client):
    response = client.post("/api/ask", json={"question": "Who is Veera?", "k": 4})
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].strip()
    assert payload["citations"]


def test_mcp_tools_listed(client):
    payload = client.get("/api/mcp/tools").json()
    names = {tool["name"] for tool in payload["tools"]}
    assert payload["tools"]
    assert {"script.catalog", "pipeline.run", "quality.report", "graph.spec"} <= names


def test_mcp_initialize_over_http(client):
    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["serverInfo"]["name"] == "ruthambhara-film-studio"


def test_mcp_tool_call(client):
    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "script.catalog", "arguments": {}},
    })
    payload = response.json()
    assert payload["result"]["isError"] is False
    structured = payload["result"]["structuredContent"]
    assert structured["title"] == "RUTHAMBHARA"


def test_run_lifecycle_and_artifacts(client):
    submitted = client.post("/api/runs", json={
        "scope": "sample",
        "sample_sequences": 1,
        "max_shots": 3,
        "render_media": False,
        "render_video": False,
    })
    assert submitted.status_code == 200
    run = submitted.json()["run"]
    run_id = run["id"]
    assert run["status"] in {"queued", "running"}

    deadline = time.time() + 120
    final = None
    while time.time() < deadline:
        final = client.get(f"/api/runs/{run_id}").json()
        if final["status"] not in {"queued", "running"}:
            break
        time.sleep(0.5)

    assert final is not None
    assert final["status"] == "completed", final.get("error")
    result = final["result"]
    assert result["film"]["title"] == "RUTHAMBHARA"
    assert result["quality"]["mean_score"] >= 0.8
    assert len(result["agents"]) == 8
    assert result["artifacts"]["storyboard"]["frames"] > 0
    assert result["evaluation"]["overall"] > 0

    listed = client.get("/api/runs").json()["runs"]
    assert any(item["id"] == run_id for item in listed)

    artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()
    assert artifacts["count"] > 0

    events = client.get(f"/api/runs/{run_id}/events").text
    assert "run.closed" in events or "agent.finished" in events


def test_eval_export(client):
    payload = client.post("/api/evals/export", json={}).json()
    assert "pairs" in payload or "path" in payload


def test_metrics_endpoint(client):
    text = client.get("/metrics").text
    assert "afp_" in text or "no metrics" in text
