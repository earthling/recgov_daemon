import datetime as dt
import logging
import typing
from typing import Dict

from dateutil.relativedelta import relativedelta
from dateutil.rrule import *

from campground import Campground
from ridb_interface import OnlineAvailabilityProvider


class Availability(object):
    def __init__(self):
        self._provider = OnlineAvailabilityProvider()

    def search(self, campground: Campground, start_date: dt.date, num_nights: int, num_sites: int) -> bool:
        availability = self._provider.get_availability(campground.id, start_date)
        dates = search(availability, MinimumStayLength(num_nights, num_sites=num_sites))
        if logging.getLogger().isEnabledFor(logging.INFO):
            formatted = [dt.datetime.strftime(date, "%Y-%m-%d") for date in dates]
            logging.info("%s has dates: %s", campground.name, formatted)
        return len(dates) > 0


class Criteria(object):
    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        return False

    def matches(self, site_availability: typing.Dict) -> Dict:
        return {}

    @staticmethod
    def days_of_week(*nights_to_stay: [int], start_date: dt.date = None,
                     look_ahead_months: int = 3,
                     num_sites: int = 0):
        if start_date is None:
            start_date = dt.date.today()

        end_date = start_date + relativedelta(months=look_ahead_months)
        end_date = dt.datetime(end_date.year, end_date.month, end_date.day)

        stays = []
        dates = iter(rrule(WEEKLY, byweekday=nights_to_stay, until=end_date))
        try:
            while True:
                stay = []
                for _ in nights_to_stay:
                    date = next(dates)
                    stay.append(date.date())
                stays.append(ConsecutiveDateSearch(*stay, num_sites=num_sites))
        except StopIteration:
            pass

        return Stay(*stays)


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


class MinimumStayLength(Criteria):
    def __init__(self, nights: int, num_sites: int = 0):
        self._nights = nights
        self._num_sites = num_sites
        self._dates = []

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        if len(dates) >= self._nights:
            self._dates.append(dates)
        return True

    def matches(self, site_availability: typing.Dict) -> typing.Sequence[dt.date]:
        results = []
        if self._num_sites == 0:
            for span in self._dates:
                results.extend(span)
            return results

        for span in self._dates:
            if find_sites(span, site_availability, self._num_sites):
                results.extend(span)
        return results


class MaximumStayLength(Criteria):
    def __init__(self, num_sites: int = 0):
        self._max_nights = -1
        self._max_dates = []
        self._num_sites = num_sites

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


class ExactDateSearch(Criteria):
    def __init__(self, *dates: [dt.date]):
        self._desired_dates = set(dates)
        self._matches = []

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        matches = dates.intersection(self._desired_dates)
        if len(matches) > 0:
            self._matches.extend(matches)
        return True

    def matches(self, site_availability: typing.Dict) -> typing.Sequence[dt.date]:
        return self._matches


class ConsecutiveDateSearch(Criteria):
    def __init__(self, *dates: [dt.date], num_sites=0):
        self._dates = set(dates)
        self._matches = []
        self._num_sites = num_sites

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        if self._dates.issubset(dates):
            self._matches.extend(self._dates)
        return True

    def matches(self, site_availability: typing.Dict) -> typing.Sequence[dt.date]:
        if self._num_sites == 0 or len(self._matches) == 0:
            return self._matches

        if find_sites(self._matches, site_availability, self._num_sites):
            return self._matches
        return []


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

