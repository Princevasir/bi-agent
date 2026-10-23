"""Load the generated retail dataset into Postgres.

    cd backend && .venv/bin/python -m retail.load --scale full

Runs as retail_owner in one transaction: recreate the tables, stream every
batch in with COPY, add foreign keys and indexes, apply the read grants, and
update planner statistics. If anything fails, the previous data stays.
"""
import argparse
import os
import time
from pathlib import Path

import psycopg

from retail.generate import COLUMNS, SCALES, generate

SQL_DIR = Path(__file__).resolve().parents[2] / "db" / "retail"
DEFAULT_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail"


def load(url, seed=7, scale="small"):
    """Replace the retail tables at `url` with freshly generated data. Returns row counts per table."""
    counts = {t: 0 for t in COLUMNS}
    with psycopg.connect(url) as conn:
        conn.execute((SQL_DIR / "schema.sql").read_text())
        with conn.cursor() as cur:
            for table, rows in generate(seed, scale):
                with cur.copy(f"COPY {table} ({', '.join(COLUMNS[table])}) FROM STDIN") as copy:
                    for row in rows:
                        copy.write_row(row)
                counts[table] += len(rows)
        conn.execute((SQL_DIR / "constraints.sql").read_text())
        conn.execute((SQL_DIR / "grants.sql").read_text())
        conn.execute("ANALYZE")
    return counts


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate and load the retail demo dataset.")
    p.add_argument("--scale", default="small", help=f"one of {', '.join(SCALES)} or a number (full = 1.0)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--url", default=os.getenv("RETAIL_OWNER_URL", DEFAULT_URL),
                   help="owner connection URL (default: RETAIL_OWNER_URL or the local retail database)")
    args = p.parse_args(argv)
    scale = args.scale if args.scale in SCALES else float(args.scale)
    started = time.monotonic()
    counts = load(args.url, seed=args.seed, scale=scale)
    for table, n in counts.items():
        print(f"{table:24} {n:>10,}")
    print(f"{'total':24} {sum(counts.values()):>10,}   in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
