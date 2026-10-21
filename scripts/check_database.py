import os
import sys

import psycopg2


REQUIRED_SETTINGS = (
    "SUPABASE_DB_HOST",
    "SUPABASE_DB_PORT",
    "SUPABASE_DB_NAME",
    "SUPABASE_DB_USER",
    "SUPABASE_DB_PASSWORD",
)


def main() -> int:
    missing = [name for name in REQUIRED_SETTINGS if not os.getenv(name)]
    if missing:
        print("Missing GitHub Actions database secrets: " + ", ".join(missing))
        return 1

    connection = psycopg2.connect(
        dbname=os.environ["SUPABASE_DB_NAME"],
        user=os.environ["SUPABASE_DB_USER"],
        password=os.environ["SUPABASE_DB_PASSWORD"],
        host=os.environ["SUPABASE_DB_HOST"],
        port=os.environ["SUPABASE_DB_PORT"],
        sslmode="require",
        options="-c statement_timeout=5000",
    )
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM public.products),
                    (SELECT COUNT(*) FROM public.brands),
                    (SELECT COUNT(*) FROM public.categories);
                """
            )
            products, brands, categories = cursor.fetchone()
            if products == 0:
                print("Database check failed: public.products has no rows.")
                return 1
            print(
                "Database check passed: "
                f"{products} products, {brands} brands, {categories} categories."
            )
            return 0
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
