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

def send_to_slack(message, slack_webhook_url):
    """Send a message to Slack."""
    try:
        response = requests.post(slack_webhook_url, json={"text": message})

        if not response.ok:
            logger.error(f"Failed to send message to Slack: {response.status_code}")
    except Exception as e:
        logger.exception(f"An error occured during the send_to_slack() operation: {e}")