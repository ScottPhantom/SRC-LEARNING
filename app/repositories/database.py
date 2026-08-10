from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.models import AppSettings, Question, QuestionErrorStat


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """SQLite gateway. Each public write is atomic and thread-safe."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );
        INSERT INTO schema_version(version)
        SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            category TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            last_seen_at TEXT NOT NULL,
            UNIQUE(subject, relative_path)
        );
        CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject, active);

        CREATE TABLE IF NOT EXISTS card_progress (
            question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK(state IN ('new', 'known', 'learning')),
            review_count INTEGER NOT NULL DEFAULT 0,
            last_reviewed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS question_error_stats (
            question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
            total_attempts INTEGER NOT NULL DEFAULT 0 CHECK(total_attempts >= 0),
            wrong_count INTEGER NOT NULL DEFAULT 0 CHECK(wrong_count >= 0),
            updated_at TEXT NOT NULL,
            CHECK(wrong_count <= total_attempts)
        );

        CREATE TABLE IF NOT EXISTS flash_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
            current_position INTEGER NOT NULL DEFAULT 0,
            only_learning INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_flash_per_subject
            ON flash_sessions(subject) WHERE status = 'active';
        CREATE TABLE IF NOT EXISTS flash_session_items (
            session_id INTEGER NOT NULL REFERENCES flash_sessions(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            question_id TEXT NOT NULL REFERENCES questions(id),
            PRIMARY KEY(session_id, position)
        );

        CREATE TABLE IF NOT EXISTS cram_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            seed INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
            current_round INTEGER NOT NULL DEFAULT 1,
            total_rounds INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            grading_mode TEXT NOT NULL DEFAULT 'self_assessment'
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_cram_per_subject
            ON cram_cycles(subject) WHERE status = 'active';
        CREATE TABLE IF NOT EXISTS cram_items (
            cycle_id INTEGER NOT NULL REFERENCES cram_cycles(id) ON DELETE CASCADE,
            round_number INTEGER NOT NULL,
            initial_order INTEGER NOT NULL,
            queue_rank INTEGER NOT NULL,
            question_id TEXT NOT NULL REFERENCES questions(id),
            mastered INTEGER NOT NULL DEFAULT 0,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(cycle_id, question_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cram_queue
            ON cram_items(cycle_id, round_number, mastered, queue_rank);

        CREATE TABLE IF NOT EXISTS exam_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            config_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            submit_reason TEXT NOT NULL,
            total INTEGER NOT NULL,
            correct INTEGER NOT NULL,
            unanswered INTEGER NOT NULL,
            score_percent REAL NOT NULL,
            score REAL NOT NULL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS exam_answers (
            attempt_id INTEGER NOT NULL REFERENCES exam_attempts(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            selected_answer TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            is_correct INTEGER NOT NULL,
            awarded_score REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY(attempt_id, position)
        );
        """
        with self.transaction() as connection:
            connection.executescript(schema)
            attempt_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(exam_attempts)")
            }
            if "score" not in attempt_columns:
                connection.execute(
                    "ALTER TABLE exam_attempts ADD COLUMN score REAL NOT NULL DEFAULT 0.0"
                )
                connection.execute(
                    "UPDATE exam_attempts SET score=ROUND(score_percent / 10.0, 2)"
                )
            answer_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(exam_answers)")
            }
            if "awarded_score" not in answer_columns:
                connection.execute(
                    "ALTER TABLE exam_answers ADD COLUMN awarded_score REAL NOT NULL DEFAULT 0.0"
                )
                connection.execute(
                    """UPDATE exam_answers SET awarded_score=ROUND(
                    CASE WHEN is_correct=1 THEN 10.0 / COALESCE(
                        (SELECT total FROM exam_attempts
                         WHERE exam_attempts.id=exam_answers.attempt_id), 1
                    ) ELSE 0.0 END, 2)"""
                )
            cram_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(cram_cycles)")
            }
            if "grading_mode" not in cram_columns:
                connection.execute(
                    "ALTER TABLE cram_cycles ADD COLUMN grading_mode TEXT NOT NULL "
                    "DEFAULT 'self_assessment'"
                )
            connection.execute("UPDATE schema_version SET version=4 WHERE version < 4")

    def sync_questions(
        self, questions: Sequence[Question], subject_names: Sequence[str] | None = None
    ) -> None:
        now = utc_now()
        with self.transaction() as connection:
            # Scanner passes the complete catalog, therefore a missing path is
            # inactive but its historical progress is intentionally retained.
            connection.execute("UPDATE questions SET active = 0")
            connection.executemany(
                """
                INSERT INTO questions(id, subject, category, relative_path, active, last_seen_at)
                VALUES(?, ?, ?, ?, 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    subject=excluded.subject, category=excluded.category,
                    relative_path=excluded.relative_path, active=1,
                    last_seen_at=excluded.last_seen_at
                """,
                [
                    (
                        question.id,
                        question.subject,
                        question.category,
                        question.relative_path,
                        now,
                    )
                    for question in questions
                ],
            )

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO app_settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, str(value)),
            )

    def load_app_settings(self, default_data_dir: Path) -> AppSettings:
        def as_float(key: str, default: float) -> float:
            try:
                return float(self.get_setting(key, str(default)))
            except ValueError:
                return default

        return AppSettings(
            theme=self.get_setting("theme", "system"),
            data_dir=self.get_setting("data_dir", str(default_data_dir)),
            mask_x=as_float("mask_x", 0.0),
            mask_y=as_float("mask_y", 0.90),
            mask_width=as_float("mask_width", 0.25),
            mask_height=as_float("mask_height", 0.10),
        )

    def save_app_settings(self, settings: AppSettings) -> None:
        values = {
            "theme": settings.theme,
            "data_dir": settings.data_dir,
            "mask_x": settings.mask_x,
            "mask_y": settings.mask_y,
            "mask_width": settings.mask_width,
            "mask_height": settings.mask_height,
        }
        with self.transaction() as connection:
            connection.executemany(
                """INSERT INTO app_settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                [(key, str(value)) for key, value in values.items()],
            )

    # Flashcard ---------------------------------------------------------
    def active_flash_session(self, subject: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM flash_sessions WHERE subject=? AND status='active'", (subject,)
        ).fetchone()

    def create_flash_session(
        self, subject: str, question_ids: Sequence[str], only_learning: bool = False
    ) -> int:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE flash_sessions SET status='completed', updated_at=? "
                "WHERE subject=? AND status='active'",
                (now, subject),
            )
            cursor = connection.execute(
                """INSERT INTO flash_sessions
                (subject,status,current_position,only_learning,created_at,updated_at)
                VALUES(?, 'active', 0, ?, ?, ?)""",
                (subject, int(only_learning), now, now),
            )
            session_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO flash_session_items(session_id,position,question_id) VALUES(?,?,?)",
                [(session_id, index, qid) for index, qid in enumerate(question_ids)],
            )
            return session_id

    def delete_active_flash_session(self, subject: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM flash_sessions WHERE subject=? AND status='active'",
                (subject,),
            )

    def flash_question_ids(self, session_id: int) -> list[str]:
        rows = self._connection.execute(
            "SELECT question_id FROM flash_session_items WHERE session_id=? ORDER BY position",
            (session_id,),
        ).fetchall()
        return [str(row["question_id"]) for row in rows]

    def update_flash_position(self, session_id: int, position: int, complete: bool) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE flash_sessions SET current_position=?, status=?, updated_at=? WHERE id=?",
                (position, "completed" if complete else "active", utc_now(), session_id),
            )

    def rate_card(self, question_id: str, known: bool) -> None:
        state = "known" if known else "learning"
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO card_progress(question_id,state,review_count,last_reviewed_at)
                VALUES(?,?,1,?) ON CONFLICT(question_id) DO UPDATE SET
                state=excluded.state, review_count=card_progress.review_count+1,
                last_reviewed_at=excluded.last_reviewed_at""",
                (question_id, state, utc_now()),
            )

    def learning_question_ids(self, subject: str) -> list[str]:
        rows = self._connection.execute(
            """SELECT p.question_id FROM card_progress p JOIN questions q ON q.id=p.question_id
            WHERE q.subject=? AND q.active=1 AND p.state='learning'""",
            (subject,),
        ).fetchall()
        return [str(row["question_id"]) for row in rows]

    def card_stats(self, subject: str) -> dict[str, int]:
        result = {"new": 0, "known": 0, "learning": 0}
        rows = self._connection.execute(
            """SELECT COALESCE(p.state,'new') state, COUNT(*) amount
            FROM questions q LEFT JOIN card_progress p ON p.question_id=q.id
            WHERE q.subject=? AND q.active=1 GROUP BY COALESCE(p.state,'new')""",
            (subject,),
        ).fetchall()
        for row in rows:
            result[str(row["state"])] = int(row["amount"])
        return result

    # Adaptive learning ------------------------------------------------
    @staticmethod
    def _record_question_attempt(
        connection: sqlite3.Connection, question_id: str, correct: bool
    ) -> None:
        connection.execute(
            """INSERT INTO question_error_stats
            (question_id,total_attempts,wrong_count,updated_at)
            VALUES(?,1,?,?)
            ON CONFLICT(question_id) DO UPDATE SET
                total_attempts=question_error_stats.total_attempts+1,
                wrong_count=question_error_stats.wrong_count+excluded.wrong_count,
                updated_at=excluded.updated_at""",
            (question_id, int(not correct), utc_now()),
        )

    def record_question_attempt(self, question_id: str, correct: bool) -> None:
        with self.transaction() as connection:
            self._record_question_attempt(connection, question_id, correct)

    def question_error_stats(
        self, question_ids: Sequence[str]
    ) -> dict[str, QuestionErrorStat]:
        ids = list(dict.fromkeys(question_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._connection.execute(
            f"""SELECT q.id question_id,
            COALESCE(s.total_attempts,0) total_attempts,
            COALESCE(s.wrong_count,0) wrong_count,
            COALESCE(p.state,'new') card_state
            FROM questions q
            LEFT JOIN question_error_stats s ON s.question_id=q.id
            LEFT JOIN card_progress p ON p.question_id=q.id
            WHERE q.id IN ({placeholders})""",
            ids,
        ).fetchall()
        return {
            str(row["question_id"]): QuestionErrorStat(
                question_id=str(row["question_id"]),
                total_attempts=int(row["total_attempts"]),
                wrong_count=int(row["wrong_count"]),
                card_state=str(row["card_state"]),
            )
            for row in rows
        }

    def question_exam_exposure_counts(
        self, question_ids: Sequence[str]
    ) -> dict[str, int]:
        """Return how often each question appeared in a submitted Mock Exam.

        Exposure is derived from ``exam_answers`` so deleting an exam also removes
        its contribution. Questions that have never appeared are returned with 0.
        """
        ids = list(dict.fromkeys(question_ids))
        counts = {question_id: 0 for question_id in ids}
        # Keep below SQLite's common 999-variable limit for large subjects.
        for offset in range(0, len(ids), 900):
            chunk = ids[offset : offset + 900]
            placeholders = ",".join("?" for _ in chunk)
            rows = self._connection.execute(
                f"""SELECT question_id, COUNT(*) appearances
                FROM exam_answers
                WHERE question_id IN ({placeholders})
                GROUP BY question_id""",
                chunk,
            ).fetchall()
            for row in rows:
                counts[str(row["question_id"])] = int(row["appearances"])
        return counts

    # Cramming ----------------------------------------------------------
    def active_cram_cycle(self, subject: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM cram_cycles WHERE subject=? AND status='active'", (subject,)
        ).fetchone()

    def latest_cram_cycle(self, subject: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM cram_cycles WHERE subject=? ORDER BY id DESC LIMIT 1", (subject,)
        ).fetchone()

    def cram_cycle_question_ids(self, cycle_id: int) -> list[str]:
        rows = self._connection.execute(
            "SELECT question_id FROM cram_items WHERE cycle_id=? ORDER BY initial_order",
            (cycle_id,),
        ).fetchall()
        return [str(row["question_id"]) for row in rows]

    def create_cram_cycle(
        self,
        subject: str,
        seed: int,
        rounds: Sequence[Sequence[str]],
        grading_mode: str = "self_assessment",
    ) -> int:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE cram_cycles SET status='completed', completed_at=?, updated_at=? "
                "WHERE subject=? AND status='active'",
                (now, now, subject),
            )
            cursor = connection.execute(
                """INSERT INTO cram_cycles
                (subject,seed,status,current_round,total_rounds,created_at,updated_at,
                 grading_mode) VALUES(?,?,'active',1,?,?,?,?)""",
                (subject, seed, len(rounds), now, now, grading_mode),
            )
            cycle_id = int(cursor.lastrowid)
            records: list[tuple[int, int, int, int, str]] = []
            for round_index, question_ids in enumerate(rounds, start=1):
                for position, question_id in enumerate(question_ids):
                    records.append(
                        (cycle_id, round_index, position, position, question_id)
                    )
            connection.executemany(
                """INSERT INTO cram_items
                (cycle_id,round_number,initial_order,queue_rank,question_id)
                VALUES(?,?,?,?,?)""",
                records,
            )
            return cycle_id

    def cram_current_item(self, cycle_id: int) -> sqlite3.Row | None:
        cycle = self._connection.execute(
            "SELECT current_round,status FROM cram_cycles WHERE id=?", (cycle_id,)
        ).fetchone()
        if not cycle or cycle["status"] != "active":
            return None
        return self._connection.execute(
            """SELECT * FROM cram_items WHERE cycle_id=? AND round_number=? AND mastered=0
            ORDER BY queue_rank LIMIT 1""",
            (cycle_id, int(cycle["current_round"])),
        ).fetchone()

    def cram_round_items(self, cycle_id: int) -> list[sqlite3.Row]:
        cycle = self._connection.execute(
            "SELECT current_round FROM cram_cycles WHERE id=?", (cycle_id,)
        ).fetchone()
        if not cycle:
            return []
        return list(
            self._connection.execute(
                """SELECT * FROM cram_items WHERE cycle_id=? AND round_number=?
                ORDER BY initial_order""",
                (cycle_id, int(cycle["current_round"])),
            ).fetchall()
        )

    def focus_cram_item(self, cycle_id: int, question_id: str) -> None:
        """Đưa một câu chưa thuộc trong vòng hiện tại lên đầu queue."""
        with self.transaction() as connection:
            cycle = connection.execute(
                "SELECT * FROM cram_cycles WHERE id=? AND status='active'", (cycle_id,)
            ).fetchone()
            if not cycle:
                raise ValueError("Chu kỳ không còn hoạt động")
            current_round = int(cycle["current_round"])
            item = connection.execute(
                """SELECT * FROM cram_items WHERE cycle_id=? AND round_number=?
                AND question_id=? AND mastered=0""",
                (cycle_id, current_round, question_id),
            ).fetchone()
            if not item:
                raise ValueError("Câu hỏi không còn trong queue của vòng hiện tại")
            minimum = connection.execute(
                """SELECT COALESCE(MIN(queue_rank),0) value FROM cram_items
                WHERE cycle_id=? AND round_number=? AND mastered=0""",
                (cycle_id, current_round),
            ).fetchone()["value"]
            connection.execute(
                """UPDATE cram_items SET queue_rank=?
                WHERE cycle_id=? AND question_id=?""",
                (int(minimum) - 1, cycle_id, question_id),
            )
            connection.execute(
                "UPDATE cram_cycles SET updated_at=? WHERE id=?", (utc_now(), cycle_id)
            )

    def rate_cram_item(self, cycle_id: int, question_id: str, correct: bool) -> dict[str, Any]:
        with self.transaction() as connection:
            cycle = connection.execute(
                "SELECT * FROM cram_cycles WHERE id=? AND status='active'", (cycle_id,)
            ).fetchone()
            if not cycle:
                raise ValueError("Chu kỳ không còn hoạt động")
            current_round = int(cycle["current_round"])
            current = connection.execute(
                """SELECT * FROM cram_items WHERE cycle_id=? AND round_number=?
                AND mastered=0 ORDER BY queue_rank LIMIT 1""",
                (cycle_id, current_round),
            ).fetchone()
            if not current or current["question_id"] != question_id:
                raise ValueError("Câu được đánh giá không phải đầu hàng đợi")
            self._record_question_attempt(connection, question_id, correct)
            if correct:
                connection.execute(
                    "UPDATE cram_items SET mastered=1 WHERE cycle_id=? AND question_id=?",
                    (cycle_id, question_id),
                )
            else:
                maximum = connection.execute(
                    """SELECT COALESCE(MAX(queue_rank),0) value FROM cram_items
                    WHERE cycle_id=? AND round_number=?""",
                    (cycle_id, current_round),
                ).fetchone()["value"]
                connection.execute(
                    """UPDATE cram_items SET queue_rank=?, wrong_count=wrong_count+1
                    WHERE cycle_id=? AND question_id=?""",
                    (int(maximum) + 1, cycle_id, question_id),
                )

            remaining = int(
                connection.execute(
                    """SELECT COUNT(*) amount FROM cram_items WHERE cycle_id=?
                    AND round_number=? AND mastered=0""",
                    (cycle_id, current_round),
                ).fetchone()["amount"]
            )
            completed = False
            if remaining == 0:
                if current_round >= int(cycle["total_rounds"]):
                    completed = True
                    now = utc_now()
                    connection.execute(
                        """UPDATE cram_cycles SET status='completed',completed_at=?,updated_at=?
                        WHERE id=?""",
                        (now, now, cycle_id),
                    )
                else:
                    current_round += 1
                    connection.execute(
                        "UPDATE cram_cycles SET current_round=?,updated_at=? WHERE id=?",
                        (current_round, utc_now(), cycle_id),
                    )
            else:
                connection.execute(
                    "UPDATE cram_cycles SET updated_at=? WHERE id=?", (utc_now(), cycle_id)
                )
            return {
                "completed": completed,
                "current_round": current_round,
                "remaining": remaining,
            }

    def cram_stats(self, cycle_id: int) -> dict[str, int | str]:
        cycle = self._connection.execute(
            "SELECT * FROM cram_cycles WHERE id=?", (cycle_id,)
        ).fetchone()
        if not cycle:
            return {}
        item = self._connection.execute(
            """SELECT COUNT(*) total,
            SUM(CASE WHEN mastered=0 AND round_number=? THEN 1 ELSE 0 END) remaining,
            SUM(CASE WHEN round_number=? THEN 1 ELSE 0 END) round_total,
            SUM(CASE WHEN round_number=? AND mastered=1 THEN 1 ELSE 0 END) round_mastered,
            SUM(mastered) mastered, SUM(wrong_count) wrong
            FROM cram_items WHERE cycle_id=?""",
            (
                int(cycle["current_round"]),
                int(cycle["current_round"]),
                int(cycle["current_round"]),
                cycle_id,
            ),
        ).fetchone()
        return {
            "status": str(cycle["status"]),
            "current_round": int(cycle["current_round"]),
            "total_rounds": int(cycle["total_rounds"]),
            "remaining": int(item["remaining"] or 0),
            "round_total": int(item["round_total"] or 0),
            "round_mastered": int(item["round_mastered"] or 0),
            "mastered": int(item["mastered"] or 0),
            "wrong": int(item["wrong"] or 0),
            "total": int(item["total"] or 0),
        }

    # Exams -------------------------------------------------------------
    def save_exam_attempt(
        self,
        *,
        subject: str,
        config: dict[str, Any],
        started_at: str,
        submit_reason: str,
        score: float,
        answers: Sequence[dict[str, Any]],
    ) -> int:
        total = len(answers)
        correct = sum(bool(item["is_correct"]) for item in answers)
        unanswered = sum(not item["selected_answer"] for item in answers)
        rounded_score = round(float(score), 2)
        score_percent = round(rounded_score * 10.0, 2)
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO exam_attempts
                (subject,config_json,started_at,submitted_at,submit_reason,total,correct,
                 unanswered,score_percent,score) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    subject,
                    json.dumps(config, ensure_ascii=False),
                    started_at,
                    utc_now(),
                    submit_reason,
                    total,
                    correct,
                    unanswered,
                    score_percent,
                    rounded_score,
                ),
            )
            attempt_id = int(cursor.lastrowid)
            connection.executemany(
                """INSERT INTO exam_answers
                (attempt_id,position,question_id,relative_path,selected_answer,
                 correct_answer,is_correct,awarded_score) VALUES(?,?,?,?,?,?,?,?)""",
                [
                    (
                        attempt_id,
                        index,
                        item["question_id"],
                        item["relative_path"],
                        item["selected_answer"],
                        item["correct_answer"],
                        int(item["is_correct"]),
                        round(float(item["awarded_score"]), 2),
                    )
                    for index, item in enumerate(answers)
                ],
            )
            for item in answers:
                if item["selected_answer"]:
                    self._record_question_attempt(
                        connection,
                        str(item["question_id"]),
                        bool(item["is_correct"]),
                    )
            return attempt_id

    def exam_history(self, subject: str | None = None) -> list[sqlite3.Row]:
        if subject:
            return list(
                self._connection.execute(
                    "SELECT * FROM exam_attempts WHERE subject=? ORDER BY id DESC", (subject,)
                ).fetchall()
            )
        return list(
            self._connection.execute("SELECT * FROM exam_attempts ORDER BY id DESC").fetchall()
        )

    def exam_detail(self, attempt_id: int) -> list[sqlite3.Row]:
        return list(
            self._connection.execute(
                "SELECT * FROM exam_answers WHERE attempt_id=? ORDER BY position",
                (attempt_id,),
            ).fetchall()
        )

    def delete_exam_attempts(self, attempt_ids: Sequence[int]) -> int:
        """Xóa nhiều bài thi trong một transaction; chi tiết cascade theo FK."""
        normalized_ids = sorted({int(attempt_id) for attempt_id in attempt_ids})
        if not normalized_ids:
            return 0
        placeholders = ",".join("?" for _ in normalized_ids)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"DELETE FROM exam_attempts WHERE id IN ({placeholders})",
                normalized_ids,
            )
            return max(0, int(cursor.rowcount))
