"""Repository scripts in scripts/ (standard library only, loaded by path)."""

import importlib.util
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load("backup")


def test_archive_round_trip(tmp_path):
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    env = tmp_path / ".env"
    env.write_text("POSTGRES_DB=custom\n")
    archive = tmp_path / "b.tar"

    backup.write_archive(
        archive, {"platemates.dump": dump, "keycloak.dump": dump}, env, {"created_at": "now"}
    )

    assert backup.read_manifest(archive) == {"created_at": "now"}
    with tarfile.open(archive) as tar:
        assert set(tar.getnames()) == {"manifest.json", "platemates.dump", "keycloak.dump", ".env"}
    # Backups hold personal data and password hashes.
    assert archive.stat().st_mode & 0o077 == 0


def test_archives_without_manifest_are_rejected(tmp_path):
    archive = tmp_path / "other.tar"
    with tarfile.open(archive, "w"):
        pass
    with pytest.raises(ValueError, match="no manifest"):
        backup.read_manifest(archive)


def test_database_names_follow_env():
    assert backup.databases({"POSTGRES_DB": "app", "KEYCLOAK_DB": "kc"}) == {
        "platemates.dump": "app",
        "keycloak.dump": "kc",
    }
    assert backup.databases({}) == {"platemates.dump": "platemates", "keycloak.dump": "keycloak"}


def test_pruning_keeps_the_newest():
    names = [Path(f"platemates-2026100{d}-000000.tar") for d in (3, 1, 2)]
    assert backup.backups_to_prune(names, keep=2) == [Path("platemates-20261001-000000.tar")]
    assert backup.backups_to_prune(names, keep=0) == []


def test_read_env_ignores_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# POSTGRES_DB=no\nPOSTGRES_DB=yes\n\nEMPTY=\n")
    assert backup.read_env(env) == {"POSTGRES_DB": "yes", "EMPTY": ""}
