import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import axios from "axios";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8081";

interface Shot {
  number: string; setting: string; duration_sec: number;
  lens: string; camera_movement: string; visual_description: string;
  dialog: { character: string; line: string }[];
  sound: string; emotion_context: string; video_url: string | null;
}

interface Sequence {
  number: number; english_name: string; telugu_name: string;
  runtime_minutes: number; shots: Shot[]; total_shots: number;
}

interface Act {
  number: number; english_subtitle: string; telugu_subtitle: string;
  start_time: string; end_time: string;
  sequences: Sequence[]; total_sequences: number; total_shots: number;
}

interface ScriptData {
  title: string; telugu_title: string; runtime: string;
  runtime_minutes: number; languages: string[];
  total_acts: number; total_sequences: number; total_shots: number;
  acts: Act[];
}

const ROMAN = "I II III IV V VI VII VIII IX X XI XII".split(" ");
const roman = (n: number) => ROMAN[n - 1] || n;

const ACT_PALETTE = [
  { name: "amber", hex: "#F59E0B", bg: "rgba(245,158,11,0.08)", edge: "rgba(245,158,11,0.15)" },
  { name: "blue", hex: "#3B82F6", bg: "rgba(59,130,246,0.08)", edge: "rgba(59,130,246,0.15)" },
  { name: "emerald", hex: "#10B981", bg: "rgba(16,185,129,0.08)", edge: "rgba(16,185,129,0.15)" },
  { name: "purple", hex: "#A855F7", bg: "rgba(168,85,247,0.08)", edge: "rgba(168,85,247,0.15)" },
  { name: "rose", hex: "#F43F5E", bg: "rgba(244,63,94,0.08)", edge: "rgba(244,63,94,0.15)" },
  { name: "cyan", hex: "#06B6D4", bg: "rgba(6,182,212,0.08)", edge: "rgba(6,182,212,0.15)" },
];

const EMOJI: Record<string, string> = {
  contemplative_neutral: "🧘", intense: "⚡", emotional: "💔", joyful: "🎉",
  suspense: "😰", peaceful: "🌅", dramatic: "🎭", romantic: "💕", action: "💥", mysterious: "🔮",
};

// ─── Utility Components ──────────────────────────────────────────

function cls(...a: (string | false | undefined | null)[]) { return a.filter(Boolean).join(" "); }

function AnimatedCounter({ value, suffix = "", prefix = "", decimals = 0 }: {
  value: number; suffix?: string; prefix?: string; decimals?: number;
}) {
  const [display, setDisplay] = useState(0);
  const ref = useRef<number>(0);
  useEffect(() => {
    const start = ref.current;
    const dur = 800;
    const step = Math.max(1, Math.abs(value - start) / 30);
    let cur = start;
    const t = setInterval(() => {
      cur += step * (value > start ? 1 : -1);
      if ((value > start && cur >= value) || (value < start && cur <= value)) {
        cur = value; clearInterval(t);
      }
      setDisplay(Math.round(cur));
    }, dur / Math.abs(value - start + 1) * 15);
    ref.current = value;
    return () => clearInterval(t);
  }, [value]);
  return <>{prefix}{display.toFixed(decimals)}{suffix}</>;
}

function ProgressRing({ pct, size = 44, stroke = 4, color = "#00D4AA" }: {
  pct: number; size?: number; stroke?: number; color?: string;
}) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(100, Math.max(0, pct)) / 100) * circ;
  return (
    <svg width={size} height={size} className="ring-progress">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke}
        strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset}
        style={{ transition: "stroke-dashoffset 1.5s ease-out" }} />
    </svg>
  );
}

function ProgressBar({ value, max, color = "var(--accent)" }: {
  value: number; max: number; color?: string;
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2.5">
      <div className="progress-track flex-1">
        <div className="progress-bar" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}, ${color}dd)` }} />
      </div>
      <span className="text-[10px] text-gray-700 w-9 text-right font-mono">{Math.round(pct)}%</span>
    </div>
  );
}

function MetricCard({ icon, label, value, sub, accent, children, ring }: {
  icon?: string; label: string; value?: string | number; sub?: string;
  accent?: boolean; children?: React.ReactNode; ring?: { value: number; color?: string };
}) {
  return (
    <div className="glass-card group animate-fade-in">
      <div className="flex items-start gap-4">
        {icon && (
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#00D4AA]/15 to-[#0066FF]/5 flex items-center justify-center text-lg shrink-0 group-hover:scale-110 transition-all duration-500 group-hover:rotate-[-5deg]">
            {icon}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="metric-label">{label}</div>
          <div className={cls("mt-0.5", accent ? "metric-value-accent" : "metric-value")}>
            {value}
          </div>
          {sub && <div className="text-[11px] text-gray-600 mt-1.5">{sub}</div>}
          {children}
        </div>
        {ring && (
          <div className="shrink-0 mt-1">
            <ProgressRing pct={ring.value} color={ring.color || "#00D4AA"} size={44} />
          </div>
        )}
      </div>
    </div>
  );
}

function HeatMap({ acts }: { acts: Act[] }) {
  const maxShots = Math.max(...acts.map(a => a.total_shots), 1);
  return (
    <div className="flex gap-1.5">
      {acts.map((act, i) => {
        const p = act.total_shots / maxShots;
        const c = ACT_PALETTE[i % ACT_PALETTE.length];
        const v = act.sequences.reduce((a, s) => a + s.shots.filter(sh => sh.video_url).length, 0);
        const pct = act.total_shots > 0 ? Math.round(v / act.total_shots * 100) : 0;
        return (
          <div key={act.number} className="flex-1 flex flex-col items-center gap-1.5 group cursor-pointer">
            <div className="relative w-full flex flex-col items-center gap-0.5 h-24 justify-end">
              {Array.from({ length: 8 }).map((_, j) => (
                <div key={j} className="w-full rounded-sm transition-all duration-300 group-hover:scale-x-105"
                  style={{
                    height: `${100 / 8}%`,
                    background: j < Math.ceil(pct / (100 / 8))
                      ? `linear-gradient(180deg, ${c.hex}88, ${c.hex}33)`
                      : "rgba(255,255,255,0.03)",
                    border: `1px solid ${j < Math.ceil(pct / (100 / 8)) ? c.edge : "transparent"}`,
                  }} />
              ))}
            </div>
            <span className="text-[10px] font-mono text-gray-700 group-hover:text-gray-400 transition">{roman(act.number)}</span>
            <span className="text-[8px] text-gray-700">{pct}%</span>
          </div>
        );
      })}
    </div>
  );
}

function ActDistChart({ acts }: { acts: Act[] }) {
  const total = acts.reduce((a, ac) => a + ac.total_shots, 0) || 1;
  return (
    <div className="space-y-2.5">
      {acts.map((act, i) => {
        const c = ACT_PALETTE[i % ACT_PALETTE.length];
        const pct = (act.total_shots / total) * 100;
        const v = act.sequences.reduce((a, s) => a + s.shots.filter(sh => sh.video_url).length, 0);
        return (
          <div key={act.number} className="flex items-center gap-3 group cursor-default">
            <span className="text-[11px] font-mono text-gray-600 w-6 shrink-0 group-hover:text-gray-400 transition">
              {roman(act.number)}
            </span>
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-400 truncate group-hover:text-gray-200 transition">{act.english_subtitle}</span>
                <span className="text-[10px] text-gray-600 font-mono">{act.total_shots} shots</span>
              </div>
              <div className="h-2.5 bg-[#0A0A14] rounded-full overflow-hidden flex">
                <div className="h-full rounded-full transition-all duration-1000"
                  style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${c.hex}, ${c.hex}88)` }} />
              </div>
              <div className="flex justify-between mt-0.5">
                <span className="text-[9px] text-gray-700">{v} with video</span>
                <span className="text-[9px] text-gray-700">{Math.round(pct)}%</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Video Player ──────────────────────────────────────────

function VideoPlayer({ videoUrl, onClose, shots, currentIndex, onNavigate }: {
  videoUrl: string; onClose: () => void;
  shots: Shot[]; currentIndex: number; onNavigate: (i: number) => void;
}) {
  const vr = useRef<HTMLVideoElement>(null);
  const s = shots[currentIndex];
  return (
    <div className="fixed inset-0 z-50 bg-[#07070D]/98 flex items-center justify-center p-4 md:p-8" onClick={onClose}>
      <div className="max-w-5xl w-full max-h-full" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#00D4AA]/20 to-[#0066FF]/10 flex items-center justify-center shrink-0">
              <span className="text-emerald-400 text-sm">▶</span>
            </div>
            <div className="min-w-0">
              <div className="text-sm text-white font-medium truncate">{s?.setting || "Shot"}</div>
              <p className="text-[10px] text-gray-600">Shot {s?.number} · {s?.duration_sec}s · {s?.emotion_context}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {shots.length > 1 && (
              <>
                <button onClick={() => { onNavigate(currentIndex - 1); vr.current?.load(); }}
                  disabled={currentIndex <= 0}
                  className="px-3 py-1.5 text-xs bg-[#12121E]/80 border border-[#1E1E30] rounded-xl hover:border-[#00D4AA]/30 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 hover:text-[#00D4AA] transition">
                  ←
                </button>
                <span className="text-xs text-gray-700 font-mono">{currentIndex + 1}/{shots.length}</span>
                <button onClick={() => { onNavigate(currentIndex + 1); vr.current?.load(); }}
                  disabled={currentIndex >= shots.length - 1}
                  className="px-3 py-1.5 text-xs bg-[#12121E]/80 border border-[#1E1E30] rounded-xl hover:border-[#00D4AA]/30 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 hover:text-[#00D4AA] transition">
                  →
                </button>
              </>
            )}
            <button onClick={onClose} className="w-8 h-8 rounded-xl bg-[#12121E]/80 border border-[#1E1E30] flex items-center justify-center text-gray-600 hover:text-white hover:border-red-500/30 transition ml-2 text-sm">
              ✕
            </button>
          </div>
        </div>
        <div className="relative bg-black rounded-2xl overflow-hidden shadow-2xl border border-[#1E1E30]/60">
          <video ref={vr} controls autoPlay className="w-full max-h-[65vh]" src={videoUrl} />
          {s?.visual_description && (
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent p-5 pt-12">
              <p className="text-sm text-gray-200 leading-relaxed">{s.visual_description}</p>
            </div>
          )}
        </div>
        {s?.dialog && s.dialog.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {s.dialog.map((d, i) => (
              <span key={i} className="text-xs bg-[#00D4AA]/10 text-[#00D4AA]/80 px-3 py-1.5 rounded-lg border border-[#00D4AA]/15">
                <strong>{d.character}:</strong> "{d.line}"
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Shot Row ──────────────────────────────────────────

function ShotRow({ shot, onPlay, actNum }: { shot: Shot; onPlay: (url: string) => void; actNum: number }) {
  const [open, setOpen] = useState(false);
  const p = ACT_PALETTE[(actNum - 1) % ACT_PALETTE.length];
  const id = shot.number.split(".")[1] || shot.number;
  return (
    <div className={cls(
      "rounded-xl border transition-all duration-300",
      open ? "border-[#00D4AA]/15 bg-gradient-to-r from-[#00D4AA]/[0.02] to-transparent" : "border-[#1E1E30] hover:border-[#2A2A3E]"
    )}>
      <button onClick={() => setOpen(!open)} className="w-full text-left p-3 flex items-center gap-3">
        <div className={cls(
          "w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-mono shrink-0 border transition",
          shot.video_url
            ? "bg-emerald-900/20 text-emerald-400 border-emerald-800/30"
            : "bg-[#0A0A14] text-gray-700 border-[#1E1E30]"
        )}>{id.padStart(2, "0")}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs">{EMOJI[shot.emotion_context] || "🎬"}</span>
            <span className="text-sm font-medium text-gray-200 truncate">{shot.setting}</span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] text-gray-700 bg-[#0A0A14] px-2 py-0.5 rounded-md">{shot.lens}</span>
            <span className="text-[10px] text-gray-700 bg-[#0A0A14] px-2 py-0.5 rounded-md">{shot.camera_movement}</span>
            <span className="text-[10px] text-gray-700 bg-[#0A0A14] px-2 py-0.5 rounded-md">{shot.duration_sec}s</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {shot.video_url ? (
            <button onClick={e => { e.stopPropagation(); onPlay(shot.video_url!); }}
              className="flex items-center gap-1 px-2.5 py-1.5 text-[10px] bg-emerald-900/25 hover:bg-emerald-800/35 text-emerald-300 rounded-lg border border-emerald-800/30 transition whitespace-nowrap">
              ▶ Play
            </button>
          ) : (
            <span className="text-[10px] text-gray-700 bg-[#0A0A14] px-2 py-1.5 rounded-lg">No video</span>
          )}
          <span className={cls("text-gray-700 text-xs transition-transform duration-200", open && "rotate-180")}>▼</span>
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 animate-slide-down border-t border-[#1E1E30] pt-3 mt-0">
          {shot.visual_description && <p className="text-sm text-gray-500 leading-relaxed">{shot.visual_description}</p>}
          {shot.dialog?.length > 0 && (
            <div className="space-y-1 bg-[#0A0A14] rounded-xl p-3 border border-[#1E1E30]">
              {shot.dialog.map((d, i) => (
                <p key={i} className="text-sm text-gray-400"><span className="font-semibold text-[#00D4AA]">{d.character}:</span> "{d.line}"</p>
              ))}
            </div>
          )}
          <div className="flex gap-2 text-[10px] text-gray-700">
            <span>Sound: {shot.sound || "Ambient"}</span>
            <span>· Emotion: {shot.emotion_context}</span>
            {shot.video_url && <span>· <span className="text-emerald-500">Video ready</span></span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sequence Panel ──────────────────────────────────────────

function SeqPanel({ seq, actNum, onPlay, open }: { seq: Sequence; actNum: number; onPlay: (url: string) => void; open: boolean }) {
  const [isOpen, setIsOpen] = useState(open);
  const hv = seq.shots.some(s => s.video_url);
  const vc = seq.shots.filter(s => s.video_url).length;
  return (
    <div className="rounded-xl bg-[#0A0A14]/40 border border-[#1E1E30]/60 overflow-hidden">
      <button onClick={() => setIsOpen(!isOpen)}
        className="w-full text-left p-3.5 flex items-center justify-between hover:bg-white/[0.01] transition">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#00D4AA]/15 to-[#0066FF]/5 flex items-center justify-center">
            <span className="text-[#00D4AA] text-xs font-bold">{String(seq.number).padStart(2, "0")}</span>
          </div>
          <div>
            <div className="text-sm font-medium text-gray-100">{seq.english_name}</div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] text-gray-700">⏱ {seq.runtime_minutes}m</span>
              <span className="text-gray-800">·</span>
              <span className="text-[10px] text-gray-700">{seq.total_shots} shots</span>
              {hv && <><span className="text-gray-800">·</span><span className="text-[10px] text-emerald-500">▶ {vc}</span></>}
            </div>
          </div>
        </div>
        <span className={cls("text-gray-700 text-xs transition-transform", isOpen && "rotate-180")}>▼</span>
      </button>
      {isOpen && (
        <div className="px-3.5 pb-3.5 space-y-1.5 animate-slide-down border-t border-[#1E1E30]/50 pt-3">
          {seq.shots.map(sh => <ShotRow key={sh.number} shot={sh} onPlay={onPlay} actNum={actNum} />)}
        </div>
      )}
    </div>
  );
}

// ─── Act Section ──────────────────────────────────────────

function ActSection({ act, index, expanded, onToggle, onPlay }: {
  act: Act; index: number; expanded: boolean; onToggle: () => void; onPlay: (url: string) => void;
}) {
  const p = ACT_PALETTE[index % ACT_PALETTE.length];
  const vc = act.sequences.reduce((a, s) => a + s.shots.filter(sh => sh.video_url).length, 0);
  return (
    <div className={cls(
      "rounded-2xl border overflow-hidden transition-all duration-500 animate-scale-in",
      expanded ? "border-l-[3px]" : "border-[#1E1E30]/80",
      p.name
    )} style={expanded ? { borderLeftColor: p.hex } : {}}>
      <button onClick={onToggle} className="w-full text-left p-5 flex items-center justify-between gap-4 transition hover:bg-white/[0.01]">
        <div className="flex items-center gap-4 min-w-0">
          <div className={cls(
            "w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 transition-all duration-500",
            expanded ? "scale-110" : "scale-100"
          )} style={{ background: expanded ? `${p.bg}` : "rgba(255,255,255,0.02)" }}>
            <span className="text-xl font-bold" style={{ color: expanded ? p.hex : "gray" }}>{roman(act.number)}</span>
          </div>
          <div className="min-w-0">
            <div className={cls("text-lg font-display transition", expanded ? "text-white" : "text-gray-500")}>
              Act {roman(act.number)} — "{act.english_subtitle}"
            </div>
            <div className="flex items-center gap-2 mt-1 text-sm text-gray-700 flex-wrap">
              <span>{act.telugu_subtitle}</span>
              <span>·</span>
              <span>{act.start_time}—{act.end_time}</span>
              <span>·</span>
              <span>{act.total_sequences} seq</span>
              <span>·</span>
              <span>{act.total_shots} shots</span>
              {vc > 0 && <><span>·</span><span className="text-emerald-500">▶ {vc}</span></>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <div className="hidden md:block w-28"><ProgressBar value={vc} max={act.total_shots} color={p.hex} /></div>
          <div className={cls("w-8 h-8 rounded-xl flex items-center justify-center transition-all duration-500", expanded ? "rotate-180" : "")}
            style={{ background: "rgba(255,255,255,0.03)" }}>
            <span className="text-gray-600 text-sm">▼</span>
          </div>
        </div>
      </button>
      {expanded && (
        <div className="px-5 pb-5 space-y-2.5 animate-slide-down border-t border-[#1E1E30]/40 pt-4">
          {act.sequences.map(s => <SeqPanel key={s.number} seq={s} actNum={act.number} onPlay={onPlay} open={false} />)}
        </div>
      )}
    </div>
  );
}

// ─── Cast Card ──────────────────────────────────────────

function CastCard({ m, i }: { m: any; i: number }) {
  const init = m.actor.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase();
  const g = ["from-amber-500/40","from-blue-500/40","from-emerald-500/40","from-purple-500/40","from-rose-500/40","from-cyan-500/40"];
  return (
    <div className="glass-card flex items-start gap-4 animate-fade-in group cursor-default" style={{ animationDelay: `${i * 50}ms` }}>
      <div className={cls(
        "w-14 h-14 rounded-2xl bg-gradient-to-br flex items-center justify-center shrink-0",
        "font-bold text-base tracking-wide transition-all duration-500 group-hover:scale-110 group-hover:rotate-[-5deg]",
        g[i % g.length], "to-[#0A0A14] text-white"
      )}>{init}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-100 text-base">{m.role}</span>
          <span className="text-[10px] text-gray-600 bg-[#0A0A14] px-2 py-0.5 rounded-md">{m.actor}</span>
        </div>
        <p className="text-sm text-gray-500 mt-1.5 leading-relaxed">{m.function}</p>
      </div>
    </div>
  );
}

// ─── Tab Definitions ──────────────────────────────────────────

const TABS = [
  { id: "dashboard", label: "Dashboard", icon: "◉", desc: "Overview" },
  { id: "scenes", label: "Scenes", icon: "◆", desc: "Breakdown" },
  { id: "gallery", label: "Gallery", icon: "▣", desc: "Shots" },
  { id: "pipeline", label: "Pipeline", icon: "▶", desc: "Engine" },
  { id: "story", label: "Script", icon: "○", desc: "Story" },
  { id: "cast", label: "Cast", icon: "△", desc: "Talent" },
  { id: "models", label: "Models", icon: "◇", desc: "Config" },
];

// ─── Animated Background ──────────────────────────────────────────

function BgParticles() {
  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="absolute animate-float"
          style={{
            left: `${15 + i * 15}%`,
            top: `${20 + (i % 3) * 30}%`,
            width: `${200 + i * 100}px`,
            height: `${200 + i * 100}px`,
            background: `radial-gradient(circle, rgba(0,212,170,${0.015 + i * 0.002}) 0%, transparent 70%)`,
            borderRadius: "50%",
            animationDelay: `${i * 1.5}s`,
            animationDuration: `${6 + i * 2}s`,
          }} />
      ))}
    </div>
  );
}

// ─── Pipeline Flow ──────────────────────────────────────────

const AGENTS = [
  { id: "script", label: "Script", icon: "📝" },
  { id: "storyboard", label: "Storyboard", icon: "🎨" },
  { id: "character", label: "Character", icon: "👤" },
  { id: "voice", label: "Voice", icon: "🎤" },
  { id: "animation", label: "Animation", icon: "🎞️" },
  { id: "lipsync", label: "LipSync", icon: "👄" },
  { id: "render", label: "Render", icon: "💻" },
  { id: "quality", label: "Quality", icon: "✅" },
];

function PipelineFlow({ result }: { result: any }) {
  const statuses = result?.agents?.reduce((a: any, ag: any) => ({ ...a, [ag.name.toLowerCase()]: ag.status }), {}) || {};
  return (
    <div className="flex items-center gap-1 md:gap-2 justify-center flex-wrap">
      {AGENTS.map((a, i) => {
        const st = statuses[a.id] || "pending";
        return (
          <div key={a.id} className="flex items-center">
            <div className={cls(
              "pipeline-node text-sm",
              st === "completed" ? "completed" : st === "running" ? "running" : "pending"
            )}>
              <span>{a.icon}</span>
            </div>
            {i < AGENTS.length - 1 && (
              <div className="w-3 md:w-6 h-px mx-0.5"
                style={{ background: `linear-gradient(90deg, ${st === "completed" ? "#00D4AA" : "#1E1E30"}, #1E1E30)` }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Main Dashboard ──────────────────────────────────────────

export default function Dashboard() {
  const [script, setScript] = useState<any>(null);
  const [scenes, setScenes] = useState<ScriptData | null>(null);
  const [models, setModels] = useState<any>(null);
  const [enhanced, setEnhanced] = useState("");
  const [sel, setSel] = useState<Record<string, string>>({});
  const [tier, setTier] = useState("free");
  const [mode, setMode] = useState("hybrid");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [tab, setTab] = useState("dashboard");
  const [expandedActs, setExpandedActs] = useState<number[]>([1]);
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [playing, setPlaying] = useState<string | null>(null);
  const [playlist, setPlaylist] = useState<Shot[]>([]);
  const [playIdx, setPlayIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [time, setTime] = useState("");

  useEffect(() => {
    const t = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(t);
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, sc, m] = await Promise.all([
        axios.get(`${API}/script`).catch(() => null),
        axios.get(`${API}/scenes`).catch(() => null),
        axios.get(`${API}/models`).catch(() => null),
      ]);
      if (s?.data) setScript(s.data);
      if (sc?.data) setScenes(sc.data);
      if (m?.data) setModels(m.data);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  const runPipeline = async () => {
    setRunning(true);
    setResult(null);
    try {
      const r = await axios.post(`${API}/pipeline/run`, { mode, tier, model_selections: sel });
      setResult(r.data);
      setTimeout(fetchAll, 2000);
    } catch (e: any) { setResult({ status: "error", message: e.message }); }
    setRunning(false);
  };

  const loadEnhanced = async () => {
    try { const r = await axios.get(`${API}/script/enhanced`); setEnhanced(r.data.story); setTab("story"); } catch {}
  };

  const playVideo = useCallback((url: string, shots?: Shot[], idx?: number) => {
    setPlaying(url); if (shots) { setPlaylist(shots); setPlayIdx(idx || 0); }
  }, []);

  const allShots = useMemo(() => {
    if (!scenes) return [];
    return scenes.acts.flatMap(a => a.sequences.flatMap(s => s.shots.map(sh => ({ ...sh, actNum: a.number, seqNum: s.number }))));
  }, [scenes]);

  const filteredShots = useMemo(() => {
    if (!search) return allShots;
    const q = search.toLowerCase();
    return allShots.filter(s =>
      s.setting.toLowerCase().includes(q) || s.number.includes(q) || s.lens.toLowerCase().includes(q) ||
      s.camera_movement.toLowerCase().includes(q) || s.visual_description.toLowerCase().includes(q) ||
      s.emotion_context.toLowerCase().includes(q) ||
      s.dialog.some(d => d.character.toLowerCase().includes(q) || d.line.toLowerCase().includes(q))
    );
  }, [allShots, search]);

  const videoShots = useMemo(() => allShots.filter(s => s.video_url), [allShots]);
  const vc = videoShots.length;
  const ts = scenes?.total_shots || 0;
  const tq = scenes?.total_sequences || 0;
  const overallPct = ts > 0 ? Math.round(vc / ts * 100) : 0;

  return (
    <div className="min-h-screen relative">
      <BgParticles />
      {playing && (
        <VideoPlayer videoUrl={playing} onClose={() => { setPlaying(null); setPlaylist([]); }}
          shots={playlist.length > 0 ? playlist : videoShots}
          currentIndex={playlist.length > 0 ? playIdx : videoShots.findIndex(s => s.video_url === playing)}
          onNavigate={i => { setPlayIdx(i); const p = playlist.length > 0 ? playlist : videoShots; if (p[i]?.video_url) setPlaying(p[i].video_url!); }} />
      )}

      <div className="relative z-10 max-w-7xl mx-auto px-4 md:px-6 py-6">

        {/* ─── Header ─── */}
        <header className="mb-8 animate-fade-in">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[#00D4AA]/20 to-[#0066FF]/10 flex items-center justify-center text-xl border border-[#00D4AA]/10">
                🎬
              </div>
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-3xl md:text-4xl font-display text-white tracking-tight">ఋతంభర</h1>
                  <span className="px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.15em] bg-[#00D4AA]/10 text-[#00D4AA] border border-[#00D4AA]/20 rounded-full">v2.0</span>
                  <span className="live-dot animate-pulse-ring" />
                </div>
                <p className="text-sm text-gray-600 mt-0.5">RUTHAMBHARA — Agentic Film Pipeline</p>
              </div>
            </div>
            <div className="hidden md:flex items-center gap-4 text-[11px] text-gray-700">
              <span>⏱ 3h 25m</span>
              <span className="w-px h-4 bg-[#1E1E30]" />
              <span>{tq} Sequences</span>
              <span className="w-px h-4 bg-[#1E1E30]" />
              <span>{ts} Shots</span>
              <span className="w-px h-4 bg-[#1E1E30]" />
              <span className="font-mono">{time}</span>
            </div>
          </div>
        </header>

        {/* ─── Nav ─── */}
        <nav className="flex items-center justify-center gap-1 mb-8 p-1.5 bg-[#0C0C18]/80 backdrop-blur-xl rounded-2xl border border-[#1E1E30]/60 w-fit mx-auto flex-wrap">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={cls(tab === t.id ? "nav-tab-active" : "nav-tab")}>
              <span className="mr-1.5 text-xs">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </nav>

        {/* ─── Loading ─── */}
        {loading && (
          <div className="flex items-center justify-center py-24">
            <div className="text-center">
              <div className="w-10 h-10 border-2 border-[#00D4AA]/30 border-t-[#00D4AA] rounded-full animate-spin mx-auto mb-4" />
              <p className="text-sm text-gray-600 font-mono">Loading film data<span className="animate-breathe">...</span></p>
            </div>
          </div>
        )}

        {!loading && (
          <>
            {/* ═══════ DASHBOARD ═══════ */}
            {tab === "dashboard" && (
              <div className="space-y-6 animate-fade-in">
                {/* Metric Grid */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                  <MetricCard icon="📜" label="Acts" value={<AnimatedCounter value={scenes?.total_acts || 0} />} sub="6-act structure" ring={{ value: 100 }} />
                  <MetricCard icon="📋" label="Sequences" value={<AnimatedCounter value={tq} />} sub="Across all acts" ring={{ value: (tq / 40) * 100, color: "#3B82F6" }} />
                  <MetricCard icon="🎯" label="Total Shots" value={<AnimatedCounter value={ts} />} sub="Planned" ring={{ value: 100 }} />
                  <MetricCard icon="🎬" label="With Video" value={<AnimatedCounter value={vc} />} sub={`${overallPct}% complete`} accent ring={{ value: overallPct, color: "#00D4AA" }} />
                  <MetricCard icon="🌐" label="Languages" value={scenes?.languages?.length || 0} sub="Pan-India" />
                  <MetricCard icon="🎭" label="Cast" value={script?.cast?.length || 0} sub="Star talent" />
                </div>

                {/* Progress + Charts */}
                {scenes && (
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Act Progress */}
                    <div className="glass-card lg:col-span-1">
                      <div className="flex items-center justify-between mb-5">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500/20 to-emerald-500/5 flex items-center justify-center text-sm">📈</div>
                          <div>
                            <h3 className="text-sm text-white font-medium">Render Progress</h3>
                            <p className="text-[10px] text-gray-600">{vc}/{ts} shots complete</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-lg font-bold text-[#00D4AA]"><AnimatedCounter value={overallPct} /></span>
                          <span className="text-[10px] text-gray-600">%</span>
                        </div>
                      </div>
                      <div className="space-y-3">
                        {scenes.acts.map((act, i) => {
                          const p = ACT_PALETTE[i % ACT_PALETTE.length];
                          const v = act.sequences.reduce((a, s) => a + s.shots.filter(sh => sh.video_url).length, 0);
                          return (
                            <div key={act.number} className="flex items-center gap-3 group">
                              <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" style={{ background: p.bg }}>
                                <span className="text-[10px] font-bold" style={{ color: p.hex }}>{roman(act.number)}</span>
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex justify-between text-[10px] mb-0.5">
                                  <span className="text-gray-500 truncate group-hover:text-gray-300 transition">{act.english_subtitle}</span>
                                  <span className="text-gray-700 font-mono">{v}/{act.total_shots}</span>
                                </div>
                                <ProgressBar value={v} max={act.total_shots} color={p.hex} />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Act Distribution */}
                    <div className="glass-card lg:col-span-1">
                      <div className="flex items-center gap-3 mb-5">
                        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500/20 to-blue-500/5 flex items-center justify-center text-sm">📊</div>
                        <div>
                          <h3 className="text-sm text-white font-medium">Shot Distribution</h3>
                          <p className="text-[10px] text-gray-600">By act</p>
                        </div>
                      </div>
                      <ActDistChart acts={scenes.acts} />
                    </div>

                    {/* Heatmap / Ring */}
                    <div className="glass-card lg:col-span-1">
                      <div className="flex items-center gap-3 mb-5">
                        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-purple-500/20 to-purple-500/5 flex items-center justify-center text-sm">🔥</div>
                        <div>
                          <h3 className="text-sm text-white font-medium">Heatmap</h3>
                          <p className="text-[10px] text-gray-600">Completion density</p>
                        </div>
                      </div>
                      <div className="flex items-center justify-center py-4">
                        <div className="relative">
                          <ProgressRing pct={overallPct} size={120} stroke={8} color="#00D4AA" />
                          <div className="absolute inset-0 flex items-center justify-center flex-col">
                            <span className="text-2xl font-bold text-white"><AnimatedCounter value={overallPct} /></span>
                            <span className="text-[9px] text-gray-700 uppercase tracking-wider">Complete</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-3">
                        <HeatMap acts={scenes.acts} />
                      </div>
                    </div>
                  </div>
                )}

                {/* Quick Stats */}
                {scenes && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="glass-card p-4 text-center">
                      <div className="metric-label">Total Runtime</div>
                      <div className="metric-value-accent text-lg mt-1">3h 25m</div>
                      <div className="text-[10px] text-gray-700 mt-1">205 minutes</div>
                    </div>
                    <div className="glass-card p-4 text-center">
                      <div className="metric-label">Avg Shot Duration</div>
                      <div className="metric-value-accent text-lg mt-1">{ts > 0 ? Math.round((205 * 60) / ts) : "—"}s</div>
                      <div className="text-[10px] text-gray-700 mt-1">Across all shots</div>
                    </div>
                    <div className="glass-card p-4 text-center">
                      <div className="metric-label">Sequences / Act</div>
                      <div className="metric-value-accent text-lg mt-1">{scenes.acts.length > 0 ? Math.round(tq / scenes.acts.length) : "—"}</div>
                      <div className="text-[10px] text-gray-700 mt-1">Average</div>
                    </div>
                    <div className="glass-card p-4 text-center">
                      <div className="metric-label">Shots / Sequence</div>
                      <div className="metric-value-accent text-lg mt-1">{tq > 0 ? Math.round(ts / tq) : "—"}</div>
                      <div className="text-[10px] text-gray-700 mt-1">Average</div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ═══════ SCENES ═══════ */}
            {tab === "scenes" && scenes && (
              <div className="space-y-4 animate-fade-in">
                <div className="flex items-center gap-3 mb-2 flex-wrap">
                  <div className="relative flex-1 max-w-xs">
                    <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-700 text-xs">🔍</span>
                    <input type="text" placeholder="Search shots, dialog, settings..." value={search}
                      onChange={e => setSearch(e.target.value)} className="input-field w-full pl-9 text-xs" />
                  </div>
                  <div className="flex gap-1 bg-[#0C0C18] rounded-xl p-1 border border-[#1E1E30]">
                    <button onClick={() => setViewMode("list")}
                      className={cls("px-3 py-1.5 text-xs rounded-lg transition", viewMode === "list" ? "bg-[#00D4AA]/15 text-[#00D4AA]" : "text-gray-600 hover:text-gray-400")}>📋 List</button>
                    <button onClick={() => setViewMode("grid")}
                      className={cls("px-3 py-1.5 text-xs rounded-lg transition", viewMode === "grid" ? "bg-[#00D4AA]/15 text-[#00D4AA]" : "text-gray-600 hover:text-gray-400")}>🖼️ Grid</button>
                  </div>
                  <span className="text-[10px] text-gray-700 font-mono">{vc}▶ {ts} total</span>
                </div>

                {search && (
                  <div className="glass-card">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-sm text-white font-medium">Search: "{search}"</span>
                      <span className="text-[10px] text-gray-600">{filteredShots.length} results</span>
                    </div>
                    {filteredShots.length === 0 ? (
                      <p className="text-sm text-gray-600 text-center py-6">No matches.</p>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-72 overflow-y-auto scrollbar-thin">
                        {filteredShots.slice(0, 40).map((s, i) => (
                          <div key={i} className="flex items-center gap-2 p-2.5 bg-[#0A0A14] rounded-xl border border-[#1E1E30]">
                            <span className="text-[9px] text-[#00D4AA]/50 font-mono shrink-0">S{s.seqNum}.{s.number}</span>
                            <span className="text-xs text-gray-500 truncate flex-1">{s.setting}</span>
                            {s.video_url ? <button onClick={() => playVideo(s.video_url!)}
                              className="text-[9px] px-2 py-1 bg-emerald-900/25 text-emerald-400 rounded-lg border border-emerald-800/30 hover:bg-emerald-800/35 transition">▶</button> : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {scenes.acts.map((act, i) => (
                  <ActSection key={act.number} act={act} index={i}
                    expanded={expandedActs.includes(act.number)}
                    onToggle={() => setExpandedActs(p => p.includes(act.number) ? p.filter(a => a !== act.number) : [...p, act.number])}
                    onPlay={url => playVideo(url)} />
                ))}
              </div>
            )}

            {/* ═══════ GALLERY ═══════ */}
            {tab === "gallery" && scenes && (
              <div className="animate-fade-in">
                <div className="flex items-center justify-between mb-5">
                  <div className="flex items-center gap-3">
                    <h2 className="text-xl text-white font-display">Shot Gallery</h2>
                    <span className="text-[10px] text-gray-600 bg-[#12121E] px-2.5 py-1 rounded-lg font-mono">{videoShots.length}▶ {allShots.length} total</span>
                  </div>
                  <input type="text" placeholder="Filter..." value={search} onChange={e => setSearch(e.target.value)} className="input-field w-36 text-xs" />
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                  {filteredShots.map((shot, i) => {
                    const p = ACT_PALETTE[(shot.actNum - 1) % ACT_PALETTE.length];
                    return (
                      <div key={i} className={cls(
                        "glass-card p-3 animate-fade-in cursor-pointer group",
                        shot.video_url ? "hover:border-emerald-700/40" : "opacity-40"
                      )} style={{ animationDelay: `${(i % 20) * 30}ms` }}
                        onClick={() => shot.video_url && playVideo(shot.video_url!)}>
                        <div className={cls(
                          "aspect-video rounded-xl mb-2.5 flex items-center justify-center relative overflow-hidden",
                          "bg-gradient-to-br from-[#0A0A14] to-[#12121E]"
                        )}>
                          {shot.video_url ? (
                            <>
                              <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center backdrop-blur-sm">
                                <div className="w-12 h-12 rounded-full bg-[#00D4AA]/90 flex items-center justify-center shadow-lg transform group-hover:scale-110 transition-transform">
                                  <span className="text-[#07070D] text-xl ml-0.5">▶</span>
                                </div>
                              </div>
                              <div className="w-full h-full rounded-xl opacity-10" style={{ background: p.hex }} />
                              <span className="text-2xl relative z-10">🎬</span>
                            </>
                          ) : (
                            <span className="text-xl opacity-30">🎥</span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 mb-1">
                          <div className="w-1.5 h-1.5 rounded-full" style={{ background: p.hex }} />
                          <span className="text-[9px] font-mono text-[#00D4AA]/50">S{shot.seqNum}.{shot.number}</span>
                        </div>
                        <p className="text-[11px] text-gray-400 truncate">{shot.setting}</p>
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className="text-[9px] text-gray-700">{shot.duration_sec}s</span>
                          <span className="text-gray-800">·</span>
                          <span className="text-[9px] text-gray-700">{shot.lens}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ═══════ PIPELINE ═══════ */}
            {tab === "pipeline" && (
              <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 animate-fade-in">
                <div className="lg:col-span-2 space-y-4">
                  <div className="glass-card">
                    <div className="flex items-center gap-3 mb-5">
                      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#00D4AA]/20 to-[#0066FF]/10 flex items-center justify-center text-sm">⚙️</div>
                      <div>
                        <h3 className="text-sm text-white font-medium">Pipeline Config</h3>
                        <p className="text-[10px] text-gray-600">Configure execution engine</p>
                      </div>
                    </div>
                    <div className="space-y-4">
                      <div>
                        <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1.5">Execution Mode</label>
                        <select value={mode} onChange={e => setMode(e.target.value)} className="input-field w-full text-xs">
                          <option value="sequential">Sequential — one agent at a time</option>
                          <option value="parallel">Parallel — all agents at once</option>
                          <option value="hybrid">Hybrid — parallel where possible</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-gray-600 uppercase tracking-wider block mb-1.5">Model Tier</label>
                        <div className="flex gap-2">
                          <button onClick={() => setTier("free")}
                            className={cls("flex-1 px-4 py-2.5 rounded-xl text-xs font-medium border transition-all", tier === "free"
                              ? "bg-emerald-900/25 text-emerald-300 border-emerald-800/40 shadow-sm shadow-emerald-900/20" : "bg-[#0A0A14] text-gray-700 border-[#1E1E30] hover:border-gray-600")}>
                            🆓 Free
                          </button>
                          <button onClick={() => setTier("premium")}
                            className={cls("flex-1 px-4 py-2.5 rounded-xl text-xs font-medium border transition-all", tier === "premium"
                              ? "bg-purple-900/25 text-purple-300 border-purple-800/40 shadow-sm shadow-purple-900/20" : "bg-[#0A0A14] text-gray-700 border-[#1E1E30] hover:border-gray-600")}>
                            ⭐ Premium
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>

                  <button onClick={runPipeline} disabled={running}
                    className={cls("w-full py-3.5 rounded-xl font-semibold text-sm transition-all", tier === "premium" ? "btn-premium" : "btn-primary",
                      running && "opacity-60 cursor-not-allowed")}>
                    {running ? (
                      <span className="flex items-center justify-center gap-2.5">
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Executing Pipeline...
                      </span>
                    ) : <span>▶ Execute Pipeline</span>}
                  </button>

                  <div className="glass-card">
                    <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-4">Agent Pipeline</div>
                    <PipelineFlow result={result} />
                  </div>
                </div>

                <div className="lg:col-span-3">
                  {result && (
                    <div className="glass-card animate-scale-in h-full">
                      <div className="flex items-center gap-3 mb-5">
                        <div className={cls("w-8 h-8 rounded-xl flex items-center justify-center text-sm",
                          result.status === "error" ? "bg-red-500/20 text-red-400" : "bg-emerald-500/20 text-emerald-400")}>
                          {result.status === "error" ? "✕" : "✓"}
                        </div>
                        <div>
                          <h3 className="text-sm text-white font-medium">Pipeline Result</h3>
                          <p className="text-[10px] text-gray-600">Execution complete</p>
                        </div>
                      </div>
                      {result.status === "error" ? (
                        <div className="text-sm text-red-400 p-4 bg-red-900/10 rounded-xl border border-red-900/30">{result.message}</div>
                      ) : (
                        <div className="space-y-5">
                          <div className="grid grid-cols-4 gap-3">
                            {[
                              { l: "Mode", v: result.mode, c: "text-[#00D4AA]" },
                              { l: "Duration", v: `${result.total_time_sec}s`, c: "text-emerald-400" },
                              { l: "Quality", v: `${result.quality?.passed}/${result.quality?.total}`, c: "text-white" },
                              { l: "Shots", v: result.film?.shots || 0, c: "text-white" },
                            ].map((d, i) => (
                              <div key={i} className="text-center p-3 bg-[#0A0A14] rounded-xl border border-[#1E1E30]">
                                <div className="text-[9px] text-gray-700 uppercase tracking-wider">{d.l}</div>
                                <div className={cls("text-base font-bold mt-1", d.c)}>{d.v}</div>
                              </div>
                            ))}
                          </div>
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead><tr className="text-gray-700 border-b border-[#1E1E30]">
                                <th className="text-left p-2.5 text-[10px] font-medium uppercase tracking-wider">Agent</th>
                                <th className="text-left p-2.5 text-[10px] font-medium uppercase tracking-wider">Status</th>
                                <th className="text-right p-2.5 text-[10px] font-medium uppercase tracking-wider">Time</th>
                              </tr></thead>
                              <tbody>
                                {result.agents?.map((a: any) => (
                                  <tr key={a.name} className="border-b border-[#1E1E30]/40 hover:bg-white/[0.01] transition">
                                    <td className="p-2.5 text-sm text-gray-300">{a.name}</td>
                                    <td className="p-2.5">
                                      <span className={cls("inline-flex items-center gap-1.5 text-[10px] px-2.5 py-1 rounded-lg",
                                        a.status === "completed" ? "bg-emerald-900/20 text-emerald-300 border border-emerald-800/30"
                                        : "bg-red-900/20 text-red-300 border border-red-800/30")}>
                                        <span className={cls("w-1.5 h-1.5 rounded-full", a.status === "completed" ? "bg-emerald-400 animate-pulse-ring" : "bg-red-400")} />
                                        {a.status}
                                      </span>
                                    </td>
                                    <td className="p-2.5 text-right text-xs text-gray-600 font-mono">{a.duration_sec}s</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {!result && !running && (
                    <div className="glass-card flex items-center justify-center h-full min-h-[350px]">
                      <div className="text-center">
                        <div className="text-4xl mb-4 opacity-30 animate-float">▶</div>
                        <p className="text-sm text-gray-500">Configure & execute the pipeline</p>
                        <div className="flex items-center justify-center gap-2 mt-4">
                          <PipelineFlow result={null} />
                        </div>
                      </div>
                    </div>
                  )}
                  {running && !result && (
                    <div className="glass-card flex items-center justify-center h-full min-h-[350px]">
                      <div className="text-center">
                        <div className="w-14 h-14 border-2 border-[#00D4AA]/30 border-t-[#00D4AA] rounded-full animate-spin mx-auto mb-4" />
                        <p className="text-sm text-gray-400 font-medium mb-3">Pipeline executing...</p>
                        <PipelineFlow result={{ agents: AGENTS.map(a => ({ name: a.id, status: "running" })) }} />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ═══════ SCRIPT ═══════ */}
            {tab === "story" && (
              <div className="animate-fade-in">
                <div className="flex items-center gap-3 mb-5">
                  <button onClick={loadEnhanced} className="btn-primary text-sm">
                    ✨ Generate Enhanced Script
                  </button>
                  {scenes && <span className="text-[10px] text-gray-600 bg-[#12121E] px-3 py-1.5 rounded-lg font-mono">{ts} shots · {scenes.total_acts} acts · {tq} sequences</span>}
                </div>
                {enhanced ? (
                  <div className="glass-card overflow-auto max-h-[72vh] scrollbar-thin card-glow">
                    <pre className="text-sm leading-relaxed whitespace-pre-wrap font-sans text-gray-400">{enhanced}</pre>
                  </div>
                ) : (
                  <div className="glass-card text-center py-20">
                    <div className="text-5xl mb-4 opacity-30 animate-float">○</div>
                    <p className="text-gray-500 text-sm">Click "Generate" for the human-enhanced script</p>
                    <p className="text-gray-700 text-xs mt-2">Includes emotions, camera movements, visual descriptions</p>
                  </div>
                )}
              </div>
            )}

            {/* ═══════ CAST ═══════ */}
            {tab === "cast" && script?.cast && (
              <div className="animate-fade-in">
                <div className="glass-card mb-5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#00D4AA]/20 to-[#0066FF]/10 flex items-center justify-center text-lg">△</div>
                      <div>
                        <h3 className="text-lg text-white font-display">Pan-India Cast</h3>
                        <p className="text-sm text-gray-600">{script.cast.length} members · {scenes?.languages?.length || 5} languages</p>
                      </div>
                    </div>
                    <div className="flex -space-x-2">
                      {script.cast.slice(0, 6).map((c: any, i: number) => (
                        <div key={i} className="w-9 h-9 rounded-full bg-gradient-to-br from-[#00D4AA]/40 to-[#0066FF]/40 border-2 border-[#0C0C18] flex items-center justify-center text-[8px] font-bold text-white transition hover:z-10 hover:scale-110 cursor-default">
                          {c.actor.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase()}
                        </div>
                      ))}
                      {script.cast.length > 6 && (
                        <div className="w-9 h-9 rounded-full bg-[#12121E] border-2 border-[#0C0C18] flex items-center justify-center text-[8px] font-bold text-gray-600">
                          +{script.cast.length - 6}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {script.cast.map((c: any, i: number) => <CastCard key={i} m={c} i={i} />)}
                </div>
              </div>
            )}

            {/* ═══════ MODELS ═══════ */}
            {tab === "models" && models && (
              <div className="animate-fade-in">
                <div className="flex gap-2 mb-6 bg-[#0C0C18] p-1.5 rounded-2xl border border-[#1E1E30]/60 w-fit">
                  <button onClick={() => setTier("free")}
                    className={cls("px-5 py-2.5 rounded-xl text-sm font-semibold transition", tier === "free"
                      ? "bg-emerald-900/25 text-emerald-300 shadow-sm" : "text-gray-700 hover:text-gray-400")}>
                    🆓 Free Tier
                  </button>
                  <button onClick={() => setTier("premium")}
                    className={cls("px-5 py-2.5 rounded-xl text-sm font-semibold transition", tier === "premium"
                      ? "bg-purple-900/25 text-purple-300 shadow-sm" : "text-gray-700 hover:text-gray-400")}>
                    ⭐ Premium Tier
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {Object.entries(models.categories || {}).map(([catId, cat]: [string, any]) => (
                    <div key={catId} className="glass-card">
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-sm text-white font-medium">{cat.label}</h3>
                        <span className="text-[9px] text-gray-700 bg-[#0A0A14] px-2 py-0.5 rounded-md font-mono">{catId}</span>
                      </div>
                      <div className="space-y-1.5">
                        {(tier === "free" ? cat.free : [...cat.free, ...cat.premium]).map((m: any) => (
                          <label key={m.id} className={cls(
                            "flex items-center gap-3 p-2.5 rounded-xl border transition cursor-pointer",
                            sel[catId] === m.id ? "bg-[#00D4AA]/10 border-[#00D4AA]/30" : "border-transparent hover:bg-white/[0.02]"
                          )}>
                            <div className={cls("w-4 h-4 rounded-full border-2 flex items-center justify-center transition",
                              sel[catId] === m.id ? "border-[#00D4AA]" : "border-gray-700")}>
                              {sel[catId] === m.id && <div className="w-2 h-2 rounded-full bg-[#00D4AA]" />}
                            </div>
                            <input type="radio" name={catId} checked={sel[catId] === m.id}
                              onChange={() => setSel(s => ({ ...s, [catId]: m.id }))} className="hidden" />
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-gray-200">{m.name}</div>
                              <div className="flex items-center gap-2 mt-1">
                                <span className={m.cost === "free" ? "tag-free" : "tag-premium"}>{m.cost}</span>
                                <span className="text-[9px] text-gray-700">{m.quality}</span>
                              </div>
                            </div>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}