#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import collections
import json
from datetime import datetime
from pathlib import PurePath
from typing import Any, Callable, Dict, Generator, Iterable, Optional

import smartsheet
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.models import (
    AirbyteCatalog,
    AirbyteConnectionStatus,
    AirbyteMessage,
    AirbyteRecordMessage,
    AirbyteStream,
    ConfiguredAirbyteCatalog,
    Status,
    SyncMode,
    Type,
)
from airbyte_cdk.sources import Source
from smartsheet.models.folder import Folder
from smartsheet.models.sheet import Sheet


# This dictionary maps metadata fields to a tuple of the type of the field
# and a function that can yield the field value when given tne sheet,
# the row, and any extra arguments.
METADATA_MAPPING: dict[str, tuple[str, Callable[[Any], Optional[str]]]] = {
    "Folder ID": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: kwargs.get("folder_id"),
    ),
    "Sheet Path": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: kwargs.get("sheet_path"),
    ),
    "Sheet ID": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: str(sheet.id),
    ),
    "Sheet Name": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: sheet.name,
    ),
    "Sheet Created At": (
        "DATETIME",
        lambda sheet, row, kwargs: sheet.created_at.isoformat(),
    ),
    "Sheet Modified At": (
        "DATETIME",
        lambda sheet, row, kwargs: sheet.modified_at.isoformat(),
    ),
    "Sheet Permalink": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: sheet.permalink,
    ),
    "Sheet Version": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: str(sheet.version),
    ),
    "Row ID": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: str(row.id),
    ),
    "Row Created At": (
        "DATETIME",
        lambda sheet, row, kwargs: row.created_at.isoformat(),
    ),
    "Row Created By": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: row.created_by.name,
    ),
    "Row Modified At": (
        "DATETIME",
        lambda sheet, row, kwargs: row.modified_at.isoformat(),
    ),
    "Row Modified By": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: row.modified_by.name,
    ),
    "Row Permalink": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: row.permalink,
    ),
    "Row Number": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: str(row.row_number),
    ),
    "Row Version": (
        "TEXT_NUMBER",
        lambda sheet, row, kwargs: str(row.version),
    ),
}


class SourceSmartsheets_2(Source):

    @staticmethod
    def _conn(config: json) -> smartsheet.Smartsheet:
        """
        Initializes a Smartsheet client object from the config. The returned client
        has the option set to raise exceptions from API errors, which is not the
        default behavior.
        
        :param config: Dictionary that contains credentials and proxy information.

        :return: A Smartsheet client.
        """
        kwargs = {"access_token": config["api-access-token"]}
        proxies = {}
        if "http-proxy" in config:
            proxies["http"] = config["http-proxy"]
        if "https-proxy" in config:
            proxies["https"] = config["https-proxy"]
        if proxies:
            kwargs["proxies"] = proxies
        client = smartsheet.Smartsheet(**kwargs)
        client.errors_as_exceptions(True)
        return client
    
    @staticmethod
    def _convert_column_type(column_type: str) -> dict[str, str]:
        """
        Converts column type from Smartsheet conventions to Airbyte conventions.

        :param column_type: Smartsheet style type string.
        
        :return: A dictionary of Airbyte style type information.
        """
        mapping = {
            "TEXT_NUMBER": {"type": "string"},
            "DATE": {"type": "string", "format": "date"},
            "DATETIME": {"type": "string", "format": "date-time"},
        }
        return mapping.get(column_type, {"type": "string"})
    
    @staticmethod
    def _resolve_type_conflict(type_a: dict[str, str], type_b: dict[str, str]) -> dict[str, str]:
        """
        Compares two Airbyte style type dictionaries to yield the least type that encompasses both.
        
        :param type_a: First type to compare.
        :param type_b: Second type to compare.

        :return: Airbyte style type dictionary that encompasses the input types.
        """
        # If the two types are the same, return a copy
        if type_a.get("format", {}) == type_b.get("format", {}):
            return dict(**type_a)
        # Otherwise, fallback to the base shared across all types
        return {"type": "string"}

    @staticmethod
    def _filter_sheets_by_inclusion(sheets: Iterable[Sheet], patterns: Iterable[str]) -> list[tuple[Sheet, str]]:
        """
        Filters sheets by patterns if their canonical path matches any of the patterns. Matched sheets are included.
        
        :param sheets: Iterable of tuples of sheets and iterable of segments of the canonical path to the folder where the sheet resides.
        :param patterns: Iterable of case insensitive glob patterns.

        :return: List of tuples of sheets that matched a pattern and the pattern that they matched.
        """
        matched_sheets: list[Sheet] = []
        for sheet, folder_path in sheets:
            path = PurePath(*(segment.lower() for segment in folder_path), sheet.name.lower())
            for pattern in patterns:
                if path.match(pattern.lower()):
                    matched_sheets.append((sheet, pattern))
                    break
        return matched_sheets
    
    @staticmethod
    def _filter_folders_by_exclusion(folders: Iterable[tuple[Folder, Iterable[str]]], patterns: Iterable[str]) -> tuple[list[Folder], list[tuple[Folder, str]]]:
        """
        Filter folders by patterns if their canonical path matches any of the patterns. Matched folders are excluded.

        :param folders: Iterable of tuples of folders and iterable of segments of the canonical path to the folder where the folder resides.
        :param patterns: Iterable of case insensitive glob patterns.

        :return: Tuple of list of unfiltered folders and list of tuple of filtered folders and the pattern that they matched.
        """
        unmatched_folders: list[Folder] = []
        matched_folders: list[tuple[Folder, str]] = []
        for folder, folder_path in folders:
            path = PurePath(*(segment.lower() for segment in folder_path), folder.name.lower())
            for pattern in patterns:
                if path.match(pattern.lower()):
                    matched_folders.append((folder, pattern))
                    break
            else:
                unmatched_folders.append(folder)
        return unmatched_folders, matched_folders

    @staticmethod
    def normalize_column_name(column: str) -> str:
        """
        Normalize a column name by:
          1. Trim excess whitespace surrounding the string.
          2. Convert letters to lower case.
          3. Replace whitespace with underscores.
        
        :param column: Any string.

        :return: String normalized to be an all lower case and snake-case.
        """
        ret = column.strip()
        ret = ret.split()
        ret = (word.lower() for word in ret)
        ret = "_".join(ret)
        return ret

    def check(self, logger: AirbyteLogger, config: json) -> AirbyteConnectionStatus:
        """
        Tests if the input configuration can be used to successfully connect to the integration
            e.g: if a provided Stripe API token can be used to connect to the Stripe API.

        :param logger: Logging object to display debug/info/error to the logs
            (logs will not be accessible via airbyte UI if they are not passed to this logger)
        :param config: Json object containing the configuration of this source, content of this json is as specified in
        the properties of the spec.yaml file

        :return: AirbyteConnectionStatus indicating a Success or Failure
        """
        try:
            logger.info("getting a client")
            client = self._conn(config)
            logger.info("accessing the root folder")
            client.Folders.get_folder(config["root-folder-id"])
            for sheet_id in config["schema-sheet-ids"]:
                logger.info("accessing schema sheet with id: '%d'", sheet_id)
                client.Sheets.get_sheet(sheet_id)
            return AirbyteConnectionStatus(status=Status.SUCCEEDED)
        except Exception as e:
            return AirbyteConnectionStatus(status=Status.FAILED, message=f"An exception occurred: {str(e)}")

    def discover(self, logger: AirbyteLogger, config: json) -> AirbyteCatalog:
        """
        Returns an AirbyteCatalog representing the available streams and fields in this integration.
        Given a config with stream name, valid credentials, schema sheet IDs, and metadata fields;
        returns an Airbyte catalog where there is a single stream with the given name, whose schema
        is the union of the columns of the sheets from the given schema sheet IDs and the metadata fields.

        :param logger: Logging object to display debug/info/error to the logs
            (logs will not be accessible via airbyte UI if they are not passed to this logger)
        :param config: Json object containing the configuration of this source, content of this json is as specified in
        the properties of the spec.yaml file

        :return: AirbyteCatalog is an object describing a list of all available streams in this source.
            A stream is an AirbyteStream object that includes:
            - its stream name (or table name in the case of Postgres)
            - json_schema providing the specifications of expected schema for this stream (a list of columns described
            by their names and types)
        """
        logger.info("getting a client")
        client = self._conn(config)

        # Retrieve columns from given sheet IDs
        columns = {}
        for curr_sheet_id in config["schema-sheet-ids"]:
            logger.info("processing sheet id: '%d'", curr_sheet_id)
            curr_sheet = client.Sheets.get_sheet(curr_sheet_id)
            for column in curr_sheet.columns:
                col_type = self._convert_column_type(column.type.value)
                if column.title in columns:
                    columns[column.title] = self._resolve_type_conflict(columns[column.title], col_type)
                else:
                    columns[column.title] = col_type
        
        # Add metadata fields
        metadata_fields: list[str] = config.get("metadata-fields", [])
        if metadata_fields:
            metadata_cols = {col: self._convert_column_type(METADATA_MAPPING[col]) for col in metadata_fields}
            columns.update(metadata_cols)

        # Normalize schema if needed
        if config.get("normalize-column-names"):
            columns = {self.normalize_column_name(col): val for (col, val) in columns.items()}
                
        # Return results
        json_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": columns,
        }
        stream = AirbyteStream(
            name=config["stream-name"], 
            json_schema=json_schema,
            supported_sync_modes=[SyncMode.full_refresh],
        )
        return AirbyteCatalog(streams=[stream])

    def read(
        self, logger: AirbyteLogger, config: json, catalog: ConfiguredAirbyteCatalog, state: Dict[str, any]
    ) -> Generator[AirbyteMessage, None, None]:
        """
        Returns a generator of the AirbyteMessages generated by reading the source with the given configuration,
        catalog, and state.

        :param logger: Logging object to display debug/info/error to the logs
            (logs will not be accessible via airbyte UI if they are not passed to this logger)
        :param config: Json object containing the configuration of this source, content of this json is as specified in
            the properties of the spec.yaml file
        :param catalog: The input catalog is a ConfiguredAirbyteCatalog which is almost the same as AirbyteCatalog
            returned by discover(), but
        in addition, it's been configured in the UI! For each particular stream and field, there may have been provided
        with extra modifications such as: filtering streams and/or columns out, renaming some entities, etc
        :param state: When a Airbyte reads data from a source, it might need to keep a checkpoint cursor to resume
            replication in the future from that saved checkpoint.
            This is the object that is provided with state from previous runs and avoid replicating the entire set of
            data everytime.

        :return: A generator that produces a stream of AirbyteRecordMessage contained in AirbyteMessage object.
        """
        # Process arguments
        configured_stream = catalog.streams[0]
        stream_name = configured_stream.stream.name
        schema_properties = configured_stream.stream.json_schema["properties"]
        include_patterns: Iterable[str] = config.get("include-patterns", [])
        exclude_patterns: Iterable[str] = config.get("exclude-patterns", [])

        # Get a client
        client = self._conn(config)

        # Depth-first traversal of the Smartsheet file system, starting from the given root folder
        folder_stack: Iterable[tuple[int, Optional[tuple[str]]]] = collections.deque()
        folder_stack.append((config["root-folder-id"], None))

        while folder_stack:
            curr_folder_id, prev_path = folder_stack.pop()
            logger.info("requesting folder: '%d'", curr_folder_id)
            curr_folder = client.Folders.get_folder(curr_folder_id)
            # Some logic to make paths prettier
            # 'curr_path' is a tuple of path segments that laters gets converted to a 'pathlib.PurePath'
            # 'curr_path_str' is the representation that is mainly for logging, can also be used in the metadata
            if prev_path is None:
                curr_path = ("/",)
                curr_path_str = "/"
            else:
                curr_path = prev_path + (curr_folder.name,)
                curr_path_str = curr_path[0] + "/".join(curr_path[1:])
            logger.info("processing folder: '%s'", curr_path_str)

            # Filter subfolders
            unmatched_folders, matched_folders = self._filter_folders_by_exclusion(((subfolder, curr_path) for subfolder in curr_folder.folders), exclude_patterns)
            for subfolder, pattern in matched_folders:
                logger.info("subfolder excluded: '%s' -- matched pattern: '%s'", f"{curr_path_str}/{subfolder.name}", pattern)
            # Reverse iteration to extend the stack in lexical order
            for subfolder in reversed(unmatched_folders):
                folder_stack.append((subfolder.id, curr_path))

            # Filter sheets
            matched_sheets = self._filter_sheets_by_inclusion(((sheet, curr_path) for sheet in curr_folder.sheets), include_patterns)
            sheet_ids: list[int] = [sheet.id for (sheet, _) in matched_sheets]
            for sheet, pattern in matched_sheets:
                logger.info("sheet included: '%s' -- matched pattern: '%s'", f"{curr_path_str}/{sheet.name}", pattern)

            # Process sheets
            for sheet_id in sheet_ids:
                curr_sheet = client.Sheets.get_sheet(sheet_id)
                logger.info("processing sheet: '%s'", f"{curr_path_str}/{curr_sheet.name}")
                columns: list[tuple[int, str]] = []
                # Get whatever columns from the schema are available
                for col_idx, column in enumerate(curr_sheet.columns):
                    if column.title in schema_properties:
                        columns.append((col_idx, column.title))
                
                # Process rows with the available columns and the metadata
                for row in curr_sheet.rows:
                    metadata: dict[str, Any] = {
                        field: METADATA_MAPPING[field][1](sheet, row, {
                            "folder_id": curr_folder_id,
                            "sheet_path": curr_path_str,
                        })
                        for field in config.get("metadata-fields", [])
                    }
                    data: dict[str, Any] = {}
                    for col_idx, col_name in columns:
                        data[col_name] = row.cells[col_idx].value
                    # Sometimes we get rows that are actually empty, skip those
                    if all(val is None for val in data.values()):
                        continue
                    data.update(metadata)
                    # Normalize schema if needed
                    data = {self.normalize_column_name(col): val for (col, val) in data.items()}
                    yield AirbyteMessage(
                        type=Type.RECORD,
                        record=AirbyteRecordMessage(stream=stream_name, data=data, emitted_at=int(datetime.now().timestamp()) * 1000),
                    )
