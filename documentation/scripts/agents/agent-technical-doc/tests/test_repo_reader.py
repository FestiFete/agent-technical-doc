"""Task 2 — extraction sûre + lecture bornée du dépôt."""
import io
import os
import tarfile

import pytest

from docagent.config import ReadCaps
from docagent.repo_reader import RepoReader, RepoTooLargeError, extract_tarball_safely


def _make_tarball(files: dict[str, bytes], top: str = "acme-widget-abc123",
                  extra_members=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, content in files.items():
            info = tarfile.TarInfo(name=f"{top}/{rel}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        for member in (extra_members or []):
            tar.addfile(member)
    return buf.getvalue()


def test_extract_returns_top_level_root(tmp_path):
    tar = _make_tarball({"README.md": b"# hello", "src/app.py": b"print(1)"})
    root = extract_tarball_safely(tar, str(tmp_path))
    assert os.path.isdir(root)
    assert os.path.isfile(os.path.join(root, "README.md"))
    assert os.path.isfile(os.path.join(root, "src", "app.py"))


def test_extract_rejects_path_traversal(tmp_path):
    evil = tarfile.TarInfo(name="../../etc/evil")
    evil.size = 3
    # membre malveillant hors du top-level
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.addfile(evil, io.BytesIO(b"bad"))
    with pytest.raises(RepoTooLargeError):
        extract_tarball_safely(buf.getvalue(), str(tmp_path))


def test_extract_skips_symlinks(tmp_path):
    link = tarfile.TarInfo(name="acme-widget-abc123/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    tar = _make_tarball({"README.md": b"ok"}, extra_members=[link])
    root = extract_tarball_safely(tar, str(tmp_path))
    assert not os.path.lexists(os.path.join(root, "link"))


def _reader_with(tmp_path, files: dict[str, str], caps=None) -> RepoReader:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return RepoReader(str(tmp_path), caps=caps)


def test_list_tree_skips_vendored_and_binary(tmp_path):
    reader = _reader_with(tmp_path, {
        "README.md": "# hi",
        "src/main.py": "x=1",
        "node_modules/lib/index.js": "// vendored",
        "assets/logo.png": "binary",
        "package-lock.json.lock": "lock",
    })
    tree = reader.list_tree()
    assert "README.md" in tree
    assert "src/main.py" in tree
    assert all("node_modules" not in t for t in tree)
    assert "assets/logo.png" not in tree


def test_list_tree_respects_max_files(tmp_path):
    files = {f"f{i}.txt": "x" for i in range(20)}
    reader = _reader_with(tmp_path, files, caps=ReadCaps(max_files=5))
    assert len(reader.list_tree()) == 5


def test_read_file_bounded_by_max_file_bytes(tmp_path):
    reader = _reader_with(tmp_path, {"big.txt": "A" * 1000}, caps=ReadCaps(max_file_bytes=100))
    text = reader.read_file("big.txt")
    assert "tronqué" in text
    assert text.count("A") == 100


def test_read_file_respects_total_budget(tmp_path):
    reader = _reader_with(
        tmp_path, {"a.txt": "A" * 80, "b.txt": "B" * 80, "c.txt": "C" * 80},
        caps=ReadCaps(max_file_bytes=100, max_total_bytes=100),
    )
    first = reader.read_file("a.txt")
    second = reader.read_file("b.txt")
    third = reader.read_file("c.txt")
    assert first.count("A") == 80
    # Lecture partielle jusqu'à épuisement du budget total (20 octets restants).
    assert second.count("B") == 20
    assert reader.bytes_read == 100
    # Budget épuisé : lecture suivante vide.
    assert third == ""


def test_read_file_refuses_traversal(tmp_path):
    reader = _reader_with(tmp_path, {"ok.txt": "ok"})
    with pytest.raises(ValueError):
        reader.read_file("../../../etc/passwd")
