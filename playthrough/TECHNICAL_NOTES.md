# Technical notes

The engineering record for the playthrough capture. Everything that is a
decision about the machinery, a measurement taken from this checkout, or an
observation about how the pipeline behaves belongs here — and nowhere else.

`playthrough/dossier.md` is Delphine Ouellette's own account of herself,
written before the first keystroke, and it is hers entirely: no point
accounting, no option values, no source citations, no notes about how any of
it was arranged. She would not write a page like that and does not think
about herself in those terms. Keeping the two apart is what makes the
in-character record worth reading as a record rather than as a commentary,
so the mechanical half of the character lives on this page instead.

Every value below was read out of this checkout at the stated location. Where
a number is quoted, it is the shipped value in this tree and not a value
remembered from another version.

---

## The pre-play character build

Set down in advance, because the exact shape of the character is a thing
that has to be decided and written down BEFORE the first day is played
rather than described afterwards from memory. Every value is traceable to
this checkout, and every choice is traceable to a sentence Delphine already
wrote in the dossier — quoted here so the link between the human account and
the mechanical one can be checked in both directions.

**Creation path.** The custom creator — the entry labelled `Custom Character`
[src/main_menu.cpp:476], whose own hint is "Allows you to fully customize
points pool, scenario, and character's profession, stats, traits, skills and
other parameters" [src/main_menu.cpp:486]. Not `Preset Character`
[src/main_menu.cpp:477], not `Random Character` [src/main_menu.cpp:478], and
neither "Play Now!" entry [src/main_menu.cpp:481-482]. The points are spent in
**multi pool**, which the world setting `CHARACTER_POINT_POOLS = any` keeps
selectable [src/newcharacter.cpp:438-446]; under the shipped `story_teller`
value the pool tab is informational and read-only and there is no point-buy at
all [src/newcharacter.cpp:462-467].

**Scenario.** *Missed* — id `missed`, **0 points**, "you missed the evacuation
and are stuck in a city full of the risen dead"
[data/json/scenarios.json:55-61]. She missed it out of stubbornness and live
boilers, which is the account under "How I missed the buses". It costs nothing,
so it is not a trade-off she has to pay for.

**Profession.** *Mechanical Engineer* — id `engineer_mech`, **2 points**,
granting **mechanics 5** and the proficiencies `prof_basic_engines`,
`prof_high_pressure_systems` and `prof_pneumatics`
[data/json/professions.json:1086]. Twenty-two years on the steam side of a
paper mill is exactly that profession and exactly those three proficiencies.
Its kit is also what the dossier is describing when she inventories herself:
dress shirt, jeans, socks, steel-toed boots, a **wristwatch**, a charged
smartphone carrying a mechanics textbook, and a full wallet. She calls the
dress shirt a work shirt, because that is what a woman on shift calls the
shirt she works in; it is the same garment.

The wristwatch is not a flourish. `display::time_string()` returns an exact
`to_string_time_of_day()` reading only while the survivor `has_watch()`, and
otherwise a coarse phrase or `"???"` [src/display.cpp:207-219, :159-185], and
every frame's on-screen duration in the finished film IS the delta between two
consecutive sidebar clock readings. A survivor without a timepiece would
therefore produce a film with no derivable pacing at all. Acquiring one
legitimately was a creation decision, and the profession that fits her history
happens to carry one.

**Stats.** The pool is `4 * 8 + INITIAL_STAT_POINTS`, and the shipped value of
`INITIAL_STAT_POINTS` is 6, so 38 points
[src/newcharacter.cpp:250-253]. Each stat costs its own value plus one more for
every point above 12 [src/newcharacter.cpp:255-263; `HIGH_STAT` = 12,
src/player_difficulty.h:14]. The descriptors quoted below are the creator's own
words for those numbers [`stat_level_description`,
src/newcharacter.cpp:1573-1606]:

* **STR 10** — costs 10, reads "above average". "I am strong for a woman my
  age". She can still lift; Bad Back is what she cannot do with it.
* **DEX 7** — costs 7, reads "below average". "I have never been quick."
  Deliberately below the baseline of 8, which the creator calls "average
  human": this is the stat she pays with.
* **INT 12** — costs 12, reads "top 10%". "a head full of machines", and the
  reason she can name what is wrong with a machine "before the cover is off".
* **PER 9** — costs 9, reads "above average". "My eyes are still good enough to
  read a gauge from across a bay". Her hearing is bought separately, below.

Total 38 of 38, nothing left over and nothing borrowed.

**Traits.** The trait pool is the shipped value of `INITIAL_TRAIT_POINTS`,
which is 0 [src/newcharacter.cpp:266-267], so every advantage here is paid for
with a liability — the arrangement she states as "You buy the one with the
other." A positive value below is a cost; a negative value is a liability that
hands points back. All five are declared in data/json/mutations/mutations.json:

* **Good Hearing** (`GOODHEARING`, +1, line 420) — "hearing is better than
  average", a quarter again on the hearing multiplier. "My ears are the best
  thing I own", and in five days they have already been how she knows which
  rooms have something in them.
* **Fast Healer** (`FASTHEALER`, +2, line 554) — "wounds and broken limbs heal
  quicker than usual". "My hands are steady and they recover fast".
* **Bad Back** (`BADBACK`, −3, line 386) — "maximum weight carried is reduced
  by 35%". "I can still lift. I cannot carry." This is the one she says will
  "decide what I pick up and what I walk away from, all day, every day", and it
  is the single choice that will shape the play most.
* **Insomniac** (`INSOMNIA`, −2, line 1701) — "a hard time falling asleep, even
  under the best circumstances". "I do not sleep. Not properly". It is also
  what makes the end of the first day genuinely uncertain rather than a
  formality.
* **Slow Footed** (`SLOWRUNNER`, −3, line 281) — "a 15% speed penalty on flat
  ground". She is "slow for anybody's". With DEX 7 as well, running away is not
  a plan available to her.

That is 3 points of boon against 8 points of liability, a net −5, and in multi
pool a trait surplus is spendable on skills but never upward on stats
[src/newcharacter.cpp:325-343].

**Hobbies.** Charged against the skill pool on the same sign convention, all
five declared in data/json/hobbies.json:

* **Nicotine Dependence** (`smoker`, −1, line 80) — a nicotine addiction at
  intensity 10, and "nothing in my shirt pocket but the pocket". "One hour
  without and I am mean".
* **First Aid** (`redcross`, +1, line 1144) — firstaid 2. "The mill sent us to
  the first-aid refresher every spring and I paid attention every spring".
* **Fishing** (`fishing`, +1, line 1212) — survival 2, swimming 1, and the
  `OUTDOORSMAN` trait free with it (line 1815 of the mutations file: it eases
  the misery of being wet). Her father taught her "to fish the river in the
  spring when the water is still too cold to be pleasant about it."
* **Machinist (Beginner)** (`machinist_beginner`, +2, line 1203) —
  fabrication 3, mechanics 1. "the part you want is not in the crib, so you
  build one out of whatever is on the bench."
* **Driving License** (`driving_license`, 0, line 15) — driving 2, mechanics 1.
  "I would put on the boots, drive down through a dead town, and fix it".

**Levels bought outright.** The skill pool is the shipped value of
`INITIAL_SKILL_POINTS`, which is 2 [src/newcharacter.cpp:288-290]. In every
mode except the freeform one, the first increment on an untouched skill moves
it from 0 to **2** for a single point [src/newcharacter.cpp:3845-3862; cost
table at src/newcharacter.cpp:303], so both points go on the two things that
twenty-two years of swinging wrenches and pry bars at seized machinery would
actually have taught her: **melee 2** (1 point) and **bashing 2** (1 point).
It is also what she will be holding when the first thing comes at her, since
"when a plan runs out and the thing in front of me is fast, I am the wrong
person to be standing there."

**What she therefore starts with.** Profession levels are added on top of what
was bought [src/newcharacter.cpp:1105-1108] and hobby levels raise a skill only
where they exceed what is already there [src/newcharacter.cpp:1042-1053], so
the sheet reads: **mechanics 5, fabrication 3, bashing 2, driving 2,
firstaid 2, melee 2, survival 2, swimming 1**.

**The arithmetic, so it can be checked rather than taken on trust.** Pools:
38 stat + 0 trait + 2 skill = 40. Spent: 38 on stats, −5 on traits, and 7
against the skill pool (scenario 0 + profession 2 + hobbies 3 + bought
levels 2) = 40. Under multi-pool accounting — where a stat surplus can fund
traits, a stat-plus-trait surplus can fund skills, and nothing ever flows the
other way [src/newcharacter.cpp:325-343] — the three remainders come out at
exactly 0, 0 and 0. Nothing is left unspent and nothing is overdrawn.

**Distinctive rather than optimal, and deliberately not average.** Three
liabilities worth eight points against two boons worth three; one stat below
the average human and one in the top tenth. She is a specialist with a wrecked
back who cannot carry a load, cannot run, and cannot reliably sleep, and who in
exchange hears what is in the next room, mends fast, and understands every
machine she is likely to meet. That is neither a min-max nor a flat spread; it
is a forty-seven-year-old maintenance engineer with a body that has done
twenty-two years of the work, which is the person the dossier describes.

*If the creator's own display disagrees with any number on this page, the
creator is right and this page is wrong: correct it here before the day is
played, never reconcile it afterwards.*
