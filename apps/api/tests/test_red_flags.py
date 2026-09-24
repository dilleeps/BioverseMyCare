import pytest

from bioverse.safety.red_flags import evaluate_safety_check, screen


@pytest.mark.parametrize(
    "text",
    [
        "my face is drooping and I have slurred speech",
        "I can't breathe properly",
        "my throat is closing up after eating peanuts",
        "I'm vomiting blood",
        "my dad passed out and is unresponsive",
        "chest pain spreading to my left arm",
        "crushing chest pressure",
        "I think I took too many pills",
    ],
)
def test_emergencies(text):
    assert screen(text).level == "emergency"


@pytest.mark.parametrize("text", ["I want to kill myself", "I've been thinking about suicide", "I keep hurting myself"])
def test_crisis_outranks_everything(text):
    assert screen(text).level == "crisis"


def test_chest_symptoms_need_a_safety_check_first():
    result = screen("I've had chest discomfort since yesterday")
    assert result.level == "screen"
    assert result.topic == "chest"


def test_headache_needs_a_safety_check():
    assert screen("bad headache since this morning").topic == "headache"


@pytest.mark.parametrize("text", ["I have an itchy rash on my arm", "need a refill of my inhaler", "hello"])
def test_routine_messages_pass(text):
    assert screen(text).level == "none"


def test_negated_findings_do_not_fire():
    assert screen("no chest pain, just a rash").level == "none"
    assert screen("I have not passed out").level == "none"


def test_safety_check_any_positive_is_emergency():
    assert evaluate_safety_check("chest", ["none"]).level == "none"
    positive = evaluate_safety_check("chest", ["breathless"])
    assert positive.level == "emergency"
    assert positive.flags == ["Shortness of breath"]


def test_unknown_safety_answer_is_treated_as_positive():
    assert evaluate_safety_check("chest", ["something-new"]).level == "emergency"
