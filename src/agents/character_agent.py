"""Character agent: character bible, portraits and consistency embeddings.

The bible is derived from real screenplay data (dialogue count, emotion range,
music themes, scene presence).  Portraits are painted locally with Pillow and a
deterministic 128-d identity embedding is stored for continuity checks.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from src.agents.base import BaseAgent
from src.core.text import slugify
from src.models.schemas import (
    AgentResult,
    CharacterOutput,
    CharacterProfile,
    PipelineContext,
)

_STOPWORDS = {"the", "young", "old", "age", "a", "an", "of", "and"}


def _normalise(role: str) -> str:
    name = role.split("(")[0].strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t and t not in _STOPWORDS}


class CharacterAgent(BaseAgent):
    def __init__(self):
        super().__init__("character_agent")

    # ── alias resolution ─────────────────────────────────────────────────
    @classmethod
    def resolve_character(cls, spoken: str, names: list[str]) -> str | None:
        spoken_norm = _normalise(spoken).upper()
        for name in names:
            if name.upper() == spoken_norm:
                return name
        spoken_tokens = _tokens(spoken_norm)
        if not spoken_tokens:
            return None
        best, best_score = None, 0.0
        for name in names:
            name_tokens = _tokens(name)
            if not name_tokens:
                continue
            overlap = len(spoken_tokens & name_tokens) / len(spoken_tokens | name_tokens)
            if spoken_tokens <= name_tokens or name_tokens <= spoken_tokens:
                overlap += 0.35
            if overlap > best_score:
                best, best_score = name, overlap
        return best if best_score >= 0.5 else None

    def process(self, ctx: PipelineContext) -> AgentResult:
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=CharacterOutput(characters=[]))

        names = [_normalise(member.role) for member in ctx.film.cast]
        name_to_member = dict(zip(names, ctx.film.cast))
        spoken_lines: Counter[str] = Counter()
        spoken_emotions: dict[str, Counter[str]] = {name: Counter() for name in names}
        shot_presence: Counter[str] = Counter()

        for act, seq, shot in self.all_shots(ctx):
            for dialog in shot.dialog:
                spoken = dialog.get("character", "")
                resolved = self.resolve_character(spoken, names)
                if not resolved:
                    continue
                spoken_lines[resolved] += 1
                spoken_emotions[resolved][shot.emotion_context] += 1
                shot_presence[resolved] += 1

        run_dir = self.run_dir(ctx)
        brand = slugify(ctx.film.title)
        profiles: list[CharacterProfile] = []
        cards: list[dict] = []
        embedding_dim = int(getattr(self.studio().providers.embeddings, "hash").dim)

        for name, member in zip(names, ctx.film.cast):
            emotions = spoken_emotions.get(name) or Counter({"contemplative_neutral": 1})
            dominant = [emotion for emotion, _ in emotions.most_common(3)]
            palette = {
                emotion: f"{brand}/{slugify(name)}_{emotion}.png"
                for emotion in dict.fromkeys(dominant + ["neutral", "anger", "sadness", "joy", "fear"])
            }
            face_rel = f"character_agent/{run_dir}/faces/{slugify(name)}.json"
            embedding = self.studio().providers.embeddings.embed(
                f"{name}. {member.actor}. {member.function}. "
                f"Emotions: {', '.join(dominant)}"
            )
            self.studio().artifacts.save_json(face_rel, {
                "character": name,
                "actor": member.actor,
                "dimension": len(embedding),
                "embedding": [round(v, 6) for v in embedding[:embedding_dim]],
                "dominant_emotions": dominant,
                "dialogue_lines": spoken_lines.get(name, 0),
            })

            profile = CharacterProfile(
                name=name,
                actor=member.actor,
                function=member.function,
                voice_id=f"voice_{slugify(name)}",
                face_embedding_path=face_rel,
                emotion_palette=palette,
                languages=ctx.film.languages,
            )
            profiles.append(profile)

            if ctx.media_enabled:
                card_rel = f"character_agent/{run_dir}/cards/{slugify(name)}.png"
                try:
                    result = self.studio().providers.image.procedural.render_character_card(
                        {
                            "name": name,
                            "actor": member.actor,
                            "function": member.function,
                            "lines": spoken_lines.get(name, 0),
                            "emotions": ", ".join(e.replace("_", " ") for e in dominant),
                        },
                        self.studio().artifacts.path(card_rel),
                    )
                    cards.append({
                        **result,
                        "relative": card_rel,
                        "url": self.artifact_url(card_rel),
                        "character": name,
                    })
                    self.emit(ctx, "character.card", {"character": name, "url": self.artifact_url(card_rel)})
                except Exception as exc:  # pragma: no cover
                    self.logger.warning(f"portrait failed for {name}: {exc}")

        bible = [
            {
                "name": profile.name,
                "actor": profile.actor,
                "function": profile.function,
                "dialogue_lines": spoken_lines.get(profile.name, 0),
                "shots_present": shot_presence.get(profile.name, 0),
                "dominant_emotions": list((spoken_emotions.get(profile.name) or {}).keys())[:4],
                "voice_id": profile.voice_id,
                "face_embedding": profile.face_embedding_path,
                "portrait": next(
                    (c["url"] for c in cards if c["character"] == profile.name), None
                ),
            }
            for profile in profiles
        ]

        cast_analysis_prompt = (
            "TASK: character arc analysis. For this feature film cast, describe the "
            "central relationships in 4 bullet points. "
            + "; ".join(
                f"{b['name']} ({b['actor']}): {b['function']}, {b['dialogue_lines']} lines"
                for b in bible[:8]
            )
        )
        arc_note = self.llm(cast_analysis_prompt, system="You are a casting director.", max_tokens=320)

        ctx.artifacts["characters"] = {
            "count": len(profiles),
            "cards": len(cards),
            "bible_json": f"character_agent/{run_dir}/character_bible.json",
            "bible_markdown": f"character_agent/{run_dir}/character_bible.md",
            "portraits": [c["url"] for c in cards],
        }
        self.save_json(ctx, "character_bible.json", {
            "film": ctx.film.title,
            "characters": bible,
            "arc_note": arc_note,
        })
        self.save_text(ctx, "character_bible.md", self._markdown(ctx, bible, cards, arc_note))

        self.remember(
            f"Character bible for {ctx.film.title}: {len(profiles)} roles, "
            f"top speakers {', '.join(f'{n} ({c})' for n, c in spoken_lines.most_common(4))}.",
            key=f"characters:{run_dir}",
            tags=["characters", "casting"],
            metadata={"characters": len(profiles)},
        )

        return AgentResult(agent_name=self.name, output=CharacterOutput(characters=profiles))

    @staticmethod
    def _markdown(ctx: PipelineContext, bible: list[dict], cards: list[dict], note: str) -> str:
        lines = [f"# {ctx.film.title} — Character Bible", ""]
        lines += [f"**Roles:** {len(bible)} · **Portraits:** {len(cards)}", ""]
        if note:
            lines += ["## Arc analysis", "", note, ""]
        lines += [
            "| Character | Actor | Function | Lines | Shots | Portraits |",
            "|-----------|-------|----------|-------|-------|-----------|",
        ]
        for entry in bible:
            portrait = "✅" if entry["portrait"] else "–"
            lines.append(
                f"| {entry['name']} | {entry['actor']} | {entry['function'][:44]} | "
                f"{entry['dialogue_lines']} | {entry['shots_present']} | {portrait} |"
            )
        if cards:
            lines += ["", "## Portraits", ""]
            for card in cards:
                lines += [f"### {card['character']}", f"![{card['character']}]({card['url']})", ""]
        return "\n".join(lines)
