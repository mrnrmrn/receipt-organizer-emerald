from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from receipt_app.models import OCRResult, ParsedReceipt

AMOUNT_PATTERNS = (
    re.compile(r"합계\s*[:：]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})\s*원?"),
    re.compile(r"총\s*금액\s*[:：]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})\s*원?"),
    re.compile(r"결제\s*금액\s*[:：]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})\s*원?"),
    re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})\s*원"),
)

DATE_PATTERNS = (
    re.compile(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"),
    re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    re.compile(r"(\d{1,2})[./-](\d{1,2})"),
)

SKIP_VENDOR_PATTERNS = (
    re.compile(
        r"사업자|승인|카드|합계|금액|매출|부가세|단말기|영수증|거래|전화|주소|가맹점"
    ),
    re.compile(r"^[0-9\s:./,-]+$"),
)


@dataclass
class ReceiptParser:
    def parse(self, ocr_result: OCRResult) -> ParsedReceipt:
        text = ocr_result.text.strip()
        lines = ocr_result.lines or [
            line.strip() for line in text.splitlines() if line.strip()
        ]
        amount = self._extract_amount(text, lines)
        receipt_date = self._extract_date(text)
        vendor = self._extract_vendor(lines)
        return ParsedReceipt(
            source_file_name=ocr_result.source_file_name,
            raw_text=text,
            amount=amount,
            receipt_date=receipt_date,
            vendor=vendor,
            notes=None,
        )

    def _extract_amount(self, text: str, lines: list[str]) -> Decimal | None:
        for pattern in AMOUNT_PATTERNS:
            match = pattern.search(text)
            if match:
                return Decimal(match.group(1).replace(",", ""))

        hinted_candidates: list[Decimal] = []
        plain_candidates: list[Decimal] = []
        for line in lines:
            compact_line = line.replace(" ", "")
            if any(
                token in compact_line
                for token in ("사업자", "승인번호", "카드번호", "전화", "현금영수증")
            ):
                continue

            has_amount_hint = any(
                token in compact_line
                for token in (
                    "합계",
                    "총금액",
                    "결제금액",
                    "받을금액",
                    "청구금액",
                    "거래금액",
                )
            )
            for match in re.finditer(
                r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})", compact_line
            ):
                value = Decimal(match.group(1).replace(",", ""))
                if not Decimal("1000") <= value <= Decimal("10000000"):
                    continue
                if has_amount_hint:
                    hinted_candidates.append(value)
                else:
                    plain_candidates.append(value)

        if hinted_candidates:
            return max(hinted_candidates)
        if plain_candidates:
            return max(plain_candidates)
        return None

    def _extract_date(self, text: str) -> date | None:
        for index, pattern in enumerate(DATE_PATTERNS):
            match = pattern.search(text)
            if not match:
                continue

            groups = [int(value) for value in match.groups()]
            if index < 2:
                year, month, day = groups
            else:
                year = date.today().year
                month, day = groups
            try:
                return date(year, month, day)
            except ValueError:
                continue
        return None

    def _extract_vendor(self, lines: list[str]) -> str | None:
        for raw_line in lines:
            line = raw_line.strip(" -*_=·•\t")
            if len(line) < 2:
                continue
            if any(pattern.search(line) for pattern in SKIP_VENDOR_PATTERNS):
                continue
            return line[:60]
        return None

def parse_receipt_text(ocr_result: OCRResult) -> ParsedReceipt:
    parser = ReceiptParser()
    return parser.parse(ocr_result)
