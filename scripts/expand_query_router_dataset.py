"""One-time, deterministic expansion of the local query-router datasets."""

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAIN_PATH = PROJECT_ROOT / "data" / "query_router" / "intents.jsonl"
EVAL_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "query_router_cases.json"
)
TRAIN_TARGET_PER_INTENT = 70
EVAL_TARGET_PER_INTENT = 25


TRAIN_SPECS = {
    "chitchat": {
        "templates": [
            "{greeting} bạn ơi",
            "{greeting}, mình hỏi chút được không",
            "chúc bạn {time} vui vẻ",
            "cảm ơn vì đã {help}",
            "ok nha, {thanks}",
            "mình hiểu rồi, cảm ơn nhiều",
            "hẹn gặp lại bạn {when}",
            "tạm biệt nhé, chúc bạn {wish}",
            "bạn có khỏe không",
            "hôm nay nói chuyện với bạn vui ghê",
            "alo, bạn còn ở đó không",
            "ê trợ lý ơi, nghe mình nói không",
            "{greeting}, rất vui được gặp bạn",
            "{thanks}, mình không còn thắc mắc nữa",
            "chúc bạn {wish}",
            "{when} mình lại trò chuyện tiếp nha",
            "mong bạn có một {time} thật dễ chịu",
            "{greeting}, hôm nay bạn thế nào",
            "{thanks}, bạn hỗ trợ tốt lắm",
            "chào nhé, hẹn nói chuyện vào {when}",
        ],
        "variants": [
            {
                "greeting": "xin chào",
                "time": "buổi sáng",
                "help": "tư vấn cho mình",
                "thanks": "cảm ơn bạn",
                "when": "sau nhé",
                "wish": "một ngày tốt lành",
            },
            {
                "greeting": "chào buổi chiều",
                "time": "buổi tối",
                "help": "giải thích rõ",
                "thanks": "thanks nhiều",
                "when": "ngày mai",
                "wish": "làm việc hiệu quả",
            },
            {
                "greeting": "hello nha",
                "time": "cuối tuần",
                "help": "hỗ trợ nãy giờ",
                "thanks": "mình rõ rồi",
                "when": "lần tới",
                "wish": "luôn vui vẻ",
            },
            {
                "greeting": "chao ban",
                "time": "hôm nay",
                "help": "trả lời câu hỏi",
                "thanks": "cam on nhe",
                "when": "khi khác",
                "wish": "ngủ ngon",
            },
        ],
    },
    "entity_lookup": {
        "templates": [
            "{place} nằm chính xác ở đâu",
            "cho mình địa chỉ của {place}",
            "{place} mở cửa từ mấy giờ",
            "quán {place} đóng cửa lúc nào vậy",
            "một suất ở {place} giá khoảng bao nhiêu",
            "{place} có món gì nổi bật",
            "xin thông tin chi tiết về {place}",
            "số nhà của {place} là bao nhiêu",
            "{place} thuộc quận nào",
            "ở {place} có chỗ để xe không",
            "menu của {place} gồm những món nào",
            "{place} bán đến mấy giờ tối",
            "{place} có phục vụ buổi tối không",
            "buổi tối quán {place} còn mở cửa chứ",
            "kiểm tra giờ hoạt động cụ thể của {place}",
        ],
        "variants": [
            {"place": "Phở Thìn Bờ Hồ"},
            {"place": "Bún Chả Hương Liên"},
            {"place": "Chả Cá Thăng Long"},
            {"place": "Xôi Yến Nguyễn Hữu Huân"},
        ],
    },
    "food_search": {
        "templates": [
            "tìm quán {dish} ở {district}",
            "{district} có chỗ nào bán {dish} không",
            "lọc giúp mình hàng {dish} giá dưới {price}",
            "cho danh sách quán ăn sáng quanh {district}",
            "kiếm chỗ ăn {dish} còn mở buổi tối",
            "quán {dish} nào gần khu {district}",
            "mình cần tìm đồ ăn giá rẻ tại {district}",
            "ở {district} có quán nào mở khuya",
            "tìm hàng ăn có món {dish} và giá vừa túi tiền",
            "cho t vài quán {dish} trong quận {district}",
            "tim quan {dish} tai {district} gia duoi {price}",
            "có nhà hàng nào bán {dish} quanh {district} không",
            "cần tìm quán ăn đêm tại {district}",
            "chỗ ăn nào ở {district} vừa ngân sách {price}",
            "lọc hàng ăn đang mở quanh {district}",
        ],
        "variants": [
            {"dish": "phở bò", "district": "Cầu Giấy", "price": "50 nghìn"},
            {"dish": "bún chả", "district": "Ba Đình", "price": "70k"},
            {"dish": "cơm gà", "district": "Đống Đa", "price": "80.000 đồng"},
            {"dish": "lẩu", "district": "Hai Bà Trưng", "price": "200k"},
        ],
    },
    "recommendation": {
        "templates": [
            "gợi ý quán {dish} ngon cho {occasion}",
            "mình nên ăn ở đâu khi muốn {preference}",
            "tư vấn một quán phù hợp để {occasion}",
            "đề xuất giúp mình chỗ ăn có không gian {space}",
            "chọn hộ quán {dish} đáng thử nhất",
            "cuối tuần nên đi ăn món gì với {company}",
            "có quán nào hợp cho người thích {preference} không",
            "recommend chỗ ăn {space} để {occasion}",
            "mình phân vân không biết nên chọn quán nào cho {company}",
            "đề cử một địa điểm ăn uống thật {space}",
            "theo bạn quán {dish} nào đáng trải nghiệm",
            "giúp mình chọn nơi ăn tối phù hợp với {occasion}",
            "tư vấn chỗ ăn tốt nhất cho {company}",
            "đề xuất nơi có món {dish} hợp khẩu vị {preference}",
            "chọn giúp một địa điểm {space} cho dịp {occasion}",
        ],
        "variants": [
            {
                "dish": "đồ Việt",
                "occasion": "hẹn hò",
                "preference": "vị thanh nhẹ",
                "space": "yên tĩnh",
                "company": "người yêu",
            },
            {
                "dish": "đồ nướng",
                "occasion": "sinh nhật",
                "preference": "ăn cay",
                "space": "ấm cúng",
                "company": "nhóm bạn",
            },
            {
                "dish": "món chay",
                "occasion": "tiếp khách",
                "preference": "đồ ít dầu mỡ",
                "space": "lịch sự",
                "company": "gia đình",
            },
            {
                "dish": "hải sản",
                "occasion": "kỷ niệm",
                "preference": "khẩu vị đậm đà",
                "space": "thoáng đãng",
                "company": "đồng nghiệp",
            },
        ],
    },
    "comparison": {
        "templates": [
            "so sánh {first} với {second}",
            "{first} và {second} quán nào rẻ hơn",
            "nên chọn {first} hay {second}",
            "chỗ nào ngon hơn giữa {first} và {second}",
            "đối chiếu giá và giờ mở cửa của {first} với {second}",
            "{first} khác {second} ở điểm gì",
            "quán nào phù hợp đi nhóm hơn, {first} hay {second}",
            "so giúp mình chất lượng của {first} và {second}",
            "giữa {first} với {second}, nơi nào gần trung tâm hơn",
            "phân tích ưu nhược điểm của {first} và {second}",
            "{first} hay {second} có nhiều món hơn",
            "mình phân vân giữa {first} và {second}, so sánh giúp",
            "đánh giá {first} cùng {second} xem bên nào đáng tiền",
            "{first} với {second}, nơi nào hợp đi gia đình hơn",
            "trải nghiệm tại {first} và {second} khác nhau thế nào",
        ],
        "variants": [
            {"first": "Phở Thìn", "second": "Phở Lý Quốc Sư"},
            {"first": "Xôi Yến", "second": "Xôi Bà Thảo"},
            {"first": "Bún Chả Hương Liên", "second": "Bún Chả Đắc Kim"},
            {"first": "Chả Cá Lã Vọng", "second": "Chả Cá Thăng Long"},
        ],
    },
    "planning": {
        "templates": [
            "lập lịch ăn uống {duration} ở {district}",
            "xếp giúp mình hành trình ăn từ sáng đến tối tại {district}",
            "lên kế hoạch food tour cho {company}",
            "thiết kế lịch trình thử {count} món Hà Nội trong {duration}",
            "sắp xếp thứ tự các quán để đỡ phải di chuyển xa",
            "mình có {duration}, hãy lên lịch ăn hợp lý",
            "lập kế hoạch ăn sáng trưa tối quanh {district}",
            "tạo lịch trình khám phá ẩm thực cho {company}",
            "phân bổ ngân sách và địa điểm cho chuyến food tour {duration}",
            "xây dựng route ăn uống bắt đầu từ {district}",
            "lên lịch ghé {count} quán trong cùng một ngày",
            "giúp mình tổ chức buổi khám phá đồ ăn cho {company}",
            "sắp lịch trải nghiệm ẩm thực tại {district} trong {duration}",
            "phân bổ ngân sách cho {company} ghé {count} quán",
            "với {duration}, xếp lịch đi ăn nhiều địa điểm giúp mình",
            "lên kế hoạch dùng ngân sách hợp lý quanh {district}",
        ],
        "variants": [
            {
                "duration": "một ngày",
                "district": "Hoàn Kiếm",
                "company": "hai người",
                "count": "ba",
            },
            {
                "duration": "cuối tuần",
                "district": "Ba Đình",
                "company": "gia đình",
                "count": "bốn",
            },
            {
                "duration": "hai ngày",
                "district": "Đống Đa",
                "company": "nhóm bạn",
                "count": "năm",
            },
            {
                "duration": "một buổi tối",
                "district": "Tây Hồ",
                "company": "đồng nghiệp",
                "count": "hai",
            },
        ],
    },
    "out_of_scope": {
        "templates": [
            "dự báo thời tiết {time} thế nào",
            "viết giúp mình đoạn code {topic}",
            "giải phương trình {math}",
            "giá cổ phiếu {stock} hôm nay bao nhiêu",
            "đội nào vô địch {sport}",
            "tư vấn cách chữa bệnh {health}",
            "dịch câu này sang {language}",
            "kể mình nghe lịch sử của {landmark}",
            "đặt vé máy bay đi {destination}",
            "soạn email xin nghỉ phép giúp mình",
            "tỷ giá đô la hiện tại là bao nhiêu",
            "hướng dẫn cài đặt {software}",
            "{destination} có khách sạn nào gần biển",
            "giải thích khái niệm {topic} cho người mới",
            "triệu chứng {health} có đáng lo không",
            "kết quả trận đấu ở {sport} tối qua thế nào",
            "hướng dẫn điều trị tình trạng {health}",
        ],
        "variants": [
            {
                "time": "ngày mai",
                "topic": "Python",
                "math": "bậc hai",
                "stock": "FPT",
                "sport": "World Cup",
                "health": "đau đầu",
                "language": "tiếng Anh",
                "landmark": "Văn Miếu",
                "destination": "Đà Nẵng",
                "software": "Docker",
            },
            {
                "time": "cuối tuần",
                "topic": "JavaScript",
                "math": "hai ẩn",
                "stock": "VNM",
                "sport": "Champions League",
                "health": "mất ngủ",
                "language": "tiếng Nhật",
                "landmark": "Hồ Gươm",
                "destination": "Singapore",
                "software": "Ubuntu",
            },
            {
                "time": "tối nay",
                "topic": "SQL",
                "math": "lượng giác",
                "stock": "Tesla",
                "sport": "Ngoại hạng Anh",
                "health": "đau lưng",
                "language": "tiếng Hàn",
                "landmark": "Hoàng thành Thăng Long",
                "destination": "Bangkok",
                "software": "PostgreSQL",
            },
            {
                "time": "tuần sau",
                "topic": "React",
                "math": "tích phân",
                "stock": "Apple",
                "sport": "NBA",
                "health": "dị ứng",
                "language": "tiếng Pháp",
                "landmark": "Chùa Một Cột",
                "destination": "Tokyo",
                "software": "Git",
            },
        ],
    },
}


EVAL_SPECS = {
    "chitchat": {
        "templates": [
            "{hello}, lâu rồi không gặp",
            "chúc trợ lý một {time} thật vui",
            "{thanks}, câu trả lời dễ hiểu lắm",
            "mình đi đây, {bye}",
            "bạn vẫn đang nghe chứ",
            "{hello}, chúc bạn một {time} bình an",
        ],
        "variants": [
            {"hello": "hey bạn", "time": "ngày", "thanks": "cảm ơn nha", "bye": "tạm biệt"},
            {"hello": "alo alo", "time": "tuần", "thanks": "đa tạ", "bye": "hẹn gặp lại"},
            {"hello": "xin chao", "time": "buổi chiều", "thanks": "thank you", "bye": "bye nha"},
            {"hello": "ê chào nhé", "time": "buổi tối", "thanks": "cam on m", "bye": "gặp sau nhé"},
        ],
    },
    "entity_lookup": {
        "templates": [
            "mấy giờ {place} bắt đầu bán",
            "xin vị trí cụ thể của quán {place}",
            "ăn tại {place} hết khoảng bao nhiêu tiền",
            "{place} có mở vào buổi tối không",
            "quán {place} chuyên bán món gì vậy",
        ],
        "variants": [
            {"place": "Phở Bát Đàn"},
            {"place": "Bánh Cuốn Bà Hoành"},
            {"place": "Miến Lươn Đông Thịnh"},
            {"place": "Bún Ốc Cô Huê"},
        ],
    },
    "food_search": {
        "templates": [
            "quanh {district} tìm đâu ra {dish} dưới {price}",
            "cho danh sách địa điểm bán {dish} tại {district}",
            "cần quán ăn đêm ở khu {district}",
            "search giúp hàng {dish} bình dân gần {district}",
            "có chỗ ăn nào ở {district} hợp ngân sách {price} không",
        ],
        "variants": [
            {"district": "Thanh Xuân", "dish": "bún riêu", "price": "60k"},
            {"district": "Long Biên", "dish": "bánh cuốn", "price": "40 nghìn"},
            {"district": "Nam Từ Liêm", "dish": "cơm rang", "price": "70.000đ"},
            {"district": "Hà Đông", "dish": "gà nướng", "price": "150k"},
        ],
    },
    "recommendation": {
        "templates": [
            "chọn giúp nơi ăn {mood} cho {company}",
            "theo bạn nên thử quán nào nếu thích {taste}",
            "gợi ý địa điểm có không gian {space}",
            "mình muốn được tư vấn chỗ ăn cho dịp {occasion}",
            "đề xuất món phù hợp với người {taste}",
        ],
        "variants": [
            {"mood": "thật chill", "company": "hai vợ chồng", "taste": "ăn nhạt", "space": "có view đẹp", "occasion": "cầu hôn"},
            {"mood": "thoải mái", "company": "trẻ nhỏ", "taste": "mê đồ ngọt", "space": "rộng rãi", "occasion": "họp lớp"},
            {"mood": "ấm áp", "company": "bố mẹ", "taste": "không ăn cay", "space": "riêng tư", "occasion": "mừng thọ"},
            {"mood": "sang trọng", "company": "đối tác", "taste": "thích món truyền thống", "space": "trang nhã", "occasion": "ký hợp đồng"},
        ],
    },
    "comparison": {
        "templates": [
            "đặt {first} cạnh {second} thì nơi nào đáng tiền hơn",
            "giữa {first} và {second}, quán nào đóng cửa muộn hơn",
            "so sánh thực đơn của {first} cùng {second}",
            "{first} với {second} bên nào hợp gia đình hơn",
            "phân biệt trải nghiệm ăn tại {first} và {second}",
        ],
        "variants": [
            {"first": "Phở Bát Đàn", "second": "Phở Sướng"},
            {"first": "Bánh Cuốn Thanh Vân", "second": "Bánh Cuốn Bà Hoành"},
            {"first": "Bún Ốc Cô Huê", "second": "Bún Ốc Giang"},
            {"first": "Miến Lươn Đông Thịnh", "second": "Miến Lươn Chân Cầm"},
        ],
    },
    "planning": {
        "templates": [
            "xây lịch ăn {duration} xuất phát từ {district}",
            "chia giúp các bữa để thử đủ {count} món",
            "tổ chức food tour hợp lý cho {company}",
            "lên tuyến đường ghé nhiều hàng ăn mà không đi vòng",
            "sắp lịch ăn uống với ngân sách {budget} trong {duration}",
            "thiết kế chuyến khám phá món ngon cho {company} từ {district}",
        ],
        "variants": [
            {"duration": "nửa ngày", "district": "Cầu Giấy", "count": "bốn", "company": "ba người", "budget": "500k"},
            {"duration": "ba ngày", "district": "Hai Bà Trưng", "count": "sáu", "company": "khách nước ngoài", "budget": "hai triệu"},
            {"duration": "một buổi sáng", "district": "Long Biên", "count": "ba", "company": "một gia đình", "budget": "800 nghìn"},
            {"duration": "tối thứ bảy", "district": "Thanh Xuân", "count": "năm", "company": "nhóm sáu bạn", "budget": "1,5 triệu"},
        ],
    },
    "out_of_scope": {
        "templates": [
            "ai đang là {role} hiện nay",
            "giúp mình sửa lỗi trong code {technology}",
            "hôm nay {asset} tăng hay giảm",
            "triệu chứng {symptom} có nguy hiểm không",
            "đặt phòng khách sạn ở {city} giúp mình",
        ],
        "variants": [
            {"role": "tổng thống Mỹ", "technology": "Java", "asset": "Bitcoin", "symptom": "sốt cao", "city": "Huế"},
            {"role": "huấn luyện viên tuyển Việt Nam", "technology": "C++", "asset": "giá vàng", "symptom": "khó thở", "city": "Nha Trang"},
            {"role": "CEO của Microsoft", "technology": "Node.js", "asset": "VN-Index", "symptom": "đau ngực", "city": "Đà Lạt"},
            {"role": "thủ tướng Nhật Bản", "technology": "FastAPI", "asset": "Ethereum", "symptom": "chóng mặt", "city": "Phú Quốc"},
        ],
    },
}


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def candidates(spec: dict) -> list[str]:
    return [
        template.format(**variant)
        for template in spec["templates"]
        for variant in spec["variants"]
    ]


def load_train() -> list[dict]:
    return [
        json.loads(line)
        for line in TRAIN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_eval() -> list[dict]:
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))


def append_train(rows: list[dict]) -> None:
    counts = Counter(row["label"] for row in rows)
    seen = {normalize_text(row["text"]) for row in rows}

    for label, spec in TRAIN_SPECS.items():
        for text in candidates(spec):
            if counts[label] >= TRAIN_TARGET_PER_INTENT:
                break
            normalized = normalize_text(text)
            if normalized in seen:
                continue
            rows.append(
                {
                    "text": text,
                    "label": label,
                    "group_id": (
                        f"expanded_{label}_{counts[label] + 1:03d}"
                    ),
                }
            )
            counts[label] += 1
            seen.add(normalized)

    if any(counts[label] < TRAIN_TARGET_PER_INTENT for label in TRAIN_SPECS):
        raise RuntimeError(f"Insufficient training candidates: {counts}")


def append_eval(rows: list[dict], train_rows: list[dict]) -> None:
    counts = Counter(row["expected_intent"] for row in rows)
    train_texts = {normalize_text(row["text"]) for row in train_rows}
    seen = {normalize_text(row["text"]) for row in rows}

    for label, spec in EVAL_SPECS.items():
        sequence = 1
        for text in candidates(spec):
            if counts[label] >= EVAL_TARGET_PER_INTENT:
                break
            normalized = normalize_text(text)
            if normalized in seen or normalized in train_texts:
                continue
            rows.append(
                {
                    "id": f"router-aug-{label}-{sequence:03d}",
                    "text": text,
                    "expected_intent": label,
                }
            )
            sequence += 1
            counts[label] += 1
            seen.add(normalized)

    if any(counts[label] < EVAL_TARGET_PER_INTENT for label in EVAL_SPECS):
        raise RuntimeError(f"Insufficient evaluation candidates: {counts}")


def main() -> None:
    train_rows = load_train()
    eval_rows = load_eval()
    append_train(train_rows)
    append_eval(eval_rows, train_rows)

    TRAIN_PATH.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in train_rows
        ),
        encoding="utf-8",
    )
    EVAL_PATH.write_text(
        json.dumps(eval_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    train_counts = Counter(row["label"] for row in train_rows)
    eval_counts = Counter(row["expected_intent"] for row in eval_rows)
    print(f"train={len(train_rows)} {dict(sorted(train_counts.items()))}")
    print(f"eval={len(eval_rows)} {dict(sorted(eval_counts.items()))}")


if __name__ == "__main__":
    main()
