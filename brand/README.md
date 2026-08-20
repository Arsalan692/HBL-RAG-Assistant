# Brand assets

`hbl-lockup-source.png` is the official HBL lockup — the chevron mark plus the
wordmark, on transparency. Every icon in `frontend/public/` is derived from it
by `make_icons.py`; none of them were redrawn by hand.

## Regenerating

```bash
pip install pillow
python brand/make_icons.py
```

Only needed if the source artwork changes.

## Colours

| Token | Light | Dark | Used for |
| --- | --- | --- | --- |
| Brand teal | `#009F8C` | `#2DD4BF` | Borders, focus rings, progress bars, the streaming caret |
| Accessible fill | `#008373` | `#2DD4BF` | Anything with text or an icon on top |
| Lime | `#E0DF00` | — | Appears in the mark only; not used in the interface |

The two teals exist because white on the brand teal is 3.31:1, below the WCAG AA
threshold of 4.5:1 for normal text. Filled controls therefore use the deeper
step, while the true brand teal is kept everywhere nothing sits on top of it.
In dark mode the relationship inverts: the fill stays bright and the text on it
goes near-black, which reads at 10.47:1.

Both are defined in `frontend/src/styles/theme.css`. The interaction states and
the full motion contract are documented at `/#/states` when the app is running.
