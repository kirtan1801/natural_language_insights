# DuckDB SQL notes

Your query runs on DuckDB. Syntax from BigQuery, Postgres, MySQL or SQL Server often fails
here. Use these forms.

## Does not work in DuckDB, use instead

| Don't write | Write |
|---|---|
| `ARRAY_AGG(x ORDER BY y LIMIT 5)` (LIMIT inside any aggregate) | `list(x ORDER BY y DESC)[1:5]`, or `ROW_NUMBER()` in a CTE |
| `SELECT TOP 10 ...` | `... ORDER BY ... LIMIT 10` |
| `DATE_SUB(d, INTERVAL 1 DAY)`, `DATEADD(...)` | `d - INTERVAL 1 DAY`, `d + INTERVAL 3 MONTH` |
| `DATEDIFF(d1, d2)` | `date_diff('day', d1, d2)` |
| `FORMAT_DATE('%Y-%m', d)`, `TO_CHAR(d, ...)` | `strftime(d, '%Y-%m')` |
| `EXTRACT(QUARTER FROM d)` is fine; `QUARTER(d)` also works | `year(d)`, `quarter(d)`, `month(d)` |
| `ISNULL(x, 0)`, `IFNULL`, `NVL` | `coalesce(x, 0)` |
| `x / y` expecting integer division | `/` always returns a decimal (7 / 2 = 3.5); `//` is integer division |
| backticks or `[brackets]` around names | double quotes: `"column name"` |
| double quotes around text | single quotes: `'United Kingdom'` |
| `GROUP_CONCAT(x)` | `string_agg(x, ', ' ORDER BY x)` |
| `PERCENTILE_CONT(0.5) WITHIN GROUP (...)` | `median(x)`, `quantile_cont(x, 0.9)` |

## Useful DuckDB features

- **Top N per group:** `QUALIFY ROW_NUMBER() OVER (PARTITION BY g ORDER BY v DESC) <= 3`
- **Conditional aggregates:** `SUM(amount) FILTER (WHERE period = 'Q3')`
- **Group by every non-aggregate column:** `GROUP BY ALL`
- **Truncate dates:** `date_trunc('month', ts)`, `date_trunc('quarter', ts)`
- **Safe casts:** `TRY_CAST(x AS DOUBLE)` returns NULL instead of failing. Use it for numbers stored as text.
- **Case-insensitive match:** `ILIKE '%gift%'`
- **Nulls in rankings:** `ORDER BY v DESC NULLS LAST`
- **Shares and percentages:** multiply by `100.0` and use `ROUND(x, 2)`. Division by zero returns NULL. Use `NULLIF(denominator, 0)` to be explicit.
