# Personalization few-shot examples

These pairs are injected into the Claude vision prompt in `agents/personalizer.py`.
They define the **target style** for X Project (3–5 words: room + aesthetic) and
Y Detail (4–6 words: a prominent design feature — countertop, island, lighting,
range hood, vanity, fixture). Y Detail must NEVER describe walls, flooring, trim,
brick (unless used as a feature surface), grout, or ceilings.

Drawn from operator-curated CRM exports.

| X Project                          | Y Detail                              |
|-----------------------------------|---------------------------------------|
| white subway tile bath            | matte black contrast sink             |
| dark modern kitchen remodel       | blue marble waterfall island          |
| frameless glass shower bath       | mosaic tile accent strip              |
| warm wood kitchen remodel         | black framed glass cabinets           |
| white shaker kitchen remodel      | granite waterfall island top          |
| tiled walk-in shower remodel      | pebble floor mosaic niche             |
| herringbone tile bath remodel     | brushed gold fixtures throughout      |
| modern open kitchen remodel       | geometric black fireplace surround    |

Operator: when adding more examples, keep the same shape. The agent does not
re-train — these are inlined verbatim into every prompt.
