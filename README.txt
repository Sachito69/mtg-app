# MTG App - Refactored Layout

This refactor keeps the existing Flask routes and database logic intact, but moves all embedded HTML out of `app.py`.

## Replace
- Replace your current `app.py` with this `app.py`.
- Copy the entire `templates` folder beside `app.py`.

## Keep your existing files
- `add_card.py`
- `deck_logic.py`
- `.env`
- `static/style.css`
- `requirements.txt`

Your project should look like:

mtg-app/
  app.py
  add_card.py
  deck_logic.py
  .env
  requirements.txt
  templates/
    ...
  static/
    style.css

Run:
    py app.py

This is the first/safest refactor stage. The next stage can split the Python routes into Flask Blueprints without mixing that larger change into the template migration.
