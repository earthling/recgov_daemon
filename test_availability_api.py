import logging
import unittest
from datetime import datetime

from ridb_interface import get_availability_for_campground


class AvailabilityApiTest(unittest.TestCase):
    def test_fetch_availability_data(self):
        logging.basicConfig(level=logging.DEBUG)
        # Check availability for Meeks Bay:
        availability = get_availability_for_campground("232876", datetime.now())
        for date, sites in availability.items():
            site_ids = [site["site"] for site in sites]
            print(f"{date} = {site_ids}")
        self.assertEqual(True, True)  # add assertion here


if __name__ == '__main__':
    unittest.main()
