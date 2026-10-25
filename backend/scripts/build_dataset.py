"""Deterministically build the bundled RAG evaluation dataset (rag-eval-v1).

The dataset describes *fictional* entities so that no language model can answer
from prior knowledge: the only way to answer correctly is to retrieve the right
passage. Each entity has two look-alike "decoy" entities whose passages share
vocabulary but carry different facts, which makes retrieval depth, ranking and
reranking genuinely matter.

Run:  python scripts/build_dataset.py
Output: data/rag_eval.json  (byte-identical across runs for a given SEED)
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 42
VERSION = "rag-eval-v1"
OUT = Path(__file__).resolve().parent.parent / "data" / "rag_eval.json"

# (gold name, decoy names, domain filler sentences)
ENTITIES = [
    ("Velmora Research Station", ["Velmara Research Station", "Velmora Field Station"], "polar"),
    ("Kestrel Bay Observatory", ["Kestrel Point Observatory", "Kestrel Bay Planetarium"], "astronomy"),
    ("Orinth Biolabs", ["Orinth Genomics", "Orinda Biolabs"], "biotech"),
    ("Thalassa Deep Probe", ["Thalassa Surface Probe", "Thalara Deep Probe"], "space"),
    ("Marrowgate Public Library", ["Marrowgate University Library", "Marrowfield Public Library"], "library"),
    ("Cindral River Dam", ["Cindral Lake Dam", "Cindrel River Dam"], "infrastructure"),
    ("Halvren Robotics Institute", ["Halvren Aerospace Institute", "Halvrin Robotics Institute"], "robotics"),
    ("Solvane Wind Farm", ["Solvane Solar Farm", "Solvany Wind Farm"], "energy"),
]

FILLER = {
    "polar": [
        "{name} operates year-round despite long periods of darkness.",
        "Supply flights to {name} are scheduled around seasonal sea ice.",
        "Visiting scientists at {name} study glaciers, sea ice and atmospheric chemistry.",
        "The main hall of {name} was renovated to improve insulation.",
    ],
    "astronomy": [
        "{name} hosts public viewing nights during clear winter evenings.",
        "The dome of {name} houses a large reflecting telescope.",
        "Researchers at {name} publish surveys of variable stars.",
        "Light pollution near {name} is monitored by a regional council.",
    ],
    "biotech": [
        "{name} develops enzyme assays for industrial partners.",
        "Laboratories at {name} follow strict biosafety procedures.",
        "{name} licenses several of its sequencing tools to universities.",
        "The campus of {name} includes greenhouse facilities.",
    ],
    "space": [
        "The {name} carries spectrometers and a magnetometer.",
        "Telemetry from the {name} is relayed through deep space antennas.",
        "Engineers designed the {name} to survive extreme pressure.",
        "Mission planners for the {name} publish quarterly status reports.",
    ],
    "library": [
        "{name} lends rare manuscripts to accredited researchers.",
        "The reading rooms of {name} are open seven days a week.",
        "{name} runs a digitisation programme for historic newspapers.",
        "Volunteers at {name} organise weekly reading circles.",
    ],
    "infrastructure": [
        "The {name} regulates seasonal flooding downstream.",
        "Turbines inside the {name} generate hydroelectric power.",
        "Inspections of the {name} are carried out every spring.",
        "A walking trail runs along the crest of the {name}.",
    ],
    "robotics": [
        "{name} builds autonomous inspection robots.",
        "Students at {name} compete in international robotics challenges.",
        "{name} partners with manufacturers on warehouse automation.",
        "The test arena at {name} simulates rough outdoor terrain.",
    ],
    "energy": [
        "{name} feeds electricity into the regional grid.",
        "Maintenance crews visit {name} every month.",
        "Output from {name} peaks during the windy autumn months.",
        "Environmental surveys around {name} track local bird populations.",
    ],
}

# Each attribute: sentence templates (gold/decoy passages pick one), and question
# templates. "direct" questions share the key verb with template 0; "paraphrase"
# questions use wording that matches template 1 — so lexical retrieval is easy
# for some questions and hard for others.
ATTRIBUTES = {
    "year": {
        "answer_type": "year",
        "sentences": [
            "{name} was formally established in {value}.",
            "{name} first opened its doors to staff in {value}.",
        ],
        "questions": {
            "direct": "In what year was {name} established?",
            "paraphrase": "When did {name} first open its doors?",
        },
    },
    "leader": {
        "answer_type": "person",
        "sentences": [
            "{name} is currently led by director {value}.",
            "Day-to-day management of {name} is headed by {value}.",
        ],
        "questions": {
            "direct": "Who is the director that leads {name}?",
            "paraphrase": "Who heads the day-to-day management of {name}?",
        },
    },
    "location": {
        "answer_type": "place",
        "sentences": [
            "{name} is located near the town of {value}.",
            "The nearest settlement to {name} is {value}.",
        ],
        "questions": {
            "direct": "Near which town is {name} located?",
            "paraphrase": "What is the nearest settlement to {name}?",
        },
    },
    "staff": {
        "answer_type": "count",
        "sentences": [
            "{name} employs {value} full-time staff.",
            "A workforce of {value} people keeps {name} running.",
        ],
        "questions": {
            "direct": "How many full-time staff does {name} employ?",
            "paraphrase": "How large is the workforce that keeps {name} running?",
        },
    },
    "project": {
        "answer_type": "project",
        "sentences": [
            "The flagship programme at {name} is the {value} initiative.",
            "Most funding at {name} goes to the {value} initiative.",
        ],
        "questions": {
            "direct": "What is the flagship programme at {name}?",
            "paraphrase": "Which initiative receives most of the funding at {name}?",
        },
    },
}

FIRST = ["Hana", "Tomas", "Ilse", "Ruben", "Mira", "Oskar", "Leda", "Pavel", "Ines", "Dario",
         "Sanne", "Emil", "Yara", "Kasimir", "Noor", "Felix", "Ada", "Bruno", "Clio", "Jonas",
         "Vera", "Anton", "Liv", "Matteo", "Runa", "Teodor"]
LAST = ["Orlov", "Brenner", "Castell", "Duvall", "Ekberg", "Farrow", "Galvez", "Hollis", "Ivers",
        "Jansky", "Korvan", "Lindqvist", "Moreau", "Navarro", "Oyelaran", "Petrakis", "Quill",
        "Rasmund", "Sorensen", "Tavish", "Ulrich", "Varga", "Wexley", "Yilmaz", "Zelenka", "Abara"]
PLACES = ["Tesk Harbour", "Brimvale", "Ostrava Point", "Kelmwick", "Durnholt", "Sablecross",
          "Frostmere", "Allerby", "Quarnes", "Wyndle", "Pellorin", "Haskett", "Rookmoor",
          "Ebbington", "Varnholm", "Glenmarsh", "Toller Cove", "Ashgrove", "Marlin Sound",
          "Corrabeg", "Nethercombe", "Islay Ford", "Brackwater", "Selby Rise", "Ostwick", "Pennaby"]
PROJECTS = ["Aurora Lattice", "Blue Meridian", "Cobalt Arc", "Deep Lantern", "Ember Tide",
            "Frost Signal", "Granite Echo", "Helix Harbor", "Iron Bloom", "Jade Compass",
            "Kite Horizon", "Lumen Drift", "Mosaic Vale", "North Quarry", "Opal Current",
            "Prism Hollow", "Quiet Atlas", "Raven Thread", "Silver Furrow", "Tidal Ledger",
            "Umber Spire", "Violet Gauge", "Willow Circuit", "Zenith Loom", "Amber Relay", "Basalt Choir"]

BACKGROUND = [
    "Research stations, observatories and laboratories are often established decades before they reach full capacity.",
    "Many institutions publish the number of full-time staff they employ in annual reports.",
    "A director usually leads the day-to-day management of a scientific facility.",
    "Flagship programmes often receive most of the funding at a research institute.",
    "The nearest settlement to a remote facility is frequently a small harbour town.",
    "Historians debate when facilities formally opened their doors versus when construction finished.",
    "Workforce figures for infrastructure projects include contractors and permanent staff.",
    "Funding initiatives at public institutions are reviewed every few years.",
    "Many observatories are located near towns with low light pollution.",
    "Libraries and archives employ conservators, archivists and full-time reference staff.",
    "Wind farms and dams are typically located far from the nearest town.",
    "Deep space probes are managed by mission directors rather than facility directors.",
    "Robotics institutes often run several flagship programmes at once.",
    "Biotechnology companies frequently change directors after acquisitions.",
    "The year a facility was established is not always the year it first opened.",
    "Polar research stations rely on a small workforce during the winter months.",
    "Hydroelectric dams employ engineers to keep the turbines running.",
    "Public libraries often name their flagship initiatives after local landmarks.",
    "Many research facilities are formally established by government charter.",
    "Annual reports describe who leads each facility and how many staff it employs.",
]


def main() -> None:
    rng = random.Random(SEED)

    n_variants = len(ENTITIES) * 3
    years = [str(y) for y in rng.sample(range(1952, 2019), n_variants)]
    people = rng.sample([f"{f} {l}" for f in FIRST for l in LAST], n_variants)
    places = rng.sample(PLACES, n_variants)
    counts = [str(c) for c in rng.sample(range(118, 990), n_variants)]
    projects = rng.sample(PROJECTS, n_variants)
    pools = {"year": years, "leader": people, "location": places, "staff": counts, "project": projects}

    documents: list[dict] = []
    questions: list[dict] = []
    vocab: dict[str, set[str]] = {a["answer_type"]: set() for a in ATTRIBUTES.values()}

    def add_doc(text: str, meta: dict) -> str:
        doc_id = f"d{len(documents) + 1:03d}"
        documents.append({"id": doc_id, "text": text, "metadata": meta})
        return doc_id

    variant_idx = 0
    for gold_name, decoys, domain in ENTITIES:
        names = [gold_name, *decoys]
        facts: dict[str, dict[str, str]] = {}
        for name in names:
            facts[name] = {attr: pools[attr][variant_idx] for attr in ATTRIBUTES}
            variant_idx += 1

        entity_docs: dict[str, dict[str, str]] = {n: {} for n in names}
        for name in names:
            for attr, spec in ATTRIBUTES.items():
                value = facts[name][attr]
                vocab[spec["answer_type"]].add(value)
                template = spec["sentences"][rng.randrange(2)]
                fillers = rng.sample(FILLER[domain], 2)
                parts = [template.format(name=name, value=value)] + [f.format(name=name) for f in fillers]
                rng.shuffle(parts)
                text = " ".join(p[0].upper() + p[1:] for p in parts)
                entity_docs[name][attr] = add_doc(
                    text, {"entity": name, "attribute": attr, "is_decoy": name != gold_name}
                )

        for attr, spec in ATTRIBUTES.items():
            style = "paraphrase" if rng.random() < 0.45 else "direct"
            gold_doc = entity_docs[gold_name][attr]
            context_ids = [gold_doc] + [entity_docs[d][attr] for d in decoys] + [
                entity_docs[gold_name][a] for a in ATTRIBUTES if a != attr
            ]
            doc_text = {d["id"]: d["text"] for d in documents}
            questions.append(
                {
                    "id": f"q{len(questions) + 1:03d}",
                    "question": spec["questions"][style].format(name=gold_name),
                    "context": [doc_text[c] for c in context_ids],
                    "expected_answer": facts[gold_name][attr],
                    "metadata": {
                        "entity": gold_name,
                        "attribute": attr,
                        "answer_type": spec["answer_type"],
                        "question_style": style,
                        "gold_doc_id": gold_doc,
                        "context_ids": context_ids,
                    },
                }
            )

    for text in BACKGROUND:
        add_doc(text, {"entity": None, "attribute": None, "is_decoy": False, "background": True})

    dataset = {
        "name": "RAG Retrieval Evaluation (synthetic)",
        "version": VERSION,
        "seed": SEED,
        "description": (
            "Deterministic synthetic QA benchmark over fictional entities. Each gold entity has two "
            "look-alike decoy entities with conflicting facts, so answering requires retrieving the "
            "correct passage. Questions are either 'direct' (share wording with the gold passage) or "
            "'paraphrase' (share wording with a template that decoys may also use)."
        ),
        "answer_vocabulary": {k: sorted(v) for k, v in vocab.items()},
        "documents": documents,
        "questions": questions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} — {len(questions)} questions, {len(documents)} documents")


if __name__ == "__main__":
    main()
