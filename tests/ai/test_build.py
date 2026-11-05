import pytest
from pydantic import BaseModel

from why_now.ai import BadModelOutput, ResearchStep, UnknownModel, build_models
from why_now.ai.claude import ClaudeAnswerer
from why_now.domain import FitQuestion
from why_now.sample.models import Script, scripted_models

QUESTIONS = [FitQuestion(id="q1", text="A?"), FitQuestion(id="q2", text="B?")]


def test_without_a_jev_key_the_quick_look_uses_claude(settings, meter):
    models = build_models(settings, meter, env={"ANTHROPIC_API_KEY": "test-key"})
    assert isinstance(models.quick_look, ClaudeAnswerer)
    assert models.quick_look.model == "claude-haiku-5-5"
    assert models.judge.model == "claude-sonnet-5-5"


def test_with_a_jev_key_the_quick_look_uses_a_locked_jev_version(settings, meter):
    pytest.importorskip("typesafe_sdk")
    env = {"ANTHROPIC_API_KEY": "test-key", "TYPESAFE_API_KEY": "test-key"}
    assert build_models(settings, meter, env).quick_look.model == "jev-1.14.0"


def test_a_jev_alias_in_the_settings_is_refused(settings, meter):
    pytest.importorskip("typesafe_sdk")
    env = {"ANTHROPIC_API_KEY": "test-key", "TYPESAFE_API_KEY": "test-key"}
    with pytest.raises(UnknownModel):
        build_models(settings.model_copy(update={"judge_model": "jev-latest"}), meter, env)


def test_a_jev_judge_without_a_jev_key_is_refused(settings, meter):
    with pytest.raises(UnknownModel):
        build_models(settings.model_copy(update={"judge_model": "jev-1.14.0"}), meter, env={})


class Brief(BaseModel):
    text: str


def test_scripted_models_need_no_network_or_keys():
    script = Script(
        probabilities={"q1": 0.9},
        default_probability=0.2,
        writes={"Brief": {"text": "Hiring."}},
        research=[ResearchStep(read_urls=["https://acme.test"], searches_used=1, done=False)],
    )
    models = scripted_models(script)
    answers = models.judge.answer("An ad.", QUESTIONS, "judge")
    assert [(a.question_id, a.probability) for a in answers] == [("q1", 0.9), ("q2", 0.2)]
    out = models.writer.structured(system="s", untrusted="u", schema=Brief, category="brief")
    assert out == Brief(text="Hiring.")
    assert models.research.step([], "research").read_urls == ["https://acme.test"]
    assert models.research.step([], "research").done  # the script has run out


def test_a_scripted_writer_with_nothing_scripted_gives_bad_output():
    with pytest.raises(BadModelOutput):
        scripted_models(Script()).writer.structured(
            system="s", untrusted="u", schema=Brief, category="brief"
        )
