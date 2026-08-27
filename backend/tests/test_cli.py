"""Smoke tests for the command line itself.

These exist because a syntax error in `cli.py` once survived a full green test
run: nothing else imports it, so nothing else notices. The CLI is the only way
ingestion is ever invoked on the workstation, and it must not be the least
tested module in the backend.
"""

from __future__ import annotations

import pytest

from app import cli


def test_the_cli_module_imports() -> None:
    """The test that would have caught the syntax error."""
    assert cli.main is not None


def test_every_subcommand_parses_and_has_a_handler() -> None:
    parser = cli.build_parser()
    subparsers = [
        action for action in parser._actions if isinstance(action, __import__("argparse")._SubParsersAction)
    ]
    assert subparsers, "the CLI should expose subcommands"

    names = set(subparsers[0].choices)
    assert {
        "health", "providers", "paths",
        "classify", "extract", "verify", "bench", "chunk",
        "index", "documents", "delete", "search", "ask",
    } <= names

    # Two commands take a mandatory argument: what to delete, and what to ask.
    required = {
        "delete": ["some-doc-id"],
        "search": ["what", "is", "a", "PEP"],
        "ask": ["what", "is", "a", "PEP"],
    }
    for name in names:
        args = parser.parse_args([name, *required.get(name, [])])
        assert callable(args.handler), f"{name} has no handler"


@pytest.mark.parametrize(
    "command",
    ["health", "providers", "paths", "classify", "extract", "verify",
     "bench", "chunk", "index", "documents", "delete", "search", "ask"],
)
def test_help_renders_for_each_subcommand(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args([command, "--help"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip()


def test_unknown_command_exits_rather_than_raising() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["definitely-not-a-command"])


def test_output_streams_are_forced_to_utf8() -> None:
    """Both machines are Windows, where stdout defaults to a code page that
    cannot encode the arrows and superscripts this CLI prints."""
    cli._force_utf8_output()  # must not raise, whatever the stream is
