"""Local, single-user API for the research workbench (R09).

Read-only over verified EventStore folds and the CAS. It holds no launch or
grant authority, and a browser session minted here is never a Worker
credential.
"""

from llm_research_os.web.app import API_PREFIX, LocalApi
from llm_research_os.web.errors import LOCAL_API_VERSION, LocalApiError
from llm_research_os.web.limits import RequestLimits
from llm_research_os.web.sessions import BrowserSession, SessionStore

__all__ = [
    "API_PREFIX",
    "LOCAL_API_VERSION",
    "BrowserSession",
    "LocalApi",
    "LocalApiError",
    "RequestLimits",
    "SessionStore",
]
