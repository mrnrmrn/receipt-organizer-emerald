from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
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
        "Backend package import failed.\n\n"
        "Expected: receipt_app.config, receipt_app.models, receipt_app.ocr, "
        "receipt_app.parse.receipt_parser, receipt_app.export.excel_export\n\n"
        f"Import error: {type(e).__name__}: {e}"
    )
    st.stop()


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
    elif dataclasses.is_dataclass(row):
        data = dataclasses.asdict(row)
    elif hasattr(row, "model_dump") and callable(getattr(row, "model_dump")):
        data = row.model_dump()
    elif hasattr(row, "dict") and callable(getattr(row, "dict")):
        data = row.dict()
    elif hasattr(row, "__dict__"):
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
        amount_value = d.get("amount")
        if amount_value in (None, ""):
            continue

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
                amount=Decimal(str(amount_value).replace(",", "").strip()),
                vendor=d.get("vendor") or None,
                receipt_date=receipt_date,
                notes=d.get("notes") or None,
            )
        )
    return out


def _uploads_as_receipts(uploads: list[dict[str, Any]]) -> list[Any]:
    return [
        models.UploadedReceipt(
            file_name=upload["name"],
            image_bytes=upload["bytes"],
            mime_type=upload.get("type") or "image/png",
        )
        for upload in uploads
    ]


def _tesseract_hint(err: Exception) -> str | None:
    msg = f"{type(err).__name__}: {err}".lower()
    if "tesseract" not in msg:
        return None
    return (
        "Tesseract is missing in the current runtime.\n\n"
        "- Streamlit Community Cloud: add `packages.txt` in the repo root with `tesseract-ocr` and `tesseract-ocr-kor`, then redeploy\n"
        "- Local macOS: `brew install tesseract`\n"
        "- Local Ubuntu/Debian: `sudo apt-get install tesseract-ocr`\n"
        "- Local Windows: install Tesseract and ensure `tesseract` is on PATH\n"
    )


def main() -> None:
    st.set_page_config(
        page_title=getattr(config, "APP_TITLE", "Receipt organizer"), layout="wide"
    )
    _init_state()

    st.title(getattr(config, "APP_TITLE", "Receipt organizer"))
    st.caption("Upload -> Process -> Review -> Download")

    with st.expander("OCR / Tesseract", expanded=False):
        st.write(
            "This app uses a Tesseract-based OCR backend. On Streamlit Community Cloud, "
            "the runtime needs system packages declared in `packages.txt`."
        )
        st.code(
            "# packages.txt (repo root)\n"
            "tesseract-ocr\n"
            "tesseract-ocr-kor\n\n"
            "# local macOS only\n"
            "brew install tesseract\n",
            language="bash",
        )

    if not st.session_state.person_name:
        st.subheader("1) Your name")
        with st.form("name_form", clear_on_submit=False):
            name = st.text_input("Required", placeholder="e.g. Alex Kim")
            submitted = st.form_submit_button("Continue")
        if submitted:
            if not name.strip():
                st.error("Please enter your name to continue.")
            else:
                st.session_state.person_name = name.strip()
                st.rerun()
        st.stop()

    st.subheader("2) Upload receipts")
    st.write(f"Name: **{st.session_state.person_name}**")
    selected_date = st.date_input(
        "Report date",
        value=st.session_state.report_date,
        format="YYYY-MM-DD",
    )
    if selected_date != st.session_state.report_date:
        st.session_state.report_date = selected_date
        st.session_state.workbook_bytes = None
        st.session_state.workbook_filename = None

    uploaded_files = st.file_uploader(
        "Upload PNG/JPG receipts",
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
        st.info("Upload one or more receipt images to continue.")
        st.stop()

    st.caption("Preview")
    cols = st.columns(3)
    for i, u in enumerate(st.session_state.uploads):
        with cols[i % 3]:
            st.image(u["bytes"], caption=u["name"], use_container_width=True)

    st.subheader("3) Process")
    process_clicked = st.button("Process", type="primary")
    if process_clicked:
        st.session_state.last_error = None
        all_rows: list[Any] = []
        ocr_text_by_file: dict[str, str] = {}
        tesseract_hint: str | None = None

        progress = st.progress(0)
        with st.spinner("Running OCR and parsing receipts..."):
            try:
                ocr_backend = get_ocr_backend()
            except Exception as e:
                st.session_state.last_error = (
                    f"Failed to initialize OCR backend: {type(e).__name__}: {e}"
                )
                st.error(st.session_state.last_error)
                hint = _tesseract_hint(e)
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
                    hint = _tesseract_hint(e)
                    if hint and tesseract_hint is None:
                        tesseract_hint = hint
                finally:
                    progress.progress(idx / max(total, 1))

        if tesseract_hint:
            st.warning(tesseract_hint)

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
        with st.expander("OCR text (per receipt)", expanded=False):
            for fname, text in st.session_state.ocr_text_by_file.items():
                st.markdown(f"**{fname}**")
                st.text(text if isinstance(text, str) else str(text))

    if not st.session_state.rows_for_edit:
        st.info("Click **Process** to extract rows from your receipts.")
        st.stop()

    st.subheader("4) Review / edit")
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

    st.subheader("5) Download Excel")
    if st.session_state.workbook_bytes is None:
        try:
            with st.spinner("Building workbook..."):
                export_rows = _rows_for_export(st.session_state.rows_for_edit)
                wb = build_workbook_bytes(
                    person_name=st.session_state.person_name,
                    rows=export_rows,
                    receipts=_uploads_as_receipts(st.session_state.uploads),
                    month=st.session_state.report_date,
                    template_path="template.xlsx",
                )
                st.session_state.workbook_bytes = wb
                safe_name = "_".join(st.session_state.person_name.split())
                month = st.session_state.report_date.strftime("%Y-%m")
                st.session_state.workbook_filename = (
                    f"{safe_name}_{month}_receipts.xlsx"
                )
        except Exception as e:
            st.session_state.last_error = (
                f"Failed to build workbook: {type(e).__name__}: {e}"
            )
            st.error(st.session_state.last_error)
            st.stop()

    st.download_button(
        "Download Excel",
        data=st.session_state.workbook_bytes,
        file_name=st.session_state.workbook_filename or "receipts.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )


if __name__ == "__main__":
    main()
