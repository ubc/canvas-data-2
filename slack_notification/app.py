import os
import sys
import logging
import ast

from shared.utils import get_secret_value, send_to_slack, get_full_environment_name

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ["AWS_REGION"]
ENVIRONMENT = os.environ["AWS_ENVIRONMENT"]
SLACK_WEBHOOK_URL_SECRET_NAME = os.getenv("SLACK_WEBHOOK_SECRET_NAME")
STACK_NAME =  os.environ["STACK_NAME"]

SLACK_WEBHOOK_URL = get_secret_value(SLACK_WEBHOOK_URL_SECRET_NAME, REGION)

def process_table_update_message(message):
    green_check_mark_emoji = ':white_check_mark:'
    red_cross_mark_emoji = ':x:'
    warning_mark_emoji = ':warning:'
    failed_table_number_emoji = green_check_mark_emoji
    failed_tables_number_lower_threshold = 2
    failed_tables_number_upper_threshold = 10

    environment_name = get_full_environment_name(ENVIRONMENT)

    sns_title = f"*{STACK_NAME} ({environment_name})*\n"

    #Transform the string message from the step function into the real data.
    message = ast.literal_eval(message)

    # Extract different table state information and error messages from the input data from the SNS topic.
    complete_tables = [item["table_name"] for item in message if item.get("state") == "complete"]
    complete_tables_with_schema_update = [item["table_name"] for item in message if item.get("state") == "complete_with_update"]
    failed = [item for item in message if item.get("state") == "failed" or item.get("state") == "needs_init" or item.get("state") == "needs_sync"]
    failed_tables = [item["table_name"] for item in failed if item.get("state") == "failed" or item.get("state") == "needs_init" or item.get("state") == "needs_sync"]
    error_messages = [item.get("error_message") for item in failed]

    number_of_failed_tables = len(failed_tables)

    # Apply different emojis and the <!channel> tag depending on the number of errors.
    if number_of_failed_tables > failed_tables_number_upper_threshold:
        sns_title = "<!channel> " + sns_title
        failed_table_number_emoji = red_cross_mark_emoji
    elif number_of_failed_tables > failed_tables_number_lower_threshold:
        failed_table_number_emoji = red_cross_mark_emoji
    else:
        failed_table_number_emoji = warning_mark_emoji

    # Create a multi-line message for the slack notification.
    message = (
        f'{green_check_mark_emoji} Complete: {str(len(complete_tables))} \n'
        f'{green_check_mark_emoji} Complete w/ Schema Update: {str(len(complete_tables_with_schema_update))} \n'
        f'{failed_table_number_emoji} Failed: {str(number_of_failed_tables)} \n'
        f'Failed Tables: \n' + '\n'.join(f'{i + 1}. {msg}' for i, msg in enumerate(error_messages))
    )

    message = sns_title + message

    return message

def lambda_handler(event, context):

    # Get the SNS message payload
    sns_message = event['Records'][0]['Sns']['Message']

    sns_message = process_table_update_message(sns_message)

    try:
        send_to_slack(sns_message, SLACK_WEBHOOK_URL)
    except Exception as e:
        print(f"Slack notification failed: {e}")
        raise