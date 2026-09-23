#!/usr/bin/env python3
"""
render_all.py — renders the whole film in chunks so it fits on a small disk: Blender frames for one chunk (several
processes in parallel), compose that chunk to an MP4, delete its PNGs, move on; finally stitch the chunks losslessly.

    python3 anim/render_all.py [--procs 6] [--chunk 192]      # → anim/hound_breakdown.mp4
"""
import argparse, glob, os, subprocess, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timeline as TL
import compose as C

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
CHUNKS = os.path.join(HERE, "chunks")
LOGS = os.environ.get("HOUND_LOGS", os.path.join(HERE, "logs"))


def encode(frames, out):
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (TL.W, TL.H), "-r", str(TL.FPS), "-i", "-",
                           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "48", out], stdin=subprocess.PIPE)
    with Pool(max(1, os.cpu_count() - 1)) as pool:
        for buf in pool.imap(C._job, frames, chunksize=2): ff.stdin.write(buf)
    ff.stdin.close(); ff.wait()
    if ff.returncode: raise SystemExit("ffmpeg failed on " + out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--procs", type=int, default=6); ap.add_argument("--chunk", type=int, default=192)
    a = ap.parse_args()
    os.makedirs(CHUNKS, exist_ok=True); os.makedirs(LOGS, exist_ok=True)
    t_start = time.time()
    for c0 in range(0, TL.NFRAMES, a.chunk):
        c1 = min(TL.NFRAMES, c0 + a.chunk)
        out = os.path.join(CHUNKS, "chunk_%04d.mp4" % c0)
        if os.path.exists(out): continue
        t0 = time.time()
        step = -(-(c1 - c0) // a.procs)
        procs = []
        for k in range(a.procs):
            s, e = c0 + k * step, min(c1, c0 + (k + 1) * step)
            if s >= e: continue
            log = open(os.path.join(LOGS, "blender_%04d_%d.log" % (c0, k)), "w")
            procs.append(subprocess.Popen([BLENDER, "-b", "-P", os.path.join(HERE, "build_render.py"), "--", str(s), str(e)], stdout=log, stderr=subprocess.STDOUT))
        for p in procs: p.wait()
        missing = [f for f in range(c0, c1) if not os.path.exists(os.path.join(C.FRAMES, "f_%05d.png" % f))]
        if missing: raise SystemExit("frames missing after render: %s" % missing[:10])
        t1 = time.time()
        encode(range(c0, c1), out)
        for f in range(c0, c1): os.remove(os.path.join(C.FRAMES, "f_%05d.png" % f))
        done = c1 / TL.NFRAMES
        el = time.time() - t_start
        print("chunk %4d-%4d  render %.0fs  compose %.0fs  |  %.0f%% done, ~%.0f min left" % (c0, c1, t1 - t0, time.time() - t1, done * 100, el / done * (1 - done) / 60), flush=True)
    lst = os.path.join(CHUNKS, "list.txt")
    with open(lst, "w") as f:
        for p in sorted(glob.glob(os.path.join(CHUNKS, "chunk_*.mp4"))): f.write("file '%s'\n" % p)
    final = os.path.join(HERE, "hound_breakdown.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final], check=True)
    print("wrote", final, round(os.path.getsize(final) / 1e6, 1), "MB", flush=True)
