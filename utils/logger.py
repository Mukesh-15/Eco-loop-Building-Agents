import logging
import sys
from datetime import datetime
from utils.config import LOG_DIR

def get_logger(name):
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_DIR / f"eco_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S"))
    log.addHandler(sh)
    log.propagate = False
    return log
