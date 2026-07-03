import os
import sys
import logging
import argparse
from urllib.parse import urlparse

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
dotenv.load_dotenv()

from backend.store import load_json
from backend.crypto import decrypt_value

# Set up logging to both file and console
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_sdk.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("test_sdk")

def test_sdk_connection(instance_url, username, password):
    logger.info("=" * 60)
    logger.info(f"Testing ServiceNow SDK (PySNC) connection for: {instance_url}")
    logger.info(f"Username: {username}")
    
    try:
        from pysnc import ServiceNowClient
        logger.info("Successfully imported pysnc module.")
    except ImportError:
        logger.error("pysnc is not installed in the python environment. Please run 'pip install pysnc'.")
        return False

    # Initialize PySNC client
    try:
        logger.info("Initializing ServiceNowClient...")
        client = ServiceNowClient(instance_url, (username, password))
        logger.info("ServiceNowClient initialized.")
    except Exception as e:
        logger.exception("Failed to initialize ServiceNowClient:")
        return False

    # Test query using GlideRecord
    try:
        table_name = "incident"
        logger.info(f"Attempting to query table: {table_name}")
        gr = client.GlideRecord(table_name)
        gr.limit = 1
        
        logger.info("Executing query on GlideRecord...")
        gr.query()
        
        logger.info("Query executed. Checking for results...")
        if gr.next():
            sys_id = gr.get_value('sys_id')
            number = gr.get_value('number')
            logger.info("Connection test using SDK: SUCCESS!")
            logger.info(f"Retrieved incident sys_id: {sys_id}, number: {number}")
            return True
        else:
            logger.warning("No records returned. This might be normal if the table is empty, or if permission restricts viewing records.")
            # Fallback
            logger.info("Attempting fallback check with 'sys_user' table...")
            gr_user = client.GlideRecord('sys_user')
            gr_user.limit = 1
            gr_user.query()
            if gr_user.next():
                logger.info("Connection test using SDK: SUCCESS (sys_user fallback)!")
                logger.info(f"Retrieved user sys_id: {gr_user.get_value('sys_id')}, username: {gr_user.get_value('user_name')}")
                return True
            else:
                logger.error("Both incident and sys_user queries returned no records. Check if access is restricted.")
                return False
                
    except Exception as e:
        logger.exception("SDK Request failed during GlideRecord query:")
        
        err_msg = str(e)
        if "401" in err_msg or "Unauthorized" in err_msg:
            logger.error("Likely 401 Unauthorized. Double check your credentials (username/password) or account lock status.")
        elif "403" in err_msg or "Forbidden" in err_msg:
            logger.error("Likely 403 Forbidden. The user does not have permission/roles to access the table via REST API.")
        elif "404" in err_msg:
            logger.error("Likely 404 Not Found. Verify the instance URL is correct and not redirecting.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test ServiceNow connection using ServiceNow official SDK (PySNC).")
    parser.add_argument("--url", help="ServiceNow instance URL (e.g., https://dev12345.service-now.com)")
    parser.add_argument("--username", help="ServiceNow username")
    parser.add_argument("--password", help="ServiceNow password (plain text)")
    
    args = parser.parse_args()
    
    if args.url and args.username and args.password:
        test_sdk_connection(args.url, args.username, args.password)
    else:
        logger.info("No command line credentials provided. Checking credentials.json...")
        credentials_dict = load_json("credentials.json")
        if not credentials_dict:
            logger.error("No credentials.json found or failed to load.")
            return
        
        tested_any = False
        for user_id, config in credentials_dict.items():
            if "servicenow" in config:
                sn_config = config["servicenow"]
                instance_url = sn_config.get("instance_url", "").strip()
                username = sn_config.get("username", "").strip()
                encrypted_password = sn_config.get("password", "").strip()
                
                if instance_url and username and encrypted_password:
                    try:
                        password = decrypt_value(encrypted_password)
                        test_sdk_connection(instance_url, username, password)
                        tested_any = True
                    except Exception:
                        logger.exception(f"Failed to decrypt password for user {user_id}")
        
        if not tested_any:
            logger.error("No valid ServiceNow configurations found in credentials.json.")

if __name__ == "__main__":
    main()
