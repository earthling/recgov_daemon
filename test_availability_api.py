import datetime as dt
import logging
import typing
import unittest
from typing import Dict

from dateutil.relativedelta import relativedelta
from dateutil.rrule import *

from ridb_interface import OnlineAvailabilityProvider, OfflineAvailabilityProvider, AVAILABILITY_DATETIME_FORMAT


class Criteria(object):
    def test(self, d: dt.date, sites: typing.Set[str]) -> bool:
        return False

    def matches(self) -> Dict:
        return {}

    @staticmethod
    def days_of_week(nights_to_stay: [int], start_date: dt.date = None, look_ahead_months: int = 3):
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

    def test(self, d: dt.date, sites: typing.Set[str]) -> bool:
        for criteria in self.criteria:
            criteria.test(d, sites)
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


class ExactDateSearch(Criteria):
    def __init__(self, dates):
        self._dates = dates
        self._matches = dict()

    def test(self, d: dt.date, sites: typing.Set[str]) -> bool:
        if d in self._dates:
            self._matches[d] = sites
        return True

    def matches(self) -> Dict:
        return self._matches


class DatesInSameCampsite(Criteria):
    def __init__(self, *dates: [dt.date]):
        self._dates = dates
        self._matches = dict()

    def test(self, d: dt.date, sites: typing.Set[str]) -> bool:
        if d in self._dates:
            if len(self._matches) == 0:
                self._matches[d] = sites
            else:
                for date_key, site_ids_value in self._matches.items():
                    sites.intersection_update(site_ids_value)
                    if len(sites) == 0:
                        self._matches.clear()
                        return False
                    else:
                        self._matches[date_key] = sites

                self._matches[d] = sites
        return True

    def matches(self) -> Dict:
        return self._matches if len(self._matches) == len(self._dates) else {}


def search(availability: Dict, criteria: Criteria) -> Dict:
    for date_key, sites in availability.items():
        test_date = dt.datetime.strptime(date_key, AVAILABILITY_DATETIME_FORMAT)
        site_ids = set([site["site"] for site in sites])
        if not criteria.test(test_date.date(), site_ids):
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
        # for date_key, sites in self.availability.items():
        #     site_ids = [site["site"] for site in sites]
        #     print(f"{date_key} = {site_ids}")

    def test_search_no_availability(self):
        matches = search(self.availability, ExactDateSearch([dt.date(2022, 9, 24)]))
        self.assertEqual(0, len(matches), "No matches expected")

    def test_search_specific_dates_available(self):
        matches = search(self.availability, ExactDateSearch([dt.date(2022, 9, 20), dt.date(2022, 9, 21)]))
        self.assertEqual(2, len(matches))

    def test_search_dates_in_same_campsite(self):
        first = dt.date(2022, 9, 25)
        second = dt.date(2022, 9, 26)
        matches = search(self.availability, DatesInSameCampsite(first, second))
        self.assertEqual(2, len(matches))
        self.assertEqual(matches[first], matches[second])
        self.assertEqual({'004', '005'}, matches[first])

    def test_search_no_dates_in_same_campsite(self):
        first = dt.date(2022, 10, 9)
        second = dt.date(2022, 10, 10)
        matches = search(self.availability, DatesInSameCampsite(first, second))
        self.assertEqual(0, len(matches))

    def test_search_for_stays(self):
        stays = Stay(DatesInSameCampsite(dt.date(2022, 9, 25), dt.date(2022, 9, 26)),
                     DatesInSameCampsite(dt.date(2022, 10, 9), dt.date(2022, 10, 10)))
        matches = search(self.availability, stays)
        self.assertEqual(2, len(matches))
        self.assertEqual({'004', '005'}, matches[dt.date(2022, 9, 25)])
        self.assertEqual({'004', '005'}, matches[dt.date(2022, 9, 26)])

    def test_search_for_weekends(self):
        stays = Criteria.days_of_week([FR, SA])
        matches = search(self.availability, stays)
        self.assertEqual(0, len(matches))

    def test_search_midweek(self):
        stays = Criteria.days_of_week([SU, MO])
        matches = search(self.availability, stays)
        # [print(f"{key} {value}") for key, value in matches.items()]
        self.assertEqual(4, len(matches))


if __name__ == '__main__':
    unittest.main()
