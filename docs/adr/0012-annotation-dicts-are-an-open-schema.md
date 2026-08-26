# 12. Annotation dicts are an open schema

Date: 2026-08-25

## Status

Accepted

## Context

`annotations.json` is public library surface, not just a file the app writes to itself: `load_annotations` and `load_database_annotations` are exported from `clinical_scope/__init__.py`, and the format is documented for users who hand-write a file or generate one from another tool.

`Annotation.to_dict` wrote a fixed thirteen-key literal, so any key the class did not recognise was erased. It was tempting to read that as a mutation-time concern — the callbacks manipulate raw dicts, so a delete or a label toggle looked like the place a stray key might survive or die. It is not. `auto_load_annotations` hydrates the file through `from_dict` and re-serialises through `to_dict` straight into `annotation-store`, so an externally authored file lost its keys **at load**, before the user clicked anything, and the stripped version was what the next save wrote back. The raw-dict mutations preserved keys that could no longer be present.

That leaves exactly one choke point, and it is the one every path already goes through.

## Decision

**An annotation dict is an open schema: keys the app does not own are carried, not dropped.**

`Annotation` holds an `extra` dict. `from_dict` collects every key outside the owned set into it; `to_dict` splats `extra` back **before** the owned keys, so a stale or hostile duplicate (`"id"`, `"type"`) can never shadow a real field. A round-trip through the app — load, edit, save — is lossless for anything the app does not understand.

The owned set is derived from `dataclasses.fields(Annotation)` rather than restated as a literal, so promoting a convention to a real field automatically stops it landing in `extra`.

## Scope

This is a **record-level** promise. Sibling keys in the JSON envelope — anything alongside `"annotations"`, including the `"version"` the `io.py` docstring anticipates — are still dropped, because `save_annotations` writes a fresh envelope rather than reading and merging the existing one.

That was considered and deliberately left out. Read-before-write introduces a merge-or-clobber question when the file has changed on disk underneath a running app, which is a larger decision than the one this ADR makes, and no consumer needs it yet. **Revisit if** a tool appears that stores state in the envelope.

## Consequences

- Users can carry their own per-annotation fields — a reviewer, a confidence, an external record id — through the app without the app understanding them.
- Promotion is free: when a convention becomes a real field, `from_dict` starts claiming it and `extra` quietly stops holding it. No migration.
- **Accepted cost:** `Annotation` cannot later be swapped for a strict-schema model without breaking this, and the guarantee needs a test that a foreign key survives load → mutate → save rather than merely load → save.
- Sits beside a second rule that fell out of the same work and stays at docstring level: **`from_dict` transcribes, `create` interprets.** Creation-time defaulting — a point is never global, and its label starts hidden — lives in `Annotation.create`, never in `__post_init__`, because deserialisation must reproduce a stored annotation verbatim: a point whose label the user explicitly un-hid has to load back un-hidden. The same shape as [ADR-0010](0010-load-transcribes-format-interprets.md), one layer up.
