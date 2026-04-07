from __future__ import annotations

import hashlib
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("uploads", [])
    ss.setdefault("uploads_fingerprint", "")
    ss.setdefault("processed_receipts", [])
    ss.setdefault("ocr_text_by_file", {})
    ss.setdefault("parsed_receipts", [])
    ss.setdefault("task_name_by_date", {})
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


def _receipt_date_key(receipt: Any) -> str:
    receipt_date = getattr(receipt, "receipt_date", None)
    return receipt_date.isoformat() if receipt_date else "unknown-date"


def _receipt_date_label(date_key: str) -> str:
    if date_key == "unknown-date":
        return "날짜 미인식"
    return date_key


def _build_task_name_map(
    parsed_receipts: list[Any],
    existing: dict[str, str] | None = None,
) -> dict[str, str]:
    existing = existing or {}
    date_keys = {_receipt_date_key(parsed) for parsed in parsed_receipts}
    return {date_key: existing.get(date_key, "") for date_key in sorted(date_keys)}


def _missing_task_name_dates(task_name_by_date: dict[str, str]) -> list[str]:
    return [
        date_key
        for date_key, task_name in sorted(task_name_by_date.items())
        if not task_name.strip()
    ]


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE_KO,
        layout="wide",
    )
    _init_state()

    st.title(APP_TITLE_KO)
    st.caption("업로드 → OCR 추출 → PDF 변환 → ZIP 다운로드")

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
        st.session_state.task_name_by_date = {}
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
    process_clicked = st.button("PDF 만들기", type="primary")
    if process_clicked:
        st.session_state.last_error = None
        successful_receipts: list[Any] = []
        all_receipts: list[Any] = []
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
                    successful_receipts.append(receipt)
                    all_receipts.append(parsed)
                except Exception as e:
                    ocr_text_by_file[u["name"]] = f"[ERROR] {type(e).__name__}: {e}"
                    hint = _ocr_init_hint(e)
                    if hint and ocr_hint is None:
                        ocr_hint = hint
                finally:
                    progress.progress(idx / max(total, 1))

        if ocr_hint:
            st.warning(ocr_hint)

        st.session_state.processed_receipts = successful_receipts
        st.session_state.ocr_text_by_file = ocr_text_by_file
        st.session_state.parsed_receipts = all_receipts
        st.session_state.task_name_by_date = _build_task_name_map(
            all_receipts,
            st.session_state.task_name_by_date,
        )
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

    if not st.session_state.parsed_receipts:
        st.info("**PDF 만들기**를 눌러 영수증별 PDF를 생성하세요.")
        st.stop()

    st.subheader("과제명 입력")
    with st.form("task_name_form", clear_on_submit=False):
        updated_task_names: dict[str, str] = {}
        for date_key in sorted(st.session_state.task_name_by_date):
            updated_task_names[date_key] = st.text_input(
                f"{_receipt_date_label(date_key)} 과제명",
                value=st.session_state.task_name_by_date.get(date_key, ""),
                placeholder="예: 고객 인터뷰, 디자인 시스템 정리",
            )
        task_names_submitted = st.form_submit_button("과제명 저장")

    if task_names_submitted:
        st.session_state.task_name_by_date = updated_task_names

    missing_task_name_dates = _missing_task_name_dates(st.session_state.task_name_by_date)
    if missing_task_name_dates:
        labels = ", ".join(_receipt_date_label(date_key) for date_key in missing_task_name_dates)
        st.warning(f"과제명을 모두 입력해 주세요. 누락 날짜: {labels}")

    st.subheader("변환 결과")
    preview_rows = []
    for parsed in st.session_state.parsed_receipts:
        date_key = _receipt_date_key(parsed)
        preview_rows.append(
            {
                "source_file_name": parsed.source_file_name,
                "receipt_date": parsed.receipt_date.isoformat()
                if parsed.receipt_date
                else None,
                "amount": str(parsed.amount) if parsed.amount is not None else None,
                "vendor": parsed.vendor,
                "task_name": st.session_state.task_name_by_date.get(date_key, ""),
                "pdf_name": build_pdf_filename(
                    parsed.source_file_name,
                    parsed,
                    task_name_by_date=st.session_state.task_name_by_date,
                ),
            }
        )
    st.dataframe(preview_rows, use_container_width=True)

    st.subheader("다운로드")
    if missing_task_name_dates:
        st.stop()

    if st.session_state.pdf_archive_bytes is None:
        try:
            with st.spinner("PDF ZIP 파일을 생성하는 중..."):
                archive_bytes, generated_names = build_pdf_archive(
                    receipts=st.session_state.processed_receipts,
                    parsed_receipts=st.session_state.parsed_receipts,
                    task_name_by_date=st.session_state.task_name_by_date,
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
