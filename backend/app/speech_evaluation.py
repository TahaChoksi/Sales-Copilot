"""Word-error counts for explicitly authorised, offline audio evaluation."""

import re


def _words(text: str) -> list[str]:
    # Normalize case/punctuation only. Keep negation and numerical differences.
    return re.findall(r"\w+(?:'\w+)*", text.casefold().replace("’", "'"))


def word_error_counts(reference: str, hypothesis: str) -> dict[str, int | float | None]:
    expected, predicted = _words(reference), _words(hypothesis)
    # Cells hold (distance, substitutions, deletions, insertions). Stable tie
    # breaking prefers substitution, then deletion, then insertion.
    previous = [(i, 0, 0, i) for i in range(len(predicted) + 1)]
    for i, expected_word in enumerate(expected, 1):
        current = [(i, 0, i, 0)]
        for j, predicted_word in enumerate(predicted, 1):
            if expected_word == predicted_word:
                current.append(previous[j - 1])
                continue
            diagonal, above, left = previous[j - 1], previous[j], current[j - 1]
            candidates = [
                (diagonal[0] + 1, diagonal[1] + 1, diagonal[2], diagonal[3]),
                (above[0] + 1, above[1], above[2] + 1, above[3]),
                (left[0] + 1, left[1], left[2], left[3] + 1),
            ]
            current.append(min(candidates, key=lambda item: item[0]))
        previous = current
    distance, substitutions, deletions, insertions = previous[-1]
    return dict(reference_words=len(expected), hypothesis_words=len(predicted),
                substitutions=substitutions, deletions=deletions, insertions=insertions,
                word_error_rate=distance / len(expected) if expected else None)
