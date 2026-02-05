import json
import datetime
import os

LOG_FILE = os.getenv("OBSERVABILITY_LOG", "logs/run.log")
RUN_ID = os.getenv("RUN_ID", "unknown")

def log(section, event_type, payload):
    record = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "run_id": RUN_ID,
        "section": section,
        "event_type": event_type,
        "payload": payload
    }

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
