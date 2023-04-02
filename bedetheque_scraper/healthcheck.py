from __future__ import annotations
import shutil

import xml.etree.ElementTree as ET
from pathlib import Path

DB_PATH = Path(r"C:\Users\Henri\AppData\Roaming\cYo\ComicRack\ComicDb.xml")


def open_comicrack_db() -> ET.ElementTree:
    return ET.parse(DB_PATH)


def get_books_from_db() -> list[ET.Element]:
    tree = open_comicrack_db()
    root = tree.getroot()
    books_et = root.find("Books")
    return books_et.findall("Book")


def check_for_missing_files() -> list[Path]:
    missings: list[Path] = []
    for book in get_books_from_db():
        if any(str(x).endswith("...") for x in Path(book.get("File")).parts):
            continue
        if not Path(book.get("File")).exists():
            missings.append(Path(book.get("File")))
    return missings


def check_in_trash(path: Path) -> Path | None:
    if path.anchor.lower() != "\\\\quirinalis\\bagarre\\":
        return None
    parents = path.relative_to(path.anchor)
    if (trash_path := (Path(path.anchor) / "#recycle").joinpath(parents)).exists():
        return trash_path
    else:
        return None


def main() -> None:
    missings = check_for_missing_files()
    for missing in sorted(missings):
        if trash_path := check_in_trash(missing):
            print(f"Found in trash: {missing}")
            missing.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(trash_path, missing)
        else:
            print(f"Missing: {missing}")

    print(f"Total: {len(missings)}")


if __name__ == "__main__":
    main()
