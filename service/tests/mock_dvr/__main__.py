"""Run a mock recorder as a standalone process.

The unit suite starts these servers in-process on ephemeral ports. The
end-to-end suite needs one reachable from another process at a known address,
so this entry point serves the same fixtures on a fixed port. Using the same
mock for both means the browser tests and the adapter tests are talking to
identical protocol behaviour rather than to two drifting imitations.

    python -m tests.mock_dvr --vendor hikvision --port 8081 \
        --username admin --password Admin12345
"""

import argparse
import sys
import threading

from tests.mock_dvr.dahua import DahuaServer
from tests.mock_dvr.hikvision import HikvisionServer

VENDORS = {"hikvision": HikvisionServer, "dahua": DahuaServer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.mock_dvr")
    parser.add_argument("--vendor", choices=sorted(VENDORS), default="hikvision")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin12345")
    args = parser.parse_args(argv)

    server = VENDORS[args.vendor](
        port=args.port, username=args.username, password=args.password
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    print(f"mock {args.vendor} recorder listening on http://{host}:{port} "
          f"({args.username}/{args.password}) - Ctrl-C to stop", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
