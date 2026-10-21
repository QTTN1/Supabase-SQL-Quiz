from dataclasses import dataclass
from decimal import Decimal

import psycopg2
from pglast import parse_sql
from pglast.ast import SelectStmt
from pglast.parser import ParseError


MAX_RESULT_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class Question:
    question_id: str
    title: str
    prompt: str
    answer_sql: str
    expected_result: str
    hints: tuple[str, str]
    points: int = 4


QUESTIONS = tuple(sorted((
    Question(
        question_id="brand-counts",
        title="Above-average brand catalogs",
        prompt=(
            "Return each brand whose product count is greater than the average "
            "product count across all brands. Show the brand and product count, "
            "ordered from the largest catalog to the smallest."
        ),
        answer_sql="""WITH brand_counts AS (
    SELECT b.id, b.name, COUNT(p.id) AS product_count
    FROM brands AS b
    JOIN products AS p ON p.brand_id = b.id
    GROUP BY b.id, b.name
)
SELECT name, product_count
FROM brand_counts
WHERE product_count > (SELECT AVG(product_count) FROM brand_counts)
ORDER BY product_count DESC, name ASC;""",
        expected_result="""12 rows. In order: nyx (164), clinique (93), dior (74),
covergirl (54), maybelline (54), l'oreal (46), smashbox (46),
physicians formula (43), benefit (41), revlon (29), e.l.f. (27),
cargo cosmetics (20).""",
        hints=(
            "Count products for each brand by joining brands to products, then "
            "group by the brand's ID and name.",
            "Compare each brand's count with a scalar subquery that calculates "
            "the average of the per-brand counts. The result has brand and count "
            "columns, sorted by count descending.",
        ),
        points=3,
    ),
    Question(
        question_id="currency-normalized-category-averages",
        title="Compare category averages in USD",
        prompt=(
            "Normalize each product price to USD using these fixed quiz rates: "
            "USD = 1.00, CAD = 0.74, GBP = 1.28 (multiply the listed price by "
            "the rate). Among products with a price and one of these currencies, "
            "return each category whose average normalized price is above the "
            "overall average normalized price. Show the category, product count, "
            "and average price in USD, rounded to two decimals. Ignore products "
            "without a category when calculating category averages, but include "
            "them in the overall average. Order by category average descending. "
            "Use the listed rates as the conversion rates for this quiz."
        ),
        answer_sql="""WITH converted_products AS (
    SELECT p.category_id,
           p.price * CASE p.currency
               WHEN 'USD' THEN 1.00
               WHEN 'CAD' THEN 0.74
               WHEN 'GBP' THEN 1.28
           END AS price_usd
    FROM products AS p
    WHERE p.price IS NOT NULL
      AND p.currency IN ('USD', 'CAD', 'GBP')
),
category_averages AS (
    SELECT c.id, c.name, COUNT(*) AS product_count,
           AVG(cp.price_usd) AS average_price_usd
    FROM converted_products AS cp
    JOIN categories AS c ON c.id = cp.category_id
    GROUP BY c.id, c.name
)
SELECT name AS category, product_count,
       ROUND(average_price_usd, 2) AS average_price_usd
FROM category_averages
WHERE average_price_usd > (
    SELECT AVG(price_usd) FROM converted_products
)
ORDER BY average_price_usd DESC, category ASC;""",
        expected_result="""5 rows. The overall average for all 368 products with a price
and a listed currency is 16.90 USD. In order (category, product count, average
USD price): bb_cc / 2 / 38.75; highlighter / 2 / 32.06; contour / 3 / 28.33;
palette / 10 / 22.74; concealer / 18 / 17.03.""",
        hints=(
            "Use a CASE expression to multiply each price by its currency's "
            "fixed USD rate. Exclude rows without a price or a recognized currency.",
            "A CTE can hold converted prices. Aggregate those prices by category, "
            "then compare each category average with a scalar subquery for the "
            "overall average. Return category, count, and rounded USD average.",
        ),
        points=6,
    ),
    Question(
        question_id="nyx-description-search",
        title="NYX products matching description keywords",
        prompt=(
            "Find every NYX product priced below $10 USD whose description "
            "contains 'strong' or 'long-lasting' (case-insensitive). Also "
            "recognize the unhyphenated phrase 'long lasting'. Show product, "
            "category, price, currency, and description."
        ),
        answer_sql="""SELECT p.name AS product, c.name AS category,
       p.price, p.currency, p.description
FROM products AS p
JOIN brands AS b ON b.id = p.brand_id
LEFT JOIN categories AS c ON c.id = p.category_id
WHERE b.name = 'nyx'
  AND p.currency = 'USD'
  AND p.price < 10
  AND (
      p.description ILIKE '%strong%'
      OR p.description ILIKE '%long-lasting%'
      OR p.description ILIKE '%long lasting%'
  )
ORDER BY p.price ASC, p.name ASC;""",
        expected_result="""2 rows, ordered by price: Rouge Cream Blush (no category,
6.00 USD) and Tinted Brow Mascara (no category, 7.00 USD). The Rouge Cream
Blush description contains 'long-lasting'; Tinted Brow Mascara contains
'strong'.""",
        hints=(
            "Join products to brands to filter the NYX catalog. Use a "
            "case-insensitive text match on description and filter by USD price.",
            "Combine the two keyword checks with OR, keep the price strictly "
            "below 10, and left join categories so products without a category "
            "are still returned. Expect product, category, price, currency, and "
            "description columns.",
        ),
        points=2,
    ),
    Question(
        question_id="mascara-price-order",
        title="Average mascara price by brand",
        prompt=(
            "For each brand with at least one priced product whose name contains "
            "'mascara' (case-insensitive), return the number of mascara products "
            "and their average price. Group separately by currency so prices in "
            "different currencies are never averaged together; keep products "
            "with an unspecified currency in their own group. Include products "
            "with no brand in an '(unknown brand)' group. Round averages to two "
            "decimal places and sort alphabetically by brand."
        ),
        answer_sql="""SELECT COALESCE(b.name, '(unknown brand)') AS brand,
       p.currency,
       COUNT(*) AS mascara_count,
       ROUND(AVG(p.price), 2) AS average_mascara_price
FROM products AS p
LEFT JOIN brands AS b ON b.id = p.brand_id
WHERE p.price IS NOT NULL
  AND p.name ILIKE '%mascara%'
GROUP BY b.id, b.name, p.currency
ORDER BY b.name ASC NULLS LAST, p.currency ASC NULLS LAST;""",
        expected_result="""22 rows from 77 priced mascara products. Currency is unspecified
for groups where the source has no currency. In order (brand, currency, count,
average price): almay / unspecified / 3 / 10.99; benefit / unspecified / 5 /
26.00; c'est moi / USD / 1 / 0.00; covergirl / unspecified / 13 / 9.22;
dr. hauschka / unspecified / 1 / 33.00; e.l.f. / unspecified / 3 / 4.99;
green people / USD / 1 / 0.00; l'oreal / unspecified / 7 / 13.15;
lotus cosmetics usa / USD / 1 / 0.00; marcelle / unspecified / 1 / 10.99;
marienatie / USD / 1 / 0.00; maybelline / unspecified / 10 / 10.02;
mineral fusion / unspecified / 1 / 19.00; nyx / USD / 11 / 8.32;
pacifica / unspecified / 2 / 24.50; physicians formula / unspecified / 5 /
15.79; pure anada / unspecified / 1 / 14.00; smashbox / unspecified / 5 /
22.20; suncoat / unspecified / 1 / 16.49; wet n wild / unspecified / 1 / 3.49;
zorah / unspecified / 1 / 27.00; (unknown brand) / unspecified / 2 / 17.00.
Three additional mascara-named products in the source have no price and are
excluded.""",
        hints=(
            "Filter product names with a case-insensitive match for the word "
            "'mascara'; ignore rows without a price.",
            "Left join brands so products without one remain in the results. "
            "Group by brand and currency, then calculate COUNT and AVG. Expect "
            "one row per brand/currency pair rather than one row per product.",
        ),
        points=4,
    ),
    Question(
        question_id="category-price-leaders",
        title="Highest-priced products in each category and currency",
        prompt=(
            "Find the five most expensive products that tie for the highest "
            "price in their category and currency. Include category, currency, "
            "product, brand, and price. Ignore products with no category or "
            "currency."
        ),
        answer_sql="""SELECT c.name AS category, p.currency, p.name AS product,
       b.name AS brand, p.price
FROM products AS p
JOIN categories AS c ON c.id = p.category_id
LEFT JOIN brands AS b ON b.id = p.brand_id
WHERE p.currency IS NOT NULL
  AND p.price = (
      SELECT MAX(peer.price)
      FROM products AS peer
      WHERE peer.category_id = p.category_id
        AND peer.currency = p.currency
  )
ORDER BY p.price DESC, category ASC, product ASC, COALESCE(brand, '') ASC
LIMIT 5;""",
        expected_result="""5 rows, in order: lipstick / GBP / Dior Holiday Couture Collection /
dior / 77.00; palette / GBP / Couture Colour Wardrobe palette / dior / 65.00;
powder / GBP / DIORIFIC PRECIOUS ROCKS - Christmas 2017 Limited Edition /
dior / 40.00; bb_cc / USD / Moisture Surge&trade; CC Cream Hydrating Colour
Corrector Broad Spectrum SPF 30 / clinique / 39.00; contour / USD /
Limited Edition Highlighting Kit / clinique / 39.00.""",
        hints=(
            "For each product, find the maximum price among products in the same "
            "category and currency.",
            "Use a correlated scalar subquery with MAX, then keep products whose "
            "price equals that maximum. Sort the qualifying rows by price "
            "descending and return only the first five.",
        ),
        points=5,
    ),
), key=lambda question: question.points))


def validate_read_query(sql: str) -> str:
    """Accept exactly one PostgreSQL SELECT statement."""
    if not sql or not sql.strip():
        raise ValueError("Enter a SQL query before running it.")

    try:
        statements = parse_sql(sql)
    except ParseError as error:
        raise ValueError(f"SQL syntax error: {error}") from error

    if len(statements) != 1:
        raise ValueError("Run one SELECT query at a time.")
    if not isinstance(statements[0].stmt, SelectStmt):
        raise ValueError("Only SELECT queries are allowed.")

    return sql.strip()


def run_read_query(connection_settings: dict[str, str], sql: str):
    """Run one SELECT in a read-only transaction and return a bounded result."""
    query = validate_read_query(sql)
    connection = psycopg2.connect(
        dbname=connection_settings["POSTGRES_DB"],
        user=connection_settings["POSTGRES_USER"],
        password=connection_settings["POSTGRES_PASSWORD"],
        host=connection_settings["DB_HOST"],
        port=connection_settings["DB_PORT"],
        sslmode=connection_settings["DB_SSLMODE"],
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [description.name for description in cursor.description]
            rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
            truncated = len(rows) > MAX_RESULT_ROWS
            return columns, rows[:MAX_RESULT_ROWS], truncated
    finally:
        connection.rollback()
        connection.close()


def grade_query(connection_settings: dict[str, str], question: Question, sql: str):
    """Run a student's query and compare its ordered result with the answer key."""
    columns, rows, truncated = run_read_query(connection_settings, sql)
    expected_columns, expected_rows, expected_truncated = run_read_query(
        connection_settings, question.answer_sql
    )
    correct = (
        not truncated
        and not expected_truncated
        and len(columns) == len(expected_columns)
        and _normalize_rows(rows) == _normalize_rows(expected_rows)
    )
    return columns, rows, truncated, correct


def _normalize_rows(rows):
    return tuple(
        tuple(_normalize_cell(value) for value in row)
        for row in rows
    )


def _normalize_cell(value):
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value)).normalize()
    return value
