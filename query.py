import os

import psycopg2
from dotenv import load_dotenv
from psycopg2 import errors

load_dotenv()

DB_NAME = os.getenv("POSTGRES_DB", "postgres")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_SSLMODE = os.getenv("DB_SSLMODE", "prefer")


def main():
    print(f"Connecting to {DB_NAME} at {DB_HOST}:{DB_PORT} as {DB_USER} ...")
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        sslmode=DB_SSLMODE,
    )
    cur = conn.cursor()

    try:
        print("\nMost expensive products:")
        cur.execute(
            """
            SELECT products.name, brands.name, products.price, products.currency
            FROM products
            LEFT JOIN brands ON brands.id = products.brand_id
            WHERE products.price IS NOT NULL
            ORDER BY products.price DESC, products.name ASC
            LIMIT 10;
            """
        )
        for row in cur.fetchall():
            print(row)

        try:
            # Keep the demo's temporary product ID unique if multiple clients write.
            cur.execute("LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE;")

            print("\nInserting a temporary product...")
            cur.execute(
                """
                INSERT INTO products (
                    id, name, price, currency, created_at, description
                )
                SELECT COALESCE(MAX(id), 0) + 1, %s, %s, %s, now(), %s
                FROM products
                RETURNING id, name;
                """,
                (
                    "SQL Demo Test Product",
                    1.00,
                    "USD",
                    "Temporary product used to demonstrate parameterized CRUD.",
                ),
            )
            product_id, product_name = cur.fetchone()
            print("Inserted:", product_id, product_name)

            print("\nUpdating the temporary product...")
            cur.execute(
                """
                UPDATE products
                SET price = %s
                WHERE id = %s
                RETURNING id, name, price;
                """,
                (2.00, product_id),
            )
            print("Updated:", cur.fetchone())

            print("\nDeleting the temporary product...")
            cur.execute(
                """
                DELETE FROM products
                WHERE id = %s
                RETURNING id, name;
                """,
                (product_id,),
            )
            print("Deleted:", cur.fetchone())

            conn.commit()
            print("\nChanges committed. The temporary product was removed.")
        except errors.InsufficientPrivilege as error:
            conn.rollback()
            print("\nWrite blocked by the database:", str(error).strip().splitlines()[0])
            print("The connection cannot write to products; no changes were committed.")
        except Exception:
            conn.rollback()
            raise
    finally:
        cur.close()
        conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()