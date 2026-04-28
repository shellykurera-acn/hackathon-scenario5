"""
Helper to resolve AWS SSO credentials from the 'bootcamp' profile.

Uses `aws configure export-credentials` (the same mechanism as the CLI)
and passes the resulting short-lived keys directly to AnthropicBedrock,
bypassing boto3's internal SSO credential provider which requires botocore[crt].
"""

import json
import subprocess


def get_bedrock_client():
    """Returns an AnthropicBedrock client authenticated via the bootcamp SSO profile."""
    from anthropic import AnthropicBedrock

    import os
    env = {**os.environ, "AWS_DEFAULT_REGION": "us-east-1"}
    result = subprocess.run(
        ["aws", "configure", "export-credentials", "--profile", "bootcamp"],
        capture_output=True, text=True, check=True, env=env,
    )
    creds = json.loads(result.stdout)

    return AnthropicBedrock(
        aws_access_key=creds["AccessKeyId"],
        aws_secret_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        aws_region="us-east-1",
    )
