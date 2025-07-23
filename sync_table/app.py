import asyncio
import os
import boto3
import json
from urllib.parse import quote_plus

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters
from botocore.config import Config
from dap.api import DAPClient
from dap.dap_types import Credentials
from dap.integration.database import DatabaseConnection
from dap.integration.database_errors import NonExistingTableError
from dap.replicator.sql import SQLReplicator
from pysqlsync.base import QueryException
import requests

region = os.environ.get("AWS_REGION")

stepfunctions = boto3.client('stepfunctions')
rds_data_client = boto3.client("rds-data")

config = Config(region_name=region)
ssm_provider = parameters.SSMProvider(config=config)

logger = Logger()

env = os.environ.get("ENV", "dev")
db_cluster_arn = os.environ.get("DB_CLUSTER_ARN")
db_user_secret_name = os.environ.get("DB_USER_SECRET_NAME")
admin_secret_arn = os.environ.get("ADMIN_SECRET_ARN")
param_path = f"/{env}/canvas_data_2"
api_base_url = os.environ.get("API_BASE_URL", "https://api-gateway.instructure.com")

FUNCTION_NAME = 'sync_table'

def get_ecs_log_url():
    # Get region from env
    region = os.environ.get('AWS_REGION', 'ca-central-1')  # fallback if not set

    # Get ECS metadata
    metadata_uri = os.environ.get('ECS_CONTAINER_METADATA_URI_V4')
    if not metadata_uri:
        raise Exception("ECS_CONTAINER_METADATA_URI_V4 not set")

    metadata = requests.get(f"{metadata_uri}/task").json()

    log_group = metadata['Containers'][0]['LogOptions']['awslogs-group']
    log_stream = metadata['Containers'][0]['LogOptions']['awslogs-stream']

    log_url = (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#logsV2:log-groups/log-group:{log_group.replace('/', '$2F')}/log-events/{log_stream}"
    )

    return log_url

def generate_error_string(function_name, table_name, state, error_message, cloudwatch_log_url, exception_type):
    return f"Task: {function_name}, table_name: {table_name}, state: {state}, error: {error_message}, cloudwatch_log_url: {cloudwatch_log_url}, exception: {exception_type}"

def start(event):
    params = ssm_provider.get_multiple(param_path, max_age=600, decrypt=True)

    dap_client_id = params["dap_client_id"]
    dap_client_secret = params["dap_client_secret"]

    db_user_secret = parameters.get_secret(db_user_secret_name, transform="json")
    db_user = db_user_secret["username"]
    db_password = quote_plus(db_user_secret["password"])
    db_name = db_user_secret["dbname"]
    db_host = db_user_secret["host"]
    db_port = db_user_secret["port"]
    namespace = db_user

    conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?sslmode=verify-ca&sslrootcert=rds-combined-ca-bundle.pem"
    db_connection = DatabaseConnection(connection_string=conn_str)

    credentials = Credentials.create(
        client_id=dap_client_id, client_secret=dap_client_secret
    )

    cloudwatch_log_url = get_ecs_log_url()

    table_name = event["table_name"]

    logger.info(f"syncing table: {table_name}")

    os.chdir("/tmp/")

    try:
        asyncio.get_event_loop().run_until_complete(
            sync_table(credentials, api_base_url, db_connection, namespace, table_name)
        )

        event["state"] = "complete"
    except QueryException as e:
        logger.exception(f"{e}")
        if "ALTER TABLE" in str(e):
            # This is a special case where the table needs a DDL update
            # Before we can apply the DDL update, we need to drop all dependent views
            try:
                drop_dependencies(db_name="cd2", table_name=table_name)
                asyncio.get_event_loop().run_until_complete(
                    sync_table(
                        credentials, api_base_url, db_connection, namespace, table_name
                    )
                )
                event["state"] = "complete_with_update"
            except Exception as e:
                logger.exception(e)
                event["state"] = "failed"
                # Make the each error as string.
                event["error_message"] = generate_error_string(FUNCTION_NAME, table_name, event["state"], str(e), cloudwatch_log_url, "Exception druing ALTER TABLE")
            finally:
                restore_dependencies(db_name="cd2", table_name=table_name)
        else:
            event["state"] = "failed"
    except NonExistingTableError as e:
        logger.exception(e)
        event["state"] = "needs_init"
        event["error_message"] = generate_error_string(FUNCTION_NAME, table_name, event["state"], str(e), cloudwatch_log_url, "NonExistingTableError")
    except ValueError as e:
        logger.exception(e)
        if "table not initialized" in str(e):
            event["state"] = "needs_init"
        else:
            event["state"] = "failed"
        event["error_message"] = generate_error_string(FUNCTION_NAME, table_name, event["state"], str(e), cloudwatch_log_url, "ValueError")
    except Exception as e:
        logger.exception(e)
        event["state"] = "failed"
        event["error_message"] = generate_error_string(FUNCTION_NAME, table_name, event["state"], str(e), cloudwatch_log_url, "Exception")

    logger.info(f"event: {event}")

    return event


async def sync_table(credentials, api_base_url, db_connection, namespace, table_name):
    async with DAPClient(api_base_url, credentials) as session:
        await SQLReplicator(session, db_connection).synchronize(namespace, table_name)


def drop_dependencies(db_name, table_name):
    # This function will drop all dependent views and retain the DDL to recreate them
    pass
    drop_sql = f"""select public.deps_save_and_drop_dependencies(
        'canvas',
        '{table_name}',
        '{{
          "dry_run": false,
          "verbose": false,
          "populate_materialized_view": false
        }}'
      )
    """
    response = rds_data_client.execute_statement(
        secretArn=admin_secret_arn,
        database=db_name,
        resourceArn=db_cluster_arn,
        sql=drop_sql,
    )
    logger.info(f"dropped dependencies for {table_name}: {response}")


def restore_dependencies(db_name, table_name):
    # This function will restore all dependent views
    pass
    restore_sql = f"""
      select public.deps_restore_dependencies(
        'canvas',
        '{table_name}',
        '{{
          "dry_run": false,
          "verbose": false
        }}'
      )
    """
    response = rds_data_client.execute_statement(
        secretArn=admin_secret_arn,
        database=db_name,
        resourceArn=db_cluster_arn,
        sql=restore_sql,
    )
    logger.info(f"restored dependencies for {table_name}: {response}")

if __name__ == "__main__":
    event = json.loads(os.environ.get('TABLE_NAME'))
    token = os.environ.get('TASK_TOKEN')

    payload = None
    result = None

    try:
        result = start(event)

    except Exception as err:
        if token:
            stepfunctions.send_task_failure(
                taskToken=token,
                error=f'{err}'
            )
        raise err

    payload = {
        "Payload": result
    }

    if token:
        stepfunctions.send_task_success(
            taskToken=token,
            output=json.dumps(payload))

"""
    if token and result['state'] == 'failed':
        stepfunctions.send_task_failure(
            taskToken=token,
            error=json.dumps(payload))
    elif token:
        stepfunctions.send_task_success(
            taskToken=token,
            output=json.dumps(payload))
"""