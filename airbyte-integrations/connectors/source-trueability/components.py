from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests
from airbyte_cdk.sources.declarative.extractors.record_extractor import RecordExtractor


_CANDIDATE_IDENTITY_FIELDS = ("user_id", "user_email", "user_first_name", "user_full_name", "user_last_name")


def _keep_candidate_uuid(record: dict[str, Any]) -> None:
    for field in _CANDIDATE_IDENTITY_FIELDS:
        record.pop(field, None)

    user = record.get("user")
    if user is not None:
        uuid = user.get("uuid") if isinstance(user, dict) else None
        record["user"] = {"uuid": uuid} if isinstance(uuid, str) else {}


class TrueAbilityResultsExtractor(RecordExtractor):
    """Extract results, validate page metadata, strip direct candidate PII, and wrap as {id, payload}."""

    def extract_records(self, response: requests.Response) -> Iterable[Mapping[str, Any]]:
        try:
            body = response.json()
        except requests.exceptions.JSONDecodeError:
            raise ValueError("TrueAbility /results did not return valid JSON") from None

        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise ValueError("TrueAbility /results did not return a results array")

        results = body["results"]
        page = int(parse_qs(urlsplit(response.request.url).query).get("page", ["1"])[0])
        meta = body.get("meta")
        if page == 1 and not results and meta is None:
            return

        if (
            not isinstance(meta, dict)
            or type(meta.get("current_page")) is not int
            or type(meta.get("total_pages")) is not int
        ):
            raise ValueError("TrueAbility /results did not return valid pagination metadata")

        current_page, total_pages = meta["current_page"], meta["total_pages"]
        if current_page != page:
            raise ValueError(f"TrueAbility returned page {current_page} when page {page} was requested")
        if not results:
            if page == 1 and total_pages in (0, 1):
                return
            raise ValueError(f"TrueAbility returned an unexpected empty page ({page} of {total_pages})")
        if not 1 <= page <= total_pages:
            raise ValueError(f"TrueAbility returned invalid pagination bounds for page {page}")

        for result in results:
            if not isinstance(result, dict) or type(result.get("id")) is not int:
                raise ValueError("TrueAbility result has no numeric assessment id")

            _keep_candidate_uuid(result)
            result.pop("address", None)
            transcript = result.get("user_transcript")
            if isinstance(transcript, dict):
                _keep_candidate_uuid(transcript)
                summary = transcript.get("summary")
                if isinstance(summary, dict):
                    summary.pop("user", None)

            yield {"id": result["id"], "payload": result}
