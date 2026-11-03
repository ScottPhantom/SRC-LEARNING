from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from app.services.data_package_installer import DataPackageCatalog, DataPackageError

LOGGER = logging.getLogger(__name__)
MAX_CATALOG_BYTES = 1024 * 1024
FetchCatalog = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class CatalogLoadResult:
    catalog: DataPackageCatalog
    source: str
    warning: str = ""


class PackageCatalogSource:
    """Fetch the owner-published GOOGLE_IDS CSV, retaining the last valid copy."""

    def __init__(
        self,
        source_url: str,
        cache_path: Path,
        fetch: FetchCatalog | None = None,
    ) -> None:
        self.source_url = source_url.strip()
        self.cache_path = Path(cache_path)
        self.fetch = fetch or self._fetch

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "docs.google.com"
            or not parsed.path.startswith("/spreadsheets/d/")
            or query.get("gid") != ["105"]
            or not (
                query.get("output") == ["csv"]
                or query.get("format") == ["csv"]
            )
        ):
            raise DataPackageError("URL danh mục phải là liên kết CSV HTTPS của Google Sheets.")

    @staticmethod
    def _fetch(url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "SRC-LEARNING/1.0"})
        with urlopen(request, timeout=8) as response:
            content = response.read(MAX_CATALOG_BYTES + 1)
        if len(content) > MAX_CATALOG_BYTES:
            raise DataPackageError("Danh mục môn học vượt quá giới hạn 1 MB.")
        return content

    def _store(self, content: bytes) -> None:
        parent = self.cache_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if self.cache_path.is_symlink():
            raise OSError("Đường dẫn bộ nhớ đệm không an toàn")
        descriptor, temporary = tempfile.mkstemp(prefix=".catalog-", dir=parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.cache_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self) -> CatalogLoadResult:
        warning = (
            "Danh mục trực tuyến chưa được cấu hình. "
            "Hãy dùng mã môn có sẵn hoặc liên hệ người quản lý ứng dụng."
            if not self.source_url else ""
        )
        if self.source_url:
            try:
                self._validate_url(self.source_url)
                content = self.fetch(self.source_url)
                if len(content) > MAX_CATALOG_BYTES:
                    raise DataPackageError("Danh mục môn học vượt quá giới hạn 1 MB.")
                catalog = DataPackageCatalog.from_sheet_csv(content)
                try:
                    self._store(content)
                except OSError as exc:
                    LOGGER.warning("Không lưu được danh mục môn học: %s", exc)
                return CatalogLoadResult(catalog, "Google Sheets")
            except (DataPackageError, OSError, TimeoutError, ValueError) as exc:
                LOGGER.warning("Không cập nhật được danh mục trực tuyến: %s", exc)
                warning = (
                    "Không thể tải danh mục mới từ Google Sheets. "
                    "Hãy kiểm tra kết nối hoặc quyền xuất bản tab GOOGLE_IDS."
                )

        try:
            if self.cache_path.is_file() and not self.cache_path.is_symlink():
                content = self.cache_path.read_bytes()
                if len(content) <= MAX_CATALOG_BYTES:
                    catalog = DataPackageCatalog.from_sheet_csv(content)
                    return CatalogLoadResult(catalog, "bộ nhớ đệm", warning)
        except (DataPackageError, OSError) as exc:
            LOGGER.warning("Bộ nhớ đệm danh mục không hợp lệ: %s", exc)

        return CatalogLoadResult(DataPackageCatalog.bundled(), "bản đóng gói", warning)
