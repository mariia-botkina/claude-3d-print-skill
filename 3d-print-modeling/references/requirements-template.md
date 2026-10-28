# REQUIREMENTS.md template

Copy this into the project folder as REQUIREMENTS.md at the start of a project. Write it
in the owner's language. Update it in the same turn whenever something is decided, and
deliver it with every output: the sandbox is wiped between conversations, so this file
(attached again by the owner, or kept in her repo/project files) is how the next session
knows the project.

Every line in "Confirmed" must trace back to something the owner said or chose. Your
guesses live in "Assumptions" until she confirms them.

```markdown
# <Project name>

Status: interview | design | modelling | checking | delivered (v<N>)
Updated: <date>

## Purpose
<one paragraph in the owner's words: what, for whom, where, what success looks like>

## Confirmed requirements
| # | Requirement | Value | Source |
|---|---|---|---|
| R1 | Overall size | max 120 x 80 x 60 mm | said <date> |
| R2 | Material | PLA Basic, white (AMS slot 1) | chose <date> |
| R2a | Nozzle | 0.4 (installed); or 0.2 because <reason> | chose <date> |
| R3 | Fit to phone | 78.1 x 8.2 mm measured, sliding fit | measured <date> |

## Assumptions (unconfirmed)
| # | Assumption | Why it was needed | Ask by |
|---|---|---|---|
| A1 | Textured PEI plate | 3MF needs a plate type | before delivery |

## Decisions log
| Date | Question | Options offered | Chosen |
|---|---|---|---|
| <date> | Lid style | A flat / B domed / C stepped | B |

## Structure
- Parts: <name: purpose, material/colour, print orientation>
- Joints: <how parts connect, fit class, clearance used>
- Plates: <plate name: parts>

## Usability checks (agreed)
| Check | Method | Result v1 | Result v2 |
|---|---|---|---|
| Lifts out with one finger | geometry: 12 mm finger gap | pass | |

## Parameters (in the source file)
| Parameter | Value | Meaning |
|---|---|---|
| wall | 1.6 | wall thickness, mm |

## Open questions
- <question> (blocking? yes/no)

## Versions
- v1 <date>: first full model; check: printable with caveats (overhang under lid rim)
```
