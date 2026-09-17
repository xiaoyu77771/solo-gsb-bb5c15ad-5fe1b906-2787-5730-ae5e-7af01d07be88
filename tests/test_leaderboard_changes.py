"""Tests for GET /leaderboard/changes: rank/total diffs between revisions."""

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient backed by an isolated SQLite file."""
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "changes-test.db"))
    db_module.init_db()
    return TestClient(app)


def _post(client, event_id, participant_id, points, correction_of=None):
    payload = {
        "event_id": event_id,
        "participant_id": participant_id,
        "points": points,
    }
    if correction_of is not None:
        payload["correction_of"] = correction_of
    r = client.post("/events", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["revision"]


def _changes(client, from_revision, to_revision, **extra):
    return client.get(
        "/leaderboard/changes",
        params={"from_revision": from_revision, "to_revision": to_revision, **extra},
    )


def test_missing_params_422(client):
    assert client.get("/leaderboard/changes").status_code == 422
    assert client.get("/leaderboard/changes", params={"from_revision": 0}).status_code == 422
    assert client.get("/leaderboard/changes", params={"to_revision": 1}).status_code == 422
    assert _changes(client, "x", 1).status_code == 422
    assert _changes(client, 0, "1.5").status_code == 422


@pytest.mark.parametrize("frm,to", [(0, 0), (2, 2), (3, 1), (1, 0), (-1, 1), (0, -1)])
def test_invalid_ordering_422(client, frm, to):
    _post(client, "e1", "alice", 10)
    r = _changes(client, frm, to)
    assert r.status_code == 422, (frm, to, r.status_code)


def test_beyond_current_revision_404(client):
    # empty board: even to_revision=1 does not exist yet
    assert _changes(client, 0, 1).status_code == 404
    _post(client, "e1", "alice", 10)
    assert _changes(client, 0, 2).status_code == 404
    assert _changes(client, 1, 2).status_code == 404
    # ordering is validated first: from > to stays 422 even when out of range
    assert _changes(client, 5, 4).status_code == 422


def test_from_empty_board_lists_all_entries(client):
    rev = 0
    rev = _post(client, "e1", "alice", 10)
    rev = _post(client, "e2", "bob", 7)

    r = _changes(client, 0, rev)
    assert r.status_code == 200
    assert r.json() == {
        "from_revision": 0,
        "to_revision": rev,
        "changes": [
            {
                "participant_id": "alice",
                "before": None,
                "after": {"rank": 1, "total_points": 10},
                "points_delta": 10,
            },
            {
                "participant_id": "bob",
                "before": None,
                "after": {"rank": 2, "total_points": 7},
                "points_delta": 7,
            },
        ],
    }


def test_points_and_rank_changes_only(client):
    _post(client, "e1", "alice", 10)
    _post(client, "e2", "bob", 8)
    rev3 = _post(client, "e3", "carol", 5)
    # carol (9) overtakes bob but stays behind alice, whose rank/total don't move
    rev4 = _post(client, "e4", "carol", 4)

    r = _changes(client, rev3, rev4)
    assert r.status_code == 200
    assert [c["participant_id"] for c in r.json()["changes"]] == ["bob", "carol"]
    by_id = {c["participant_id"]: c for c in r.json()["changes"]}
    assert by_id["bob"] == {
        "participant_id": "bob",
        "before": {"rank": 2, "total_points": 8},
        "after": {"rank": 3, "total_points": 8},
        "points_delta": 0,  # rank moved even though points did not
    }
    assert by_id["carol"] == {
        "participant_id": "carol",
        "before": {"rank": 3, "total_points": 5},
        "after": {"rank": 2, "total_points": 9},
        "points_delta": 4,
    }


def test_results_sorted_by_participant_id(client):
    rev = 0
    for pid, pts in [("zoe", 1), ("amy", 2), ("mike", 3)]:
        rev = _post(client, f"e-{pid}", pid, pts)
    body = _changes(client, 0, rev).json()
    assert [c["participant_id"] for c in body["changes"]] == ["amy", "mike", "zoe"]


def test_correction_redirecting_participant_shows_exit_and_entry(client):
    rev1 = _post(client, "e1", "alice", 10)
    _post(client, "e2", "carol", 5)
    # correction moves the 10 points from alice to bob
    rev3 = _post(client, "e3", "bob", 10, correction_of="e1")

    r = _changes(client, rev1, rev3)
    assert r.status_code == 200
    by_id = {c["participant_id"]: c for c in r.json()["changes"]}
    assert by_id["alice"] == {
        "participant_id": "alice",
        "before": {"rank": 1, "total_points": 10},
        "after": None,  # alice leaves the board
        "points_delta": -10,
    }
    assert by_id["bob"] == {
        "participant_id": "bob",
        "before": None,  # bob enters the board
        "after": {"rank": 1, "total_points": 10},
        "points_delta": 10,
    }
    assert by_id["carol"] == {
        "participant_id": "carol",
        "before": None,
        "after": {"rank": 2, "total_points": 5},
        "points_delta": 5,
    }
    assert [c["participant_id"] for c in r.json()["changes"]] == [
        "alice",
        "bob",
        "carol",
    ]

    # snapshots themselves reflect the same effective-event rule
    assert _changes(client, 1, rev3).json()["changes"] == r.json()["changes"]


def test_correction_chain_tip_effective_at_each_snapshot(client):
    rev1 = _post(client, "e1", "alice", 10)
    rev2 = _post(client, "e2", "alice", 12, correction_of="e1")
    rev3 = _post(client, "e3", "alice", 15, correction_of="e2")

    body = _changes(client, rev1, rev3).json()
    assert body["changes"] == [
        {
            "participant_id": "alice",
            "before": {"rank": 1, "total_points": 10},
            "after": {"rank": 1, "total_points": 15},
            "points_delta": 5,
        }
    ]

    mid = _changes(client, rev1, rev2).json()
    assert mid["changes"][0]["before"] == {"rank": 1, "total_points": 10}
    assert mid["changes"][0]["after"] == {"rank": 1, "total_points": 12}
    assert mid["changes"][0]["points_delta"] == 2


def test_no_change_when_totals_and_ranks_identical(client):
    # a correction with the same points/participant swaps the effective
    # event but leaves the board unchanged -> empty diff
    rev1 = _post(client, "e1", "alice", 10)
    rev2 = _post(client, "e2", "alice", 10, correction_of="e1")
    body = _changes(client, rev1, rev2).json()
    assert body == {"from_revision": rev1, "to_revision": rev2, "changes": []}


def test_to_current_revision_allowed(client):
    rev = _post(client, "e1", "alice", 10)
    r = _changes(client, 0, rev)
    assert r.status_code == 200
    assert r.json()["to_revision"] == rev
