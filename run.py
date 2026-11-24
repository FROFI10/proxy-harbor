"""Launch Proxy Harbor on loopback; use start.bat on Windows."""

import argparse
import logging
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from proxyharbor import __version__
from proxyharbor.app import create_app
from proxyharbor.config import load_settings, save_settings
from proxyharbor.instance import SingleInstanceLock

PROJECT_ROOT = Path(__file__).resolve().parent


def _port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="Proxy Harbor — локальный проверенный пул прокси")
    parser.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="открыть web UI после запуска")
    parser.add_argument("--no-auto", action="store_true", help="отключить авто-сбор только для этого запуска")
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def _open_when_ready(server, url):
    deadline = time.monotonic() + 30
    while not server.started and not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.1)
    if server.started and not server.should_exit:
        webbrowser.open(url)


def main(argv=None):
    arguments = parse_arguments(argv)
    root = PROJECT_ROOT.resolve()
    logger = logging.getLogger("proxyharbor")
    handlers = []
    previous_propagation = logger.propagate
    try:
        with SingleInstanceLock(root / "data" / "service.lock"):
            settings = load_settings(root / "config.json")
            if not (root / "config.json").exists():
                save_settings(root / "config.json", settings)
            if arguments.no_auto:
                settings = settings.model_copy(update={"auto_collect": False})
            log_directory = root / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s · %(message)s",
                                          datefmt="%Y-%m-%dT%H:%M:%SZ")
            formatter.converter = time.gmtime
            handlers = [logging.StreamHandler(),
                        RotatingFileHandler(log_directory / "proxyharbor.log", maxBytes=3_000_000,
                                            backupCount=3, encoding="utf-8")]
            logger.setLevel(logging.INFO)
            logger.propagate = False
            for handler in handlers:
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            host = "[::1]" if arguments.host == "::1" else arguments.host
            url = f"http://{host}:{arguments.port}"
            logger.info("Web UI: %s · API: %s/api/proxy · Docs: %s/docs", url, url, url)
            configuration = uvicorn.Config(
                create_app(root=root, settings=settings), host=arguments.host, port=arguments.port,
                workers=1, proxy_headers=False, server_header=False, access_log=False,
                timeout_graceful_shutdown=10,
            )
            server = uvicorn.Server(configuration)
            if arguments.open_browser:
                threading.Thread(target=_open_when_ready, args=(server, url), daemon=True,
                                 name="proxyharbor-open-browser").start()
            server.run()
            return 0 if server.started else 1
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"Не удалось запустить Proxy Harbor: {error}", file=sys.stderr)
        return 1
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = previous_propagation


if __name__ == "__main__":
    raise SystemExit(main())
