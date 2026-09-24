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
        "The pain in my chest is going into my jaw and I feel faint",
        "My baby is floppy and won't wake up properly",
        "I'm 34 weeks pregnant and bleeding heavily",
        "Stiff neck, high fever and a rash that doesn't fade",
        "My arm is numb and my speech sounds weird",
        "I can't stop shaking and it's hard to breathe",
    ],
)
def test_emergencies(text):
    assert screen(text).level == "emergency"


@pytest.mark.parametrize(
    "text",
    [
        "I want to kill myself",
        "I've been thinking about suicide",
        "I keep hurting myself",
        "I feel like I can't go on anymore and there's no point living",
        "I don't want to be here anymore",
    ],
)
def test_crisis_outranks_everything(text):
    assert screen(text).level == "crisis"


def test_chest_symptoms_need_a_safety_check_first():
    result = screen("I've had chest discomfort since yesterday")
    assert result.level == "screen"
    assert result.topic == "chest"


def test_palpitations_need_a_safety_check():
    assert screen("My heart is racing and I feel uneasy").topic == "chest"


@pytest.mark.parametrize(
    "text", ["It's not hard to breathe, just a cough", "I'm pregnant and want to book my scan", "My son has a mild cold"]
)
def test_new_rules_stay_calm_on_routine_messages(text):
    assert screen(text).level == "none"


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
