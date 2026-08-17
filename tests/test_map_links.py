import unittest

from rag.map_links import append_directions_links, build_directions_url


class MapLinksTestCase(unittest.TestCase):
    def test_builds_google_maps_url_from_coordinates(self):
        url = build_directions_url(21.03123456, 105.81234567)

        self.assertEqual(
            url,
            "https://www.google.com/maps/dir/"
            "?api=1&destination=21.0312346%2C105.8123457",
        )
        self.assertNotIn("key=", url)
        self.assertNotIn("origin=", url)

    def test_rejects_invalid_coordinates(self):
        self.assertIsNone(build_directions_url(None, 105.8))
        self.assertIsNone(build_directions_url(91, 105.8))
        self.assertIsNone(build_directions_url(21.0, float("nan")))

    def test_prefers_specific_address_over_unverified_osm_coordinates(self):
        url = build_directions_url(
            21.0173841,
            105.8315492,
            address="149 Đường Đê La Thành, Nam Đồng, Đống Đa, Hà Nội",
            address_source="osm_street",
        )

        self.assertIn(
            "destination=149+%C4%90%C6%B0%E1%BB%9Dng+%C4%90%C3%AA+La+"
            "Th%C3%A0nh%2C+Nam+%C4%90%E1%BB%93ng%2C+%C4%90%E1%BB%91ng+"
            "%C4%90a%2C+H%C3%A0+N%E1%BB%99i",
            url,
        )
        self.assertNotIn("21.0173841", url)

    def test_uses_coordinates_for_district_fallback_address(self):
        url = build_directions_url(
            21.01,
            105.8,
            address="Cầu Giấy, Hà Nội",
            address_source="district_fallback",
        )

        self.assertIn("destination=21.0100000%2C105.8000000", url)

    def test_appends_only_places_mentioned_in_answer(self):
        documents = [
            {
                "parent_id": "place-1",
                "title": "Phở Hà Nội",
                "address": "1 Trung Kính, Cầu Giấy, Hà Nội",
                "latitude": 21.01,
                "longitude": 105.8,
            },
            {
                "parent_id": "place-2",
                "title": "Quán không được nhắc đến",
                "address": "2 Trung Kính, Cầu Giấy, Hà Nội",
                "latitude": 21.02,
                "longitude": 105.81,
            },
        ]

        result = append_directions_links(
            "Bạn có thể thử Phở Hà Nội tại Cầu Giấy.",
            documents,
        )

        self.assertIn("Chỉ đường từ vị trí hiện tại", result)
        self.assertIn("destination=1+Trung+K%C3%ADnh", result)
        self.assertNotIn("destination=2+Trung+K%C3%ADnh", result)

    def test_does_not_duplicate_existing_url(self):
        document = {
            "title": "Phở Hà Nội",
            "latitude": 21.01,
            "longitude": 105.8,
        }
        url = build_directions_url(21.01, 105.8)
        answer = f"[Phở Hà Nội]({url})"

        self.assertEqual(append_directions_links(answer, [document]), answer)

    def test_district_fallback_does_not_create_unrelated_link(self):
        document = {
            "title": "Quán không được nhắc đến",
            "address": "Cầu Giấy, Hà Nội",
            "address_source": "district_fallback",
            "latitude": 21.01,
            "longitude": 105.8,
        }

        answer = "Dưới đây là một số quán tại Cầu Giấy, Hà Nội."

        self.assertEqual(append_directions_links(answer, [document]), answer)


if __name__ == "__main__":
    unittest.main()
