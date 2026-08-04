import json
import unittest

from scripts.crawl_foody_hanoi import (
    assert_safe_output,
    build_opening_hours,
    build_price_range,
    extract_init_data,
    to_catalog_record,
)


def sample_detail() -> dict:
    return {
        "RestaurantID": 123,
        "Name": "Quán thử nghiệm",
        "Address": "10 Phố Huế",
        "City": "Hà Nội",
        "District": "Quận Hai Bà Trưng",
        "Area": "Phố Huế",
        "PriceMin": 30000,
        "PriceMax": 70000,
        "Latitude": 21.01,
        "Longtitude": 105.85,
        "Cuisines": [{"Name": "Món Việt"}],
        "LstCategory": [
            {
                "Name": "Quán ăn",
                "CategoryGroupKey": "food",
            }
        ],
        "OpeningTime": [
            {
                "DayOfWeek": 4,
                "IsDayOff": False,
                "TimeOpen": {"Hours": 6, "Minutes": 30},
                "TimeClose": {"Hours": 22, "Minutes": 0},
            }
        ],
    }


class FoodyHanoiCrawlerTests(unittest.TestCase):
    def test_extract_init_data_reads_only_metadata_object(self):
        expected = sample_detail()
        html = (
            "<script>var other = {};</script>"
            f"<script>var initData = {json.dumps(expected)};"
            "var initDataReviews = {\"Items\":[{\"Username\":\"private\"}]};"
            "</script>"
        )

        actual = extract_init_data(html)

        self.assertEqual(actual, expected)
        self.assertNotIn("Username", json.dumps(actual))

    def test_record_matches_food_catalog_without_user_content(self):
        record = to_catalog_record(
            sample_detail(),
            source_url="https://www.foody.vn/ha-noi/quan-thu-nghiem",
            collected_at="2026-07-30T00:00:00+00:00",
        )

        self.assertEqual(record["id"], "foody_123")
        self.assertEqual(record["district"], "Hai Bà Trưng")
        self.assertEqual(record["price_range"], "30.000đ - 70.000đ")
        self.assertEqual(record["opening_hours"], "06:30 - 22:00")
        self.assertEqual(record["opening_hours_source_days"], [4])
        self.assertEqual(record["category"], "Ẩm thực")
        self.assertEqual(record["sub_category"], "Quán ăn")
        self.assertNotIn("review", json.dumps(record).casefold())
        self.assertNotIn("phone", json.dumps(record).casefold())
        assert_safe_output(record)

    def test_unknown_price_and_invalid_hours_are_not_invented(self):
        self.assertEqual(build_price_range(None, None), "N/A")
        hours, source_days = build_opening_hours(
            [
                {
                    "DayOfWeek": 2,
                    "IsDayOff": False,
                    "TimeOpen": {"Hours": 25, "Minutes": 0},
                    "TimeClose": {"Hours": 10, "Minutes": 0},
                }
            ]
        )
        self.assertEqual(hours, "N/A")
        self.assertEqual(source_days, [])


if __name__ == "__main__":
    unittest.main()
