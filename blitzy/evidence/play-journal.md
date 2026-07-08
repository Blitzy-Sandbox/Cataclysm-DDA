# Play Journal

*This is an in-character account of the survivor Marcus Reyes, covering character creation and the first minute of in-game time in the Missed scenario.  It is written strictly from the frames captured in the session recording (`cata-play.mp4`) and the milestone screenshots under `screenshots/`; nothing here is imagined.  Objective and technical detail is kept out of the survivor's voice and gathered in the Technical Notes at the end.*

## Who I Am

My name is Marcus Reyes.  I played the outfield for a team that does not exist anymore, in a town that has stopped existing too.  I was fast — I still am — and once, in a kinder world, I could throw a runner out at the plate from the warning track.  None of that is worth much now, except that it turns out to be worth everything: the legs still run, the arm still works, and there is still a bat in my hands.

When the game laid out the ways a person could begin, I did not reach for the gentle one.  The list offered a whole shelf of starts, and I chose the one named Missed — the story of a man who simply did not get out in time.  The screen did not dress it up.  It told me plainly where I would open my eyes: Start of game, Year 1, the twentieth of May, eight in the morning, set down in a town with no one left to come for me.  I did not argue with it.  I stopped running the day the sirens went quiet, and I am finished pretending there is a convoy out there still waiting on me.

## Awakening

I woke in a bookstore.  The readout down the side of my vision — the way I measure whatever is left of me now — laid the morning out with no kindness in it at all:

```
Place: bookstore
Date:  Thursday, May 20
Time:  8:00:00 AM
```

Eight o'clock exactly.  That is my mark, the zero I count everything else from.  A clear sky I could not see for the shelves, a new moon hung somewhere over the ruin, and light coming in bright enough to show me exactly what I had woken into.  The first thing the world bothered to tell me was that my hands were already full — "You wield your baseball bat." — and that my body still remembered the ugly work: "You have learned a new style: Brawling!"  Then it named my whole situation in one flat line, the way an umpire calls a third strike:

> Whether due to stubbornness, ignorance, or just plain bad luck, you missed the evacuation and are stuck in a city full of the risen dead.

I was not alone between those shelves, and nothing sharing them with me was breathing.  They were already stacked up to the northwest, the north, and the west; I felt the weight of them before the margin did my counting for me.  The tally read like a nightmare's roster: a thing on four legs that used to be a dog, seventeen of the walking dead, three more dragging themselves across the floor by their arms, one gone soft with decay, one marked only as tough, and — worst of the lot — one still wearing the shape of a medic.  Books everywhere, knocked from their shelves, and old blood gone black in the gaps between them.  I stood up into the middle of all of it with a bat and a very poor opinion of my chances.

## The First Turns

I quit waiting for the store to decide my morning and started to move.  I let the safety off — no more standing still and hoping — and by the half-minute the readout had already ticked over to 8:00:30, and whatever quiet I had woken to was spent.  Glass came apart somewhere close, crunching and then breaking, a heavy wet whump behind it, and from off to the southeast something screamed the way only the freshly terrified can.  Twice.  The dead do not scream like that.  Someone — or something — was having a far worse morning than mine….

They reached for me, and I gave them nothing to hold.  One threw a hand out and closed it on the air where I had just been; the log put it as plainly as it happened: "The zombie tries to grab you, but you dodge!"  Another raked its claws through the same empty space a breath later: "The zombie claws at you, but you dodge!"  I am not brave — let the record show that much clearly.  I am fast.  This morning that is the whole of the difference between the man writing this and one more shape left cooling on the floor.  Behind the two that missed me the rest were still hauling themselves upright, one after another struggling to stand, and the count in the margin had slipped by one, down to sixteen.

## Save and Quit

By the time a clean minute had come and gone, the morning had started to charge me for it.  The readout hit the mark I had sworn to myself I would stop at:

```
Date: Thursday, May 20
Time: 8:01:00 AM
```

One minute.  Sixty seconds of this new world's time from the moment I opened my eyes.  Fewer of them stood than when I woke — the tally in the margin read twelve where it had read seventeen — but the crowd finally got a hand on me.  "The zombie grabs your torso!"  It was not much, only a minimal ache, the first honest hurt of the day, but a body remembers the first one and knows the next will be worse.  My focus had frayed from a clean hundred down to eighty-six, I was working at the ragged red edge the readout only calls Extreme, and away to the south the dead were wailing and howling like the whole city had finally turned to look for me.

So I did the one smart thing a fast man can do in a room full of slow death: I stopped, and I saved.  I brought up the menu, and the game asked me the plain question, the only one that matters at the end of a turn:

```
Save and quit? (Case Sensitive)   [Y]es  [N]o
```

I answered it.  The bat is still in my hands.  There are still twelve of them standing between me and the door.  But the ruined town will keep until I come back for it, and so — for one more save — will I.

## Technical Notes

*Not in character.  This section records the objective anchors for the account above; every narrative sentence traces to one of the referenced frames.*

- **Time gate.**  The spawn clock `T0` reads `8:00:00 AM` (Thursday, May 20), captured in `screenshots/08-spawn-T0.png`.  The Save & Quit clock reads `8:01:00 AM` (Thursday, May 20), captured in `screenshots/10-save-quit.png`.  Elapsed in-game time is therefore exactly 60 seconds — one full in-game minute — which is the window the engagement directive set (Decision Log #1 and #10).
- **Turn model.**  CDDA advances roughly one second of game time per turn, so ~60 in-game seconds corresponds to ~60 turns.  The midpoint frame `screenshots/09-midplay.png` is stamped `8:00:30 AM` (`T0` + 30 s), exactly halfway through the window.
- **Enemy tally across the minute.**  The sidebar enemy readout shows 17 zombies at `T0` (frame 08), 16 at `T0` + 30 s (frame 09), and 12 at `T0` + 60 s (frame 10), alongside a zombie dog / "rot-weiler", crawling zombies, fat zombies, a decayed zombie, and a zombie medic — a shrinking count consistent with a survivor moving and evading through the crowd rather than standing still.  No on-screen message confirmed a specific kill by the survivor, so none is narrated; the account reports only the readout and the dodges, grabs, and sounds actually shown.
- **Observed state at Save & Quit** (frame 10): Focus 86 (down from 100 at spawn), Activity "Extreme", Pain "Minimal pain", Safe Mode off, baseball bat still wielded.
- **Input method.**  The session was driven headlessly: the game rendered under the real x11 driver into an Xvfb virtual framebuffer on display `:99`, and all input — menu navigation, the survivor's name, movement, and combat keys — was delivered to the focused SDL window with `xdotool`.
- **Evidence pointers.**  Full session recording: `cata-play.mp4` (1920×1080, H.264; verified non-blank — a mid-run frame contains several thousand unique colors, far above the ≥ 50 threshold used for the UI gate).  Milestone stills: `screenshots/08-spawn-T0.png` (spawn / `T0`), `screenshots/09-midplay.png` (`T0` + 30 s), and `screenshots/10-save-quit.png` (`T0` + 60 s, Save & Quit).  The survivor's full mechanical build — Stats, Traits, Skills, and the Baseball Player Profession — is documented separately in `character-dossier.md`; this journal deliberately keeps those numbers out of the survivor's voice.
