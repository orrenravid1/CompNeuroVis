"""Small Xeno-canto catalog adapter for STFT viewer examples."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv

from stft_viewer import AudioClip


@dataclass(frozen=True, slots=True)
class AnimalQuery:
    label: str
    english_name: str
    group: str


DEFAULT_ANIMALS = (
    AnimalQuery("Common raven", "Common Raven", "birds"),
    AnimalQuery("Common blackbird", "Common Blackbird", "birds"),
    AnimalQuery("American bullfrog", "American Bullfrog", "frogs"),
    AnimalQuery("Red fox", "Red Fox", "land mammals"),
)


def _safe_name(value: str) -> str:
    for character in '<>:"/\\|?*':
        value = value.replace(character, "_")
    return value.strip(". ")


def _recording_path(cache_dir: Path, recording: Mapping[str, Any]) -> Path:
    species = _safe_name(
        f"{recording.get('gen', 'Unknown').strip()}_{recording.get('sp', 'unknown').strip()}"
    )
    filename = _safe_name(
        str(recording.get("file-name") or f"XC{recording.get('id', 'unknown')}.mp3")
    )
    return cache_dir / species / filename


def download_catalog(
    animals: Sequence[AnimalQuery] = DEFAULT_ANIMALS,
    *,
    cache_dir: str | Path = ".animal_sound_cache",
    api_key: str | None = None,
    max_duration: float = 8.0,
) -> dict[str, AudioClip]:
    """Download one quality-A recording per animal and decode each clip."""
    try:
        from xcapi.client import XenoCantoClient
        from xcapi.downloader import Downloader
        from xcapi.query import QueryBuilder
    except ImportError:
        raise RuntimeError(
            "Install this app's environment from examples/animal_sounds"
        ) from None

    load_dotenv(Path(__file__).with_name(".env"))
    resolved_key = api_key or os.getenv("XENO_CANTO_API_KEY")
    if not resolved_key:
        raise RuntimeError(
            "Set XENO_CANTO_API_KEY. Xeno-canto requires an account API key."
        )

    output = Path(cache_dir).expanduser().resolve()
    downloader = Downloader(output_dir=str(output))
    clips: dict[str, AudioClip] = {}
    errors: list[str] = []
    with XenoCantoClient(api_key=resolved_key) as client:
        for animal in animals:
            query = (
                QueryBuilder()
                .group(animal.group)
                .english_name(animal.english_name)
                .quality("A")
                .build()
            )
            recordings = client.search(query, per_page=50, max_results=8)
            if not recordings:
                errors.append(f"{animal.label}: no quality-A recordings")
                continue
            recordings.sort(key=lambda item: str(item.get("length", "99:99")))
            loaded = False
            for recording in recordings:
                path = _recording_path(output, recording)
                if not path.exists():
                    stats = downloader.download_recordings([recording])
                    if not stats["downloaded"] and not path.exists():
                        continue
                metadata = {
                    key: recording.get(key)
                    for key in (
                        "id", "en", "gen", "sp", "rec", "cnt", "loc",
                        "type", "q", "lic", "url", "date", "length",
                    )
                }
                clips[animal.label] = AudioClip.from_file(
                    path,
                    label=str(recording.get("en") or animal.label),
                    metadata=metadata,
                    max_duration=max_duration,
                )
                loaded = True
                break
            if not loaded:
                errors.append(f"{animal.label}: download failed")
    if not clips:
        detail = "; ".join(errors) or "no matching recordings"
        raise RuntimeError(f"Could not load Xeno-canto catalog: {detail}")
    return clips


__all__ = ["AnimalQuery", "DEFAULT_ANIMALS", "download_catalog"]
