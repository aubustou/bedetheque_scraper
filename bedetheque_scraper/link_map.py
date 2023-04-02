from __future__ import annotations

import os
import logging

from pathlib import Path
import json
from bedetheque_scraper.series import Series as SeriesDict
from bedetheque_scraper.graph_db import connect_to_db
from typing import TypedDict


from neomodel import (
    config,
    StructuredNode,
    StringProperty,
    IntegerProperty,
    UniqueIdProperty,
    RelationshipTo,
)
from neomodel import config
from neomodel import db


config.DATABASE_URL = os.getenv("NEO4J_URI")

linked_series_file = Path("linked_series.json")


class Series(StructuredNode):
    """A series of comic books."""

    id = StringProperty(unique_index=True)
    series_id = IntegerProperty(unique_index=True)
    name = StringProperty()

    # Create relationship to other series
    linked_series = RelationshipTo("Series", "LINKED_TO")
    series_group = RelationshipTo("SeriesGroup", "BELONGS_TO")

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{self.name} ({self.__class__.__name__})"

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)


class SeriesGroup(StructuredNode):
    """A group of series that are linked together."""

    name = StringProperty()

    series = RelationshipTo("Series", "CONTAINS")


class SeriesMap(TypedDict):
    series: list[SeriesDict]
    ids: list[str]


def clean_list(series: list[str]) -> list[str]:
    return sorted(set(series))


def get_series_map(linked_series: dict[str, SeriesDict]) -> None:
    """Cluster the series by their links.

    {
    "uuid4": {
        "series": [{Series}, {Series}, ...],
        "ids": [str, str, ...],
    }
    """
    series_map = list(linked_series.values())
    for serie in series_map:
        serie["series_id"] = int(serie["id"])
    series = Series.create_or_update(*series_map)

    for db_serie in series:
        with db.transaction:
            for link in linked_series[str(db_serie.series_id)]["linked_series"]:
                try:
                    db_serie.linked_series.connect(Series.nodes.get(series_id=link))
                except Series.DoesNotExist:
                    print(f"Could not find {link} in database")

    print(series)


def create_series_groups() -> None:
    """Create the series groups."""
    for series in Series.nodes.all():
        if groups := series.series_group.all():
            series_group = groups[0]
        else:
            series_group = SeriesGroup(name=series.name).save()
        with db.transaction:
            recurse_connect_to_series_group(series, series_group)


def get_series_groups() -> list[SeriesGroup]:
    """Get the series groups."""
    return SeriesGroup.nodes.all()


def recurse_connect_to_series_group(series: Series, series_group: SeriesGroup) -> None:
    """Recursively connect a series to a series group."""
    if series.series_group.is_connected(series_group):
        return

    series.series_group.connect(series_group)
    for linked_serie in series.linked_series.all():
        recurse_connect_to_series_group(linked_serie, series_group)


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    linked_series: dict[str, SeriesDict] = json.load(linked_series_file.open())

    # Create the series group
    # create_series_groups()

    # print(linked_series)

    # series_map = get_series_map(linked_series)

    # print(series_map)


if __name__ == "__main__":
    main()
