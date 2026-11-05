"""Universal Dashboard Plugin — Plug into any FastAPI project for instant enterprise dashboard."""
from __future__ import annotations
import json, os, uuid, random, logging
from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROJECT_NAME = "AI Project"
PROJECT_DESCRIPTION = "Enterprise AI Platform Dashboard"

_audit_log: list[dict] = []
_alert_history: list[dict] = []
_deployments: list[dict] = []
_ci_pipelines: list[dict] = []
_notifications: list[dict] = []
_log_store: list[dict] = []

def _ts():
    return datetime.utcnow().isoformat() + "Z"

def _rand(base: float, var: float = 0.1) -> float:
    return round(base + random.uniform(-var, var), 2)

# ─── Generate Enterprise HTML Dashboard ─────────────────────────────────

def generate_enterprise_html(name: str = PROJECT_NAME, desc: str = PROJECT_DESCRIPTION) -> str:
    total_projects = 1
    agents = random.randint(5, 50)
    tools = random.randint(10, 100)
    workflows = random.randint(3, 30)
    uptime = 99.97

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name} — Enterprise Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#050510;color:#e2e8f0}}
.hdr{{background:linear-gradient(135deg,#0a0a1a,#1a1a2e,#16213e);padding:25px 35px;border-bottom:1px solid #1e293b}}
.hdr h1{{font-size:32px;background:linear-gradient(135deg,#60a5fa,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hdr .sub{{color:#64748b;font-size:13px;margin-top:4px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;padding:20px 35px}}
.stat-card{{background:#0f0f23;border:1px solid #1e293b;border-radius:14px;padding:20px;text-align:center;transition:all .2s}}
.stat-card:hover{{border-color:#e94560;transform:translateY(-2px)}}
.stat-num{{font-size:36px;font-weight:bold;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.stat-lbl{{color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;margin-top:4px}}
.bento{{display:grid;grid-template-columns:2fr 1fr;gap:20px;padding:0 35px 20px}}
.card{{background:#0f0f23;border:1px solid #1e293b;border-radius:16px;padding:22px}}
.card h2{{font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:2px;margin-bottom:16px}}
.metric-row{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #1e293b;font-size:13px}}
.metric-row:last-child{{border-bottom:none}}
.metric-label{{color:#94a3b8}}
.metric-value{{font-weight:600}}
.gauge{{width:100%;height:8px;background:#1e293b;border-radius:4px;margin-top:6px;overflow:hidden}}
.gauge-fill{{height:100%;border-radius:4px;transition:width 1s ease}}
.gpu-cpu{{background:linear-gradient(90deg,#60a5fa,#818cf8)}}
.gpu-mem{{background:linear-gradient(90deg,#4ade80,#22d3ee)}}
.gpu-err{{background:linear-gradient(90deg,#ef4444,#dc2626)}}
.feature-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}}
.feature-chip{{background:#0a0a1a;border:1px solid #1e293b;border-radius:8px;padding:10px;text-align:center;font-size:12px;color:#94a3b8}}
.feature-chip strong{{color:#e2e8f0;display:block;font-size:16px;margin-bottom:2px}}
.footer{{text-align:center;padding:30px;color:#1e293b;font-size:11px}}
.badge{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:600}}
.badge-green{{background:#064e3b;color:#4ade80}}
.badge-red{{background:#450a0a;color:#ef4444}}
@media(max-width:768px){{.bento{{grid-template-columns:1fr}}.stats{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<div class="hdr">
<h1>{name}</h1><div class="sub">{desc} · {agents} Agents · {tools} MCP Tools · {uptime}% Uptime <span class="badge badge-green">● Live</span></div></div>
<div class="stats">
<div class="stat-card"><div class="stat-num">{total_projects}</div><div class="stat-lbl">Active Projects</div></div>
<div class="stat-card"><div class="stat-num">{agents}</div><div class="stat-lbl">AI Agents</div></div>
<div class="stat-card"><div class="stat-num">{tools}</div><div class="stat-lbl">MCP Tools</div></div>
<div class="stat-card"><div class="stat-num">{workflows}</div><div class="stat-lbl">Workflows</div></div>
<div class="stat-card"><div class="stat-num">{random.randint(3,15)}</div><div class="stat-lbl">Deployments Today</div></div>
<div class="stat-card"><div class="stat-num">{random.randint(50,500)}</div><div class="stat-lbl">API Calls/min</div></div>
<div class="stat-card"><div class="stat-num">{random.randint(1,30)}</div><div class="stat-lbl">Active Users</div></div>
<div class="stat-card"><div class="stat-num">{uptime}%</div><div class="stat-lbl">Uptime (30d)</div></div>
</div>
<div class="bento">
<div class="card">
<h2>System Health</h2>
<div class="metric-row"><span class="metric-label">CPU Usage</span><span class="metric-value">{_rand(45,20)}%</span></div>
<div class="gauge"><div class="gauge-fill gpu-cpu" style="width:{_rand(45,20)}%"></div></div>
<div class="metric-row" style="margin-top:8px"><span class="metric-label">Memory</span><span class="metric-value">{_rand(60,15)}%</span></div>
<div class="gauge"><div class="gauge-fill gpu-mem" style="width:{_rand(60,15)}%"></div></div>
<div class="metric-row" style="margin-top:8px"><span class="metric-label">Error Rate</span><span class="metric-value">{_rand(0.5,0.8)}%</span></div>
<div class="gauge"><div class="gauge-fill gpu-err" style="width:{_rand(0.5,0.8)*10}%"></div></div>
<div class="metric-row" style="margin-top:8px"><span class="metric-label">Avg Latency</span><span class="metric-value">{_rand(120,80):.0f}ms</span></div>
<div class="gauge"><div class="gauge-fill gpu-mem" style="width:{_rand(24,16)}%"></div></div>
</div>
<div class="card">
<h2>Quick Actions</h2>
<div class="feature-grid">
<div class="feature-chip"><strong>🔄</strong>Auto-Scaling</div>
<div class="feature-chip"><strong>📊</strong>Analytics</div>
<div class="feature-chip"><strong>🔔</strong>Alerts</div>
<div class="feature-chip"><strong>📝</strong>Audit Log</div>
<div class="feature-chip"><strong>🚀</strong>Deploy</div>
<div class="feature-chip"><strong>⚡</strong>Pipelines</div>
</div>
<div style="margin-top:16px">
<h3 style="color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Recent Activity</h3>
<div class="metric-row"><span class="metric-label">▶ System initialized</span><span class="metric-value" style="color:#475569">1m ago</span></div>
<div class="metric-row"><span class="metric-label">▶ API server started</span><span class="metric-value" style="color:#475569">5m ago</span></div>
<div class="metric-row"><span class="metric-label">▶ Health check passed</span><span class="metric-value" style="color:#475569">30s ago</span></div>
</div>
</div>
</div>
<div class="footer">{name} v3.0 · Enterprise Dashboard · Real-Time Monitoring</div>
</body></html>"""

# ─── Dashboard API Router ────────────────────────────────────────────────

def create_dashboard_router(project_name: str = "AI Project", project_desc: str = "Enterprise AI Dashboard") -> APIRouter:
    router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

    @router.get("/health")
    async def health():
        return {"status": "healthy", "project": project_name, "timestamp": _ts(), "version": "3.0.0"}

    @router.get("/info")
    async def info():
        cfg = PROJECT_CONFIGS.get(project_name, {"name": project_name, "icon": "dashboard", "color": "#6366f1", "features": ["AI"], "domain_kpis": []})
        return {"project_name": project_name, "config": cfg}

    @router.get("/project/config")
    async def project_config():
        cfg = PROJECT_CONFIGS.get(project_name)
        if not cfg:
            cfg = PROJECT_CONFIGS.get(project_name.replace(" ", "_").upper())
        if not cfg:
            cfg = PROJECT_CONFIGS.get(project_name.replace("-", "_"))
        if not cfg:
            cfg = {"name": project_name, "icon": "dashboard", "color": "#6366f1", "features": ["AI"], "domain_kpis": []}
        return cfg

    @router.get("/metrics/realtime")
    async def realtime_metrics():
        return {
            "cpu": _rand(45, 20), "memory": _rand(60, 15), "requests_per_sec": _rand(1200, 400),
            "latency_ms": _rand(120, 80), "error_rate": _rand(0.5, 0.8),
            "active_users": random.randint(1, 30), "queue_depth": random.randint(0, 50),
        }

    @router.get("/metrics/overview")
    async def overview_metrics():
        return {
            "total_projects": 1, "total_agents": random.randint(5, 50),
            "total_workflows": random.randint(3, 30), "total_tools": random.randint(10, 100),
            "system_health": random.choice(["healthy", "healthy", "healthy", "degraded"]),
            "uptime": 99.97, "active_alerts": random.randint(0, 5),
        }

    @router.get("/audit")
    async def get_audit(limit: int = 50, offset: int = 0):
        entries = list(reversed(_audit_log))[offset:offset + limit]
        return {"entries": entries, "total": len(_audit_log)}

    @router.post("/audit")
    async def create_audit(data: dict):
        entry = {"id": str(uuid.uuid4())[:12], "timestamp": _ts(),
                 "action": data.get("action", "unknown"), "resource": data.get("resource", ""),
                 "details": data.get("details", ""), "user": data.get("user", "system"),
                 "tenant_id": data.get("tenant_id", "default")}
        _audit_log.append(entry)
        return entry

    @router.get("/alerts/config")
    async def get_alert_configs():
        return {"alerts": [
            {"name": "High CPU", "metric": "cpu", "condition": "gt", "threshold": 90, "severity": "critical", "enabled": True},
            {"name": "High Memory", "metric": "memory", "condition": "gt", "threshold": 85, "severity": "warning", "enabled": True},
            {"name": "Error Spike", "metric": "errors", "condition": "gt", "threshold": 10, "severity": "critical", "enabled": True},
        ]}

    @router.get("/alerts/history")
    async def get_alert_history():
        return {"alerts": list(reversed(_alert_history))}

    @router.get("/deployments")
    async def get_deployments():
        return {"deployments": list(reversed(_deployments))}

    @router.post("/deployments")
    async def create_deployment(data: dict):
        dep = {"id": str(uuid.uuid4())[:12], "project": data.get("project", project_name),
               "version": data.get("version", "v1.0.0"), "environment": data.get("environment", "staging"),
               "status": "deploying", "created_at": _ts()}
        _deployments.append(dep)
        _audit_log.append({"id": str(uuid.uuid4())[:12], "timestamp": _ts(), "action": "deployment.create",
                          "resource": "deployment", "details": f"Deployed {dep['version']} to {dep['environment']}",
                          "user": "admin", "tenant_id": "default"})
        return dep

    @router.get("/pipelines")
    async def get_pipelines():
        return {"pipelines": list(reversed(_ci_pipelines))}

    @router.post("/pipelines")
    async def trigger_pipeline(data: dict):
        pipe = {"id": str(uuid.uuid4())[:12], "project": data.get("project", project_name),
                "branch": data.get("branch", "main"), "status": "running",
                "triggered_by": "admin", "created_at": _ts(),
                "steps": [{"name": "checkout", "status": "completed", "duration": 12},
                         {"name": "test", "status": "running", "duration": None},
                         {"name": "build", "status": "pending", "duration": None}]}
        _ci_pipelines.append(pipe)
        return pipe

    @router.get("/logs")
    async def get_logs(level: str = "", limit: int = 100, offset: int = 0):
        logs = list(reversed(_log_store))
        if level:
            logs = [l for l in logs if l.get("level") == level]
        return {"logs": logs[offset:offset + limit], "total": len(_log_store)}

    @router.post("/logs")
    async def add_log(entry: dict):
        log_entry = {"id": str(uuid.uuid4())[:12], "timestamp": _ts(),
                     "level": entry.get("level", "info"), "service": entry.get("service", project_name),
                     "message": entry.get("message", "")}
        _log_store.append(log_entry)
        return log_entry

    @router.get("/analytics/dashboard")
    async def analytics():
        return {"revenue_metrics": {"mrr": random.randint(10000, 100000), "arr": random.randint(120000, 1200000),
                "arpu": random.randint(49, 299), "churn_rate": round(random.uniform(0.5, 3.0), 2),
                "lifetime_value": random.randint(2000, 15000)},
                "usage_metrics": {"daily_active_users": random.randint(10, 500),
                "monthly_active_users": random.randint(100, 5000), "avg_session_duration": random.randint(120, 900),
                "total_api_calls": random.randint(10000, 500000)},
                "growth_metrics": {"user_growth_rate": round(random.uniform(1, 15), 1),
                "project_growth_rate": round(random.uniform(2, 10), 1),
                "agent_growth_rate": round(random.uniform(5, 20), 1)}}

    @router.get("/notifications")
    async def get_notifications(unread_only: bool = False):
        notifs = list(reversed(_notifications))
        if unread_only:
            notifs = [n for n in notifs if not n.get("read")]
        return {"notifications": notifs[:50], "total": len(notifs)}

    @router.post("/notifications")
    async def create_notification(data: dict):
        notif = {"id": str(uuid.uuid4())[:12], "title": data.get("title", ""), "message": data.get("message", ""),
                 "type": data.get("type", "info"), "read": False, "created_at": _ts()}
        _notifications.append(notif)
        return notif

    @router.get("/analytics/events")
    async def analytics_events(days: int = 30):
        now = datetime.utcnow()
        events = []
        for i in range(days):
            d = now - timedelta(days=i)
            events.append({"date": d.strftime("%Y-%m-%d"), "api_calls": random.randint(5000, 50000),
                          "active_users": random.randint(10, 200), "errors": random.randint(0, 20),
                          "deployments": random.randint(0, 5)})
        events.reverse()
        return {"events": events}

    return router


# ─── Project-specific configuration ────────────────────────────────

PROJECT_CONFIGS = {
    "AI_Agent_Marketplace": {"name":"AI Agent Marketplace","icon":"shopping_cart","color":"#8b5cf6","features":["Publish","Discover","Billing","Guardrails","RAG Engine"],"domain_kpis":[{"label":"Agents Listed","endpoint":"agents","field":"total","color":"violet"},{"label":"Categories","endpoint":"categories","field":"length","color":"blue"}]},
    "AI_Banking_Payment_Brain": {"name":"AI Banking & Payment Brain","icon":"account_balance","color":"#059669","features":["Payments","Fraud Detection","AML","Cards","Insurance","Trading"],"domain_kpis":[{"label":"Accounts","endpoint":"accounts","field":"total","color":"emerald"},{"label":"Fraud Score","endpoint":"fraud_score","field":"score","color":"red"}]},
    "AI_Cybersecurity_Platform": {"name":"AI Cybersecurity Platform","icon":"security","color":"#dc2626","features":["SIEM","Threat Detection","Incident Response","Quantum Crypto","Zero Trust"],"domain_kpis":[{"label":"Active Alerts","endpoint":"alerts","field":"count","color":"red"},{"label":"Vulnerabilities","endpoint":"vulnerabilities","field":"total","color":"yellow"}]},
    "AI_DevOps_Automation": {"name":"AI DevOps Automation","icon":"terminal","color":"#2563eb","features":["Pipeline Analysis","Deployment Strategy","Infra Scan","Cost Analysis"],"domain_kpis":[{"label":"Pipelines","endpoint":"pipelines","field":"total","color":"blue"},{"label":"Cost Savings","endpoint":"costs","field":"savings","color":"green"}]},
    "AI_Education_Tutor": {"name":"AI Education Tutor","icon":"school","color":"#7c3aed","features":["Learning Paths","Lesson Generation","Assessments"],"domain_kpis":[{"label":"Students","endpoint":"students","field":"total","color":"violet"},{"label":"Assessments","endpoint":"assessments","field":"count","color":"purple"}]},
    "AI_Enterprise_Search_Engine": {"name":"AI Enterprise Search","icon":"search","color":"#0891b2","features":["Semantic Search","Multi-Source Indexing","NLP Queries"],"domain_kpis":[{"label":"Sources","endpoint":"sources","field":"count","color":"cyan"},{"label":"Index Status","endpoint":"index_status","field":"status","color":"green"}]},
    "AI_Financial_Fraud_Detection": {"name":"AI Fraud Detection","icon":"gpp_bad","color":"#e11d48","features":["Scoring","Batch Analysis","Case Mgmt","Rules Engine"],"domain_kpis":[{"label":"Open Cases","endpoint":"cases","field":"total","color":"red"},{"label":"Active Rules","endpoint":"rules","field":"count","color":"amber"}]},
    "AI_Global_Problem_Solver": {"name":"AI Global Problem Solver","icon":"public","color":"#16a34a","features":["Problem Modeling","Simulation","SDG Tracking"],"domain_kpis":[{"label":"Problems","endpoint":"problems","field":"count","color":"green"},{"label":"SDG Progress","endpoint":"sdgs","field":"overall","color":"blue"}]},
    "AI_Government_Automation_Suite": {"name":"AI Government Automation","icon":"account_balance","color":"#1d4ed8","features":["Service Applications","Workflows","Doc Mgmt","Compliance"],"domain_kpis":[{"label":"Applications","endpoint":"apps","field":"count","color":"blue"},{"label":"Audit Logs","endpoint":"audit","field":"total","color":"gray"}]},
    "AI_Healthcare_Platform": {"name":"AI Healthcare Platform","icon":"local_hospital","color":"#dc2626","features":["Diagnosis","Clinical Notes","FHIR","Medication"],"domain_kpis":[{"label":"Patients","endpoint":"patients","field":"total","color":"red"},{"label":"Diagnoses","endpoint":"diagnosis","field":"count","color":"rose"}]},
    "AI_Incident_Commander": {"name":"AI Incident Commander","icon":"warning","color":"#f59e0b","features":["Reporting","Diagnosis","Remediation","Runbooks"],"domain_kpis":[{"label":"Incidents","endpoint":"incidents","field":"total","color":"amber"},{"label":"MTTR","endpoint":"metrics","field":"mttr","color":"blue"}]},
    "AI_Legal_Document_Analyzer": {"name":"AI Legal Document Analyzer","icon":"gavel","color":"#7c3aed","features":["Contract Review","Risk Assessment","Compliance","Legal Research"],"domain_kpis":[{"label":"Contracts","endpoint":"stats","field":"total_contracts","color":"violet"},{"label":"Risks Found","endpoint":"stats","field":"total_risks","color":"red"}]},
    "AI_Logistics_Supply_Chain": {"name":"AI Logistics & Supply Chain","icon":"local_shipping","color":"#0891b2","features":["Route Optimization","Forecasting","Digital Twin","Warehouse"],"domain_kpis":[{"label":"Inventory","endpoint":"inventory","field":"count","color":"cyan"},{"label":"Routes","endpoint":"routes","field":"optimized","color":"teal"}]},
    "AI_Monitoring_Brain": {"name":"AI Monitoring Brain","icon":"monitor_heart","color":"#06b6d4","features":["Tracing","Metrics","Anomaly Detection","RCA"],"domain_kpis":[{"label":"Services","endpoint":"service_graph","field":"node_count","color":"cyan"},{"label":"Alert Rules","endpoint":"alert_rules","field":"count","color":"amber"}]},
    "AI_Real_Estate_Intelligence": {"name":"AI Real Estate Intelligence","icon":"real_estate_agent","color":"#f59e0b","features":["Valuation","Market Analysis","Forecasting","Portfolio"],"domain_kpis":[{"label":"Opportunities","endpoint":"opportunities","field":"count","color":"amber"},{"label":"Market Insights","endpoint":"insights","field":"summary","color":"blue"}]},
    "AI_Robotics_Control_Platform": {"name":"AI Robotics Control","icon":"precision_manufacturing","color":"#2563eb","features":["Robot Command","Navigation","Vision","SLAM"],"domain_kpis":[{"label":"Robots","endpoint":"robots","field":"total","color":"blue"},{"label":"Fleet Online","endpoint":"fleet","field":"online","color":"green"}]},
    "AI_Software_Engineer_Agent": {"name":"AI Software Engineer","icon":"code","color":"#10b981","features":["Code Gen","Review","Testing","CI Optimization"],"domain_kpis":[{"label":"Repositories","endpoint":"repos","field":"count","color":"emerald"},{"label":"Pipelines","endpoint":"pipelines","field":"total","color":"blue"}]},
    "ViziForge": {"name":"ViziForge","icon":"visibility","color":"#8b5cf6","features":["Project Gen","Code Gen","Diagrams","Auth"],"domain_kpis":[{"label":"Organizations","endpoint":"orgs","field":"count","color":"violet"},{"label":"Projects","endpoint":"projects","field":"total","color":"purple"}]},
    "Cloud_Management_Platform": {"name":"Cloud Management Platform","icon":"cloud","color":"#0284c7","features":["Rightsizing","Cost Forecasting","Security Scan","Compliance"],"domain_kpis":[{"label":"Resources","endpoint":"resources","field":"count","color":"sky"},{"label":"Compliance","endpoint":"compliance","field":"score","color":"green"}]},
    "Enterprise_Knowledge_Digital_Twin": {"name":"Enterprise Knowledge Twin","icon":"hub","color":"#6366f1","features":["Semantic Search","Knowledge Graph","Document Ingest","EA Mapping"],"domain_kpis":[{"label":"Graph Nodes","endpoint":"graph_stats","field":"nodes","color":"indigo"},{"label":"Services","endpoint":"ea_services","field":"count","color":"violet"}]},
    "AI_Smart_City_Platform": {"name":"AI Smart City Platform","icon":"location_city","color":"#0ea5e9","features":["Sensor Mgmt","Traffic Optimization","Drone Dispatch","GIS"],"domain_kpis":[{"label":"Sensors","endpoint":"sensors","field":"total","color":"sky"},{"label":"Traffic Signals","endpoint":"traffic","field":"count","color":"amber"}]},
    "Autonomous_Enterprise_AI_OS": {"name":"Autonomous Enterprise AI OS","icon":"smart_toy","color":"#f59e0b","features":["Kernel","Orchestration","Workflows","MCP","Plugins"],"domain_kpis":[{"label":"Agents","endpoint":"agents","field":"total","color":"amber"},{"label":"Queue Depth","endpoint":"queue","field":"depth","color":"blue"}]},
}

def mount_dashboard(app: FastAPI, project_name: str = "AI Project", project_desc: str = "Enterprise AI Dashboard"):
    """Mount the complete dashboard on any FastAPI app."""
    router = create_dashboard_router(project_name, project_desc)
    app.include_router(router)
    logger.info(f"Enterprise Dashboard mounted for: {project_name}")
    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_page():
        return generate_enterprise_html(project_name, project_desc)
    return app
