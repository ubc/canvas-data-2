import asyncio
import os

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config
from dap.api import DAPClient
from dap.dap_types import Credentials
from shared.utils import get_secret_value, send_to_slack, get_full_environment_name

region = os.environ.get('AWS_REGION')

config = Config(region_name=region)
ssm_provider = parameters.SSMProvider(config=config)

logger = Logger()

env = os.environ.get('ENV', 'dev')

param_path = f'/{env}/canvas_data_2'

api_base_url = os.environ.get('API_BASE_URL', 'https://api-gateway.instructure.com')

namespace = 'canvas'

REGION = os.environ["AWS_REGION"]
SLACK_WEBHOOK_URL_SECRET_NAME = os.getenv("SLACK_WEBHOOK_SECRET_NAME")
STACK_NAME =  os.environ["STACK_NAME"]
SLACK_WEBHOOK_URL = get_secret_value(SLACK_WEBHOOK_URL_SECRET_NAME, REGION)

def generate_error_message(input_error):
    environment_name = get_full_environment_name(env)
    red_cross_mark_emoji = ':x:'

    sns_title = f"<!channel> *{STACK_NAME} ({environment_name})*\n"
    message = f"{red_cross_mark_emoji} The ListTables step failed with the following error: \n {input_error}"

    return sns_title + message

@logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context: LambdaContext):
    try:
        params = ssm_provider.get_multiple(param_path, max_age=600, decrypt=True)

        dap_client_id = params['dap_client_id']
        dap_client_secret = params['dap_client_secret']

        logger.info(f"dap_client_id: {dap_client_id}")

        credentials = Credentials.create(client_id=dap_client_id, client_secret=dap_client_secret)

        os.chdir("/tmp/")

        tables = asyncio.get_event_loop().run_until_complete(async_get_tables(api_base_url, credentials, namespace))

        # we can skip certain tables if necessary by setting an environment variable (comma-separated list)
        skip_tables = os.environ.get('SKIP_TABLES', '').split(',')

        tmap = list(map(lambda t: {'table_name': t, "state": "needs_sync"}, [t for t in tables if t not in skip_tables]))

        return {'tables': tmap}
    except Exception as e:
        logger.exception(e)
        message = generate_error_message(e)

        # Send a slack notification to alert any issue during the list_tables operation.
        try:
            send_to_slack(message, SLACK_WEBHOOK_URL)
        except Exception as e:
            logger.exception(f"Slack notification failed: {e}")
            raise


async def async_get_tables(api_base_url: str, credentials: Credentials, namespace: str):
    async with DAPClient(
        base_url=api_base_url,
        credentials=credentials,
    ) as session:
        return await session.get_tables(namespace)
