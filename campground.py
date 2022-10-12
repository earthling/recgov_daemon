"""
campground.py

Class declarations for Campground and CampgroundList. Also contains misc functions for creating
and keeping track of campground data.
"""
from typing import NamedTuple

RECGOV_BASE_URL = "https://www.recreation.gov/camping/campgrounds"


class Campground(NamedTuple):
    name: str
    id: int

    @property
    def url(self):
        # recreation.gov URL for campground
        return f"{RECGOV_BASE_URL}/{self.id}"
