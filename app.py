from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from decimal import Decimal

import streamlit as st

try:
    import receipt_app.config as config
    import receipt_app.models as models
    from receipt_app.export.excel_export import build_workbook_bytes
    from receipt_app.ocr import get_ocr_backend
    from receipt_app.parse.receipt_parser import parse_receipt_text
except Exception as e:
    st.error(
        "백엔드 패키지를 불러오지 못했습니다.\n\n"
        "필요 모듈: receipt_app.config, receipt_app.models, receipt_app.ocr, "
        "receipt_app.parse.receipt_parser, receipt_app.export.excel_export\n\n"
        f"에러: {type(e).__name__}: {e}"
    )
    st.stop()


APP_TITLE_KO = "TBU 업무지원금 신청"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("person_name", "")
    ss.setdefault("report_date", dt.date.today())
    ss.setdefault("uploads", [])
    ss.setdefault("uploads_fingerprint", "")
    ss.setdefault("ocr_text_by_file", {})
    ss.setdefault("parsed_rows", [])
    ss.setdefault("rows_for_edit", [])
    ss.setdefault("rows_fingerprint", "")
    ss.setdefault("workbook_bytes", None)
    ss.setdefault("workbook_filename", None)
    ss.setdefault("last_error", None)


def _uploads_from_uploader(uploaded_files: list[Any] | None) -> list[dict[str, Any]]:
    if not uploaded_files:
        return []
    uploads: list[dict[str, Any]] = []
    for f in uploaded_files:
        data = f.getvalue() if hasattr(f, "getvalue") else f.read()
        uploads.append(
            {
                "name": getattr(f, "name", "receipt"),
                "type": getattr(f, "type", ""),
                "bytes": data,
                "sha": _sha256(data),
            }
        )
    return uploads


def _uploads_fingerprint(uploads: list[dict[str, Any]]) -> str:
    return "|".join(f"{u['name']}:{u['sha']}" for u in uploads)


def _rows_fingerprint(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return _sha256(payload.encode("utf-8"))


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        data = dict(row)
    elif dataclasses.is_dataclass(row) and not isinstance(row, type):
        data = dataclasses.asdict(row)
    elif (
        not isinstance(row, type)
        and hasattr(row, "model_dump")
        and callable(getattr(row, "model_dump"))
    ):
        data = row.model_dump()
    elif (
        not isinstance(row, type)
        and hasattr(row, "dict")
        and callable(getattr(row, "dict"))
    ):
        data = row.dict()
    elif not isinstance(row, type) and hasattr(row, "__dict__"):
        data = {k: v for k, v in vars(row).items() if not k.startswith("_")}
    else:
        data = {"value": row}

    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, Decimal):
            normalized[key] = (
                int(value) if value == value.to_integral_value() else float(value)
            )
        elif isinstance(value, dt.date):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def _coerce_editor_rows(edited: Any) -> list[dict[str, Any]]:
    if edited is None:
        return []
    if isinstance(edited, list):
        out: list[dict[str, Any]] = []
        for r in edited:
            out.append(dict(r) if isinstance(r, dict) else _row_to_dict(r))
        return out
    if hasattr(edited, "to_dict") and callable(getattr(edited, "to_dict")):
        try:
            return list(edited.to_dict(orient="records"))
        except TypeError:
            return list(edited.to_dict())
    if isinstance(edited, dict):
        return [dict(edited)]
    return [_row_to_dict(edited)]


def _rows_for_export(edited_rows: list[dict[str, Any]]) -> list[Any]:
    row_cls = getattr(models, "ExportRow", None)
    if row_cls is None:
        return list(edited_rows)

    out: list[Any] = []
    for index, d in enumerate(edited_rows, start=1):
        amount = _coerce_amount_value(d.get("amount"))

        receipt_date = d.get("receipt_date")
        if isinstance(receipt_date, str) and receipt_date:
            try:
                receipt_date = dt.date.fromisoformat(receipt_date[:10])
            except ValueError:
                receipt_date = None

        out.append(
            row_cls(
                number=index,
                category=(d.get("category") or "기타").strip(),
                subcategory=(d.get("subcategory") or "기타").strip(),
                amount=amount,
                vendor=d.get("vendor") or None,
                receipt_date=receipt_date,
                notes=d.get("notes") or None,
            )
        )
    return out


def _coerce_amount_value(raw_amount: Any) -> Decimal:
    if raw_amount in (None, ""):
        return Decimal("0")
    if isinstance(raw_amount, Decimal):
        return Decimal("0") if raw_amount.is_nan() else raw_amount
    if isinstance(raw_amount, float) and math.isnan(raw_amount):
        return Decimal("0")

    normalized = str(raw_amount).replace(",", "").strip()
    if not normalized or normalized.lower() == "nan":
        return Decimal("0")
    return Decimal(normalized)


def _uploads_as_receipts(uploads: list[dict[str, Any]]) -> list[Any]:
    return [
        models.UploadedReceipt(
            file_name=upload["name"],
            image_bytes=upload["bytes"],
            mime_type=upload.get("type") or "image/png",
        )
        for upload in uploads
    ]


def _ocr_init_hint(err: Exception) -> str | None:
    msg = f"{type(err).__name__}: {err}".lower()
    if "gemini" in msg or "google" in msg or "api key" in msg:
        return (
            "Gemini API 키가 없거나 올바르지 않을 수 있습니다.\n\n"
            "Streamlit secrets(`.streamlit/secrets.toml`)에 추가하세요:\n"
            "```\n"
            'GEMINI_API_KEY = "your-key-here"\n'
            'GEMINI_MODEL = "gemini-2.5-flash"\n'
            "```\n"
            "또는 서버 환경변수 `GEMINI_API_KEY`, `GEMINI_MODEL`을 설정하세요.\n"
            "키 발급: https://aistudio.google.com/app/apikey\n"
        )
    return None


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE_KO,
        layout="wide",
    )
    _init_state()

    st.title(APP_TITLE_KO)
    st.caption("업로드 → 추출 → 검토 및 수정 → 다운로드")

    st.subheader("정보를 입력해 주세요")
    with st.form("info_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            raw_name = st.text_input(
                "이름",
                value=st.session_state.person_name or "",
                placeholder="김일렉",
            )
            name = raw_name or ""
        with c2:
            selected_date = st.date_input(
                "작성일",
                value=st.session_state.report_date,
                format="YYYY-MM-DD",
            )
        submitted = st.form_submit_button("계속")

    if submitted:
        if not name.strip():
            st.error("이름을 입력해 주세요.")
        else:
            next_name = name.strip()
            changed = (
                next_name != st.session_state.person_name
                or selected_date != st.session_state.report_date
            )
            st.session_state.person_name = next_name
            st.session_state.report_date = selected_date
            if changed:
                st.session_state.workbook_bytes = None
                st.session_state.workbook_filename = None
            st.rerun()

    if not st.session_state.person_name:
        st.info("이름과 작성일을 입력한 뒤 계속 진행해 주세요.")
        st.stop()

    st.subheader("영수증을 첨부해 주세요")
    st.caption(
        f"신청자: **{st.session_state.person_name}** · 작성일: **{st.session_state.report_date.isoformat()}**"
    )

    uploaded_files = st.file_uploader(
        "영수증 이미지 업로드 (PNG/JPG)",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    uploads = _uploads_from_uploader(uploaded_files)
    fp = _uploads_fingerprint(uploads)
    if fp != st.session_state.uploads_fingerprint:
        st.session_state.uploads = uploads
        st.session_state.uploads_fingerprint = fp
        st.session_state.ocr_text_by_file = {}
        st.session_state.parsed_rows = []
        st.session_state.rows_for_edit = []
        st.session_state.rows_fingerprint = ""
        st.session_state.workbook_bytes = None
        st.session_state.workbook_filename = None
        st.session_state.last_error = None

    if not st.session_state.uploads:
        st.info("영수증 이미지를 1장 이상 업로드해 주세요.")
        st.stop()

    st.caption("미리보기")
    cols = st.columns(3)
    for i, u in enumerate(st.session_state.uploads):
        with cols[i % 3]:
            st.image(u["bytes"], caption=u["name"], use_container_width=True)

    st.subheader("추출")
    process_clicked = st.button("시작", type="primary")
    if process_clicked:
        st.session_state.last_error = None
        all_rows: list[Any] = []
        ocr_text_by_file: dict[str, str] = {}
        ocr_hint: str | None = None

        progress = st.progress(0)
        with st.spinner("영수증을 인식하고 항목을 추출하는 중..."):
            try:
                ocr_backend = get_ocr_backend()
            except Exception as e:
                st.session_state.last_error = (
                    f"OCR 백엔드를 초기화하지 못했습니다: {type(e).__name__}: {e}"
                )
                st.error(st.session_state.last_error)
                hint = _ocr_init_hint(e)
                if hint:
                    st.warning(hint)
                st.stop()

            total = len(st.session_state.uploads)
            for idx, u in enumerate(st.session_state.uploads, start=1):
                try:
                    receipt = models.UploadedReceipt(
                        file_name=u["name"],
                        image_bytes=u["bytes"],
                        mime_type=u.get("type") or "image/png",
                    )
                    ocr_result = ocr_backend.extract_text(receipt)
                    ocr_text_by_file[u["name"]] = ocr_result.text

                    parsed = parse_receipt_text(ocr_result)
                    all_rows.append(parsed)
                except Exception as e:
                    ocr_text_by_file[u["name"]] = f"[ERROR] {type(e).__name__}: {e}"
                    hint = _ocr_init_hint(e)
                    if hint and ocr_hint is None:
                        ocr_hint = hint
                finally:
                    progress.progress(idx / max(total, 1))

        if ocr_hint:
            st.warning(ocr_hint)

        st.session_state.ocr_text_by_file = ocr_text_by_file
        st.session_state.parsed_rows = all_rows
        st.session_state.rows_for_edit = [_row_to_dict(r) for r in all_rows]
        st.session_state.rows_fingerprint = _rows_fingerprint(
            st.session_state.rows_for_edit
        )
        st.session_state.workbook_bytes = None
        st.session_state.workbook_filename = None

    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    if st.session_state.ocr_text_by_file:
        with st.expander("OCR 원문 (영수증별)", expanded=False):
            for fname, text in st.session_state.ocr_text_by_file.items():
                st.markdown(f"**{fname}**")
                st.text(text if isinstance(text, str) else str(text))

    if not st.session_state.rows_for_edit:
        st.info("**시작**을 눌러 영수증에서 항목을 추출하세요.")
        st.stop()

    st.subheader("검토 및 수정")
    edited = st.data_editor(
        st.session_state.rows_for_edit,
        num_rows="dynamic",
        use_container_width=True,
        key="rows_editor",
    )
    edited_rows = _coerce_editor_rows(edited)
    edited_fp = _rows_fingerprint(edited_rows)
    if edited_fp != st.session_state.rows_fingerprint:
        st.session_state.rows_for_edit = edited_rows
        st.session_state.rows_fingerprint = edited_fp
        st.session_state.workbook_bytes = None
        st.session_state.workbook_filename = None

    st.subheader("다운로드")
    if st.session_state.workbook_bytes is None:
        try:
            with st.spinner("엑셀 파일을 생성하는 중..."):
                export_rows = _rows_for_export(st.session_state.rows_for_edit)
                wb = build_workbook_bytes(
                    person_name=st.session_state.person_name,
                    rows=export_rows,
                    receipts=_uploads_as_receipts(st.session_state.uploads),
                    month=st.session_state.report_date,
                    template_path="template.xlsx",
                )
                st.session_state.workbook_bytes = wb
                safe_name = "".join(st.session_state.person_name.split())
                month = st.session_state.report_date.strftime("%Y-%m")
                st.session_state.workbook_filename = (
                    f"{safe_name}-{month}-업무지원금신청.xlsx"
                )
        except Exception as e:
            st.session_state.last_error = (
                f"엑셀 생성에 실패했습니다: {type(e).__name__}: {e}"
            )
            st.error(st.session_state.last_error)
            st.stop()

    st.download_button(
        "다운로드",
        data=st.session_state.workbook_bytes,
        file_name=st.session_state.workbook_filename or "업무지원금신청.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )


if __name__ == "__main__":
    main()
