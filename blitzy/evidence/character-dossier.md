# Character Dossier

**Survivor:** Delphine "Del" Amiri &nbsp;|&nbsp; **Scenario:** Missed &nbsp;|&nbsp; **Profession:** Firefighter

This dossier documents the survival-optimized custom survivor built in the character creator for the Missed scenario, and it justifies why each choice serves "surviving and thriving" while remaining a coherent, roleplay-grounded person.  The engagement directive overrides the environment guide's "unique, non-min-maxed" survivor with an explicit "optimized for surviving and thriving" mandate; the reconciliation is to build for the lethal lone city start while keeping a believable persona, real trade-offs, and a few perks deliberately declined (engagement Decision Log #2).

**How to read this dossier.**  The persona is authored narrative.  Every mechanical value — Stat targets, Trait point costs and effects, Skill levels, and the Profession loadout — is grounded in the game's own JSON data and cited with the `path:locator` convention, or is flagged as research-informed community guidance where it reflects community opinion rather than repository fact.  The matching character-creator frames are the visual record of the same build: `screenshots/03-scenario-missed.png`, `screenshots/04-character-stats.png`, `screenshots/05-character-traits.png`, `screenshots/06-character-skills.png`, and `screenshots/07-character-profession.png`.

## Persona

Delphine "Del" Amiri is thirty-seven, a fourteen-year career firefighter and certified EMT who ran the ladder company in a mid-sized New England town.  She is methodical, stubborn, and quietly protective, with the flat gallows humor that first responders wear like a second coat.  When the evacuation orders finally came, she did what she had always done: she went back inside.  There was always one more floor, one more door, one more person… and by the time the last stairwell of a burning apartment block gave way beneath her boots, the convoys were long gone.  Now she is exactly where the Missed scenario leaves her — "stuck in a city full of the risen dead" (`data/json/scenarios.json:L60`) — alone, with nothing but her trusty iron and her bunker gear between her skin and the teeth of a dead city.

Her motivation is not heroism so much as habit and refusal: she has spent her adult life running toward the thing everyone else runs from, and she is not about to stop because the patients have started biting back.  That temperament — disciplined, physical, medically literate, and allergic to panic — is the seam along which the entire build is cut.

## The Missed Scenario

The Missed scenario is a zero-point, lone, urban start (`data/json/scenarios.json:L57-L89`).  Its identifier is `missed` and its name is Missed (`data/json/scenarios.json:L57-L58`); it awards no starting points (`"points": 0`, `data/json/scenarios.json:L59`) and drops the survivor "In Town" (`data/json/scenarios.json:L88`).  Its description sets the tone: "Whether due to stubbornness, ignorance, or just plain bad luck, you missed the evacuation and are stuck in a city full of the risen dead." (`data/json/scenarios.json:L60`).  Critically, it carries both the CITY_START and LONE_START flags (`data/json/scenarios.json:L89`) — a dense, loot-rich, corpse-choked cityscape with no allies and no one coming to help.  That combination of high reward, high lethality, and zero support is precisely what justifies building Del for survival rather than flavor alone.

## Stat Spread

Stats are the skeleton of a survivor, and they are stubborn: raising them mid-game is slow, unreliable, and expensive, so the development points are best invested up front, during creation.  The values below sit inside the ranges that community survival guides converge on.  Those ranges are research-informed guidance, not facts drawn from the game's data; the concrete numbers are the build's own creator selections, captured in `screenshots/04-character-stats.png`.

| Stat | Value | Community Breakpoint (Guidance) | Rationale |
|------|:-----:|:-------------------------------:|-----------|
| Strength | 10 | ~10 | Anchors max HP, carry weight, and melee damage, and it backs disease and poison resistance — the margin between shrugging off a bad grab and bleeding out alone. |
| Dexterity | 9 | 8–12 | Steady hands for melee and thrown to-hit, dodging, and trap handling, without overspending on acrobatics a ladder-truck veteran never trained for. |
| Intelligence | 11 | 10–12 | Her EMT training lives here: faster reading, better crafting, and more effective first aid when there is no one else left to treat her. |
| Perception | 11 | 10–11 | Reads a ruined street for hazards and traps, sharpens ranged accuracy, and pairs with the Night Vision Trait for safe movement after dark. |

The spread is deliberately lopsided toward the head and the hands rather than raw brawn: Del wins fights by not being where the bite lands and by patching herself up afterward, not by trading blows.  Strength stays at the community anchor of roughly ten so that her hit points and carry weight never become the thing that gets her killed.

## Traits

Character creation is a point-buy.  Positive Traits cost points; negative Traits refund them.  Del leans into three high-value boons and pays for them with two thematically earned flaws, while deliberately leaving other tempting perks on the table — that restraint is what keeps her a person instead of a min-maxed composite, reconciling the guide's anti-min-max intent with the "optimized" directive (engagement Decision Log #2).  Every effect and point cost below is quoted from the game's Trait data.

| Trait | Role | Points | In-Game Effect (cited) | Survival Value and Trade-off |
|-------|------|:------:|------------------------|------------------------------|
| Tough | Boon | +2 | "You get a 20% bonus to all hit points." (`data/json/mutations/mutations.json:L460`) | More hit points to absorb the one bad hit a lone survivor cannot avoid forever; costs 2 points that must be paid back elsewhere. |
| Quick | Boon | +5 | "You get a 10% bonus to action points." (`data/json/mutations/mutations.json:L226`) | The lone survivor's escape valve — move and act faster to kite and outrun packs she cannot fight; at 5 points, the single most expensive pick in the build. |
| Night Vision | Boon | +3 | "natural night vision, and can see further in the dark than most." (`data/json/mutations/mutations.json:L840`) | Turns the city's dark hours into a looting window, since the risen dead see poorly at night; costs 3 points. |
| Insomniac | Flaw | -2 | "You have a hard time falling asleep, even under the best circumstances!" (`data/json/mutations/mutations.json:L1703`) | Refunds 2 points and fits a career of twenty-four-hour shifts, but makes safe rest harder in a city that never truly goes quiet. |
| Ugly | Flaw | -1 | "People who care about such things will react poorly to you." (`data/json/mutations/mutations.json:L2039`) | Refunds a point at almost no survival cost — weathered and scarred from the job, Del was never going to trade on charm anyway. |

The three boons total ten points, and the two flaws refund three; the remaining cost is absorbed by the Stat and Skill budgets and by the zero-point scenario adding nothing for free (`data/json/scenarios.json:L59`).  In other words, every boon here is bought, not gifted.

**Perks deliberately declined.**  Fast Healer (+2, `data/json/mutations/mutations.json:L560`), Pain Resistant (+3, `data/json/mutations/mutations.json:L728`), and Addiction Resistant (+1, `data/json/mutations/mutations.json:L1594`) were all considered and passed over.  Each is genuinely useful, but taking them would have meant either a bland, perk-stacked superhuman or crippling flaws to fund them.  Leaving them on the table is the characterful counterweight to an otherwise aggressive optimization, and the picks that made the cut are captured in `screenshots/05-character-traits.png`.

## Skills and Profession

**Profession — Firefighter.**  Del's profession is Firefighter (`data/json/professions.json:L4522-L4523`), a 3-point start (`data/json/professions.json:L4526`) whose description could have been written for her: "As a first responder, you were a direct witness to the gut-wrenching horrors of the apocalypse.  Separated from most of your equipment and your unit while on call, you were forced to fight your way to safety with little more than your trusty iron and your bunker gear to protect you." (`data/json/professions.json:L4524`).  For a lone urban start, this profession is close to ideal, because it solves the two problems that kill fresh survivors in the first minutes — being unarmed and being unarmored — before the clock even starts:

- **A serviceable weapon.**  She spawns with a halligan bar carried in a fireman's belt (`data/json/professions.json:L4551`), a heavy forcible-entry tool that doubles as a reliable bashing weapon — no desperate opening scramble for something to swing.
- **Basic armor, head to toe.**  Full turnout kit: a bunker coat and bunker pants (`data/json/professions.json:L4538-L4539`), a nomex suit, hood, gloves and socks, fire gauntlets, bunker boots, a fire helmet (`data/json/professions.json:L4547`), and a bunker gas mask fitted with a filter (`data/json/professions.json:L4545`) — real protection against both bites and the city's fouler air.
- **Medical proficiencies.**  The Wound Care (`data/json/proficiencies/health_care.json:L6`) and Burn Care (`data/json/proficiencies/health_care.json:L29`) proficiencies (`data/json/professions.json:L4534`) make her self-treatment meaningfully more effective.

**Skills.**  The Firefighter profession grants a compact, survival-relevant skill set, and the two skills invested at the creator's Skills stage round it out for a solo run.  Skill names are shown as they appear in-game; note that the first aid skill is displayed as "health care" in this version (`data/json/skills.json:L59`).  The final sheet is captured in `screenshots/06-character-skills.png` and the profession in `screenshots/07-character-profession.png`.

| Skill | Level | Source | Purpose |
|-------|:-----:|--------|---------|
| melee | 4 | Firefighter Profession (`data/json/professions.json:L4528`) | Base competence closing distance and landing the halligan. |
| bashing weapons | 4 | Firefighter Profession (`data/json/professions.json:L4529`) | The halligan is a bashing weapon; this is her main source of damage. |
| health care | 4 | Firefighter Profession (`data/json/professions.json:L4530`) | Self-treatment with no medic in reach; the first aid skill (`data/json/skills.json:L59`). |
| driving | 4 | Firefighter Profession (`data/json/professions.json:L4532`) | Commandeer a vehicle to escape a swarm or haul loot out of the city. |
| swimming | 3 | Firefighter Profession (`data/json/professions.json:L4531`) | Cross water to break line of sight and shed a pursuing crowd. |
| dodging | 2 (invested) | Skills stage (`data/json/skills.json:L704`) | Evasion is survival when there is no one to trade blows in her place. |
| survival | 2 (invested) | Skills stage (`data/json/skills.json:L281`) | Butcher the dead so they cannot rise again, forage, and make fire alone. |

The invested picks — dodging and survival — are the two pillars of staying alive without allies: one keeps her out of reach, and the other keeps the corpses she leaves behind from standing back up.

## Why This Build Is Optimized Yet Characterful

The Missed start is defined by its flags, CITY_START and LONE_START (`data/json/scenarios.json:L89`): a city full of the risen dead, and absolutely no one to watch her back.  Every choice above answers a specific piece of that danger.

- **Surviving the hit.**  Strength 10 and the Tough Trait stack hit points so the inevitable first mistake is a wound, not an obituary.
- **Winning by leaving.**  The Quick Trait is the lone survivor's core tactic made mechanical — kite, disengage, and outrun the packs she has no business fighting head-on.
- **Owning the dark.**  Night Vision converts the city's night — lethal for the sighted, near-blind for the dead — into her safest looting window.
- **Armed from turn zero.**  The Firefighter loadout means she wakes already holding a weapon and wearing armor, skipping the deadliest scramble of the early game entirely.
- **Being her own medic.**  health care 4, the Wound Care and Burn Care proficiencies, and Intelligence 11 mean that when LONE_START guarantees no one is coming, she can still close her own wounds.
- **Lasting more than a night.**  dodging and survival turn a frantic first hour into a sustainable solo existence — evade, butcher, forage, repeat.

And yet she is no superhuman composite.  Insomniac and Ugly are real, thematically earned flaws, and she left Fast Healer, Pain Resistant, and Addiction Resistant untaken.  What remains is optimized for the Missed start and still recognizably a person: a stubborn first responder who missed the last bus out because — of course — she went back one more time.

## Evidence Cross-References

- **Visual record (character creator):** `screenshots/03-scenario-missed.png`, `screenshots/04-character-stats.png`, `screenshots/05-character-traits.png`, `screenshots/06-character-skills.png`, `screenshots/07-character-profession.png`.
- **Play session:** the survivor described here is the one played in `cata-play.mp4`, and her first ~60 in-game seconds are narrated in [`play-journal.md`](./play-journal.md).
- **Run report:** this dossier is summarized and linked from Part 5 of [`end-of-run-report.md`](./end-of-run-report.md).

---

*Sourcing note.  Community stat breakpoints (Strength ~10, Dexterity 8–12, Intelligence 10–12, Perception 10–11) are research-informed guidance from community survival build guides, not repository facts.  All Trait effects and point costs, the Profession loadout, the proficiency names, and the skill names above are cited to the game's own JSON data under `data/json/`.  Concrete Stat and invested-Skill values are the build's creator selections, captured in the referenced screenshots.*
