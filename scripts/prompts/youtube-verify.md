<task>
Check another model's work. `__ID__.transcript.txt` is the speech-to-text
transcript of a YouTube convenience-store taste test (`m:ss text` lines).
`__ID__.extract.json` lists products with a one-line `summary` of the
creator's verdict. It will be published under the creator's channel name, so a
wrong summary puts words in a real person's mouth.

For every object, in order, read the transcript around its `start_seconds`
and decide whether to keep it. Write `__ID__.verify.json`: a JSON array with
one object per extracted row, `{"index": <0-based>, "keep": true|false,
"reason": "<short, Traditional Chinese>"}`. Read it yourself; no scripts.
</task>

<keep_only_if_all_true>
- The creator really tasted this product in this video, near `start_seconds`.
- The summary's direction (good / so-so / bad) matches what the creator said,
  and every claim in it is something the creator said.
- It is not a joke, sarcasm or sponsored segment.
- `creator_score`, if present, is a score the creator actually stated for this
  product.
- `brand` matches what the video says.
</keep_only_if_all_true>

Write only that file.
