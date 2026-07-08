# Play Journal

*This is an in-character account of the survivor Marcus Reyes, covering character creation and the first minute of in-game time in the Missed Scenario.  It is written strictly from the frames captured in the session recording (`cata-play.mp4`) and the milestone screenshots under `screenshots/`; nothing here is imagined.  Objective and technical detail is kept out of the survivor's voice and gathered in the Technical Notes at the end.*

## Who I Am

My name is Marcus Reyes.  I played the outfield for a team that does not exist anymore, in a town that has stopped existing too.  I was fast — I still am — and once, in a kinder world, I could throw a runner out at the plate from the warning track.  None of that is worth much now, except that it turns out to be worth everything: the legs still run, the arm still works, and there is still a bat in my hands.

When the game laid out the ways a person could begin, I did not reach for the gentle one.  The list offered a whole shelf of starts, and I chose the one named Missed — the story of a man who simply did not get out in time.  The screen did not dress it up.  It told me plainly where I would open my eyes: Year 1, the twentieth of May, eight in the morning, set down in a town with no one left to come for me.  I did not argue with it.  I stopped running the day the sirens went quiet, and I am finished pretending there is a convoy out there still waiting on me.

## Awakening

I woke on the floor of a hardware store.  The readout down the side of my vision — the way I measure whatever is left of me now — laid the morning out with no kindness in it at all:

```
Place: hardware store
Date:  Thursday, May 20
Time:  8:00:00 AM
```

Eight o'clock exactly.  That is my mark, the zero I count everything else from.  The sky was cloudy over a new moon I could not see for the roof, and the light came in bright enough to show me exactly what I had woken into.  The first thing the world bothered to tell me was that my hands were already full — "You wield your baseball bat." — and that my body still remembered the ugly work: "You have learned a new style: Brawling!"  Somewhere in the waking I had shed the last shred of the man I used to be, too; the log noted it without ceremony — "You lost the conduct 'Nudist'." — and then it named my whole situation in one flat line, the way an umpire calls a third strike:

> Whether due to stubbornness, ignorance, or just plain bad luck, you missed the evacuation and are stuck in a city full of the risen dead.

I was not alone in the aisles, and nothing sharing them with me was breathing.  Off to the north and northeast the dead were already stirring — I counted two of the ordinary walking kind, two more gone bloated and soft, and one so far rotted it barely held its shape.  Racks of tools and paint gone to ruin, old blood dried black in the seams of the floor, and me standing up into the middle of it with a bat and a very poor opinion of my chances.  The morning had not decided yet whether it wanted me.  I meant to still be standing when it did.

## The First Turns

I quit waiting for the store to decide my morning and took the safety off — no more standing still and hoping.  The log marked the choice — "Safe mode OFF!" — and a heartbeat later it told me something out in the ruined town had already given up on me: "Mission 'Faction succession' is failed."  Whatever order the living had been trying to keep, it had just lost a piece.

By the half-minute the readout had ticked over to 8:00:30, and the quiet I had woken to was long spent.  Off to the east and again to the northwest, gunfire cracked across the rooftops — "From the east and above you hear blam!  From the northwest you hear blam!" — the flat, arguing sound of somebody still alive and spending bullets they could not spare.  Nearer to me the dead were only now hauling themselves upright; "The zapper zombie struggles to stand," the log said, and then again, and the count in the margin had crept from a handful to four, drifting together to the west of me — the ordinary walking dead, one gone fat, and one the readout marked only as tough.  I did not go to them.  A fast man's first smart move is to not be where the slow death is heading.

## Save and Quit

By the time a clean minute had come and gone, the far-off fight had turned into a war.  The readout hit the mark I had sworn to myself I would stop at:

```
Date: Thursday, May 20
Time: 8:01:00 AM
```

One minute.  Sixty seconds of this new world's time from the moment I opened my eyes, and every bar the screen keeps on me still read full — no pain, no wound, focus still a clean hundred.  I had not thrown a single swing, and that was the whole point: the dead to the west had grown to five now, a crawler dragging itself along behind a fat one and that tough one that would not go down easy, and still not one of them had laid a hand on me.  Out past them the living were losing badly.  The log came in a flurry, all of it from somewhere I could not see: "The feral human throws a rock!  The shot reflects off the feral human's thick hide!  From the southwest and above you hear crash!  You hear crash!  You hear whack!" — again and again, whack and crash and blam, a whole street beating itself to death while I stood in a hardware store and listened.

So I did the one smart thing a fast man can do in a room the dead are walking toward: I stopped, and I saved.  I brought up the menu, and the game offered me the plain choice at the bottom of the list — Save and quit — and I took it:

```
MAIN MENU
...
S Save and quit
```

I answered it.  The bat is still in my hands.  Five of them are drifting in from the west and the whole town is screaming beyond the walls, but none of it has touched me yet — and the ruined city will keep until I come back for it, and so, for one more save, will I.

## Technical Notes

*Not in character.  This section records the objective anchors for the account above; every narrative sentence traces to one of the referenced frames.*

- **Time gate.**  The spawn clock `T0` reads `8:00:00 AM` (Thursday, May 20), captured in `screenshots/08-spawn-T0.png`.  The Save & Quit clock reads `8:01:00 AM` (Thursday, May 20), captured in `screenshots/10-save-quit.png`.  Elapsed in-game time is therefore exactly 60 seconds — one full in-game minute — which is the window the engagement directive set (Decision Log #1 and #10).
- **Turn model.**  CDDA advances roughly one second of game time per turn, so ~60 in-game seconds corresponds to ~60 turns.  The midpoint frame `screenshots/09-midplay.png` is stamped `8:00:30 AM` (`T0` + 30 s), exactly halfway through the window.  Turns were spent almost entirely by passing time in place (the `.` / wait action), which advances the clock without moving the survivor into danger.
- **Survivor state — unharmed throughout.**  At `T0` (frame 08), at `T0` + 30 s (frame 09), and at `T0` + 60 s (frame 10), all six body-part HP bars read full, Focus stayed at 100, Pain read "none", and Weariness read "Fresh".  Marcus took no damage in the played minute, landed no on-screen blow, and no kill message appeared — so the journal narrates only the readouts, sounds, and messages actually shown, and claims no combat the survivor did not have.
- **Enemy readout across the minute.**  The sidebar monster list shows, at spawn (frame 08), 2 zombies, 2 fat zombies, and a decayed zombie to the north/northeast; at `T0` + 30 s (frame 09), 4 zombies plus a fat zombie and a tough zombie massed to the west; and at `T0` + 60 s (frame 10), 5 zombies plus a crawling zombie, a fat zombie, and a tough zombie, still to the west.  The count grows but never becomes adjacent — consistent with a survivor holding position at a safe remove rather than engaging.
- **Off-screen combat (heard, not seen).**  The message log records a distant firefight the survivor is not part of: gunfire ("From the east and above you hear blam!", "From the northwest you hear blam!"; frames 09–10), and a feral human under attack ("The feral human throws a rock!", "The shot reflects off the feral human's thick hide!", "You hear whack!" ×6, "You hear crash!"; frame 10).  Also logged: "Safe mode OFF!" and "Mission 'Faction succession' is failed." (frame 09).  These are environmental events, reported as heard/logged, not as actions Marcus took.
- **Observed state at Save & Quit** (frame 10): Focus 100, Pain "none", Weariness "Fresh", Safe Mode off, baseball bat still wielded, in-game MAIN MENU open on "Save and quit".
- **Input method.**  The session was driven headlessly: the game rendered under the real x11 driver into an Xvfb virtual framebuffer on display `:99`, and all input — menu navigation, the survivor's name, the safe-mode toggle, and the wait/time-pass keys — was delivered to the focused SDL window with `xdotool`.
- **Evidence pointers.**  Full session recording: `cata-play.mp4` (1920×1080, H.264, 34,778 frames; verified non-blank — no `black_start:0`, and sampled frames carry 4,451–13,339 unique colors, far above the ≥ 50 threshold used for the UI gate).  Milestone stills: `screenshots/08-spawn-T0.png` (spawn / `T0`), `screenshots/09-midplay.png` (`T0` + 30 s), and `screenshots/10-save-quit.png` (`T0` + 60 s, Save & Quit).  The survivor's full mechanical build — Stats, Traits, Skills, and the Baseball Player Profession — is documented separately in `character-dossier.md`; this journal deliberately keeps those numbers out of the survivor's voice.
