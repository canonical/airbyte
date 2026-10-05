# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

import requests


class DuplicateQueryNameError(ValueError):
    def __init__(self, names: list[str]) -> None:
        super().__init__(f"Duplicate query names: {', '.join(sorted(names))}")


class InvalidQueryNameError(ValueError):
    def __init__(self, names: list[str]) -> None:
        super().__init__(
            "Query names must start with a letter or underscore and contain only letters, numbers, and underscores: " + ", ".join(names)
        )


class IncompleteIncrementalConfigurationError(ValueError):
    def __init__(self, query_name: str) -> None:
        super().__init__(f"Incremental query '{query_name}' must configure primary_key, cursor_field, and cursor_parameter_index together.")


class InvalidCursorParameterIndexError(ValueError):
    def __init__(self, query_name: str) -> None:
        super().__init__(f"Incremental query '{query_name}' cursor_parameter_index must reference an item in parameters.")


class MissingCursorFieldError(ValueError):
	def __init__(self, cursor_field: str) -> None:
		super().__init__(f"Incremental query record is missing cursor field '{cursor_field}'.")


def raise_for_netsuite_status(response: requests.Response) -> None:
	try:
		response.raise_for_status()
	except requests.HTTPError as error:
		try:
			details = response.json().get("o:errorDetails", [])
			message = "; ".join(detail.get("detail", "") for detail in details if detail.get("detail"))
		except ValueError:
			message = response.text
		if message:
			raise requests.HTTPError(f"{error} NetSuite error: {message}", response=response) from error
		raise
