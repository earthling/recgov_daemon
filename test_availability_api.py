import unittest
from dateutil.rrule import WEEKLY, FR, SA, rrule
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
        availability = OnlineAvailabilityProvider().get_availability(232876, dt.datetime.now())
        print_by_date(availability)
        self.assertTrue(len(availability) > 0)


class SearchAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OfflineAvailabilityProvider("availability-09.json", "availability-10.json")
        self.availability = self.provider.get_availability(232876, dt.datetime.now())
        print_by_date(self.availability)

    def test_search_for_weekends(self):
        stays = MinimumStayLength(2, first_week_day=FRIDAY)
        matches = search(self.availability, stays)
        self.assertEqual(0, len(matches))

    def test_search_midweek(self):
        stays = MinimumStayLength(2, first_week_day=SUNDAY)
        matches = search(self.availability, stays)
        self.assertEqual(6, len(matches))

    def test_search_midweek_two_campsites(self):
        # Only one site available on Sunday, 10-09
        stays = MinimumStayLength(2, first_week_day=SUNDAY, num_sites=2)
        matches = search(self.availability, stays)
        self.assertEqual(4, len(matches))

    def test_search_for_consecutive_days(self):
        nights = MinimumStayLength(3)
        matches = search(self.availability, nights)
        self.assertEqual(19, len(matches))

    def test_find_consecutive_days_with_first_day_restricted(self):
        nights = MinimumStayLength(3, first_night=oct(9))
        matches = search(self.availability, nights)
        self.assertEqual(5, len(matches))

    def test_find_no_consecutive_nights_with_first_day_restricted(self):
        nights = MinimumStayLength(3, first_night=oct(12))
        matches = search(self.availability, nights)
        self.assertEqual(0, len(matches))

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


class ParseSearchOptionsTest(unittest.TestCase):
    def test_parse_min_stay_options(self):
        criteria = parse_search_options([], num_nights=3, num_sites=3)
        self.assertIsInstance(criteria, MinimumStayLength)

    def test_parse_days_of_week(self):
        # Search for weekend availability (good luck!)
        criteria = parse_search_options(["Fr"], num_sites=0, num_nights=2)
        # Use recurring rule to generate dates for Friday and Saturday this week
        dates = set(rrule(WEEKLY, byweekday=[FR, SA], until=dt.datetime.now() + dt.timedelta(weeks=1)))
        # Pretend like these are available for one site.
        criteria.test('001', {d.date() for d in dates})
        # Since we set num_sites = 0, we don't have to check if dates are available in same site
        self.assertEqual(2, len(criteria.matches({})))

    def test_parse_specific_dates(self):
        criteria = parse_search_options(["2022-10-12", "2022-10-25"], num_nights=3, num_sites=0)
        criteria.test('001', {oct(24), oct(25), oct(26), oct(27)})
        self.assertEqual(3, len(criteria.matches({})))


if __name__ == '__main__':
    unittest.main()
