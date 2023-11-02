"""Scraper for Bedetheque.com"""
from __future__ import annotations

import logging
import re
from dataclasses import InitVar, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, TypedDict

import requests
import xmlschema
import xmltodict
from bs4 import BeautifulSoup

XML_SCHEMA = xmlschema.XMLSchema(Path("ComicInfo_v2.0.xsd"))


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    """Get the soup of a page"""
    page = session.get(url)
    session.cookies.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Host": "www.bedetheque.com",
            "Referer": "https://www.bedetheque.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:108.0) Gecko/20100101 Firefox/108.0",
        }
    )
    return BeautifulSoup(page.content, "html.parser")


def get_csrf_token(session: requests.Session) -> str:
    """Get the CSRF token"""
    if "csrf_cookie_bel" not in session.cookies:
        session.get("https://www.bedetheque.com/")

    return session.cookies["csrf_cookie_bel"]


@dataclass
class Serie:
    """Serie class"""

    title: str
    url: str


def remove_accents(raw_text: str) -> str:
    for pattern, replacement in [
        ("[àáâãäåÀÁÂÄÅÃ]", "a"),
        ("[èéêëÉÈÊË]", "e"),
        ("[çÇ]", "c"),
        ("[ìíîïÍÌÎÏ]", "i"),
        ("[òóôõöÓÒÔÖÕ]", "o"),
        ("[ùúûüÚÙÛÜ]", "u"),
        ("[œŒ]", "oe"),
    ]:
        raw_text = re.sub(pattern, replacement, raw_text)
    return raw_text


PREFIXES = [
    "Les Aventures De",
    "Les Aventures D'",
    "Les Nouvelles Aventures De",
    "Les Nouvelles Aventures D'",
    "Une Aventure De",
    "Une Aventure D'",
]
PREFIX_PATTERN = re.compile(f"^({'|'.join(PREFIXES)})\s", re.IGNORECASE)
DETERMINERS = [
    "Le",
    "La",
    "Les",
    "L'",
    "Un",
    "Une",
    "Des",
    "Du",
    "De",
    "D'",
    "The",
    "A",
    "An",
]
DETERMINER_PATTERN = re.compile(f"^({'|'.join(DETERMINERS)})\s", re.IGNORECASE)


def revert_determiner(raw_text: str) -> str:
    prefix = None

    if match := PREFIX_PATTERN.match(raw_text):
        prefix = match.group(1)
    elif match := DETERMINER_PATTERN.match(raw_text):
        prefix = match.group(1)

    if prefix:
        return f"""{raw_text.removeprefix(
            prefix
        ).strip()
        } ({prefix.removesuffix(' ')})"""
    else:
        return raw_text


def sanitize_series_name(series_name: str) -> str:
    series_name = revert_determiner(series_name)

    if " " in series_name:
        series_to_find = series_name.split(" ")[0]
    else:
        series_to_find = series_name

    series_to_find = remove_accents(series_to_find)
    return series_to_find


def search_for_series(series_name: str, session: requests.Session) -> Serie | None:
    series_to_find = sanitize_series_name(series_name)
    series = search_for_title(series_to_find, session)

    if found := next(
        (x for x in series if x.title.lower() == series_name.lower()), None
    ):
        return found

    logging.warning("No serie found for %s", series_name)
    if series:
        logging.info("Found those series")
        for index, serie in enumerate(series, start=1):
            logging.info("%d: %s", index, serie.title)
        logging.info("%d: other", index + 1)
    else:
        index = 0
        logging.info("No series found")
        logging.info("%d: enter a name", index + 1)

    logging.info("%d: quit", index + 2)

    choice = input("Choose a number")
    if not choice.isdigit():
        return None

    choice_ = int(choice)
    if choice_ == index + 1:
        series_name = input("Enter a name")
        return search_for_series(series_name, session)
    elif choice_ == index + 2:
        return None
    else:
        return series[choice_ - 1]


class SerieResult(TypedDict):
    id: str
    label: str
    value: str
    desc: str


[
    {
        "id": "74809",
        "label": "Canardo (Uma investiga\u00e7\u00e3o do inspector)",
        "value": "Canardo (Uma investiga\u00e7\u00e3o do inspector)",
        "desc": "skin\/flags\/Portugal.png",
    },
    {
        "id": "401",
        "label": "Canardo (Une enqu\u00eate de l'inspecteur)",
        "value": "Canardo (Une enqu\u00eate de l'inspecteur)",
        "desc": "skin\/flags\/France.png",
    },
]


def search_for_title(title: str, session: requests.Session) -> list[Serie]:
    """Search for a title on Bedetheque.com"""

    url = f"https://online.bdgest.com/ajax/series?term={title}"
    content: list[SerieResult] = session.get(url).json()
    if not content:
        return []
    else:
        return [
            Serie(
                title=x["label"],
                url=f"https://www.bedetheque.com//serie/index/s/{x['id']}",
            )
            for x in content
        ]


def get_albums(serie: Serie, session: requests.Session) -> list[Album]:
    """Get the albums of a serie"""
    soup = get_soup(serie.url, session)

    genre = ""
    if genre_block := soup.find("ul", class_="serie-info"):
        for line in genre_block.find_all("li"):
            if (label := line.find("label")) and label.text.strip() == "Genre :":
                genre = line.find("span").text.strip()
                break

    if albums := soup.find("div", class_="tab_content_liste_albums"):
        return [
            Album(
                title=x.find("a").text.strip(),
                url=x.find("a")["href"],
                number=x.find("label").text.strip().removesuffix("."),
                series=serie.title,
                genre=genre,
            )
            for x in albums.find_all("li")
        ]
    else:
        if not (block := soup.find("div", class_="album-main")):
            raise ValueError("No album found")

        if not (block_title := block.find("a", class_="titre")):
            raise ValueError("No title found")

        return [
            Album(
                title=block_title["title"],
                url=block_title["href"],
                series=serie.title,
                genre=genre,
            )
        ]


def get_author_info_from_block(block: BeautifulSoup, role: str) -> Author | None:
    found_name = block.text.strip().removeprefix(role).strip("\r\n ")
    url = block.find("a")["href"]

    if found_name in {"<N&B>", "<Quadrichromie>"}:
        return None
    else:
        return Author(found_name=found_name, url=url)


def get_authors(content: BeautifulSoup, role: str) -> list[Author]:
    """Get the authors of a serie"""
    authors: list[Author] = []
    if block := next(
        (x for x in content.find_all("li") if x.find("label").text == role), None
    ):
        if author := get_author_info_from_block(block, role):
            authors.append(author)

        while (
            (next_block := block.find_next_sibling("li"))
            and next_block.find("label")
            and not next_block.find("label").text.strip()
        ):
            if author := get_author_info_from_block(next_block, role):
                authors.append(author)
            block = next_block

    return authors


@dataclass
class Author:
    found_name: InitVar[str]
    url: str

    name: str = field(init=False)
    first_name: str = field(init=False, default="")
    last_name: str = field(init=False, default="")

    def __post_init__(self, found_name: str) -> None:
        """Post init"""
        if ", " in found_name:
            self.last_name, self.first_name = found_name.split(", ")
            self.name = f"{self.first_name} {self.last_name}"
        else:
            self.name = found_name


DEPOT_LEGAL_BLOCK_PATTERN = re.compile(
    r"Dépot légal : (?P<month>\d\d)\/(?P<year>\d\d\d\d)"
)
RELEASE_DATE_PATTERN = re.compile(
    r"\(Parution le (?P<day>\d+)/(?P<month>\d+)/(?P<year>\d+)\)"
)


def get_album_info(album: Album, session: requests.Session) -> Album | None:
    """Get the album"""
    soup = get_soup(album.url, session)

    if not (content := soup.find("div", class_="tab_content_liste_albums")):
        return None
    infos = content.find_all("li")

    for info in infos:
        if not (block := info.find("label")):
            continue

        match block.text.strip():
            case "Titre :" as key:
                album.title = info.text.removeprefix(key).strip()
            case "Tome :" as key:
                album.number = info.text.removeprefix(key).strip()
            case "Scénario :" as key:
                album.writers = get_authors(content, key)
                album.writer = ", ".join([x.name for x in album.writers])
            case "Dessin :" as key:
                album.pencillers = get_authors(content, key)
                album.penciller = ", ".join([x.name for x in album.pencillers])
            case "Couleurs :" as key:
                album.colorists = get_authors(content, key)
                album.colorist = ", ".join([x.name for x in album.colorists])
            case "Editeur :" as key:
                album.publisher = info.text.removeprefix(key).strip()
            case "Format :" as key:
                album.format = info.text.removeprefix(key).strip()
            case "Dépot légal :" as key:
                album.get_release_date(info)
            case "EAN/ISBN :" as key:
                album.isbn = info.text.removeprefix(key).strip()
            case "Collection :" as key:
                album.collection = info.text.removeprefix(key).strip()

    if rating_box := soup.find("div", class_="etoiles"):
        if rating := rating_box.find("span", itemprop="ratingValue"):
            album.community_rating = float(rating.text.strip())

    if description_box := soup.find("span", itemprop="description"):
        album.summary = description_box.text.strip()

    if album.format == "Format Manga":
        album.manga = "Yes"

    return album


class ToDictMixin:
    def to_dict(self) -> dict[str, Any]:
        """Convert the Album object to a dict"""
        result: dict[str, Any] = {}
        for field_ in fields(self):
            snakecase_name = field_.name
            if not (camelcase_name := field_.metadata.get("camelcase")):
                camelcase_name = to_camelcase(field_.name)

            if "not_included" in field_.metadata:
                continue

            value = getattr(self, snakecase_name)
            if isinstance(value, list):
                result[camelcase_name] = [x.to_dict() for x in value]
            else:
                result[camelcase_name] = value

        return result


@dataclass
class Album(ToDictMixin):
    """Album class"""

    url: str = field(metadata={"not_included": True})

    title: str = ""
    series: str = ""
    number: str = ""

    count: int = -1
    volume: int = -1
    alternate_series: str = ""
    alternate_number: str = ""
    alternate_count: int = -1
    summary: str = ""
    notes: str = ""
    year: int = -1
    month: int = -1
    day: int = -1
    writers: list[Author] = field(default_factory=list, metadata={"not_included": True})
    pencillers: list[Author] = field(
        default_factory=list, metadata={"not_included": True}
    )
    inkers: list[Author] = field(default_factory=list, metadata={"not_included": True})
    colorists: list[Author] = field(
        default_factory=list, metadata={"not_included": True}
    )
    letterers: list[Author] = field(
        default_factory=list, metadata={"not_included": True}
    )
    cover_artists: list[Author] = field(
        default_factory=list, metadata={"not_included": True}
    )
    editors: list[Author] = field(default_factory=list, metadata={"not_included": True})
    writer: str = field(init=False, default="")
    penciller: str = field(init=False, default="")
    inker: str = field(init=False, default="")
    colorist: str = field(init=False, default="")
    letterer: str = field(init=False, default="")
    cover_artist: str = field(init=False, default="")
    editor: str = field(init=False, default="")
    publisher: str = ""
    imprint: str = ""
    genre: str = ""
    web: str = field(init=False, default="")
    page_count: int = 0
    language_iso: str = field(default="FR", metadata={"camelcase": "LanguageISO"})
    format: str = ""
    black_and_white: Literal["Yes", "No", "Unknown"] = "Unknown"
    manga: Literal["Yes", "No", "Unknown", "YesAndRightToLeft"] = "Unknown"
    characters: str = ""
    teams: str = ""
    locations: str = ""
    scan_information: str = ""
    story_arc: str = ""
    series_group: str = ""
    age_rating: Literal[
        "Unknown",
        "Adults Only 18+",
        "Early Childhood",
        "Everyone",
        "Everyone 10+",
        "G",
        "Kids to Adults",
        "M",
        "MA15+",
        "Mature 17+",
        "PG",
        "R18+",
        "Rating Pending",
        "Teen",
        "X18+",
    ] = "Unknown"
    pages: list[Page] = field(default_factory=list)
    community_rating: float = 0.0
    main_character_or_team: str = ""
    review: str = ""

    isbn: str = field(init=False, default="", metadata={"not_included": True})
    barcode: str = field(init=False, default="", metadata={"not_included": True})

    def __post_init__(self) -> None:
        self.web = self.url

    def __repr__(self) -> str:
        return f"{self.title} #{self.number} in {self.series}"

    def get_release_date(self, info: BeautifulSoup):
        """Get the release date of an album"""

        if (block := info.find("span")) and (
            match := RELEASE_DATE_PATTERN.match(block.text.strip())
        ):
            self.day = int(match.group("day"))
            self.month = int(match.group("month"))
            self.year = int(match.group("year"))
        elif match := DEPOT_LEGAL_BLOCK_PATTERN.match(info.text.strip()):
            self.month = int(match.group("month"))
            self.year = int(match.group("year"))

    def to_xml(self) -> str:
        """Convert the album to XML"""
        dict_ = {"ComicInfo": self.to_dict()}
        xml_content = xmltodict.unparse(dict_, pretty=True)

        XML_SCHEMA.validate(xml_content)

        return xml_content


def to_camelcase(string: str) -> str:
    """Convert a string to camelcase"""
    return "".join(x.capitalize() or "_" for x in string.split("_"))


@dataclass
class Page(ToDictMixin):
    image: int
    type: Literal[
        "FrontCover",
        "InnerCover",
        "Roundup",
        "Story",
        "Advertisement",
        "Editorial",
        "Letters",
        "Preview",
        "BackCover",
        "Other",
        "Deleted",
    ] = "Story"
    double_page: bool = False
    image_size: int = 0
    key: str = ""
    bookmark: str = ""
    image_width: int = -1
    image_height: int = -1


def scrape(title: str, numbers: list[str] | None = None) -> list[Album]:
    infos: list[Album] = []
    with requests.Session() as session:
        series = search_for_series(title, session)
        if not series:
            logging.error("No series found")
            return []

        albums = get_albums(series, session)
        logging.info(albums)

        if numbers:
            albums = [x for x in albums if str(x.number).lower() in numbers]

        for album in albums:
            info = get_album_info(album, session)
            if not info:
                logging.error("No info found")
                continue
            infos.append(info)
            logging.info("Found info for %s", album)

            for field_ in fields(info):
                if field_.metadata.get("not_included"):
                    continue
                logging.debug("%s: %s", field_.name, getattr(info, field_.name))

    return infos
