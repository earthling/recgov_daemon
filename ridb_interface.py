"""
RIDB Interface

Coordinates talking with the recreation.gov database API (RIDB) with requests, parses response
as json to extract campsite names and facility IDs. See below links for details:

https://www.recreation.gov/use-our-data
https://ridb.recreation.gov/docs#/
"""
import datetime
import json
import logging
import os
from typing import Tuple, Dict
import datetime as dt
import requests

AVAILABILITY_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

logger = logging.getLogger(__name__)

# set in ~/.virtualenvs/recgov_daemon/bin/postactivate
API_KEY = os.environ.get("ridb_api_key")
RIDB_BASE_URL = "https://ridb.recreation.gov/api/v1/facilities"
RECDATA_ELEM = "RECDATA"
FACILITY_TYPE_FIELD = "FacilityTypeDescription"
FACILITY_ID_FIELD = "FacilityID"
FACILITY_NAME_FIELD = "FacilityName"


class AvailabilityProvider(object):
    def request_availability(self, facility_id: str, start_date: dt.date) -> Dict:
        pass

    def get_availability(self, facility_id: str, start_date: dt.date) -> Dict[str, Dict]:

        available_sites = dict()
        max_look_ahead_months = 3
        months_fetched = 0
        while start_date and months_fetched < max_look_ahead_months:
            data = self.request_availability(facility_id, start_date)
            months_fetched += 1

            campsites = data["campsites"]
            for site_id, site_data in campsites.items():
                # The _first_ entry in the list of sites seems to represent the
                # campground itself. The 'campsite_type' is 'MANAGER'. This entry
                # is interesting because it has a list of dates in a 'quantities'
                # field. I have observed that when this list does not contain the
                # last day of the month, there will be no availability information
                # after the last day of the quantities list.
                quantities = site_data["quantities"]
                if len(quantities) > 0:
                    start_date = extract_next_month(quantities)

                availability_data = site_data.pop("availabilities")
                availabilities = []
                for date, status in availability_data.items():
                    if status.lower() == "available":
                        available_date = datetime.datetime.strptime(date, AVAILABILITY_DATETIME_FORMAT)
                        availabilities.append(available_date.date())

                if len(availabilities) > 0:
                    site_data = available_sites.setdefault(site_id, site_data)
                    site_availabilities = site_data.setdefault("availabilities", set())
                    site_availabilities.update(availabilities)

        return available_sites


class OnlineAvailabilityProvider(AvailabilityProvider):
    def request_availability(self, facility_id: str, start_date: dt.date):
        # They will accept this user agent, but will not accept the python requests default
        headers = {
            "user-agent": "curl/7.68.0"
        }

        # The API is very picky about date formats, only the year and month are allowed to vary.
        query = {
            "start_date": dt.datetime.strftime(start_date, "%Y-%m-01T00:00:00.000Z")
        }

        url = "https://www.recreation.gov/api/camps/availability/campground/%s/month" % facility_id
        response = requests.get(url, headers=headers, params=query, timeout=60)
        if not response.ok:
            print(response.request.headers)
            raise ValueError("Unable to access RIDB API. Check connection and API key.")
        return response.json()


class OfflineAvailabilityProvider(AvailabilityProvider):
    def __init__(self, *args):
        self.response_files = list(args)
        self.response_files.reverse()

    def request_availability(self, facility_id: str, start_date: dt.date) -> Dict:
        response_file = self.response_files.pop()
        with open(response_file, "r") as data:
            return json.load(data)


def extract_next_month(quantities) -> dt.date:
    last_date = None
    for date, zero in quantities.items():
        last_date = date
    # 2022-09-10T00:00:00Z
    date = dt.datetime.strptime(last_date, AVAILABILITY_DATETIME_FORMAT)
    next_date = date + datetime.timedelta(days=1)
    return next_date.date() if date.month < next_date.month else None


def get_facilities_from_ridb(latitude: float, longitude: float, radius: int) -> [Tuple[str, str]]:
    """
    Calls RIDB API with a location and search radius, and returns campground names and RDIB
    facility ID strings.

    :param latitude: Latitude of coordinate to center the search around
    :param longitude: Longitude of coordinate to center the search around
    :param radius: Radius to search around
    :raises ValueError: if request to RIDB does not return 200 OK
    :raises KeyError: if can't find expected facility type/recdata element fields in resp json
    :returns: set of (name, facility_id) tuples
    """
    headers = {
        "accept": "application/json",
        "apikey": API_KEY
    }
    facilities_query = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "radius": str(radius),
        "FacilityTypeDescription": "Campground",
        # "Reservable": "True",
        # "lastupdated": "01-01-2021",
        "limit": 20
    }

    logger.debug("\tUse requests library to retrieve facilities from RIDB API")
    resp = requests.get(RIDB_BASE_URL, headers=headers, params=facilities_query, timeout=60)
    if not resp.ok:
        raise ValueError("Unable to access RIDB API. Check connection and API key.")
    try:
        res = [x for x in resp.json()[RECDATA_ELEM] if x[FACILITY_TYPE_FIELD] == "Campground"]
    except KeyError as err:
        err_msg = "No %s field in %s element. Check RIDB API specs."
        raise KeyError(err_msg.format(FACILITY_TYPE_FIELD, RECDATA_ELEM)) from err
    logger.info("Received %d results from RIDB, parsing campground info...", len(res))

    # Construct list of campground names/facility IDs from ridb response
    facilities = []
    for campsite in res:
        try:
            facility_id = str(campsite[FACILITY_ID_FIELD])
            name = " ".join(w.capitalize() for w in campsite[FACILITY_NAME_FIELD].split())
            facilities.append((name, facility_id))
        except KeyError as err:
            err_msg = "No %s or %s field in campground dict. Check RIDB API specs."
            raise KeyError(err_msg.format(FACILITY_ID_FIELD, FACILITY_NAME_FIELD)) from err
    logger.info("Parsed %d facilities from %d RIDB results", len(facilities), len(res))

    return facilities


def run():
    """
    Runs the RIDB interface module for specific values, should be used for debugging only.
    """
    # lat = 35.994431       # these are the coordinates for Ponderosa Campground
    # lon = -121.394325
    lat = 38.951209  # coordinates for Emerald Bay, Lake Tahoe
    lon = -120.106420
    radius = 10
    campgrounds = get_facilities_from_ridb(lat, lon, radius)
    print(campgrounds)


if __name__ == "__main__":
    run()
