"""Inspect captured 16kHz PCM WAV levels and optionally run genuine Vosk decoding."""
import argparse
import array
import json
import math
import sys
import wave

from host.worker import mono_pcm


def sample_levels(samples):
    """Describe PCM level without assuming a speaker or microphone distance."""
    count = max(1, len(samples))
    rms = math.sqrt(sum(x*x for x in samples) / count) / 32768
    return {"rms": rms, "peak": max((abs(x) for x in samples), default=0) / 32768,
            "rms_dbfs": 20*math.log10(rms) if rms else None,
            "clipped_fraction": sum(abs(x) >= 32760 for x in samples)/count,
            "zero_fraction": sum(x == 0 for x in samples)/count}


def inspect_audio(filename, model_path=None, skip_seconds=0):
    """Report normalized amplitude, clipping and real decoding without any HTTP."""
    with wave.open(filename, "rb") as wav:
        channels, rate, frames = wav.getnchannels(), wav.getframerate(), wav.getnframes()
        if wav.getsampwidth() != 2 or channels not in (1, 2) or rate != 16000:
            raise ValueError("audio probe needs 16kHz 16-bit mono/stereo PCM")
        wav.setpos(min(frames, int(skip_seconds * rate)))
        raw = wav.readframes(frames)
        pcm = mono_pcm(raw, channels)
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    output = {"channels": channels, "sample_rate": rate, "duration_s": frames/rate,
              "skip_seconds": skip_seconds, **sample_levels(samples)}
    raw_samples = array.array("h", raw)
    if sys.byteorder != "little":
        raw_samples.byteswap()
    output["channel_levels"] = [sample_levels(raw_samples[channel::channels])
                                for channel in range(channels)]
    if channels == 2:
        left, right = raw_samples[::2], raw_samples[1::2]
        energy = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
        output["channel_correlation"] = sum(a*b for a, b in zip(left, right))/energy if energy else None
    if model_path:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        recognizer = KaldiRecognizer(Model(model_path), rate)
        parts = []
        for position in range(0, len(pcm), 3200):
            if recognizer.AcceptWaveform(pcm[position:position+3200]):
                parts.append(json.loads(recognizer.Result()).get("text", ""))
        parts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        output["text"] = "".join(parts).replace(" ", "")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav")
    parser.add_argument("--model")
    parser.add_argument("--skip-seconds", type=float, default=0,
                        help="Exclude startup transient when assessing the steady microphone level")
    args = parser.parse_args()
    if args.skip_seconds < 0:
        parser.error("skip-seconds must be nonnegative")
    print(json.dumps(inspect_audio(args.wav, args.model, args.skip_seconds), ensure_ascii=False, indent=2))
