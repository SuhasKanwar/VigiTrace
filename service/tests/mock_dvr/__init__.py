"""Fake recorders that speak the real protocol shapes.

Each mock answers on an ephemeral loopback port, so the suite never touches a
real device and never needs a fixed port to be free.
"""

from tests.mock_dvr.base import BlankServer, MockRecorderServer, parse_auth_params
from tests.mock_dvr.dahua import DahuaServer
from tests.mock_dvr.dvrip import DvripServer
from tests.mock_dvr.hikvision import HikvisionServer

__all__ = [
    "BlankServer",
    "DahuaServer",
    "DvripServer",
    "HikvisionServer",
    "MockRecorderServer",
    "parse_auth_params",
]
