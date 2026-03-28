"""RAST legacy database service.

Queries the RastProdJobCache MySQL database to list a user's RAST
annotation jobs.  Replaces MSSeedSupportServer's list_rast_jobs method.
"""

from __future__ import annotations

import logging
from typing import Any

from modelseed_api.config import settings

logger = logging.getLogger("modelseed_api.rast")


class RastService:
    """Read-only client for the legacy RAST job database."""

    def list_jobs(self, username: str) -> list[dict[str, Any]]:
        """Return all RAST annotation jobs owned by *username*."""
        import pymysql

        conn = pymysql.connect(
            host=settings.rast_db_host,
            port=settings.rast_db_port,
            user=settings.rast_db_user,
            password=settings.rast_db_password,
            database=settings.rast_db_name,
            connect_timeout=10,
            read_timeout=30,
            cursorclass=pymysql.cursors.DictCursor,
        )

        try:
            with conn.cursor() as cur:
                # Look up internal user ID
                cur.execute("SELECT _id FROM User WHERE login = %s", (username,))
                row = cur.fetchone()
                if not row:
                    return []
                user_id = row["_id"]

                # Fetch jobs owned by this user
                cur.execute(
                    """
                    SELECT id, owner, project_name, created_on, last_modified,
                           genome_bp_count, genome_contig_count, genome_id,
                           genome_name, type
                    FROM Job
                    WHERE owner = %s
                    ORDER BY last_modified DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            {
                "owner": username,
                "project": r.get("project_name", ""),
                "id": str(r.get("id", "")),
                "creation_time": str(r.get("created_on", "")),
                "mod_time": str(r.get("last_modified", "")),
                "genome_size": r.get("genome_bp_count", 0) or 0,
                "contig_count": r.get("genome_contig_count", 0) or 0,
                "genome_id": r.get("genome_id", "") or "",
                "genome_name": r.get("genome_name", "") or "",
                "type": r.get("type", "") or "",
            }
            for r in rows
        ]
