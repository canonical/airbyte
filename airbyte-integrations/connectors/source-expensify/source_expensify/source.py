# Copyright (c) 2026 Airbyte, Inc., all rights reserved.

from typing import Any, List, Mapping, Tuple

from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from source_expensify.base_stream import CredentialsInvalidError, ResourceNotFoundError, _post_job_description
from source_expensify.reports import ExpensifyReports


class SourceExpensify(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, Any]:
        # Validate that the provided credentials actually work
        try:
            # Request a non-existent policy to ensure credentials are valid
            job_description = {
                "type": "get",
                "credentials": {
                    "partnerUserID": config["partner_user_id"],
                    "partnerUserSecret": config["partner_user_secret"],
                },
                "inputSettings": {"type": "policy", "fields": ["reportFields"], "policyIDList": ["abc"]},
            }
            response = _post_job_description(job_description)
            # Ensure the response is valid JSON
            response.json()
            return True, None
        except ResourceNotFoundError:
            # Expensify returns 410 if the (deliberately non-existent) policy doesn't exist
            logger.info("Credentials are valid.")
            return True, None
        except CredentialsInvalidError:
            # Expensify returns 401 if the credentials are invalid
            logger.info("Credentials are invalid.")
            return False, None
        except Exception as e:
            logger.info(f"Other issue connecting to Expensify: {e}")
            return False, e

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        # Pass the credentials from the Airbyte UI into your stream
        return [
            ExpensifyReports(
                name="reports",
                partner_user_id=config["partner_user_id"],
                partner_user_secret=config["partner_user_secret"],
                start_date=config["start_date"],
                end_date=config["end_date"],
            )
        ]
