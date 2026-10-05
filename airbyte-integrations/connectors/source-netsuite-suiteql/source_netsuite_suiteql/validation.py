# Copyright (c) 2026 Airbyte, Inc., all rights reserved.
import re
from typing import Any, Mapping

from .errors import InvalidIdentifierError


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SuiteQLTableValidator:
    def __init__(self, table: Mapping[str, Any]):
        self.table = table

    def validate(self) -> None:
        identifiers = [
            self.table["table_name"],
            *self.table["primary_key"],
            self.table["cursor_field"],
        ]
        invalid_identifiers = [identifier for identifier in identifiers if not IDENTIFIER_PATTERN.fullmatch(identifier)]
        if invalid_identifiers:
            raise InvalidIdentifierError(invalid_identifiers)
