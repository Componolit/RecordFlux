from pathlib import Path
from typing import Any

import pkg_resources
import pytest

import rflx.specification
from rflx import cli
from rflx.error import Location, Severity, Subsystem, fail
from tests.const import SPEC_DIR

SPEC_FILE = str(SPEC_DIR / "tlv.rflx")


def raise_parser_error() -> None:
    fail("TEST", Subsystem.PARSER, Severity.ERROR, Location((8, 22)))


def raise_model_error() -> None:
    fail("TEST", Subsystem.MODEL, Severity.ERROR, Location((8, 22)))


def test_main_noarg() -> None:
    with pytest.raises(SystemExit, match="^2$"):
        cli.main(["rflx"])


def test_main_help() -> None:
    with pytest.raises(SystemExit):
        cli.main(["rflx", "-h"])


def test_main_check() -> None:
    assert cli.main(["rflx", "check", SPEC_FILE]) == 0


def test_main_check_quiet() -> None:
    assert cli.main(["rflx", "-q", "check", SPEC_FILE]) == 0
    assert cli.main(["rflx", "--quiet", "check", SPEC_FILE]) == 0


def test_main_check_parser_error(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli, "check", lambda x: raise_parser_error())
    assert "<stdin>:8:22: parser: error: TEST" in str(cli.main(["rflx", "check", "README.md"]))


def test_main_check_model_error_parse(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli, "check", lambda x: raise_model_error())
    assert "<stdin>:8:22: model: error: TEST" in str(cli.main(["rflx", "check", "README.md"]))


def test_main_check_model_error_create_model(monkeypatch: Any) -> None:
    monkeypatch.setattr(rflx.specification.Parser, "create_model", lambda x: raise_model_error())
    assert "<stdin>:8:22: model: error: TEST" in str(cli.main(["rflx", "check", "README.md"]))


def test_main_check_non_existent_file() -> None:
    assert 'error: file not found: "non-existent file"' in str(
        cli.main(["rflx", "check", "non-existent file"])
    )


def test_main_generate(tmp_path: Path) -> None:
    assert cli.main(["rflx", "generate", "-d", str(tmp_path), SPEC_FILE]) == 0
    top_level_package = Path(tmp_path) / (cli.DEFAULT_PREFIX.lower() + ".ads")
    assert top_level_package.exists()


def test_main_generate_no_library_files(tmp_path: Path) -> None:
    assert (
        cli.main(
            [
                "rflx",
                "generate",
                "-d",
                str(tmp_path),
                "-p",
                "",
                "-n",
                str(SPEC_DIR / "empty_package.rflx"),
            ]
        )
        == 0
    )
    assert len(list(tmp_path.glob("*"))) == 0


def test_main_generate_prefix(tmp_path: Path) -> None:
    for prefix in ["", " ", "A", "A.B", "A.B.C"]:
        assert cli.main(["rflx", "generate", "-d", str(tmp_path), "-p", prefix, SPEC_FILE]) == 0
        top_level_package = Path(tmp_path) / (prefix.replace(".", "-").lower() + ".ads")
        assert not top_level_package.exists()


def test_main_generate_invalid_prefix(tmp_path: Path) -> None:
    for prefix in [".", "A.B.", ".A.B", "A..B"]:
        assert rf'cli: error: invalid prefix: "{prefix}"' in str(
            cli.main(["rflx", "generate", "-d", str(tmp_path), "-p", prefix, SPEC_FILE])
        )


def test_main_generate_no_output_files(tmp_path: Path) -> None:
    assert (
        cli.main(["rflx", "generate", "-d", str(tmp_path), str(SPEC_DIR / "empty_package.rflx")])
        == 0
    )


def test_main_generate_non_existent_directory() -> None:
    assert 'cli: error: directory not found: "non-existent directory"' in str(
        cli.main(["rflx", "generate", "-d", "non-existent directory", SPEC_FILE])
    )


def test_main_generate_missing_template_directory(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(pkg_resources, "resource_filename", lambda *x: "non-existent directory")
    with pytest.raises(AssertionError, match="^template directory not found"):
        cli.main(["rflx", "generate", "-d", str(tmp_path), SPEC_FILE])


def test_main_generate_missing_template_files(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(pkg_resources, "resource_filename", lambda *x: tmp_path)
    with pytest.raises(AssertionError, match="^template file not found"):
        cli.main(["rflx", "generate", "-d", str(tmp_path), SPEC_FILE])


def test_main_graph(tmp_path: Path) -> None:
    assert cli.main(["rflx", "graph", "-d", str(tmp_path), SPEC_FILE]) == 0


def test_main_graph_non_existent_file(tmp_path: Path) -> None:
    assert 'cli: error: file not found: "non-existent file"' in str(
        cli.main(["rflx", "graph", "-d", str(tmp_path), "non-existent file"])
    )


def test_main_graph_non_existent_files(tmp_path: Path) -> None:
    assert (
        'cli: error: file not found: "non-existent file 1"\n'
        'cli: error: file not found: "non-existent file 2"'
        in str(
            cli.main(
                ["rflx", "graph", "-d", str(tmp_path), "non-existent file 1", "non-existent file 2"]
            )
        )
    )


def test_main_graph_non_existent_directory() -> None:
    assert 'graph: error: directory not found: "non-existent directory"' in str(
        cli.main(["rflx", "graph", "-d", "non-existent directory", SPEC_FILE])
    )


def test_main_graph_no_output_files(tmp_path: Path) -> None:
    assert (
        cli.main(["rflx", "graph", "-d", str(tmp_path), str(SPEC_DIR / "empty_package.rflx")]) == 0
    )


def test_main_export(tmp_path: Path) -> None:
    assert cli.main(["rflx", "export", "-o", str(tmp_path / "model.json"), SPEC_FILE]) == 0
