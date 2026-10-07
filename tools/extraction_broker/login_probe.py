"""
login_access_probe_01: what the Oracle LOGIN used by the Inventory Automation extractor can do and see. Metadata only: the login's OWN grants
(SESSION_PRIVS, USER_ROLE_PRIVS, USER_SYS_PRIVS, USER_TAB_PRIVS, ROLE_*_PRIVS) and the object counts per visible schema. Nothing is written and no data object is read.
Run it before relying on a changed login: any write-capable privilege in the answer means STOP (see CLAUDE.md).
"""
from __future__ import annotations

import packages
from packages import Dataset

LOGIN_ACCESS_PROBE_01: tuple[Dataset, ...] = (
    Dataset("l1_session_privs", "metadata", "System privileges active in the session (including those from roles).",
            sql="SELECT privilege FROM session_privs ORDER BY privilege FETCH FIRST 2000 ROWS ONLY"),
    Dataset("l2_roles", "metadata", "Roles granted to the login.",
            sql="SELECT username, granted_role, admin_option, default_role FROM user_role_privs ORDER BY granted_role FETCH FIRST 500 ROWS ONLY"),
    Dataset("l3_sys_privs", "metadata", "System privileges granted directly to the login.",
            sql="SELECT username, privilege, admin_option FROM user_sys_privs ORDER BY privilege FETCH FIRST 2000 ROWS ONLY"),
    Dataset("l4_tab_priv_summary", "metadata", "Object privileges granted to the login, counted per owner and privilege.",
            sql="SELECT owner, privilege, count(*) AS objects FROM user_tab_privs GROUP BY owner, privilege ORDER BY owner, privilege FETCH FIRST 2000 ROWS ONLY"),
    Dataset("l5_tab_priv_not_select", "metadata", "Object privileges other than SELECT granted directly to the login (should be empty).",
            sql="SELECT owner, table_name, privilege, grantable FROM user_tab_privs WHERE privilege <> 'SELECT' ORDER BY owner, table_name FETCH FIRST 5000 ROWS ONLY"),
    Dataset("l6_role_sys_privs", "metadata", "System privileges that the login's roles carry.",
            sql="SELECT role, privilege, admin_option FROM role_sys_privs ORDER BY role, privilege FETCH FIRST 5000 ROWS ONLY"),
    Dataset("l7_role_tab_not_select", "metadata", "Object privileges other than SELECT that the login's roles carry (should be empty).",
            sql="SELECT role, owner, table_name, privilege FROM role_tab_privs WHERE privilege <> 'SELECT' ORDER BY role, owner FETCH FIRST 5000 ROWS ONLY"),
    Dataset("l8_visible_objects", "metadata", "Tables and views the login can see, counted per schema.",
            sql="SELECT owner, object_type, count(*) AS objects FROM all_objects WHERE object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') GROUP BY owner, object_type ORDER BY owner, object_type FETCH FIRST 5000 ROWS ONLY"),
)
packages.PACKAGES["login_access_probe_01"] = LOGIN_ACCESS_PROBE_01
