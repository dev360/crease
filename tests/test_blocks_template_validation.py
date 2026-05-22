"""Template-load validation for the v2 `blocks:` grammar.

These cases exercise rules that fire at `Template.model_validate` time —
before any file is opened. They sit next to the corpus tests because they
share the same public contract (a `Template` that survives load is one
that's safe to hand to `extract`).

All fixtures use Acme/Globex/Hooli vocabulary; no real data leaks into
this file or any error message it asserts on.
"""

from __future__ import annotations

import textwrap

import pytest
import yaml
from pydantic import ValidationError as PydValidationError

from crease import Template


def _load(yml_body: str) -> Template:
    return Template.model_validate(yaml.safe_load(textwrap.dedent(yml_body).strip()))


def test_blocks_requires_version_2() -> None:
    """A template that declares `blocks:` but leaves `version: 1` is rejected."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: needs_v2
            version: 1
            description: test
            entities: []
            blocks:
              - name: x
                starts_at: { column: 0, cell_pattern: ^a$ }
            """
        )
    assert "requires `version: 2`" in str(exc.value)


def test_block_ref_not_found_rejected() -> None:
    """`Entity.block` pointing at an undeclared block name is rejected."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: ghost_ref
            version: 2
            description: test
            blocks:
              - name: known_block
                starts_at: { column: 0, cell_pattern: ^a$ }
            entities:
              - name: order
                cardinality: many
                block: nope_doesnt_exist
                locate: { orientation: flat }
                fields: []
            """
        )
    assert "block reference" in str(exc.value)


def test_entity_tab_with_block_rejected() -> None:
    """Setting `entity.locate.tab_pattern` while also setting `entity.block` is rejected.
    The block owns tab targeting; the entity must not redeclare it."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: tab_collision
            version: 2
            description: test
            blocks:
              - name: weekly
                tab_pattern: ^W-\\d+$
                starts_at: { column: 0, cell_pattern: ^a$ }
            entities:
              - name: order
                cardinality: many
                block: weekly
                locate:
                  orientation: flat
                  tab_pattern: ".*"
                fields: []
            """
        )
    assert "tab scope" in str(exc.value)


def test_field_shadow_collision_rejected() -> None:
    """A capture name on block B and a FieldSpec name on an entity that targets B
    cannot share a name. Forces template authors to pick a single source for the
    field instead of relying on silent precedence."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: shadow
            version: 2
            description: test
            blocks:
              - name: weekly
                starts_at: { column: 0, cell_pattern: ^a$ }
                captures:
                  - field: order_date
                    from: { column: 0, cell_pattern: ^(\\d+)$, regex_group: 1 }
                    type: string
            entities:
              - name: order
                cardinality: many
                block: weekly
                locate: { orientation: flat }
                fields:
                  - { name: order_date, source_column: order_date, type: string }
            """
        )
    assert "collide with captures" in str(exc.value)


def test_duplicate_block_name_rejected() -> None:
    """Two blocks with the same `name` are rejected — entities reference blocks
    by name, so duplicates would be ambiguous."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: dup_name
            version: 2
            description: test
            blocks:
              - name: weekly
                starts_at: { column: 0, cell_pattern: ^a$ }
              - name: weekly
                starts_at: { column: 0, cell_pattern: ^b$ }
            entities: []
            """
        )
    assert "duplicate block name" in str(exc.value)


def test_column_letter_coerced_to_int() -> None:
    """`column: D` is accepted and coerced to 3; `column: 3` is also accepted."""
    t = _load(
        """
        template_id: letter_ok
        version: 2
        description: test
        blocks:
          - name: weekly
            starts_at: { column: D, cell_pattern: ^a$ }
        entities: []
        """
    )
    assert t.blocks[0].starts_at.column == 3


def test_column_multi_letter_rejected() -> None:
    """Multi-letter columns (``AA``, ``BC``) are out of scope for v1."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: bad_letter
            version: 2
            description: test
            blocks:
              - name: weekly
                starts_at: { column: AA, cell_pattern: ^a$ }
            entities: []
            """
        )
    assert "A..Z" in str(exc.value)


def test_skip_row_rule_requires_exactly_one_match_mode() -> None:
    """A SkipRowRule with neither `cell_pattern` nor `match_blank` set is rejected;
    so is one with both set."""
    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: skip_neither
            version: 2
            description: test
            blocks:
              - name: weekly
                starts_at: { column: 0, cell_pattern: ^a$ }
                separator_rows:
                  - { column: 0 }
            entities: []
            """
        )
    assert "exactly one of" in str(exc.value)

    with pytest.raises((PydValidationError, ValueError)) as exc:
        _load(
            """
            template_id: skip_both
            version: 2
            description: test
            blocks:
              - name: weekly
                starts_at: { column: 0, cell_pattern: ^a$ }
                separator_rows:
                  - { column: 0, cell_pattern: ^x$, match_blank: true }
            entities: []
            """
        )
    assert "exactly one of" in str(exc.value)
