#
# Copyright (c) 2024 Airbyte, Inc., all rights reserved.
#


# NETSUITTE REST API PATHS
REST_PATH: str = "/services/rest/"
RECORD_PATH: str = REST_PATH + "record/v1/"
META_PATH: str = RECORD_PATH + "metadata-catalog/"

# PREDEFINE REFERAL SCHEMA LINK, TEMPLATE
REFERAL_SCHEMA_URL: str = "/services/rest/record/v1/metadata-catalog/nsLink"
REFERAL_SCHEMA: dict = {
    "type": ["null", "object"],
    "properties": {
        "id": {"title": "Internal identifier", "type": ["string"]},
        "refName": {"title": "Reference Name", "type": ["null", "string"]},
        "externalId": {"title": "External identifier", "type": ["null", "string"]},
        "links": {
            "title": "Links",
            "type": "array",
            "readOnly": True,
        },
    },
}
# ELEMENTS TO REMOVE FROM SCHEMA
USLESS_SCHEMA_ELEMENTS: list = [
    "enum",
    "x-ns-filterable",
    "x-ns-custom-field",
    "nullable",
]

# PREDEFINE SCHEMA HEADER
SCHEMA_HEADERS: dict = {"Accept": "application/schema+json"}

# Numeric JSON schema types should never carry a format annotation in Airbyte catalogs.
NUMERIC_JSON_SCHEMA_TYPES: set[str] = {"number", "integer"}

# INCREMENTAL CURSOR FIELDS
INCREMENTAL_CURSOR: str = "lastModifiedDate"
CUSTOM_INCREMENTAL_CURSOR: str = "lastmodified"

# Please keep the "%d/%m/%Y" format in the first position as it's the date format for Canonical.
# Check https://github.com/canonical/airbyte/pull/63 for more details.
NETSUITE_INPUT_DATE_FORMATS: list[str] = ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d.%m.%Y"]
NETSUITE_OUTPUT_DATETIME_FORMAT: str = "%Y-%m-%dT%H:%M:%SZ"
