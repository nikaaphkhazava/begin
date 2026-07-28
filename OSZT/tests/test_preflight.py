from __future__ import annotations

from oszt.preflight import (
    DEFAULT_MODELS,
    REQUIREMENTS,
    Requirement,
    check,
    check_models,
    installed_models,
    report,
    report_models,
)


def test_every_requirement_carries_an_install_command_and_purpose() -> None:
    assert REQUIREMENTS
    for requirement in REQUIREMENTS:
        assert requirement.install.strip()
        assert requirement.purpose.strip()


def test_the_asus_and_nvidia_tools_are_required_not_optional() -> None:
    required = {
        requirement.binary for requirement in REQUIREMENTS if not requirement.optional
    }
    assert {"asusctl", "supergfxctl", "nvidia-smi"} <= required


def test_rpm_ostree_is_optional_because_plain_fedora_lacks_it() -> None:
    optional = {requirement.binary for requirement in REQUIREMENTS if requirement.optional}
    assert "rpm-ostree" in optional


def test_check_marks_present_and_missing_binaries() -> None:
    requirements = (
        Requirement("here", "install here", "does a thing"),
        Requirement("gone", "install gone", "does another thing"),
    )
    statuses = check(requirements, which=lambda name: "/usr/bin/here" if name == "here" else None)
    assert [status.present for status in statuses] == [True, False]


def test_only_missing_required_tools_are_blocking() -> None:
    requirements = (
        Requirement("gone", "install gone", "needed"),
        Requirement("extra", "install extra", "nice to have", optional=True),
    )
    statuses = check(requirements, which=lambda name: None)
    assert [status.blocking for status in statuses] == [True, False]


def test_report_prints_the_install_command_for_missing_tools() -> None:
    requirements = (Requirement("asusctl", "sudo dnf install asusctl", "fans"),)
    text = report(check(requirements, which=lambda name: None))
    assert "MISSING" in text
    assert "sudo dnf install asusctl" in text
    assert "1 required tool(s) missing" in text


def test_report_is_clean_when_everything_is_installed() -> None:
    requirements = (Requirement("asusctl", "sudo dnf install asusctl", "fans"),)
    text = report(check(requirements, which=lambda name: "/usr/bin/asusctl"))
    assert "all required tools present" in text
    assert "dnf" not in text


def test_a_missing_optional_tool_does_not_block() -> None:
    requirements = (Requirement("ddcutil", "sudo dnf install ddcutil", "monitors", True),)
    text = report(check(requirements, which=lambda name: None))
    assert "missing?" in text
    assert "all required tools present" in text


# --- the models: installed and pulled are different questions -----------------


def test_ollama_is_a_required_tool_with_the_official_install_line() -> None:
    ollama = next(item for item in REQUIREMENTS if item.binary == "ollama")
    assert not ollama.optional
    assert "ollama.com/install.sh" in ollama.install


def test_the_default_models_are_the_mind_and_the_eye() -> None:
    assert [model.name for model in DEFAULT_MODELS] == ["qwen2.5:3b", "moondream"]
    for model in DEFAULT_MODELS:
        assert model.purpose.strip()
        assert "GB" in model.size


def test_a_pulled_model_is_recognised_with_or_without_the_latest_tag() -> None:
    statuses = check_models(present=frozenset({"qwen2.5:3b", "moondream:latest"}))
    assert statuses is not None
    assert [status.present for status in statuses] == [True, True]


def test_a_model_that_was_never_pulled_is_reported_with_the_pull_command() -> None:
    statuses = check_models(present=frozenset({"qwen2.5:3b"}))
    text = report_models(statuses)
    assert "ollama pull moondream" in text
    assert "1 model(s) not pulled" in text


def test_all_models_pulled_says_so_and_offers_nothing() -> None:
    text = report_models(check_models(present=frozenset({"qwen2.5:3b", "moondream"})))
    assert "all models pulled" in text
    assert "ollama pull" not in text


def test_ollama_absent_recommends_installing_it_and_both_models() -> None:
    """The download-and-run case: recommend Ollama, do not pretend to know more."""
    text = report_models(None)
    assert "curl -fsSL https://ollama.com/install.sh | sh" in text
    assert "ollama pull qwen2.5:3b" in text
    assert "ollama pull moondream" in text
    assert "the broker still works" in text


def test_the_models_cannot_be_listed_when_ollama_is_not_installed() -> None:
    assert installed_models(which=lambda name: None) is None
