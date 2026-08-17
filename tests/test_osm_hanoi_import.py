import unittest

from scripts.import_osm_hanoi_food import (
    build_overpass_query,
    build_tiles,
    build_summary,
    canonical_district,
    commons_title_from_value,
    to_catalog_record,
    validate_overpass_payload,
)


class OsmHanoiImportTests(unittest.TestCase):
    def test_overpass_query_is_bounded_and_filters_food_amenities(self):
        query = build_overpass_query((20.0, 105.0, 21.0, 106.0))
        self.assertIn("restaurant|fast_food|cafe|food_court|ice_cream", query)
        self.assertIn("(20.0,105.0,21.0,106.0)", query)

    def test_rejects_partial_overpass_response(self):
        with self.assertRaises(ValueError):
            validate_overpass_payload(
                {"elements": [], "remark": "runtime timeout"}
            )
        self.assertEqual(
            validate_overpass_payload({"elements": []}),
            {"elements": []},
        )

    def test_build_tiles_covers_requested_box(self):
        tiles = build_tiles((0.0, 0.0, 2.0, 2.0), rows=2, columns=2)
        self.assertEqual(len(tiles), 4)
        self.assertEqual(tiles[0], (0.0, 0.0, 1.0, 1.0))
        self.assertEqual(tiles[-1], (1.0, 1.0, 2.0, 2.0))
        with self.assertRaises(ValueError):
            build_tiles((0.0, 0.0, 1.0, 1.0), rows=0, columns=1)

    def test_converts_named_food_place_to_compatible_catalog_record(self):
        element = {
            "type": "node",
            "id": 123,
            "lat": 21.03,
            "lon": 105.81,
            "tags": {
                "name": "Phở thử nghiệm",
                "amenity": "restaurant",
                "cuisine": "vietnamese;pho",
                "addr:housenumber": "12",
                "addr:street": "Trần Thái Tông",
                "addr:district": "Quận Cầu Giấy",
                "opening_hours": "Mo-Su 06:00-22:00",
                "wikidata": "Q123",
            },
        }

        record = to_catalog_record(element, "2026-08-04T00:00:00+00:00")

        self.assertIsNotNone(record)
        self.assertEqual(record["id"], "osm_node_123")
        self.assertEqual(record["category"], "Ẩm thực")
        self.assertEqual(record["district"], "Cầu Giấy")
        self.assertEqual(record["district_source"], "osm_address_tag")
        self.assertEqual(record["address_source"], "osm_street")
        self.assertEqual(record["sub_category"], "Món Việt")
        self.assertEqual(record["price_range"], "N/A")
        self.assertEqual(record["menu_items"], [])
        self.assertEqual(record["latitude"], 21.03)
        self.assertEqual(record["longitude"], 105.81)
        self.assertEqual(record["source_id"], "node/123")
        self.assertEqual(record["license"], "ODbL 1.0")
        self.assertEqual(record["_wikidata_id"], "Q123")

    def test_uses_center_for_way_and_does_not_invent_missing_values(self):
        element = {
            "type": "way",
            "id": 456,
            "center": {"lat": 21.02, "lon": 105.84},
            "tags": {
                "name:vi": "Quán ăn thật",
                "amenity": "fast_food",
                "addr:district": "Hoàn Kiếm",
            },
        }

        record = to_catalog_record(element, "2026-08-04T00:00:00+00:00")

        self.assertEqual(record["id"], "osm_way_456")
        self.assertEqual(record["district"], "Hoàn Kiếm")
        self.assertEqual(record["price_range"], "N/A")
        self.assertEqual(record["opening_hours"], "N/A")
        self.assertIsNone(record["image_url"])

    def test_rejects_private_or_invalid_place(self):
        private_place = {
            "type": "node",
            "id": 1,
            "lat": 21,
            "lon": 105,
            "tags": {
                "name": "Private",
                "amenity": "restaurant",
                "access": "private",
            },
        }
        missing_location = {
            "type": "way",
            "id": 2,
            "tags": {"name": "No center", "amenity": "restaurant"},
        }

        self.assertIsNone(to_catalog_record(private_place, "now"))
        self.assertIsNone(to_catalog_record(missing_location, "now"))

    def test_district_mapping_handles_prefixes_and_text(self):
        self.assertEqual(
            canonical_district({"addr:district": "Quận Đống Đa"}),
            "Đống Đa",
        )
        self.assertEqual(
            canonical_district({"addr:full": "Mỹ Đình, Nam Từ Liêm, Hà Nội"}),
            "Chưa xác định",
        )
        self.assertEqual(canonical_district({}), "Chưa xác định")

    def test_commons_reference_only_accepts_https_commons_file(self):
        self.assertEqual(
            commons_title_from_value("File:Pho Hanoi.jpg"),
            "File:Pho Hanoi.jpg",
        )
        self.assertEqual(
            commons_title_from_value(
                "https://commons.wikimedia.org/wiki/File:Pho_Hanoi.jpg"
            ),
            "File:Pho Hanoi.jpg",
        )
        self.assertIsNone(
            commons_title_from_value("https://images.example.com/food.jpg")
        )
        self.assertIsNone(
            commons_title_from_value(
                "http://commons.wikimedia.org/wiki/File:Unsafe.jpg"
            )
        )

    def test_summary_reports_missing_district_and_optional_coverage(self):
        records = [
            {
                "district": "Cầu Giấy",
                "address": "Cầu Giấy, Hà Nội",
                "address_source": "district_fallback",
                "opening_hours": "N/A",
                "cuisines": ["pho"],
                "image_url": None,
            },
            {
                "district": "Chưa xác định",
                "address": "Hà Nội",
                "address_source": "osm_addr_full",
                "opening_hours": "08:00-22:00",
                "cuisines": [],
                "image_url": "https://upload.wikimedia.org/example.jpg",
            },
        ]

        summary = build_summary(records)

        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(summary["license"], "ODbL 1.0")
        self.assertEqual(summary["with_street_address_count"], 1)
        self.assertEqual(summary["unknown_district_count"], 1)
        self.assertEqual(summary["with_cuisine_count"], 1)
        self.assertEqual(summary["with_image_count"], 1)

if __name__ == "__main__":
    unittest.main()
