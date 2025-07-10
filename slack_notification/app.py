import os
import json
import boto3
import requests
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_secret_value(secret_name, region):
    client = boto3.client("secretsmanager", region)

    try:
        response = client.get_secret_value(SecretId=secret_name)

        if 'SecretString' in response:
            secret = response['SecretString']
        else:
            # Decode binary secret if necessary
            secret = response['SecretBinary']

        return secret

    except ClientError as e:
        logger.exception(f"Error while fetching secret: {e}")
        return None

REGION = os.environ["AWS_REGION"]
ENVIRONMENT = os.environ["AWS_ENVIRONMENT"]
SLACK_WEBHOOK_URL_SECRET_NAME = os.getenv("SLACK_WEBHOOK_SECRET_NAME")

def send_to_slack(message):
    """Send a message to Slack."""
    try:
        SLACK_WEBHOOK_URL = get_secret_value(SLACK_WEBHOOK_URL_SECRET_NAME, REGION)
        response = requests.post(SLACK_WEBHOOK_URL, json={"text": message})

        if not response.ok:
            logger.error(f"Failed to send message to Slack: {response.status_code}")
    except Exception as e:
        logger.exception(f"An error occured during the send_to_slack() operation: {e}")

def lambda_handler(event, context):

    # Get the SNS message payload
    sns_message = event['Records'][0]['Sns']['Message']
    sns_title = "*Canvas Data 2 Workflow Notification*:\n"
    sns_message = sns_title + sns_message

    try:
        send_to_slack(sns_message)
    except Exception as e:
        print(f"Slack notification failed: {e}")
        raise