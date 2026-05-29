from __future__ import annotations

from ambient_ai.outcomes import Outcome, append_outcome, read_outcomes


class TestAppendOutcome:
    def test_append_and_read_roundtrip(self, paths):
        append_outcome(paths, Outcome(decision="done", summary="drafted note", agent="hermes"))
        records = read_outcomes(paths)
        assert len(records) == 1
        assert records[0]["decision"] == "done"
        assert records[0]["summary"] == "drafted note"
        assert records[0]["agent"] == "hermes"
        assert records[0]["recorded_at"]  # auto-stamped

    def test_most_recent_first(self, paths):
        append_outcome(paths, Outcome(decision="no_action", summary="first"))
        append_outcome(paths, Outcome(decision="done", summary="second"))
        records = read_outcomes(paths)
        assert [r["summary"] for r in records] == ["second", "first"]

    def test_limit(self, paths):
        for i in range(5):
            append_outcome(paths, Outcome(decision="no_action", summary=f"n{i}"))
        assert len(read_outcomes(paths, limit=2)) == 2

    def test_evidence_and_event_ids_preserved(self, paths):
        append_outcome(
            paths,
            Outcome(
                decision="blocked",
                summary="needs approval",
                evidence=["https://example.com"],
                event_ids=[1, 2, 3],
            ),
        )
        record = read_outcomes(paths)[0]
        assert record["evidence"] == ["https://example.com"]
        assert record["event_ids"] == [1, 2, 3]

    def test_read_missing_log_returns_empty(self, paths):
        assert read_outcomes(paths) == []

    def test_malformed_lines_skipped(self, paths):
        log = paths.learning_dir / "trigger-outcomes.jsonl"
        append_outcome(paths, Outcome(decision="done", summary="valid"))
        with log.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        records = read_outcomes(paths)
        assert len(records) == 1
        assert records[0]["summary"] == "valid"
