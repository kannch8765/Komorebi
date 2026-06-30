"""User profile — persistent personal context across REPL sessions.

Stores the user's home location (lat, lon, label) so queries like
「家から池袋へ」 or 「家の近くでゆっくりできる場所」 can be resolved
without the user re-typing their starting point each session.

Scope (V2.5): just `home`. Future fields (work, default_slider,
mobility preferences) will be additive — see CLAUDE.md "Personal context".

Persistence: local JSON at `data/user_profile.json` (gitignored).
No cloud sync, no telemetry — home is PII.

Design notes:

- **Frozen `HomeLocation`**: a home coord is a value, not a mutable
  state. Reassigning home means creating a new HomeLocation, not
  mutating one in place.

- **Mutable `UserProfile`**: load/save semantics are easier with a
  mutable container. Frozen would force "load → modify → save" to
  work via `dataclasses.replace`, which is fine but adds boilerplate
  for no real safety win at this scale.

- **Atomic save**: write to `.tmp` then `os.replace()` to avoid
  partial writes corrupting the profile.

- **`load()` never raises on missing file**: a fresh user has no
  profile yet. We return `UserProfile.default()` instead. Corruption
  DOES raise — silent recovery would mask real bugs.

- **Schema versioning**: `version` field lets us evolve the schema
  with explicit migration code (vs. guessing from presence/absence
  of fields).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Self


# Bump when the on-disk schema changes incompatibly. load() checks this
# and raises if the file was written by a newer Komorebi version.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HomeLocation:
    """A named point on Earth. Used for the user's home (and later work).

    Coordinates are decimal degrees (WGS84), matching Google Places +
    the transit API. Label is human-readable Japanese or English
    (e.g. "横浜駅", "Yokohama Station").
    """

    label: str
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError(f"HomeLocation.label must be non-empty str, got {self.label!r}")
        if not isinstance(self.lat, (int, float)) or isinstance(self.lat, bool):
            raise TypeError(f"HomeLocation.lat must be numeric, got {type(self.lat).__name__}")
        if not isinstance(self.lon, (int, float)) or isinstance(self.lon, bool):
            raise TypeError(f"HomeLocation.lon must be numeric, got {type(self.lon).__name__}")
        if not (-90.0 <= float(self.lat) <= 90.0):
            raise ValueError(f"HomeLocation.lat must be in [-90, 90], got {self.lat}")
        if not (-180.0 <= float(self.lon) <= 180.0):
            raise ValueError(f"HomeLocation.lon must be in [-180, 180], got {self.lon}")

    @classmethod
    def from_dict(cls, data: dict) -> "HomeLocation":
        """Build from a JSON-loaded dict. Raises ValueError on missing/invalid fields."""
        try:
            return cls(label=data["label"], lat=data["lat"], lon=data["lon"])
        except KeyError as exc:
            raise ValueError(f"HomeLocation dict missing required key: {exc.args[0]}") from exc


@dataclass
class UserProfile:
    """Persistent per-user context loaded from data/user_profile.json.

    Currently only `home`. Future fields go here as Optional[...].
    """

    home: HomeLocation | None = None
    version: int = SCHEMA_VERSION

    # ------------------------------------------------------------------ #
    # Defaults & factories
    # ------------------------------------------------------------------ #

    @classmethod
    def default(cls) -> "UserProfile":
        """Empty profile — no home set yet."""
        return cls(home=None)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: str | Path) -> "UserProfile":
        """Load profile from `path`. Missing file → default(); corrupt → raises.

        Raises:
            FileNotFoundError: should never happen — we return default().
            ValueError:        JSON parse error, schema version mismatch, or
                               field validation error.
            OSError:           permission denied / disk error.
        """
        path = Path(path)
        if not path.exists():
            return cls.default()
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    def save(self, path: str | Path) -> None:
        """Atomically write profile to `path`. Creates parent dirs if missing.

        Uses tmp file + os.replace() to avoid partial writes.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict. Home is nested or null."""
        result: dict = {"version": self.version, "home": None}
        if self.home is not None:
            result["home"] = asdict(self.home)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        """Deserialize from a JSON-loaded dict. Validates everything."""
        if not isinstance(data, dict):
            raise ValueError(f"profile root must be dict, got {type(data).__name__}")
        version = data.get("version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported profile schema version {version}; "
                f"this Komorebi expects {SCHEMA_VERSION}"
            )
        home_raw = data.get("home")
        if home_raw is None:
            home = None
        elif isinstance(home_raw, dict):
            home = HomeLocation.from_dict(home_raw)
        else:
            raise ValueError(f"profile.home must be dict or null, got {type(home_raw).__name__}")
        return cls(home=home, version=version)

    # ------------------------------------------------------------------ #
    # Mutators (return new profile; this one is unchanged)
    # ------------------------------------------------------------------ #

    def with_home(self, home: HomeLocation | None) -> Self:
        """Return a new profile with `home` set (or cleared if None)."""
        return type(self)(home=home, version=self.version)

    def clear_home(self) -> Self:
        """Return a new profile with home removed."""
        return self.with_home(None)