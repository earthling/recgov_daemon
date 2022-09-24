import unittest

from availability import *
from ridb_interface import OnlineAvailabilityProvider, OfflineAvailabilityProvider


def sept(date: int):
    return dt.date(2022, 9, date)


# noinspection PyShadowingBuiltins
def oct(date: int):
    return dt.date(2022, 10, date)


def print_by_date(availability):
    by_date = index_by_date(availability)
    keys = sorted(list(by_date.keys()))
    print("")
    for key in keys:
        sites = by_date[key]
        print("%s = %s" % (dt.datetime.strftime(key, "%Y-%m-%d %a"), sorted(sites)))


class AvailabilityApiTest(unittest.TestCase):

    def test_fetch_availability_data(self):
        logging.basicConfig(level=logging.DEBUG)
        # Check availability for Meeks Bay:
        availability = OnlineAvailabilityProvider().get_availability("232876", dt.datetime.now())
        print_by_date(availability)
        self.assertTrue(len(availability) > 0)


class SearchAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OfflineAvailabilityProvider("availability-09.json", "availability-10.json")
        self.availability = self.provider.get_availability("232876", dt.datetime.now())
        print_by_date(self.availability)

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


if __name__ == '__main__':
    unittest.main()
