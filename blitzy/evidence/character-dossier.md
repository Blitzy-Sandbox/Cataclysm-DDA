# Character Dossier

**Survivor:** Marcus Reyes &nbsp;|&nbsp; **Scenario:** Missed &nbsp;|&nbsp; **Profession:** Baseball Player

This dossier documents the survival-optimized custom survivor built in the character creator for the Missed scenario, and it justifies why each choice serves "surviving and thriving" while remaining a coherent, roleplay-grounded person.  The engagement directive overrides the environment guide's "unique, non-min-maxed" survivor with an explicit "optimized for surviving and thriving" mandate; the reconciliation is to build for the lethal lone city start while keeping a believable persona and picks that cohere with a real backstory (engagement Decision Log #2).

**How to read this dossier.**  The persona is authored narrative.  Every mechanical value — the Stat values, Trait effects and point values, Skill levels, and the Profession loadout — is grounded in the game's own JSON data and cited with the `path:locator` convention, or is flagged as research-informed community guidance where it reflects community opinion rather than repository fact.  The matching character-creator frames are the visual record of the same build and are captured in `screenshots/03-scenario-missed.png`, `screenshots/04-character-stats.png`, `screenshots/05-character-traits.png`, `screenshots/06-character-skills.png`, and `screenshots/07-character-profession.png`; the spawned survivor is captured in `screenshots/08-spawn-T0.png`.

## Persona

Marcus Reyes is twenty-five, and until the world ended he was the pride of a mid-sized New England town's amateur baseball league — a fast, big-armed outfielder who could run down anything hit into the gap and throw a runner out at the plate from the warning track.  He was never the smart one in the clubhouse; he was the one who showed up early, ran the extra sprints, and stayed late in the cage.  When the evacuation sirens went, Marcus was where he always was — at the field — and by the time he understood what "risen dead" actually meant, the convoys had gone and the bleachers were full of things that used to cheer.  The game's own Profession story says it plainly: "You played with the local team.  You're the only one left, but now you can use your trusty bat for another purpose.  Home run!" (`data/json/professions.json:L1174`).

His motivation is simple and stubborn, the way athletes are stubborn: keep moving, read the play, and put the bat on anything that comes at him.  He is not a tactician and he knows it — but he is fast, he is durable, and he has spent his whole life training the exact reflexes that keep a lone survivor alive in a city full of the dead.  That temperament — physical, quick, and light on book-learning — is the seam along which the entire build is cut.

## The Missed Scenario

The Missed scenario is a zero-point, lone, urban start (`data/json/scenarios.json:L57-L89`).  Its identifier is `missed` and its name is Missed (`data/json/scenarios.json:L57-L58`); it awards no starting points (`"points": 0`, `data/json/scenarios.json:L59`) and drops the survivor "In Town" (`data/json/scenarios.json:L88`).  Its description sets the tone: "Whether due to stubbornness, ignorance, or just plain bad luck, you missed the evacuation and are stuck in a city full of the risen dead." (`data/json/scenarios.json:L60`).  Critically, it carries both the CITY_START and LONE_START flags (`data/json/scenarios.json:L89`) — a dense, loot-rich, corpse-choked cityscape with no allies and no one coming to help.  Marcus spawned into a hardware store, one of the scenario's allowed city locations (`data/json/scenarios.json:L74`, captured in `screenshots/08-spawn-T0.png`).  That combination of high reward, high lethality, and zero support is precisely what justifies building Marcus for survival rather than flavor alone.

## Stat Spread

Stats are the skeleton of a survivor, and they are stubborn: raising them mid-game is slow, unreliable, and expensive, so the values are best set up front, during creation.  This world's creator ran with a freeform point pool — the Stats screen shows no running point counter — so the spread below reflects deliberate design choices rather than a forced budget.  The values still sit inside the ranges that community survival guides converge on; those ranges are research-informed guidance, not facts drawn from the game's data.  The concrete numbers are the build's own creator selections, captured in `screenshots/04-character-stats.png`.

| Stat | Value | Community Breakpoint (Guidance) | Rationale |
|------|:-----:|:-------------------------------:|-----------|
| Strength | 10 | ~10 | Anchors max hit points, carry weight, and melee damage — the muscle behind a full-power bat swing and the margin that turns a bad grab into a survivable wound rather than an obituary. |
| Dexterity | 11 | 8–12 | The athlete's signature stat and the highest in the build ("top 10%", per the creator readout): it drives melee and thrown to-hit, dodging, and trap handling — Marcus wins by not being where the bite lands. |
| Intelligence | 8 | 10–12 | Set at the "average human" mark as the honest trade-off of a jock persona: Marcus reads a pitch, not a chemistry text, and the build deliberately declines to pretend otherwise. |
| Perception | 10 | 10–11 | Reads a ruined street for hazards and traps, sharpens ranged and thrown accuracy, and pairs with the Night Vision Trait for safer movement after dark. |

The spread is deliberately weighted toward the body and the hands rather than the head: Marcus is an elite athlete, not a scholar, and the below-average Intelligence is the characterful cost that keeps him from being a bland, maxed-out composite.  Strength sits at the community anchor of ten so that his hit points and carry weight never become the thing that gets him killed, and Dexterity leads the build because dodging and accurate swings are how a lone survivor outlasts a crowd.

## Traits

The four Traits below are all positive boons, shown green-selected on the creator's Traits screen (`screenshots/05-character-traits.png`), with no flaws taken.  Because the world uses a freeform point pool, the build is free to take four pure survival boons without funding them through drawbacks — the maximally survival-optimized reading of the "optimized for surviving and thriving" directive (engagement Decision Log #2).  Each Trait's point value below is the cost the game's data assigns it, quoted as a measure of its strength; every effect is quoted from the game's Trait data.

| Trait | Point Value (JSON) | In-Game Effect (cited) | Survival Value |
|-------|:------------------:|------------------------|----------------|
| Quick | 5 (`data/json/mutations/mutations.json:L228`) | "You're just generally quick!  You get a 10% bonus to action points." (`data/json/mutations/mutations.json:L226`) | The lone survivor's escape valve — act and move faster to kite and outrun packs Marcus cannot fight head-on; at 5 points it is the strongest pick in the build. |
| Night Vision | 3 (`data/json/mutations/mutations.json:L858`) | "You possess natural night vision, and can see further in the dark than most." (`data/json/mutations/mutations.json:L840`) | Extra sight range in the dark turns the city's night hours into a safer looting window for a lone survivor. |
| Fleet-Footed | 2 (`data/json/mutations/mutations.json:L262`) | "You can move more quickly than most, resulting in a 15% speed bonus on sure footing." (`data/json/mutations/mutations.json:L258`) | Stacks with Quick for raw movement speed on solid ground — the difference between reaching the next doorway and being surrounded. |
| Tough | 2 (`data/json/mutations/mutations.json:L463`) | "It takes a lot to bring you down!  You get a 20% bonus to all hit points." (`data/json/mutations/mutations.json:L460`) | More hit points to absorb the one bad hit a lone survivor cannot avoid forever. |

The theme is coherent and singular: **outlast the crowd by moving faster than it and taking a hit better than it expects.**  Quick and Fleet-Footed together make Marcus genuinely hard to corner; Tough gives him the durability to trade a mistake for a wound instead of a death; and Night Vision hands him the one time of day when a lone survivor can move through a city of the blind dead with the advantage.  No flaws were taken — a deliberate, honest reflection of the freeform build, not an invented drawback.

## Skills and Profession

**Profession — Baseball Player.**  Marcus's profession is Baseball Player (`data/json/professions.json:L1172-L1173`), a 2-point start (`data/json/professions.json:L1176`) whose loadout solves the two problems that kill fresh survivors in the first minutes — being unarmed and being unarmored — before the clock even starts.  The full loadout is captured in `screenshots/07-character-profession.png`:

- **A serviceable weapon from turn zero.**  He spawns wielding a baseball bat (`data/json/professions.json:L1197`), a fast, reliable bashing weapon he already knows how to swing — no desperate opening scramble for something to fight with.
- **Light protection, head to toe.**  A baseball helmet (`data/json/professions.json:L1192`) plus a light jacket, t-shirt, jeans, socks, and cleats — modest armor that still beats waking up defenseless in a city of the dead.
- **Athletic proficiencies.**  Athlete's Form (`data/json/proficiencies/athletics.json:L15`), Mace Familiarity (`data/json/proficiencies/melee_weapons.json:L744`), and Mace Proficiency (`data/json/proficiencies/melee_weapons.json:L757`) make his bat work meaningfully more effective — the bat is a mace-class weapon, and Marcus swings it like a pro.

**Skills.**  The Baseball Player profession grants a compact, athletic skill set, and the two skills invested at the creator's Skills stage turn a ballplayer into a survivor.  Skill names are shown as they appear in-game; note that in this version the athletic skill is displayed as "athletics" (`data/json/skills.json:L163`) and the first-aid skill is displayed as "health care" (`data/json/skills.json:L59`).  The final sheet is captured in `screenshots/06-character-skills.png`, where profession skills appear in the creator's "base + profession" form (for example, "melee (0 + 4)").

| Skill | Level | Source | Purpose |
|-------|:-----:|--------|---------|
| melee | 4 | Baseball Player Profession (`data/json/professions.json:L1178`; skill `data/json/skills.json:L595`) | Base competence closing distance and landing the bat. |
| bashing weapons | 4 | Baseball Player Profession (`data/json/professions.json:L1179`; skill `data/json/skills.json:L638`) | The bat is a bashing weapon; this is Marcus's main source of damage. |
| throwing | 4 | Baseball Player Profession (`data/json/professions.json:L1180`; skill `data/json/skills.json:L555`) | An outfielder's arm — hurl a rock, a bottle, or a spare bat to soften a target before it closes. |
| athletics | 4 | Baseball Player Profession (`data/json/professions.json:L1181`; skill `data/json/skills.json:L163`) | Athletic conditioning: better cardio and stamina to run, climb, and keep swinging. |
| dodging | 3 (invested) | Skills stage (`data/json/skills.json:L704`) | Evasion is survival when there is no one to trade blows in his place; it pairs with Dexterity 11 to keep Marcus untouched. |
| survival | 3 (invested) | Skills stage (`data/json/skills.json:L281`) | Butcher the dead so they cannot rise again, forage, and make fire alone. |
| health care | 1 | Background, shown "0 + 1" (`data/json/skills.json:L59`) | Self-treatment with no medic in reach — enough to close a wound and keep moving. |
| vehicles | 2 | Background (`screenshots/06-character-skills.png`, shown "0 + 2") | Commandeer a vehicle to escape a swarm or haul loot out of the city. |

A short set of background choices — Driving License, Simple Home Cooking, Computer Literate, Social Skills, High School Graduate, and Mundane Survival — rounds out the sheet with the assorted "+1" knowledge skills (applied science, electronics, fabrication, food handling, computers, mechanics, and social) visible in `screenshots/06-character-skills.png`.  The two invested picks — dodging and survival — are the pillars of staying alive without allies: one keeps Marcus out of reach, and the other keeps the corpses he leaves behind from standing back up.

## Why This Build Is Optimized Yet Characterful

The Missed start is defined by its flags, CITY_START and LONE_START (`data/json/scenarios.json:L89`): a city full of the risen dead, and absolutely no one to watch his back.  Every choice above answers a specific piece of that danger.

- **Winning by leaving.**  Quick and Fleet-Footed together are the lone survivor's core tactic made mechanical — kite, disengage, and outrun the packs Marcus has no business fighting head-on.
- **Surviving the hit.**  Strength 10 and the Tough Trait stack hit points so the inevitable first mistake is a wound, not an obituary.
- **Owning the dark.**  Night Vision converts the city's night — lethal for the sighted, near-blind for the dead — into his safest looting window.
- **Armed from turn zero.**  The Baseball Player loadout means he wakes already holding a weapon and wearing a helmet, skipping the deadliest scramble of the early game entirely.
- **A pro's swing.**  melee, bashing weapons, and throwing at 4, backed by the Mace Familiarity and Mace Proficiency proficiencies, mean the bat lands hard and often — offense that fits the persona exactly.
- **Lasting more than a night.**  dodging, survival, and health care turn a frantic first hour into a sustainable solo existence — evade, butcher, forage, patch up, repeat.

And yet Marcus is no superhuman composite.  His Intelligence sits at a plain, below-guidance 8 — the honest cost of a jock who trained his body instead of his mind — and he took no perks beyond the four that serve the singular "move fast, hit hard, take a hit" plan.  What remains is optimized for the Missed start and still recognizably a person: the last ballplayer of a dead town, running the bases of a ruined city with a bat and a stubborn refusal to strike out.

## Evidence Cross-References

- **Visual record (character creator):** `screenshots/03-scenario-missed.png`, `screenshots/04-character-stats.png`, `screenshots/05-character-traits.png`, `screenshots/06-character-skills.png`, `screenshots/07-character-profession.png`, and the spawned survivor in `screenshots/08-spawn-T0.png`.
- **Play session:** the survivor described here is the one played in `cata-play.mp4`. His first ~60 in-game seconds are narrated in the play journal (`play-journal.md`), authored at the final gate.
- **Run report:** this dossier is summarized in Part 5 of the end-of-run report (`end-of-run-report.md`), authored at the final gate.

---

*Sourcing note.  Community stat breakpoints (Strength ~10, Dexterity 8–12, Intelligence 10–12, Perception 10–11) are research-informed guidance from community survival build guides, not repository facts; this build deliberately sets Intelligence below that guidance range as a persona-driven trade-off.  All Trait effects and point values, the Profession loadout, the proficiency names, and the skill display names above are cited to the game's own JSON data under `data/json/`.  Concrete Stat, Trait, and Skill selections are the build's creator choices, captured in the referenced screenshots.  The survivor's name (Marcus Reyes) and age are authored persona details entered in the character creator during the recorded play session (per the persona latitude in AAP §0.5.2); the mechanical frames `04`-`07` were captured while stats, traits, skills, and profession were being selected — before the name was finalized — and therefore show the game's default "--- RANDOM NAME ---" placeholder in the Name field rather than the chosen name.*
