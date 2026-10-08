import os
import sys
import logging
import argparse
import requests
from urllib.parse import urlparse

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
dotenv.load_dotenv()

from backend.store import load_json
from backend.crypto import decrypt_value

# Set up logging to both file and console
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_api.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("test_api")

def test_url_connection(instance_url, username, password):
    logger.info("=" * 60)
    logger.info(f"Testing connection for: {instance_url}")
    logger.info(f"Username: {username}")
    
    # Check hostname resolution and structure
    parsed = urlparse(instance_url)
    if not parsed.scheme or not parsed.netloc:
        logger.error(f"Invalid URL structure: {instance_url}")
        return False

    test_url = f"{instance_url.rstrip('/')}/api/now/table/incident"
    params = {"sysparm_limit": 1}
    
    logger.info(f"Target API Endpoint: {test_url}")
    logger.info("Sending GET request...")
    
    session = requests.Session()
    try:
        response = session.get(
            test_url,
            auth=(username, password),
            params=params,
            timeout=20,
            allow_redirects=False # Keep it false first to detect redirection loops/SSO redirects
        )
        
        logger.info(f"Response Status Code: {response.status_code}")
        logger.info("Response Headers:")
        for k, v in response.items() if hasattr(response, 'items') else response.headers.items():
            logger.info(f"  {k}: {v}")
            
        # Check content type
        content_type = response.headers.get("Content-Type", "")
        logger.info(f"Response Content-Type: {content_type}")
        
        # Check if redirected or requires SSO / HTML login page
        if response.status_code in (301, 302, 307, 308):
            redirect_url = response.headers.get("Location", "")
            logger.warning(f"Request was redirected to: {redirect_url}")
            logger.warning("This usually indicates Single Sign-On (SSO) redirect, MFA requirement, or incorrect instance URL.")
            
        # Log response content preview
        content_preview = response.text[:1000]
        logger.info("Response Content Preview (first 1000 chars):")
        logger.info("-" * 40)
        logger.info(content_preview)
        logger.info("-" * 40)
        
        if "html" in content_type.lower() or "<html" in response.text.lower():
            logger.error("Received HTML instead of JSON. The request was likely intercepted by a login page, SSO portal, or firewall.")
            return False
        elif "hibernating" in response.text.lower():
            logger.error("The ServiceNow instance is hibernating. Wake it up via the developer portal.")
            return False
        elif response.status_code == 200:
            try:
                response.json()
                logger.info("Successfully parsed response as JSON.")
                logger.info("Connection test using API: SUCCESS!")
                return True
            except ValueError:
                logger.error("Response status is 200 but content is not valid JSON.")
                return False
        elif response.status_code == 401:
            logger.error("401 Unauthorized. The credentials (username or password) are incorrect, or the user account is locked.")
            return False
        elif response.status_code == 403:
            logger.error("403 Forbidden. The user has valid credentials but lacks the required roles (e.g. rest_service, itil) to access the Table API.")
            return False
        else:
            logger.error(f"Request failed with status code {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.exception("HTTP Request failed:")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test ServiceNow connection using normal API request.")
    parser.add_argument("--url", help="ServiceNow instance URL (e.g., https://dev12345.service-now.com)")
    parser.add_argument("--username", help="ServiceNow username")
    parser.add_argument("--password", help="ServiceNow password (plain text)")
    
    args = parser.parse_args()
    
    if args.url and args.username and args.password:
        test_url_connection(args.url, args.username, args.password)
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
                        test_url_connection(instance_url, username, password)
                        tested_any = True
                    except Exception:
                        logger.exception(f"Failed to decrypt password for user {user_id}")
        
        if not tested_any:
            logger.error("No valid ServiceNow configurations found in credentials.json.")

if __name__ == "__main__":
    main()
