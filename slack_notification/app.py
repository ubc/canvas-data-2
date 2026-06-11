import os
import json
import logging

from shared.utils import publish_alert, get_full_environment_name

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ENVIRONMENT = os.environ["AWS_ENVIRONMENT"]
STACK_NAME = os.environ["STACK_NAME"]
ALERTS_HIGH_TOPIC_ARN = os.environ["ALERTS_HIGH_TOPIC_ARN"]
ALERTS_INFO_TOPIC_ARN = os.environ["ALERTS_INFO_TOPIC_ARN"]

# More failed tables than this routes the summary to the high (action
# needed) tier instead of info. Replaces the old <!channel> webhook hack.
FAILED_TABLES_HIGH_TIER_THRESHOLD = 2

GREEN_CHECK_MARK_EMOJI = ":white_check_mark:"
RED_CROSS_MARK_EMOJI = ":x:"
WARNING_MARK_EMOJI = ":warning:"


def summarize_table_updates(table_states):
    environment_name = get_full_environment_name(ENVIRONMENT)

    namespace = table_states[0]["namespace"] if table_states else "N/A"

    complete_tables = [item["table_name"] for item in table_states if item.get("state") == "complete"]
    complete_tables_with_schema_update = [
        item["table_name"] for item in table_states if item.get("state") == "complete_with_update"
    ]
    failed = [
        item for item in table_states if item.get("state") in ("failed", "needs_init", "needs_sync")
    ]
    number_of_failed_tables = len(failed)

    if number_of_failed_tables == 0:
        verdict_emoji = GREEN_CHECK_MARK_EMOJI
        topic_arn = ALERTS_INFO_TOPIC_ARN
    elif number_of_failed_tables <= FAILED_TABLES_HIGH_TIER_THRESHOLD:
        verdict_emoji = WARNING_MARK_EMOJI
        topic_arn = ALERTS_INFO_TOPIC_ARN
    else:
        verdict_emoji = RED_CROSS_MARK_EMOJI
        topic_arn = ALERTS_HIGH_TOPIC_ARN

    title = (
        f"{verdict_emoji} {STACK_NAME} ({environment_name}): "
        f"{number_of_failed_tables} failed table{'' if number_of_failed_tables == 1 else 's'}"
    )

    lines = [
        f"*Namespace:* {namespace}",
        f"{GREEN_CHECK_MARK_EMOJI} Complete: {len(complete_tables)}",
        f"{GREEN_CHECK_MARK_EMOJI} Complete w/ Schema Update: {len(complete_tables_with_schema_update)}",
        f"{verdict_emoji} Failed: {number_of_failed_tables}",
    ]
    if failed:
        lines.append("Failed tables:")
        lines.extend(
            f"{i + 1}. {item.get('table_name', '?')}: {item.get('error_message', 'no error message')}"
            for i, item in enumerate(failed)
        )

    return topic_arn, title, "\n".join(lines)


def lambda_handler(event, context):
    sns_message = event["Records"][0]["Sns"]["Message"]
    table_states = json.loads(sns_message)

    topic_arn, title, description = summarize_table_updates(table_states)

    try:
        publish_alert(topic_arn, title, description)
    except Exception as e:
        logger.exception(f"Alert publish failed: {e}")
        raise
