"""The console entry point: `guzzionboard` and `python -m guzzionboard`."""
import subprocess
import sys

from guzzionboard.__main__ import build_parser


def test_parser_knows_its_flags():
    args = build_parser().parse_args(["--host", "0.0.0.0", "--port", "9000",
                                      "--no-record"])
    assert args.host == "0.0.0.0" and args.port == 9000 and args.no_record


def test_parser_defaults_stay_local():
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"      # a tool for one laptop, one bike
    assert args.port == 8000 and not args.no_record


def test_python_dash_m_help_works():
    out = subprocess.run(
        [sys.executable, "-m", "guzzionboard", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0
    assert "simulator mode" in out.stdout.lower()
    assert "hardware" in out.stdout.lower()


def test_console_script_is_registered():
    src = open("pyproject.toml", encoding="utf-8").read()
    assert 'guzzionboard = "guzzionboard.__main__:main"' in src
