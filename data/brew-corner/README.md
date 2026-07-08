# The Brew Corner — demo catalog

Synthetic retail dataset for an **in-person store kiosk** demo (customer is already inside the shop — not a website or call center).

**Catalog file:** [`tests/brew-corner-catalog.json`](../../tests/brew-corner-catalog.json)

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

## Option 1 — Upload to UNO Q (recommended)

`moorcheh-edge up` must be running on the board.

**From the PC** (repo root):

```powershell
scp tests/brew-corner-catalog.json arduino@<UNO_Q_IP>:~/
scp tests/upload-catalog-to-edge.py arduino@<UNO_Q_IP>:~/
```

**On the UNO Q:**

```bash
source ~/moorcheh-venv/bin/activate
python ~/upload-catalog-to-edge.py --catalog ~/brew-corner-catalog.json -y
```

Use `--clear -y` to replace an existing catalog. Then `moorcheh-edge status` should show **`dimension`** and **`embedding_model`** set.

**On the PC:** open **Admin → Prompts** and paste `header_prompt` and `footer_prompt` from `tests/brew-corner-catalog.json` if you want to customize them (defaults work for The Brew Corner).

## Option 2 — Admin UI (manual)

1. Open http://localhost:5173/admin
2. **Answer prompts** tab — paste `header_prompt` and `footer_prompt` from `tests/brew-corner-catalog.json` → Save
3. **Documents** tab — for each entry in `documents[]`, create a document:
   - **doc_id**, **category**, **title**, **tags** (comma-separated), **text**

Each save embeds on the PC and syncs vectors to the UNO Q.

## Option 3 — Clear old edge data first

If you still see sciq or unrelated chunks in answers:

```bash
# On UNO Q
source ~/moorcheh-venv/bin/activate
moorcheh-edge clear-store
```

Then re-run the upload script or re-upload via Admin.

## File format

`tests/brew-corner-catalog.json` structure:

```json
{
  "store": { "name", "tagline" },
  "prompts": { "header_prompt", "footer_prompt" },
  "voice": { "holding_enabled" },
  "documents": [
    { "doc_id", "category", "title", "tags", "text" }
  ]
}
```

Copy `tests/brew-corner-catalog.json`, rename the store, and edit documents for your own demo.
