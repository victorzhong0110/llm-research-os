# Map examples

valid/write.json composes a note. invalid/missing-parent.json is invalid because
its parentId does not identify an existing group.

activity/valid.json is an empty latest-activity snapshot. activity/invalid.json
is invalid because highWaterMark cannot be negative. These API response examples
use the local-api-response schema, not the map-write schema.
