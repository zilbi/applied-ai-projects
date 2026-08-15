"""SQLite persistence for the company-research pipeline.

The store is factual and append-oriented: competing registry values keep their
source/provenance instead of being silently replaced by a guessed "best" value.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .normalization import clean_text
from .validation import valid_inn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_request_id(request: dict[str, Any]) -> str:
    """Stable key from real queue fields; generated LOOKUP-0001 may change order."""
    identity = {
        "inn": request.get("inn"),
        "legal_name_candidates": sorted(str(x) for x in request.get("legal_name_candidates", []) if x),
        "account_candidates": sorted(str(x) for x in request.get("account_candidates", []) if x),
        "operation_ids": sorted(str(x) for x in request.get("operation_ids", []) if x),
        "source_sides": sorted(str(x) for x in request.get("source_sides", []) if x),
    }
    return "request:" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()


class ResearchStore:
    def __init__(self, database_path: str | Path = "results/company_research.sqlite3", *, read_only: bool = False) -> None:
        self.database_path = Path(database_path)
        self.read_only = read_only
        if read_only:
            if not self.database_path.exists():
                raise FileNotFoundError(self.database_path)
            self.connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True)
        else:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            self.create_schema()

    def close(self) -> None:
        self.connection.close()

    def create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY,
                company_key TEXT NOT NULL UNIQUE,
                inn TEXT UNIQUE,
                confirmed_legal_name TEXT,
                legal_form TEXT,
                kpp TEXT,
                ogrn TEXT,
                registration_status TEXT,
                registration_date TEXT,
                region TEXT,
                legal_address TEXT,
                official_website TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_requests (
                id INTEGER PRIMARY KEY,
                external_request_id TEXT NOT NULL UNIQUE,
                source_lookup_id TEXT,
                source_file TEXT,
                source_row INTEGER,
                company_id INTEGER REFERENCES companies(id),
                request_status TEXT NOT NULL,
                raw_request_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_research_requests_lookup ON research_requests(source_lookup_id);
            CREATE TABLE IF NOT EXISTS request_operations (
                research_request_id INTEGER NOT NULL REFERENCES research_requests(id) ON DELETE CASCADE,
                operation_id TEXT NOT NULL,
                PRIMARY KEY (research_request_id, operation_id)
            );
            CREATE TABLE IF NOT EXISTS company_aliases (
                id INTEGER PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                research_request_id INTEGER REFERENCES research_requests(id),
                original_name TEXT NOT NULL,
                normalized_name TEXT,
                alias_kind TEXT NOT NULL,
                source_name TEXT,
                source_result_id INTEGER,
                created_at TEXT NOT NULL,
                CHECK (company_id IS NOT NULL OR research_request_id IS NOT NULL)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_company_aliases_unique
                ON company_aliases(company_id, research_request_id, original_name, alias_kind, source_name);
            CREATE TABLE IF NOT EXISTS source_results (
                id INTEGER PRIMARY KEY,
                research_request_id INTEGER REFERENCES research_requests(id),
                company_id INTEGER REFERENCES companies(id),
                source_name TEXT NOT NULL,
                input_inn TEXT,
                source_url TEXT,
                request_status TEXT NOT NULL,
                inn_confirmed INTEGER NOT NULL DEFAULT 0,
                collected_at TEXT NOT NULL,
                snapshot_path TEXT,
                parse_warnings_json TEXT NOT NULL DEFAULT '[]',
                content_hash TEXT,
                raw_result_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(research_request_id, source_name, source_url)
            );
            CREATE TABLE IF NOT EXISTS company_facts (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                field_name TEXT NOT NULL,
                value_text TEXT NOT NULL,
                normalized_value TEXT,
                source_result_id INTEGER REFERENCES source_results(id),
                source_name TEXT,
                source_url TEXT,
                confidence REAL,
                is_conflicting INTEGER NOT NULL DEFAULT 0,
                collected_at TEXT NOT NULL,
                UNIQUE(company_id, field_name, normalized_value, source_result_id)
            );
            CREATE TABLE IF NOT EXISTS company_okved (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                okved_code TEXT NOT NULL,
                okved_name TEXT,
                is_primary INTEGER NOT NULL DEFAULT 0,
                source_result_id INTEGER REFERENCES source_results(id),
                source_name TEXT,
                source_url TEXT,
                confidence REAL,
                is_conflicting INTEGER NOT NULL DEFAULT 0,
                collected_at TEXT NOT NULL,
                UNIQUE(company_id, okved_code, is_primary, source_result_id)
            );
            CREATE TABLE IF NOT EXISTS company_websites (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                domain TEXT,
                website_url TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                verification_score REAL,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(company_id, website_url, source)
            );
            CREATE TABLE IF NOT EXISTS website_candidates (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                candidate_url TEXT NOT NULL,
                domain TEXT,
                search_query TEXT NOT NULL DEFAULT '',
                candidate_source TEXT,
                source_type TEXT NOT NULL DEFAULT 'search_result',
                domain_role TEXT NOT NULL DEFAULT 'OFFICIAL_CANDIDATE',
                role_reason TEXT,
                brand_match INTEGER NOT NULL DEFAULT 0,
                title_match INTEGER NOT NULL DEFAULT 0,
                search_score REAL NOT NULL DEFAULT 0,
                verification_score REAL NOT NULL DEFAULT 0,
                rejection_reason TEXT,
                selected INTEGER NOT NULL DEFAULT 0,
                search_position INTEGER,
                search_title TEXT,
                search_snippet TEXT,
                candidate_score REAL NOT NULL DEFAULT 0,
                candidate_status TEXT NOT NULL,
                positive_evidence_json TEXT NOT NULL DEFAULT '[]',
                negative_evidence_json TEXT NOT NULL DEFAULT '[]',
                checked_pages_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(company_id, candidate_url, search_query)
            );
            CREATE TABLE IF NOT EXISTS website_search_attempts (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                provider TEXT NOT NULL,
                reason_for_call TEXT,
                template_id TEXT,
                search_query TEXT,
                include_domains_json TEXT NOT NULL DEFAULT '[]',
                exclude_domains_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                http_status INTEGER,
                request_id TEXT,
                response_time REAL,
                result_count INTEGER NOT NULL DEFAULT 0,
                accepted_count INTEGER NOT NULL DEFAULT 0,
                rejected_count INTEGER NOT NULL DEFAULT 0,
                credits_used INTEGER,
                error_type TEXT,
                error_message TEXT,
                raw_response_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_website_search_attempts_company
                ON website_search_attempts(company_id, id DESC);
            CREATE TABLE IF NOT EXISTS website_pages (
                id INTEGER PRIMARY KEY,
                website_id INTEGER REFERENCES company_websites(id),
                company_id INTEGER NOT NULL REFERENCES companies(id),
                url TEXT NOT NULL,
                page_type TEXT,
                http_status INTEGER,
                title TEXT,
                meta_description TEXT,
                h1 TEXT,
                visible_text_path TEXT,
                html_snapshot_path TEXT,
                content_hash TEXT,
                fetched_at TEXT NOT NULL,
                parse_status TEXT NOT NULL,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                UNIQUE(company_id, url, content_hash)
            );
            CREATE TABLE IF NOT EXISTS website_keywords (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                website_id INTEGER REFERENCES company_websites(id),
                keyword_type TEXT NOT NULL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                score REAL NOT NULL,
                occurrences INTEGER NOT NULL,
                page_urls_json TEXT NOT NULL,
                contexts_json TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(company_id, website_id, keyword_type, normalized_text, algorithm_version)
            );
            CREATE TABLE IF NOT EXISTS transaction_features (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                feature_name TEXT NOT NULL,
                value_numeric REAL,
                value_text TEXT,
                period_start TEXT,
                period_end TEXT,
                algorithm_version TEXT NOT NULL,
                calculated_at TEXT NOT NULL,
                UNIQUE(company_id, feature_name, period_start, period_end, algorithm_version)
            );
            CREATE TABLE IF NOT EXISTS website_signals (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                signal_code TEXT NOT NULL,
                signal_class TEXT,
                found_text TEXT,
                page_url TEXT,
                weight REAL,
                algorithm_version TEXT NOT NULL,
                collected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS classification_results (
                id INTEGER PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                predicted_class TEXT NOT NULL,
                class_probabilities_json TEXT,
                used_features_json TEXT,
                explanation TEXT,
                run_at TEXT NOT NULL,
                UNIQUE(company_id, model_name, model_version, run_at)
            );
            CREATE TABLE IF NOT EXISTS company_target_mappings (
                source_sheet TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                operation_id TEXT NOT NULL,
                target_side TEXT,
                source_inn TEXT,
                source_name TEXT,
                company_id INTEGER REFERENCES companies(id),
                mapping_method TEXT NOT NULL,
                mapping_status TEXT NOT NULL,
                raw_target TEXT,
                normalized_target TEXT,
                target_status TEXT NOT NULL,
                gold_company_id TEXT,
                PRIMARY KEY(source_sheet, source_row)
            );
            CREATE TABLE IF NOT EXISTS company_targets (
                company_id INTEGER PRIMARY KEY REFERENCES companies(id),
                target_class TEXT,
                target_status TEXT NOT NULL,
                labeled_operations_count INTEGER NOT NULL,
                source_sheet TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            -- A curated, local lookup layer.  It is intentionally separate
            -- from facts scraped during an individual run: only records that
            -- were explicitly activated may short-circuit external research.
            CREATE TABLE IF NOT EXISTS reference_companies (
                inn TEXT PRIMARY KEY,
                legal_name TEXT NOT NULL,
                kpp TEXT,
                ogrn TEXT,
                reference_class TEXT NOT NULL CHECK(reference_class IN ('A', 'B', 'NON_FINTECH')),
                classification_basis TEXT NOT NULL,
                official_website TEXT NOT NULL,
                official_domain TEXT NOT NULL,
                website_keywords_json TEXT NOT NULL DEFAULT '[]',
                website_keyphrases_json TEXT NOT NULL DEFAULT '[]',
                website_signals_json TEXT NOT NULL DEFAULT '[]',
                legal_sources_json TEXT NOT NULL DEFAULT '[]',
                website_sources_json TEXT NOT NULL DEFAULT '[]',
                verification_status TEXT NOT NULL CHECK(verification_status IN ('active', 'pending_manual_verification', 'rejected')),
                catalog_version TEXT NOT NULL,
                verified_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reference_company_aliases (
                inn TEXT NOT NULL REFERENCES reference_companies(inn) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                source_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(inn, normalized_alias, source_name)
            );
            CREATE INDEX IF NOT EXISTS idx_reference_companies_status
                ON reference_companies(verification_status, inn);
            """
        )
        # The initial project created ``website_signals`` for future use.  Keep
        # it compatible with installations made before this website stage.
        for column, definition in (
            ("website_id", "INTEGER REFERENCES company_websites(id)"),
            ("signal_family", "TEXT"), ("preliminary_class", "TEXT"),
            ("matched_phrase", "TEXT"), ("normalized_phrase", "TEXT"),
            ("context", "TEXT"), ("page_url", "TEXT"), ("html_zone", "TEXT"),
            ("occurrence_count", "INTEGER NOT NULL DEFAULT 1"),
            ("source_urls_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("independent_page_count", "INTEGER NOT NULL DEFAULT 1"),
        ):
            try:
                self.connection.execute(f"ALTER TABLE website_signals ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        try:
            self.connection.execute("ALTER TABLE website_candidates ADD COLUMN candidate_source TEXT")
        except sqlite3.OperationalError:
            pass
        # Website lifecycle is intentionally independent: a found domain can
        # time out without becoming "not found" or "rejected".
        for table, column, definition in (
            ("website_candidates", "discovery_status", "TEXT NOT NULL DEFAULT 'found'"),
            ("website_candidates", "verification_status", "TEXT NOT NULL DEFAULT 'not_started'"),
            ("website_candidates", "fetch_status", "TEXT NOT NULL DEFAULT 'not_started'"),
            ("website_candidates", "analysis_status", "TEXT NOT NULL DEFAULT 'not_started'"),
            ("website_candidates", "registry_sources_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("website_candidates", "source_type", "TEXT NOT NULL DEFAULT 'search_result'"),
            ("website_candidates", "domain_role", "TEXT NOT NULL DEFAULT 'OFFICIAL_CANDIDATE'"),
            ("website_candidates", "role_reason", "TEXT"),
            ("website_candidates", "brand_match", "INTEGER NOT NULL DEFAULT 0"),
            ("website_candidates", "title_match", "INTEGER NOT NULL DEFAULT 0"),
            ("website_candidates", "search_score", "REAL NOT NULL DEFAULT 0"),
            ("website_candidates", "verification_score", "REAL NOT NULL DEFAULT 0"),
            ("website_candidates", "rejection_reason", "TEXT"),
            ("website_candidates", "selected", "INTEGER NOT NULL DEFAULT 0"),
            ("website_candidates", "hard_rejected", "INTEGER NOT NULL DEFAULT 0"),
            ("website_candidates", "shortlist_eligible", "INTEGER NOT NULL DEFAULT 0"),
            ("website_candidates", "selection_status", "TEXT NOT NULL DEFAULT 'NOT_CHECKED'"),
            ("website_candidates", "score_components_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("website_candidates", "identity_evidence_scope", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
            ("company_websites", "discovery_status", "TEXT NOT NULL DEFAULT 'found'"),
            ("company_websites", "fetch_status", "TEXT NOT NULL DEFAULT 'not_started'"),
            ("company_websites", "analysis_status", "TEXT NOT NULL DEFAULT 'not_started'"),
        ):
            try:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        self.connection.commit()

    def upsert_reference_company(self, record: dict[str, Any]) -> None:
        """Store one curated company record.

        A reference record is not a replacement for the factual registry
        tables.  It is a deliberately curated assertion used only when its
        ``verification_status`` is ``active``.  This makes it safe to import a
        broad review queue without accidentally turning noisy data into an
        automatic classification rule.
        """
        inn = str(record.get("inn") or "").strip()
        if not valid_inn(inn):
            raise ValueError("Reference catalogue requires a valid INN")
        reference_class = str(record.get("reference_class") or "").strip()
        if reference_class not in {"A", "B", "NON_FINTECH"}:
            raise ValueError("Reference catalogue class must be A, B or NON_FINTECH")
        legal_name = str(record.get("legal_name") or "").strip()
        website = str(record.get("official_website") or "").strip()
        domain = str(record.get("official_domain") or "").strip().lower()
        if not legal_name or not website or not domain:
            raise ValueError("Reference catalogue requires legal_name, official_website and official_domain")
        status = str(record.get("verification_status") or "pending_manual_verification")
        if status not in {"active", "pending_manual_verification", "rejected"}:
            raise ValueError(f"Unsupported reference verification_status: {status}")
        now = utcnow()
        self.connection.execute(
            """INSERT INTO reference_companies(
                   inn, legal_name, kpp, ogrn, reference_class, classification_basis,
                   official_website, official_domain, website_keywords_json,
                   website_keyphrases_json, website_signals_json, legal_sources_json,
                   website_sources_json, verification_status, catalog_version,
                   verified_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(inn) DO UPDATE SET
                   legal_name=excluded.legal_name, kpp=excluded.kpp, ogrn=excluded.ogrn,
                   reference_class=excluded.reference_class, classification_basis=excluded.classification_basis,
                   official_website=excluded.official_website, official_domain=excluded.official_domain,
                   website_keywords_json=excluded.website_keywords_json,
                   website_keyphrases_json=excluded.website_keyphrases_json,
                   website_signals_json=excluded.website_signals_json,
                   legal_sources_json=excluded.legal_sources_json,
                   website_sources_json=excluded.website_sources_json,
                   verification_status=excluded.verification_status,
                   catalog_version=excluded.catalog_version, verified_at=excluded.verified_at,
                   updated_at=excluded.updated_at""",
            (
                inn, legal_name, str(record.get("kpp") or "").strip() or None,
                str(record.get("ogrn") or "").strip() or None, reference_class,
                str(record.get("classification_basis") or "").strip(), website, domain,
                canonical_json(record.get("website_keywords") or []),
                canonical_json(record.get("website_keyphrases") or []),
                canonical_json(record.get("website_signals") or []),
                canonical_json(record.get("legal_sources") or []),
                canonical_json(record.get("website_sources") or []), status,
                str(record.get("catalog_version") or "reference-v1"),
                record.get("verified_at"), now, now,
            ),
        )
        aliases = {legal_name, *(str(value).strip() for value in record.get("aliases") or [] if str(value).strip())}
        for alias in aliases:
            self.connection.execute(
                """INSERT OR IGNORE INTO reference_company_aliases(inn, alias, normalized_alias, source_name, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (inn, alias, clean_text(alias), "reference_catalog", now),
            )

    def get_active_reference_company(self, inn: str | None) -> dict[str, Any] | None:
        """Return only an explicitly activated, valid-INN lookup record."""
        value = str(inn or "").strip()
        if not valid_inn(value):
            return None
        row = self.connection.execute(
            "SELECT * FROM reference_companies WHERE inn=? AND verification_status='active'", (value,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in (
            "website_keywords_json", "website_keyphrases_json", "website_signals_json",
            "legal_sources_json", "website_sources_json",
        ):
            try:
                result[key[:-5]] = json.loads(result.pop(key) or "[]")
            except (TypeError, json.JSONDecodeError):
                result[key[:-5]] = []
        result["aliases"] = [item[0] for item in self.connection.execute(
            "SELECT alias FROM reference_company_aliases WHERE inn=? ORDER BY alias", (value,)
        ).fetchall()]
        return result

    def reference_catalog_stats(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT verification_status, COUNT(*) AS count FROM reference_companies GROUP BY verification_status"
        ).fetchall()
        return {str(row["verification_status"]): int(row["count"]) for row in rows}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def find_request(self, source_lookup_id: str | None) -> sqlite3.Row | None:
        if not source_lookup_id:
            return None
        return self.connection.execute(
            "SELECT * FROM research_requests WHERE source_lookup_id = ? ORDER BY id DESC LIMIT 1", (source_lookup_id,)
        ).fetchone()

    def upsert_company(self, inn: str, aliases: list[str] | None = None) -> int:
        if not valid_inn(inn):
            raise ValueError("A company can only be created from a valid INN")
        now = utcnow()
        company_key = f"inn:{inn}"
        self.connection.execute(
            """INSERT INTO companies(company_key, inn, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(inn) DO UPDATE SET updated_at=excluded.updated_at""",
            (company_key, inn, now, now),
        )
        company_id = int(self.connection.execute("SELECT id FROM companies WHERE inn = ?", (inn,)).fetchone()[0])
        for alias in aliases or []:
            self.add_alias(company_id, None, alias, "request_name", "payment_request")
        return company_id

    def update_company_facts(self, company_id: int, facts: dict[str, str]) -> None:
        """Copy only known, non-conflicting canonical values to company columns."""
        mapping = {
            "legal_name": "confirmed_legal_name", "kpp": "kpp", "ogrn": "ogrn",
            "address": "legal_address", "region": "region", "registration_status": "registration_status",
            "registration_date": "registration_date", "legal_form": "legal_form",
        }
        updates = {column: facts[key] for key, column in mapping.items() if facts.get(key)}
        if not updates:
            return
        updates["updated_at"] = utcnow()
        assignments = ", ".join(f"{column}=?" for column in updates)
        self.connection.execute(f"UPDATE companies SET {assignments} WHERE id=?", (*updates.values(), company_id))

    def add_alias(self, company_id: int | None, request_id: int | None, original_name: str,
                  alias_kind: str, source_name: str | None, source_result_id: int | None = None) -> None:
        name = str(original_name).strip()
        if not name:
            return
        normalized = clean_text(name)
        exists = self.connection.execute(
            """SELECT id FROM company_aliases WHERE company_id IS ? AND research_request_id IS ?
               AND original_name = ? AND alias_kind = ? AND source_name IS ? LIMIT 1""",
            (company_id, request_id, name, alias_kind, source_name),
        ).fetchone()
        if not exists:
            self.connection.execute(
                """INSERT INTO company_aliases(company_id, research_request_id, original_name, normalized_name,
                   alias_kind, source_name, source_result_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (company_id, request_id, name, normalized, alias_kind, source_name, source_result_id, utcnow()),
            )

    def import_request(self, request: dict[str, Any], source_file: str | None = None, source_row: int | None = None) -> int:
        inn = str(request.get("inn") or "").strip() or None
        company_id = self.upsert_company(inn, request.get("legal_name_candidates", [])) if inn and valid_inn(inn) else None
        external_id = stable_request_id(request)
        now = utcnow()
        self.connection.execute(
            """INSERT INTO research_requests(external_request_id, source_lookup_id, source_file, source_row,
               company_id, request_status, raw_request_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(external_request_id) DO UPDATE SET
                 source_lookup_id=excluded.source_lookup_id, source_file=excluded.source_file, source_row=excluded.source_row,
                 company_id=excluded.company_id, request_status=excluded.request_status,
                 raw_request_json=excluded.raw_request_json, updated_at=excluded.updated_at""",
            (external_id, request.get("lookup_id"), source_file, source_row, company_id,
             request.get("lookup_status") or "unknown", canonical_json(request), now, now),
        )
        request_id = int(self.connection.execute("SELECT id FROM research_requests WHERE external_request_id = ?", (external_id,)).fetchone()[0])
        for name in request.get("legal_name_candidates", []):
            self.add_alias(company_id, request_id if company_id is None else None, name, "request_name", "payment_request")
        for operation_id in request.get("operation_ids", []):
            self.connection.execute("INSERT OR IGNORE INTO request_operations(research_request_id, operation_id) VALUES (?, ?)", (request_id, str(operation_id)))
        return request_id

    def record_source_result(self, request_id: int | None, company_id: int | None, *, source_name: str,
                             input_inn: str | None, source_url: str | None, request_status: str,
                             inn_confirmed: bool, warnings: list[str] | None = None,
                             content: str | None = None, raw_result: dict[str, Any] | None = None,
                             snapshot_root: str | Path = "results/source_snapshots") -> int:
        snapshot_path, content_hash = None, None
        if content is not None:
            content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
            safe_inn = input_inn if input_inn and valid_inn(input_inn) else "unverified"
            safe_source = re.sub(r"[^a-zA-Z0-9_.-]+", "_", source_name)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            snapshot = Path(snapshot_root) / safe_inn / safe_source / f"{timestamp}_{content_hash[:12]}.html"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(content, encoding="utf-8")
            snapshot_path = str(snapshot)
        now = utcnow()
        self.connection.execute(
            """INSERT INTO source_results(research_request_id, company_id, source_name, input_inn, source_url,
               request_status, inn_confirmed, collected_at, snapshot_path, parse_warnings_json, content_hash, raw_result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(research_request_id, source_name, source_url) DO UPDATE SET
                 company_id=excluded.company_id, input_inn=excluded.input_inn, request_status=excluded.request_status,
                 inn_confirmed=excluded.inn_confirmed, collected_at=excluded.collected_at,
                 snapshot_path=COALESCE(excluded.snapshot_path, source_results.snapshot_path),
                 parse_warnings_json=excluded.parse_warnings_json,
                 content_hash=COALESCE(excluded.content_hash, source_results.content_hash), raw_result_json=excluded.raw_result_json""",
            (request_id, company_id, source_name, input_inn, source_url, request_status, int(inn_confirmed), now,
             snapshot_path, canonical_json(warnings or []), content_hash, canonical_json(raw_result or {})),
        )
        row = self.connection.execute(
            """SELECT id FROM source_results WHERE research_request_id IS ? AND source_name = ? AND source_url IS ?""",
            (request_id, source_name, source_url),
        ).fetchone()
        return int(row[0])

    def add_fact(self, company_id: int, field_name: str, value_text: str, *, source_result_id: int | None,
                 source_name: str | None, source_url: str | None, confidence: float | None = None) -> int:
        value = str(value_text).strip()
        normalized = clean_text(value)
        self.connection.execute(
            """INSERT OR IGNORE INTO company_facts(company_id, field_name, value_text, normalized_value,
               source_result_id, source_name, source_url, confidence, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, field_name, value, normalized, source_result_id, source_name, source_url, confidence, utcnow()),
        )
        self._refresh_fact_conflicts(company_id, field_name)
        return int(self.connection.execute(
            "SELECT id FROM company_facts WHERE company_id=? AND field_name=? AND normalized_value=? AND source_result_id IS ?",
            (company_id, field_name, normalized, source_result_id),
        ).fetchone()[0])

    def _refresh_fact_conflicts(self, company_id: int, field_name: str) -> None:
        rows = self.connection.execute(
            "SELECT DISTINCT normalized_value FROM company_facts WHERE company_id=? AND field_name=?", (company_id, field_name)
        ).fetchall()
        self.connection.execute("UPDATE company_facts SET is_conflicting=? WHERE company_id=? AND field_name=?",
                                (int(len(rows) > 1), company_id, field_name))

    def add_okved(self, company_id: int, code: str, name: str | None, is_primary: bool, *, source_result_id: int | None,
                  source_name: str | None, source_url: str | None, confidence: float | None = None) -> int:
        code = str(code).strip()
        self.connection.execute(
            """INSERT OR IGNORE INTO company_okved(company_id, okved_code, okved_name, is_primary,
               source_result_id, source_name, source_url, confidence, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, code, name or None, int(is_primary), source_result_id, source_name, source_url, confidence, utcnow()),
        )
        if is_primary:
            codes = self.connection.execute(
                "SELECT DISTINCT okved_code FROM company_okved WHERE company_id=? AND is_primary=1", (company_id,)
            ).fetchall()
            self.connection.execute("UPDATE company_okved SET is_conflicting=? WHERE company_id=? AND is_primary=1",
                                    (int(len(codes) > 1), company_id))
        return int(self.connection.execute(
            """SELECT id FROM company_okved WHERE company_id=? AND okved_code=? AND is_primary=? AND source_result_id IS ?""",
            (company_id, code, int(is_primary), source_result_id),
        ).fetchone()[0])

    def add_website(self, company_id: int, website_url: str, verification_status: str,
                    verification_score: float | None, source: str | None, *, discovery_status: str = "found",
                    fetch_status: str = "not_started", analysis_status: str = "not_started") -> None:
        from urllib.parse import urlparse
        domain = urlparse(website_url).netloc.lower() or None
        now = utcnow()
        self.connection.execute(
            """INSERT INTO company_websites(company_id, domain, website_url, verification_status,
               verification_score, source, created_at, updated_at, discovery_status, fetch_status, analysis_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(company_id, website_url, source) DO UPDATE SET domain=excluded.domain,
                 verification_status=excluded.verification_status, verification_score=excluded.verification_score,
                 discovery_status=excluded.discovery_status, fetch_status=excluded.fetch_status,
                 analysis_status=excluded.analysis_status, updated_at=excluded.updated_at""",
            (company_id, domain, website_url, verification_status, verification_score, source, now, now,
             discovery_status, fetch_status, analysis_status),
        )
        if verification_status in {"confirmed", "confirmed_by_registry", "confirmed_by_website"}:
            # A company may have several valid-looking URLs.  Never let the
            # last Tavily result overwrite a stronger, earlier verification
            # (e.g. an exact official legal page with score 1.0).
            best = self.connection.execute(
                """SELECT website_url FROM company_websites WHERE company_id=?
                   ORDER BY CASE verification_status WHEN 'confirmed_by_website' THEN 0
                                                     WHEN 'confirmed_by_registry' THEN 1
                                                     WHEN 'confirmed' THEN 1 ELSE 2 END,
                            COALESCE(verification_score, 0) DESC, id DESC LIMIT 1""",
                (company_id,),
            ).fetchone()
            if best and best["website_url"]:
                self.connection.execute("UPDATE companies SET official_website=?, updated_at=? WHERE id=?",
                                        (best["website_url"], now, company_id))

    def add_website_candidate(self, company_id: int, *, candidate_url: str, search_query: str,
                              candidate_source: str | None = None,
                              search_position: int | None, search_title: str | None,
                              search_snippet: str | None, score: float, status: str,
                              positive_evidence: list[str], negative_evidence: list[str],
                              checked_pages: list[str], discovery_status: str = "found",
                              verification_status: str = "not_started", fetch_status: str = "not_started",
                              analysis_status: str = "not_started", registry_sources: list[str] | None = None,
                              source_type: str = "search_result", domain_role: str = "OFFICIAL_CANDIDATE",
                              brand_match: bool = False, title_match: bool = False,
                              rejection_reason: str | None = None, role_reason: str | None = None,
                              search_score: float = 0.0, verification_score: float = 0.0,
                              selected: bool = False, hard_rejected: bool = False,
                              shortlist_eligible: bool = False, selection_status: str = "NOT_CHECKED",
                              score_components: dict[str, float] | None = None,
                              identity_evidence_scope: str = "UNKNOWN") -> int:
        from urllib.parse import urlparse
        now = utcnow()
        domain = urlparse(candidate_url).netloc.lower()
        self.connection.execute(
            """INSERT INTO website_candidates(company_id, candidate_url, domain, search_query, candidate_source, source_type, domain_role,
               role_reason, brand_match, title_match, search_score, verification_score, rejection_reason, selected, search_position,
               search_title, search_snippet, candidate_score, candidate_status, positive_evidence_json,
               negative_evidence_json, checked_pages_json, created_at, updated_at, discovery_status, verification_status,
               fetch_status, analysis_status, registry_sources_json, hard_rejected, shortlist_eligible,
               selection_status, score_components_json, identity_evidence_scope)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(company_id, candidate_url, search_query) DO UPDATE SET
                 candidate_source=excluded.candidate_source, source_type=excluded.source_type, domain_role=excluded.domain_role,
                 role_reason=excluded.role_reason, brand_match=excluded.brand_match, title_match=excluded.title_match,
                 search_score=excluded.search_score, verification_score=excluded.verification_score, rejection_reason=excluded.rejection_reason,
                 selected=excluded.selected, search_position=excluded.search_position, search_title=excluded.search_title,
                 search_snippet=excluded.search_snippet, candidate_score=excluded.candidate_score,
                 candidate_status=excluded.candidate_status, positive_evidence_json=excluded.positive_evidence_json,
                 negative_evidence_json=excluded.negative_evidence_json, checked_pages_json=excluded.checked_pages_json,
                 discovery_status=excluded.discovery_status, verification_status=excluded.verification_status,
                 fetch_status=excluded.fetch_status, analysis_status=excluded.analysis_status,
                 registry_sources_json=excluded.registry_sources_json, hard_rejected=excluded.hard_rejected,
                 shortlist_eligible=excluded.shortlist_eligible, selection_status=excluded.selection_status,
                 score_components_json=excluded.score_components_json, identity_evidence_scope=excluded.identity_evidence_scope,
                 updated_at=excluded.updated_at""",
            (company_id, candidate_url, domain, search_query, candidate_source, source_type, domain_role, role_reason,
             int(brand_match), int(title_match), search_score, verification_score, rejection_reason, int(selected), search_position, search_title, search_snippet,
             score, status, canonical_json(positive_evidence), canonical_json(negative_evidence),
             canonical_json(checked_pages), now, now, discovery_status, verification_status, fetch_status,
             analysis_status, canonical_json(registry_sources or []), int(hard_rejected), int(shortlist_eligible),
             selection_status, canonical_json(score_components or {}), identity_evidence_scope),
        )
        return int(self.connection.execute(
            "SELECT id FROM website_candidates WHERE company_id=? AND candidate_url=? AND search_query=?",
            (company_id, candidate_url, search_query),
        ).fetchone()[0])

    def record_website_search_attempt(self, company_id: int, attempt: dict[str, Any]) -> int:
        """Persist provider audit data without headers or secrets."""
        now = utcnow()
        raw = attempt.get("raw_response") or {}
        self.connection.execute(
            """INSERT INTO website_search_attempts(company_id, provider, reason_for_call, template_id,
               search_query, include_domains_json, exclude_domains_json, started_at, finished_at, status,
               http_status, request_id, response_time, result_count, accepted_count, rejected_count,
               credits_used, error_type, error_message, raw_response_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, attempt.get("provider") or "unknown", attempt.get("reason_for_call"),
             attempt.get("template_id"), attempt.get("query"), canonical_json(attempt.get("include_domains") or []),
             canonical_json(attempt.get("exclude_domains") or []), attempt.get("started_at") or now,
             attempt.get("finished_at") or now, attempt.get("status") or "not_started", attempt.get("http_status"),
             attempt.get("request_id"), attempt.get("response_time"), int(attempt.get("result_count") or 0),
             int(attempt.get("accepted_count") or 0), int(attempt.get("rejected_count") or 0),
             attempt.get("credits_used"), attempt.get("error_type"), attempt.get("error_message"), canonical_json(raw)),
        )
        return int(self.connection.execute("SELECT last_insert_rowid()").fetchone()[0])

    def website_search_attempts(self, company_id: int) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM website_search_attempts WHERE company_id=? ORDER BY id", (company_id,)
        ).fetchall()

    def confirmed_website(self, company_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            """SELECT * FROM company_websites WHERE company_id=? AND verification_status IN ('confirmed', 'confirmed_by_registry', 'confirmed_by_website')
               ORDER BY verification_score DESC, id DESC LIMIT 1""", (company_id,)
        ).fetchone()

    def analysis_website(self, company_id: int) -> sqlite3.Row | None:
        """Return a site safe to analyse without promoting a probable URL.

        A successful fetch of a registry-backed probable domain is usable text
        evidence, but it must not be returned by :meth:`confirmed_website` or
        copied into ``companies.official_website``.
        """
        return self.connection.execute(
            """SELECT * FROM company_websites
               WHERE company_id=?
                 AND (verification_status IN ('confirmed', 'confirmed_by_registry', 'confirmed_by_website')
                      OR (verification_status='probable' AND fetch_status='success'))
               ORDER BY CASE WHEN verification_status LIKE 'confirmed%' OR verification_status='confirmed' THEN 1 ELSE 0 END DESC,
                        verification_score DESC, id DESC
               LIMIT 1""", (company_id,)
        ).fetchone()

    def update_website_analysis_status(self, website_id: int, status: str) -> None:
        self.connection.execute(
            "UPDATE company_websites SET analysis_status=?, updated_at=? WHERE id=?",
            (status, utcnow(), website_id),
        )

    def update_candidate_analysis_status(self, company_id: int, candidate_url: str, status: str) -> None:
        self.connection.execute(
            "UPDATE website_candidates SET analysis_status=?, updated_at=? WHERE company_id=? AND candidate_url=?",
            (status, utcnow(), company_id, candidate_url),
        )

    def add_website_page(self, website_id: int, company_id: int, *, url: str, page_type: str,
                         http_status: int | None, title: str | None, meta_description: str | None,
                         h1: str | None, visible_text_path: str | None, html_snapshot_path: str | None,
                         content_hash: str | None, parse_status: str, warnings: list[str]) -> None:
        self.connection.execute(
            """INSERT OR IGNORE INTO website_pages(website_id, company_id, url, page_type, http_status, title,
               meta_description, h1, visible_text_path, html_snapshot_path, content_hash, fetched_at, parse_status, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (website_id, company_id, url, page_type, http_status, title, meta_description, h1,
             visible_text_path, html_snapshot_path, content_hash, utcnow(), parse_status, canonical_json(warnings)),
        )

    def replace_website_keywords(self, company_id: int, website_id: int, entries: list[dict[str, Any]], algorithm_version: str) -> None:
        for entry in entries:
            self.connection.execute(
                """INSERT INTO website_keywords(company_id, website_id, keyword_type, text, normalized_text, score,
                   occurrences, page_urls_json, contexts_json, algorithm_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id, website_id, keyword_type, normalized_text, algorithm_version) DO UPDATE SET
                     text=excluded.text, score=excluded.score, occurrences=excluded.occurrences,
                     page_urls_json=excluded.page_urls_json, contexts_json=excluded.contexts_json, created_at=excluded.created_at""",
                (company_id, website_id, entry["keyword_type"], entry["text"], entry["normalized_text"], entry["score"],
                 entry["occurrences"], canonical_json(entry["page_urls"]), canonical_json(entry["contexts"]), algorithm_version, utcnow()),
            )

    def add_website_signal(self, company_id: int, website_id: int, *, family: str, code: str,
                           preliminary_class: str, phrase: str, normalized_phrase: str, context: str,
                           page_url: str, html_zone: str, weight: float, algorithm_version: str,
                           occurrence_count: int = 1, source_urls: list[str] | None = None,
                           independent_page_count: int = 1) -> None:
        """Store one semantic evidence item once, with repeat metadata.

        SQLite installations before the website phase have no unique signal
        index, so the deterministic lookup is deliberately explicit.
        """
        existing = self.connection.execute(
            """SELECT id, occurrence_count, source_urls_json FROM website_signals
               WHERE company_id=? AND website_id=? AND signal_code=? AND normalized_phrase=? AND page_url=? AND algorithm_version=?
               ORDER BY id LIMIT 1""",
            (company_id, website_id, code, normalized_phrase, page_url, algorithm_version),
        ).fetchone()
        urls = sorted(set(source_urls or [page_url]))
        if existing:
            try:
                urls = sorted(set(urls + json.loads(existing[2] or "[]")))
            except (TypeError, json.JSONDecodeError):
                pass
            self.connection.execute(
                "UPDATE website_signals SET occurrence_count=?, source_urls_json=?, independent_page_count=? WHERE id=?",
                (max(int(existing[1] or 1), occurrence_count), canonical_json(urls), max(1, independent_page_count), existing[0]),
            )
            return
        self.connection.execute(
            """INSERT INTO website_signals(company_id, website_id, signal_family, signal_code, preliminary_class,
               matched_phrase, normalized_phrase, context, page_url, html_zone, weight, algorithm_version, collected_at,
               occurrence_count, source_urls_json, independent_page_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, website_id, family, code, preliminary_class, phrase, normalized_phrase, context,
             page_url, html_zone, weight, algorithm_version, utcnow(), max(1, occurrence_count), canonical_json(urls), max(1, independent_page_count)),
        )

    def companies_for_okved(self, limit: int, inn: str | None = None) -> list[sqlite3.Row]:
        if inn:
            return self.connection.execute("SELECT * FROM companies WHERE inn=?", (inn,)).fetchall()
        return self.connection.execute(
            """SELECT companies.* FROM companies
               WHERE NOT EXISTS (SELECT 1 FROM company_okved WHERE company_okved.company_id=companies.id)
               ORDER BY companies.id LIMIT ?""", (limit,)
        ).fetchall()

    def request_for_company(self, company_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM research_requests WHERE company_id=? ORDER BY id LIMIT 1", (company_id,)
        ).fetchone()
