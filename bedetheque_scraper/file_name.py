from __future__ import annotations
from zipfile import BadZipFile, ZipFile
import locale
import re

from pathlib import Path
from dataclasses import InitVar, dataclass, field
import logging


def recurse_find_cbz(
    path: Path, exclude_comicinfo: bool = False, accept_zip: bool = False
) -> list[Path]:
    """Recursively find all cbz files in a directory and its subdirectories.

    Args:
        path (Path): The directory to search.

    Returns:
        list[Path]: A list of all cbz files found.
    """
    accepted_extensions = {".cbz"}
    if accept_zip:
        accepted_extensions.add(".zip")

    cbz_files: list[Path] = []
    for file in path.iterdir():
        if file.is_dir():
            cbz_files.extend(recurse_find_cbz(file, exclude_comicinfo, accept_zip))
        elif file.suffix.lower() in accepted_extensions:
            try:
                with ZipFile(file, "r") as zip_:  # type: ignore
                    if exclude_comicinfo and "ComicInfo.xml" in zip_.namelist():
                        continue
            except BadZipFile:
                logging.warning("Bad zip file: %s", file)
                continue
            cbz_files.append(file)
    return cbz_files


def remove_root_folder_from_path(path: Path, root: Path) -> Path:
    """Remove the root folder from a path.

    Args:
        path (Path): The path to remove the root folder from.

    Returns:
        Path: The path with the root folder removed.
    """
    return Path(*path.parts[len(root.parents) + 1 :])


NUMBER_PATTERNS = [
    re.compile(r"( T(\d+))"),
    re.compile(r"((\d+))"),
    re.compile(r"( [Tt]ome\s*(\d+))"),
    re.compile(r"( Vol(?:ume)?\s?(\d+))"),
    re.compile(r"( -\s*(\d+)\s*-)"),
]

ALREADY_FORMATTED_PATTERN = re.compile(r"(.*) #\d+.*")
TITLE_PATTERNS = [
    re.compile(r"/?([a-zA-Z][\w '&.-]+)"),
]


@dataclass
class BDFile:
    file_path: Path

    root: InitVar[Path]

    relative_path: Path = field(init=False)
    file_name: str = field(default="", init=False)
    parents: list[str] = field(default_factory=list, init=False)
    file_extension: str = field(default="", init=False)

    number: str | None = field(default=None, init=False)
    ai_suggested_title: str = field(default="", init=False)
    regex_suggested_title: str = field(default="", init=False)

    found_number: str = field(default="", init=False)

    def __post_init__(self, root: Path) -> None:
        self.file_name = self.file_path.stem
        self.file_extension = self.file_path.suffix

        self.relative_path = remove_root_folder_from_path(self.file_path, root)
        self.parents = [parent.name for parent in self.relative_path.parents]

        self.get_number()
        self.get_title()

    @property
    def title(self) -> str:
        return self.ai_suggested_title or self.regex_suggested_title

    def __repr__(self) -> str:
        if self.number is not None:
            return f"{self.title} - {self.number} ({self.file_name})"
        else:
            return f"{self.title} ({self.file_name})"

    def get_number(self):
        """Get the number from the file name.

        Returns:
            str: The number from the file name.
        """
        for pattern in NUMBER_PATTERNS:
            if match := pattern.search(self.file_name):
                block = match.group(1)
                number = match.group(2)

                if len(number) == 4 and any(number.startswith(x) for x in ["19", "20"]):
                    # If the number is 4 digits and starts with 19 or 20, it's
                    # probably a year.
                    continue

                self.found_number = block

                if number.isdigit():
                    self.number = str(int(number))
                else:
                    self.number = number
                return

    def get_title(self):
        """Get the title from the file name.

        Returns:
            str: The title from the file name.
        """
        if match := ALREADY_FORMATTED_PATTERN.search(self.file_name):
            self.regex_suggested_title = match.group(1)
            return

        for name in [self.file_name, *self.parents]:
            if self.found_number:
                name = name.split(self.found_number)[0].strip()

            name = name.split(" - ")[0].strip()

            name = replace_double_spaces(name)

            for suffix in ["-", "_", ":", "–", "."]:
                name = name.removesuffix(suffix)
                name = name.strip()

            for pattern in TITLE_PATTERNS:
                if match := pattern.search(name):
                    self.regex_suggested_title = match.group(1)
                    return


def get_titles(
    path: Path, exclude_comicinfo: bool = True, accept_zip: bool = False
) -> list[BDFile]:
    """Get the titles of all cbz files in a directory and its subdirectories.

    Args:
        path (Path): The directory to search.

    Returns:
        list[str]: A list of all titles found.
    """
    locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")

    titles = []
    for file in recurse_find_cbz(path, exclude_comicinfo, accept_zip=accept_zip):
        title = BDFile(file, root=path)
        titles.append(title)
    return titles


def replace_double_spaces(string: str) -> str:
    """Replace double spaces with single spaces.

    Args:
        string (str): The string to replace double spaces in.

    Returns:
        str: The string with double spaces replaced.
    """
    return re.sub(r"\s{2,}", " ", string)
