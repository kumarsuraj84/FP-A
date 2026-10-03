"""Environment facts for Gate 1. Read-only evidence only: privileges are INSPECTED via SESSION_PRIVS,
never probed by attempting a write."""
import re

WRITE_LIKE = re.compile(r"^(CREATE (?!SESSION$)|ALTER |DROP |INSERT |UPDATE |DELETE |EXECUTE |GRANT |MERGE |LOCK |TRUNCATE|"
                        r"DEBUG |ADMINISTER|BECOME USER|EXEMPT |FLASHBACK ANY|ANALYZE ANY|COMMENT ANY)")


def classify_privileges(privs: list[str]) -> dict:
    flagged = sorted(p for p in privs if WRITE_LIKE.match(p))
    return {"status": "APPEARS_READ_ONLY" if not flagged else "WRITE_CAPABLE_PRIVILEGES_PRESENT",
            "flagged_system_privileges": flagged, "total_system_privileges": len(privs),
            "caveat": "Inspects system privileges only; object-level grants and roles via EXECUTE on packages are not exhaustively proven."}


def check_environment(ora) -> dict:
    env = {"connected": False}
    ora.query("SELECT 1 AS ok FROM dual")
    env["connected"] = True
    env["driver"] = getattr(ora, "driver", "?")
    for k, q in (("user", "SELECT USER AS v FROM dual"),
                 ("version", "SELECT banner AS v FROM v$version WHERE ROWNUM = 1"),
                 ("utc_now", "SELECT TO_CHAR(SYS_EXTRACT_UTC(SYSTIMESTAMP), 'YYYY-MM-DD HH24:MI:SS') AS v FROM dual")):
        try:
            env[k] = ora.query(q)[0]["V"]
        except Exception as e:
            env[k] = f"unavailable ({type(e).__name__})"
    try:
        env["privileges"] = classify_privileges([r["PRIVILEGE"] for r in ora.query("SELECT privilege FROM session_privs")])
    except Exception as e:
        env["privileges"] = {"status": f"UNKNOWN ({type(e).__name__})"}
    return env
