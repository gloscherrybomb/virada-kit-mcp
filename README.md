# Virada kit maker (MCP server)

Make a cycling kit for **Virada** with the AI of your choice. Give your agent pictures of a jersey and bib shorts; this
MCP server tells it the game's kit format, shows it the kit on the game's riders (male and female, in the game's
look) so it can compare with your pictures and fix what differs, and writes the finished **kit file** (`.kit.zip`) for
you to send in. Submitted kits are reviewed before they appear in the game.

## Connect your agent

The server runs on your computer (Python 3.12+, [uv](https://docs.astral.sh/uv/)):

    uvx --from git+https://github.com/OWNER/virada-kit-mcp virada-kit

**Claude Code:** `claude mcp add virada-kit -- uvx --from git+https://github.com/OWNER/virada-kit-mcp virada-kit`

**Claude Desktop, Gemini CLI, Cursor and other MCP clients** (their MCP settings file, `mcpServers`):

```json
{"mcpServers": {"virada-kit": {"command": "uvx", "args": ["--from", "git+https://github.com/OWNER/virada-kit-mcp", "virada-kit"]}}}
```

Then ask, for example: *"Make a Virada kit from this picture (attached). Use the virada-kit tools; show me the preview
before exporting."* If you only have a front picture, the agent will propose the back and sides first.

## What the agent gets

| tool | does |
|---|---|
| `get_kit_spec` | the format and the workflow (SPEC.md) |
| `get_template` | the sheet templates: a guide (where each rider's seams, zip and pockets fall) or a clean canvas to paint on |
| `add_asset` | add a logo or a painted sheet (file path or base64) |
| `render_sheets` | the flat jersey and bib sheets |
| `preview_kit` | the kit on the male or female rider from six angles |
| `compare_to_reference` | your picture beside the kit on the rider from a similar angle |
| `validate_kit`, `export_kit` | check it and write the `.kit.zip` |

Agents can build a kit from **layers** (colours, bands, panels, stripes, shapes, lines, text, logos) or paint the
whole **sheet** as a picture (image models), or both. The format: [SPEC.md](src/virada_kit/SPEC.md).

## The kit file

`<name>.kit.zip`: `kit.json` (the design and its notes), `jersey.png` (2048 x 2048) and `bib.png` (2048 x 1024), the
pictures it uses, and previews. The game reads the two sheets.

## Notes
- Only use names, logos and designs you own or made.
- The preview riders are made from Quaternius' Universal Base Characters (CC0). Fonts: Montserrat and Oswald (SIL Open
  Font License, see `src/virada_kit/data/fonts`).
- Run over HTTP instead: `virada-kit --http --port 8000` (then pictures must be sent as base64, not paths).

## Develop

    uv sync && uv run pytest
