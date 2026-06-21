from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HYBRID = "hybrid"


@dataclass
class CastMember:
    role: str
    actor: str
    function: str


@dataclass
class MusicTheme:
    name: str
    telugu_name: str
    description: str
    instruments: str
    inspiration: str
    usage_rule: str


@dataclass
class MusicCue:
    sequence_num: int
    entry_time: str
    duration: str
    theme: str
    instruments: str
    scene_description: str


@dataclass
class Shot:
    number: str
    setting: str
    duration_sec: float
    lens: str
    camera_movement: str
    visual_description: str
    dialog: list[dict[str, str]]
    sound: str
    language: str
    emotion_context: str = "contemplative_neutral"
    composition_notes: str = ""
    color_palette: str = ""
    music_cue: str = ""


@dataclass
class Sequence:
    number: int
    telugu_name: str
    english_name: str
    runtime_minutes: float
    shots: list[Shot] = field(default_factory=list)
    language: str = "te"


@dataclass
class Act:
    number: int
    english_subtitle: str
    telugu_subtitle: str
    start_time: str
    end_time: str
    sequences: list[Sequence] = field(default_factory=list)


@dataclass
class FilmScript:
    title: str
    telugu_title: str
    runtime_str: str
    runtime_minutes: float
    languages: list[str]
    aspect_ratio: str
    acts: list[Act] = field(default_factory=list)
    cast: list[CastMember] = field(default_factory=list)
    music_themes: list[MusicTheme] = field(default_factory=list)
    music_cues: list[MusicCue] = field(default_factory=list)


@dataclass
class ScriptOutput:
    film: FilmScript
    total_acts: int
    total_sequences: int
    language: str


@dataclass
class StoryboardFrame:
    sequence_num: int
    shot_number: str
    frame_number: int
    description: str
    camera_angle: str
    lens: str
    composition_notes: str
    duration_sec: float


@dataclass
class StoryboardOutput:
    frames: list[StoryboardFrame]
    total_shots: int


@dataclass
class CharacterProfile:
    name: str
    actor: str
    function: str
    voice_id: str
    face_embedding_path: str
    emotion_palette: dict[str, str]
    languages: list[str]


@dataclass
class CharacterOutput:
    characters: list[CharacterProfile]


@dataclass
class VoiceLine:
    character: str
    actor: str
    dialog: str
    dialog_english: str
    emotion: str
    language: str
    shot_number: str
    sequence_num: int
    audio_path: str
    duration_sec: float


@dataclass
class VoiceOutput:
    lines: list[VoiceLine]
    total_lines: int


@dataclass
class AnimationOutput:
    sequence_num: int
    shot_number: str
    video_path: str
    frame_count: int
    fps: int
    duration_sec: float


@dataclass
class LipSyncOutput:
    sequence_num: int
    shot_number: str
    video_path: str
    sync_accuracy: float


@dataclass
class RenderOutput:
    sequence_num: int
    shot_number: str
    final_path: str
    resolution: str
    bitrate_mbps: int


@dataclass
class QualityReport:
    sequence_num: int
    consistency_score: float
    lip_sync_accuracy: float
    emotion_fidelity: float
    scene_coherence: float
    music_theme_accuracy: float
    passed: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class PipelineContext:
    pipeline_id: str
    mode: PipelineMode
    source_script_path: str
    language: str
    total_duration_minutes: float
    film: Optional[FilmScript] = None
    current_act_index: int = 0
    current_sequence_index: int = 0
    results: dict[str, object] = field(default_factory=dict)
    quality_reports: list[QualityReport] = field(default_factory=list)
    model_selections: dict[str, str] = field(default_factory=dict)
    tier: str = "free"


@dataclass
class AgentResult:
    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    output: Optional[object] = None
    error: Optional[str] = None
    duration_sec: float = 0.0
