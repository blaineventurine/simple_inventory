[← Back to README](../README.md)

# Voice & AI Assistants

Simple Inventory registers ten native Home Assistant intents so you can
control your inventories by voice or through an LLM-backed conversation
agent, without writing any automations:

- **Remove/consume an item** — "remove one aluminum foil from the
  disposable goods inventory"
- **Add/restock an item** — "add two cans of soup to the pantry"
- **Set an exact quantity** — "set the milk in the fridge to three"
- **Move stock** — "move two milk from the fridge to the garage fridge in the
  kitchen" (without a quantity, everything at the source moves)
- **Query a quantity** — "how many aluminum foil do we have in disposable
  goods" or "how many apples are in dry goods" (when stock is in several
  places it adds a breakdown: "…: 2 in Fridge, 1 in Garage.")
- **Find an item in every inventory** — "how many batteries do we have",
  "do we have any butter", "where are the batteries", or in one inventory
  "do we have any milk in the kitchen" (searches item names and aliases in
  all enabled inventories, or the named one; an exact name or alias wins over
  partial matches: "I found 2 matches for batteries: 4 AA batteries in
  Garage (Shelf B) and 8 AA batteries in Kitchen (Drawer).")
- **Count low-stock items** — items at or below their restock threshold,
  and how many of them are out of stock ("2 items are low on stock, 1 of
  them out of stock.")
- **List low-stock items** — "what's running low", "what are we low on in
  the pantry" ("2 items are low on stock: Butter and Oil (out of stock).")
- **Count expired / expiring items** (counts distinct items, even if an
  item has several expiring batches)
- **List expired / expiring items**

Counts and lists scoped to one inventory name it as stored ("… in Kitchen"),
not as heard.

The add and remove intents take an optional **location** (the storage spot
inside the inventory, e.g. "Fridge"): adding stores the new stock there,
removing only takes stock that is there. The location must already exist in
the inventory (matched with the same typo tolerance as items); an unknown
location is refused with "I don't know a location called … in …" rather than
created. When the spoken location is ambiguous (e.g. "fridge" matching both
"Fridge Door" and "Fridge Drawer", with no location named exactly "Fridge"),
removing narrows the candidates to ones where the item has stock — one match
is used, several are asked about, none is refused; adding always asks.
LLM-backed agents fill this slot directly. With the bundled example
sentences, name the location before the inventory: "remove 2 milk from the
fridge in the kitchen", "add milk to the garage fridge in the kitchen".

The move intent needs the destination and, optionally, the source location;
both must already exist in the inventory (same matching and refusal as
above). LLM-backed agents may leave out the source, which moves the
soonest-expiring stock that isn't already at the destination.

Items and inventories are matched by name with typo tolerance (exact match,
then substring, then closest-match), so you don't need to remember exact
casing or the internal inventory ID. Items also match by any alias you've
set on them (see [Item Aliases](features.md#item-aliases)), which is handy for
giving voice commands a shorter or more natural name than what's stored.

## LLM-backed Assist (OpenAI, Google Generative AI, a local model via Ollama, etc.)

No setup needed beyond configuring the LLM conversation agent in "Assist"
control mode. Simple Inventory exposes these intents as callable tools to
Home Assistant's Assist API automatically — no entity exposure required,
since the tools resolve inventories and items by name rather than acting on
Home Assistant entities. Each tool's description ends with your current
inventory names, so the agent fills the inventory parameter with a real name.

## Local/offline Assist (Home Assistant Voice's default pipeline)

If your Home Assistant language is English, Spanish, French or Slovenian, check
**"Install example voice commands"** when adding your first inventory
(Settings → Devices & Services → Add Integration → Simple Inventory), or
later via the global Simple Inventory entry's **Configure** button (the same dialog
holds the [sidebar panel](../README.md#sidebar-panel) settings). This
copies the bundled example sentence file for that language into your config
directory, writes the inventory names file next to it (below) and reloads custom
sentences automatically — no restart needed. It never overwrites a file that's
already there, so it's safe to check even if you've already installed it or
created your own.

If you'd rather do it by hand — to review the content first, or because you
skipped the checkbox — copy the file for your language (`en`, `es`, `fr` or
`sl`) manually:

```bash
cp custom_components/simple_inventory/data/custom_sentences/en/simple_inventory.yaml \
   <config>/custom_sentences/en/simple_inventory.yaml
```

Then reload any Simple Inventory entry (or restart Home Assistant) so it writes the
names file and reloads custom sentences. Edit the sentence templates in that file to
add your own phrasing.

The sentences only accept the names of your inventories
(`{simple_inventory_name:inventory}`). Simple Inventory keeps them in
`<config>/custom_sentences/<language>/simple_inventory_names.yaml` and
rewrites that file whenever an inventory is added, renamed, enabled, disabled
or removed — don't edit it. Home Assistant prefers custom sentences over its
own, so an overly broad slot would hijack unrelated commands such as "add
milk to my shopping list" or "add 5 minutes to my timer". For Slovenian the
file also lists common case forms of each name's last word ("v kuhinji", "v
shrambo") to match how the language inflects noun endings; a name whose
forms don't follow those endings still works in the form it is stored in.

Answers are spoken in the conversation's language (the Assist pipeline's
language) when it is English, Spanish, French or Slovenian, regional variants
included ("fr-CA" answers in French); any other language gets English answers.
Item, inventory and location names are spoken as stored. The Spanish, French
and Slovenian sentence files cover the same commands as the English one, except
naming a location inside an add/remove command (LLM-backed agents can still
fill it).

**Upgrading an installed sentence file.** An installed English file that is still the
unedited copy of an earlier release is replaced with the current one automatically.
An edited one is left alone and a repair (Settings → Repairs) lists it: in that
format any words can name an inventory, so delete it and install the example
sentences again, or bring your edits over to the current file. The "move" sentences
can mis-parse location names that contain the words "from", "to" or "in";
LLM-backed assistants are unaffected.
