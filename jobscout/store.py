"""Banco local (SQLite) com vagas, candidaturas, rascunhos e movimentos."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

STATUSES = (
    ("visualizada", "Visualizada"),
    ("candidatado", "Candidatado"),
    ("em_analise", "Em análise"),
    ("entrevista", "Entrevista"),
    ("proposta", "Proposta"),
    ("recusada", "Recusada"),
    ("fria", "Fria / esquecida"),
)
STATUS_KEYS = tuple(key for key, _ in STATUSES)
STATUS_LABELS = dict(STATUSES)

JOB_FIELDS = ("source", "url", "title", "company", "description", "location")
# Extraídos por regras (insights) ou pela página pública; ficam na vaga e no rascunho.
EXTRA_FIELDS = (
    "seniority", "employment_type", "industry", "company_url",
    "work_mode", "english", "salary", "region", "skills",
)
ALL_JOB_FIELDS = JOB_FIELDS + EXTRA_FIELDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'manual',
  url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  captured_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
  status TEXT NOT NULL,
  applied_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
  id INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  suggested_by_llm INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  email TEXT UNIQUE,
  phone TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  application_id INTEGER REFERENCES applications(id),
  contact_id INTEGER REFERENCES contacts(id),
  channel TEXT NOT NULL,
  external_id TEXT UNIQUE,
  subject TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  classification TEXT NOT NULL DEFAULT 'outro',
  event_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pendente',
  dedupe_key TEXT NOT NULL,
  source TEXT NOT NULL,
  job_id INTEGER REFERENCES jobs(id),
  job_url TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL,
  original TEXT NOT NULL,
  edited INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS drafts_pending ON drafts(state, dedupe_key);
CREATE TABLE IF NOT EXISTS movements (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  source TEXT NOT NULL,
  job_id INTEGER,
  draft_id INTEGER,
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS movements_job ON movements(job_id, at);
CREATE TABLE IF NOT EXISTS insertions (
  id INTEGER PRIMARY KEY,
  page_url TEXT NOT NULL,
  field TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pendente',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_failures (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  site TEXT NOT NULL,
  url TEXT NOT NULL,
  detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  linkedin_url TEXT NOT NULL DEFAULT '',
  industry TEXT NOT NULL DEFAULT '',
  size TEXT NOT NULL DEFAULT '',
  headquarters TEXT NOT NULL DEFAULT '',
  specialties TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  fetched_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS improvements (
  id INTEGER PRIMARY KEY,
  question TEXT NOT NULL,
  options TEXT NOT NULL DEFAULT '[]',
  kind TEXT NOT NULL DEFAULT 'text',
  suggestion TEXT NOT NULL DEFAULT '',
  basis TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT '',
  job TEXT NOT NULL DEFAULT '',
  job_url TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'aberto',
  note TEXT NOT NULL DEFAULT '',
  latest TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume_versions (
  id INTEGER PRIMARY KEY,
  job_id INTEGER,
  name TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'pt',
  data TEXT NOT NULL,
  pdf TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_contacts (
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (job_id, contact_id)
);
CREATE TABLE IF NOT EXISTS gmail_seen (
  message_id TEXT PRIMARY KEY,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_stages (
  id INTEGER PRIMARY KEY,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'entrevista',
  state TEXT NOT NULL DEFAULT 'pendente',
  scheduled_at TEXT,
  notes TEXT NOT NULL DEFAULT '',
  done_at TEXT
);
CREATE INDEX IF NOT EXISTS job_stages_job ON job_stages(job_id, position);
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY,
  job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
  intent TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  next_at TEXT NOT NULL,
  every_days INTEGER NOT NULL DEFAULT 0,
  remaining INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL DEFAULT 'ativo',
  notified_at TEXT,
  calendar_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_threads (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY,
  thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  sources TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_results (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  work_mode TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  score INTEGER NOT NULL DEFAULT 0,
  reasons TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL DEFAULT 'novo',
  job_id INTEGER,
  found_at TEXT NOT NULL,
  decided_at TEXT
);
"""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bancos criados por versões anteriores ganham as colunas novas."""
        added = {
            "jobs": {name: "TEXT NOT NULL DEFAULT ''" for name in EXTRA_FIELDS},
            "answers": {"origin": "TEXT NOT NULL DEFAULT 'rascunho'"},
            # Currículo (arquivo) enviado e salário informado no formulário, para os indicadores.
            "applications": {"documents": "TEXT NOT NULL DEFAULT ''", "salary_informed": "TEXT NOT NULL DEFAULT ''"},
            # Recrutadores: LinkedIn e notas, além do que o e-mail já trazia.
            "contacts": {"linkedin": "TEXT NOT NULL DEFAULT ''", "notes": "TEXT NOT NULL DEFAULT ''", "created_at": "TEXT NOT NULL DEFAULT ''"},
            # Quadro (etapas do processo) que a empresa usa; vazio = o padrão do JobScout.
            "companies": {"pipeline": "TEXT NOT NULL DEFAULT ''"},
            # Avaliação de encaixe feita pela IA (JSON) e, nos resultados da busca, o % pelas skills.
            "search_results": {"fit": "INTEGER"},
        }
        added["jobs"]["fit_ai"] = "TEXT NOT NULL DEFAULT ''"
        for table, columns in added.items():
            have = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in have:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def tx(self) -> Iterator[None]:
        """Agrupa as escritas: ou entra tudo, ou nada."""
        with self._lock:
            if self._db.in_transaction:
                yield
                return
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._db.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _run(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            return int(self._db.execute(sql, params).lastrowid or 0)

    # Vagas e candidaturas

    def job(self, job_id: int) -> dict[str, Any] | None:
        return self._one(_JOB_SELECT + " WHERE j.id = ?", (job_id,))

    def job_by_url(self, url: str) -> dict[str, Any] | None:
        return self._one(_JOB_SELECT + " WHERE j.url = ?", (url,))

    def jobs(self) -> list[dict[str, Any]]:
        return self._all(_JOB_SELECT + " ORDER BY COALESCE(a.updated_at, j.updated_at) DESC")

    def insert_job(self, fields: dict[str, str], status: str, applied_at: str | None) -> int:
        at = now()
        with self.tx():
            columns = ", ".join(ALL_JOB_FIELDS)
            marks = ", ".join("?" for _ in ALL_JOB_FIELDS)
            job_id = self._run(
                f"INSERT INTO jobs ({columns}, captured_at, updated_at) VALUES ({marks}, ?, ?)",
                tuple(fields.get(name, "") or "" for name in ALL_JOB_FIELDS) + (at, at),
            )
            self._run(
                "INSERT INTO applications (job_id, status, applied_at, updated_at) VALUES (?, ?, ?, ?)",
                (job_id, status, applied_at, at),
            )
        return job_id

    def update_job(self, job_id: int, fields: dict[str, str]) -> None:
        names = [name for name in fields if name in ALL_JOB_FIELDS and name != "url"]
        if not names:
            return
        assignments = ", ".join(f"{name} = ?" for name in names)
        self._run(
            f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?",
            tuple(fields[name] for name in names) + (now(), job_id),
        )

    def set_status(self, job_id: int, status: str, applied_at: str | None = None) -> None:
        if applied_at:
            self._run(
                "UPDATE applications SET status = ?, applied_at = COALESCE(applied_at, ?), updated_at = ?"
                " WHERE job_id = ?",
                (status, applied_at, now(), job_id),
            )
        else:
            self._run(
                "UPDATE applications SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, now(), job_id),
            )

    def set_sent(self, job_id: int, documents: str | None = None, salary: str | None = None) -> None:
        """O que foi enviado na candidatura: só sobrescreve o que vier preenchido."""
        if documents:
            self._run("UPDATE applications SET documents = ? WHERE job_id = ?", (documents, job_id))
        if salary:
            self._run("UPDATE applications SET salary_informed = ? WHERE job_id = ?", (salary, job_id))

    def stages(self) -> dict[int, set[str]]:
        """Status por que cada vaga já passou (da linha do tempo), além do atual."""
        reached: dict[int, set[str]] = {}
        for row in self._all("SELECT job_id, detail FROM movements WHERE kind = 'status' AND job_id IS NOT NULL"):
            target = json.loads(row["detail"] or "{}").get("para")
            if target:
                reached.setdefault(row["job_id"], set()).add(target)
        return reached

    def application_id(self, job_id: int) -> int | None:
        row = self._one("SELECT id FROM applications WHERE job_id = ?", (job_id,))
        return int(row["id"]) if row else None

    # Respostas, contatos, mensagens e notas

    def add_answer(
        self, job_id: int, question: str, answer: str, suggested_by_llm: bool, origin: str = "rascunho"
    ) -> int:
        application_id = self.application_id(job_id)
        return self._run(
            "INSERT INTO answers (application_id, question, answer, suggested_by_llm, origin, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (application_id, question, answer, int(suggested_by_llm), origin, now()),
        )

    def answers(self, job_id: int | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT s.*, a.job_id, j.title, j.company FROM answers s"
            " JOIN applications a ON a.id = s.application_id JOIN jobs j ON j.id = a.job_id"
        )
        if job_id is None:
            return self._all(sql + " ORDER BY s.created_at DESC")
        return self._all(sql + " WHERE a.job_id = ? ORDER BY s.created_at", (job_id,))

    def last_activity(self, job_id: int) -> str | None:
        row = self._one("SELECT MAX(at) AS at FROM movements WHERE job_id = ?", (job_id,))
        return row["at"] if row else None

    # Empresas

    def company(self, company_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM companies WHERE id = ?", (company_id,))

    def company_by_key(self, key: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM companies WHERE key = ?", (key,))

    def companies(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM companies ORDER BY name COLLATE NOCASE")

    def upsert_company(self, key: str, name: str, fields: dict[str, str]) -> tuple[int, bool]:
        """Cria ou completa a empresa. Devolve (id, criada_agora)."""
        names = [n for n in COMPANY_FIELDS if fields.get(n)]
        found = self.company_by_key(key)
        at = now()
        if found:
            if names:
                assignments = ", ".join(f"{n} = ?" for n in names)
                self._run(
                    f"UPDATE companies SET {assignments}, updated_at = ? WHERE id = ?",
                    tuple(fields[n] for n in names) + (at, found["id"]),
                )
            return int(found["id"]), False
        columns = ", ".join(["key", "name", *names, "created_at", "updated_at"])
        marks = ", ".join("?" for _ in range(len(names) + 4))
        company_id = self._run(
            f"INSERT INTO companies ({columns}) VALUES ({marks})",
            (key, name, *(fields[n] for n in names), at, at),
        )
        return company_id, True

    def mark_company_fetched(self, company_id: int) -> None:
        self._run("UPDATE companies SET fetched_at = ? WHERE id = ?", (now(), company_id))

    def set_company_notes(self, company_id: int, notes: str) -> None:
        self._run("UPDATE companies SET notes = ?, updated_at = ? WHERE id = ?", (notes, now(), company_id))

    def upsert_contact(self, name: str, email: str, company: str = "") -> int | None:
        if not email:
            return None
        found = self._one("SELECT id, name, company FROM contacts WHERE email = ?", (email,))
        if found:
            if (name and not found["name"]) or (company and not found["company"]):
                self._run(
                    "UPDATE contacts SET name = COALESCE(NULLIF(name, ''), ?),"
                    " company = COALESCE(NULLIF(company, ''), ?) WHERE id = ?",
                    (name, company, found["id"]),
                )
            return int(found["id"])
        return self._run(
            "INSERT INTO contacts (name, email, company) VALUES (?, ?, ?)",
            (name, email, company),
        )

    # Recrutadores e o vínculo com as vagas (uma pessoa pode cuidar de várias vagas, e uma vaga ter várias pessoas)

    CONTACT_FIELDS = ("name", "email", "phone", "company", "role", "linkedin", "notes")

    def contact(self, contact_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM contacts WHERE id = ?", (contact_id,))

    def contacts(self) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM contacts ORDER BY lower(name), id")
        links = self._all(
            "SELECT jc.contact_id, j.id, j.title, j.company, COALESCE(a.status, '') AS status FROM job_contacts jc"
            " JOIN jobs j ON j.id = jc.job_id LEFT JOIN applications a ON a.job_id = j.id ORDER BY jc.created_at DESC"
        )
        by_contact: dict[int, list[dict[str, Any]]] = {}
        for link in links:
            by_contact.setdefault(link["contact_id"], []).append({key: link[key] for key in ("id", "title", "company", "status")})
        for row in rows:
            row["vagas"] = by_contact.get(row["id"], [])
        return rows

    def create_contact(self, fields: dict[str, str]) -> int:
        values = {key: str(fields.get(key) or "").strip() for key in self.CONTACT_FIELDS}
        email = values.pop("email") or None
        if email:
            found = self._one("SELECT id FROM contacts WHERE lower(email) = lower(?)", (email,))
            if found:
                self.update_contact(found["id"], {**values, "email": email})
                return int(found["id"])
        return self._run(
            "INSERT INTO contacts (name, email, phone, company, role, linkedin, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (values["name"], email, values["phone"], values["company"], values["role"], values["linkedin"], values["notes"], now()),
        )

    def update_contact(self, contact_id: int, fields: dict[str, str]) -> None:
        sets = {key: (str(value).strip() or None if key == "email" else str(value).strip()) for key, value in fields.items() if key in self.CONTACT_FIELDS}
        if sets:
            columns = ", ".join(f"{key} = ?" for key in sets)
            self._run(f"UPDATE contacts SET {columns} WHERE id = ?", (*sets.values(), contact_id))

    def link_contact(self, job_id: int, contact_id: int) -> None:
        self._run("INSERT OR IGNORE INTO job_contacts (job_id, contact_id, created_at) VALUES (?, ?, ?)", (job_id, contact_id, now()))

    def unlink_contact(self, job_id: int, contact_id: int) -> None:
        self._run("DELETE FROM job_contacts WHERE job_id = ? AND contact_id = ?", (job_id, contact_id))

    def job_contacts(self, job_id: int) -> list[dict[str, Any]]:
        return self._all(
            "SELECT c.* FROM job_contacts jc JOIN contacts c ON c.id = jc.contact_id WHERE jc.job_id = ? ORDER BY jc.created_at",
            (job_id,),
        )

    def contact_jobs(self, contact_id: int) -> list[dict[str, Any]]:
        return self._all(
            _JOB_SELECT + " JOIN job_contacts jc ON jc.job_id = j.id WHERE jc.contact_id = ? ORDER BY COALESCE(a.updated_at, j.updated_at) DESC",
            (contact_id,),
        )

    def add_message(self, message: dict[str, Any]) -> int:
        return self._run(
            "INSERT INTO messages (application_id, contact_id, channel, external_id, subject, received_at,"
            " body, summary, classification, event_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.get("application_id"),
                message.get("contact_id"),
                message.get("channel", "email"),
                message.get("external_id") or None,
                message.get("subject", ""),
                message.get("received_at") or now(),
                message.get("body", ""),
                message.get("summary", ""),
                message.get("classification", "outro"),
                message.get("event_at") or None,
            ),
        )

    def message_exists(self, external_id: str) -> bool:
        return self._one("SELECT 1 FROM messages WHERE external_id = ?", (external_id,)) is not None

    def messages(self, job_id: int) -> list[dict[str, Any]]:
        return self._all(
            "SELECT m.*, c.name AS contact_name, c.email AS contact_email FROM messages m"
            " JOIN applications a ON a.id = m.application_id LEFT JOIN contacts c ON c.id = m.contact_id"
            " WHERE a.job_id = ? ORDER BY m.received_at",
            (job_id,),
        )

    def add_note(self, job_id: int, text: str) -> int:
        return self._run(
            "INSERT INTO notes (job_id, text, created_at) VALUES (?, ?, ?)",
            (job_id, text, now()),
        )

    def notes(self, job_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM notes WHERE job_id = ? ORDER BY created_at", (job_id,))

    # Rascunhos

    def add_draft(
        self,
        kind: str,
        dedupe_key: str,
        source: str,
        payload: dict[str, Any],
        job_id: int | None = None,
        job_url: str = "",
    ) -> int:
        at = now()
        encoded = json.dumps(payload, ensure_ascii=False)
        return self._run(
            "INSERT INTO drafts (kind, dedupe_key, source, job_id, job_url, payload, original, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, dedupe_key, source, job_id, job_url, encoded, encoded, at, at),
        )

    def draft(self, draft_id: int) -> dict[str, Any] | None:
        return _decode_draft(self._one("SELECT * FROM drafts WHERE id = ?", (draft_id,)))

    def pending_draft(self, dedupe_key: str) -> dict[str, Any] | None:
        return _decode_draft(
            self._one(
                "SELECT * FROM drafts WHERE state = 'pendente' AND dedupe_key = ? ORDER BY id DESC LIMIT 1",
                (dedupe_key,),
            )
        )

    def was_discarded(self, dedupe_key: str) -> bool:
        row = self._one(
            "SELECT 1 FROM drafts WHERE state = 'descartado' AND dedupe_key = ? LIMIT 1",
            (dedupe_key,),
        )
        return row is not None

    def drafts(self, state: str | None = "pendente", job_id: int | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if state:
            clauses.append("state = ?")
            params.append(state)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = " ORDER BY id" if state == "pendente" else " ORDER BY COALESCE(decided_at, updated_at) DESC LIMIT 200"
        return [_decode_draft(row) for row in self._all("SELECT * FROM drafts" + where + order, tuple(params))]

    def pending_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS total FROM drafts WHERE state = 'pendente'")
        return int(row["total"]) if row else 0

    def update_draft(
        self,
        draft_id: int,
        payload: dict[str, Any],
        *,
        edited: bool | None = None,
        job_id: int | None = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        sets = ["payload = ?", "updated_at = ?"]
        params: list[Any] = [encoded, now()]
        if edited is not None:
            sets.append("edited = ?")
            params.append(int(edited))
        if job_id is not None:
            sets.append("job_id = ?")
            params.append(job_id)
        params.append(draft_id)
        self._run(f"UPDATE drafts SET {', '.join(sets)} WHERE id = ?", tuple(params))

    def set_draft_state(self, draft_id: int, state: str, job_id: int | None = None) -> None:
        at = now()
        self._run(
            "UPDATE drafts SET state = ?, decided_at = ?, updated_at = ?, job_id = COALESCE(?, job_id) WHERE id = ?",
            (state, at, at, job_id, draft_id),
        )

    def attach_drafts_to_job(self, job_url: str, job_id: int) -> None:
        self._run(
            "UPDATE drafts SET job_id = ? WHERE state = 'pendente' AND job_id IS NULL AND job_url = ?",
            (job_id, job_url),
        )

    # Movimentos

    def log(
        self,
        kind: str,
        summary: str,
        source: str,
        *,
        job_id: int | None = None,
        draft_id: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        return self._run(
            "INSERT INTO movements (at, kind, summary, source, job_id, draft_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now(), kind, summary, source, job_id, draft_id, json.dumps(detail or {}, ensure_ascii=False)),
        )

    def movements(self, limit: int = 200, job_id: int | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT m.*, j.title AS job_title, j.company AS job_company, j.seniority AS job_seniority FROM movements m"
            " LEFT JOIN jobs j ON j.id = m.job_id"
        )
        if job_id is None:
            rows = self._all(sql + " ORDER BY m.id DESC LIMIT ?", (limit,))
        else:
            rows = self._all(sql + " WHERE m.job_id = ? ORDER BY m.id DESC LIMIT ?", (job_id, limit))
        for row in rows:
            row["detail"] = json.loads(row["detail"] or "{}")
        return rows

    # Inserções pedidas à extensão

    def add_insertion(self, page_url: str, field: str, label: str, text: str) -> int:
        return self._run(
            "INSERT INTO insertions (page_url, field, label, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (page_url, field, label, text, now()),
        )

    def pending_insertions(self, page_url: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT id, field, label, text FROM insertions WHERE state = 'pendente' AND page_url = ? ORDER BY id",
            (page_url,),
        )

    def finish_insertion(self, insertion_id: int, state: str) -> None:
        self._run("UPDATE insertions SET state = ? WHERE id = ?", (state, insertion_id))

    # Falhas de captura e Gmail

    def add_failure(self, site: str, url: str, detail: str) -> None:
        self._run(
            "INSERT INTO capture_failures (at, site, url, detail) VALUES (?, ?, ?, ?)",
            (now(), site, url, detail),
        )

    def failures(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM capture_failures ORDER BY id DESC LIMIT ?", (limit,))

    # Backlog de melhoria do currículo: perguntas cuja resposta sugerida não refletiu a experiência real

    def add_improvement(self, fields: dict[str, Any]) -> int:
        """Mesma pergunta em aberto não duplica: atualiza o que foi sugerido por último."""
        stamp = now()
        with self.tx():
            existing = self._one(
                "SELECT id FROM improvements WHERE state = 'aberto' AND lower(question) = lower(?)", (fields["question"],)
            )
            values = (
                json.dumps(fields.get("options") or [], ensure_ascii=False), fields.get("kind") or "text",
                fields.get("suggestion") or "", fields.get("basis") or "", fields.get("origin") or "",
                fields.get("job") or "", fields.get("job_url") or "",
            )
            if existing:
                self._run(
                    "UPDATE improvements SET options = ?, kind = ?, suggestion = ?, basis = ?, origin = ?, job = ?, job_url = ?,"
                    " updated_at = ? WHERE id = ?",
                    (*values, stamp, existing["id"]),
                )
                return existing["id"]
            return self._run(
                "INSERT INTO improvements (question, options, kind, suggestion, basis, origin, job, job_url, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fields["question"], *values, stamp, stamp),
            )

    def improvement(self, improvement_id: int) -> dict[str, Any] | None:
        return _decode_improvement(self._one("SELECT * FROM improvements WHERE id = ?", (improvement_id,)))

    def improvements(self, state: str | None = None) -> list[dict[str, Any]]:
        if state:
            rows = self._all("SELECT * FROM improvements WHERE state = ? ORDER BY updated_at DESC", (state,))
        else:
            rows = self._all("SELECT * FROM improvements ORDER BY state = 'aberto' DESC, updated_at DESC")
        return [_decode_improvement(row) for row in rows]

    def update_improvement(self, improvement_id: int, **fields: Any) -> None:
        allowed = {"state", "note", "latest"}
        sets = {key: (json.dumps(value, ensure_ascii=False) if key == "latest" else value) for key, value in fields.items() if key in allowed}
        if not sets:
            return
        columns = ", ".join(f"{key} = ?" for key in sets)
        self._run(f"UPDATE improvements SET {columns}, updated_at = ? WHERE id = ?", (*sets.values(), now(), improvement_id))

    # Versões do currículo direcionadas a uma vaga

    def add_resume_version(self, job_id: int | None, name: str, lang: str, data: dict[str, Any]) -> int:
        stamp = now()
        return self._run(
            "INSERT INTO resume_versions (job_id, name, lang, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, name, lang, json.dumps(data, ensure_ascii=False), stamp, stamp),
        )

    def resume_version(self, version_id: int) -> dict[str, Any] | None:
        row = self._one(
            "SELECT v.*, j.title AS job_title, j.company AS job_company FROM resume_versions v LEFT JOIN jobs j ON j.id = v.job_id WHERE v.id = ?",
            (version_id,),
        )
        if row:
            row["data"] = json.loads(row["data"] or "{}")
        return row

    def resume_versions(self) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT v.id, v.job_id, v.name, v.lang, v.pdf, v.created_at, v.updated_at, j.title AS job_title, j.company AS job_company"
            " FROM resume_versions v LEFT JOIN jobs j ON j.id = v.job_id ORDER BY v.updated_at DESC"
        )
        return rows

    def update_resume_version(self, version_id: int, **fields: Any) -> None:
        allowed = {"name", "lang", "data", "pdf"}
        sets = {key: (json.dumps(value, ensure_ascii=False) if key == "data" else value) for key, value in fields.items() if key in allowed}
        if sets:
            columns = ", ".join(f"{key} = ?" for key in sets)
            self._run(f"UPDATE resume_versions SET {columns}, updated_at = ? WHERE id = ?", (*sets.values(), now(), version_id))

    def delete_resume_version(self, version_id: int) -> None:
        self._run("DELETE FROM resume_versions WHERE id = ?", (version_id,))

    def gmail_seen(self, message_id: str) -> bool:
        return self._one("SELECT 1 FROM gmail_seen WHERE message_id = ?", (message_id,)) is not None

    def mark_gmail_seen(self, message_id: str) -> None:
        self._run("INSERT OR IGNORE INTO gmail_seen (message_id, at) VALUES (?, ?)", (message_id, now()))

    # Etapas do processo (o quadro da empresa aplicado a cada vaga)

    def job_stages(self, job_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM job_stages WHERE job_id = ? ORDER BY position, id", (job_id,))

    def all_job_stages(self) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in self._all("SELECT * FROM job_stages ORDER BY job_id, position, id"):
            grouped.setdefault(row["job_id"], []).append(row)
        return grouped

    def replace_job_stages(self, job_id: int, stages: list[dict[str, Any]]) -> None:
        with self.tx():
            self._run("DELETE FROM job_stages WHERE job_id = ?", (job_id,))
            for position, stage in enumerate(stages):
                self._run(
                    "INSERT INTO job_stages (job_id, position, name, kind, state, scheduled_at, notes, done_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, position, stage["name"], stage["kind"], stage["state"], stage.get("scheduled_at") or None,
                     stage.get("notes") or "", stage.get("done_at") or None),
                )

    def set_company_pipeline(self, company_id: int, pipeline: list[dict[str, str]]) -> None:
        self._run("UPDATE companies SET pipeline = ?, updated_at = ? WHERE id = ?",
                  (json.dumps(pipeline, ensure_ascii=False) if pipeline else "", now(), company_id))

    # Lembretes (cobrar retorno, pedir feedback...), com ou sem repetição

    def add_reminder(self, fields: dict[str, Any]) -> int:
        at = now()
        return self._run(
            "INSERT INTO reminders (job_id, intent, title, notes, next_at, every_days, remaining, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fields.get("job_id"), fields.get("intent") or "", fields["title"], fields.get("notes") or "", fields["next_at"],
             int(fields.get("every_days") or 0), int(fields.get("remaining") or 1), at, at),
        )

    def reminder(self, reminder_id: int) -> dict[str, Any] | None:
        return self._one(_REMINDER_SELECT + " WHERE r.id = ?", (reminder_id,))

    def reminders(self, job_id: int | None = None, states: tuple[str, ...] = ("ativo",)) -> list[dict[str, Any]]:
        marks = ", ".join("?" for _ in states)
        if job_id is None:
            return self._all(_REMINDER_SELECT + f" WHERE r.state IN ({marks}) ORDER BY r.next_at", states)
        return self._all(_REMINDER_SELECT + f" WHERE r.job_id = ? AND r.state IN ({marks}) ORDER BY r.next_at", (job_id, *states))

    def update_reminder(self, reminder_id: int, **fields: Any) -> None:
        allowed = {"title", "notes", "next_at", "every_days", "remaining", "state", "notified_at", "calendar_id", "intent"}
        sets = {key: value for key, value in fields.items() if key in allowed}
        if sets:
            columns = ", ".join(f"{key} = ?" for key in sets)
            self._run(f"UPDATE reminders SET {columns}, updated_at = ? WHERE id = ?", (*sets.values(), now(), reminder_id))

    def set_job_fit(self, job_id: int, data: dict[str, Any]) -> None:
        self._run("UPDATE jobs SET fit_ai = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), job_id))

    # Conversas da aba Busca (perguntas sobre o histórico)

    def chat_threads(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM chat_threads ORDER BY updated_at DESC, id DESC LIMIT 100")

    def chat_thread(self, thread_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM chat_threads WHERE id = ?", (thread_id,))

    def add_chat_thread(self, title: str) -> int:
        at = now()
        return self._run("INSERT INTO chat_threads (title, created_at, updated_at) VALUES (?, ?, ?)", (title, at, at))

    def delete_chat_thread(self, thread_id: int) -> None:
        self._run("DELETE FROM chat_threads WHERE id = ?", (thread_id,))

    def add_chat_message(self, thread_id: int, role: str, text: str, sources: list[dict[str, Any]] | None = None) -> int:
        at = now()
        with self.tx():
            message_id = self._run(
                "INSERT INTO chat_messages (thread_id, role, text, sources, created_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, role, text, json.dumps(sources or [], ensure_ascii=False), at),
            )
            self._run("UPDATE chat_threads SET updated_at = ? WHERE id = ?", (at, thread_id))
        return message_id

    def chat_messages(self, thread_id: int) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY id", (thread_id,))
        for row in rows:
            row["sources"] = json.loads(row["sources"] or "[]")
        return rows

    # Resultados da busca automática de vagas

    def add_search_result(self, item: dict[str, Any]) -> int | None:
        """Grava a vaga encontrada; se o link já apareceu antes (mesmo descartado), não volta."""
        if self._one("SELECT 1 FROM search_results WHERE url = ?", (item["url"],)):
            return None
        return self._run(
            "INSERT INTO search_results (url, source, title, company, location, work_mode, description, published_at,"
            " score, reasons, fit, found_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["url"], item["source"], item.get("title") or "", item.get("company") or "", item.get("location") or "",
             item.get("work_mode") or "", (item.get("description") or "")[:6000], item.get("published_at"),
             int(item.get("score") or 0), json.dumps(item.get("reasons") or [], ensure_ascii=False), item.get("fit"), now()),
        )

    def search_results(self, state: str = "novo", limit: int = 200) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM search_results WHERE state = ? ORDER BY score DESC, found_at DESC LIMIT ?", (state, limit))
        for row in rows:
            row["reasons"] = json.loads(row["reasons"] or "[]")
        return rows

    def search_result(self, result_id: int) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM search_results WHERE id = ?", (result_id,))
        if row:
            row["reasons"] = json.loads(row["reasons"] or "[]")
        return row

    def set_search_result(self, result_id: int, state: str, job_id: int | None = None) -> None:
        self._run("UPDATE search_results SET state = ?, job_id = COALESCE(?, job_id), decided_at = ? WHERE id = ?",
                  (state, job_id, now(), result_id))

    # Busca

    def corpus(self) -> list[dict[str, Any]]:
        """Tudo que a busca do painel percorre: vagas, respostas, mensagens e notas."""
        sources = (
            ("vaga", "SELECT id AS job_id, title || ' — ' || company AS titulo,"
             " title || ' ' || company || ' ' || description AS texto, captured_at AS quando FROM jobs"),
            ("resposta", "SELECT a.job_id, s.question AS titulo, s.answer AS texto,"
             " s.created_at AS quando FROM answers s JOIN applications a ON a.id = s.application_id"),
            ("mensagem", "SELECT a.job_id, m.subject AS titulo, m.subject || ' ' || m.body AS texto,"
             " m.received_at AS quando FROM messages m JOIN applications a ON a.id = m.application_id"),
            ("nota", "SELECT job_id, 'Nota' AS titulo, text AS texto, created_at AS quando FROM notes"),
        )
        found: list[dict[str, Any]] = []
        for kind, sql in sources:
            found.extend({"tipo": kind, **row} for row in self._all(sql))
        return found


COMPANY_FIELDS = ("linkedin_url", "industry", "size", "headquarters", "specialties", "description")

_JOB_SELECT = (
    "SELECT j.*, a.id AS application_id, a.status, a.applied_at, a.updated_at AS status_at,"
    " COALESCE(a.documents, '') AS documents, COALESCE(a.salary_informed, '') AS salary_informed"
    " FROM jobs j LEFT JOIN applications a ON a.job_id = j.id"
)

_REMINDER_SELECT = (
    "SELECT r.*, j.title AS job_title, j.company AS job_company, a.status AS job_status"
    " FROM reminders r LEFT JOIN jobs j ON j.id = r.job_id LEFT JOIN applications a ON a.job_id = r.job_id"
)


def _decode_improvement(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    row["options"] = json.loads(row["options"] or "[]")
    row["latest"] = json.loads(row["latest"] or "{}")
    return row


def _decode_draft(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    row["payload"] = json.loads(row["payload"])
    row["original"] = json.loads(row["original"])
    row["edited"] = bool(row["edited"])
    return row
