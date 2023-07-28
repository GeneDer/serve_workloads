"""Run Locust on Ray cluster.

Run this script on a Ray cluster's head node to launch one Locust worker per
CPU across the Ray cluster's nodes.

Example command:

$ python locust_runner.py -f locustfile.py -u 200 -r 50 --host [HOST_URL]
"""

import os
import ray
import time
import argparse
import subprocess
from tqdm import tqdm

HTML_RESULTS_DIR = "locust_results"
DEFAULT_RESULT_FILENAME = f"{time.strftime('%Y-%m-%d-%p-%H-%M-%S-results.html')}"

parser = argparse.ArgumentParser()
parser.add_argument(
    "--html",
    default=DEFAULT_RESULT_FILENAME,
    type=str,
    help="HTML file to save results to.",
)

args, locust_args = parser.parse_known_args()

ray.init(address="auto")
num_locust_workers = int(ray.available_resources()["CPU"])
master_address = ray.util.get_node_ip_address()

if not os.path.exists(HTML_RESULTS_DIR):
    os.mkdir(HTML_RESULTS_DIR)

# Required locust args: -f, -u, -r, --host, and any custom locustfile args
base_locust_cmd = [
    "locust",
    "--headless",
    f"--html={HTML_RESULTS_DIR}/{args.html}",
    *locust_args,
]


@ray.remote(num_cpus=1)
class LocustWorker:
    def __init__(self):
        self.proc = None

    def start(self):
        worker_locust_cmd = base_locust_cmd + [
            "--worker",
            f"--master-host={master_address}",
        ]
        self.proc = subprocess.Popen(worker_locust_cmd)


print(f"Spawning {num_locust_workers} Locust worker Ray tasks.")

# Hold reference to each locust worker to prevent them from being torn down
locust_workers = []
start_refs = []
for _ in tqdm(range(num_locust_workers)):
    locust_worker = LocustWorker.remote()
    locust_workers.append(locust_worker)
    start_refs.append(locust_worker.start.remote())

print(f"Waiting for Locust worker processes to start.")


def wait_for_locust_workers(start_refs):
    """Generator that yields whenever a worker process starts.

    Use with tqdm to track how many workers have started. If you don't need
    tqdm, use ray.get(start_refs) instead of calling this function.
    """

    remaining_start_refs = start_refs
    while remaining_start_refs:
        finished_start_refs, remaining_start_refs = ray.wait(remaining_start_refs)
        for ref in finished_start_refs:
            yield ray.get(ref)


# No-op for-loop to let tqdm track wait_for_locust_workers() progress
for _ in tqdm(wait_for_locust_workers(start_refs), total=num_locust_workers):
    pass

master_locust_cmd = base_locust_cmd + [
    "--master",
    f"--expect-workers={num_locust_workers}",
]
proc = subprocess.Popen(master_locust_cmd)
proc.communicate()
