"""Import XML content of CBZ files into a Neo4j graph database."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING
from pathlib import Path
import xmltodict
from zipfile import ZipFile, BadZipFile
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET

from neo4j import GraphDatabase

if TYPE_CHECKING:
    from neo4j import Driver, Session


BD_ROOT = Path(r"\\quirinalis\bagarre\Bouquins\Bédés")

URI = os.getenv("NEO4J_URI")


def connect_to_db() -> Driver:
    return GraphDatabase.driver(URI, auth=("neo4j", PASSWORD))


def get_info_from_cbz(path: Path) -> dict:
    try:
        with ZipFile(path, "r") as zip_:
            with zip_.open("ComicInfo.xml") as xml_file:
                tree = ET.parse(xml_file)
    except BadZipFile:
        print(f"Could not open {path}")
        return {"Title": ""}
    else:
        root = tree.getroot()
        return xmltodict.parse(ET.tostring(root))["ComicInfo"]


def generate_unit_of_work(tx: Session, path: Path, info: dict):
    query = "MERGE (x:BD2 {path: $path}) SET x += $info"
    info.pop("Pages", None)
    print(info)
    print(query)
    result = tx.run(query, path=str(path), info=info)
    return result


def push_to_db(driver: Driver, path: Path) -> None:
    info = get_info_from_cbz(path)
    print(f"Pushing {path} to DB")

    with driver.session() as session:
        session.execute_write(
            generate_unit_of_work,
            path=path,
            info=info,
        )


def main() -> None:
    with connect_to_db() as driver, ThreadPoolExecutor(max_workers=1) as executor:
        for path in BD_ROOT.rglob("*.cbz"):
            push_to_db(driver, path)
        #     executor.submit(push_to_db, driver, path)


if __name__ == "__main__":
    main()
