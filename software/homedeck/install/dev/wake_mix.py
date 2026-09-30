import glob, os, subprocess, numpy as np, openwakeword
from openwakeword.model import Model
res = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
paths = glob.glob(os.path.join(res, "hey_jarvis*.onnx"))
def make():
    try: return Model(wakeword_model_paths=paths)
    except TypeError: return Model(wakeword_models=paths, inference_framework="onnx")
def tts(ph, voice):
    subprocess.run(["/var/lib/homedeck/piper/piper/piper", "--model", voice, "--output_file", "/tmp/wk/m.wav"], input=ph.encode(), capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "/tmp/wk/m.wav", "-ar", "16000", "-ac", "1", "-f", "s16le", "/tmp/wk/m.raw"])
    return np.fromfile("/tmp/wk/m.raw", dtype=np.int16).astype(np.float64)
def score(a):
    a = np.concatenate([np.zeros(16000), a, np.zeros(16000)]).astype(np.int16)
    m = make(); best = 0.0
    for i in range(0, len(a) - 1280, 1280):
        sc = m.predict(a[i:i+1280]); best = max(best, max(float(x) for k, x in sc.items() if k.startswith("hey_jarvis")))
    return best
rng = np.random.default_rng(3)
for voice in sorted(glob.glob("/var/lib/homedeck/piper/*.onnx")):
    for ph in ("Hey Jarvis.", "Jarvis."):
        a = tts(ph, voice) * 0.5
        line = [f"{os.path.basename(voice)[6:12]} {ph:12s} single {score(a):.2f} |"]
        for tau_ms in (3, 20, 40, 80):
            for g in (1.0, 0.3):
                d = int(tau_ms * 16)
                b = np.concatenate([np.zeros(d), a[:-d] if d else a]) * g
                noise = rng.standard_normal(len(a)) * 150
                mix = (a + b) / (1 + g) + noise
                line.append(f"t{tau_ms}g{g}:{score(mix):.2f}")
        print(" ".join(line))
