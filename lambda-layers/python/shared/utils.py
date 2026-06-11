import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns = boto3.client("sns")


def publish_alert(topic_arn, title, description):
    """Publish a Chatbot custom-notification message to an alert topic.

    The schema is what Amazon Q Developer in chat applications (Chatbot)
    renders natively; free-form payloads are silently dropped.
    """
    message = {
        "version": "1.0",
        "source": "custom",
        "content": {
            "textType": "client-markdown",
            "title": title,
            "description": description,
        },
    }
    sns.publish(TopicArn=topic_arn, Message=json.dumps(message))


def get_full_environment_name(environment_string):
    if "stg" in environment_string.lower() or "stag" in environment_string.lower():
        return "Staging"
    if "prod" in environment_string.lower():
        return "Production"
    return environment_string.capitalize()
