"""The data catalog (M29): what each table and column means, checked against the database.

Descriptions, grain, caveats, allowed values and personal-data flags are written by people in
backend/catalog/*.toml and reviewed in git. Types, keys, relationships and row counts are never
typed by hand: introspect() reads them from the database, and drift() reports any disagreement.
"""
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "catalog"
DOMAINS = ("Geography", "Product", "Customers", "Sales", "Supply chain", "Marketing and service", "People")
TABLE_KEYS = {"description", "grain", "caveats", "columns"}
COLUMN_KEYS = {"description", "values", "unit", "pii"}
METRIC_KEYS = {"description", "expression", "filters", "tables", "unit"}


class CatalogError(Exception):
    """A catalog file is missing, unreadable or malformed."""


@dataclass
class Column:
    name: str
    description: str
    values: tuple = ()
    unit: str = ""
    pii: bool = False


@dataclass
class Table:
    name: str
    domain: str
    description: str
    grain: str
    caveats: tuple = ()
    columns: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    expression: str
    filters: tuple
    tables: tuple
    unit: str


@dataclass
class Catalog:
    path: Path
    tables: dict
    metrics: dict
    hints: tuple = ()


def _read(path):
    try:
        return tomllib.loads(path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise CatalogError(f"{path.name} could not be read: {e}") from e


def _unknown(keys, allowed, where):
    extra = sorted(set(keys) - allowed)
    if extra:
        raise CatalogError(f"Unknown key in {where}: {', '.join(extra)}")


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{where} needs a non-empty description.")
    return value.strip()


def _column(name, raw, where):
    if isinstance(raw, str):
        return Column(name, _text(raw, where))
    if not isinstance(raw, dict):
        raise CatalogError(f"{where} must be a description or a table.")
    _unknown(raw, COLUMN_KEYS, where)
    values = raw.get("values", [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise CatalogError(f"{where} values must be a list of strings.")
    if not isinstance(raw.get("pii", False), bool):
        raise CatalogError(f"{where} pii must be true or false.")
    return Column(name, _text(raw.get("description"), where), tuple(values), str(raw.get("unit", "")),
                  raw.get("pii", False))


def _metric(name, raw, where):
    _unknown(raw, METRIC_KEYS, where)
    filters, tables = raw.get("filters", []), raw.get("tables", [])
    if not isinstance(filters, list) or not isinstance(tables, list) or not tables:
        raise CatalogError(f"{where} needs a list of filters and a non-empty list of tables.")
    return Metric(name, _text(raw.get("description"), where), _text(raw.get("expression"), f"{where} expression"),
                  tuple(filters), tuple(tables), str(raw.get("unit", "")))


def load(path=None):
    path = Path(path or DEFAULT_DIR)
    files = sorted(path.glob("*.toml"))
    if not files:
        raise CatalogError(f"No catalog files in {path}.")
    tables, metrics, hints = {}, {}, ()
    for f in files:
        doc = _read(f)
        if f.name == "hints.toml":
            _unknown(doc, {"hints"}, f.name)
            raw = doc.get("hints")
            if not isinstance(raw, list) or not raw or not all(isinstance(h, str) and h.strip() for h in raw):
                raise CatalogError("hints.toml: hints must be a non-empty list of text.")
            hints = tuple(h.strip() for h in raw)
            continue
        if f.name == "metrics.toml":
            _unknown(doc, {"metrics"}, f.name)
            for name, raw in doc.get("metrics", {}).items():
                metrics[name] = _metric(name, raw, f"{f.name} [metrics.{name}]")
            continue
        _unknown(doc, {"domain", "tables"}, f.name)
        domain = doc.get("domain")
        if domain not in DOMAINS:
            raise CatalogError(f"{f.name}: unknown domain {domain!r}; use one of {', '.join(DOMAINS)}.")
        for name, raw in doc.get("tables", {}).items():
            where = f"{f.name} [tables.{name}]"
            if name in tables:
                raise CatalogError(f"{where}: table {name} is described twice.")
            if not isinstance(raw, dict):
                raise CatalogError(f"{where} must be a table.")
            _unknown(raw, TABLE_KEYS, where)
            caveats = raw.get("caveats", [])
            if not isinstance(caveats, list) or not all(isinstance(c, str) for c in caveats):
                raise CatalogError(f"{where} caveats must be a list of strings.")
            columns = raw.get("columns") or {}
            if not columns:
                raise CatalogError(f"{where} describes no columns.")
            tables[name] = Table(
                name, domain, _text(raw.get("description"), where), _text(raw.get("grain"), f"{where} grain"),
                tuple(caveats), {c: _column(c, v, f"{where} column {c}") for c, v in columns.items()})
    for m in metrics.values():
        unknown = set(m.tables) - set(tables)
        if unknown:
            raise CatalogError(f"Metric {m.name} uses undescribed tables: {', '.join(sorted(unknown))}")
    return Catalog(path, tables, metrics, hints)


# ---- the database side ----------------------------------------------------------------------------

COLUMNS_SQL = """
    SELECT table_name, column_name, data_type FROM information_schema.columns
    WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"""
PRIMARY_KEYS_SQL = """
    SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
    ORDER BY tc.table_name, kcu.ordinal_position"""
FOREIGN_KEYS_SQL = """
    SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, af.attname
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]
    WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace"""
ROWS_SQL = """
    SELECT c.relname, greatest(c.reltuples, 0)::bigint FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"""


def introspect(run):
    """Tables as the database sees them. `run(sql, params)` returns rows; with a role's read-only
    login, Postgres lists only the tables and columns that login may read."""
    db = {}
    for table, column, dtype in run(COLUMNS_SQL):
        db.setdefault(table, {"columns": {}, "primary_key": [], "foreign_keys": [], "rows": 0})
        db[table]["columns"][column] = dtype
    for table, column in run(PRIMARY_KEYS_SQL):
        if table in db:
            db[table]["primary_key"].append(column)
    for table, column, ref_table, ref_column in run(FOREIGN_KEYS_SQL):
        if table in db:
            db[table]["foreign_keys"].append((column, ref_table, ref_column))
    for table, rows in run(ROWS_SQL):
        if table in db:
            db[table]["rows"] = rows
    return db


def drift(cat, db):
    """Differences between the catalog and the database; an empty list means they agree."""
    problems = []
    for name in sorted(set(db) - set(cat.tables)):
        problems.append(f"table {name} is in the database but not described in the catalog")
    for name in sorted(set(cat.tables) - set(db)):
        problems.append(f"table {name} is described in the catalog but not in the database")
    for name in sorted(set(db) & set(cat.tables)):
        described, actual = set(cat.tables[name].columns), set(db[name]["columns"])
        problems += [f"column {name}.{c} is in the database but not described" for c in sorted(actual - described)]
        problems += [f"column {name}.{c} is described but not in the database" for c in sorted(described - actual)]
    return problems


@lru_cache(maxsize=1)
def get():
    """The catalog in backend/catalog, loaded once."""
    return load()
