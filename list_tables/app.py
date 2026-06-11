import asyncio
import os

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config
from dap.api import DAPClient
from dap.dap_types import Credentials
from shared.utils import publish_alert, get_full_environment_name

region = os.environ.get('AWS_REGION')

config = Config(region_name=region)
ssm_provider = parameters.SSMProvider(config=config)

logger = Logger()

env = os.environ.get('ENV', 'dev')
ssm_parameter_name = os.environ.get('SSM_PARAMETER_NAME', 'canvas_data_2')
db_user = os.environ.get('DB_CD2_USER', 'canvas')

param_path = f'/{env}/{ssm_parameter_name}'

api_base_url = os.environ.get('API_BASE_URL', 'https://api-gateway.instructure.com')

REGION = os.environ["AWS_REGION"]
ALERTS_HIGH_TOPIC_ARN = os.environ["ALERTS_HIGH_TOPIC_ARN"]
STACK_NAME =  os.environ["STACK_NAME"]

@logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context: LambdaContext):
    try:
        params = ssm_provider.get_multiple(param_path, max_age=600, decrypt=True)

        dap_client_id = params['dap_client_id']
        dap_client_secret = params['dap_client_secret']

        logger.info(f"dap_client_id: {dap_client_id}")

        credentials = Credentials.create(client_id=dap_client_id, client_secret=dap_client_secret)

        os.chdir("/tmp/")

        namespace = event["namespace"]
        tables = asyncio.get_event_loop().run_until_complete(async_get_tables(api_base_url, credentials, namespace))

        # we can skip certain tables if necessary by setting an environment variable (comma-separated list)
        skip_tables = os.environ.get('SKIP_TABLES', '').split(',')

        tmap = list(map(lambda t: {'table_name': t, "state": "needs_sync", "namespace": namespace}, [t for t in tables if t not in skip_tables]))

        return {'tables': tmap}
    except Exception as e:
        logger.exception(e)

        # The whole sync workflow dies here, so this goes to the high tier.
        try:
            environment_name = get_full_environment_name(env)
            publish_alert(
                ALERTS_HIGH_TOPIC_ARN,
                f":x: {STACK_NAME} ({environment_name}): ListTables failed",
                f"The ListTables step failed with the following error:\n```{e}```",
            )
        except Exception as e:
            logger.exception(f"Alert publish failed: {e}")
            raise


async def async_get_tables(api_base_url: str, credentials: Credentials, namespace: str):
    async with DAPClient(
        base_url=api_base_url,
        credentials=credentials,
    ) as session:
        return await session.get_tables(namespace)
