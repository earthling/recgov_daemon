import unittest

from campground import Campground
from locations import forward_geocode, resolve_locations

from ridb_interface import query_facilities


class GeoCodingTest(unittest.TestCase):
    def test_forward_geocoding(self):
        lat, lon = forward_geocode("Portland, OR")
        self.assertTrue(abs(lat) > 0)
        self.assertTrue(abs(lon) > 0)


class LocationTest(unittest.TestCase):
    def test_resolve_facility_by_name(self):
        #  We could further filter on name of campground to remove any 'bonus' campgrounds.
        facilities = query_facilities(query="Meeks Bay")
        self.assertEqual(2, len(facilities))

    def test_resolve_facility_by_city(self):
        lat, lon = forward_geocode("Downieville, CA")
        facilities = query_facilities(latitude=lat, longitude=lon, radius=30)
        self.assertTrue(len(facilities) > 0)

    def test_resolve_locations(self):
        facilities = resolve_locations([
            "Downieville, CA",
            "232876",
            "Meeks Bay",
            "38.951209,-120.106420"])
        self.assertTrue(Campground('Meeks Bay', 232876) in facilities)
        self.assertTrue(Campground('Fiddle Creek', 234542) in facilities)
        self.assertTrue(Campground('Loon Lake Chalet', 232348) in facilities)


if __name__ == '__main__':
    unittest.main()
