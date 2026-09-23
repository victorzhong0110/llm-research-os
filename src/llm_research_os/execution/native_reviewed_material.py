"""Closed artifact documents for reviewed-native preparation.

These bytes are content-addressed inputs. Parsing them does not import an
entrypoint, install a package, or start a process.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from llm_research_os.execution.native_reviewed_documents import (
    ByteDigest,
    NativeReviewedDocumentModel,
    ReviewedEntrypoint,
    ReviewedIdentifier,
    ReviewedPlatform,
    ReviewedPythonVersion,
)

MAX_BUNDLE_FILES = 32
MAX_DEPENDENCY_PINS = 32
_PY_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*\.py$")
_PIN_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class NativeReviewedBundleFile(NativeReviewedDocumentModel):
    """One Python source inside a reviewed bundle. The path is bundle-relative."""

    path: str = Field(min_length=4, max_length=256)
    digest: ByteDigest

    @field_validator("path", mode="before")
    @classmethod
    def path_is_relative_python(cls, value: object) -> object:
        if type(value) is not str or _PY_PATH.fullmatch(value) is None:
            raise ValueError("bundle file path must be a relative Python module")
        return value


class NativeReviewedPythonBundle(NativeReviewedDocumentModel):
    """Digest index of a reviewed CPU Python brick. Not an executable path."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedPythonBundle"]
    entrypoint: ReviewedEntrypoint
    files: tuple[NativeReviewedBundleFile, ...] = Field(
        min_length=1,
        max_length=MAX_BUNDLE_FILES,
    )

    @field_validator("files", mode="before")
    @classmethod
    def freeze_files(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("files must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def entrypoint_file_is_present(self) -> Self:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("bundle file paths must be unique")
        if entrypoint_source_path(self.entrypoint) not in paths:
            raise ValueError("bundle does not contain the entrypoint module")
        return self


class NativeReviewedCodeReview(NativeReviewedDocumentModel):
    """Review citation bound to one bundle digest. Not a launch credential."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedCodeReview"]
    bundle_digest: ByteDigest = Field(alias="bundleDigest")
    media_type: Literal["researchos.native-reviewed-python-bundle/v0alpha1"] = Field(
        alias="mediaType"
    )
    entrypoint: ReviewedEntrypoint


class NativeReviewedInterpreterIdentity(NativeReviewedDocumentModel):
    """Byte-identified interpreter. A filesystem path is not this document."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedInterpreterIdentity"]
    implementation: Literal["cpython"]
    python_version: ReviewedPythonVersion = Field(alias="pythonVersion")
    abi: Literal["cp312", "cp313", "cp314"]
    platform: ReviewedPlatform


class NativeReviewedPackagePin(NativeReviewedDocumentModel):
    """Identity of one reviewed distribution. Preparation does not install it."""

    name: ReviewedIdentifier
    version: str = Field(min_length=1, max_length=64)
    digest: ByteDigest

    @field_validator("version", mode="before")
    @classmethod
    def version_is_closed(cls, value: object) -> object:
        if type(value) is not str or _PIN_VERSION.fullmatch(value) is None:
            raise ValueError("package version is not a closed token")
        return value


class NativeReviewedDependencyLock(NativeReviewedDocumentModel):
    """Reviewed lock identity. No install scripts or URLs are accepted."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedDependencyLock"]
    packages: tuple[NativeReviewedPackagePin, ...] = Field(max_length=MAX_DEPENDENCY_PINS)

    @field_validator("packages", mode="before")
    @classmethod
    def freeze_packages(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("packages must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def pins_are_sorted_and_unique(self) -> Self:
        names = [item.name for item in self.packages]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("dependency pins must be unique and sorted by name")
        return self


class NativeReviewedDependencyInventory(NativeReviewedDocumentModel):
    """Resolved inventory identity. Preparation does not import these pins."""

    api_version: Literal["researchos.dev/v0alpha1"] = Field(alias="apiVersion")
    kind: Literal["NativeReviewedDependencyInventory"]
    packages: tuple[NativeReviewedPackagePin, ...] = Field(max_length=MAX_DEPENDENCY_PINS)

    @field_validator("packages", mode="before")
    @classmethod
    def freeze_packages(cls, value: object) -> object:
        if type(value) is not list:
            raise ValueError("packages must be a JSON array")
        return tuple(value)

    @model_validator(mode="after")
    def pins_are_sorted_and_unique(self) -> Self:
        names = [item.name for item in self.packages]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("dependency pins must be unique and sorted by name")
        return self


def entrypoint_source_path(entrypoint: str) -> str:
    """Map ``package.module:function`` to a bundle-relative ``.py`` path.

    The mapping is a string check. It does not import the module.
    """

    module, separator, _function = entrypoint.partition(":")
    if separator != ":" or module == "":
        raise ValueError("entrypoint is not module:function")
    return module.replace(".", "/") + ".py"
