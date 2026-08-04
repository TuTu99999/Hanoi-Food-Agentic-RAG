import argparse
import json
from collections import Counter
from pathlib import Path

from embedding.catalog_schema import (
    is_open_at,
    parse_opening_hours,
    parse_price_range,
)
from embedding.text_utils import normalize_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_CATALOG_PATH = PROJECT_ROOT / "data" / "raw" / "food_raw.json"
OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "retrieval_cases.json"
)

ENTITY_CASES = (
    ("địa chỉ Phở Thìn Bờ Hồ", "Hoàn Kiếm", "food_001"),
    ("Cà phê Giảng mở cửa lúc nào", "Hoàn Kiếm", "food_003"),
    ("Bún thang Bà Đức ở đâu", "Hoàn Kiếm", "food_005"),
    ("giờ mở cửa Ốc Hà Trang Đinh Liệt", "Hoàn Kiếm", "food_010"),
    ("địa chỉ Bánh mì sốt vang Đình Ngang", "Hoàn Kiếm", "food_025"),
    ("Bún riêu tôm cua Hàng Bông ở đâu", "Hoàn Kiếm", "food_050"),
    ("Cơm Gà Gia Trần 1 giá bao nhiêu", "Hoàn Kiếm", "food_075"),
    ("Bánh Xèo Bé Uyên Đặc Sản Đại Lộc", "Hoàn Kiếm", "food_100"),
    ("Bún Bò Huế Đông Ba Quán", "Ba Đình", "food_125"),
    ("địa chỉ Chè Xà Vẫn Ngọc Trâm", "Ba Đình", "food_150"),
    ("tìm Bún Lành", "Ba Đình", "food_175"),
    ("Bún Bò Huế Ngọc Diệp giá bao nhiêu", "Ba Đình", "food_184"),
    ("6 Degrees Hồ Tây mở đến mấy giờ", "Tây Hồ", "food_202"),
    ("Pizza 4P's Tây Hồ ở đâu", "Tây Hồ", "food_205"),
    ("thông tin Maison de Tet Decor", "Tây Hồ", "food_211"),
    ("Nhà Hàng Sài Gòn 1970s", "Tây Hồ", "food_225"),
    ("The Sushi Club Tây Hồ giá", "Tây Hồ", "food_250"),
    ("Maison de Tet Decor brunch", "Tây Hồ", "food_275"),
    ("Nhà Hàng Sen Việt Tây Hồ", "Tây Hồ", "food_300"),
    ("GangnamBox The Loop IPH", "Cầu Giấy", "food_315"),
    ("Gác Trịnh Cafe mở cửa", "Cầu Giấy", "food_319"),
    ("Trill Rooftop Cafe Cầu Giấy", "Cầu Giấy", "food_350"),
    ("Mì Cay Sasin Cầu Giấy ở đâu", "Cầu Giấy", "food_375"),
    ("Phở Thìn 13 Lò Đúc ở đâu", "Hai Bà Trưng", "food_401"),
    (
        "TukTuk Thai Bistro Triệu Việt Vương",
        "Hai Bà Trưng",
        "food_416",
    ),
)

NATURAL_NEED_CASES = (
    (
        "cafe hiện đại có bánh ngọt để ngồi làm việc",
        "Hoàn Kiếm",
        "food_058",
    ),
    (
        "trà sữa bình dân cho sinh viên và nhóm bạn",
        "Hoàn Kiếm",
        "food_066",
    ),
    (
        "quán gỏi cá trích hợp nhóm đông người",
        "Hoàn Kiếm",
        "food_070",
    ),
    (
        "pizza kiểu Ý phù hợp gia đình và dân văn phòng",
        "Hoàn Kiếm",
        "food_072",
    ),
    (
        "cafe giá hợp lý cho sinh viên và dân văn phòng",
        "Hoàn Kiếm",
        "food_083",
    ),
    (
        "trà sữa kèm đồ ăn vặt phù hợp trẻ em",
        "Hoàn Kiếm",
        "food_087",
    ),
    (
        "quán bê thui nóng bình dân cho đồng nghiệp",
        "Ba Đình",
        "food_101",
    ),
    (
        "quán gà và hải sản phong cách miền Trung",
        "Ba Đình",
        "food_116",
    ),
    (
        "quán nhậu bình dân cho nhóm đồng nghiệp",
        "Ba Đình",
        "food_123",
    ),
    (
        "cafe để học tập làm việc cho sinh viên",
        "Ba Đình",
        "food_127",
    ),
    (
        "quán chay thanh đạm giá sinh viên",
        "Ba Đình",
        "food_146",
    ),
    (
        "nhà hàng Nhật có cả sushi và BBQ",
        "Ba Đình",
        "food_177",
    ),
    (
        "pizza đồ ăn nhanh cho nhóm bạn và gia đình",
        "Ba Đình",
        "food_192",
    ),
    (
        "nhà hàng món Âu có view Hồ Tây để hẹn hò",
        "Tây Hồ",
        "food_202",
    ),
    (
        "món Việt trong sân vườn yên tĩnh ven Hồ Tây",
        "Tây Hồ",
        "food_211",
    ),
    (
        "cafe món Âu có lựa chọn món chay cho người nước ngoài",
        "Tây Hồ",
        "food_215",
    ),
    (
        "steak và hải sản cao cấp cho buổi hẹn",
        "Tây Hồ",
        "food_220",
    ),
    (
        "bistro không gian đẹp phù hợp hẹn hò",
        "Tây Hồ",
        "food_223",
    ),
    (
        "nhà hàng chay tốt cho sức khỏe đi cùng gia đình",
        "Tây Hồ",
        "food_227",
    ),
    (
        "quán nhậu Nhật kiểu izakaya mở khuya",
        "Tây Hồ",
        "food_237",
    ),
    (
        "sushi sashimi Nhật phù hợp hẹn hò",
        "Tây Hồ",
        "food_250",
    ),
    (
        "nhà hàng Ấn Độ truyền thống không gian sang trọng",
        "Tây Hồ",
        "food_253",
    ),
    (
        "cafe bistro không gian đẹp để làm việc",
        "Tây Hồ",
        "food_263",
    ),
    (
        "món Thái phong cách châu Á cho buổi hẹn",
        "Tây Hồ",
        "food_274",
    ),
    (
        "cà ri Ấn Độ bánh naan cho khách du lịch",
        "Tây Hồ",
        "food_284",
    ),
    (
        "cafe rooftop view đẹp để hẹn hò",
        "Tây Hồ",
        "food_299",
    ),
    (
        "nhà hàng chay có không gian thiền trà thư giãn",
        "Cầu Giấy",
        "food_310",
    ),
    (
        "cafe yên tĩnh vừa làm việc vừa trò chuyện",
        "Cầu Giấy",
        "food_319",
    ),
    (
        "rooftop rộng để chụp ảnh và đi cùng bạn bè",
        "Cầu Giấy",
        "food_350",
    ),
    (
        "món Thái có tom yum và pad thai cho gia đình",
        "Hai Bà Trưng",
        "food_416",
    ),
)

MULTI_CONSTRAINT_CASES = (
    (
        "bún chả Obama giá 60k đổ về còn mở lúc 12h",
        "Hoàn Kiếm",
        "food_002",
        None,
        60000,
        "12:00",
    ),
    (
        "nộm bò khô phố Hàm Long dưới 35k lúc 12h",
        "Hoàn Kiếm",
        "food_007",
        None,
        35000,
        "12:00",
    ),
    (
        "kem lâu đời gần Hồ Gươm dưới 20k mở lúc 22h",
        "Hoàn Kiếm",
        "food_011",
        None,
        20000,
        "22:00",
    ),
    (
        "xôi xéo ăn đêm dưới 50k lúc 23h",
        "Hoàn Kiếm",
        "food_016",
        None,
        50000,
        "23:00",
    ),
    (
        "mỳ vằn thắn có sủi cảo dưới 60k mở lúc 18h",
        "Hoàn Kiếm",
        "food_022",
        None,
        60000,
        "18:00",
    ),
    (
        "phở nước dùng đục béo dưới 70k mở lúc 8h",
        "Hoàn Kiếm",
        "food_031",
        None,
        70000,
        "08:00",
    ),
    (
        "bún riêu sườn sụn dưới 50k còn mở lúc 20h",
        "Hoàn Kiếm",
        "food_042",
        None,
        50000,
        "20:00",
    ),
    (
        "há cảo chiên và mỳ vằn thắn gốc Hoa dưới 40k lúc 20h",
        "Hoàn Kiếm",
        "food_047",
        None,
        40000,
        "20:00",
    ),
    (
        "Việt V món Việt cho gia đình dưới 60k mở lúc 20h",
        "Hoàn Kiếm",
        "food_055",
        None,
        60000,
        "20:00",
    ),
    (
        "trà sữa ăn vặt cho nhóm bạn dưới 20k lúc 20h",
        "Hoàn Kiếm",
        "food_061",
        None,
        20000,
        "20:00",
    ),
    (
        "mỳ cay và trà sữa cho sinh viên dưới 30k lúc 21h",
        "Hoàn Kiếm",
        "food_089",
        None,
        30000,
        "21:00",
    ),
    (
        "Thống Gia món Việt cho gia đình dưới 60k lúc 20h",
        "Ba Đình",
        "food_102",
        None,
        60000,
        "20:00",
    ),
    (
        "bò né ăn sáng cho sinh viên dưới 20k lúc 7h",
        "Ba Đình",
        "food_110",
        None,
        20000,
        "07:00",
    ),
    (
        "lẩu cho nhóm đông dưới 50k còn mở lúc 23h",
        "Ba Đình",
        "food_118",
        None,
        50000,
        "23:00",
    ),
    (
        "bánh kẹp ăn vặt sinh viên dưới 20k mở lúc 18h",
        "Ba Đình",
        "food_132",
        None,
        20000,
        "18:00",
    ),
    (
        "món chay thanh đạm giá 15k còn mở lúc 18h",
        "Ba Đình",
        "food_146",
        None,
        15000,
        "18:00",
    ),
    (
        "mì Quảng miền Trung giá 20k mở lúc 12h",
        "Ba Đình",
        "food_158",
        None,
        20000,
        "12:00",
    ),
    (
        "TAIYO sushi BBQ dưới 50k mở lúc 12h",
        "Ba Đình",
        "food_177",
        None,
        50000,
        "12:00",
    ),
    (
        "pizza đồ ăn nhanh dưới 20k còn mở lúc 18h",
        "Ba Đình",
        "food_192",
        None,
        20000,
        "18:00",
    ),
    (
        "Pizza 4P's cho gia đình dưới 200k mở lúc 20h",
        "Tây Hồ",
        "food_205",
        None,
        200000,
        "20:00",
    ),
    (
        "steak hải sản hẹn hò từ 300k mở lúc 20h",
        "Tây Hồ",
        "food_220",
        300000,
        None,
        "20:00",
    ),
    (
        "đồ chay tốt cho sức khỏe dưới 120k mở lúc 20h",
        "Tây Hồ",
        "food_227",
        None,
        120000,
        "20:00",
    ),
    (
        "izakaya Nhật từ 300k còn mở lúc 0h30",
        "Tây Hồ",
        "food_237",
        300000,
        None,
        "00:30",
    ),
    (
        "sushi Nhật hẹn hò từ 200k mở lúc 20h",
        "Tây Hồ",
        "food_250",
        200000,
        None,
        "20:00",
    ),
    (
        "cafe bistro làm việc dưới 100k mở lúc 20h",
        "Tây Hồ",
        "food_263",
        None,
        100000,
        "20:00",
    ),
    (
        "cà ri Ấn Độ bánh naan dưới 150k mở lúc 20h",
        "Tây Hồ",
        "food_284",
        None,
        150000,
        "20:00",
    ),
    (
        "rooftop view đẹp dưới 100k còn mở lúc 22h",
        "Tây Hồ",
        "food_299",
        None,
        100000,
        "22:00",
    ),
    (
        "cafe yên tĩnh làm việc dưới 50k mở lúc 22h",
        "Cầu Giấy",
        "food_319",
        None,
        50000,
        "22:00",
    ),
    (
        "rooftop check-in dưới 100k còn mở lúc 22h",
        "Cầu Giấy",
        "food_350",
        None,
        100000,
        "22:00",
    ),
    (
        "món Thái cho gia đình dưới 200k mở lúc 20h",
        "Hai Bà Trưng",
        "food_416",
        None,
        200000,
        "20:00",
    ),
)

TYPO_SLANG_CASES = (
    ("pho thin bo hoo o dau", "Hoàn Kiếm", "food_001"),
    ("ca phe gian mo cua may gio", "Hoàn Kiếm", "food_003"),
    ("bun thang ba duk", "Hoàn Kiếm", "food_005"),
    ("oc ha tran dinh liet", "Hoàn Kiếm", "food_010"),
    ("banh mi sot vang dinh ngan", "Hoàn Kiếm", "food_025"),
    ("bun rieu tom cua hang bon", "Hoàn Kiếm", "food_050"),
    ("com ga gia trann 1", "Hoàn Kiếm", "food_075"),
    ("banh xeo be uyen dai lok", "Hoàn Kiếm", "food_100"),
    ("bun bo hue dong baa quan", "Ba Đình", "food_125"),
    ("che xa van ngoc trammm", "Ba Đình", "food_150"),
    ("bun lanhh o dau", "Ba Đình", "food_175"),
    ("bun bo hue ngoc diep gi bao nhieu", "Ba Đình", "food_184"),
    ("6 degres ho tay mo den may gio", "Tây Hồ", "food_202"),
    ("nha hang sai gon 1970z", "Tây Hồ", "food_225"),
    ("the susi club tay ho", "Tây Hồ", "food_250"),
    ("maison de tet deccor", "Tây Hồ", "food_275"),
    ("gangnambox the lop iph", "Cầu Giấy", "food_315"),
    ("tril rooftop cafe cau giay", "Cầu Giấy", "food_350"),
    ("mi cay sasin cau giayy", "Cầu Giấy", "food_375"),
    (
        "tuktuk thai bistro trieu viet vuongg",
        "Hai Bà Trưng",
        "food_416",
    ),
)

NO_ANSWER_CASES = (
    ("quán phở ở Đống Đa", "Đống Đa", None, None, None),
    ("sushi tại Thanh Xuân", "Thanh Xuân", None, None, None),
    ("pizza ở Hà Đông", "Hà Đông", None, None, None),
    ("cafe làm việc tại Long Biên", "Long Biên", None, None, None),
    ("quán chay ở Hoàng Mai", "Hoàng Mai", None, None, None),
    ("quán lẩu tại Nam Từ Liêm", "Nam Từ Liêm", None, None, None),
    ("chỗ ăn brunch ở Bắc Từ Liêm", "Bắc Từ Liêm", None, None, None),
    ("hải sản tại Ba Vì", "Ba Vì", None, None, None),
    ("món ăn dưới 1k ở Hoàn Kiếm", "Hoàn Kiếm", None, 1000, None),
    ("nhà hàng từ 2 triệu ở Ba Đình", "Ba Đình", 2000000, None, None),
    ("đồ ăn dưới 1k tại Tây Hồ", "Tây Hồ", None, 1000, None),
    ("quán từ 2 triệu ở Cầu Giấy", "Cầu Giấy", 2000000, None, None),
    (
        "món Thái dưới 1k tại Hai Bà Trưng",
        "Hai Bà Trưng",
        None,
        1000,
        None,
    ),
    ("quán Tây Hồ còn mở lúc 4h sáng", "Tây Hồ", None, None, "04:00"),
    (
        "quán Cầu Giấy còn mở lúc 3h30 sáng",
        "Cầu Giấy",
        None,
        None,
        "03:30",
    ),
)

EXPECTED_GROUP_COUNTS = {
    "entity_lookup": 25,
    "natural_need": 30,
    "multi_constraint": 30,
    "typo_slang": 20,
    "no_answer": 15,
}


def simple_cases(
    group,
    prefix,
    seeds,
    *,
    min_unique_parent_ids=None,
):
    cases = []
    for index, (query, district, parent_id) in enumerate(
        seeds,
        start=1,
    ):
        case = {
            "id": f"{prefix}-{index:03d}",
            "group": group,
            "query": query,
            "district": district,
            "domain": "food",
            "expected_parent_ids": [parent_id],
        }
        if min_unique_parent_ids is not None:
            case["min_unique_parent_ids"] = min_unique_parent_ids
        cases.append(case)
    return cases


def build_cases():
    cases = [
        *simple_cases("entity_lookup", "entity", ENTITY_CASES),
        *simple_cases(
            "natural_need",
            "natural",
            NATURAL_NEED_CASES,
            min_unique_parent_ids=3,
        ),
        *simple_cases("typo_slang", "typo", TYPO_SLANG_CASES),
    ]

    for index, seed in enumerate(MULTI_CONSTRAINT_CASES, start=1):
        (
            query,
            district,
            parent_id,
            price_min,
            price_max,
            open_at,
        ) = seed
        case = {
            "id": f"multi-{index:03d}",
            "group": "multi_constraint",
            "query": query,
            "district": district,
            "domain": "food",
            "expected_parent_ids": [parent_id],
        }
        for field, value in (
            ("price_min", price_min),
            ("price_max", price_max),
            ("open_at", open_at),
        ):
            if value is not None:
                case[field] = value
        cases.append(case)

    for index, seed in enumerate(NO_ANSWER_CASES, start=1):
        query, district, price_min, price_max, open_at = seed
        case = {
            "id": f"no-answer-{index:03d}",
            "group": "no_answer",
            "query": query,
            "district": district,
            "domain": "food",
            "expected_parent_ids": [],
        }
        for field, value in (
            ("price_min", price_min),
            ("price_max", price_max),
            ("open_at", open_at),
        ):
            if value is not None:
                case[field] = value
        cases.append(case)

    cases.sort(key=lambda case: case["id"])
    return cases


def read_catalog():
    with RAW_CATALOG_PATH.open("r", encoding="utf-8") as file:
        rows = json.load(file)
    return {
        str(row["id"]): row
        for row in rows
        if normalize_text(row.get("category")) == "am thuc"
    }


def validate_expected_record(case, record):
    if normalize_text(record["district"]) != normalize_text(case["district"]):
        raise ValueError(
            f"{case['id']} có district không khớp {record['id']}."
        )

    price = parse_price_range(record.get("price_range"))
    if (
        case.get("price_min") is not None
        and price["price_max"] < case["price_min"]
    ):
        raise ValueError(f"{case['id']} có price_min không khớp.")
    if (
        case.get("price_max") is not None
        and price["price_min"] > case["price_max"]
    ):
        raise ValueError(f"{case['id']} có price_max không khớp.")

    open_at = case.get("open_at")
    if open_at:
        opening = parse_opening_hours(record.get("opening_hours"))
        if not is_open_at(opening["opening_intervals"], open_at):
            raise ValueError(f"{case['id']} có open_at không khớp.")


def validate_cases(cases):
    catalog = read_catalog()
    ids = [case["id"] for case in cases]
    queries = [normalize_text(case["query"]) for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation case id bị trùng.")
    if len(queries) != len(set(queries)):
        raise ValueError("Evaluation query bị trùng.")

    group_counts = Counter(case["group"] for case in cases)
    if dict(group_counts) != EXPECTED_GROUP_COUNTS:
        raise ValueError(
            f"Phân bố case không đúng: {dict(group_counts)}"
        )

    for case in cases:
        for parent_id in case["expected_parent_ids"]:
            record = catalog.get(parent_id)
            if record is None:
                raise ValueError(
                    f"{case['id']} tham chiếu record không tồn tại."
                )
            validate_expected_record(case, record)


def write_cases(cases):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(cases, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Build the curated food retrieval evaluation set."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate that the committed JSON matches the curated seeds.",
    )
    args = parser.parse_args()

    cases = build_cases()
    validate_cases(cases)
    if args.check:
        with OUTPUT_PATH.open("r", encoding="utf-8") as file:
            committed_cases = json.load(file)
        if committed_cases != cases:
            raise RuntimeError(
                "retrieval_cases.json is out of date. Run this script."
            )
    else:
        write_cases(cases)

    print(
        f"Validated {len(cases)} retrieval cases: "
        f"{dict(Counter(case['group'] for case in cases))}"
    )


if __name__ == "__main__":
    main()
