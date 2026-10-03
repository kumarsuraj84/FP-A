"""python -m app.cli registry-check | oracle-check"""
import sys
from pathlib import Path

from app.config import Settings
from app.registry.resolver import load_seed, validate_no_double_coverage

SEED = Path(__file__).resolve().parents[2] / "config" / "source_registry_seed.csv"


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "registry-check":
        validate_no_double_coverage(load_seed(SEED)); print("registry OK: no double coverage"); return 0
    if cmd == "oracle-check":
        s = Settings()
        if not s.oracle_configured:
            print("BLOCKED: ORACLE_DSN/ORACLE_USER/ORACLE_PASSWORD not set"); return 2
        from app.oracle.client import OracleReadOnly
        print(OracleReadOnly(s).query("SELECT 1 AS ok FROM dual")); return 0
    print(__doc__); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
