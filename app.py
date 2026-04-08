from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

import streamlit as st

try:
    import receipt_app.models as models
    from receipt_app.export import build_pdf_archive, build_pdf_filename
    from receipt_app.ocr import get_ocr_backend
    from receipt_app.parse.receipt_parser import parse_receipt_text
except Exception as e:
    st.error(
        "백엔드 패키지를 불러오지 못했습니다.\n\n"
        "필요 모듈: receipt_app.models, receipt_app.ocr, "
        "receipt_app.parse.receipt_parser, receipt_app.export\n\n"
        f"에러: {type(e).__name__}: {e}"
    )
    st.stop()


APP_TITLE_KO = "에메랄드 영수증"
OCR_MAX_WORKERS = 4


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("person_name", "")
    ss.setdefault("uploads", [])
    ss.setdefault("uploads_fingerprint", "")
    ss.setdefault("processed_receipts", [])
    ss.setdefault("ocr_text_by_file", {})
    ss.setdefault("parsed_receipts", [])
    ss.setdefault("rows_for_edit", [])
    ss.setdefault("pdf_archive_bytes", None)
    ss.setdefault("pdf_archive_filename", None)
    ss.setdefault("generated_pdf_names", [])
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


def _uploads_as_receipts(uploads: list[dict[str, Any]]) -> list[models.UploadedReceipt]:
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


def _archive_basename(uploads: list[dict[str, Any]]) -> str:
    if not uploads:
        return "receipts"
    if len(uploads) == 1:
        return uploads[0]["name"].rsplit(".", 1)[0] or "receipt"
    return f"receipts_{len(uploads)}"


def _sanitize_person_name(value: str) -> str:
    return " ".join(value.split()).strip()


def _parsed_receipt_to_row(
    upload: dict[str, Any],
    parsed: models.ParsedReceipt | None,
) -> dict[str, Any]:
    if parsed is None:
        return {
            "source_file_name": upload["name"],
            "receipt_date": None,
            "category": "etc",
            "amount": None,
            "task_name": "",
        }

    return {
        "source_file_name": parsed.source_file_name,
        "receipt_date": parsed.receipt_date.isoformat() if parsed.receipt_date else None,
        "category": parsed.category,
        "amount": int(parsed.amount) if parsed.amount is not None else None,
        "task_name": parsed.task_name or "",
    }


def _coerce_receipt_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _coerce_amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _rows_to_parsed_receipts(rows: list[dict[str, Any]]) -> list[models.ParsedReceipt]:
    parsed_receipts: list[models.ParsedReceipt] = []
    for row in rows:
        parsed_receipts.append(
            models.ParsedReceipt(
                source_file_name=str(row.get("source_file_name") or ""),
                raw_text="",
                receipt_date=_coerce_receipt_date(row.get("receipt_date")),
                category=str(row.get("category") or "etc"),
                amount=_coerce_amount(row.get("amount")),
                receipt_box=None,
                task_name=str(row.get("task_name") or "").strip() or None,
                notes=None,
            )
        )
    return parsed_receipts


def _missing_task_name_files(rows: list[dict[str, Any]]) -> list[str]:
    return [
        str(row.get("source_file_name") or "")
        for row in rows
        if not str(row.get("task_name") or "").strip()
    ]


def _extract_single_receipt(upload: dict[str, Any]) -> tuple[dict[str, Any], models.ParsedReceipt]:
    receipt = models.UploadedReceipt(
        file_name=upload["name"],
        image_bytes=upload["bytes"],
        mime_type=upload.get("type") or "image/png",
    )
    ocr_result = get_ocr_backend().extract_text(receipt)
    parsed = parse_receipt_text(ocr_result)
    return {"text": ocr_result.text}, parsed


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE_KO,
        layout="wide",
    )
    _init_state()

    st.title(APP_TITLE_KO)
    st.caption("업로드 → OCR 추출 → PDF 변환 → ZIP 다운로드")

    st.subheader("이름을 입력해 주세요")
    person_name_input = st.text_input(
        "이름",
        value=st.session_state.person_name,
        placeholder="김에메",
    )
    normalized_person_name = _sanitize_person_name(person_name_input)
    if normalized_person_name != st.session_state.person_name:
        st.session_state.person_name = normalized_person_name
        st.session_state.pdf_archive_bytes = None
        st.session_state.pdf_archive_filename = None
        st.session_state.generated_pdf_names = []

    if not st.session_state.person_name:
        st.info("이름을 입력한 뒤 진행해 주세요.")
        st.stop()

    st.subheader("영수증을 첨부해 주세요")

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
        st.session_state.processed_receipts = []
        st.session_state.ocr_text_by_file = {}
        st.session_state.parsed_receipts = []
        st.session_state.rows_for_edit = []
        st.session_state.pdf_archive_bytes = None
        st.session_state.pdf_archive_filename = None
        st.session_state.generated_pdf_names = []
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
    process_clicked = st.button("추출하기", type="primary")
    if process_clicked:
        st.session_state.last_error = None
        all_receipts: list[Any] = []
        rows_for_edit: list[dict[str, Any]] = []
        ocr_text_by_file: dict[str, str] = {}
        ocr_hint: str | None = None

        progress = st.progress(0)
        with st.spinner("영수증을 인식하고 항목을 추출하는 중..."):
            total = len(st.session_state.uploads)
            results_by_index: dict[int, tuple[str, models.ParsedReceipt]] = {}
            failed_indices: list[int] = []
            completed = 0

            with ThreadPoolExecutor(max_workers=min(OCR_MAX_WORKERS, max(total, 1))) as executor:
                future_to_index = {
                    executor.submit(_extract_single_receipt, upload): index
                    for index, upload in enumerate(st.session_state.uploads)
                }

                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    upload = st.session_state.uploads[index]
                    try:
                        meta, parsed = future.result()
                        results_by_index[index] = (str(meta["text"]), parsed)
                    except Exception as e:
                        ocr_text_by_file[upload["name"]] = f"[ERROR] {type(e).__name__}: {e}"
                        failed_indices.append(index)
                        hint = _ocr_init_hint(e)
                        if hint and ocr_hint is None:
                            ocr_hint = hint
                    finally:
                        completed += 1
                        progress.progress(completed / max(total, 1))

            for index in failed_indices:
                upload = st.session_state.uploads[index]
                try:
                    meta, parsed = _extract_single_receipt(upload)
                    results_by_index[index] = (str(meta["text"]), parsed)
                except Exception as e:
                    ocr_text_by_file[upload["name"]] = f"[ERROR] {type(e).__name__}: {e}"
                    hint = _ocr_init_hint(e)
                    if hint and ocr_hint is None:
                        ocr_hint = hint

            for index, upload in enumerate(st.session_state.uploads):
                result = results_by_index.get(index)
                if result is None:
                    rows_for_edit.append(_parsed_receipt_to_row(upload, None))
                    continue

                ocr_text, parsed = result
                ocr_text_by_file[upload["name"]] = ocr_text
                all_receipts.append(parsed)
                rows_for_edit.append(_parsed_receipt_to_row(upload, parsed))

        if ocr_hint:
            st.warning(ocr_hint)

        st.session_state.processed_receipts = _uploads_as_receipts(st.session_state.uploads)
        st.session_state.ocr_text_by_file = ocr_text_by_file
        st.session_state.parsed_receipts = all_receipts
        st.session_state.rows_for_edit = rows_for_edit
        st.session_state.pdf_archive_bytes = None
        st.session_state.pdf_archive_filename = None
        st.session_state.generated_pdf_names = []

    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    if st.session_state.ocr_text_by_file:
        with st.expander("OCR 원문 (영수증별)", expanded=False):
            for fname, text in st.session_state.ocr_text_by_file.items():
                st.markdown(f"**{fname}**")
                st.text(text if isinstance(text, str) else str(text))

    if not st.session_state.rows_for_edit:
        st.info("**추출하기**를 눌러 영수증별 PDF를 생성하세요. OCR 실패 건도 아래 표에 수동 입력용 행으로 남습니다.")
        st.stop()

    st.subheader("변환 결과")
    edited_rows = st.data_editor(
        st.session_state.rows_for_edit,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        column_config={
            "source_file_name": st.column_config.TextColumn("파일명", disabled=True),
            "receipt_date": st.column_config.DateColumn("날짜"),
            "category": st.column_config.SelectboxColumn(
                "카테고리",
                options=["meal", "taxi", "coffee", "etc"],
                required=True,
            ),
            "amount": st.column_config.NumberColumn("금액", min_value=0, step=1),
            "task_name": st.column_config.TextColumn("과제명", required=True),
        },
        key="rows_editor",
    )
    if edited_rows != st.session_state.rows_for_edit:
        st.session_state.pdf_archive_bytes = None
        st.session_state.pdf_archive_filename = None
        st.session_state.generated_pdf_names = []
    st.session_state.rows_for_edit = edited_rows

    edited_parsed_receipts = _rows_to_parsed_receipts(st.session_state.rows_for_edit)
    preview_rows = []
    for parsed in edited_parsed_receipts:
        preview_rows.append(
            {
                "source_file_name": parsed.source_file_name,
                "receipt_date": parsed.receipt_date.isoformat()
                if parsed.receipt_date
                else None,
                "category": parsed.category,
                "amount": str(parsed.amount) if parsed.amount is not None else None,
                "task_name": parsed.task_name,
                "person_name": st.session_state.person_name,
                "pdf_name": build_pdf_filename(
                    parsed.source_file_name,
                    parsed,
                    person_name=st.session_state.person_name,
                ),
            }
        )
    st.dataframe(preview_rows, use_container_width=True)

    missing_task_name_files = _missing_task_name_files(st.session_state.rows_for_edit)
    if missing_task_name_files:
        labels = ", ".join(missing_task_name_files)
        st.warning(f"과제명을 모두 입력해 주세요. 누락 파일: {labels}")

    st.subheader("다운로드")
    if missing_task_name_files:
        st.stop()

    if st.session_state.pdf_archive_bytes is None:
        try:
            with st.spinner("PDF ZIP 파일을 생성하는 중..."):
                archive_bytes, generated_names = build_pdf_archive(
                    receipts=st.session_state.processed_receipts,
                    parsed_receipts=edited_parsed_receipts,
                    person_name=st.session_state.person_name,
                )
                st.session_state.pdf_archive_bytes = archive_bytes
                st.session_state.generated_pdf_names = generated_names
                st.session_state.pdf_archive_filename = (
                    f"{_archive_basename(st.session_state.uploads)}_pdfs.zip"
                )
        except Exception as e:
            st.session_state.last_error = (
                f"PDF 생성에 실패했습니다: {type(e).__name__}: {e}"
            )
            st.error(st.session_state.last_error)
            st.stop()

    if st.session_state.generated_pdf_names:
        st.caption("생성 파일")
        st.code("\n".join(st.session_state.generated_pdf_names))

    st.download_button(
        "ZIP 다운로드",
        data=st.session_state.pdf_archive_bytes,
        file_name=st.session_state.pdf_archive_filename or "receipts_pdfs.zip",
        mime="application/zip",
        type="primary",
    )


if __name__ == "__main__":
    main()
