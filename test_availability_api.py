import logging
import typing
import unittest
from datetime import datetime, date
from typing import Dict

from ridb_interface import OnlineAvailabilityProvider, OfflineAvailabilityProvider, AVAILABILITY_DATETIME_FORMAT


class Criteria(object):
    def test(self, d: date, sites: typing.Set[str]) -> bool:
        return False

    def matches(self) -> Dict:
        return {}


class Stay(Criteria):
    def __init__(self, *criteria: [Criteria]):
        self.criteria = criteria

    def test(self, d: date, sites: typing.Set[str]) -> bool:
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

    def test(self, d: date, sites: typing.Set[str]) -> bool:
        if d in self._dates:
            self._matches[d] = sites
        return True

    def matches(self) -> Dict:
        return self._matches


class DatesInSameCampsite(Criteria):
    def __init__(self, *dates: [date]):
        self._dates = dates
        self._matches = dict()

    def test(self, d: date, sites: typing.Set[str]) -> bool:
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
        return self._matches


def search(availability: Dict, criteria: Criteria) -> Dict:
    for date_key, sites in availability.items():
        dt = datetime.strptime(date_key, AVAILABILITY_DATETIME_FORMAT)
        site_ids = set([site["site"] for site in sites])
        criteria.test(dt.date(), site_ids)
    return criteria.matches()


class AvailabilityApiTest(unittest.TestCase):

    def test_fetch_availability_data(self):
        logging.basicConfig(level=logging.DEBUG)
        # Check availability for Meeks Bay:
        availability = OnlineAvailabilityProvider().get_availability("232876", datetime.now())
        for date_key, sites in availability.items():
            site_ids = [site["site"] for site in sites]
            print(f"{date_key} = {site_ids}")
        self.assertEqual(True, True)  # add assertion here


class SearchAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OfflineAvailabilityProvider("availability-09.json", "availability-10.json")
        self.availability = self.provider.get_availability("232876", datetime.now())
        for date_key, sites in self.availability.items():
            site_ids = [site["site"] for site in sites]
            print(f"{date_key} = {site_ids}")

    def test_search_no_availability(self):
        matches = search(self.availability, ExactDateSearch([date(2022, 9, 24)]))
        self.assertEqual(0, len(matches), "No matches expected")

    def test_search_specific_dates_available(self):
        matches = search(self.availability, ExactDateSearch([date(2022, 9, 20), date(2022, 9, 21)]))
        self.assertEqual(2, len(matches))

    def test_search_dates_in_same_campsite(self):
        first = date(2022, 9, 25)
        second = date(2022, 9, 26)
        matches = search(self.availability, DatesInSameCampsite(first, second))
        self.assertEqual(2, len(matches))
        self.assertEqual(matches[first], matches[second])
        self.assertEqual({'004', '005'}, matches[first])

    def test_search_no_dates_in_same_campsite(self):
        first = date(2022, 10, 9)
        second = date(2022, 10, 10)
        matches = search(self.availability, DatesInSameCampsite(first, second))
        self.assertEqual(0, len(matches))

    def test_search_for_stays(self):
        stays = Stay(DatesInSameCampsite(date(2022, 9, 25), date(2022, 9, 26)),
                     DatesInSameCampsite(date(2022, 10, 9), date(2022, 10, 10)))
        matches = search(self.availability, stays)
        self.assertEqual(2, len(matches))
        self.assertEqual({'004', '005'}, matches[date(2022, 9, 25)])
        self.assertEqual({'004', '005'}, matches[date(2022, 9, 26)])


if __name__ == '__main__':
    unittest.main()
