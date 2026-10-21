import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pglast.ast import SelectStmt
from pglast import parse_sql

from app import is_answer_unsaved, is_quiz_complete, log_quiz_activity
from quiz import (
    MAX_RESULT_ROWS,
    QUESTIONS,
    Question,
    grade_query,
    run_read_query,
    validate_read_query,
)


class QuizQuestionTests(unittest.TestCase):
    # Confirms question count, point total, and IDs.
    def test_questions_total_twenty_points(self):
        self.assertEqual(len(QUESTIONS), 5)
        self.assertEqual(sum(question.points for question in QUESTIONS), 20)
        self.assertEqual([question.points for question in QUESTIONS], [2, 3, 4, 5, 6])
        self.assertEqual(
            [question.question_id for question in QUESTIONS],
            [
                "nyx-description-search",
                "brand-counts",
                "mascara-price-order",
                "category-price-leaders",
                "currency-normalized-category-averages",
            ],
        )

    # Validates hints and expected results exist.
    def test_each_hint_is_a_single_select(self):
        for question in QUESTIONS:
            with self.subTest(question=question.question_id):
                statements = parse_sql(question.answer_sql)
                self.assertEqual(len(statements), 1)
                self.assertIsInstance(statements[0].stmt, SelectStmt)
                self.assertTrue(question.expected_result.strip())
                self.assertEqual(len(question.hints), 2)

    # Prompts only unsaved, non-empty answers.
    def test_switch_requires_saving_only_when_query_is_unsaved(self):
        self.assertTrue(is_answer_unsaved("SELECT 1", None))
        self.assertFalse(is_answer_unsaved("  ", None))
        self.assertFalse(is_answer_unsaved("SELECT 1", "SELECT 1"))
        self.assertTrue(is_answer_unsaved("SELECT 2", "SELECT 1"))

    # Unlocks answer key only after every submission.
    def test_quiz_completes_only_after_all_questions_are_submitted(self):
        partial_submissions = {
            question.question_id: {}
            for question in QUESTIONS[:-1]
        }
        complete_submissions = {
            question.question_id: {}
            for question in QUESTIONS
        }

        self.assertFalse(is_quiz_complete(partial_submissions))
        self.assertTrue(is_quiz_complete(complete_submissions))

    # Saves submission details to the activity log.
    def test_activity_log_records_submit_without_exposing_other_fields(self):
        client = Mock()

        log_quiz_activity(
            client,
            user_id="user-id",
            question_id="brand-counts",
            action="submit",
            query="SELECT 1",
            result_correct=True,
        )

        client.table.assert_called_once_with("quiz_activity_log")
        client.table.return_value.insert.assert_called_once_with(
            {
                "user_id": "user-id",
                "question_id": "brand-counts",
                "action": "submit",
                "submitted_sql": "SELECT 1",
                "result_correct": True,
            }
        )
        client.table.return_value.insert.return_value.execute.assert_called_once()

    # Accepts alternate SQL with matching results.
    @patch("quiz.run_read_query")
    def test_grades_matching_query_results(self, run_query):
        run_query.side_effect = [
            (["brand", "count"], [("nyx", 2)], False),
            (["brand", "product_count"], [("nyx", 2)], False),
        ]
        question = Question(
            question_id="test",
            title="Test",
            prompt="Test",
            answer_sql="SELECT 'nyx', 2",
            expected_result="nyx, 2",
            hints=("Hint one", "Hint two"),
        )

        columns, rows, truncated, correct = grade_query(
            {}, question, "SELECT 'nyx' AS brand, 2 AS count"
        )

        self.assertEqual(columns, ["brand", "count"])
        self.assertEqual(rows, [("nyx", 2)])
        self.assertFalse(truncated)
        self.assertTrue(correct)

    # Rejects queries with different result rows.
    @patch("quiz.run_read_query")
    def test_grades_different_query_results_as_incorrect(self, run_query):
        run_query.side_effect = [
            (["brand", "count"], [("nyx", 1)], False),
            (["brand", "count"], [("nyx", 2)], False),
        ]
        question = Question(
            question_id="test",
            title="Test",
            prompt="Test",
            answer_sql="SELECT 'nyx', 2",
            expected_result="nyx, 2",
            hints=("Hint one", "Hint two"),
        )

        _, _, _, correct = grade_query({}, question, "SELECT 'nyx', 1")

        self.assertFalse(correct)


class QueryValidationTests(unittest.TestCase):
    # Allows SELECT and WITH SELECT queries.
    def test_accepts_select_and_with_select(self):
        self.assertEqual(validate_read_query(" SELECT 1; "), "SELECT 1;")
        self.assertTrue(
            validate_read_query("WITH items AS (SELECT 1) SELECT * FROM items")
        )

    # Rejects queries containing only whitespace.
    def test_rejects_empty_query(self):
        with self.assertRaisesRegex(ValueError, "Enter a SQL query"):
            validate_read_query("  ")

    # Blocks SQL statements that modify data.
    def test_rejects_write_statements(self):
        for sql in ("INSERT INTO products (id, name) VALUES (1, 'x')", "DELETE FROM products"):
            with self.subTest(sql=sql):
                with self.assertRaisesRegex(ValueError, "Only SELECT"):
                    validate_read_query(sql)

    # Allows only one statement per query.
    def test_rejects_multiple_statements(self):
        with self.assertRaisesRegex(ValueError, "one SELECT"):
            validate_read_query("SELECT 1; SELECT 2;")

    # Reports malformed SQL as a validation error.
    def test_rejects_invalid_sql(self):
        with self.assertRaisesRegex(ValueError, "SQL syntax error"):
            validate_read_query("SELECT FROM")

    # Enforces read-only execution and row limits.
    @patch("quiz.psycopg2.connect")
    def test_runs_read_only_and_limits_result_rows(self, connect):
        connection = connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [SimpleNamespace(name="answer")]
        cursor.fetchmany.return_value = [(value,) for value in range(MAX_RESULT_ROWS + 1)]
        settings = {
            "POSTGRES_DB": "postgres",
            "POSTGRES_USER": "quiz_reader",
            "POSTGRES_PASSWORD": "not-a-real-password",
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_SSLMODE": "require",
        }

        columns, rows, truncated = run_read_query(settings, "SELECT 1 AS answer")

        connection.set_session.assert_called_once_with(readonly=True)
        cursor.fetchmany.assert_called_once_with(MAX_RESULT_ROWS + 1)
        self.assertEqual(columns, ["answer"])
        self.assertEqual(len(rows), MAX_RESULT_ROWS)
        self.assertTrue(truncated)
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
