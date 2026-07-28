"""Downloading: the capability with the most ways to go wrong."""

from __future__ import annotations

from pathlib import Path

import pytest

from oszt.broker import Context
from oszt.capabilities import net
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.policy import Policy
from oszt.runner import RecordingRunner


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def net_policy(downloads: Path, tmp_path: Path) -> Policy:
    return Policy.from_dict(
        {
            "allowed_capabilities": ["download_file"],
            "file_roots": [str(downloads)],
            "write_roots": [str(downloads)],
            "protected_paths": [],
            "trash_dir": str(tmp_path / "trash"),
            "allowed_hosts": ["flathub.org"],
            "max_download_bytes": 1024,
            "dry_run": False,
        }
    )


@pytest.fixture
def ctx(net_policy: Policy, runner: RecordingRunner) -> Context:
    return Context(policy=net_policy, run=runner)


def test_an_allowed_download_uses_curl_with_the_size_cap(
    ctx: Context, runner: RecordingRunner, downloads: Path
) -> None:
    net.download_file(ctx, url="https://flathub.org/thing.zip", filename="thing.zip")
    argv = runner.calls[0]
    assert argv[0] == "curl"
    assert "--max-filesize" in argv and "1024" in argv
    assert str(downloads / "thing.zip") in argv
    assert "--proto" in argv and "=https" in argv


@pytest.mark.parametrize(
    "url",
    [
        "http://flathub.org/thing.zip",  # plain http
        "file:///etc/passwd",  # not the web at all
        "https://evil.example.com/thing.zip",  # host not allowlisted
    ],
)
def test_unsafe_urls_are_refused(ctx: Context, url: str) -> None:
    with pytest.raises(PolicyViolation):
        net.download_file(ctx, url=url, filename="thing.zip")


@pytest.mark.parametrize(
    "filename",
    ["../escape.zip", "/etc/cron.d/job", "sub/dir.zip", ".bashrc", ""],
)
def test_the_filename_must_be_a_plain_name(ctx: Context, filename: str) -> None:
    with pytest.raises(PolicyViolation):
        net.download_file(ctx, url="https://flathub.org/x.zip", filename=filename)


def test_a_download_will_not_overwrite_an_existing_file(
    ctx: Context, downloads: Path
) -> None:
    (downloads / "thing.zip").write_text("mine\n", encoding="utf-8")
    with pytest.raises(CapabilityFailed):
        net.download_file(ctx, url="https://flathub.org/thing.zip", filename="thing.zip")


def test_a_downloaded_file_loses_its_execute_bits(
    net_policy: Policy, downloads: Path
) -> None:
    class CurlThatWritesAnExecutable(RecordingRunner):
        """Stands in for curl fetching a shell script marked executable."""

        def __call__(self, argv):  # type: ignore[no-untyped-def]
            target = Path(argv[argv.index("--output") + 1])
            target.write_bytes(b"#!/bin/sh\necho pwned\n")
            target.chmod(0o755)
            return super().__call__(argv)

    ctx = Context(policy=net_policy, run=CurlThatWritesAnExecutable())
    result = net.download_file(
        ctx, url="https://flathub.org/payload.sh", filename="payload.sh"
    )
    assert result["executable"] is False
    assert (downloads / "payload.sh").stat().st_mode & 0o111 == 0


def test_dry_run_records_the_command_but_writes_nothing(
    downloads: Path, tmp_path: Path, runner: RecordingRunner
) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["download_file"],
            "file_roots": [str(downloads)],
            "write_roots": [str(downloads)],
            "trash_dir": str(tmp_path / "trash"),
            "allowed_hosts": ["flathub.org"],
            "dry_run": True,
        }
    )
    result = net.download_file(
        Context(policy=policy, run=runner),
        url="https://flathub.org/thing.zip",
        filename="thing.zip",
    )
    assert result["dry_run"] is True
    assert not (downloads / "thing.zip").exists()
    assert runner.calls  # the argv is still recorded for the ledger
