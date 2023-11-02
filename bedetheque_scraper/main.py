from __future__ import annotations
import argparse
from itertools import islice

import json
from typing import TypedDict

from zipfile import ZipFile
import logging
import shutil
from pathlib import Path

from send2trash import send2trash

from .file_name import BDFile, get_titles
from .scraper import Album, scrape
import openai

try:
    from itertools import batched
except ImportError:

    def batched(iterable, n):
        # batched('ABCDEFG', 3) --> ABC DEF G
        if n < 1:
            raise ValueError("n must be at least one")
        it = iter(iterable)
        while batch := tuple(islice(it, n)):
            yield batch


BD_FOLDER = Path(r"M:\Bédés")
SCRAPED_FOLDER = BD_FOLDER / "Scraped"

COMICINFO_FILE = "ComicInfo.xml"

DEBUG = False


def move_to_scraped_folder(file: Path) -> None:
    """Move a file to the Scraped folder with full directories."""
    destination = SCRAPED_FOLDER / file.relative_to(BD_FOLDER)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(file, destination)


def add_file_to_zip(zip_file: Path, file: Album, *, overwrite: bool = False) -> None:
    """Add a file to a zip file"""

    temporary_zip = None

    with ZipFile(zip_file, "a") as zip_:
        # Open the ComicInfo.xml file if exists and write into it

        if COMICINFO_FILE in zip_.namelist() and overwrite:
            temporary_zip = zip_file.with_stem(zip_file.stem + "_tempBDScraper")

            if temporary_zip.exists():
                temporary_zip.unlink()

            with ZipFile(temporary_zip, "w") as temporary_zip_:
                for name in zip_.namelist():
                    if name != COMICINFO_FILE:
                        temporary_zip_.writestr(name, zip_.read(name))
                temporary_zip_.writestr(COMICINFO_FILE, file.to_xml())

        else:
            # Otherwise, create the ComicInfo.xml file
            zip_.writestr("ComicInfo.xml", file.to_xml())

    if temporary_zip is not None:
        send2trash(zip_file)
        shutil.move(temporary_zip, zip_file)

    move_to_scraped_folder(zip_file)


PROMPT = """Here is a list of paths to CBZ files. Please extract the informations and return as a JSON formatted like this:
{
"path":  <path to the cbz>,
"series": <extracted series name>,
"number": <tome number in the series if applicable>,
}
Return empty dictionary in case you cannot extract informations.
"""


MODEL = "gpt-4"


def extract_json(
    response_content: str,
    start_marker="[",
    end_marker="]",
) -> list[BDMetadata]:
    # Find the start and end of the JSON
    start_idx = response_content.find(start_marker)
    end_idx = response_content.rfind(end_marker)

    # Extract and parse the JSON data
    to_return: list[BDMetadata] = []
    if start_idx != -1 and end_idx != -1:
        json_str = response_content[start_idx : end_idx + 1]
        try:
            json_data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logging.error("Failed to decode JSON: %s", json_str, exc_info=exc)
        else:
            logging.debug("JSON data: %s", json_str)
            for metadata in json_data if isinstance(json_data, list) else [json_data]:
                if ensure_metadata(metadata):
                    to_return.append(metadata)

    else:
        logging.warning(
            "Start marker %s or end marker %s not found", start_marker, end_marker
        )
        # Assume the whole response is a single JSON object
        to_return = extract_json(response_content, start_marker="{", end_marker="}")

    return to_return


def ensure_metadata(metadata: BDMetadata) -> bool:
    for key in ["path", "series", "number"]:
        if key not in metadata:
            logging.warning("Missing key %s in metadata %s", key, metadata)
            return False
    return True


def remove_zeroes(number: str | int) -> str:
    if isinstance(number, int):
        return str(number)

    try:
        if int(number) == 0:
            return "0"
    except ValueError:
        pass

    return number.lstrip("0")


class BDMetadata(TypedDict):
    path: str
    series: str
    number: str | None


MAX_NUMBER_PER_PROMPT = 15


def get_metadata_from_ai(files: list[BDFile]) -> list[BDFile]:
    ai_files: dict[str, BDFile] = {
        str(x.file_path.relative_to(BD_FOLDER).as_posix()): x for x in files
    }

    prompt = PROMPT + "\n".join(y for y in ai_files)

    existing = Path("response.txt")

    global DEBUG
    if existing.exists() and DEBUG:
        response = existing.read_text()
    else:
        completion = openai.ChatCompletion.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}]
        )
        response = completion["choices"][0]["message"]["content"]
        with open("response.txt", "w") as f:
            f.write(response)

    if metadata := extract_json(response):
        for file_data in metadata:
            if not file_data:
                continue
            file_ = ai_files.get(file_data["path"])
            if file_ is None:
                logging.error("File %s not found", file_data["path"])
                continue
            file_.ai_suggested_title = file_data["series"]
            file_.number = remove_zeroes(
                file_data["number"] if file_data["number"] is not None else ""
            )

    return list(ai_files.values())


def map_by_titles(files: list[BDFile], use_ai: bool = False) -> dict[str, list[BDFile]]:
    if use_ai:
        ai_files = []
        for batch in batched(files, MAX_NUMBER_PER_PROMPT):
            ai_files.extend(get_metadata_from_ai(batch))

        files = ai_files

    mapped_files: dict[str, list[BDFile]] = {}
    for file_ in files:
        mapped_files.setdefault(file_.title, []).append(file_)

    return mapped_files


def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    parser.add_argument("root_folder", type=Path)
    parser.add_argument("--include-comicinfo", action="store_true", default=False)
    parser.add_argument("--overwrite", action="store_true", default=False)
    parser.add_argument("--accept-zip", action="store_true", default=False)
    parser.add_argument("--use-ai", action="store_true", default=False)
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument(
        "--credentials-file", type=Path, default=Path("credentials.json")
    )
    args = parser.parse_args()

    global DEBUG
    DEBUG = args.debug

    openai.api_key = json.loads(args.credentials_file.read_text())["openai_key"]

    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    files = get_titles(
        args.root_folder,
        exclude_comicinfo=not args.include_comicinfo,
        accept_zip=args.accept_zip,
    )

    if not files:
        logging.info("No files found")
        return

    mapped_files = map_by_titles(files, use_ai=args.use_ai)

    for title, files in mapped_files.items():
        logging.info("Scraping %s", title)
        numbers: list[str] = [
            str(file_.number).lower() for file_ in files if file_.number is not None
        ]
        albums = scrape(title, numbers)

        # if not albums:
        #     for file_ in files:
        #         logging.warning("No album found for %s", file_.relative_path)
        #     title = input("Title for files: ")
        #     if not title:
        #         continue
        #     albums = scrape(title, numbers)

        for album in albums:
            if not (
                file_ := next(
                    file_
                    for file_ in files
                    if file_.number.lower() == album.number.lower()
                )
            ):
                logging.error("Cannot find file for %s", album)
                continue
            logging.info("Adding %s to %s", file_.relative_path, album)
            add_file_to_zip(file_.file_path, album, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
