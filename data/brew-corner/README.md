# The Brew Corner — demo catalog

Synthetic retail dataset for an **in-person store kiosk** demo (customer is already inside the shop — not a website or call center).

| Field | Value |
|-------|--------|
| **Store name** | The Brew Corner |
| **Type** | Café + mini-market |
| **Address / phone** | Not used — in-store kiosk only; ask staff at the counter |
| **Documents** | 26 (hours, menus, grocery, policies, services, accessibility, and more) |

## Sample questions to try

- "What coffee do you have?"
- "How much is a latte?"
- "Do you have oat milk?"
- "What are your store hours?"
- "Can I return unopened grocery items?"
- "Is there a student discount?"
- "Do you have gluten-free options?"
- "What's on the kids menu?"
- "Do you cater coffee for meetings?"
- "Is there a senior discount?"
- "Can I bring my dog inside?"

## Option 1 — Seed script (recommended)

From your PC, with `MOORCHEH_EDGE_URL` pointing at the UNO Q and `retail-kiosk-api` **not** required (talks to edge directly):

```powershell
$env:MOORCHEH_EDGE_URL = "http://10.0.0.196:8080"
python "c:\Users\patel\Downloads\Edge AI\moorcheh-edge-private\scripts\seed-retail-catalog.py" `
  --catalog "c:\Users\patel\Downloads\Edge AI\moorcheh-edge-private\retail-kiosk\data\brew-corner\catalog.json"
```

Flags:

| Flag | Purpose |
|------|---------|
| `--skip-existing` | Skip documents already in SQLite (default behavior) |
| `--update-existing` | Re-upload and replace documents that already exist |
| `--set-prompts` | Save store-specific header/footer prompts in SQLite |
| `--clear-edge` | Call `moorcheh-edge clear-store` before upload (removes old test/sciq data) |

Example — fresh edge + full catalog + prompts:

```powershell
$env:MOORCHEH_EDGE_URL = "http://10.0.0.196:8080"
python "c:\Users\patel\Downloads\Edge AI\moorcheh-edge-private\scripts\seed-retail-catalog.py" `
  --catalog "c:\Users\patel\Downloads\Edge AI\moorcheh-edge-private\retail-kiosk\data\brew-corner\catalog.json" `
  --clear-edge --set-prompts
```

## Option 2 — UNO Q only (one command, Python client)

Copy the repo folder `retail-kiosk/data/brew-corner/` to the board if it is not there yet, then SSH in:

```bash
source ~/moorcheh-venv/bin/activate ; python ~/scripts/upload-catalog-edge.py --catalog ~/retail-kiosk/data/brew-corner/catalog.json --clear -y
```

Uses `moorcheh-edge-client` only: clears edge, embeds on the board, uploads every chunk with `[meta]…[/meta]` formatting. Does not update PC SQLite or kiosk prompts — use Admin on PC for prompts, or Option 1 from PC for full sync.

## Option 3 — Admin UI (manual)

1. Open http://localhost:5173/admin
2. **Answer prompts** tab — paste `header_prompt` and `footer_prompt` from `catalog.json` → Save
3. **Documents** tab — for each entry in `documents[]`, create a document:
   - **doc_id**, **category**, **title**, **tags** (comma-separated), **text**

Each save embeds on the PC and syncs vectors to the UNO Q.

## Option 4 — Clear old edge data first

If you still see sciq or unrelated chunks in answers:

```bash
# On UNO Q
source ~/moorcheh-venv/bin/activate
moorcheh-edge clear-store
```

Then run the seed script or re-upload via Admin.

## File format

`catalog.json` structure:

```json
{
  "store": { "name", "tagline", "address", "phone" },
  "prompts": { "header_prompt", "footer_prompt" },
  "documents": [
    { "doc_id", "category", "title", "tags", "text" }
  ]
}
```

You can copy this folder, rename the store in `catalog.json`, and edit documents for your own demo.
