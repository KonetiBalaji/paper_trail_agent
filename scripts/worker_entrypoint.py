"""Production worker process: database service mode, no paid model capability."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    # The web service can use Meta, but OCR/eval workers do not need that key.
    # An explicit empty value also prevents dotenv from restoring it.
    os.environ['MODEL_API_KEY']=''
    os.environ['PAPER_TRAIL_MODE']='service'
    from app.worker import main as worker_main
    worker_main()


if __name__=='__main__':main()
