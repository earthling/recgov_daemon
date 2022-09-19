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

    def matches(self) -> Dict:
        return {}

    @staticmethod
    def days_of_week(*nights_to_stay: [int], start_date: dt.date = None, look_ahead_months: int = 3):
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
                stays.append(DatesInSameCampsite(*stay))
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

    def matches(self) -> Dict:
        matches = {}
        for criteria in self.criteria:
            m = criteria.matches()
            for date_key, site_ids in m.items():
                sites = matches.setdefault(date_key, set())
                for site_id in site_ids:
                    sites.add(site_id)
        return matches


class MinimumStayLength(Criteria):
    def __init__(self, nights: int):
        self._nights = nights
        self._sites = {}

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        dates = list(dates)
        spans = consecutive(dates)
        for span in spans:
            start, end = span
            if end - start >= self._nights:
                runs = self._sites.setdefault(site_id, [])
                runs.append(dates[start:end])
        return True

    def matches(self) -> Dict:
        return self._sites


class MaximumStayLength(Criteria):

    def __init__(self):
        self._sites = {}
        self._max_nights = -1
        self._max_site = None
        self._max_dates = None

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        dates = list(dates)
        spans = consecutive(dates)
        for span in spans:
            start, end = span
            if end - start > self._max_nights:
                self._max_nights = end - start
                self._max_dates = dates[start:end]
                self._max_site = site_id
        return True

    def matches(self) -> Dict:
        if self._max_site is None:
            return dict()

        return {self._max_site: self._max_dates}


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


class ExactDateSearch(Criteria):
    def __init__(self, *dates: [dt.date]):
        self._dates = set(dates)
        self._matches = dict()

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        matches = dates.intersection(self._dates)
        if len(matches) > 0:
            self._matches[site_id] = matches
        return True

    def matches(self) -> Dict:
        return self._matches


class DatesInSameCampsite(Criteria):
    def __init__(self, *dates: [dt.date]):
        self._dates = set(dates)
        self._matches = dict()

    def test(self, site_id: str, dates: typing.Set[dt.date]) -> bool:
        if self._dates.issubset(dates):
            self._matches[site_id] = self._dates
        return True

    def matches(self) -> Dict:
        return self._matches


def search(availability: Dict, criteria: Criteria) -> Dict:
    for site_id, site_data in availability.items():
        available_dates = site_data["availabilities"]
        if not criteria.test(site_id, available_dates):
            break
    return criteria.matches()


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
        # self.print_by_date()

    def print_by_date(self):
        by_date = dict()
        for site_id, site_data in self.availability.items():
            dates = site_data["availabilities"]
            for d in dates:
                sites = by_date.setdefault(d, [])
                sites.append(site_id)
        keys = sorted(list(by_date.keys()))
        for key in keys:
            sites = by_date[key]
            print("%s = %s" % (key.isoformat(), sites))

    def test_search_no_availability(self):
        matches = search(self.availability, ExactDateSearch(sept(24)))
        self.assertEqual(0, len(matches), "No matches expected")

    def test_search_specific_dates_available(self):
        matches = search(self.availability, ExactDateSearch(sept(20), sept(21)))
        self.assertEqual(20, len(matches))

    def test_search_dates_in_same_campsite(self):
        matches = search(self.availability, DatesInSameCampsite(sept(25), sept(26)))
        self.assertEqual(2, len(matches))

    def test_search_no_dates_in_same_campsite(self):
        matches = search(self.availability, DatesInSameCampsite(oct(9), oct(10)))
        self.assertEqual(0, len(matches))

    def test_search_for_stays(self):
        stays = Stay(DatesInSameCampsite(sept(25), sept(26)),
                     DatesInSameCampsite(oct(9), oct(10)))
        matches = search(self.availability, stays)
        self.assertEqual(2, len(matches))

    def test_search_for_weekends(self):
        stays = Criteria.days_of_week(FR, SA)
        matches = search(self.availability, stays)
        self.assertEqual(0, len(matches))

    def test_search_midweek(self):
        stays = Criteria.days_of_week(SU, MO)
        matches = search(self.availability, stays)
        self.assertEqual(20, len(matches))

    def test_search_for_consecutive_days(self):
        nights = MinimumStayLength(3)
        matches = search(self.availability, nights)
        self.assertTrue(len(matches) > 1)

    def test_search_for_maximum_stay(self):
        maximum = MaximumStayLength()
        matches = search(self.availability, maximum)
        for key, value in matches.items():
            self.assertEqual(5, len(value))


def sept(date: int):
    return dt.date(2022, 9, date)


# noinspection PyShadowingBuiltins
def oct(date: int):
    return dt.date(2022, 10, date)


if __name__ == '__main__':
    unittest.main()
