import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

def build_retry_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
