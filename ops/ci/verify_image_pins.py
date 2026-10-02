from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPROVED_IMAGES_PATH = ROOT / "ops" / "supply-chain" / "approved-images.json"
DOCKERFILE_PATTERN = re.compile(r"^\s*FROM\s+(\S+)", re.MULTILINE)
IMAGE_PATTERN = re.compile(r"^\s*image:\s*[\"']?([^\"'\s]+)", re.MULTILINE)
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def load_approved_images() -> tuple[set[str], dict[str, dict[str, object]]]:
    payload = json.loads(APPROVED_IMAGES_PATH.read_text(encoding="utf-8"))
    required_platforms = set(payload["required_platforms"])
    images = payload["images"]
    if not isinstance(images, dict):
        raise TypeError("approved images must be an object")
    return required_platforms, images


def docker_references() -> list[tuple[Path, str]]:
    references: list[tuple[Path, str]] = []
    dockerfiles = [
        *ROOT.glob("backend/Dockerfile*"),
        *ROOT.glob("frontend/Dockerfile*"),
    ]
    for path in dockerfiles:
        content = path.read_text(encoding="utf-8")
        references.extend(
            (path, match) for match in DOCKERFILE_PATTERN.findall(content)
        )

    for path in ROOT.glob("docker-compose*.yml"):
        content = path.read_text(encoding="utf-8")
        references.extend((path, match) for match in IMAGE_PATTERN.findall(content))

    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        content = path.read_text(encoding="utf-8")
        for reference in IMAGE_PATTERN.findall(content):
            if reference.startswith(("${{", "semantix-")):
                continue
            references.append((path, reference))
    return references


def validate_reference(
    path: Path,
    reference: str,
    approved_images: dict[str, dict[str, object]],
) -> str:
    if reference.count("@") != 1:
        raise ValueError(
            f"{path.relative_to(ROOT)}: mutable image reference {reference}"
        )

    tagged_image, digest = reference.split("@", maxsplit=1)
    if tagged_image not in approved_images:
        raise ValueError(f"{path.relative_to(ROOT)}: unapproved image {tagged_image}")
    if not DIGEST_PATTERN.fullmatch(digest):
        raise ValueError(f"{path.relative_to(ROOT)}: invalid digest for {tagged_image}")

    approved_digest = approved_images[tagged_image]["digest"]
    if digest != approved_digest:
        raise ValueError(
            f"{path.relative_to(ROOT)}: {tagged_image} does not use its approved digest"
        )
    return tagged_image


def main() -> None:
    required_platforms, approved_images = load_approved_images()
    used_images: set[str] = set()
    for path, reference in docker_references():
        used_images.add(validate_reference(path, reference, approved_images))

    missing_images = set(approved_images) - used_images
    if missing_images:
        missing = ", ".join(sorted(missing_images))
        raise ValueError(f"approved images are not referenced: {missing}")

    for image, approval in approved_images.items():
        platforms = set(approval["platforms"])
        missing_platforms = required_platforms - platforms
        if missing_platforms:
            missing = ", ".join(sorted(missing_platforms))
            raise ValueError(f"{image} does not support required platforms: {missing}")

    print(
        f"Verified {len(used_images)} approved image tags and digests "
        f"for {', '.join(sorted(required_platforms))}."
    )


if __name__ == "__main__":
    main()
