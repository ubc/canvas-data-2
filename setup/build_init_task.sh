#!/bin/bash

# Script assumes valid AWS credentials and an argument with the CloudFormation stack name
STACK_NAME=$1
AWS_REGION=$(aws configure get region --profile $PROFILE)
AWS_ACCOUNT=$(aws sts get-caller-identity --profile $PROFILE --query 'Account' --output text)
INIT_REPO_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='cd2-init-uri'].OutputValue" --output text)

echo "Login To Repo"
aws --profile=$PROFILE ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $INIT_REPO_URL

echo "Build InitTable Container"
docker build --quiet --tag $INIT_REPO_URL:latest ./init_table

echo "Push InitTable Container"
docker push --quiet $INIT_REPO_URL:latest &

echo "Finished"