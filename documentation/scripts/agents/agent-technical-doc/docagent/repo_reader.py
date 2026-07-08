"""Lecture bornée et sûre d'un dépôt (extrait d'une archive tarball GitHub).

Principes de sécurité (le contenu du dépôt est NON FIABLE) :
- Extraction protégée contre le *path traversal* (zip/tar-slip) : tout membre
  dont le chemin résolu sort du répertoire de destination est rejeté ; les liens
  symboliques, liens durs et fichiers spéciaux sont ignorés.
- Aucune exécution : on ne fait que lire des octets.
- Lecture bornée par des plafonds (nombre de fichiers, taille par fichier, taille
  totale) pour maîtriser le contexte, la mémoire et le coût.
"""
from __future__ import annotations

import io
import logging
import os
import tarfile

from .config import BINARY_EXTENSIONS, VENDORED_DIRS, ReadCaps, read_caps

logger = logging.getLogger(__name__)


class RepoTooLargeError(RuntimeError):
    """Le dépôt dépasse un plafond de sécurité."""


def _is_within(base: str, target: str) -> bool:
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def extract_tarball_safely(tar_bytes: bytes, dest_dir: str) -> str:
    """Extrait une archive tar.gz en mémoire vers ``dest_dir`` de façon sûre.

    Retourne le chemin du répertoire racine du dépôt (top-level de l'archive
    GitHub, ex. ``owner-repo-<sha>/``). Lève ``RepoTooLargeError`` ou rejette les
    membres dangereux.
    """
    os.makedirs(dest_dir, exist_ok=True)
    top_levels: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Ignorer tout ce qui n'est pas fichier ou dossier régulier
            # (liens symboliques/durs, périphériques) : vecteur d'évasion.
            if member.issym() or member.islnk() or member.ischr() or \
                    member.isblk() or member.isfifo():
                logger.warning("Membre spécial ignoré à l'extraction: %s", member.name)
                continue
            target_path = os.path.join(dest_dir, member.name)
            if not _is_within(dest_dir, target_path):
                raise RepoTooLargeError(f"Chemin d'archive suspect (traversal): {member.name}")
            parts = member.name.split("/", 1)
            if parts and parts[0]:
                top_levels.add(parts[0])
            tar.extract(member, path=dest_dir, filter="data")

    if len(top_levels) == 1:
        return os.path.join(dest_dir, next(iter(top_levels)))
    return dest_dir


class RepoReader:
    """Lecture bornée d'un dépôt déjà extrait dans ``root``."""

    def __init__(self, root: str, caps: ReadCaps | None = None):
        self.root = os.path.realpath(root)
        self.caps = caps or read_caps()
        self._bytes_read = 0

    # --- filtres -------------------------------------------------------------
    @staticmethod
    def is_vendored(rel_path: str) -> bool:
        parts = rel_path.replace("\\", "/").split("/")
        return any(p in VENDORED_DIRS for p in parts)

    @staticmethod
    def is_binary(rel_path: str) -> bool:
        _, ext = os.path.splitext(rel_path.lower())
        return ext in BINARY_EXTENSIONS

    def _is_readable(self, rel_path: str) -> bool:
        return not self.is_vendored(rel_path) and not self.is_binary(rel_path)

    # --- arborescence --------------------------------------------------------
    def list_tree(self) -> list[str]:
        """Liste les fichiers pertinents (relatifs à ``root``), plafonnée.

        Trie de façon déterministe et applique le plafond ``max_files``.
        """
        collected: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Élague les dossiers vendored à la source (évite de les parcourir).
            dirnames[:] = sorted(d for d in dirnames if d not in VENDORED_DIRS)
            for name in sorted(filenames):
                abs_path = os.path.join(dirpath, name)
                rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
                if not self._is_readable(rel):
                    continue
                collected.append(rel)
                if len(collected) >= self.caps.max_files:
                    logger.info("Plafond max_files atteint (%d)", self.caps.max_files)
                    return collected
        return collected

    # --- lecture -------------------------------------------------------------
    def read_file(self, rel_path: str) -> str:
        """Lit un fichier texte, borné à ``max_file_bytes`` et au budget total.

        Refuse toute sortie de ``root`` (path traversal) et tout fichier
        binaire/vendored. Retourne "" si le budget est épuisé.
        """
        rel_norm = rel_path.replace("\\", "/").lstrip("/")
        abs_path = os.path.join(self.root, rel_norm)
        if not _is_within(self.root, abs_path):
            raise ValueError(f"Chemin hors du dépôt refusé: {rel_path}")
        if not self._is_readable(rel_norm):
            return ""
        if not os.path.isfile(abs_path):
            return ""
        if self._bytes_read >= self.caps.max_total_bytes:
            logger.info("Budget total de lecture épuisé (%d octets)", self.caps.max_total_bytes)
            return ""

        remaining = self.caps.max_total_bytes - self._bytes_read
        limit = min(self.caps.max_file_bytes, remaining)
        with open(abs_path, "rb") as fh:
            raw = fh.read(limit + 1)
        truncated = len(raw) > limit
        raw = raw[:limit]
        self._bytes_read += len(raw)
        text = raw.decode("utf-8", errors="replace")
        if truncated:
            text += "\n\n[...tronqué par l'agent (plafond de lecture)...]"
        return text

    @property
    def bytes_read(self) -> int:
        return self._bytes_read
