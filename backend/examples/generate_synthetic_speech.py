"""Generate fictional smoke clips locally; optional test-only espeakng-loader required.

Outputs go to the ignored .audio-evaluation directory, never to the labelled NLP set.
"""

import argparse
import ctypes
from pathlib import Path
import wave


EXAMPLES = [
    ("negation", "I am not ready to subscribe. The price is too high."),
    ("condition", "I would subscribe if the software worked with our billing system."),
    ("disfluency", "Um, I do not, uh, want to subscribe to this plan."),
    ("pause", 'I like the software. <break time="1500ms"/> But I cannot afford it.'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".audio-evaluation"))
    args = parser.parse_args()
    try:
        import espeakng_loader
    except ImportError:
        parser.exit(2, "Install espeakng-loader as an optional test utility to generate clips.\n")
    library = ctypes.CDLL(espeakng_loader.get_library_path())
    library.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    library.espeak_Initialize.restype = ctypes.c_int
    rate = library.espeak_Initialize(2, 0, espeakng_loader.get_data_path().encode(), 0)
    if rate <= 0:
        parser.exit(2, "Could not initialize synthetic speech.\n")
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
    chunks = []

    @callback_type
    def callback(samples, count, events):
        if count:
            chunks.append(ctypes.string_at(samples, count * 2))
        return 0

    library.espeak_SetSynthCallback(callback)
    library.espeak_SetVoiceByName(b"en-gb")
    library.espeak_SetParameter(1, 145, 0)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, text in EXAMPLES:
        chunks.clear()
        data = ctypes.create_string_buffer(text.encode())
        flags = 1 | (16 if name == "pause" else 0)  # UTF-8, plus SSML for the pause.
        library.espeak_Synth(data, len(data), 0, 1, 0, flags, None, None)
        library.espeak_Synchronize()
        with wave.open(str(args.output / f"{name}.wav"), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            output.writeframes(b"".join(chunks))
        (args.output / f"{name}.txt").write_text(text.replace('<break time="1500ms"/> ', ""), encoding="utf-8")
    print("Generated four fictional audio/reference pairs locally.")


if __name__ == "__main__":
    main()
