#
# Copyright (c) 2026 Airbyte, Inc., all rights reserved.
#

from dataclasses import dataclass
from typing import Any, Dict, Optional

from airbyte_cdk.sources.declarative.transformations import RecordTransformation
from airbyte_cdk.sources.types import Config, StreamSlice, StreamState


@dataclass
class NestRecordUnderData(RecordTransformation):
    """Moves every column of an exported row under one `data` key.

    Each worksheet has different columns, so they can't be listed in the
    stream schema, and destinations drop columns the schema doesn't list.
    `data` is listed, so the whole row is kept inside it.
    """

    def transform(
        self,
        record: Dict[str, Any],
        config: Optional[Config] = None,
        stream_state: Optional[StreamState] = None,
        stream_slice: Optional[StreamSlice] = None,
    ) -> None:
        row = dict(record)
        record.clear()
        record["data"] = row
