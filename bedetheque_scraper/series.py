from __future__ import annotations

import time
from dataclasses import dataclass
import random
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile
from bs4 import BeautifulSoup
import requests
import os
import re
import json
from typing import NotRequired, TypedDict

BD_ROOT = Path("\\\\quirinalis\\bagarre\\Bouquins\\Bédés")

os.environ["ALL_PROXY"] = "socks5://localhost:3333"


LINKED_SERIES: dict[str, Series] = {}


SERIES_URL_PATTERN = re.compile(r"https://www.bedetheque.com/serie-(\d+)-(.+).html")


class Series(TypedDict):
    id: str
    name: str
    linked_series: list[str]
    unlinked: NotRequired[bool]


def get_url_from_book(path: Path) -> str | None:
    try:
        with ZipFile(path, "r") as zip_:
            with zip_.open("ComicInfo.xml") as xml_file:
                tree = ET.parse(xml_file)
    except BadZipFile:
        print(f"Could not open {path}")
        return None
    else:
        root = tree.getroot()
        if (web_block := root.find("Web")) is None:
            return None
        else:
            return web_block.text


def scrape_info_from_url(url: str) -> tuple[str, str, list[str]] | None:

    page = requests.get(url)
    if "Votre IP a ete bloquee" in str(content := page.content):
        raise RuntimeError("IP blocked")

    time.sleep(5 + 0.001 * random.randint(0, 1000))
    soup = BeautifulSoup(page.content, "html.parser")
    if (title_block := soup.find("h1")) is None:
        print(f"Could not find title block for {url}")
        return None

    if (series_url := title_block.find("a").get("href")) is None:
        print(f"Could not find series URL for {url}")
        return None

    if not (
        series_url.startswith("https://www.bedetheque.com/")
        or series_url.startswith("http://www.bedetheque.com/")
    ):
        return None

    series_page = requests.get(series_url)
    series_soup = BeautifulSoup(series_page.content, "html.parser")
    if not (
        series_liees_block := next(
            (
                x
                for x in series_soup.find_all("div")
                if "serie-liee" in x.get("class", [])
            ),
            [],
        )
    ):
        return None

    series_id = SERIES_URL_PATTERN.match(series_url).group(1)
    linked_series = []

    for serie_liee in series_liees_block.find_all("li"):
        if (serie_liee_url := serie_liee.find("a").get("href")) is None:
            continue

        serie_liee_id = SERIES_URL_PATTERN.match(serie_liee_url).group(1)
        linked_series.append(serie_liee_id)

    return series_id, title_block.text.strip(), linked_series


def encode_json(obj):
    if isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, set):
        return list(obj)
    else:
        return obj


def main():
    global LINKED_SERIES
    if (linked_series_file := Path("linked_series.json")).exists():
        LINKED_SERIES = json.load(linked_series_file.open())

    if (treated_folders_file := Path("treated_folders.json")).exists():
        treated_folders = set(Path(x) for x in json.load(treated_folders_file.open()))
    else:
        treated_folders = set()

    for zip_file in BD_ROOT.rglob("*.cbz"):
        if zip_file.parent in treated_folders:
            continue

        # if not "Incal" in str(zip_file):
        #     continue

        print(zip_file)
        if url := get_url_from_book(zip_file):
            if url.startswith("https://www.bedetheque.com/") or url.startswith(
                "http://www.bedetheque.com/"
            ):
                if info := scrape_info_from_url(url):
                    series_id, title, linked_series = info
                    if series_id in LINKED_SERIES:
                        LINKED_SERIES[series_id]["linked_series"].extend(linked_series)
                    else:
                        LINKED_SERIES[series_id] = Series(
                            id=series_id, name=title, linked_series=linked_series
                        )

        json.dump(
            LINKED_SERIES, linked_series_file.open("w"), indent=4, default=encode_json
        )

        treated_folders.add(zip_file.parent)
        json.dump(
            treated_folders,
            treated_folders_file.open("w"),
            indent=4,
            default=encode_json,
        )


if __name__ == "__main__":
    main()
