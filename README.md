# Makeup SQL Quiz

[![SQL quiz checks](https://github.com/QTTN1/Supabase-SQL-Quiz/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/QTTN1/Supabase-SQL-Quiz/actions/workflows/ci.yml)

Live site: [supabase-makeup-sql-quiz.streamlit.app](https://supabase-makeup-sql-quiz.streamlit.app/)

## About the project

This project is an interactive SQL quiz built to give learners practice writing
queries against a real-world-style product catalog. The quiz contains five
questions worth 20 points total, increasing in difficulty and covering joins,
aggregations, correlated and nested queries, filtering, and currency conversion.

The catalog is based on [`makeup.csv`](./makeup.csv), derived from the [Makeup Dataset on Kaggle](https://www.kaggle.com/datasets/raiusama/makeup-dataset?resource=download).
It includes product details such as brand, category, price, currency, creation
date, and description. The catalog is used for educational SQL practice; prices
and product details reflect the source dataset and are not intended as current
shopping information.

## Taking the quiz

The quiz runs as a Streamlit web application and uses Supabase authentication.
To take it, open the hosted quiz link provided by the repository owner, create
an account or sign in, then choose a question and write a SQL query.

- **Run query** executes a query so you can inspect its results while working.
- **Submit answer** grades the result and updates your score summary.
- Your SQL does not need to match one particular query. A submission is correct
  when its result matches the expected answer.
- After submitting all five questions, the results summary appears with an
  answer key containing one example query for each question.
- Each question has two progressive hints. The expected result is hidden until
  both hints have been viewed and you have submitted a query that runs but
  returns an incorrect result.
- **Save answer** saves your current query to your signed-in account. If you
  change questions with an unsaved query, the app prompts you before switching.

Only one `SELECT` query is allowed per run. Queries execute in a read-only
transaction, with a five-second timeout and a maximum of 200 displayed rows.

## Database structure

The catalog is organized into three related tables:

| Table          | Purpose                                                         | Main fields                                                                                               |
| -------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `brands`     | One row per product brand.                                      | `id`, `name`                                                                                          |
| `categories` | One row per product category.                                   | `id`, `name`                                                                                          |
| `products`   | Product catalog; brand and category are linked by foreign keys. | `id`, `brand_id`, `category_id`, `name`, `price`, `currency`, `created_at`, `description` |

`products.brand_id` references `brands.id`, and `products.category_id`
references `categories.id`. The references may be empty when the source data
does not provide a brand or category.

The application also uses `quiz_answers` to store SQL that a signed-in user
chooses to save. Row-level security restricts saved answers to their owner.
`quiz_activity_log` records successful query runs, submissions, and saves with
the associated user, question, SQL text, and submission result. Row-level
security limits each user to their own log entries, and database permissions
make the log append-only for quiz takers: they cannot update or delete entries.

## Repository guide

- [`makeup.csv`](./makeup.csv) — source product dataset used to build the
  catalog.
- [`init.sql`](./init.sql) — PostgreSQL schema and catalog seed data, plus the
  saved-answer and append-only activity-log tables and their access policies.
- [`app.py`](./app.py) — Streamlit interface for signing in, running and
  submitting queries, viewing results, saving answers, and recording quiz
  activity.
- [`quiz.py`](./quiz.py) — question prompts, hints, expected results, grading
  logic, and read-only query validation/execution.
- [`requirements.txt`](./requirements.txt) — Python packages used by the
  application.
- [`tests/`](./tests/) — automated checks for quiz questions, result grading,
  and query restrictions.

Dataset source: [Makeup Dataset by raiusama on Kaggle](https://www.kaggle.com/datasets/raiusama/makeup-dataset?resource=download).
Refer to the Kaggle listing for its license and source-specific details.

Inspiration: 

This project was inspired by the class [SQL Tutorial with Supabase](https://sql-practice-lab-ids706.vercel.app/),
which demonstrates practicing SQL against a hosted Supabase database.
