import pytest
from pathlib import Path
from src.models.schemas import PipelineContext, PipelineMode
from src.supervisor import AgentSupervisor
from src.readers.ruthambhara_reader import RuthambharaReader

SCRIPT_PATH = "D:\\WorkSpace\\Telugu_Film_Stroy_Board\\feature\\ఋతంభర_పూర్తి_సినిమా_స్క్రిప్ట్.md"


@pytest.fixture
def ctx():
    assert Path(SCRIPT_PATH).exists(), f"Script not found at {SCRIPT_PATH}"
    return PipelineContext(
        pipeline_id="test_ruthambhara",
        mode=PipelineMode.SEQUENTIAL,
        source_script_path=SCRIPT_PATH,
        language="te",
        total_duration_minutes=205.0,
    )


@pytest.fixture
def film():
    reader = RuthambharaReader()
    return reader.read(SCRIPT_PATH)


def test_reader_parses_header(film):
    assert film.title == "RUTHAMBHARA"
    assert film.telugu_title == "ఋతంభర"
    assert film.runtime_minutes == 205.0
    assert len(film.languages) >= 1
    assert "te" in film.languages


def test_reader_parses_cast(film):
    assert len(film.cast) > 0
    names = [m.actor for m in film.cast]
    assert "Prabhas" in names or any("Prabhas" in m.actor for m in film.cast)


def test_reader_parses_music_themes(film):
    assert len(film.music_themes) >= 3
    theme_names = [t.name for t in film.music_themes]
    assert any("RAKTHA" in t.name.upper() or "RAGAM" in t.name.upper() for t in film.music_themes)


def test_reader_parses_acts(film):
    assert len(film.acts) >= 6, f"Expected 6 acts, got {len(film.acts)}"
    total_seq = sum(len(a.sequences) for a in film.acts)
    assert total_seq >= 30, f"Expected 30+ sequences, got {total_seq}"


def test_reader_parses_shots(film):
    total_shots = sum(len(s.shots) for a in film.acts for s in a.sequences)
    assert total_shots > 0, "No shots parsed"
    for act in film.acts:
        for seq in act.sequences:
            for shot in seq.shots:
                assert shot.number, f"Shot missing number in seq {seq.number}"
                assert shot.duration_sec > 0


def test_sequential_pipeline(ctx):
    supervisor = AgentSupervisor()
    results = supervisor.run(ctx)
    assert len(results) == 8
    assert all(r.status.value == "completed" for r in results)


def test_hybrid_pipeline(ctx):
    ctx.mode = PipelineMode.HYBRID
    supervisor = AgentSupervisor()
    results = supervisor.run(ctx)
    assert len(results) == 8


def test_script_agent_extracts_film(ctx):
    supervisor = AgentSupervisor()
    supervisor.run(ctx)
    result = ctx.results.get("script_agent")
    assert result is not None
    output = result.output
    assert output.film.title == "RUTHAMBHARA"
    assert len(output.film.acts) >= 6


def test_quality_agent_reports(ctx):
    supervisor = AgentSupervisor()
    supervisor.run(ctx)
    assert len(ctx.quality_reports) > 0


def test_storyboard_generates_frames(ctx):
    supervisor = AgentSupervisor()
    supervisor.run(ctx)
    result = ctx.results.get("storyboard_agent")
    assert result is not None
    output = result.output
    assert output.total_shots > 0


def test_model_registry_returns_categories():
    from src.models.model_registry import registry
    data = registry.to_dict()
    assert "categories" in data
    assert "llm" in data["categories"]
    assert "tts" in data["categories"]
    assert "image" in data["categories"]
    assert "video" in data["categories"]
    assert "voice_clone" in data["categories"]
    assert "lipsync" in data["categories"]


def test_model_registry_default_models():
    from src.models.model_registry import registry
    default_llm = registry.get_default_model_id("llm")
    assert default_llm, "No default LLM model configured"
    model = registry.get_model(default_llm)
    assert model is not None
    assert model.cost == "free"


def test_agent_uses_selected_model(ctx):
    from src.models.model_registry import registry
    ctx.model_selections = {"llm": "ollama_qwen"}
    supervisor = AgentSupervisor()
    supervisor.run(ctx)
    result = ctx.results.get("script_agent")
    assert result is not None
    assert result.status.value == "completed"


def test_agent_uses_premium_model_selection(ctx):
    ctx.model_selections = {"image": "openai_dalle3"}
    ctx.tier = "premium"
    supervisor = AgentSupervisor()
    supervisor.run(ctx)
    result = ctx.results.get("storyboard_agent")
    assert result is not None
    assert result.status.value == "completed"
