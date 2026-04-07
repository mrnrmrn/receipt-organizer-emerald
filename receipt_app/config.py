from __future__ import annotations

from dataclasses import dataclass, field


GUIDE_NOTICE_TEXT = (
    "회사는 구성원의 업무 편의 향상을 위해, 개인의 업무과 직/간접적으로 연관된 지출 항목에 대해서 최대 월 15만원까지 지원합니다.\n"
    "업무지원비로 승인된 건에 대해서는 다음 급여일에 정산하여 지급합니다.\n"
    "사용 금액이 청구 가능한 금액보다 큰 경우, 부분 청구가 가능합니다 (예: 169000원 음식점 이용시, 150000원 부분 청구 가능)\n"
    "당월에 사용하지 않은 업무 지원금은 이월되지 않습니다.\n"
    "해당 월에 장기 휴직등으로 인해 근무하지 않은 경우, 업무지원금 사용이 불가능합니다.\n"
    "본인 외 사용 건에 대해서는 비용 청구를 금지하며, 타인과 공동으로 사용한 금액에 대해서 결재를 요청 할 경우, 본인이 사용한 금액에 대해서만 별도로 영수증/구매내역등을 통해 증빙하여 청구 금액을 작성합니다.\n"
    "각 지출 항목에 대해 각 번호에 해당되는 증빙자료 혹은 영수증을 반드시 첨부해야만 승인이 가능합니다. (지류 영수증, 배달 내역 캡쳐, 카드청구이력 캡쳐 등)\n"
    "기안자가 청구한 내용에 대하여 업무연관성 소명을 요구할 수 있으며, 소명이 어려운 경우 본 결재건을 반려할 수 있습니다.\n"
    "여러 개월에 걸쳐 사용 가능한 상품 (예: 헬스장 1년권)의 경우 매 개월마다, 전체 금액을 사용 개월 수로 균등하게 분할한 금액을 회차별로 나누어 신청 합니다."
)


@dataclass(frozen=True)
class GuideRow:
    category: str | None = None
    subcategory: str | None = None
    note: str | None = None
    merge_category: str | None = None
    merge_note: str | None = None
    row_height: float | None = None
    note_wrap: bool = False


@dataclass(frozen=True)
class AppConfig:
    sheet_name: str = "항목"
    guide_sheet_name: str = "비목 안내"
    operator_name_cell: str = "C2"
    total_amount_cell: str = "C3"
    month_cell: str = "C4"
    header_value_merge_ranges: tuple[str, ...] = ("C2:D2", "C3:D3", "C4:D4")
    table_header_row: int = 6
    table_start_row: int = 7
    table_formula_end_row: int = 28
    table_border_end_row: int = 29
    numbered_table_end_row: int = 26
    number_column: str = "B"
    category_column: str = "C"
    subcategory_column: str = "D"
    amount_column: str = "E"
    image_header_range: str = "G2:K2"
    image_anchor_columns: tuple[str, ...] = ("G", "H", "I", "J", "K")
    image_numbering_rows: tuple[int, ...] = (3, 30, 57, 84)
    image_slot_merge_ranges: tuple[str, ...] = (
        "H4:H29",
        "I4:I29",
        "J4:J29",
        "K4:K29",
        "G31:G56",
        "H31:H56",
        "I31:I56",
        "J31:J56",
        "K31:K56",
        "G58:G83",
        "H58:H83",
        "I58:I83",
        "J58:J83",
        "K58:K83",
        "G85:G110",
        "H85:H110",
        "I85:I110",
        "J85:J110",
        "K85:K110",
    )
    image_anchor_cells: tuple[str, ...] = (
        "G4",
        "H4",
        "I4",
        "J4",
        "K4",
        "G31",
        "H31",
        "I31",
        "J31",
        "K31",
        "G58",
        "H58",
        "I58",
        "J58",
        "K58",
        "G85",
        "H85",
        "I85",
        "J85",
        "K85",
    )
    image_max_width_px: int = 260
    image_max_height_px: int = 460
    max_receipt_images: int = 20
    tesseract_languages: str = "kor+eng"
    category_rules: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {
            "택시": ("교통비", "택시"),
            "카카오택시": ("교통비", "택시"),
            "주차": ("교통비", "택시"),
            "버스": ("교통비", "대중교통"),
            "지하철": ("교통비", "대중교통"),
            "철도": ("교통비", "대중교통"),
            "ktx": ("교통비", "대중교통"),
            "티머니": ("교통비", "대중교통"),
            "tmoney": ("교통비", "대중교통"),
            "식대": ("식비", "음식점"),
            "식사": ("식비", "음식점"),
            "배달": ("식비", "배달"),
            "카페": ("식비", "음식점"),
            "커피": ("식비", "음식점"),
            "병원": ("자기관리", "의료/치료"),
            "치과": ("자기관리", "의료/치료"),
            "약국": ("자기관리", "의료/치료"),
            "미용": ("자기관리", "헤어"),
            "헬스": ("자기관리", "운동"),
            "운동": ("자기관리", "운동"),
            "통신": ("통신비", "통신비"),
            "u+": ("통신비", "통신비"),
            "lg u+": ("통신비", "통신비"),
            "kt": ("통신비", "통신비"),
            "skt": ("통신비", "통신비"),
        }
    )
    guide_rows: tuple[GuideRow, ...] = (
        # row 1 – blank (styled separately)
        GuideRow(row_height=18.0),
        # row 2 – header (styled separately)
        GuideRow(row_height=18.0),
        # row 3 – 자기관리 / 의료치료
        GuideRow(
            category="자기관리",
            subcategory="의료/치료",
            note="치과치료, 물리치료 등 일반 의료 목적에 사용한 비용 청구 가능\n여러 개월에 걸쳐 사용 가능한 회원권 (예: 헬스장 1년권)의 경우 매 개월마다, 전체 금액을 사용 개월 수로 균등하게 분할한 금액을 회차별로 나누어 신청",
            merge_category="B3:B5",
            merge_note="D3:D5",
            row_height=34.5,
            note_wrap=True,
        ),
        # row 4
        GuideRow(subcategory="헤어", row_height=34.5),
        # row 5
        GuideRow(subcategory="운동", row_height=34.5),
        # row 6 – 식비 / 음식점
        GuideRow(
            category="식비",
            subcategory="음식점",
            note="음식점 사용시 일반음식점만 청구 가능\n주류는 청구 불가. 주류 금액은 제외하여 청구.\n사내 다른 팀원과 함께 이용한 금액에 대해서는 N할로 분할하여 청구하고, 인보이스(영수증/구매내역) 제출 필요",
            merge_category="B6:B7",
            merge_note="D6:D7",
            row_height=43.5,
            note_wrap=True,
        ),
        # row 7
        GuideRow(subcategory="배달", row_height=43.5),
        # row 8 – 통신비
        GuideRow(
            category="통신비",
            subcategory="통신비",
            note="개인 및 업무 장비에 사용한 통신요금 포함",
            row_height=24.75,
            note_wrap=False,
        ),
        # row 9 – 교통비 / 대중교통
        GuideRow(
            category="교통비",
            subcategory="대중교통",
            note="택시의 경우 다른 회사 구성원과 함께에 탑승한 경우, 해당 동승인 인원만큼 나누어 개인별로 청구",
            merge_category="B9:B10",
            merge_note="D9:D10",
            row_height=24.0,
            note_wrap=True,
        ),
        # row 10
        GuideRow(subcategory="택시", row_height=24.0),
        # row 11 – blank separator
        GuideRow(row_height=18.0),
        # row 12 – 유의사항 header
        GuideRow(category="유의사항", merge_category="B12:D12", row_height=18.0),
        # row 13 – notice text (merged B13:D20)
        GuideRow(
            category=GUIDE_NOTICE_TEXT,
            merge_category="B13:D20",
            row_height=18.0,
            note_wrap=True,
        ),
        # rows 14-19 – continuation of merge (heights set for completeness)
        GuideRow(row_height=18.0),
        GuideRow(row_height=18.0),
        GuideRow(row_height=18.0),
        GuideRow(row_height=18.0),
        GuideRow(row_height=18.0),
        GuideRow(row_height=18.0),
        # row 20 – last row of notice merge
        GuideRow(row_height=99.0),
    )


DEFAULT_CONFIG = AppConfig()
