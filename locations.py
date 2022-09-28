import logging
import os
import typing
from typing import Tuple

import requests

from campground import Campground
from ridb_interface import query_facilities, get_facility_name_for_id


def forward_geocode(city_and_state: str) -> Tuple[float, float]:
    url = "http://api.positionstack.com/v1/forward"
    query = {
        "access_key": os.environ["position_stack"],
        "query": city_and_state
    }
    response = requests.get(url, params=query)
    if not response.ok:
        raise ValueError("Error from geocoding API")
    data = response.json()["data"]
    # print(json.dumps(data, indent=2))
    if len(data) == 0:
        raise ValueError("No data for: %s" % city_and_state)

    location = data[0]
    if len(data) > 1:
        logging.warning("%s matches for %s, using first result from: %s",
                        len(data), city_and_state, location["region"])
    return float(location["latitude"]), float(location["longitude"])


def resolve_locations(locations: [str], radius_miles=50) -> typing.Set[Campground]:
    """
    Take a list of locations and turn it into a set of unique campground ids

    :param locations: Each location can be a "City, State", a "Campground Name" or "<lat>,<lon>"
    :param radius_miles: For city or coordinates, search for campgrounds within this distance
    :return: Set of unique campground identifiers
    """
    campgrounds = set()
    for location in locations:
        if "," in location:
            parts = location.split(",", maxsplit=1)
            try:
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                logging.info("Looking up coordinates for: %s", location)
                lat, lon = forward_geocode(location)
            facilities = query_facilities(latitude=lat, longitude=lon, radius=radius_miles)
            campgrounds.update(facilities)
        else:
            try:
                facility_id = int(location)
                facility_name = get_facility_name_for_id(facility_id)
                campgrounds.add(Campground(facility_name, facility_id))
            except ValueError:
                # treat this as a campground name
                facilities = query_facilities(query=location)
                campgrounds.update(facilities)
    return campgrounds
