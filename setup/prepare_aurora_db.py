#!/usr/bin/env python

import argparse
import json
import boto3
from rich.console import Console
from botocore.exceptions import ClientError

parser = argparse.ArgumentParser()
parser.add_argument(
    "--stack-name",
    help="The name of the Canvas Data 2 CloudFormation stack containing the Aurora database",
    required=True,
)
args = parser.parse_args()

console = Console()

# Initialize AWS clients
secrets_client = boto3.client("secretsmanager")
rds_data_client = boto3.client("rds-data")
cf_resource = boto3.resource("cloudformation")
stack = cf_resource.Stack(args.stack_name)

console.print("Starting database preparation", style="bold green")

# Fetch stack outputs and parameters
stack_outputs = {output["OutputKey"]: output["OutputValue"] for output in stack.outputs}
stack_parameters = {parameter["ParameterKey"]: parameter["ParameterValue"] for parameter in stack.parameters}

# Get admin secret
admin_secret_arn = stack_outputs["DatabaseAdminSecretArn"]
admin_secret = json.loads(secrets_client.get_secret_value(SecretId=admin_secret_arn)["SecretString"])
admin_username = admin_secret["username"]

# Get CD2 database user secret
db_user_secret_arn = stack_outputs["DatabaseUserSecretArn"]
db_user_secret = json.loads(secrets_client.get_secret_value(SecretId=admin_secret_arn)["SecretString"])
db_user_username = admin_secret["username"]

# Get Aurora cluster ARN
aurora_cluster_arn = stack_outputs["AuroraClusterArn"]

# Get environment and resource prefix
env = stack_parameters["EnvironmentParameter"]
prefix = stack_parameters["ResourcePrefixParameter"]

# Define role-based privileges
role_privileges = {
    "read_only": "GRANT SELECT ON ALL TABLES IN SCHEMA {schema_name} TO {username};",
    "read_write": "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema_name} TO {username};",
    "admin": "GRANT ALL PRIVILEGES ON SCHEMA {schema_name} TO {username};",
}

# Define user-role mapping
user_roles = {
    "athena": "read_only",
    db_user_username: "admin"
}

# List of usernames that should have schemas created
users_to_create_schema = [db_user_username]

def get_user_role(username):
    """Retrieve the role for a given username. Return read-only if not found"""
    return user_roles.get(username, "read_only")

def execute_statement(sql, database_name):
    rds_data_client.execute_statement(
        resourceArn=aurora_cluster_arn,
        secretArn=admin_secret_arn,
        sql=sql,
        database=database_name,
    )

def create_user(username, password, database_name):
    """Create a user"""
    try:
        create_user_sql = f"CREATE USER {username} WITH PASSWORD '{password}'"
        execute_statement(create_user_sql, database_name)
        console.print(f" - Created user {username}", style="bold green")
    except ClientError as e:
        if "already exists" in e.response["Error"]["Message"]:
            console.print(f" - User {username} already exists. Updating password...", style="yellow")
            update_password_sql = f"ALTER USER {username} WITH PASSWORD '{password}'"
            execute_statement(update_password_sql, database_name)
            console.print(f" - Updated password for user {username}", style="green")
        else:
            console.print(f" ! Error creating user {username}: {e}", style="bold red")

def create_schema(schema_name, username, database_name):
    """Create a schema with user as owner"""
    try:
        create_schema_sql = f"CREATE SCHEMA IF NOT EXISTS {username} AUTHORIZATION {username}"
        execute_statement(create_schema_sql, database_name)
        console.print(f" - Created schema {schema_name} with owner {username}", style="bold green")
    except ClientError as e:
        if "already exists" in e.response["Error"]["Message"]:
            console.print(f" - Schema {schema_name} already exists", style="yellow")
        else:
            console.print(f" ! Error creating schema {schema_name} with owner {username}: {e}", style="bold red")

def assign_privileges(username, schema_name, role, database_name):
    """Assign privileges to a database user based on their role."""
    try:
        grant_schema_sql = role_privileges[role].format(username=username, schema_name=schema_name)
        execute_statement(grant_schema_sql, database_name)
        console.print(f" - Granted {role} privileges on schema {schema_name} to user {username}", style="bold green")
    except ClientError as e:
        console.print(f" ! Error granting {role} privileges on schema {schema_name} to {username}: {e}", style="bold red")

def grant_usage_to_schema(username, schema_name, database_name):
    """Grant usage on a schema to a user"""
    try:
        grant_usage_sql = f"GRANT USAGE ON SCHEMA {schema_name} TO {username}"
        execute_statement(grant_usage_sql, database_name)
        console.print(f" - Granted usage on schema {schema_name} to user {username}", style="bold green")
    except ClientError as e:
        console.print(f" ! Error granting usage on schema {schema_name} to {username}: {e}", style="bold red")

def grant_user_to_admin(username, admin_username, database_name):
    """Grant user to the admin user"""
    try:
        grant_user_sql = f"GRANT {username} TO {admin_username}"
        execute_statement(grant_user_sql, database_name)
        console.print(f" - Granted user {username} to user {admin_username}", style="bold green")
    except ClientError as e:
        console.print(f" ! Error granting user {username} to user {admin_username}: {e}", style="bold red")

# Get all database user secrets
secret_name_prefix = f"{prefix}-cd2-db-user-{env}-"
user_secrets = secrets_client.list_secrets(
    Filters=[{"Key": "name", "Values": [secret_name_prefix]}],
    MaxResults=100,
)

# Process each user secret to create database users, schemas, and assign roles
for s in user_secrets["SecretList"]:
    secret_arn = s["ARN"]
    secret_value = json.loads(secrets_client.get_secret_value(SecretId=secret_arn)["SecretString"])
    username = secret_value["username"]
    database_name = secret_value["dbname"]
    
    # Create or update the user
    create_user(username, secret_value["password"], database_name)
    
    # Grant user to admin user
    grant_user_to_admin(username, admin_username, database_name)
    
    # Create schema for user (with them as owner) if they need a schema
    if username in users_to_create_schema:
        create_schema(username, username, database_name)
    
    # Create instructure_dap schema for the CD2 database user with them as owner
    if username == db_user_username:
        create_schema("instructure_dap", username, database_name)

    # Assign privileges to canvas and instructure_dap schemas
    # Defaults to read-only if user is not set in user_roles dict
    user_role = get_user_role(username)
    
    grant_usage_to_schema(username, "canvas", database_name)
    assign_privileges(username, "canvas", user_role, database_name)
    
    grant_usage_to_schema(username, "instructure_dap", database_name)
    assign_privileges(username, "instructure_dap", user_role, database_name)