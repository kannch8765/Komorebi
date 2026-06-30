"""Tests for models/user_profile.py — HomeLocation + UserProfile persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.user_profile import (
    SCHEMA_VERSION,
    HomeLocation,
    UserProfile,
)


# ---------------------------------------------------------------------------
# HomeLocation validation
# ---------------------------------------------------------------------------


def test_home_location_basic_construction():
    """A valid HomeLocation can be constructed."""
    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    assert home.label == "横浜駅"
    assert home.lat == 35.4657
    assert home.lon == 139.6223


def test_home_location_frozen():
    """HomeLocation is immutable."""
    home = HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    with pytest.raises((AttributeError, Exception)):
        home.label = "東京駅"  # type: ignore[misc]


@pytest.mark.parametrize("bad_lat", [-90.1, 90.1, -200.0, 200.0])
def test_home_location_lat_out_of_range_raises(bad_lat):
    """lat outside [-90, 90] raises ValueError."""
    with pytest.raises(ValueError, match=r"lat must be in \[-90, 90\]"):
        HomeLocation(label="x", lat=bad_lat, lon=0.0)


@pytest.mark.parametrize("bad_lon", [-180.1, 180.1, -400.0, 400.0])
def test_home_location_lon_out_of_range_raises(bad_lon):
    """lon outside [-180, 180] raises ValueError."""
    with pytest.raises(ValueError, match=r"lon must be in \[-180, 180\]"):
        HomeLocation(label="x", lat=0.0, lon=bad_lon)


@pytest.mark.parametrize("edge_lat,edge_lon", [(-90.0, -180.0), (90.0, 180.0), (0.0, 0.0)])
def test_home_location_boundary_values_ok(edge_lat, edge_lon):
    """Boundary lat/lon values are accepted."""
    home = HomeLocation(label="edge", lat=edge_lat, lon=edge_lon)
    assert home.lat == edge_lat
    assert home.lon == edge_lon


@pytest.mark.parametrize("bad_label", ["", "   ", "\t\n"])
def test_home_location_empty_label_raises(bad_label):
    """Empty or whitespace-only label raises ValueError."""
    with pytest.raises(ValueError, match="label must be non-empty"):
        HomeLocation(label=bad_label, lat=0.0, lon=0.0)


def test_home_location_label_none_raises():
    """None label raises TypeError (caught by the str type check)."""
    with pytest.raises((TypeError, ValueError)):
        HomeLocation(label=None, lat=0.0, lon=0.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_coord", ["35.0", None, [35.0], {"v": 35.0}])
def test_home_location_non_numeric_coord_raises(bad_coord):
    """Non-numeric lat/lon raises TypeError."""
    with pytest.raises(TypeError, match="must be numeric"):
        HomeLocation(label="x", lat=bad_coord, lon=0.0)  # type: ignore[arg-type]


def test_home_location_rejects_bool_for_coord():
    """bool is excluded from numeric check (Python bool is an int subclass)."""
    with pytest.raises(TypeError, match="must be numeric"):
        HomeLocation(label="x", lat=True, lon=0.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HomeLocation.from_dict
# ---------------------------------------------------------------------------


def test_home_location_from_dict_ok():
    """Round-trip a dict → HomeLocation."""
    home = HomeLocation.from_dict({"label": "横浜駅", "lat": 35.4657, "lon": 139.6223})
    assert home == HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)


@pytest.mark.parametrize("missing_key", ["label", "lat", "lon"])
def test_home_location_from_dict_missing_key_raises(missing_key):
    """Dict missing any required key raises ValueError."""
    data = {"label": "x", "lat": 0.0, "lon": 0.0}
    data.pop(missing_key)
    with pytest.raises(ValueError, match=f"missing required key: {missing_key}"):
        HomeLocation.from_dict(data)


# ---------------------------------------------------------------------------
# UserProfile.default + serialization round-trip
# ---------------------------------------------------------------------------


def test_default_profile_has_no_home():
    """UserProfile.default() returns profile with home=None."""
    p = UserProfile.default()
    assert p.home is None
    assert p.version == SCHEMA_VERSION


def test_profile_round_trip_via_dict():
    """to_dict → from_dict preserves all fields."""
    original = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    restored = UserProfile.from_dict(original.to_dict())
    assert restored == original


def test_profile_round_trip_without_home():
    """to_dict → from_dict preserves profile with home=None."""
    original = UserProfile.default()
    restored = UserProfile.from_dict(original.to_dict())
    assert restored == original
    assert restored.home is None


def test_profile_to_dict_shape():
    """to_dict produces the expected JSON shape with version + home."""
    p = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    data = p.to_dict()
    assert data == {
        "version": SCHEMA_VERSION,
        "home": {"label": "横浜駅", "lat": 35.4657, "lon": 139.6223},
    }


def test_profile_to_dict_when_no_home():
    """to_dict with home=None emits home=null in JSON."""
    p = UserProfile.default()
    data = p.to_dict()
    assert data == {"version": SCHEMA_VERSION, "home": None}


# ---------------------------------------------------------------------------
# UserProfile.load
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_default(tmp_path: Path):
    """load() on a missing path returns UserProfile.default() — no error."""
    p = tmp_path / "no_such_profile.json"
    loaded = UserProfile.load(p)
    assert loaded == UserProfile.default()
    assert loaded.home is None


def test_load_existing_file(tmp_path: Path):
    """load() reads and parses a previously-saved profile."""
    p = tmp_path / "profile.json"
    p.write_text(
        json.dumps(
            {
                "version": SCHEMA_VERSION,
                "home": {"label": "横浜駅", "lat": 35.4657, "lon": 139.6223},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = UserProfile.load(p)
    assert loaded.home == HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)


def test_load_corrupt_json_raises(tmp_path: Path):
    """load() raises ValueError on unparseable JSON."""
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        UserProfile.load(p)


def test_load_wrong_version_raises(tmp_path: Path):
    """load() raises ValueError on a profile from a newer schema version."""
    p = tmp_path / "future.json"
    p.write_text(
        json.dumps({"version": SCHEMA_VERSION + 99, "home": None}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported profile schema version"):
        UserProfile.load(p)


def test_load_home_with_invalid_coords_raises(tmp_path: Path):
    """load() raises ValueError if the saved home has bad coords."""
    p = tmp_path / "bad_home.json"
    p.write_text(
        json.dumps(
            {
                "version": SCHEMA_VERSION,
                "home": {"label": "x", "lat": 999.0, "lon": 0.0},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"lat must be in \[-90, 90\]"):
        UserProfile.load(p)


def test_load_non_dict_root_raises(tmp_path: Path):
    """load() raises ValueError if the root JSON value isn't an object."""
    p = tmp_path / "list_root.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="profile root must be dict"):
        UserProfile.load(p)


def test_load_home_wrong_type_raises(tmp_path: Path):
    """load() raises ValueError if home is a non-dict, non-null value."""
    p = tmp_path / "bad_home_type.json"
    p.write_text(
        json.dumps({"version": SCHEMA_VERSION, "home": "横浜駅"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="profile.home must be dict or null"):
        UserProfile.load(p)


# ---------------------------------------------------------------------------
# UserProfile.save
# ---------------------------------------------------------------------------


def test_save_creates_parent_dirs(tmp_path: Path):
    """save() creates missing parent directories."""
    p = tmp_path / "nested" / "deeper" / "profile.json"
    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    profile.save(p)
    assert p.exists()
    # And it's loadable
    loaded = UserProfile.load(p)
    assert loaded == profile


def test_save_is_atomic_no_tmp_left(tmp_path: Path):
    """save() cleans up the .tmp file after a successful write."""
    p = tmp_path / "profile.json"
    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    profile.save(p)
    # The tmp file should not linger
    assert not (tmp_path / "profile.json.tmp").exists()
    assert p.exists()


def test_save_then_load_round_trip(tmp_path: Path):
    """Save then load preserves all fields exactly."""
    p = tmp_path / "profile.json"
    original = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    original.save(p)
    loaded = UserProfile.load(p)
    assert loaded == original


def test_save_default_profile(tmp_path: Path):
    """A profile with home=None saves and loads cleanly."""
    p = tmp_path / "profile.json"
    UserProfile.default().save(p)
    loaded = UserProfile.load(p)
    assert loaded.home is None


def test_save_uses_unicode(tmp_path: Path):
    """save() preserves Japanese characters (ensure_ascii=False)."""
    p = tmp_path / "profile.json"
    profile = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    profile.save(p)
    raw = p.read_text(encoding="utf-8")
    assert "横浜駅" in raw  # not escaped to \u escape sequences
    assert "\\u" not in raw


# ---------------------------------------------------------------------------
# UserProfile.with_home / clear_home (immutable update)
# ---------------------------------------------------------------------------


def test_with_home_returns_new_profile():
    """with_home returns a new instance; original is unchanged."""
    original = UserProfile.default()
    new = original.with_home(HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    assert original.home is None
    assert new.home == HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223)
    assert new is not original


def test_with_home_none_clears_home():
    """with_home(None) clears the home (replaces)."""
    original = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    cleared = original.with_home(None)
    assert cleared.home is None
    assert original.home is not None  # original unchanged


def test_clear_home():
    """clear_home is shorthand for with_home(None)."""
    original = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    cleared = original.clear_home()
    assert cleared.home is None


def test_with_home_replaces_existing():
    """with_home replaces the previous home (does not merge)."""
    original = UserProfile(home=HomeLocation(label="横浜駅", lat=35.4657, lon=139.6223))
    new = original.with_home(HomeLocation(label="東京駅", lat=35.6812, lon=139.7671))
    assert new.home.label == "東京駅"
    assert original.home.label == "横浜駅"  # original unchanged