from __future__ import annotations

from oszt.preflight import REQUIREMENTS, Requirement, check, report


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
