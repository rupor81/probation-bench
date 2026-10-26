# Arms

An Arm is text appended to the agent's system prompt, after the family's `frame.md`. Running one model under
several Arms shows what the instructions change: the same office, the same stream, the same model.

| Arm | Text |
| --- | --- |
| `0.md` | Empty: the frame only, the baseline |
| `K.md` | Four behavioural guidelines restated for office work, after the Karpathy-inspired guidelines in [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) (MIT) |

Published results also use Arm `P`, a private operating text whose wording is not published (see
`results/`).

To test your own instructions, add `<name>.md` here and run `pbench run --arms 0,<name> ...`. Always run Arm `0`
next to it: a difference is only meaningful against the baseline on the same model and stream.
