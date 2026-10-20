"""External HTTP evidence client; JSONL output, bounded duration and request concurrency."""
import argparse
import concurrent.futures
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def run(url, seconds, workers, output, timeout=3):
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must use HTTP or HTTPS")
    if not 0 < seconds <= 3600 or not 1 <= workers <= 32 or not 0 < timeout <= 30:
        raise ValueError("seconds: (0,3600], workers: [1,32], timeout: (0,30]")
    stop = time.monotonic() + seconds
    lock = threading.Lock()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects previous evidence from accidental overwrite.
    with output.open("x", encoding="utf-8") as stream:
        def worker():
            while time.monotonic() < stop:
                start = time.monotonic()
                event = {"timestamp": datetime.now(timezone.utc).isoformat(), "url": url}
                try:
                    with urlopen(url, timeout=timeout) as response:
                        event["status"] = response.status
                        body = response.read(65536)
                        try:
                            event["response"] = json.loads(body)
                        except (ValueError, UnicodeDecodeError):
                            pass
                except HTTPError as exc:
                    event["status"] = exc.code
                    exc.close()
                except (URLError, TimeoutError, OSError) as exc:
                    event.update(status=0, error=type(exc).__name__)
                event["duration_seconds"] = round(time.monotonic() - start, 6)
                with lock:
                    stream.write(json.dumps(event) + "\n")
                    stream.flush()
                time.sleep(0.05)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(lambda _: worker(), range(workers)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.url, args.seconds, args.workers, args.output)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
