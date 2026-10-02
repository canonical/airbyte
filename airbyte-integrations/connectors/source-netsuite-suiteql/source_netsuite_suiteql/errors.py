class DuplicateQueryNameError(ValueError):
	def __init__(self, names: list[str]) -> None:
		super().__init__(f"Duplicate query names: {', '.join(sorted(names))}")


class InvalidQueryNameError(ValueError):
	def __init__(self, names: list[str]) -> None:
		super().__init__(
			"Query names must start with a letter or underscore and contain only letters, numbers, and underscores: "
			+ ", ".join(names)
		)
