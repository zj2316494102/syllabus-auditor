from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from syllabus_auditor.core.types import ExtractionRaw


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, pdf_path: Path) -> ExtractionRaw:
        raise NotImplementedError
