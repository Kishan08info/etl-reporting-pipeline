"""Run the whole pipeline: generate data -> ETL -> report.

Usage: python3 src/run_pipeline.py
"""
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent


def main():
    for script in ("generate_data.py", "etl.py", "report.py"):
        subprocess.run([sys.executable, str(SRC / script)], check=True)
    print("pipeline complete: data/saas.sqlite, results/kpi_report.md, "
          "results/charts/*.png")


if __name__ == "__main__":
    main()
