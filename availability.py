import datetime as dt
import logging
import typing
# noinspection PyProtectedMember
from calendar import MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY
from parser import ParserError
from typing import Dict

from dateutil.parser import parse

from campground import Campground
from ridb_interface import OnlineAvailabilityProvider


class Criteria(object):
    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        return False

    def matches(self, site_availability: typing.Dict) -> Dict:
        return {}

    def reset(self) -> None:
        pass


class Availability(object):
    def __init__(self):
        self._provider = OnlineAvailabilityProvider()

    def search(self, campground: Campground, criteria: Criteria) -> bool:
        availability = self._provider.get_availability(campground.id, dt.date.today())
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            available_dates = index_by_date(availability)
            formatted = [dt.datetime.strftime(date, "%Y-%m-%d %a") for date in available_dates]
            logging.info("%s has dates: %s", campground.name, formatted)
        dates = search(availability, criteria)
        if logging.getLogger().isEnabledFor(logging.INFO):
            formatted = [dt.datetime.strftime(date, "%Y-%m-%d %a") for date in dates]
            logging.info("%s has dates that meet criteria: %s", campground.name, formatted)
        return len(dates) > 0


class Stay(Criteria):
    def __init__(self, *criteria: [Criteria]):
        self.criteria = criteria

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        for criteria in self.criteria:
            criteria.test(site_id, dates)
        return True

    def matches(self, site_availability: typing.Dict) -> typing.Sequence[dt.date]:
        result = []
        for criteria in self.criteria:
            result.extend(criteria.matches(site_availability))
        return result

    def reset(self) -> None:
        for criteria in self.criteria:
            criteria.reset()


class MinimumStayLength(Criteria):
    def __init__(self, nights: int, num_sites: int = 0, first_night: dt.date = None, first_week_day: int = -1):
        if first_night and first_week_day != -1:
            raise ValueError("Cannot set first_night and first_week_day together")

        self._nights = nights
        self._num_sites = num_sites
        self._first_night = first_night
        self._first_week_day = int(first_week_day)
        self._matches = []

    def reset(self):
        self._matches.clear()

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        if self._first_night:
            if self._first_night not in dates:
                return True
            else:
                ordered = sorted(list(dates))
                first_index = ordered.index(self._first_night)
                dates = ordered[first_index:]
        elif self._first_week_day != -1:
            first_index = 0
            found = False
            ordered = sorted(list(dates))
            for d in ordered:
                if d.weekday() == self._first_week_day:
                    found = True
                    break
                first_index += 1
            if found:
                dates = ordered[first_index:first_index + self._nights]
            else:
                return True

        if len(dates) >= self._nights:
            self._matches.append(dates)
        return True

    def matches(self, site_availability: typing.Dict) -> typing.Sequence[dt.date]:
        results = []
        if self._num_sites == 0:
            for span in self._matches:
                results.extend(span)
            return results

        for span in self._matches:
            if find_sites(span, site_availability, self._num_sites):
                results.extend(span)
        return results


class MaximumStayLength(Criteria):
    def __init__(self, num_sites: int = 0):
        self._max_nights = -1
        self._max_dates = []
        self._num_sites = num_sites

    def reset(self) -> None:
        self._max_nights = -1
        self._max_dates.clear()

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        if len(dates) > self._max_nights:
            self._max_nights = len(dates)
            self._max_dates = dates
        return True

    def matches(self, site_availability: typing.Dict) -> typing.Sequence[dt.date]:
        if self._num_sites == 0 or len(self._max_dates) == 0:
            return self._max_dates

        max_dates = sorted(list(self._max_dates))
        if find_sites(max_dates, site_availability, self._num_sites):
            return max_dates

        num_max_stays_for_sites = -1
        max_stays_for_sites = None
        for i in range(1, len(max_dates)):
            dates = max_dates[i:]
            if find_sites(dates, site_availability, self._num_sites):
                if len(dates) > num_max_stays_for_sites:
                    num_max_stays_for_sites = len(dates)
                    max_stays_for_sites = dates
        return max_stays_for_sites


def find_sites(dates: [dt.date], availability: typing.Dict, num_sites: int):
    sites = None
    for d in dates:
        sites_available = set(availability[d])
        if sites is None:
            sites = sites_available
        else:
            sites.intersection_update(sites_available)
        if len(sites) < num_sites:
            print("Not enough sites available.")
            return False
    return True


def search(availability: Dict, criteria: Criteria) -> typing.Sequence[dt.date]:
    criteria.reset()
    available_dates = index_by_date(availability)
    dates = list(available_dates.keys())
    spans = consecutive(dates)
    for start, end in spans:
        criteria.test("dummy", set(dates[start:end]))

    return criteria.matches(available_dates)


def index_by_date(availability):
    available_dates = dict()
    for site_id, site_data in availability.items():
        availabilities = site_data["availabilities"]
        for d in availabilities:
            sites = available_dates.setdefault(d, [])
            sites.append(site_id)
    return available_dates


def consecutive(dates: typing.List[dt.date]) -> [typing.Tuple]:
    runs = []
    dates.sort()
    previous = None
    start = 0
    end = 0
    current = 0
    for d in dates:
        if previous is None:
            previous = d
            current += 1
            continue

        span = d - previous
        previous = d
        if span.days > 1:
            # not consecutive
            runs.append((start, end + 1))
            start = current
        else:
            end = current
        current += 1
    runs.append((start, end + 1))
    return runs


DAYS_OF_WEEK = {"MO": MONDAY, "TU": TUESDAY, "WE": WEDNESDAY, "TH": THURSDAY,
                "FR": FRIDAY, "SA": SATURDAY, "SU": SUNDAY}


def parse_search_options(dates: typing.List[str], num_nights: int = 1, num_sites: int = 1) -> Criteria:
    if len(dates) == 0:
        if num_nights == 0:
            raise ValueError("No dates given and no nights requested.")
        return MinimumStayLength(num_nights, num_sites=num_sites)

    stays = []
    for date in dates:
        if date == "max":
            return MaximumStayLength(num_sites=num_sites)

        if date.upper() in DAYS_OF_WEEK:
            day = DAYS_OF_WEEK[date.upper()]
            stays.append(MinimumStayLength(num_nights, num_sites=num_sites, first_week_day=day))
            continue

        try:
            parsed = parse(date).date()
            criteria = MinimumStayLength(num_nights, num_sites=num_sites, first_night=parsed)
            stays.append(criteria)
        except ParserError:
            raise ValueError("Could not parse: %s" % date)

    if len(stays) > 0:
        return Stay(*stays)
