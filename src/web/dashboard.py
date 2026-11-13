"""Self-contained studio dashboard served at ``/dashboard``.

The page is deliberately dependency-free (plain HTML/CSS/JS) so the MVP works
with a single ``uvicorn`` process — no Node build step required.  It reads the
live studio snapshot from ``/api/dashboard`` and streams run events over SSE.
"""
from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RUTHAMBHARA — Agentic Film Studio</title>
<style>
  :root{
    --bg:#07090f; --bg2:#0d1119; --panel:#111726; --panel2:#151d2e;
    --line:#22304a; --line2:#2c3d5c;
    --text:#e8eefc; --muted:#8fa3c4; --dim:#5f7396;
    --gold:#e0b062; --gold2:#f6d492; --amber:#ffb347;
    --red:#ff6b6b; --green:#4ade80; --cyan:#5eead4; --violet:#a78bfa; --blue:#60a5fa;
    --radius:14px; --mono:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    background:
      radial-gradient(1200px 600px at 80% -10%, rgba(224,176,98,.14), transparent 60%),
      radial-gradient(900px 500px at -10% 20%, rgba(96,165,250,.10), transparent 60%),
      var(--bg);
    color:var(--text);
    font:14px/1.5 Inter,Segoe UI,system-ui,-apple-system,sans-serif;
    min-height:100vh;
  }
  a{color:var(--gold2);text-decoration:none}
  a:hover{text-decoration:underline}
  button{font:inherit;cursor:pointer}
  .wrap{max-width:1520px;margin:0 auto;padding:20px 24px 60px}
  header.top{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:22px}
  .brand{display:flex;align-items:center;gap:14px;min-width:340px}
  .mark{
    width:54px;height:54px;border-radius:14px;display:grid;place-items:center;
    background:linear-gradient(145deg,#2a1f10,#120d07);border:1px solid #5c4522;
    color:var(--gold2);font-size:26px;font-weight:700;
    box-shadow:0 8px 26px rgba(0,0,0,.45), inset 0 0 22px rgba(224,176,98,.12);
  }
  .brand h1{margin:0;font-size:22px;letter-spacing:.20em;font-weight:700}
  .brand p{margin:2px 0 0;color:var(--muted);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
  .pills{display:flex;gap:8px;flex-wrap:wrap;flex:1}
  .pill{
    display:inline-flex;align-items:center;gap:7px;padding:6px 11px;border-radius:999px;
    background:var(--panel);border:1px solid var(--line);color:var(--muted);font-size:12px;
  }
  .dot{width:7px;height:7px;border-radius:50%;background:var(--dim)}
  .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
  .dot.warn{background:var(--amber);box-shadow:0 0 8px var(--amber)}
  .dot.off{background:var(--red)}
  .actions{display:flex;gap:10px;align-items:center}
  .btn{
    border:1px solid var(--line2);background:var(--panel2);color:var(--text);
    padding:10px 16px;border-radius:10px;transition:.18s;white-space:nowrap;
  }
  .btn:hover{border-color:var(--gold);transform:translateY(-1px)}
  .btn.primary{
    background:linear-gradient(135deg,#d9a54f,#a97a2d);border-color:#f0c67e;color:#1a1206;
    font-weight:700;box-shadow:0 8px 22px rgba(224,176,98,.22);
  }
  .btn.primary:disabled{opacity:.55;cursor:not-allowed;transform:none}
  .btn.ghost{background:transparent}
  .btn.small{padding:6px 10px;border-radius:8px;font-size:12px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
  .kpi{background:linear-gradient(180deg,var(--panel),#0c111c);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px}
  .kpi .label{color:var(--muted);font-size:11px;letter-spacing:.10em;text-transform:uppercase}
  .kpi .value{font-size:26px;font-weight:700;margin-top:4px;line-height:1.15}
  .kpi .sub{color:var(--dim);font-size:11px;margin-top:3px}
  .kpi.gold .value{color:var(--gold2)}
  .kpi.green .value{color:var(--green)}
  .kpi.red .value{color:var(--red)}
  .kpi.cyan .value{color:var(--cyan)}
  .panel{background:linear-gradient(180deg,rgba(21,29,46,.9),rgba(13,17,25,.95));border:1px solid var(--line);border-radius:var(--radius);padding:18px;margin-bottom:18px}
  .panel h2{margin:0 0 4px;font-size:15px;letter-spacing:.05em}
  .panel h3{margin:18px 0 8px;font-size:13px;color:var(--gold2);letter-spacing:.06em;text-transform:uppercase}
  .panel .hint{color:var(--muted);font-size:12px;margin:0 0 14px}
  .panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:10px}
  .progress{height:8px;background:#0a0e17;border:1px solid var(--line);border-radius:99px;overflow:hidden;margin:12px 0}
  .progress>div{height:100%;width:0;background:linear-gradient(90deg,#a97a2d,#f6d492);transition:width .45s ease}
  .agent-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:10px;margin-top:12px}
  .agent{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:11px 12px;position:relative;overflow:hidden}
  .agent .name{font-weight:700;font-size:12.5px;letter-spacing:.04em}
  .agent .desc{color:var(--dim);font-size:10.5px;margin-top:3px;min-height:28px}
  .agent .meta{display:flex;justify-content:space-between;align-items:center;margin-top:7px;font-size:10.5px;color:var(--muted);font-family:var(--mono)}
  .agent.completed{border-color:rgba(74,222,128,.45)}
  .agent.running{border-color:rgba(255,179,71,.65);box-shadow:inset 0 0 18px rgba(255,179,71,.08)}
  .agent.failed{border-color:rgba(255,107,107,.6)}
  .badge{padding:2px 7px;border-radius:99px;font-size:10px;border:1px solid var(--line2);color:var(--muted);font-family:var(--mono)}
  .badge.completed{color:var(--green);border-color:rgba(74,222,128,.4)}
  .badge.running{color:var(--amber);border-color:rgba(255,179,71,.5)}
  .badge.failed{color:var(--red);border-color:rgba(255,107,107,.5)}
  .badge.queued,.badge.skipped{color:var(--dim)}
  .tabs{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 14px}
  .tab{border:1px solid var(--line);background:var(--panel);color:var(--muted);padding:8px 13px;border-radius:9px;font-size:12.5px}
  .tab:hover{color:var(--text);border-color:var(--line2)}
  .tab.active{background:rgba(224,176,98,.12);border-color:var(--gold);color:var(--gold2);font-weight:600}
  .grid{display:grid;gap:12px}
  .g2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
  .g3{grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
  .g4{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
  .card{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:12px;min-width:0}
  .card .title{font-weight:650;font-size:12.5px}
  .card .sub{color:var(--muted);font-size:11px;margin-top:2px}
  .thumb{width:100%;display:block;border-radius:8px;border:1px solid var(--line);background:#05070b;aspect-ratio:16/9;object-fit:cover}
  .portrait{width:100%;border-radius:9px;border:1px solid var(--line);background:#05070b;aspect-ratio:4/5;object-fit:cover}
  video{width:100%;border-radius:9px;border:1px solid var(--line);background:#000}
  audio{width:100%;margin-top:6px;height:32px}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:600}
  td.mono,.mono{font-family:var(--mono);font-size:11px}
  .score{font-weight:700}
  .score.good{color:var(--green)} .score.warn{color:var(--amber)} .score.bad{color:var(--red)}
  .empty{color:var(--dim);border:1px dashed var(--line2);border-radius:11px;padding:26px;text-align:center}
  .log{background:#05070c;border:1px solid var(--line);border-radius:10px;padding:11px;max-height:260px;overflow:auto;font-family:var(--mono);font-size:11px;color:#a9bbd8;white-space:pre-wrap}
  .log .t{color:var(--gold)} .log .e{color:var(--red)} .log .s{color:var(--green)}
  .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .chip{font-size:10.5px;padding:3px 8px;border-radius:99px;background:#0c1220;border:1px solid var(--line);color:var(--muted)}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:5px 14px;font-size:12px}
  .kv .k{color:var(--muted)}
  .split{display:grid;grid-template-columns:1.2fr .8fr;gap:14px}
  @media (max-width:900px){.split{grid-template-columns:1fr}}
  .ask{display:flex;gap:8px;margin:10px 0}
  .ask input{flex:1;background:#0a0f1a;border:1px solid var(--line2);color:var(--text);padding:11px 13px;border-radius:10px;font:inherit;outline:none}
  .ask input:focus{border-color:var(--gold)}
  .answer{background:#0a101c;border:1px solid var(--line);border-radius:10px;padding:13px;white-space:pre-wrap;font-size:12.5px;color:#cfdcf2}
  .hit{border-left:2px solid var(--gold);padding:6px 10px;margin:7px 0;background:#0a101b;border-radius:0 8px 8px 0}
  .hit .kind{color:var(--gold2);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
  .hit .txt{color:#b9c9e2;font-size:11.5px;margin-top:2px}
  .seq{border:1px solid var(--line);border-radius:10px;margin:7px 0;background:var(--panel2)}
  .seq summary{cursor:pointer;padding:10px 12px;list-style:none}
  .seq summary::-webkit-details-marker{display:none}
  .seq summary:before{content:"▸";color:var(--gold);margin-right:8px}
  .seq[open] summary:before{content:"▾"}
  .shot{border-top:1px solid var(--line);padding:9px 12px;font-size:11.5px;color:#b9c9e2}
  .shot b{color:var(--text)}
  .muted{color:var(--muted)} .dim{color:var(--dim)}
  .right{text-align:right} .nowrap{white-space:nowrap}
  .flex{display:flex;gap:10px;align-items:center} .between{justify-content:space-between}
  .ok{color:var(--green)} .bad{color:var(--red)} .warnc{color:var(--amber)}
  .foot{color:var(--dim);font-size:11px;text-align:center;margin-top:26px}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <div class="mark">ఋ</div>
      <div>
        <h1>RUTHAMBHARA</h1>
        <p>Agentic Film Studio · Telugu feature pipeline</p>
      </div>
    </div>
    <div class="pills" id="pills"><span class="pill">connecting…</span></div>
    <div class="actions">
      <button class="btn ghost" id="refreshBtn" title="Reload the studio snapshot">⟳ Refresh</button>
      <button class="btn primary" id="runBtn">▶ Run MVP</button>
    </div>
  </header>

  <section class="kpis" id="kpis"></section>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>Production run</h2>
        <p class="hint" id="runHint">Live LangGraph orchestration · 8 specialist agents · bounded quality loop</p>
      </div>
      <div class="flex">
        <span class="badge" id="runBadge">idle</span>
        <span class="badge mono" id="runId">—</span>
      </div>
    </div>
    <div class="progress"><div id="progressBar"></div></div>
    <div class="agent-grid" id="agents"></div>
    <h3 style="margin-bottom:6px">Event stream</h3>
    <div class="log" id="eventLog">Waiting for a run…</div>
  </section>

  <nav class="tabs" id="tabs"></nav>
  <section id="tabContent" class="panel"><div class="empty">Loading studio…</div></section>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>GraphRAG console</h2>
        <p class="hint">Hybrid vector + screenplay-knowledge-graph retrieval, grounded answers with citations.</p>
      </div>
      <span class="badge mono" id="ragBadge">—</span>
    </div>
    <form class="ask" id="askForm">
      <input id="askInput" placeholder="e.g. What happens to Veera in Act 3? / విరాస్ కథ?" autocomplete="off"/>
      <button class="btn primary" type="submit">Ask</button>
    </form>
    <div id="askAnswer"></div>
    <div id="ragHits"></div>
  </section>

  <div class="foot">RUTHAMBHARA Agentic Film Studio · FastAPI · LangGraph · GraphRAG · MCP · free-first providers</div>
</div>

<script>
"use strict";
const S = {snap:null, spec:null, run:null, events:[], tab:"overview", cache:{}, stream:null, poll:null, busy:false};
const TABS = [
  ["overview","Overview"],["storyboard","Storyboard"],["characters","Characters"],
  ["voice","Voice & Subs"],["animatic","Animatic"],["render","Render"],
  ["quality","Quality"],["evals","Evaluations"],["ops","Ops & Governance"]
];
const $ = (s)=>document.querySelector(s);
const esc = (v)=>String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtBytes = (n)=> n>1e9 ? (n/1e9).toFixed(2)+" GB" : n>1e6 ? (n/1e6).toFixed(1)+" MB" : n>1e3 ? (n/1e3).toFixed(1)+" KB" : (n||0)+" B";
const pct = (v)=> Math.round((Number(v)||0)*100)+"%";
const num = (v,d=0)=> (v===undefined||v===null) ? "—" : Number(v).toFixed(d);
const scoreClass = (v)=> v>=.85?"good":v>=.7?"warn":"bad";
const statusClass = (s)=> ({completed:"completed",failed:"failed",running:"running"}[s]||"queued");

async function api(path, opts={}){
  const res = await fetch(path, {headers:{"Content-Type":"application/json"}, ...opts});
  if(!res.ok) throw new Error(res.status+" "+res.statusText+" · "+path);
  const ct = res.headers.get("content-type")||"";
  return ct.includes("json") ? res.json() : res.text();
}
async function loadJSON(rel){
  if(!rel) return null;
  if(S.cache[rel] !== undefined) return S.cache[rel];
  try { S.cache[rel] = await api("/artifacts/"+rel); }
  catch(e){ S.cache[rel] = null; }
  return S.cache[rel];
}

async function boot(){
  try{
    const [snap, spec] = await Promise.all([api("/api/dashboard"), api("/api/graph")]);
    S.snap = snap; S.spec = spec;
    S.run = snap.latest || null;
    renderAll();
    if(S.run && S.run.status === "running") attachStream(S.run.id);
  }catch(err){
    $("#pills").innerHTML = '<span class="pill"><span class="dot off"></span>API unreachable</span>';
    $("#tabContent").innerHTML = '<div class="empty">Could not reach the API. Start the server with <b>python main.py serve</b>.</div>';
  }
}

function renderAll(){
  renderPills(); renderKpis(); renderPipeline(); renderTabs(); renderTab(); renderEvents();
  renderRagBadge();
}

function renderPills(){
  const cfg = S.snap?.config||{};
  const active = S.snap?.provider_status?.llm?.active || "template-reasoner";
  const script = S.snap?.script||{};
  const latest = S.run;
  const items = [
    `<span class="pill"><span class="dot ${script.exists?"on":"off"}"></span>${script.exists?"Screenplay loaded":"Screenplay missing"}</span>`,
    `<span class="pill"><span class="dot on"></span>LangGraph · ${esc(S.spec?.engine||"builtin")}</span>`,
    `<span class="pill"><span class="dot ${S.snap?.pipeline?.status==="running"?"warn":"on"}"></span>${esc(S.snap?.pipeline?.status||"idle")}</span>`,
    `<span class="pill"><span class="dot on"></span>LLM · ${esc(active)}</span>`,
    `<span class="pill"><span class="dot on"></span>FFmpeg · ${(S.snap?.providers||[]).find(p=>p.name==="ffmpeg" && p.available)?"ready":"optional"}</span>`,
    `<span class="pill">v${esc(S.snap?.version||"")}</span>`,
    latest ? `<span class="pill mono">${esc(latest.id)}</span>` : ""
  ];
  $("#pills").innerHTML = items.join("");
}

function renderKpis(){
  const r = S.run?.result || {};
  const film = r.film || {};
  const q = r.quality || {};
  const art = S.snap?.artifacts || {};
  const evalScore = r.evaluation?.overall;
  const k = [
    ["Acts", film.acts ?? "—", `${film.sequences ?? "—"} sequences`, "gold"],
    ["Shots", film.shots ?? "—", `${film.cast ?? "—"} cast · ${film.music_themes ?? "—"} themes`, ""],
    ["Quality", q.mean_score!=null?num(q.mean_score,3):"—", q.passed?"gate passed":"gate pending", q.passed?"green":(q.decision==="review"?"red":""), q],
    ["Eval", evalScore!=null?num(evalScore,3):"—", r.evaluation?.passed?"rubric passed":"no evaluation", evalScore>=.75?"cyan":""],
    ["Artifacts", `${art.total_files ?? 0}`, fmtBytes(art.total_bytes||0), "cyan"],
    ["Runs", S.snap?.pipeline?.total_runs ?? 0, `${S.snap?.pipeline?.running_jobs||0} running`, ""],
    ["Runtime", film.runtime_minutes?film.runtime_minutes+"′":"205′", (film.languages||[]).join(" · ")||"te · ta · hi", ""],
    ["Elapsed", r.elapsed_sec!=null?num(r.elapsed_sec,1)+"s":"—", r.graph?`${r.graph.repair_loops||0} repair loops`:"—", ""]
  ];
  $("#kpis").innerHTML = k.map(([label,value,sub,cls])=>`
    <div class="kpi ${cls||""}">
      <div class="label">${esc(label)}</div>
      <div class="value">${esc(value)}</div>
      <div class="sub">${esc(sub)}</div>
    </div>`).join("");
}

function renderPipeline(){
  const nodes = S.spec?.nodes || [];
  const results = {};
  (S.run?.result?.agents||[]).forEach(a=>results[a.name]=a);
  const agents = S.snap?.agents||[];
  const order = nodes.length?nodes:agents.map(a=>({id:a.name,label:a.label,description:a.description}));
  $("#agents").innerHTML = order.map((n,i)=>{
    const name = n.id||n.name;
    const res = results[name]||{};
    const status = res.status || (S.run?.status==="running" && S.run?.stage ? "" : "");
    const st = status?statusClass(status):"queued";
    return `<div class="agent ${st}">
      <div class="name">${String(i+1).padStart(2,"0")} · ${esc(n.label||name)}</div>
      <div class="desc">${esc(n.description||"")}</div>
      <div class="meta"><span>${res.duration_sec!=null?num(res.duration_sec,2)+"s":"—"}</span><span class="badge ${st}">${esc(status||"queued")}</span></div>
    </div>`;
  }).join("");
  const progress = Number(S.run?.progress||0);
  $("#progressBar").style.width = Math.max(2, Math.round(progress*100))+"%";
  const badge = $("#runBadge");
  badge.textContent = S.run?.status || "idle";
  badge.className = "badge "+statusClass(S.run?.status);
  $("#runId").textContent = S.run?.id || "—";
  const stage = S.run?.stage;
  $("#runHint").textContent = S.run?.error
    ? "Error: "+S.run.error
    : stage ? `Stage: ${stage} · ${pct(progress)} · ${S.run?.result?.elapsed_sec ? num(S.run.result.elapsed_sec,1)+"s" : "running"}` 
    : "Live LangGraph orchestration · 8 specialist agents · bounded quality loop";
  $("#runBtn").disabled = S.busy || S.run?.status==="running";
  $("#runBtn").textContent = S.run?.status==="running" ? "● Running…" : "▶ Run MVP";
}

function renderEvents(){
  const evs = S.events.slice(-140);
  if(!evs.length){
    const runEvents = (S.run?.events||[]).slice(-60);
    $("#eventLog").innerHTML = runEvents.length
      ? runEvents.map(e=>line(e)).join("")
      : "Waiting for a run…";
  } else {
    $("#eventLog").innerHTML = evs.map(e=>line(e)).join("");
  }
  const log = $("#eventLog"); log.scrollTop = log.scrollHeight;
  function line(e){
    const t = (e.timestamp||"").split("T")[1]?.replace("Z","")||"";
    const cls = e.level==="error"?"e":(e.type==="run.stage"?"s":"");
    const data = e.data?JSON.stringify(e.data):"";
    return `<div><span class="t">${t}</span> <span class="${cls}">${esc(e.type)}</span> ${esc(data).slice(0,420)}</div>`;
  }
}

function renderTabs(){
  $("#tabs").innerHTML = TABS.map(([id,label])=>
    `<button class="tab ${S.tab===id?"active":""}" data-tab="${id}">${label}</button>`
  ).join("");
  $("#tabs").querySelectorAll("button").forEach(b=>b.onclick=()=>{S.tab=b.dataset.tab;renderTabs();renderTab();});
}

async function renderTab(){
  const el = $("#tabContent");
  const r = S.run?.result;
  try{
    switch(S.tab){
      case "overview": return el.innerHTML = await overviewTab(r);
      case "storyboard": return el.innerHTML = await storyboardTab(r);
      case "characters": return el.innerHTML = await charactersTab(r);
      case "voice": return el.innerHTML = await voiceTab(r);
      case "animatic": return el.innerHTML = await animaticTab(r);
      case "render": return el.innerHTML = await renderTabPanel(r);
      case "quality": return el.innerHTML = await qualityTab(r);
      case "evals": return el.innerHTML = evalsTab(r);
      case "ops": return el.innerHTML = await opsTab(r);
      default: return el.innerHTML = '<div class="empty">Unknown tab.</div>';
    }
  }catch(err){
    el.innerHTML = `<div class="empty">Could not render this tab: ${esc(err.message)}</div>`;
  }
}

async function overviewTab(r){
  let catalog = S.cache.catalog;
  if(!catalog){ try{ catalog = S.cache.catalog = await api("/api/script"); }catch(e){} }
  const film = r?.film||{};
  const guard = r?.guardrail;
  const seqRows = (catalog?.acts||[]).slice(0,3).map(act=>`
    <details class="seq"><summary><b>Act ${act.number}</b> · ${esc(act.english_subtitle)} <span class="dim">· ${act.sequences.length} sequences · ${act.start_time||""} → ${act.end_time||""}</span></summary>
      ${act.sequences.map(seq=>`
        <details class="seq" style="margin:6px 10px"><summary>Seq ${seq.number} · ${esc(seq.english_name)} <span class="dim">· ${seq.runtime_minutes||"?"}′ · ${seq.shots.length} shots</span></summary>
        ${seq.shots.slice(0,6).map(sh=>`<div class="shot"><b>${esc(sh.number)}</b> · ${esc(sh.setting).slice(0,160)} · ${esc(sh.emotion_context||"")} <span class="dim">· ${num(sh.duration_sec,1)}s · ${esc(sh.lens||"standard")}</span></div>`).join("")}
        </details>`).join("")}
    </details>`).join("");
  const filmCard = `
    <div class="card">
      <div class="title" style="font-size:16px">${esc(catalog?.title||"RUTHAMBHARA")} <span class="dim" style="font-weight:400">· ${esc(catalog?.telugu_title||"ఋతంభర")}</span></div>
      <div class="sub">${esc(catalog?.runtime||"205 min")} · ${esc((catalog?.languages||[]).join(" · "))} · ${esc(catalog?.aspect_ratio||"2.39:1")}</div>
      <div class="chips">${(catalog?.cast||[]).slice(0,8).map(c=>`<span class="chip">${esc(c.actor)} <span class="dim">as ${esc(c.role)}</span></span>`).join("")}</div>
      <h3>Themes</h3>
      ${(catalog?.music_themes||[]).map(t=>`<div class="shot" style="border-top:0;padding:4px 0"><b>${esc(t.name)}</b> <span class="dim">${esc(t.telugu_name||"")}</span><br/><span class="dim">${esc(t.description||"").slice(0,220)}</span></div>`).join("")}
    </div>`;
  const runCard = `
    <div class="card">
      <div class="title">Latest run</div>
      ${r?`<div class="kv" style="margin-top:8px">
        <span class="k">Status</span><span class="${S.run.status==="completed"?"ok":S.run.status==="failed"?"bad":""}">${esc(S.run.status)}</span>
        <span class="k">Scope</span><span>${esc(r.options?.scope||"sample")}</span>
        <span class="k">Mode</span><span>${esc(r.options?.mode||"hybrid")}</span>
        <span class="k">Elapsed</span><span>${num(r.elapsed_sec,2)}s</span>
        <span class="k">Guardrail</span><span>${guard?num(guard.score,3)+" · "+(guard.allowed?"allowed":"flagged"):"—"}</span>
        <span class="k">Errors</span><span>${(r.errors||[]).length?esc((r.errors||[]).join("; ")):"none"}</span>
      </div>`:'<div class="empty" style="padding:16px">No run yet — press “Run MVP”.</div>'}
      ${r?.artifacts?`<h3>Artifacts</h3><div class="grid g4">${["script","storyboard","characters","voice","animation","lipsync","render","quality"].map(k=>{
        const v=r.artifacts[k]; return `<div class="card" style="text-align:center"><div class="title">${esc(k)}</div><div class="sub">${v?"ready":"missing"}</div></div>`;
      }).join("")}</div>`:""}
    </div>`;
  return `<div class="panel-head"><div><h2>Production overview</h2><p class="hint">The complete MVP: screenplay intelligence → storyboard → characters → voice → animatics → A/V sync → reel → quality gate.</p></div></div>
    <div class="split">${filmCard}${runCard}</div>
    <h3>Screenplay structure</h3>
    ${seqRows||'<div class="empty">Screenplay catalog unavailable.</div>'}`;
}

async function storyboardTab(r){
  const art = r?.artifacts?.storyboard;
  if(!art) return emptyTab("Storyboard", "Run the pipeline to generate keyframes and a contact sheet.");
  const man = await loadJSON(art.manifest);
  const frames = man?.rendered?.length ? man.rendered : (man?.frames||[]);
  const sheet = art.contact_sheet_url ? `<img class="thumb" style="aspect-ratio:auto" src="${esc(art.contact_sheet_url)}" alt="contact sheet"/>` : "";
  return `${head("Storyboard", `${art.frames} frames designed · ${art.rendered} painted · ${esc(man?.renderer?.backend||"procedural")}`)}
    ${sheet?`<div class="card" style="margin-bottom:12px">${sheet}<div class="sub" style="margin-top:8px"><a href="/artifacts/${esc(art.manifest)}">storyboard.json</a> · <a href="/artifacts/${esc(art.sheet_markdown)}">storyboard.md</a></div></div>`:""}
    <div class="grid g3">${(frames||[]).slice(0,60).map((f,i)=>{
      const url = f.url || f.relative ? `/artifacts/${esc(f.relative||"")}` : "";
      return `<div class="card">${url?`<img class="thumb" src="${url}" loading="lazy" alt="frame ${i+1}"/>`:""}
        <div class="title" style="margin-top:8px">${esc(f.number||f.shot_number||"")} · Seq ${esc(f.sequence||f.sequence_num||"")}</div>
        <div class="sub">${esc(f.setting||f.description||"").slice(0,120)}</div>
        <div class="chips"><span class="chip">${esc(f.camera_angle||"")}</span><span class="chip">${num(f.duration_sec,1)}s</span><span class="chip">${esc(f.emotion||"")}</span></div>
      </div>`;
    }).join("")||'<div class="empty">No frames in this run.</div>'}</div>`;
}

async function charactersTab(r){
  const art = r?.artifacts?.characters;
  if(!art) return emptyTab("Characters", "Run the pipeline to build the character bible.");
  const bible = await loadJSON(art.bible_json);
  return `${head("Character bible", `${art.count} roles · ${art.cards} portraits · deterministic face embeddings`)}
    <div class="grid g3">${(bible?.characters||[]).map(c=>`<div class="card">
      ${c.portrait?`<img class="portrait" src="${esc(c.portrait)}" loading="lazy" alt="${esc(c.name)}"/>`:""}
      <div class="title" style="margin-top:8px">${esc(c.name)}</div>
      <div class="sub">${esc(c.actor)} · ${esc(c.function||"").slice(0,80)}</div>
      <div class="chips"><span class="chip">${c.dialogue_lines||0} lines</span><span class="chip">${c.shots_present||0} shots</span>${(c.dominant_emotions||[]).slice(0,2).map(e=>`<span class="chip">${esc(e)}</span>`).join("")}</div>
    </div>`).join("")}</div>
    ${bible?.arc_note?`<h3>Arc analysis</h3><div class="answer">${esc(bible.arc_note)}</div>`:""}
    <p class="hint" style="margin-top:10px"><a href="/artifacts/${esc(art.bible_markdown)}">character_bible.md</a> · <a href="/artifacts/${esc(art.bible_json)}">character_bible.json</a></p>`;
}

async function voiceTab(r){
  const art = r?.artifacts?.voice;
  if(!art) return emptyTab("Voice & subtitles", "Run the pipeline to synthesise dialogue and subtitles.");
  const man = await loadJSON(art.manifest);
  const lines = man?.lines||[];
  return `${head("Voice & subtitles", `${lines.length} lines · ${art.audio_files} audio files · ${esc((art.backends||[]).join(", "))}`)}
    ${art.reel?`<div class="card" style="margin-bottom:12px"><div class="title">Dialogue reel</div><audio controls src="${esc(art.reel)}"></audio></div>`:""}
    <div class="grid g2">${lines.slice(0,40).map(l=>{
      const src = String(l.audio_path||"").startsWith("voice_agent") ? `/artifacts/${esc(l.audio_path)}` : "";
      return `<div class="card">
        <div class="flex between"><div class="title">${esc(l.character)}</div><span class="chip">${esc(l.language)} · ${esc(l.emotion)}</span></div>
        <div class="sub">${esc(l.dialog||l.dialog_english||"").slice(0,220)}</div>
        ${src?`<audio controls preload="none" src="${src}"></audio>`:'<div class="sub dim">planned (media disabled)</div>'}
        <div class="sub mono">${num(l.duration_sec,1)}s</div>
      </div>`;
    }).join("")||'<div class="empty">No dialogue in the sampled shots.</div>'}</div>
    <p class="hint" style="margin-top:10px"><a href="/artifacts/${esc(art.subtitles)}">subtitles.srt</a> · <a href="/artifacts/${esc(art.manifest)}">voice_manifest.json</a></p>`;
}

async function animaticTab(r){
  const art = r?.artifacts?.animation;
  if(!art) return emptyTab("Animatic", "Run the pipeline to build animatic clips.");
  const plan = await loadJSON(art.plan);
  const clips = plan?.clips||[];
  return `${head("Animatic & motion plan", `${art.clips}/${art.shots} clips · engine ${esc(art.engine)} · free-video prompt pack`)}
    <div class="grid g2">${clips.slice(0,20).map(c=>`<div class="card">
      <video controls preload="metadata" src="${esc(c.url)}"></video>
      <div class="title" style="margin-top:8px">Seq ${esc(c.sequence)} · Shot ${esc(c.shot)}</div>
      <div class="sub">${num(c.duration_sec,1)}s · 24 fps</div>
    </div>`).join("")||'<div class="empty">No clips rendered.</div>'}</div>
    <h3>Free-video prompt pack (${(plan?.shots||[]).length})</h3>
    <div class="grid g2">${(plan?.shots||[]).slice(0,8).map(s=>`<div class="card">
      <div class="title">Shot ${esc(s.shot)} · ${esc(s.setting).slice(0,70)}</div>
      <div class="sub mono" style="max-height:110px;overflow:auto">${esc((s.prompt||"").slice(0,420))}</div>
    </div>`).join("")}</div>
    <p class="hint" style="margin-top:10px"><a href="/artifacts/${esc(art.plan)}">animation_plan.json</a> · <a href="/artifacts/${esc(art.prompts)}">video_prompts.json</a></p>`;
}

async function renderTabPanel(r){
  const art = r?.artifacts?.render;
  if(!art) return emptyTab("Render & delivery", "Run the pipeline to assemble an EDL and reel.");
  const man = await loadJSON(art.manifest);
  return `${head("Render & delivery", `${art.shots} shots · ${num(art.record_duration_sec,1)}s timeline · editor ${esc(art.editor)}`)}
    ${art.reel?`<div class="card" style="margin-bottom:12px"><div class="title">Animatic reel</div><video controls src="${esc(art.reel)}"></video></div>`:
      '<div class="empty" style="margin-bottom:12px">Reel not assembled (enable render_video).</div>'}
    <div class="split">
      <div class="card"><div class="title">Deliverables</div>
        <table><thead><tr><th>Name</th><th>Resolution</th><th>Codec</th><th>Status</th></tr></thead><tbody>
        ${(man?.deliverables||[]).map(d=>`<tr><td>${esc(d.name)}</td><td class="mono">${esc(d.resolution)}</td><td class="mono">${esc(d.codec)}</td><td>${esc(d.status)}</td></tr>`).join("")}
        </tbody></table>
      </div>
      <div class="card"><div class="title">Colour & audio</div>
        <div class="kv" style="margin-top:8px">
          <span class="k">Working space</span><span>${esc(man?.colour_pipeline?.working_space||"—")}</span>
          <span class="k">Display</span><span>${esc(man?.colour_pipeline?.display||"—")}</span>
          <span class="k">LUT</span><span class="mono">${esc(man?.colour_pipeline?.lut||"—")}</span>
          <span class="k">Loudness</span><span>${esc(man?.audio?.loudness_target||"—")}</span>
          <span class="k">Stems</span><span>${esc((man?.audio?.stems||[]).join(", "))}</span>
        </div>
      </div>
    </div>
    <h3>Edit decision list</h3>
    <table><thead><tr><th>#</th><th>Shot</th><th>In</th><th>Out</th><th>Duration</th><th>Source</th></tr></thead><tbody>
      ${(man?.edl||[]).slice(0,40).map((e,i)=>`<tr><td>${i+1}</td><td>${esc(e.shot||e.event||"")}</td><td class="mono">${esc(e.record_in||"")}</td><td class="mono">${esc(e.record_out||"")}</td><td class="mono">${num(e.duration_sec,1)}s</td><td class="mono">${esc(e.source||"")}</td></tr>`).join("")}
    </tbody></table>
    <p class="hint" style="margin-top:10px"><a href="/artifacts/${esc(art.edl)}">edl.csv</a> · <a href="/artifacts/${esc(art.manifest)}">render_manifest.json</a></p>`;
}

async function qualityTab(r){
  const q = r?.quality;
  if(!q) return emptyTab("Quality gate", "Run the pipeline to evaluate production quality.");
  const report = await loadJSON(q.report);
  const rows = report?.reports||[];
  const dims = ["storyboard","voice","animation","lip_sync","emotion_fidelity","music_theme_accuracy","scene_coherence","character_consistency"];
  return `${head("Quality gate", `Decision ${esc(String(q.decision).toUpperCase())} · mean ${num(q.mean_score,3)} · threshold ${num(q.threshold,2)} · ${q.repair_loops} repair loops`)}
    <div class="grid g4" style="margin-bottom:12px">
      ${[["Mean",num(q.mean_score,3),q.passed?"good":"bad"],["Pass rate",pct(q.pass_rate),q.pass_rate>=.8?"good":"warn"],["Frames",q.artifacts?.storyboard_frames??0,""],["Clips",q.artifacts?.animatic_clips??0,""],["Lines",q.artifacts?.voice_lines??0,""],["Mode",q.artifacts?.mode||"media",""]].map(([l,v,c])=>`<div class="kpi"><div class="label">${l}</div><div class="value ${c}" style="font-size:20px">${esc(v)}</div></div>`).join("")}
    </div>
    <div style="overflow:auto"><table><thead><tr><th>Seq</th><th>Overall</th>${dims.map(d=>`<th>${esc(d.replace(/_/g," "))}</th>`).join("")}<th>Pass</th></tr></thead><tbody>
      ${rows.map(rep=>`<tr><td>${rep.sequence_num}</td><td class="score ${scoreClass(rep.overall_score)}">${num(rep.overall_score,3)}</td>${dims.map(d=>`<td class="mono">${num(rep.rubric?.[d],3)}</td>`).join("")}<td>${rep.passed?"✅":"⚠️"}</td></tr>`).join("")}
    </tbody></table></div>
    ${rows.some(x=>x.issues?.length)?`<h3>Issues & repairs</h3><div class="grid g2">${rows.filter(x=>x.issues?.length).map(rep=>`<div class="card"><div class="title">Seq ${rep.sequence_num}</div>${(rep.issues||[]).map(i=>`<div class="sub">⚠ ${esc(i)}</div>`).join("")}${(rep.repair_actions||[]).map(a=>`<div class="sub dim">↳ ${esc(a)}</div>`).join("")}</div>`).join("")}</div>`:""}
    <p class="hint" style="margin-top:10px"><a href="/artifacts/${esc(q.markdown||"")}">quality_report.md</a> · <a href="/artifacts/${esc(q.report)}">quality_report.json</a></p>`;
}

function evalsTab(r){
  const ev = r?.evaluation;
  const summary = S.snap?.evals||{};
  const scores = ev?.scores||{};
  return `${head("Evaluations & MLOps", `${summary.total||0} recorded evaluations · mean ${num(summary.mean_overall,3)} · fine-tuning export ready`)}
    ${ev?`<div class="grid g3">${Object.entries(scores).map(([k,v])=>`<div class="kpi"><div class="label">${esc(k.replace(/_/g," "))}</div><div class="value ${scoreClass(v)}" style="font-size:22px">${num(v,3)}</div><div class="sub">weight ${num(ev.weights?.[k],2)}</div></div>`).join("")}</div>
    <div class="card" style="margin-top:12px"><div class="title">Overall ${num(ev.overall,3)} · ${ev.passed?"PASSED":"REVIEW"}</div><div class="sub mono">${esc(ev.eval_id||"")}</div></div>`:'<div class="empty">No evaluation for the latest run.</div>'}
    <h3>Rubric</h3><div class="grid g2">${Object.entries(ev?.rubric||{}).map(([k,v])=>`<div class="card"><div class="title">${esc(k.replace(/_/g," "))}</div><div class="sub">${esc(v)}</div></div>`).join("")}</div>
    <div class="flex" style="margin-top:14px"><button class="btn" id="exportBtn">⤓ Export LoRA/QLoRA dataset</button><span class="hint" id="exportOut"></span></div>`;
}

async function opsTab(r){
  const providers = S.snap?.providers||[];
  const metrics = S.snap?.metrics||{};
  const logs = S.snap?.logs||[];
  const audit = S.snap?.audit||[];
  const mcp = S.snap?.mcp||{};
  let tools = [];
  try{ tools = (await api("/api/mcp/tools")).tools||[]; }catch(e){}
  const spans = S.run?.spans||[];
  return `${head("Operations & governance", `${tools.length} MCP tools · ${providers.length} providers · guardrails, audit trail and approvals`)}
    <div class="split">
      <div class="card"><div class="title">Providers</div>
        <table><thead><tr><th>Name</th><th>Kind</th><th>Tier</th><th>Available</th></tr></thead><tbody>
        ${providers.map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(p.kind)}</td><td>${esc(p.tier)}</td><td>${p.available?'<span class="ok">yes</span>':'<span class="dim">no</span>'}</td></tr>`).join("")}
        </tbody></table>
      </div>
      <div class="card"><div class="title">Metrics</div>
        <div class="kv" style="margin-top:8px">
          <span class="k">Counters</span><span>${Object.keys(metrics.counters||{}).length}</span>
          <span class="k">Gauges</span><span>${Object.keys(metrics.gauges||{}).length}</span>
          <span class="k">Histograms</span><span>${Object.keys(metrics.histograms||{}).length}</span>
          <span class="k">MCP calls</span><span>${mcp.calls||0} (${mcp.errors||0} errors)</span>
          <span class="k">Prometheus</span><span><a href="/metrics">/metrics</a></span>
        </div>
        <h3>Recent gauges</h3>
        ${Object.entries(metrics.gauges||{}).slice(0,6).map(([k,v])=>`<div class="sub mono">${esc(k)} = ${esc(v)}</div>`).join("")||'<div class="sub dim">No metrics yet.</div>'}
      </div>
    </div>
    <h3>MCP tools</h3>
    <div class="grid g2">${tools.map(t=>`<div class="card"><div class="title mono">${esc(t.name)}</div><div class="sub">${esc(t.description)}</div></div>`).join("")||'<div class="empty">No tools registered.</div>'}</div>
    <div class="split" style="margin-top:14px">
      <div class="card"><div class="title">Audit trail</div>
        ${audit.slice(0,10).map(a=>`<div class="sub mono">${esc((a.timestamp||"").split("T")[1]||"")} ${esc(a.action)} · ${esc(a.resource)} · ${esc(a.outcome)}</div>`).join("")||'<div class="sub dim">No audit entries.</div>'}
      </div>
      <div class="card"><div class="title">Approvals</div>
        ${(S.snap?.approvals||[]).slice(0,6).map(a=>`<div class="sub">${esc(a.id)} · <span class="${a.status==="pending"?"warnc":a.status==="approved"?"ok":"bad"}">${esc(a.status)}</span></div>`).join("")||'<div class="sub dim">No approvals pending.</div>'}
      </div>
    </div>
    <h3>Traces (${spans.length})</h3>
    <div class="log">${spans.map(s=>`${esc(s.name)} · ${num(s.duration_ms,1)}ms · ${esc(s.status)}`).join("\n")||"No spans recorded for this run."}</div>
    <h3>Server log</h3>
    <div class="log">${logs.slice(0,20).map(l=>`<div>[${esc((l.timestamp||"").split("T")[1]||"")}] ${esc(l.message)} ${esc(JSON.stringify(l.context||{})).slice(0,200)}</div>`).join("")||"No log entries."}</div>`;
}

function head(title, subtitle){
  return `<div class="panel-head"><div><h2>${esc(title)}</h2><p class="hint">${esc(subtitle)}</p></div></div>`;
}
function emptyTab(title, message){
  return `${head(title,"")}<div class="empty">${esc(message)}</div>`;
}

function renderRagBadge(){
  const rag = S.snap?.rag||{};
  $("#ragBadge").textContent = `${rag.chunks||0} chunks · ${rag.faiss?"FAISS":"numpy"} · ${rag.embedding_backend||"hash"}`;
  if(S.snap?.graph?.nodes?.length) $("#ragBadge").title = `${S.snap.graph.nodes.length} graph nodes`;
}

async function startRun(){
  if(S.busy || S.run?.status==="running") return;
  S.busy = true; S.events=[]; renderPipeline();
  try{
    const resp = await api("/api/runs",{method:"POST",body:"{}"});
    S.run = resp.run; S.events=[]; S.cache={};
    renderAll(); attachStream(S.run.id);
  }catch(err){
    alert("Could not start run: "+err.message);
  }finally{
    S.busy = false;
  }
}

function attachStream(runId){
  if(S.stream) S.stream.close();
  if(S.poll) clearInterval(S.poll);
  const src = new EventSource(`/api/runs/${runId}/events`);
  S.stream = src;
  src.onmessage = (msg)=>{
    let ev; try{ ev = JSON.parse(msg.data); }catch(e){ return; }
    S.events.push(ev);
    if(ev.type==="run.stage"){
      S.run = {...(S.run||{}), progress:ev.data?.progress, stage:ev.data?.stage, status:"running"};
      renderPipeline();
    }
    renderEvents();
    if(ev.type==="run.closed"){
      src.close(); if(S.poll) clearInterval(S.poll);
      refreshRun(runId);
    }
  };
  src.onerror = ()=>{ /* browser retries automatically */ };
  S.poll = setInterval(()=>refreshRun(runId, false), 1600);
}

async function refreshRun(runId, final=true){
  try{
    const run = await api(`/api/runs/${runId}`);
    S.run = run;
    if(run.status !== "running"){
      if(S.stream){S.stream.close();S.stream=null;}
      if(S.poll){clearInterval(S.poll);S.poll=null;}
      const snap = await api("/api/dashboard");
      S.snap = snap;
    }
    renderAll();
  }catch(e){ if(final) console.warn(e); }
}

async function ask(question){
  $("#askAnswer").innerHTML = '<div class="answer">Thinking…</div>';
  $("#ragHits").innerHTML = "";
  try{
    const res = await api("/api/ask",{method:"POST",body:JSON.stringify({question,k:6})});
    $("#askAnswer").innerHTML = `<div class="answer">${esc(res.answer||"(no answer)")}</div>`;
    $("#ragHits").innerHTML = `<h3>Citations (${(res.citations||[]).length})</h3>`+
      (res.citations||[]).map((c,i)=>`<div class="hit"><div class="kind">[${i+1}] ${esc(c.kind)} · score ${num(c.score,3)}</div><div class="txt">${esc((c.text||"").slice(0,420))}</div></div>`).join("");
  }catch(err){
    $("#askAnswer").innerHTML = `<div class="answer bad">${esc(err.message)}</div>`;
  }
}

// ── events ────────────────────────────────────────────────────────────────
$("#runBtn").onclick = startRun;
$("#refreshBtn").onclick = async ()=>{ S.cache={}; await boot(); };
$("#askForm").onsubmit = (e)=>{ e.preventDefault(); const q=$("#askInput").value.trim(); if(q) ask(q); };
document.addEventListener("click",(e)=>{
  if(e.target && e.target.id==="exportBtn"){
    api("/api/evals/export",{method:"POST",body:"{}"}).then(r=>{
      $("#exportOut").textContent = `exported ${r.pairs} pairs → ${r.path}`;
    }).catch(err=>{ $("#exportOut").textContent = err.message; });
  }
});
boot();
setInterval(()=>{ if(!S.busy && (S.run?.status==="running"||!S.run)) refreshRun(S.run?.id, false); }, 5000);
</script>
</body>
</html>
"""


def dashboard_html() -> str:
    """Return the dashboard document (static; data is fetched from the API).

    The template is intentionally *not* run through :meth:`str.format` because
    the page is full of CSS/JS braces.  Anything dynamic is fetched at runtime
    from ``/api/dashboard`` instead.
    """
    return DASHBOARD_HTML
