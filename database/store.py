from contextlib import contextmanager
import json
import sqlite3

import psycopg
from psycopg.rows import dict_row


SQLITE_SCHEMA = """
create table if not exists deployments (
    service_id text not null,
    deploy_id text not null,
    commit_sha text not null,
    render_status text not null,
    observed_at text not null,
    is_incident integer not null,
    evidence text not null,
    issue_state text not null,
    issue_url text,
    primary key (service_id, deploy_id)
)
"""


class Store:
    def __init__(self, database_url, sqlite_path):
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        self.table = "selfheal.deployments" if database_url else "deployments"

    @contextmanager
    def connection(self):
        if self.database_url:
            with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=5) as conn:
                conn.execute("set local statement_timeout = '5s'")
                yield conn
            return

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                conn.execute(SQLITE_SCHEMA)
                yield conn
        finally:
            conn.close()

    def execute(self, conn, query, args=()):
        return conn.execute(query if self.database_url else query.replace("%s", "?"), args)

    def check(self):
        with self.connection() as conn:
            self.execute(conn, f"select deploy_id from {self.table} limit 1").fetchall()

    def save(self, service, deploy, observed_at, incident, evidence):
        with self.connection() as conn:
            self.execute(conn, f"""
                insert into {self.table}
                    (service_id, deploy_id, commit_sha, render_status,
                     observed_at, is_incident, evidence, issue_state)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (service_id, deploy_id) do nothing
            """, (
                service, deploy.id, deploy.commit, deploy.status, observed_at, int(incident),
                json.dumps(evidence), "draft" if incident else "not_applicable",
            ))

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        result = dict(row)
        result["evidence"] = json.loads(result["evidence"])
        return result

    def get(self, service, deploy_id):
        with self.connection() as conn:
            row = self.execute(conn, f"""
                select * from {self.table} where service_id = %s and deploy_id = %s
            """, (service, deploy_id)).fetchone()
        return self.unpack(row)

    def incidents(self, service):
        with self.connection() as conn:
            rows = self.execute(conn, f"""
                select * from {self.table} where is_incident = 1 and service_id = %s
                order by observed_at desc limit 30
            """, (service,)).fetchall()
        return [self.unpack(row) for row in rows]

    def claim_issue(self, service, deploy_id):
        with self.connection() as conn:
            result = self.execute(conn, f"""
                update {self.table} set issue_state = 'posting'
                where service_id = %s and deploy_id = %s and issue_state = 'draft'
            """, (service, deploy_id))
            return result.rowcount == 1

    def finish_issue(self, service, deploy_id, state, url=None):
        with self.connection() as conn:
            self.execute(conn, f"""
                update {self.table} set issue_state = %s, issue_url = %s
                where service_id = %s and deploy_id = %s and issue_state = 'posting'
            """, (state, url, service, deploy_id))
