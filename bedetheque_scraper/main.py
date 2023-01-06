from __future__ import annotations

from zipfile import ZipFile
import logging
from pathlib import Path

from .file_name import BDFile, get_titles
from .scraper import Album, scrape

ROOT_FOLDER = Path("/media/aubustou/Dyonisos/Bagarre/Bédés")

COMICINFO_FILE = "ComicInfo.xml"


def add_file_to_zip(zip_file: Path, file: Album) -> None:
    """Add a file to a zip file"""

    with ZipFile(zip_file, "a") as zip_:
        if COMICINFO_FILE not in zip_.namelist():
            zip_.writestr("ComicInfo.xml", file.to_xml())


def main():
    """Main function"""
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    files = get_titles(ROOT_FOLDER)

    mapped_files: dict[str, list[BDFile]] = {}
    for file_ in files:
        mapped_files.setdefault(file_.title, []).append(file_)

    for title, files in mapped_files.items():
        logging.info("Scraping %s", title)
        numbers = [file_.number for file_ in files if file_.number is not None]
        albums = scrape(title, numbers)
        if not albums:
            for file_ in files:
                logging.warning("No album found for %s", file_.relative_path)
            title = input("Title for files: ")
            if not title:
                continue
            albums = scrape(title, numbers)

        for index, album in enumerate(albums):
            file_ = files[index]
            logging.info("Adding %s to %s", file_.relative_path, album)
            add_file_to_zip(file_.file_path, album)


if __name__ == "__main__":
    main()
