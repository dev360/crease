# Layouts

Crease handles four layout patterns. Each maps to an `orientation:` value
in the template's `locate:` block.

!!! note "Placeholder page"
    Detailed walkthroughs of each layout — with screenshots of the source
    xlsx, the matching template, and the canonical output — are being
    written. Worked examples under [`test_cases/`](https://github.com/dev360/crease/tree/main/test_cases)
    cover every layout.

| Orientation | When to use | Example fixture |
|---|---|---|
| `flat` | A standard table with a header row | `flat_simple` |
| `property_sheet` | Two-column `label, value` pairs | `property_sheet_cover` |
| `anchored` | Scattered labels at arbitrary positions | `anchored_scattered` |
| Multi-tab via `tab_pattern` | One entity drawn from many tabs | `multi_tab_acme` |
