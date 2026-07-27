import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from backend.crypto import decrypt_value

def get_s3_client(credentials: dict):
    # Retrieve AWS credentials
    access_key = credentials.get("aws_access_key_id", "").strip()
    secret_key = credentials.get("aws_secret_access_key", "").strip()
    region = credentials.get("region_name", "").strip() or "us-east-1"
    
    if secret_key and not secret_key.startswith("********"):
        try:
            secret_key = decrypt_value(secret_key)
        except Exception:
            pass
            
    # Config signature_version s3v4 always
    config = Config(signature_version="s3v4")
    
    kwargs = {"config": config}
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
        
    if region:
        kwargs["region_name"] = region
        
    return boto3.client("s3", **kwargs)

def test_bucket_access(credentials: dict) -> tuple[bool, str]:
    bucket = credentials.get("bucket", "").strip()
    if not bucket:
        return False, "Bucket name is required"
    try:
        client = get_s3_client(credentials)
        client.head_bucket(Bucket=bucket)
        return True, "Bucket access test successful"
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        return False, f"Bucket access failed (Error Code: {error_code})"
    except Exception as e:
        return False, f"Bucket access failed: {str(e)}"

def object_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == '404':
            return False
        raise e

def upload_file(s3_client, bucket: str, key: str, local_path: str):
    s3_client.upload_file(local_path, bucket, key)

def presign(s3_client, bucket: str, key: str) -> str:
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=604800 # 7 days
    )
