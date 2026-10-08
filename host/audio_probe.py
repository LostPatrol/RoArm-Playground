"""Inspect captured 16kHz PCM WAV levels and optionally run genuine Vosk decoding."""
import argparse
import array
import json
import math
import sys
import wave

from host.worker import mono_pcm


def inspect_audio(filename, model_path=None):
    """Report normalized amplitude, clipping and real decoding without any HTTP."""
    with wave.open(filename, "rb") as wav:
        channels, rate, frames = wav.getnchannels(), wav.getframerate(), wav.getnframes()
        if wav.getsampwidth() != 2 or channels not in (1, 2) or rate != 16000:
            raise ValueError("audio probe needs 16kHz 16-bit mono/stereo PCM")
        pcm = mono_pcm(wav.readframes(frames), channels)
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    count = max(1, len(samples))
    rms = math.sqrt(sum(x*x for x in samples) / count) / 32768
    peak = max((abs(x) for x in samples), default=0) / 32768
    output = {"channels": channels, "sample_rate": rate, "duration_s": frames/rate,
              "rms": rms, "peak": peak, "rms_dbfs": 20*math.log10(rms) if rms else None,
              "clipped_fraction": sum(abs(x) >= 32760 for x in samples)/count,
              "zero_fraction": sum(x == 0 for x in samples)/count}
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
    args = parser.parse_args()
    print(json.dumps(inspect_audio(args.wav, args.model), ensure_ascii=False, indent=2))
