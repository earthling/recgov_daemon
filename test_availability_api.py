import datetime as dt
import logging
import typing
import unittest
from typing import Dict

from dateutil.relativedelta import relativedelta
from dateutil.rrule import *

from ridb_interface import OnlineAvailabilityProvider, OfflineAvailabilityProvider


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


class AvailabilityApiTest(unittest.TestCase):

    def test_fetch_availability_data(self):
        logging.basicConfig(level=logging.DEBUG)
        # Check availability for Meeks Bay:
        availability = OnlineAvailabilityProvider().get_availability("232876", dt.datetime.now())
        for date_key, sites in availability.items():
            site_ids = [site["site"] for site in sites]
            print(f"{date_key} = {site_ids}")
        self.assertEqual(True, True)  # add assertion here


class SearchAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OfflineAvailabilityProvider("availability-09.json", "availability-10.json")
        self.availability = self.provider.get_availability("232876", dt.datetime.now())
        self.print_by_date()

    def print_by_date(self):
        by_date = index_by_date(self.availability)
        keys = sorted(list(by_date.keys()))
        print("")
        for key in keys:
            sites = by_date[key]
            print("%s = %s" % (dt.datetime.strftime(key, "%Y-%m-%d %a"), sorted(sites)))

    def test_search_no_availability(self):
        matches = search(self.availability, ExactDateSearch(sept(24)))
        self.assertEqual(0, len(matches), "No matches expected")

    def test_search_specific_dates_available(self):
        matches = search(self.availability, ExactDateSearch(sept(20), sept(21)))
        self.assertEqual(2, len(matches))

    def test_search_consecutive_dates(self):
        matches = search(self.availability, ConsecutiveDateSearch(sept(25), sept(26)))
        self.assertEqual(2, len(matches))

    def test_search_no_dates_in_same_campsite(self):
        matches = search(self.availability, ConsecutiveDateSearch(sept(9), sept(10)))
        self.assertEqual(0, len(matches))

    def test_search_for_stays(self):
        stays = Stay(ConsecutiveDateSearch(sept(25), sept(26)),
                     ConsecutiveDateSearch(oct(9), oct(10)))
        matches = search(self.availability, stays)
        self.assertEqual(4, len(matches))

    def test_search_for_weekends(self):
        stays = Criteria.days_of_week(FR, SA)
        matches = search(self.availability, stays)
        self.assertEqual(0, len(matches))

    def test_search_midweek(self):
        stays = Criteria.days_of_week(SU, MO, start_date=dt.date(2022, 9, 9))
        matches = search(self.availability, stays)
        self.assertEqual(6, len(matches))

    def test_search_midweek_two_campsites(self):
        # Only one site available on Sunday, 10-09
        stays = Criteria.days_of_week(SU, MO, start_date=dt.date(2022, 9, 9), num_sites=2)
        matches = search(self.availability, stays)
        self.assertEqual(4, len(matches))

    def test_search_for_consecutive_days(self):
        nights = MinimumStayLength(3)
        matches = search(self.availability, nights)
        self.assertEqual(19, len(matches))

    def test_search_for_consecutive_days_with_multiple_campsites(self):
        nights = MinimumStayLength(3, num_sites=2)
        matches = search(self.availability, nights)
        self.assertEqual(14, len(matches))

    def test_search_for_maximum_stay(self):
        maximum = MaximumStayLength()
        matches = search(self.availability, maximum)
        self.assertEqual(5, len(matches))

    def test_search_for_maximum_stay_multiple_campsites(self):
        maximum = MaximumStayLength(num_sites=3)
        matches = search(self.availability, maximum)
        self.assertEqual(4, len(matches))


def sept(date: int):
    return dt.date(2022, 9, date)


# noinspection PyShadowingBuiltins
def oct(date: int):
    return dt.date(2022, 10, date)


if __name__ == '__main__':
    unittest.main()
