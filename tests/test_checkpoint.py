import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.checkpoint import clear_checkpoint, load_checkpoint, save_checkpoint


def test_load_checkpoint_returns_none_when_no_file_exists(tmp_path):
    assert load_checkpoint(tmp_path / "missing.json") is None


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "checkpoint.json"
    save_checkpoint(path, {"scraped_at": "2026-08-14T00:00:00Z", "last_completed_page": 177})

    assert load_checkpoint(path) == {
        "scraped_at": "2026-08-14T00:00:00Z",
        "last_completed_page": 177,
    }


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "checkpoint.json"
    save_checkpoint(path, {"last_completed_page": 1})

    assert path.exists()


def test_clear_checkpoint_removes_file(tmp_path):
    path = tmp_path / "checkpoint.json"
    save_checkpoint(path, {"last_completed_page": 1})

    clear_checkpoint(path)

    assert not path.exists()


def test_clear_checkpoint_is_a_no_op_when_file_does_not_exist(tmp_path):
    clear_checkpoint(tmp_path / "missing.json")  # must not raise
