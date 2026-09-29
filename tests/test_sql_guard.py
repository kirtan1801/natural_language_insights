import pytest

from natural_language_insights.qa import UnsafeSql, guard_sql

TABLE = '"dataset_abc"'


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT * FROM "dataset_abc"',
        'SELECT a, SUM(b) FROM "dataset_abc" GROUP BY 1 ORDER BY 2 DESC LIMIT 10',
        'WITH t AS (SELECT * FROM "dataset_abc") SELECT COUNT(*) FROM t',
        'SELECT 1 FROM "dataset_abc" x JOIN "dataset_abc" y ON x.a = y.a',
        'SELECT a FROM "dataset_abc" UNION ALL SELECT b FROM "dataset_abc"',
    ],
)
def test_allows_reads_of_the_dataset(sql):
    guard_sql(sql, TABLE)


@pytest.mark.parametrize(
    "sql",
    [
        'DROP TABLE "dataset_abc"',
        'DELETE FROM "dataset_abc"',
        'INSERT INTO "dataset_abc" VALUES (1)',
        'SELECT 1 FROM "dataset_abc"; DROP TABLE "dataset_abc"',
        'SELECT * FROM "dataset_other"',
        "SELECT * FROM datasets",
        "SELECT * FROM jobs",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/passwd')",
        "SELECT * FROM information_schema.tables",
        "COPY (SELECT 1) TO '/tmp/x.csv'",
        "ATTACH '/tmp/x.db'",
        "PRAGMA database_list",
        "not sql at all (",
    ],
)
def test_rejects_everything_else(sql):
    with pytest.raises(UnsafeSql):
        guard_sql(sql, TABLE)


def test_constructs_duckdb_lacks_get_a_precise_error():
    sql = 'SELECT ARRAY_AGG(a ORDER BY b DESC LIMIT 5) FROM "dataset_abc"'
    with pytest.raises(UnsafeSql, match="LIMIT inside ARRAY_AGG"):
        guard_sql(sql, TABLE)


def test_duckdb_top_n_idiom_is_allowed():
    guard_sql('SELECT list(a ORDER BY b DESC)[1:5] FROM "dataset_abc"', TABLE)
