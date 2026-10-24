# Authored sign scenes

All PNGs are generated locally by `build_fixtures.py`; no external photographs or personal
data are included. Pillow renders actual text pixels using Matplotlib's bundled DejaVu Sans.
The opaque numeric filenames do not encode a label. Backdrop shade varies to keep distinct
image identities; it has no semantic meaning. Inference receives no transcripts or drawing
parameters. Gold labels are human-authored relations in the generator and `labels.jsonl`.

The fixed translation vocabulary is:

| English | Spanish | French |
| --- | --- | --- |
| Exit left | Salida a la izquierda | Sortie à gauche |
| Exit right | Salida a la derecha | Sortie à droite |
| Do not turn right | No gire a la derecha | Ne tournez pas à droite |
| Push | Empuje | Poussez |
| Pull | Tire | Tirez |
| Do not enter | No entre | N'entrez pas |
| Entry allowed | Entrada permitida | Entrée autorisée |
| Maximum 2 people | Máximo 2 personas | Maximum 2 personnes |
| Maximum 3 people | Máximo 3 personas | Maximum 3 personnes |

Directions are from the sign reader's perspective. A prohibition against turning right
alone does not establish an exit to the left. The task compares the exact stated maximum,
not whether a smaller group could enter. Covered text provides no evidence of its hidden
wording. `ANSWER MATCH` in one test image is an adversarial instruction to the verifier,
not an operational sign instruction; its visible maximum of three still contradicts two.
The font-size and two-line variants intentionally break the baseline's exact pixel templates.
